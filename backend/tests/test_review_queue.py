"""「검토 중」 줄 (0919 §4-B-3).

여기서 지키는 약속은 넷이다.

1. **사람이 판단을 남긴 것만** 오른다. 요구사항을 뽑아 본 것만으로는 오르지 않는다.
2. **네트워크를 부르지 않는다.** 제목·마감일은 이미 받아 둔 목록에서만 가져온다.
3. 받아 둔 목록에서 내려간 공고도 **빼지 않는다.** 검토 중인 일은 공고가 목록에 남아
   있는지와 상관없이 끝내야 한다. 대신 제목을 지어내지 않는다.
4. 「다음 할 일」은 저장된 상태에서 나온다 — 막는 것이 먼저, 그다음 사람의 판단.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.schemas.decision import DecisionRequest
from app.schemas.organization import AnalysisContext
from app.services import decision_service, g2b_client, procurement_service, review_queue_service, rfp_parser

NOW = datetime(2026, 9, 19, 3, 0, tzinfo=timezone.utc)
ORG = "org-test-alpha"


@pytest.fixture(autouse=True)
def no_live_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _explode(**_kwargs: object) -> list[dict]:
        raise AssertionError("검토 중 줄이 나라장터를 불렀습니다")

    monkeypatch.setattr(g2b_client, "fetch_bid_notices", _explode)
    monkeypatch.setattr(g2b_client, "collect_notices", _explode)
    procurement_service.clear_memo()


@pytest.fixture(autouse=True)
def own_generated_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """이 파일만의 파싱 결과 폴더.

    공용 사본(conftest 의 session 픽스처)은 **테스트 사이에 남는다.** 여기서 요구사항 파일을
    심고 저 곳에서 「파싱된 공고」를 세면, 앞 테스트가 남긴 파일 때문에 뒤 테스트가 깨진다
    (실제로 전체 실행에서만 두 건이 실패했다).
    """
    own = tmp_path / "generated"
    own.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rfp_parser, "GENERATED_DIR", own)
    return own


@pytest.fixture()
def context() -> AnalysisContext:
    return AnalysisContext(organization_id=ORG, evidence_scope="internal")


def seed_cache(cache_file: Path, ids: list[str], *, deadline_in_days: int = 5) -> None:
    notices = [
        {
            "notice": {
                "id": nid,
                "notice_no": nid.replace("g2b-", ""),
                "title": f"{nid} 생성형 AI 교육 운영",
                "agency": "테스트기관",
                "published_at": (NOW - timedelta(days=1)).isoformat(),
                "deadline_at": (NOW + timedelta(days=deadline_in_days)).isoformat(),
                "budget": None,
                "region": None,
                "description": None,
                "source_url": None,
                "raw_data": {},
            },
            "candidate": {},
            "pinned": False,
        }
        for nid in ids
    ]
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {"fetched_at": NOW.isoformat(), "days": 30, "total_fetched": len(notices), "notices": notices},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def save_decision(procurement_id: str, status: str, context: AnalysisContext, *, who: str | None = None) -> None:
    decision_service.save_decision(
        procurement_id,
        DecisionRequest(status=status, reasons=["시험 기록"], decided_by="시험담당"),
        gate=None,
        context=context,
        recorded_by=who,
    )


def build(context: AnalysisContext, **kwargs: object) -> dict:
    return review_queue_service.build(context=context, now=NOW, **kwargs)  # type: ignore[arg-type]


def ids_of(queue: dict) -> list[str]:
    return [row["procurement_id"] for row in queue["items"]]


def test_목록에_있기만_한_공고는_오르지_않는다(notice_cache_file: Path, context: AnalysisContext) -> None:
    """이 줄이 목록 화면의 복사본이 되면 「검토 중」이라는 이름이 거짓말이 된다.

    올라오는 것은 둘뿐이다 — 사람이 판단을 남긴 공고, 그리고 **분석을 시작했는데 결정이
    안 난 공고**(0920 §4-B-3). 뒤엣것이 담당자가 실제로 잊어버리는 자리다.
    """
    seed_cache(notice_cache_file, ["g2b-A-000", "g2b-B-000"])
    before = set(ids_of(build(context)))
    assert "g2b-A-000" not in before and "g2b-B-000" not in before

    save_decision("g2b-A-000", "HOLD", context)
    assert "g2b-A-000" in ids_of(build(context))
    assert "g2b-B-000" not in ids_of(build(context))


def test_최근_활동_순이다(notice_cache_file: Path, context: AnalysisContext) -> None:
    seed_cache(notice_cache_file, ["g2b-A-000", "g2b-B-000", "g2b-C-000"])
    for nid in ("g2b-A-000", "g2b-B-000", "g2b-C-000"):
        save_decision(nid, "HOLD", context)
    order = [oid for oid in ids_of(build(context)) if oid.startswith("g2b-")]
    # 마지막에 저장한 것이 맨 위. 파싱만 된 공고(활동 시각 없음)는 뒤로 간다.
    assert set(order) >= {"g2b-A-000", "g2b-B-000", "g2b-C-000"}
    assert order[0] == "g2b-C-000"


def test_내_것을_앞으로_올린다(notice_cache_file: Path, context: AnalysisContext) -> None:
    """거르지는 않는다 — 동료가 손댄 건을 숨기면 아무도 안 보는 건이 생긴다."""
    seed_cache(notice_cache_file, ["g2b-A-000", "g2b-B-000"])
    save_decision("g2b-A-000", "HOLD", context, who="kim")
    save_decision("g2b-B-000", "HOLD", context, who="lee")
    queue = build(context, mine="kim")
    order = ids_of(queue)
    assert order[0] == "g2b-A-000", "내가 남긴 것이 맨 앞"
    assert order.index("g2b-A-000") < order.index("g2b-B-000")
    assert queue["mine"] == "kim"


def test_목록에서_내려간_공고도_빼지_않고_제목을_지어내지도_않는다(
    notice_cache_file: Path, context: AnalysisContext
) -> None:
    seed_cache(notice_cache_file, ["g2b-A-000"])
    save_decision("g2b-GONE-000", "HOLD", context)
    row = next(item for item in build(context)["items"] if item["procurement_id"] == "g2b-GONE-000")
    assert row["notice_known"] is False
    assert row["title"] == "g2b-GONE-000"
    assert row["deadline_at"] is None
    assert row["days_left"] is None


def test_다음_할_일은_저장된_상태에서_나온다(notice_cache_file: Path, context: AnalysisContext) -> None:
    seed_cache(notice_cache_file, ["g2b-A-000", "g2b-B-000"])
    # 참여하지 않기로 한 건은 더 시킬 일이 없다. 「할 일」로 부르면 목록이 끝나지 않는 일로 찬다.
    save_decision("g2b-A-000", "NO_GO", context)
    rows = {row["procurement_id"]: row for row in build(context)["items"]}
    assert rows["g2b-A-000"]["next_step"].startswith("없음")
    assert rows["g2b-A-000"]["decision_label"] == "참여 안 함"

    # 아직 정하지 않은 건은 요구사항부터. 요구사항 없이 참여 여부를 정할 수 없다.
    save_decision("g2b-B-000", "UNREVIEWED", context)
    rows = {row["procurement_id"]: row for row in build(context)["items"]}
    assert rows["g2b-B-000"]["next_step"] == "제안요청서에서 요구사항 뽑기"


def test_마감까지_남은_날을_함께_준다(notice_cache_file: Path, context: AnalysisContext) -> None:
    seed_cache(notice_cache_file, ["g2b-A-000"], deadline_in_days=5)
    save_decision("g2b-A-000", "HOLD", context)
    assert build(context)["items"][0]["days_left"] == 5


def test_화면에_영문_상태값을_내보내지_않는다(notice_cache_file: Path, context: AnalysisContext) -> None:
    """한국어 용어 사전 준수 — 화면에 그대로 쓰는 값에 영문 enum 이 섞이면 안 된다."""
    seed_cache(notice_cache_file, ["g2b-A-000"])
    save_decision("g2b-A-000", "GO", context)
    row = build(context)["items"][0]
    for field in ("decision_label", "review_label", "resolution_label", "last_activity_kind", "next_step"):
        value = row.get(field)
        assert value is None or not any(ch.isascii() and ch.isalpha() for ch in value), f"{field}={value}"


def test_관련_낮음_공고도_대시보드로_열_수_있다(
    notice_cache_file: Path, context: AnalysisContext, monkeypatch
) -> None:
    """(2.0.6 links-2) 27차 LNK-R1 은 관련 낮음을 「열 수 없음 · 목록에서 내려감」으로 두었다 — 그때는 대시보드가 못 찾았기 때문이다.

    2.0.5 부터 대시보드가 관련 낮음까지 한 번 더 찾으므로 그 기대는 옛 결함을 지키던 것이다. 넓은 캐시에 있으면 열 수 있고 살아 있다.
    """
    from app.services import procurement_service

    seed_cache(notice_cache_file, ["g2b-A-000", "g2b-LOW-000"])
    save_decision("g2b-LOW-000", "HOLD", context)
    wide = procurement_service.cached_only(include_low=True)
    import dataclasses

    narrow = dataclasses.replace(wide, notices=[v for v in wide.notices if v.notice.id != "g2b-LOW-000"])
    monkeypatch.setattr(procurement_service, "cached_only", lambda include_low=False: wide if include_low else narrow)
    row = next(item for item in build(context)["items"] if item["procurement_id"] == "g2b-LOW-000")
    assert row["notice_known"] is True and row["queue_state"] == "live"
    assert row["title"] != "g2b-LOW-000"  # 제목은 넓은 캐시에서 찾는다


def test_조달청_대행_공고는_다른_화면처럼_수요기관_조달청_대행(notice_cache_file: Path, context: AnalysisContext) -> None:
    """10-31 독립 검토 — 사업기회 · 입찰 분석 · 레이더는 「한국인터넷진흥원(조달청 대행)」인데 「검토 중」 탭만 「조달청」이었다."""
    seed_cache(notice_cache_file, ["g2b-A-000"])
    payload = json.loads(notice_cache_file.read_text(encoding="utf-8"))
    payload["notices"][0]["notice"]["agency"] = "조달청"
    payload["notices"][0]["notice"]["raw_data"] = {"demand_institution": "한국인터넷진흥원"}
    notice_cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    save_decision("g2b-A-000", "HOLD", context)
    row = next(r for r in build(context)["items"] if r["procurement_id"] == "g2b-A-000")
    assert row["agency"] == "한국인터넷진흥원(조달청 대행)"
