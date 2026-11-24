"""10-31 최종 점검 W5 — 판정 · 셈 규칙 둘. 호출 없음.

① 사업자등록증 업태 · 종목 조항은 나라장터 등록 업종(코드)과 맞추지 않는다 — 「1169 가 있는데 학술연구용역이 없습니다 · 등록 시 가능」이 나왔다.
② 띠 「최근 n일 새 공고」는 원공고 게시일(43차 M2 · 통합 목록과 같은 함수) — 변경공고가 변경 게시일로 섰다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import daily_digest_service, eligibility_engine, g2b_client, notice_version_service, procurement_service, qualification_store

SERVER_LIKE = eligibility_engine.CompanyFacts(location_region="전남광주", registered_industry_codes=("1169", "9999"))


def _industry(text: str) -> eligibility_engine.EligibilityResult:
    clause = eligibility_engine._Clause(id="QC-03", kind="industry", text=text, page=2, origin="입찰공고문", approx=False)
    return eligibility_engine._judge_industry(clause, {}, SERVER_LIKE)


def test_사업자등록증_종목_조항은_확인_필요_사업자등록증에서_확인_등록_권유_없음() -> None:
    row = _industry(
        "사업자등록증상의 업태 또는 종목에 학술연구용역, 연구용역, 교육 관련 연구·자문·평가, 교육컨설팅 등"
        " 본 용역과 관련된 업종이 1개 이상 등록되어 있는 업체"
    )
    assert row.status == "CHECK" and row.check_side == "company"
    assert "사업자등록증 종목에서 확인" in row.reason
    assert "없습니다" not in row.reason  # 거짓 「없다」 없음
    assert row.unlock_options == [] and row.unlock_condition is None  # 「학술연구용역 등록 시 가능」 없음


def test_사업자등록증만_나오는_등록_요건_조항은_예전처럼_업종_대조_등록_권유_유지() -> None:
    """10-31 독립 검토 — 1796954 「사업자등록증을 교부받은 업체로서 … 훈련기관으로 등록된 업체」는 업태 · 종목 조항이 아니라 등록 요건이다.
    「사업자등록증」 낱말만으로 이 갈래로 보내 「등록 시 가능」 안내가 사라졌다."""
    row = _industry("당해 사업에 관한 사업자등록증을 교부받은 업체로서 2026년 직업능력개발 훈련기관(인터넷원격 또는 우편원격)으로 등록된 업체")
    assert "사업자등록증 종목에서 확인" not in row.reason
    assert row.unlock_options or row.unlock_condition


def test_나라장터_등록_업종_조항은_그대로_대조() -> None:
    # 코드가 있거나 나라장터 낱말이 있으면 예전 규칙(등록 업종 대조) 그대로
    assert _industry("나라장터에 학술·연구용역(업종코드 1169)으로 입찰참가자격을 등록한 업체").status == "PASS"
    assert "사업자등록증 종목에서 확인" not in _industry("나라장터 입찰참가자격 등록 및 사업자등록증 종목에 행사대행업을 등록한 업체").reason


# --- ② 띠 새 공고 = 원공고 게시일 ------------------------------------------------

NOW = datetime(2026, 9, 19, 3, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _explode(**_kwargs: object) -> list[dict]:
        raise AssertionError("집계가 나라장터를 불렀습니다")

    monkeypatch.setattr(procurement_service, "_now", lambda: NOW)
    monkeypatch.setattr(g2b_client, "fetch_bid_notices", _explode)
    monkeypatch.setattr(g2b_client, "collect_notices", _explode)
    procurement_service.clear_memo()


def _notice(bid_no: str, order: str, published: datetime) -> dict:
    nid = f"g2b-{bid_no}-{order}"
    return {
        "notice": {
            "id": nid, "notice_no": f"{bid_no}-{order}", "title": f"{nid} 생성형 AI 교육 운영", "agency": "테스트기관",
            "published_at": published.isoformat(), "deadline_at": (NOW + timedelta(days=5)).isoformat(), "budget": None,
            "region": None, "description": None, "source_url": None,
            "raw_data": {"item": {"bidNtceNo": bid_no, "bidNtceOrd": order}},
        },
        "candidate": {},
        "pinned": False,
    }


def test_띠_새_공고는_변경공고를_원공고_게시일로_센다(notice_cache_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kst = timezone(timedelta(hours=9))
    monkeypatch.setattr(
        qualification_store, "first_published_days",
        lambda: {"R26BK0003": (NOW - timedelta(days=2)).astimezone(kst).date(), "R26BK0004": (NOW - timedelta(days=10)).astimezone(kst).date()},
    )
    monkeypatch.setattr(notice_version_service, "load_history", lambda pid: notice_version_service.NoticeVersionHistory(procurement_id=pid, versions=[], changes=[]))
    notices = [
        _notice("R26BK0001", "000", NOW - timedelta(days=1)),  # 원공고 · 어제 → 새 공고
        _notice("R26BK0002", "001", NOW - timedelta(days=1)),  # 변경공고 · 원공고 게시일 모름 → 세지 않음
        _notice("R26BK0003", "001", NOW - timedelta(hours=1)),  # 변경공고 · 원공고 2일 전 → 새 공고
        _notice("R26BK0004", "002", NOW - timedelta(hours=1)),  # 변경공고 · 원공고 10일 전 → 세지 않음
    ]
    notice_cache_file.parent.mkdir(parents=True, exist_ok=True)
    notice_cache_file.write_text(
        json.dumps({"fetched_at": NOW.isoformat(), "days": 30, "total_fetched": len(notices), "notices": notices}, ensure_ascii=False),
        encoding="utf-8",
    )
    digest = asyncio.run(daily_digest_service.build(now=NOW))
    assert digest["new_notices"]["value"] == 2  # 고정 공고(PINNED)는 오래전 게시라 세지 않는다
