"""AI Auditor 테스트.

- 네트워크는 conftest가 막는다. LLM은 전부 monkeypatch한다 (실호출 없음).
- 검사 대상은 저장소에 커밋된 합성 RFP 파싱 결과(synthetic-rfp-0001, 필수 23건)다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auditor as auditor_api
from app.schemas.audit import AuditRun
from app.schemas.requirement import Requirement
from app.services import auditor_service, llm_client, rfp_parser

PROCUREMENT_ID = "synthetic-rfp-0001"

# 요구사항을 대체로 충족하는 최소 초안 (테스트마다 필요한 문장만 덧붙인다)
BASE_DRAFT = "\n".join(
    [
        "교육은 총 12회 운영하며 회차당 교육시간은 3시간으로 편성한다.",
        "매 회차 종료 직후 만족도 조사를 실시하고 전체 참석자 대비 응답률 80% 이상을 확보한다.",
        "제안서에는 사업수행계획, 투입인력표, 유사사업 실적증명, 개인정보 보호계획, 가격제안서를 모두 포함하여 제출한다.",
    ]
)


@pytest.fixture(autouse=True)
def audit_run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """검사 결과 저장 경로를 tmp로 돌린다 (저장소 data/를 건드리지 않는다)."""
    target = tmp_path / "audit_runs"
    monkeypatch.setattr(auditor_service, "AUDIT_RUN_DIR", target)
    return target


@pytest.fixture(autouse=True)
def no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """기본은 LLM 미설정 상태 — 규칙 계층만으로 완전한 결과가 나와야 한다."""
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)


@pytest.fixture(scope="module")
def requirements() -> dict[str, Any]:
    parsed = rfp_parser.load_generated(PROCUREMENT_ID)
    return {req.requirement_id: req for req in parsed.requirements}


def find(run: AuditRun, finding_type: str, requirement_id: str | None = None) -> list[Any]:
    return [
        finding
        for finding in run.findings
        if finding.finding_type == finding_type
        and (requirement_id is None or finding.requirement_id == requirement_id)
    ]


# ---------------------------------------------------------------------------
# 문장 분리
# ---------------------------------------------------------------------------


def test_split_sentences_splits_on_korean_endings_and_newlines() -> None:
    text = "교육은 총 12회 운영한다. 보조인력을 배치함.\n주간보고를 제출함.\n\n최종보고서를 제출임."
    sentences = auditor_service.split_sentences(text)

    assert [s.text for s in sentences] == [
        "교육은 총 12회 운영한다.",
        "보조인력을 배치함.",
        "주간보고를 제출함.",
        "최종보고서를 제출임.",
    ]
    assert [s.id for s in sentences] == ["S-001", "S-002", "S-003", "S-004"]
    assert [s.index for s in sentences] == [0, 1, 2, 3]


def test_split_sentences_keeps_line_without_terminator() -> None:
    sentences = auditor_service.split_sentences("- 교육 운영계획\n- 보안 관리방안")
    assert [s.text for s in sentences] == ["- 교육 운영계획", "- 보안 관리방안"]


def test_split_sentences_does_not_break_decimal_numbers() -> None:
    sentences = auditor_service.split_sentences("교육 만족도는 4.5점 이상을 목표로 한다.")
    assert len(sentences) == 1


def test_empty_proposal_raises() -> None:
    with pytest.raises(auditor_service.EmptyProposalError):
        auditor_service.run_audit(PROCUREMENT_ID, "   \n \n ")


# ---------------------------------------------------------------------------
# Tier 1 규칙
# ---------------------------------------------------------------------------


def test_missing_requirement_quotes_rfp_page_and_source_text(requirements: dict[str, Any]) -> None:
    """만족도 조사 문장을 뺀 초안 → REQ-015 누락. 근거는 요구사항 원문 그대로여야 한다."""
    draft = "\n".join(line for line in BASE_DRAFT.split("\n") if "만족도" not in line)
    run = auditor_service.run_audit(PROCUREMENT_ID, draft)

    findings = find(run, "missing_requirement", "REQ-015")
    assert findings, "만족도 조사 요구사항 누락을 찾지 못했다"
    finding = findings[0]
    assert finding.severity == "high"
    assert finding.detected_by == "RULE"
    assert finding.source_page == requirements["REQ-015"].page
    assert finding.source_text == requirements["REQ-015"].source_text
    assert str(requirements["REQ-015"].page) in finding.recommendation
    assert "REQ-015" in run.coverage.missing_requirement_ids


def test_app_export_annotations_are_not_draft_text(requirements: dict[str, Any]) -> None:
    """11-01 — 앱이 내려 준 제안서 워드에는 문장마다 「[공고문 근거] 제안요청서 n쪽 · n번 요구사항 “원문”」 줄이 붙는다.
    그대로 검사하면 그 원문 인용이 지운 대응 문장 대신 「반영」이 되고, 쪽 번호(57쪽)가 근거 없는 숫자로 잡혔다."""
    req = requirements["REQ-015"]
    lines = [line for line in BASE_DRAFT.split("\n") if "만족도" not in line]
    draft = "\n".join(
        [
            "제안서 초안 — 시험 공고",
            "원문  제안요청서.pdf (pdf, 57쪽)",
            "섹션 2개  ·  필수 요구사항 3건 중 대응 3건  ·  회사 근거 0  ·  공고문 근거 0  ·  확인 필요 1",
            "요구사항 카테고리: 과업내용",
            *[f"{i}. {line}" for i, line in enumerate(lines, start=1)],
            f"[AI 덧붙임(다듬음 · 원 근거: 공고문 근거)] 제안요청서 57쪽 · 15번 요구사항 “{req.source_text}”",
            "확인 필요 — 채택된 회사 근거자료가 없습니다.",
            f"제안요청서 {req.page}쪽 · 15번 요구사항 · 과업내용  “{req.source_text}”",
            "BidPilot AI · 근거는 제안요청서 원문과 회사 근거자료에서 그대로 인용했습니다. 원문에 없는 내용은 생성하지 않았습니다.",
        ]
    )
    run = auditor_service.run_audit(PROCUREMENT_ID, draft)

    assert "REQ-015" in run.coverage.missing_requirement_ids
    assert all("57" not in (finding.proposal_text or "") for finding in find(run, "unsupported_claim"))
    # 같은 꼴의 사람이 쓴 문장은 그대로 검사한다(지우는 것은 앱 표기 줄만)
    kept = auditor_service.strip_app_annotations("1. 당사는 제안요청서 요구사항에 맞춰 교육을 운영합니다.")
    assert kept.strip() == "1. 당사는 제안요청서 요구사항에 맞춰 교육을 운영합니다."


def test_real_export_round_trip_core_docx_and_text(requirements: dict[str, Any]) -> None:
    """독립 검토 — 손으로 쓴 줄 말고 앱의 실제 내려받기(핵심 섹션 워드 · 텍스트 판)를 그대로 점검에 넣는다.
    텍스트 판의 「- 제안요청서 …」 목록 줄 · 「필수 요구사항 n건 중 대응 n건」 · 「※ 이 문서는 …」 · 「※ 추출 상한 …」 ·
    「n건입니다. 제안서 본문에 추가할지 …」 줄이 남아 있었다."""
    import io

    from docx import Document as DocxDocument

    from app.schemas.proposal import ProposalSection, ProposalSentence
    from app.services import proposal_export

    lines = [line for line in BASE_DRAFT.split("\n") if "만족도" not in line]
    sentences = [
        ProposalSentence(id=f"PS-{i}", text=line, grounding_type="RFP_GROUNDED", requirement_id="REQ-002" if i == 1 else None)
        for i, line in enumerate(lines, start=1)
    ]
    sentences.append(ProposalSentence(id="PS-9", text="당사는 보안 서약을 따르겠습니다.", grounding_type="AI_SUGGESTION",
                                      requirement_id="REQ-002", needs_review=True))
    section = ProposalSection(
        id="PROP-rt", title="사업수행계획 (핵심 섹션)", sentences=sentences, procurement_id=PROCUREMENT_ID,
        mandatory_total=23, requirements_with_sentence=3, requirements_without_sentence=["REQ-015"],
        evidence_grounded_count=0, rfp_grounded_count=2, needs_review_count=1,
    )
    parsed = rfp_parser.load_generated(PROCUREMENT_ID).model_copy(update={"truncated": True, "candidate_count": 99})
    text = proposal_export.build_text(section, parsed, notice_line="시험 공고").decode("utf-8")
    document = DocxDocument(io.BytesIO(proposal_export.build_document(section, parsed, notice_line="시험 공고")))
    docx_text = "\n".join(p.text for p in document.paragraphs)
    for label, draft in (("텍스트", text), ("워드", docx_text)):
        run = auditor_service.run_audit(PROCUREMENT_ID, draft)
        assert "REQ-015" in run.coverage.missing_requirement_ids, label
        leaked = [f.proposal_text for f in find(run, "unsupported_claim") if f.proposal_text and not re.match(r"\s*\d+\.\s", f.proposal_text)]
        assert leaked == [], (label, leaked)


def test_unmatched_quote_in_annotation_does_not_eat_next_sentence(requirements: dict[str, Any]) -> None:
    """독립 검토 — 원문을 자른 인용에 짝 없는 「“」가 남으면(3순위 공고 188번) 다음 본문 문장까지 지워 「누락」이 났다."""
    draft = "\n".join(
        [
            "1. 교육은 총 12회 운영하며 회차당 교육시간은 3시간으로 편성한다.",
            "   [공고문 근거] 제안요청서 34쪽 · 188번 요구사항 “- 팀장은 완벽해야 한다는 강박과 “내가 다 책임”",
            "2. 매 회차 종료 직후 만족도 조사를 실시하고 전체 참석자 대비 응답률 80% 이상을 확보한다.",
            "3. 제안서에는 사업수행계획, 투입인력표, 유사사업 실적증명, 개인정보 보호계획, 가격제안서를 모두 포함하여 제출한다.",
        ]
    )
    run = auditor_service.run_audit(PROCUREMENT_ID, draft)
    assert "REQ-015" not in run.coverage.missing_requirement_ids


def test_number_mismatch_uses_text_match_reason() -> None:
    """12회 요구를 10회로 쓴 초안 → number_mismatch(high)."""
    draft = BASE_DRAFT.replace("총 12회", "총 10회")
    run = auditor_service.run_audit(PROCUREMENT_ID, draft)

    findings = find(run, "number_mismatch", "REQ-002")
    assert findings
    finding = findings[0]
    assert finding.severity == "high"
    assert "12회" in finding.recommendation and "10회" in finding.recommendation
    assert finding.proposal_text is not None and "10회" in finding.proposal_text


def test_number_within_at_least_bound_is_not_flagged() -> None:
    """'240명 이상' 요구에 260명으로 답하면 위반이 아니다."""
    draft = (
        BASE_DRAFT
        + "\n전체 교육대상은 누적 260명으로 계획하고 회차별 명단과 실제 참석인원을 구분해 관리한다."
    )
    run = auditor_service.run_audit(PROCUREMENT_ID, draft)
    assert find(run, "number_mismatch", "REQ-003") == []


def test_unsupported_claim_flags_number_absent_from_rfp() -> None:
    draft = BASE_DRAFT + "\n당사는 교육 만족도 95% 이상을 보장합니다."
    run = auditor_service.run_audit(PROCUREMENT_ID, draft)

    findings = find(run, "unsupported_claim")
    assert findings
    finding = findings[0]
    assert finding.severity == "medium"
    assert finding.proposal_text is not None and "95%" in finding.proposal_text
    assert finding.requirement_id is None
    # 근거 없는 주장은 RFP 원문을 인용하지 않는다 (없는 페이지를 만들지 않는다).
    assert finding.source_page is None and finding.source_text is None


def test_rfp_number_reused_in_draft_is_not_unsupported() -> None:
    """RFP에 있는 수치(80%)를 인용한 문장은 근거 없는 주장이 아니다."""
    run = auditor_service.run_audit(PROCUREMENT_ID, BASE_DRAFT)
    claims = find(run, "unsupported_claim")
    assert all("80%" not in (finding.proposal_text or "") for finding in claims)


def test_missing_document_names_the_missing_ones() -> None:
    """제출서류 목록(REQ-021)에서 '가격제안서'를 빠뜨린 초안."""
    draft = BASE_DRAFT.replace(", 가격제안서", "")
    run = auditor_service.run_audit(PROCUREMENT_ID, draft)

    findings = find(run, "missing_document", "REQ-021")
    assert findings
    assert findings[0].severity == "high"
    assert "가격제안서" in findings[0].recommendation


def test_extract_document_names_splits_list() -> None:
    names = auditor_service.extract_document_names(
        "제안서에는 사업수행계획, 투입인력표, 유사사업 실적증명, 보안·개인정보 보호계획, "
        "가격제안서를 모두 포함해야 한다."
    )
    assert "사업수행계획" in names
    assert "투입인력표" in names
    assert "가격제안서" in names
    # 두 글자짜리 조각("보안")은 서류명으로 보지 않는다 (오탐 방지)
    assert "보안" not in names


def test_requirement_with_multiple_values_for_one_unit_asks_a_human() -> None:
    """실제 공고 요구사항처럼 같은 단위로 여러 기준(3년/7년)이 있으면 단정하지 않는다."""
    real_id = "g2b-R26BK01687776-000"
    try:
        parsed = rfp_parser.load_generated(real_id)
    except rfp_parser.RfpNotParsedError:  # pragma: no cover - 파싱 결과가 없는 환경
        pytest.skip("실제 공고 파싱 결과가 없다")

    # REQ 번호는 추출기가 바뀌면 밀리므로 내용으로 찾는다.
    target = next(
        (r for r in parsed.requirements if "3년" in r.content and "7년" in r.content),
        None,
    )
    if target is None:  # pragma: no cover - 해당 요구사항이 사라진 경우
        pytest.skip("3년/7년 두 기준을 가진 요구사항이 없다")

    draft = "최근 3년 이내 완료한 유사 과업의 수행실적 총괄표와 수행실적증명서를 함께 제출합니다."
    run = auditor_service.run_audit(real_id, draft)

    findings = find(run, "number_mismatch", target.requirement_id)
    assert findings, "3년/7년 수치 차이를 잡지 못했다"
    finding = findings[0]
    assert finding.severity == "medium"  # 단정하지 않고 사람 확인으로 넘긴다
    assert "확인" in finding.recommendation


def test_values_by_unit_groups_numbers() -> None:
    values = auditor_service._values_by_unit("최근 3년 이내 실적, 단 최근 7년 이내 240명 이상")
    assert values["년"] == {3.0, 7.0}
    assert values["명"] == {240.0}


def test_check_requirement_asserted_as_satisfied_becomes_unchecked_condition() -> None:
    draft = (
        BASE_DRAFT
        + "\n총괄책임자는 관련 분야 경력 3년 이상이며 최근 3년 이내 공공기관 AI 교육 유사사업 "
        "3건 이상 수행 경험을 보유한다."
    )
    run = auditor_service.run_audit(PROCUREMENT_ID, draft)

    findings = find(run, "unchecked_condition", "REQ-011")
    assert findings
    assert findings[0].severity == "medium"
    assert "증빙" in findings[0].recommendation
    state = next(s for s in run.requirement_states if s.requirement_id == "REQ-011")
    assert state.status == "check"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 충족 주장 — 잡는다
        ("공공기관 대상 AI 교육 실적 3건을 보유하고 있습니다.", True),
        ("최근 3년 이내 유사사업 3건 이상 수행 경험을 보유한다.", True),
        ("자격요건을 충족하는 전문인력을 투입하겠습니다.", True),
        ("당사는 공공기관 대상 AI 교육 실적이 있습니다.", True),
        # 「않도록」은 목적이지 부정이 아니다 — 단정 그대로
        ("교육 일정에 차질이 생기지 않도록 자격요건을 충족하는 전담 인력을 배치하겠습니다.", True),
        # 미확인 · 부정 · 일반 약속 — 단정이 아니다 (P1-04)
        ("수행 경험 요건의 충족 여부를 확정할 수 없습니다. 확인 필요.", False),
        ("수행 경험 요건의 충족 여부를 확정할 수 없습니다.", False),
        ("요건 충족 여부는 확인이 필요합니다.", False),
        ("실적이 있는지 확인할 필요가 있습니다.", False),
        ("제안된 내용을 충족시키지 못한 경우 계약파기를 할 수 있으며,", False),
        ("당사는 해당 인증을 보유하지 않습니다.", False),
        ("교육 종료 후 만족도 조사를 실시하겠습니다.", False),
        ("작성지침의 작성항목 순서를 준수하겠습니다.", False),
        ("지적 사항은 즉시 수정‧보완하겠습니다.", False),
    ],
)
def test_asserts_fulfillment_only_for_fulfillment_claims(text: str, expected: bool) -> None:
    assert auditor_service.asserts_fulfillment(text) is expected


def test_reserved_sentence_without_tail_is_not_unchecked_condition() -> None:
    """꼬리 「확인 필요.」가 없는 유보 문장도 「원문 확인 필요 — 초안이 충족을 단정함」으로 잡지 않는다 (P1-04)."""
    draft = (
        BASE_DRAFT
        + "\n총괄책임자의 관련 분야 경력 3년 이상과 최근 3년 이내 공공기관 AI 교육 유사사업 "
        "3건 이상 수행 경험은 충족 여부를 확정할 수 없습니다."
    )
    run = auditor_service.run_audit(PROCUREMENT_ID, draft)
    assert find(run, "unchecked_condition") == []


def test_coverage_and_counts_are_computed(requirements: dict[str, Any]) -> None:
    run = auditor_service.run_audit(PROCUREMENT_ID, BASE_DRAFT)
    mandatory = [r for r in requirements.values() if r.requirement_type == "mandatory"]

    assert run.coverage.total == len(mandatory)
    assert run.coverage.covered + run.coverage.partial + run.coverage.missing == run.coverage.total
    assert run.coverage.covered >= 1
    assert sum(run.counts.values()) == len(run.findings)
    assert len(run.requirement_states) == len(mandatory)
    assert {finding.id for finding in run.findings} == {
        f"AF-{i:03d}" for i in range(1, len(run.findings) + 1)
    }


def test_findings_never_invent_evidence(requirements: dict[str, Any]) -> None:
    """모든 finding의 페이지·원문은 요구사항에서 그대로 왔거나 비어 있어야 한다."""
    run = auditor_service.run_audit(PROCUREMENT_ID, BASE_DRAFT + "\n임의로 20억원을 절감합니다.")
    for finding in run.findings:
        if finding.requirement_id is None:
            assert finding.source_text is None
            continue
        requirement = requirements[finding.requirement_id]
        assert finding.source_page == requirement.page
        assert finding.source_text == requirement.source_text
    sentence_texts = {sentence.text for sentence in run.sentences}
    for finding in run.findings:
        if finding.proposal_text is not None:
            assert finding.proposal_text in sentence_texts


def test_audit_is_deterministic_without_llm() -> None:
    first = auditor_service.run_audit(PROCUREMENT_ID, BASE_DRAFT)
    second = auditor_service.run_audit(PROCUREMENT_ID, BASE_DRAFT)
    assert first.model_dump(exclude={"id", "created_at"}) == second.model_dump(
        exclude={"id", "created_at"}
    )


def test_unknown_procurement_id_rejected() -> None:
    with pytest.raises(rfp_parser.RfpFixtureNotFoundError):
        auditor_service.run_audit("../../etc/passwd", BASE_DRAFT)


# ---------------------------------------------------------------------------
# Tier 2 (LLM) — 전부 monkeypatch, 실호출 없음
# ---------------------------------------------------------------------------


def _drop_satisfaction_sentence() -> str:
    return "\n".join(line for line in BASE_DRAFT.split("\n") if "만족도" not in line)


def _fake_llm(covered_ids: set[str], sentence_index: int | None = 0):
    """프롬프트에 실린 요구사항 ID를 읽어 그대로 답하는 가짜 LLM."""

    def _call(*, system: str, user: str, schema: Any, temperature: float = 0.0) -> Any:
        ids = re.findall(r"REQ-\d{3}", user)
        return schema(
            items=[
                {
                    "requirement_id": req_id,
                    "covered": req_id in covered_ids,
                    "matched_sentence_index": sentence_index if req_id in covered_ids else None,
                    "reason": "표현이 다르지만 같은 내용을 다루고 있음"
                    if req_id in covered_ids
                    else "초안에 대응 문장이 없음",
                }
                for req_id in dict.fromkeys(ids)
            ]
        )

    return _call


def test_llm_covered_drops_missing_finding_and_marks_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "complete_structured", _fake_llm({"REQ-015"}))

    run = auditor_service.run_audit(PROCUREMENT_ID, _drop_satisfaction_sentence())

    assert find(run, "missing_requirement", "REQ-015") == [] or all(
        f.severity == "low" for f in find(run, "missing_requirement", "REQ-015")
    )
    assert "REQ-015" not in run.coverage.missing_requirement_ids
    state = next(s for s in run.requirement_states if s.requirement_id == "REQ-015")
    assert state.status == "partial"
    assert state.method == "AI_EXTRACTION"
    assert state.reason == "표현이 다르지만 같은 내용을 다루고 있음"
    assert run.llm_used is True


def test_llm_not_covered_keeps_finding_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "complete_structured", _fake_llm(set()))

    run = auditor_service.run_audit(PROCUREMENT_ID, _drop_satisfaction_sentence())

    findings = find(run, "missing_requirement", "REQ-015")
    assert findings
    assert findings[0].severity == "high"
    assert findings[0].detected_by == "AI_EXTRACTION"
    assert "초안에 대응 문장이 없음" in findings[0].recommendation


def test_llm_failure_falls_back_to_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """키가 있어도 호출이 실패하면 규칙 결과가 그대로 나와야 한다 (데모가 죽지 않는다)."""

    def _boom(**kwargs: Any) -> Any:
        raise llm_client.LLMUnavailableError("네트워크 실패")

    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "complete_structured", _boom)

    run = auditor_service.run_audit(PROCUREMENT_ID, _drop_satisfaction_sentence())

    assert run.llm_used is False
    assert run.llm_note is not None and "LLM" in run.llm_note
    assert find(run, "missing_requirement", "REQ-015")
    assert run.coverage.total > 0


def test_llm_hallucinated_requirement_id_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    def _call(*, system: str, user: str, schema: Any, temperature: float = 0.0) -> Any:
        return schema(
            items=[
                {
                    "requirement_id": "REQ-999",
                    "covered": True,
                    "matched_sentence_index": 999,
                    "reason": "존재하지 않는 요구사항",
                }
            ]
        )

    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "complete_structured", _call)

    run = auditor_service.run_audit(PROCUREMENT_ID, _drop_satisfaction_sentence())
    assert all(state.requirement_id != "REQ-999" for state in run.requirement_states)
    assert find(run, "missing_requirement", "REQ-015")


# ---------------------------------------------------------------------------
# 저장 / 조회 / API
# ---------------------------------------------------------------------------


def test_run_and_store_round_trip(audit_run_dir: Path) -> None:
    run = auditor_service.run_and_store(PROCUREMENT_ID, BASE_DRAFT)
    assert (audit_run_dir / f"{run.id}.json").exists()

    loaded = auditor_service.load_run(run.id)
    assert loaded.id == run.id
    assert len(loaded.findings) == len(run.findings)


def test_load_run_rejects_path_traversal() -> None:
    with pytest.raises(auditor_service.AuditRunNotFoundError):
        auditor_service.load_run("../../../etc/passwd")
    with pytest.raises(auditor_service.AuditRunNotFoundError):
        auditor_service.load_run("audit-notfound0000")


@pytest.fixture()
def api_client() -> TestClient:
    """main.py를 건드리지 않고 auditor 라우터만 올린 테스트용 앱."""
    app = FastAPI()
    app.include_router(auditor_api.router)
    return TestClient(app)


def test_api_run_and_get(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/auditor/run",
        json={"procurement_id": PROCUREMENT_ID, "proposal_text": BASE_DRAFT},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["procurement_id"] == PROCUREMENT_ID
    assert payload["coverage"]["total"] > 0
    # 기존 프론트가 쓰는 필드명이 유지되어야 한다.
    for finding in payload["findings"]:
        assert {"id", "finding_type", "severity", "recommendation"} <= set(finding)

    fetched = api_client.get(f"/api/auditor/{payload['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == payload["id"]


def test_api_unknown_run_id(api_client: TestClient) -> None:
    assert api_client.get("/api/auditor/audit-000000000000").status_code == 404
    assert api_client.get("/api/auditor/not-a-run-id").status_code == 404


def test_api_unknown_procurement(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/auditor/run",
        json={"procurement_id": "g2b-NOTPARSED-000", "proposal_text": BASE_DRAFT},
    )
    assert response.status_code == 404


def test_api_empty_proposal_rejected(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/auditor/run",
        json={"procurement_id": PROCUREMENT_ID, "proposal_text": "  "},
    )
    assert response.status_code == 422


def test_api_upload_text_file(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/auditor/run/upload",
        data={"procurement_id": PROCUREMENT_ID},
        files={"file": ("proposal.txt", BASE_DRAFT.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["source_document"] == "proposal.txt"


def test_api_upload_word_draft(api_client: TestClient) -> None:
    """11-01 — 앱이 내려 주는 제안서 · 사업계획서는 워드(.docx)인데 점검 올리기가 받지 않아 「PDF 로 저장해 올리세요」였다."""
    import io

    from docx import Document

    document = Document()
    for line in BASE_DRAFT.splitlines():
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    response = api_client.post(
        "/api/auditor/run/upload",
        data={"procurement_id": PROCUREMENT_ID},
        files={"file": ("제안서_초안.docx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["source_document"] == "제안서_초안.docx"

    broken = api_client.post(
        "/api/auditor/run/upload",
        data={"procurement_id": PROCUREMENT_ID},
        files={"file": ("깨진.docx", b"not a word file", "application/octet-stream")},
    )
    assert broken.status_code == 422
    assert "DOCX" in broken.json()["detail"] and ":\\" not in broken.json()["detail"]

    # 독립 검토 — 압축 꼴은 맞지만 워드가 아닌 파일(목록 파일 없음)은 윈도에서 500 이었고 올린 파일이 임시 폴더에 남았다
    import zipfile

    fake = io.BytesIO()
    with zipfile.ZipFile(fake, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    not_word = api_client.post(
        "/api/auditor/run/upload",
        data={"procurement_id": PROCUREMENT_ID},
        files={"file": ("압축만.docx", fake.getvalue(), "application/octet-stream")},
    )
    assert not_word.status_code == 422, not_word.text
    assert "DOCX" in not_word.json()["detail"]


def test_api_upload_rejects_unsupported_suffix(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/auditor/run/upload",
        data={"procurement_id": PROCUREMENT_ID},
        files={"file": ("proposal.exe", b"binary", "application/octet-stream")},
    )
    assert response.status_code == 415


# ---------------------------------------------------------------------------
# 발견 묶음 — 사업담당자가 「무엇부터 봐야 하는가」
# ---------------------------------------------------------------------------


def _req(**kwargs: Any) -> Requirement:
    """묶음 판정용 최소 요구사항. 내용은 판정에 쓰이지 않으므로 짧게 둔다."""
    base: dict[str, Any] = {
        "id": "pid:REQ-001",
        "procurement_id": "pid",
        "requirement_id": "REQ-001",
        "category": "기타",
        "requirement_type": "mandatory",
        "title": "제목",
        "content": "본문",
        "source_text": "본문",
    }
    base.update(kwargs)
    return Requirement(**base)


def test_참가를_막는_요구사항의_발견은_참가_불가_위험으로_묶인다() -> None:
    """실측(g2b-R26BK01707959-000): critical 2건이 「참가자격 증빙 필요」 12건 속에 묻혀 있었다.

    참가가 막히면 제안서를 아무리 잘 써도 소용이 없으므로 별도 묶음으로 맨 앞에 둔다.
    """
    item = _req(criticality="blocker", response_scope="ELIGIBILITY_DOCUMENT")
    key, label = auditor_service.group_of("missing_requirement", item)
    assert key == "risk:eligibility"
    assert label == "참가 불가 위험"
    # 묶음과 심각도가 다른 이야기를 하면 안 된다.
    assert auditor_service.missing_severity(item) == "critical"
    # 자격 범위가 아니어도(제출·일정 항목의 blocker) 같은 묶음이다.
    other = _req(criticality="blocker", item_type="SUBMISSION", response_scope="SUBMISSION_CHECKLIST")
    assert auditor_service.group_of("missing_requirement", other)[0] == "risk:eligibility"


def test_평가기준_항목의_발견은_평가기준_묶음으로_빠진다() -> None:
    item = _req(item_type="EVALUATION", response_scope="PROPOSAL_BODY")
    key, label = auditor_service.group_of("missing_requirement", item)
    assert key == "risk:evaluation"
    assert label == "평가기준 대응 부족"
    # missing_severity 가 EVALUATION 을 high 로 올리는 것과 짝이다.
    assert auditor_service.missing_severity(item) == "high"


def test_자격_항목이라고_전부_참가_불가_위험은_아니다() -> None:
    """범위(ELIGIBILITY_DOCUMENT)로 묶으면 진짜 막히는 건이 다시 묻힌다.

    실측에서 자격 증빙 12건 중 참가를 막는 것은 2건뿐이었다.
    """
    item = _req(item_type="ELIGIBILITY", response_scope="ELIGIBILITY_DOCUMENT")
    assert auditor_service.group_of("missing_requirement", item)[0] == "scope:ELIGIBILITY_DOCUMENT"


def test_기존_묶음은_그대로다() -> None:
    """회귀 — 새 축을 앞에 넣었다고 기존 묶음이 사라지면 안 된다."""
    assert auditor_service.group_of(
        "missing_requirement", _req(response_scope="SUBMISSION_CHECKLIST")
    ) == ("scope:SUBMISSION_CHECKLIST", "제출서류 준비 필요")
    assert auditor_service.group_of(
        "missing_requirement", _req(response_scope="PROPOSAL_BODY")
    ) == ("scope:PROPOSAL_BODY", "제안서 본문 대응 필요")
    assert auditor_service.group_of(
        "number_mismatch", _req(response_scope="PROPOSAL_BODY")
    ) == ("type:number_mismatch", "수치 불일치")
    assert (
        auditor_service.group_of("unchecked_condition", _req(response_scope="PROPOSAL_BODY"))[0]
        == "type:unchecked_condition"
    )
    assert auditor_service.group_of("missing_document", _req(response_scope="PROPOSAL_BODY"))[0] == (
        "scope:SUBMISSION_CHECKLIST"
    )
    # 요구사항이 없는 발견(초안에만 있는 주장)은 유형으로 묶는다.
    assert auditor_service.group_of("unsupported_claim", None) == (
        "type:unsupported_claim",
        "회사 근거 없는 주장",
    )


def test_발견_유형에_이름이_있으면_평가기준보다_먼저다() -> None:
    """수치 불일치는 「무엇이 잘못됐는가」다. 평가기준 묶음으로 내려앉으면 안 된다."""
    item = _req(item_type="EVALUATION", response_scope="PROPOSAL_BODY")
    assert auditor_service.group_of("number_mismatch", item)[0] == "type:number_mismatch"
    # 다만 참가를 막는 조건은 유형보다 먼저다.
    blocker = _req(criticality="blocker", item_type="EVALUATION")
    assert auditor_service.group_of("number_mismatch", blocker)[0] == "risk:eligibility"


def test_묶음_표시_순서는_백엔드가_정한다() -> None:
    ranks = [
        auditor_service.group_rank(key)
        for key in (
            "risk:eligibility",
            "scope:PROPOSAL_BODY",
            "type:number_mismatch",
            "scope:SUBMISSION_CHECKLIST",
            "scope:ELIGIBILITY_DOCUMENT",
            "type:unsupported_claim",
            "risk:evaluation",
        )
    ]
    assert ranks == sorted(ranks), "지정한 순서대로 커져야 한다"
    assert len(set(ranks)) == len(ranks), "같은 자리에 두 묶음을 두지 않는다"
    # 참고 항목은 맨 뒤, 모르는 묶음은 「나머지」 자리.
    assert auditor_service.group_rank("scope:REFERENCE_ONLY") > auditor_service.group_rank(
        "risk:evaluation"
    )
    assert auditor_service.group_rank("scope:CONTRACT_COMPLIANCE") == (
        auditor_service.DEFAULT_GROUP_RANK
    )
    assert auditor_service.group_rank(None) == auditor_service.DEFAULT_GROUP_RANK


def test_모든_발견이_묶음과_순서를_갖는다() -> None:
    run = auditor_service.run_audit(
        PROCUREMENT_ID, BASE_DRAFT.replace("총 12회", "총 10회") + "\n당사는 100% 완벽을 보장합니다."
    )
    assert run.findings
    for finding in run.findings:
        assert finding.group_key and finding.group_label
        assert finding.group_rank == auditor_service.group_rank(finding.group_key)
    # 같은 심각도 안에서는 묶음 순서대로 나온다.
    keys = [(auditor_service._severity_rank(f.severity), f.group_rank) for f in run.findings]
    assert keys == sorted(keys)


def test_참가_불가_위험_건수를_커버리지에서_셀_수_있다() -> None:
    """화면의 「참가 불가 위험 n건」이 묶음 밖에서도 나와야 한다."""
    run = auditor_service.run_audit(PROCUREMENT_ID, BASE_DRAFT)
    parsed = rfp_parser.load_generated(PROCUREMENT_ID)
    blockers = [r for r in parsed.requirements if r.criticality == "blocker"]

    assert run.coverage.eligibility["blocking_total"] == len(blockers)
    assert 0 <= run.coverage.eligibility["blocking_unresolved"] <= len(blockers)
    # 요구사항 1건이 발견 여러 건을 낼 수 있으므로 «묶음 건수 ≥ 미해소 요구사항 수»다.
    grouped = {f.requirement_id for f in run.findings if f.group_key == "risk:eligibility"}
    assert len(grouped) <= run.coverage.eligibility["blocking_unresolved"]


def test_수치_권고문의_목적격_조사를_맞춘다() -> None:
    """이 문장은 화면과 발표자료에 그대로 나간다.

    '10회'는 받침이 없어 '를', '30시간'은 받침이 있어 '을'이다.
    """
    assert auditor_service._object_particle("10회") == "를"
    assert auditor_service._object_particle("30시간") == "을"
    assert auditor_service._object_particle("240명") == "을"
    assert auditor_service._object_particle("3년") == "을"
    assert auditor_service._object_particle("2주") == "를"
    # 한글이 아니면 기본값
    assert auditor_service._object_particle("") == "를"
    assert auditor_service._object_particle("80%") == "를"
