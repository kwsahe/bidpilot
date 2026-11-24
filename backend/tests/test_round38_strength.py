"""38차 §3-C — 강점 보이기: 근거 줄 · 조항 파일 Git 밖 · 공고 변경 · 자동 받기 기록 · 회사자료 빈칸 · 브리핑 줄 · 매일 공고문 받기."""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.schemas.business_opportunity import NextRoute, OpportunitySummary, UnifiedOpportunity, UnifiedOpportunityListResponse
from app.services import auto_collect, company_blank_fields, eligibility_engine, notice_version_service
from app.services import opportunity_brief_service as brief
from app.services import practical_priority as practical
from app.services import qualification_clause_service as qc

NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parents[2]


def item(n: int, *, source: str = "g2b", gate: str = "CHECK", unlocks: list[str] | None = None, **extra) -> UnifiedOpportunity:
    fields = dict(
        id=f"{'g2b' if source == 'g2b' else 'bizinfo'}-T{n:03d}", source_type=source,
        opportunity_type="procurement" if source == "g2b" else "support_program", title=f"시험 {n}", agency="시험 기관",
        deadline=NOW + timedelta(days=20), published_at=NOW - timedelta(days=2), detail_url=f"https://example.invalid/{n}",
        organization_id="org-sample", company_priority_score=60, priority_rank=n, source_rank=n, priority_label="검토",
        eligibility_gate=gate, gate_reason="-", confidence="medium", score_components=[],
        next_route=NextRoute(kind="procurement_analysis", path="/", label="입찰 분석 열기"), source="cached",
        unlock_conditions=unlocks or [], fit_type="A1", practical_group="조건부", practical_order=n,
        recruit_kind=practical.RECRUIT_BID if source == "g2b" else practical.RECRUIT_BENEFIT,
    )
    fields.update(extra)
    return UnifiedOpportunity(**fields)


# --------------------------------------------------------------------------
# 근거 줄 · 조항 파일 Git 밖
# --------------------------------------------------------------------------


def test_근거_줄은_쪽_번호와_원문과_조항_번호() -> None:
    payload = {"status": "ok", "page_is_approximate": False, "clauses": [
        {"id": "QC-01", "text": "부정당업자에 해당하지 아니한 자", "page": 1, "kind": "disqualification"},
        {"id": "QC-03", "text": "소프트웨어사업자(컴퓨터관련서비스사업, 업종코드 1468)로 등록한 자", "page": 2, "kind": "industry"},
    ]}
    line, count = qc.evidence_line(payload)
    assert line == "근거: 공고문 p.2 「소프트웨어사업자(컴퓨터관련서비스사업, 업종코드 1468)로 등록한 자」(QC-03)"  # 회사가 갖출 조항 먼저
    assert count == 2


@pytest.mark.parametrize("payload", [None, {"status": "not_fetched", "clauses": []}, {"status": "ok", "clauses": []}])
def test_못_읽었으면_공고문_아직_안_읽음(payload) -> None:
    assert qc.evidence_line(payload) == ("공고문 아직 안 읽음", 0)


def test_매일_받기_조항_파일은_Git_밖에_쓰고_먼저_읽는다(tmp_path, monkeypatch) -> None:
    public, private = tmp_path / "public", tmp_path / "private"
    monkeypatch.setattr(qc, "CLAUSE_DIR", public)
    monkeypatch.setattr(qc, "PRIVATE_CLAUSE_DIR", private)
    qc._MEMO.clear()
    qc.save({"notice_id": "g2b-R26BK00000001-000", "status": "not_fetched", "clauses": []})  # 손으로 받은 옛 파일(공개)
    qc.save({"notice_id": "g2b-R26BK00000001-000", "status": "ok", "clauses": [{"id": "QC-01", "text": "가", "page": 1}]}, private=True)
    assert (public / "g2b-R26BK00000001-000.json").exists() and (private / "g2b-R26BK00000001-000.json").exists()
    assert qc.load("g2b-R26BK00000001-000")["status"] == "ok"  # Git 밖이 이긴다
    assert json.loads((public / "g2b-R26BK00000001-000.json").read_text(encoding="utf-8"))["status"] == "not_fetched"  # 공개 파일은 그대로


# --------------------------------------------------------------------------
# 공고 변경 (지역 뺌)
# --------------------------------------------------------------------------


def test_공고_변경은_마감_첨부_차수_종류만_지역은_뺀다(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(notice_version_service, "VERSION_DIR", tmp_path)
    history = notice_version_service.NoticeVersionHistory(procurement_id="g2b-X-000", versions=[], changes=[
        notice_version_service.NoticeChangeSet(from_version=1, to_version=2, observed_at=NOW - timedelta(days=10), changes=[
            notice_version_service.NoticeChange(field="deadline_at", label="마감일", before="a", after="b")]),
        notice_version_service.NoticeChangeSet(from_version=2, to_version=3, observed_at=NOW - timedelta(days=1), changes=[
            notice_version_service.NoticeChange(field="region", label="지역", before="본사또는참여지사소재지", after="광주"),
            notice_version_service.NoticeChange(field="attachments", label="첨부파일", before=[], after=["정정공고.hwp"]),
            notice_version_service.NoticeChange(field="bidNtceOrd", label="공고 차수", before="000", after="001")]),
    ])
    (tmp_path / "g2b-X-000.versions.json").write_text(history.model_dump_json(), encoding="utf-8")
    assert notice_version_service.notable_changes_since("g2b-X-000", NOW - timedelta(days=7)) == ["첨부", "차수"]
    assert notice_version_service.notable_changes_since("g2b-X-000", None) == ["마감", "첨부", "차수"]
    assert notice_version_service.notable_changes_since("g2b-없음-000", None) == []


# --------------------------------------------------------------------------
# 자동 받기 기록 (FROZEN_TERM 바로잡기)
# --------------------------------------------------------------------------


def _log(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "collect_daily.log"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n잡음 줄\n", encoding="utf-8")
    return path


def test_자동_받기_마지막_성공을_읽는다(tmp_path, monkeypatch) -> None:
    ok = {"시각": (NOW - timedelta(hours=5)).isoformat(), "실행": True, "결과": [{"출처": "나라장터", "결과": "g2b"}]}
    failed = {"시각": (NOW - timedelta(hours=1)).isoformat(), "실행": True, "결과": [{"출처": "나라장터", "오류": "G2BClientError"}]}
    dry = {"시각": NOW.isoformat(), "실행": False}
    monkeypatch.setattr(auto_collect, "LOG_FILE", _log(tmp_path, [ok, failed, dry]))
    assert auto_collect.last_success() == NOW - timedelta(hours=5)
    assert auto_collect.fresh_success(NOW) == NOW - timedelta(hours=5)
    assert auto_collect.fresh_success(NOW + timedelta(hours=50)) is None  # 48시간이 지나면 예전 글(「꺼짐」)


def test_로그가_없으면_None(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(auto_collect, "LOG_FILE", tmp_path / "없음.log")
    assert auto_collect.last_success() is None


# --------------------------------------------------------------------------
# 회사자료 빈칸 안내
# --------------------------------------------------------------------------


def test_빈칸마다_그_칸_때문에_확인_필요로_남은_공고를_센다() -> None:
    company = eligibility_engine.CompanyFacts()
    items = [
        item(1, unlocks=["소프트웨어사업자(컴퓨터관련서비스사업), 1468 등록 시 가능"]),
        item(2, unlocks=["공동수급 파트너 확보 시", "중소기업·소상공인확인서(공공기관 입찰용) 발급 시"]),
        item(3, gate="FAIL", unlocks=["1468 등록 시 가능"]),  # 불가는 세지 않는다
        item(4, unlocks=["1469 등록 시 가능"], closed=True),  # 마감은 세지 않는다
        item(5, source="bizinfo", unlocks=["기업부설연구소 인정을 받으면 가능"]),
    ]
    fields = {f.key: f for f in company_blank_fields.count_fields(items, company)}
    assert fields["registered_industries"].ids == ["g2b-T001"]
    assert fields["joint_bid_partner"].ids == ["g2b-T002"]
    assert fields["sme_certificate"].ids == ["g2b-T002"]
    assert fields["research_department"].ids == ["bizinfo-T005"]
    filled = dataclasses.replace(company, registered_industry_codes=("1468",))
    after = {f.key: f for f in company_blank_fields.count_fields(items, filled)}
    assert after["registered_industries"].blank is False and after["registered_industries"].ids == []  # 채운 칸은 세지 않는다


# --------------------------------------------------------------------------
# 브리핑 줄
# --------------------------------------------------------------------------


def _listing(items: list[UnifiedOpportunity]) -> UnifiedOpportunityListResponse:
    return UnifiedOpportunityListResponse(
        organization_id="org-sample", organization_name="주식회사 샘플에듀", total_count=len(items),
        g2b_count=sum(1 for i in items if i.source_type == "g2b"), bizinfo_count=sum(1 for i in items if i.source_type == "bizinfo"),
        returned_count=len(items), closed_count=0, source_status={}, source_errors={}, fetched_at=NOW,
        summary=OpportunitySummary(open_total=len(items), open_g2b=0, open_bizinfo=0, priority=0, closed=0, closed_pinned=0, days=30, new_days=3),
        sort="practical", ranking_method="practical", field_mapping_verified=True, note="시험", items=items,
        collected_by="공고명 키워드 21개 · 마감 제외 · 최근 30일",
    )


def test_브리핑에_본_것_근거_열기_경로_공고_변경() -> None:
    read = item(1, evidence_line="근거: 공고문 p.2 「1468 등록한 자」(QC-03)", clause_count=7, changed_fields=["마감"])
    unread = item(2, source="bizinfo", evidence_line="공고문 아직 안 읽음")
    body, _ = brief.build_markdown(_listing([read, unread]), now=NOW, previous=None)
    # 39차 PRESPEC-07 — 「마감 전 나라장터」는 입찰만, 사전규격은 따로(전부 · 본업)
    assert "오늘 BidPilot 이 본 것: 나라장터 마감 전 입찰 1건(공고명 낱말 21개) · 사전규격 0건(본업 · 의견 마감 남음 0건) · 발주계획 0건 · 기업마당 1건 전수" in body
    assert "참가자격 조항 7줄" in body
    assert "근거: 공고문 p.2 「1468 등록한 자」(QC-03)" in body  # TOP 상세 · 후보풀
    assert "[BidPilot에서 열기](http" in body and "/analysis?notice=g2b-T001" in body  # 43차 NUM-13 — 「(이 PC)」 없음
    assert "/opportunities?tab=sheet&notice=g2b-T001" in body and "/plan?notice=g2b-T001" in body  # 오늘 실제 행동 경로
    assert "공고 변경(최근 7일) 1건" in body and "(마감)" in body


def test_직접도전_안내는_등록_업종을_적어도_사람_확인이라고_말한다() -> None:
    body, _ = brief.build_markdown(_listing([item(1, unlocks=["1468 등록 시 가능"])]), now=NOW, previous=None)
    line = next(r for r in body.splitlines() if r.startswith("- 매출: 판정 「가능」"))
    # 43차 결정 2 · M7 — 「충족 확인을 골라야」(없는 단추) 대신 실제 길(회사 단위 확인 세 칸)을 말한다
    assert "회사 단위 확인" in line and "충족 확인" not in line
    assert "판정이 정리됩니다" not in line  # DOCS-04 — release · README 와 엇갈리던 글


def test_엑셀_브리핑_시트_메모에도_본_것() -> None:
    _rows, notes = brief.sheet_rows(_listing([item(1)]), now=NOW)
    assert any(n.startswith("오늘 BidPilot 이 본 것") for n in notes)


# --------------------------------------------------------------------------
# 매일 받기 — 나라장터 공고문 단계
# --------------------------------------------------------------------------


def _load_collect_daily():
    """`scripts/collect_daily.py` 를 불러온다 — 그 파일이 import 때 여는 실호출 환경변수(`setdefault`)는 되돌린다."""
    import os

    spec = importlib.util.spec_from_file_location("collect_daily_r38", REPO / "scripts" / "collect_daily.py")
    module = importlib.util.module_from_spec(spec)
    old_argv, old_env = sys.argv, dict(os.environ)
    sys.argv = ["collect_daily.py"]
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    finally:
        sys.argv = old_argv
        for key in set(os.environ) - set(old_env):
            del os.environ[key]
        os.environ.update(old_env)
    return module


def test_공고문_단계는_첨부_내려받기가_꺼져_있으면_받지_않는다(monkeypatch) -> None:
    daily = _load_collect_daily()
    from app.services import attachment_service

    monkeypatch.setattr(attachment_service, "attachment_fetch_enabled", lambda: False)
    row = asyncio.run(daily._collect_g2b_documents(5))
    assert row["건너뜀"] and row["결과"] is None


def test_공고문_단계는_마감_전_후보_조항_없는_것만_회사_방식_순서로_받아_Git_밖에_쓴다(monkeypatch) -> None:
    daily = _load_collect_daily()
    from app.schemas.procurement import ProcurementNotice
    from app.services import attachment_service, opportunity_service, procurement_service

    def notice(no: str) -> ProcurementNotice:
        return ProcurementNotice(id=f"g2b-{no}-000", notice_no=f"{no}-000", title="AI 교육", agency="기관", published_at=NOW,
                                 raw_data={"attachments": [{"name": "입찰공고문.pdf", "url": "https://www.g2b.go.kr/x"}]})

    rows = [
        item(1, id="g2b-R26BK00000001-000"),
        item(2, id="g2b-R26BK00000002-000", closed=True),
        item(3, id="g2b-R26BK00000003-000", relevance_note="본업이 아닌 교육"),
        item(4, id="g2b-R26BK00000004-000"),  # 조항 파일이 이미 있음
        item(5, id="g2b-R26BK01726154-000"),  # 보류 공고
        item(6, id="g2b-R26BK00000006-000"),
    ]

    async def fake_list(**_kwargs):
        return _listing(rows)

    cached = procurement_service.ProcurementResult(
        source="cached", fetched_at=NOW, total_fetched=6,
        notices=[procurement_service.NoticeView(notice=notice(r.id.split("-")[1]), match=None) for r in rows],  # type: ignore[arg-type]
    )
    saved: list[tuple[str, bool]] = []
    downloads: list[str] = []
    monkeypatch.setattr(opportunity_service, "list_opportunities", fake_list)
    monkeypatch.setattr(procurement_service, "load_cache", lambda: cached)
    monkeypatch.setattr(attachment_service, "attachment_fetch_enabled", lambda: True)
    monkeypatch.setattr(attachment_service, "pick_notice_document", lambda attachments: 0)
    monkeypatch.setattr(attachment_service, "cached_attachment", lambda *a: None)

    async def fake_download(url, *, file_name, notice_id, index):
        downloads.append(notice_id)
        return Path("x")

    monkeypatch.setattr(attachment_service, "download_attachment", fake_download)
    monkeypatch.setattr(qc, "load", lambda nid: {"status": "ok"} if nid == "g2b-R26BK00000004-000" else None)
    monkeypatch.setattr(qc, "build_payload", lambda nid, att, **_kw: {"notice_id": nid, "status": "ok", "clauses": [{"id": "QC-01"}]})
    monkeypatch.setattr(qc, "save", lambda payload, private=False: saved.append((payload["notice_id"], private)))
    monkeypatch.setattr(daily, "G2B_DOCUMENT_DELAY", 0)
    row = asyncio.run(daily._collect_g2b_documents(5))
    assert downloads == ["g2b-R26BK00000001-000", "g2b-R26BK00000006-000"]
    assert saved == [("g2b-R26BK00000001-000", True), ("g2b-R26BK00000006-000", True)]  # Git 밖
    assert row["새로_받은_건수"] == 2 and row["조항_줄"] == 2
