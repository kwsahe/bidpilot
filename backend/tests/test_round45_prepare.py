"""45차 — 목록 응답(호출 없음): §2-C M2 「선제준비」 칸 나눠 받기(part=main · folds · 기본 all 그대로) · §2-D M15 「검토 중」 내려간 공고 제목 · 가상 예시 빼기."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.business_opportunity import PrepareSection
from app.services import opportunity_service


def _section() -> PrepareSection:
    # 묶음 건수만 보면 되니 목록 칸은 빈 객체 대신 model_construct 로 가볍게 채운다
    fake = [object()] * 3
    return PrepareSection.model_construct(items=[object()], others=fake, opinion_passed=fake[:2], merged=fake[:1], plans=[], plans_low=0)


@pytest.fixture()
def listing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list(**_: object) -> SimpleNamespace:
        # (2.0.6) 선제준비 응답이 나라장터 오류 칸(source_errors) · 항목(items)도 읽는다 — 실제 목록 응답에는 늘 있는 칸
        return SimpleNamespace(prepare=_section(), source_errors={}, items=[])

    monkeypatch.setattr(opportunity_service, "list_opportunities", fake_list)


def test_M2_main_은_접힌_묶음을_건수로만(listing: None) -> None:
    from app.api import insights

    seen = {
        part: asyncio.run(insights.prepare_section(organization_id=None, evidence_scope=None, part=part))  # type: ignore[arg-type]
        for part in ("main", "folds", "all")
    }
    main = seen["main"]
    assert (main.others, main.opinion_passed, main.merged) == ([], [], [])
    assert (main.others_count, main.opinion_passed_count, main.merged_count) == (3, 2, 1)
    assert len(main.items) == 1
    folds = seen["folds"]
    assert folds.items == [] and len(folds.others) == 3 and folds.others_count is None
    assert len(seen["all"].others) == 3 and seen["all"].others_count is None


def test_M2_잘못된_part_는_422() -> None:
    assert TestClient(app).get("/api/business-opportunities/prepare?part=everything").status_code == 422


def test_M15_내려간_공고는_기록의_제목_가상_예시는_뺌(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timezone

    from app.services import notice_state_service, notice_version_service, review_queue_service

    monkeypatch.setattr(notice_version_service, "VERSION_DIR", tmp_path)
    history = notice_version_service.NoticeVersionHistory(
        procurement_id="g2b-R26BK0000001-000",
        versions=[notice_version_service.NoticeVersion(version=1, observed_at=datetime(2026, 10, 1, tzinfo=timezone.utc), fields={"title": "AI 교육 운영 용역"})],
        changes=[],
    )
    notice_version_service.history_path("g2b-R26BK0000001-000").write_text(history.model_dump_json(), encoding="utf-8")
    assert review_queue_service._fallback_title("g2b-R26BK0000001-000") == ("AI 교육 운영 용역", None)
    assert review_queue_service._test_record("synthetic-rfp-0001", None)
    assert review_queue_service._test_record("g2b-x", "synthetic_ai_training_rfp.pdf")
    assert not review_queue_service._test_record("g2b-x", "제안요청서.hwp")
    monkeypatch.setattr(notice_state_service, "parsed_ids", lambda: {"synthetic-rfp-0001", "g2b-a"})
    monkeypatch.setattr(notice_state_service, "touched_ids", lambda _ctx: {"g2b-b"})
    assert notice_state_service.review_queue_ids(None) == {"g2b-a", "g2b-b"}


def test_M16_발주_예정도_유형_주제_순서_본업_밖은_접음(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timezone

    from app.services import prespec_service

    raws = [
        {"bizNm": "UL인증 컨설팅 반영 50kW급 DAB DC-DC 컨버터 모듈 설계 및 제작 용역", "orderInsttNm": "기관 가", "orderYear": "2026", "orderMnth": "12", "orderPlanUntyNo": "P1"},
        {"bizNm": "2026년 위험성평가 실시 컨설팅", "orderInsttNm": "기관 나", "orderYear": "2026", "orderMnth": "12", "orderPlanUntyNo": "P2"},
        {"bizNm": "생성형 AI 활용 실무교육 운영", "orderInsttNm": "기관 다", "orderYear": "2026", "orderMnth": "12", "orderPlanUntyNo": "P3"},
    ]
    monkeypatch.setattr(prespec_service, "load_order_plans", lambda: (raws, None))
    monkeypatch.setattr(prespec_service, "load_prespecs", lambda: ([], None))
    monkeypatch.setattr(prespec_service, "order_plan_note", lambda: None)
    section = prespec_service.section([], now=datetime(2026, 11, 1, tzinfo=timezone.utc))
    titles = [p.title for p in section.plans]
    assert titles[0] == "생성형 AI 활용 실무교육 운영"  # 주제 맞음 · A1 먼저
    assert "UL인증 컨설팅 반영 50kW급 DAB DC-DC 컨버터 모듈 설계 및 제작 용역" not in titles
    folded = section.plans_folded
    assert [p.fit_type for p in folded] == ["D"] and folded[0].note and "본업 덩어리 밖" in folded[0].note
    consult = next(p for p in section.plans if p.title.startswith("2026년 위험성평가"))
    assert consult.fit_type == "B1" and consult.note and consult.note.startswith("주제 확인")


def test_마지막_검토_다음_할_일은_참여_안_함_보류가_발견보다_먼저() -> None:
    from types import SimpleNamespace as NS

    from app.services import review_queue_service as rq

    assert rq.next_step_of_state(NS(open_findings=61, decision="NO_GO", review=None, parsed=True)).startswith("없음 — 참여 안 함")
    assert rq.next_step_of_state(NS(open_findings=61, decision="GO", review=None, parsed=True)) == "점검에서 고칠 것 61건 처리"
    # 탭 줄 신호(옛 처리 기록 1건)가 있어도 발견 수는 지금 값
    assert rq._with_open_findings({"resolution": {"open_count": 1, "label": "미해결 1건"}}, 61)["resolution"]["open_count"] == 61
    assert rq._with_open_findings({"resolution": {"open_count": 1}}, 0)["resolution"]["open_count"] == 0


def test_마지막_검토_표_파일_칸은_수식으로_읽히지_않음() -> None:
    from app.services.correction_service import _csv_cell

    assert _csv_cell("- 교육은 총 20회") == "'- 교육은 총 20회"
    assert _csv_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)" and _csv_cell("@x") == "'@x" and _csv_cell("+1") == "'+1"
    assert _csv_cell("교육") == "교육" and _csv_cell(17) == 17 and _csv_cell("") == ""
