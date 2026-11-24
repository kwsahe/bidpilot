"""44차 §2-D — 남은 약속 닫기(M2 · M4 · M5 · M6). 호출 없음(LLM 은 항상 가짜).

- M2 초안 시간 상한은 중계 대기(300초)보다 짧다.
- M4 기업마당 · 직접 넣은 공고에도 결정(입찰 결정과 같은 꼴 · 같은 파일) · 409 · 결정 한 줄이 목록 · 엑셀 · 브리핑에 같은 값.
- M5 AI 가 바꾼 문장은 근거 문장 표지를 그대로 달지 않는다 — 「AI 덧붙임(다듬음 · 원 근거: …)」.
- M6 직접 넣은 공고 「원문 확인함 — 가능으로」 — 누가 · 이유 필수 · 불가 줄이 있으면 거절 · 되돌리기 · 409 · 고치면 풀림.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core import storage
from app.core.config import get_settings
from app.main import app
from app.schemas.business_opportunity import UnifiedOpportunity
from app.schemas.decision import DecisionRequest
from app.schemas.manual_notice import ManualNoticeInput
from app.schemas.organization import AnalysisContext
from app.schemas.proposal import GeneratedSectionDraft, GeneratedSentence
from app.schemas.requirement import Requirement
from app.services import decision_service, llm_client, manual_notice_service, plan_draft_service, proposal_export, proposal_service
from app.services import practical_priority as practical

ORG = get_settings().default_organization_id
KST = timezone(timedelta(hours=9))
CTX = AnalysisContext(organization_id=ORG, evidence_scope="internal")


def test_M2_초안_시간_상한은_중계_대기보다_짧다() -> None:
    assert plan_draft_service.TIME_LIMIT_SECONDS < 300 and proposal_service.PLAN_WRITER_TIME_LIMIT < 300


def test_M4_지원사업_결정은_입찰_게이트_없이_같은_꼴로_저장되고_409() -> None:
    target = "bizinfo-PBLN_000000000999999"
    first = decision_service.save_decision(target, DecisionRequest(status="GO", reasons=["지원 대상이 맞음"], decided_by="대표"), context=CTX)
    assert first.status == "GO" and first.gate is None
    assert decision_service.load_decision(target, CTX).decided_at == first.decided_at
    decision_service.save_decision(target, DecisionRequest(status="HOLD", reasons=["자부담 확인"], decided_by="대표", expected_decided_at=first.decided_at), context=CTX)
    with pytest.raises(storage.StaleWriteError) as caught:
        decision_service.save_decision(target, DecisionRequest(status="NO_GO", reasons=["안 함"], decided_by="김담당", expected_decided_at=first.decided_at), context=CTX)
    assert caught.value.by == "대표"
    assert target in decision_service.decisions_for(CTX)


def _item(**kw) -> UnifiedOpportunity:
    base = dict(
        id="bizinfo-X", source_type="bizinfo", opportunity_type="support_program", title="AI 바우처", agency="기관",
        organization_id=ORG, priority_rank=0, priority_label="검토", confidence="medium", score_components=[],
        next_route={"kind": "support_application", "path": "/", "label": "l"}, source="bizinfo",
    )
    base.update(kw)
    return UnifiedOpportunity(**base)


def test_M4_결정_한_줄은_출처마다_같은_낱말이고_브리핑_엑셀이_같은_값() -> None:
    from app.services import opportunity_brief_service as brief
    from app.services import opportunity_workbook as workbook

    decided = SimpleNamespace(status="NO_GO", decided_by="대표", decided_at=datetime(2026, 10, 24, 3, tzinfo=timezone.utc))
    support = _item()
    assert practical.decision_text(support, decided) == "신청 안 함 · 대표 · 10/24"
    bid = _item(id="g2b-X", source_type="g2b", opportunity_type="procurement", source="g2b")
    assert practical.decision_text(bid, decided) == "참여 안 함 · 대표 · 10/24"
    assert practical.decision_text(bid, None) is None
    support.decision_text = practical.decision_text(support, decided)
    assert brief.verdict_of(support).endswith("결정: 신청 안 함 · 대표 · 10/24")
    assert workbook.practical_cells(support)[-1] == "신청 안 함 · 대표 · 10/24"


def test_M4_API_로_지원사업_결정을_저장한다() -> None:
    client = TestClient(app)
    res = client.put(f"/api/decision/bizinfo-PBLN_000000000777777?organization_id={ORG}",
                     json={"status": "GO", "reasons": ["대상 맞음"], "decided_by": "대표"})
    assert res.status_code == 200 and res.json()["status"] == "GO"
    stale = client.put(f"/api/decision/bizinfo-PBLN_000000000777777?organization_id={ORG}",
                       json={"status": "HOLD", "reasons": ["다시"], "decided_by": "김담당", "expected_decided_at": "2026-01-01T00:00:00Z"})
    assert stale.status_code == 409


def _req(rid: str, text: str) -> Requirement:
    return Requirement(id=f"r-{rid}", procurement_id="synthetic-rfp-0001", requirement_id=rid, category="교육 운영",
                       requirement_type="mandatory", title="교육 운영 횟수", content=text, page=3, source_text=text, status="unmatched")


def test_M5_AI_가_바꾼_문장은_근거_문장_표지를_그대로_달지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    drafts = proposal_service.build_drafts([_req("REQ-001", "교육은 총 12회 운영해야 한다.")], [])
    original = drafts[0].grounding_type
    assert original != "AI_SUGGESTION"
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "complete_structured", lambda **_: GeneratedSectionDraft(sentences=[
        GeneratedSentence(requirement_id="REQ-001", text="교육을 총 12회 운영하겠습니다.", uses_evidence=False, needs_review=False)]))
    assert proposal_service.refine_with_llm(drafts) is True
    assert drafts[0].grounding_type == "AI_SUGGESTION" and drafts[0].refined_from == original
    sentence = SimpleNamespace(grounding_type="AI_SUGGESTION", refined_from=original, needs_review=False)
    assert proposal_export.grounding_label(sentence).startswith("AI 덧붙임(다듬음 · 원 근거: ")
    # 근거 있는 문장만 내려받기에서도 본문에 남는다(표지만 바뀜)
    kept, dropped = proposal_export._split_sentences([sentence], grounded_only=True)
    assert kept == [sentence] and dropped == []


def test_M5_바꾸지_않은_문장은_표지_그대로(monkeypatch: pytest.MonkeyPatch) -> None:
    drafts = proposal_service.build_drafts([_req("REQ-001", "교육은 총 12회 운영해야 한다.")], [])
    same = drafts[0].text
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "complete_structured", lambda **_: GeneratedSectionDraft(sentences=[
        GeneratedSentence(requirement_id="REQ-001", text=same, uses_evidence=False, needs_review=False)]))
    proposal_service.refine_with_llm(drafts)
    assert drafts[0].grounding_type != "AI_SUGGESTION" and drafts[0].refined_from is None


def _manual(**kw) -> ManualNoticeInput:
    base = dict(url="https://www.univ.ac.kr/notice/4406", title="AI 교육 운영 위탁", agency="시험대학",
                deadline=datetime(2026, 11, 30, 16, 0, tzinfo=KST), recruit="bid", methods=["이메일"])
    base.update(kw)
    return ManualNoticeInput(**base)


def test_M6_원문_확인함_가능으로_누가_이유_되돌리기_409_고치면_풀림() -> None:
    notice = manual_notice_service.create(ORG, _manual()).notice
    assert notice is not None
    marked = manual_notice_service.set_human_pass(ORG, notice.id, by="김담당", reason="원문 참가자격 · 지역 확인",
                                                  expected_updated_at=notice.updated_at, gate_now="CHECK")
    assert marked.human_pass is not None and marked.human_pass.by == "김담당"
    assert manual_notice_service.human_pass_reason(marked).startswith("사람 확인 뒤 가능 — 김담당")
    with pytest.raises(storage.StaleWriteError):
        manual_notice_service.set_human_pass(ORG, notice.id, by="대표", reason=None, expected_updated_at=notice.updated_at)
    cleared = manual_notice_service.set_human_pass(ORG, notice.id, by="대표", reason=None, expected_updated_at=marked.updated_at)
    assert cleared.human_pass is None
    again = manual_notice_service.set_human_pass(ORG, notice.id, by="김담당", reason="다시 확인", gate_now="CHECK")
    edited = manual_notice_service.update(ORG, notice.id, _manual(agency="시험대학교"), updated_by="대표", expected_updated_at=again.updated_at)
    assert edited.human_pass is None  # 고친 사실로 다시 확인한다


def test_M6_규칙에_불가_줄이_있으면_거절() -> None:
    notice = manual_notice_service.create(ORG, _manual(url="https://www.univ.ac.kr/notice/4407")).notice
    with pytest.raises(manual_notice_service.HumanPassRefusedError):
        manual_notice_service.set_human_pass(ORG, notice.id, by="김담당", reason="확인", gate_now="FAIL")


def test_M6_사람_확인_뒤_목록_판정은_가능_불가는_그대로() -> None:
    from app.services import organization_service

    notice = manual_notice_service.create(ORG, _manual(url="https://www.univ.ac.kr/notice/4408")).notice
    manual_notice_service.set_human_pass(ORG, notice.id, by="김담당", reason="원문 확인", gate_now="CHECK")
    profile = organization_service.load_profile(ORG)
    now = datetime(2026, 11, 1, 9, tzinfo=KST)
    row = next(i for i in manual_notice_service.unified_items(organization_id=ORG, profile=profile, now=now) if i.id == notice.id)
    assert row.eligibility_gate == "PASS" and row.gate_reason.startswith("사람 확인 뒤 가능 — 김담당")
    later = datetime(2026, 12, 2, 9, tzinfo=KST)  # 마감이 지나면 불가 그대로(사람 확인이 불가를 덮지 않음)
    row = next(i for i in manual_notice_service.unified_items(organization_id=ORG, profile=profile, now=later) if i.id == notice.id)
    assert row.eligibility_gate == "FAIL"


def test_M6_API_편집자만_불가면_422() -> None:
    client = TestClient(app)
    created = client.post(f"/api/manual-notices?organization_id={ORG}", json={
        "url": "https://www.univ.ac.kr/notice/4409", "title": "AI 교육 운영 위탁", "agency": "시험대학",
        "deadline": "2026-11-30T16:00:00+09:00", "recruit": "bid", "methods": ["이메일"]}).json()["notice"]
    res = client.put(f"/api/manual-notices/{created['id']}/human-pass?organization_id={ORG}&expected_updated_at={created['updated_at']}",
                     json={"reason": "원문 확인", "by": "김담당"})
    assert res.status_code == 200 and res.json()["human_pass"]["by"] == "김담당"
    back = client.delete(f"/api/manual-notices/{created['id']}/human-pass?organization_id={ORG}&by=대표")
    assert back.status_code == 200 and back.json()["human_pass"] is None
    empty = client.put(f"/api/manual-notices/{created['id']}/human-pass?organization_id={ORG}", json={"reason": " ", "by": "김담당"})
    assert empty.status_code == 422  # 이유 필수
