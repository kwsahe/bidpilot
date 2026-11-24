"""38차 §5 마지막 변경 검토에서 확정한 결함.

- 직접 넣은 공고: 지역 제한 「전국」 · 「제한 없음」은 지역 목록이 아니다(불가가 되던 것) · 수혜 점수도 낮춘 판정으로(D16)
- 연락처: 직접 넣기 공고명 · 기관 · 짧은 칸 · 본문, 붙여넣기 줄을 저장 전에 가린다 · 가려서 길어져도 500 이 아니다
- 후보함: 대기 줄이 상한을 넘어도 처리한 줄을 끝없이 남기지 않는다
- 내보내기: 「=」로 시작하는 제목이 엑셀 수식이 되지 않는다(엑셀 · CSV)
- 브리핑: TOP 자세히 보기의 근거 · 사유 줄 이스케이프
- 접수방식 부정은 괄호에서 끊는다 · 매일 받기는 공고문 첨부가 없는 공고로 하루치 칸을 쓰지 않는다
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.schemas.manual_notice import MAX_BODY, MAX_TITLE, InboxEntry, ManualNoticeInput
from app.services import (
    company_service,
    manual_notice_service as manual,
    notice_inbox_service as inbox,
    opportunity_brief_service as brief,
    opportunity_export_service as export,
    practical_priority as practical,
    procurement_service,
    support_application_service as support,
)
from app.services import qualification_clause_service as qc

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
ORG = get_settings().default_organization_id


@pytest.fixture(autouse=True)
def _private_clauses(tmp_path, monkeypatch):
    monkeypatch.setattr(qc, "PRIVATE_CLAUSE_DIR", tmp_path / "qualification_clauses")
    monkeypatch.setattr(procurement_service, "load_cache", lambda: None)


def _input(**extra) -> ManualNoticeInput:
    data = dict(
        url="https://www.kosac.re.kr/menus/274/bns/PBANC_00000000000514",
        title="교원양성기관 AI 교육과정 개발 컨설팅 수행기관 모집",
        agency="한국과학창의재단",
        deadline=datetime(2026, 10, 28, 16, 0, tzinfo=KST),
        recruit="operator",
    )
    data.update(extra)
    return ManualNoticeInput(**data)


def _items():
    return manual.unified_items(organization_id=ORG, profile=company_service.load_profile(ORG), now=NOW)


@pytest.mark.parametrize("text", ["전국", "제한 없음", "전국 · 제한없음"])
def test_지역_제한_전국은_불가가_아니다(text: str) -> None:
    assert manual._regions(text) == []
    assert manual._regions("광주 · 전남") == ["광주", "전남"]
    manual.create(ORG, _input(region_limit=text), now=NOW)
    [row] = _items()
    assert row.eligibility_gate == "CHECK" and row.gate_reason == manual.NOT_READ_REASON
    assert "거기에 없습니다" not in " ".join(row.checks + row.reasons)


def test_수혜_점수도_낮춘_판정으로_매긴다(monkeypatch) -> None:
    real = support.judge

    def passing(*args, **kwargs):
        import dataclasses

        judged = real(*args, **kwargs)
        return dataclasses.replace(
            judged,
            gate="PASS",
            gate_reason="가능 — 다 맞습니다",
            signals={**judged.signals, "gate": "PASS", "company_match": True},
            components=[c.model_copy(update={"score": 1.0}) if c.key == "eligibility" else c for c in judged.components],
        )

    monkeypatch.setattr(support, "judge", passing)
    manual.create(ORG, _input(recruit="benefit", title="2026 사회적가치지표 측정기업 모집"), now=NOW)
    [row] = _items()
    eligibility = next(c for c in row.score_components if c.key == "eligibility")
    assert row.eligibility_gate == "CHECK"
    assert eligibility.score is not None and eligibility.score < 1.0


def test_직접_넣기_칸의_연락처를_가리고_길어져도_거절은_422_꼴이다() -> None:
    notice = manual.create(
        ORG,
        _input(title="AI 교육(담당 062-123-4567)", agency="재단 kim@foo.or.kr", briefing="설명회 문의 010-1234-5678"),
        now=NOW,
    ).notice
    joined = f"{notice.title} {notice.agency} {notice.briefing}"
    assert "062-123-4567" not in joined and "kim@foo.or.kr" not in joined and "010-1234-5678" not in joined
    # 가린 글은 다시 읽어도 같은 값으로 통과한다(저장본 다시 읽기)
    assert manual.get(ORG, notice.id).title == notice.title
    # 본문 상한 바로 아래 + 메일 주소 → 가리면 길어진다 — 저장 모델에서 500 이 아니라 입력 검증 오류
    with pytest.raises(ValidationError):
        _input(body_text="가" * (MAX_BODY - 7) + " a@b.cd")
    assert len(_input(title="가" * (MAX_TITLE - 20)).title) <= MAX_TITLE


def test_붙여넣기_줄의_연락처를_가리고_전화번호를_날짜로_읽지_않는다() -> None:
    found, _rejected, _without, _truncated = inbox.parse(
        "AI 교육 운영(담당 김OO 062-123-4567, kim@foo.or.kr) [바로가기](https://www.example.go.kr/a?b=1)"
    )
    [row] = found
    assert "062-123-4567" not in row["title"] and "kim@foo.or.kr" not in row["title"]
    assert row["date_text"] is None
    assert row["url"] == "https://www.example.go.kr/a?b=1"


def test_대기_줄이_상한을_넘으면_처리한_줄을_남기지_않는다(monkeypatch) -> None:
    monkeypatch.setattr(inbox, "MAX_ENTRIES", 3)
    rows = [
        InboxEntry(id=f"inbox-{i:012x}", url=f"https://a.kr/{i}", created_at=NOW, line_no=i, status="pending" if i < 4 else "discarded")
        for i in range(6)
    ]
    inbox._save(ORG, rows)
    kept = inbox.load(ORG)
    assert len(kept) == 3 and all(e.status == "pending" for e in kept)


def test_엑셀_CSV_에서_등호로_시작하는_제목은_글이다() -> None:
    assert export._csv_cell("=HYPERLINK(\"https://x\")").startswith("'")
    assert export._csv_cell("+1") == "'+1" and export._csv_cell("@x") == "'@x"
    assert export._csv_cell("-") == "-" and export._csv_cell("AI 교육") == "AI 교육"

    from openpyxl import Workbook, load_workbook

    from app.services import opportunity_workbook as wb

    book = Workbook()
    sheet = book.active
    wb._append(sheet, ["=HYPERLINK(\"https://evil\")", "보통 글"])
    buffer = io.BytesIO()
    book.save(buffer)
    cell = load_workbook(io.BytesIO(buffer.getvalue())).active.cell(row=1, column=1)
    assert cell.data_type == "s" and cell.value.startswith("=HYPERLINK")


def _listing(items):
    from app.schemas.business_opportunity import OpportunitySummary, UnifiedOpportunityListResponse

    return UnifiedOpportunityListResponse(
        organization_id=ORG, organization_name="주식회사 샘플에듀", total_count=len(items), g2b_count=0, bizinfo_count=0,
        manual_count=len(items), returned_count=len(items), closed_count=0, source_status={}, source_errors={}, fetched_at=NOW,
        summary=OpportunitySummary(open_total=len(items), open_g2b=0, open_bizinfo=0, priority=0, closed=0, closed_pinned=0, days=30, new_days=3),
        sort="practical", ranking_method="practical", field_mapping_verified=True, note="시험", items=items,
    )


def test_브리핑_TOP_근거_줄은_이스케이프한다() -> None:
    manual.create(ORG, _input(title="생성형 AI 실무교육 운영 용역", recruit="bid"), now=NOW)
    rows = _items()
    practical.annotate(rows, now=NOW, ceiling_krw=200_000_000)
    practical.order(rows, now=NOW, home_of=lambda i: False)
    [row] = rows
    row.evidence_line = "근거: 공고문 「[x](javascript:alert(1)) *굵게*」"
    row.gate_reason = "확인 필요 — [y](javascript:alert(2))"
    body, _ = brief.build_markdown(_listing(rows), now=NOW, previous=None)
    assert "1순위 —" in body  # TOP 자세히 보기에 올랐다
    assert "[x](javascript" not in body and "[y](javascript" not in body
    assert "\\[x\\](javascript:alert(1)) \\*굵게\\*" in body


def test_접수방식_부정은_괄호에서_끊는다() -> None:
    assert practical.bizinfo_methods("온라인 접수(우편 접수 불가)", None) == [practical.METHOD_ONLINE]
    assert practical.bizinfo_methods("이메일 접수 (방문 접수 불가)", None) == [practical.METHOD_EMAIL]
    assert practical.bizinfo_methods("이메일 접수 불가", None) == [practical.METHOD_UNKNOWN]
    assert practical.bizinfo_methods("방문 · 우편 접수는 받지 않음", None) == [practical.METHOD_UNKNOWN]


def test_매일_받기는_공고문_첨부가_없는_공고로_하루치_칸을_쓰지_않는다(monkeypatch, tmp_path) -> None:
    import importlib.util
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    script = Path(__file__).resolve().parents[2] / "scripts" / "collect_daily.py"
    spec = importlib.util.spec_from_file_location("collect_daily_review", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    from app.services import attachment_service, opportunity_service

    with_doc = [{"name": "입찰공고문.hwp", "url": "https://www.g2b.go.kr/f/1"}]
    without = [{"name": "과업지시서.hwp", "url": "https://www.g2b.go.kr/f/2"}]
    notices = [
        SimpleNamespace(id=f"g2b-R26BK0000000{i}-000", notice_no=f"R26BK0000000{i}-000", raw_data={"attachments": without if i < 3 else with_doc})
        for i in range(5)
    ]
    items = [SimpleNamespace(id=n.id, closed=False, relevance_note=None) for n in notices]

    async def listing(**_kwargs):
        return SimpleNamespace(items=items)

    downloads: list[str] = []

    async def download(url, **_kwargs):
        downloads.append(url)
        raise attachment_service.AttachmentError("시험 — 받지 않음")

    monkeypatch.setattr(attachment_service, "attachment_fetch_enabled", lambda: True)
    monkeypatch.setattr(attachment_service, "cached_attachment", lambda *a, **k: None)
    monkeypatch.setattr(attachment_service, "download_attachment", download)
    monkeypatch.setattr(opportunity_service, "list_opportunities", listing)
    monkeypatch.setattr(module.procurement_service, "load_cache", lambda: SimpleNamespace(notices=[SimpleNamespace(notice=n) for n in notices]))
    monkeypatch.setattr(module, "G2B_DOCUMENT_DELAY", 0)

    import asyncio

    result = asyncio.run(module._collect_g2b_documents(limit=2))
    assert result["공고문_첨부_없음"] == 3 and result["대상"] == 2  # 첨부 없는 셋이 하루치 두 칸을 차지하지 않는다
    assert len(downloads) == 2


def test_레이더는_사전규격과_나라장터_관련_낮음을_빼고_자른다(monkeypatch) -> None:
    """L2 사본: 레이더가 받은 200건 중 76건이 사전규격(실무순 T3)이라 그려지는 입찰 공고가 124건이었다."""
    import asyncio

    from app.schemas.business_opportunity import NextRoute, UnifiedOpportunity
    from app.schemas.organization import AnalysisContext
    from app.services import opportunity_service

    def row(i: int, kind: str) -> UnifiedOpportunity:
        return UnifiedOpportunity(
            id=(f"g2bpre-R26BD0000000{i}" if kind == "pre_spec" else f"g2b-R26BK0000000{i}-000"), source_type="g2b",
            opportunity_type=kind, title=f"생성형 AI 교육 {i}", agency="기관", organization_id=ORG, priority_rank=i,
            priority_label="검토", eligibility_gate="CHECK", confidence="medium", score_components=[],
            next_route=NextRoute(kind="procurement_analysis", path="/", label="열기"), source="cached",
        )

    rows = [row(i, "pre_spec") for i in range(3)] + [row(i, "procurement") for i in range(3, 6)]
    rows.insert(3, row(9, "procurement").model_copy(update={"relevance_note": "본업이 아닌 교육 — 「안전교육」"}))

    async def collect(**_kwargs):
        return list(rows), "cached", None, None

    monkeypatch.setattr(opportunity_service, "_collect_procurements", collect)
    ctx = AnalysisContext(organization_id=ORG, evidence_scope="internal")
    full = asyncio.run(opportunity_service.list_opportunities(context=ctx, source="g2b", limit=3, sort="priority", now=NOW))
    bids = asyncio.run(opportunity_service.list_opportunities(context=ctx, source="g2b", limit=3, sort="priority", now=NOW, for_radar=True))
    assert bids.returned_count == 3 and all(i.opportunity_type == "procurement" for i in bids.items)
    assert full.g2b_count == 4 and bids.g2b_count == 3  # 레이더의 분모는 그릴 수 있는 수 · 사전규격은 39차부터 목록 밖(결정 1)
    assert not any(i.opportunity_type == "pre_spec" for i in full.items)
    assert [i.source_rank for i in bids.items] == [1, 2, 3]  # 순번도 그릴 것끼리
