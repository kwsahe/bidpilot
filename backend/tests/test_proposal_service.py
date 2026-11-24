"""제안서 생성 서비스 테스트.

원칙 검증에 집중한다.
- 근거가 없으면 충족을 단정하지 않는다(확인 필요).
- 커버리지를 지어내지 않는다(문장 없는 요구사항은 그대로 남는다).
- LLM이 원문에 없는 수치를 만들면 규칙 템플릿으로 되돌린다.
- LLM이 없거나 실패해도 완전한 규칙 기반 결과가 나온다.

네트워크는 conftest가 차단하며, LLM은 항상 monkeypatch한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import proposal as proposal_api
from app.schemas.proposal import (
    EvidenceCandidate,
    GeneratedSectionDraft,
    GeneratedSentence,
)
from app.schemas.requirement import Requirement
from app.services import llm_client, proposal_service, rfp_parser

FIXTURE_ID = "synthetic-rfp-0001"


def build_client() -> TestClient:
    """main.py는 통합 담당자가 라우터를 등록한다. 테스트는 자체 앱으로 라우터만 검증한다."""
    api = FastAPI()
    api.include_router(proposal_api.router)
    return TestClient(api)


@pytest.fixture(autouse=True)
def isolated_proposal_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """저장소의 실제 proposals 디렉터리를 건드리지 않는다."""
    target = tmp_path / "proposals"
    monkeypatch.setattr(proposal_service, "PROPOSALS_DIR", target)
    return target


@pytest.fixture(autouse=True)
def no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """기본값은 규칙 기반. LLM 테스트에서만 다시 monkeypatch한다."""
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)


def make_requirement(
    requirement_id: str,
    content: str,
    *,
    status: str = "unmatched",
    requirement_type: str = "mandatory",
    page: int = 1,
    title: str = "요구사항",
) -> Requirement:
    return Requirement(
        id=f"test:{requirement_id}",
        procurement_id="test",
        requirement_id=requirement_id,
        category="운영",
        requirement_type=requirement_type,  # type: ignore[arg-type]
        title=title,
        content=content,
        page=page,
        source_text=content,
        status=status,  # type: ignore[arg-type]
    )


def make_evidence(
    requirement_id: str,
    *,
    evidence_id: str = "EV-01",
    source_text: str = "2025년 공공기관 생성형 AI 실무교육 운영 실적 보유.",
    selected: bool = True,
    score: float = 0.8,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        requirement_id=requirement_id,
        evidence_id=evidence_id,
        document_name="수행실적 목록(합성)",
        source_text=source_text,
        page=1,
        similarity_score=score,
        selected=selected,
    )


# --------------------------------------------------------------------------
# 어미 변환 / 수치 검증
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected_tail"),
    [
        ("계약상대자는 모든 과업을 완료해야 한다.", "완료하겠습니다."),
        ("승인을 받아야 한다.", "받겠습니다."),
        ("사전 서면승인 없이 할 수 없다.", "할 수 없습니다."),
        ("회차당 교육시간은 최소 3시간으로 한다.", "합니다."),
        ("증빙이 불충분한 경우 충족으로 확정하지 않는다.", "않겠습니다."),
    ],
)
def test_to_commitment_rewrites_ending(content: str, expected_tail: str) -> None:
    result = proposal_service.to_commitment(content)
    assert result is not None
    assert result.endswith(expected_tail)


def test_to_commitment_returns_none_for_non_sentence() -> None:
    assert proposal_service.to_commitment("교육 운영 개요") is None


def test_has_unsupported_number_flags_invented_value() -> None:
    requirement = make_requirement("REQ-001", "교육은 총 12회 운영해야 한다.")
    draft = proposal_service.build_drafts([requirement], [])[0]

    assert proposal_service.has_unsupported_number("교육을 총 12회 운영하겠습니다.", draft) is False
    assert proposal_service.has_unsupported_number("교육을 총 20회 운영하겠습니다.", draft) is True
    # 수치가 없는 문장은 통과한다.
    assert proposal_service.has_unsupported_number("교육을 계획대로 운영하겠습니다.", draft) is False


def test_evidence_excerpt_keeps_numbers_intact() -> None:
    """발췌가 수치 중간을 자르면 없는 숫자를 만들게 된다. 공백 경계에서만 자른다."""
    from app.services.text_match import extract_numbers

    text = "누적 교육생 260명 " + ("운영기록 " * 30) + "만족도 84%"
    excerpt = proposal_service._excerpt(text, limit=110)

    assert excerpt.endswith("…")
    source_numbers = {(t.value, t.unit) for t in extract_numbers(text)}
    assert all((t.value, t.unit) in source_numbers for t in extract_numbers(excerpt))


# --------------------------------------------------------------------------
# 규칙 기반 문장 생성
# --------------------------------------------------------------------------


def test_selected_evidence_becomes_evidence_grounded() -> None:
    requirement = make_requirement("REQ-001", "교육 운영실적을 제출해야 한다.")
    drafts = proposal_service.build_drafts([requirement], [make_evidence("REQ-001")])

    assert len(drafts) == 1
    assert drafts[0].grounding_type == "COMPANY_EVIDENCE_GROUNDED"
    assert drafts[0].needs_review is False
    assert drafts[0].evidence is not None
    assert "수행실적 목록(합성)" in drafts[0].text


def test_unselected_evidence_only_needs_review() -> None:
    requirement = make_requirement("REQ-001", "유사사업 3건 이상을 수행해야 한다.")
    drafts = proposal_service.build_drafts(
        [requirement], [make_evidence("REQ-001", selected=False)]
    )

    assert len(drafts) == 1
    assert drafts[0].needs_review is True
    assert drafts[0].evidence is None
    assert drafts[0].grounding_type == "RFP_GROUNDED"
    assert "확인 필요" in drafts[0].text


def test_check_status_never_asserts_satisfaction() -> None:
    requirement = make_requirement(
        "REQ-001", "총괄책임자는 유사사업 3건 이상 수행 경험을 보유해야 한다.", status="check"
    )
    drafts = proposal_service.build_drafts([requirement], [make_evidence("REQ-001")])

    assert drafts[0].needs_review is True
    assert "확인 필요" in drafts[0].text


def test_plain_obligation_without_evidence_is_rfp_grounded() -> None:
    requirement = make_requirement("REQ-001", "계약상대자는 모든 과업을 완료해야 한다.")
    drafts = proposal_service.build_drafts([requirement], [])

    assert drafts[0].grounding_type == "RFP_GROUNDED"
    assert drafts[0].needs_review is False
    assert drafts[0].evidence is None


def test_requirement_without_evidence_or_obligation_gets_placeholder() -> None:
    """커버리지를 지어내지 않는다 — 43차 M19 · Q22: 과업을 건너뛰지 않고 「확인 필요」 자리표시 줄로 남긴다(점검은 반영으로 세지 않음)."""
    requirement = make_requirement(
        "REQ-001", "반영 여부는 원문과 산출물을 대조해 확인하며 보완대상으로 처리한다."
    )
    drafts = proposal_service.build_drafts([requirement], [])
    assert len(drafts) == 1 and drafts[0].needs_review and "확인 필요" in drafts[0].text


def test_평가_서식_항목은_본문_밖_참고() -> None:
    requirement = make_requirement("REQ-002", "평가점수는 대외비로 처리함.")
    assert proposal_service.build_drafts([requirement], []) == []


def test_adopted_evidence_mandatory_matches_draft_denominator(monkeypatch: pytest.MonkeyPatch) -> None:
    """UI c — /plan 의 「필수 n건」이 서식 · 참고까지 센 원시 수라 초안 · 점검 분모와 따로 보였다."""
    reqs = [
        make_requirement("REQ-001", "교육은 총 20회 이상 운영해야 한다."),
        make_requirement("REQ-002", "평가점수는 대외비로 처리함."),
    ]
    monkeypatch.setattr(rfp_parser, "load_generated", lambda _pid: type("Parsed", (), {"requirements": reqs})())
    monkeypatch.setattr(proposal_service, "_resolve_links", lambda _pid, _reqs, _ctx: ([], None))
    assert proposal_service.adopted_evidence("test")["mandatory"] == 1


def test_optional_requirements_are_skipped() -> None:
    requirement = make_requirement(
        "REQ-001", "가점 항목은 제출하면 바람직하다.", requirement_type="optional"
    )
    assert proposal_service.build_drafts([requirement], []) == []


# --------------------------------------------------------------------------
# LLM 계층 (항상 monkeypatch — 네트워크 금지)
# --------------------------------------------------------------------------


def test_llm_sentence_replaces_template(monkeypatch: pytest.MonkeyPatch) -> None:
    requirement = make_requirement("REQ-001", "교육은 총 12회 운영해야 한다.")
    drafts = proposal_service.build_drafts([requirement], [])

    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        llm_client,
        "complete_structured",
        lambda **_: GeneratedSectionDraft(
            sentences=[
                GeneratedSentence(
                    requirement_id="REQ-001",
                    text="당사는 교육을 총 12회 운영하겠습니다.",
                    uses_evidence=False,
                    needs_review=False,
                )
            ]
        ),
    )

    assert proposal_service.refine_with_llm(drafts) is True
    assert drafts[0].text == "당사는 교육을 총 12회 운영하겠습니다."
    assert drafts[0].needs_review is False


def test_llm_hallucinated_number_falls_back_to_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requirement = make_requirement("REQ-001", "교육은 총 12회 운영해야 한다.")
    drafts = proposal_service.build_drafts([requirement], [])
    template_text = drafts[0].text

    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        llm_client,
        "complete_structured",
        lambda **_: GeneratedSectionDraft(
            sentences=[
                GeneratedSentence(
                    requirement_id="REQ-001",
                    text="당사는 교육을 총 30회 운영하며 만족도 99%를 보장합니다.",
                    uses_evidence=False,
                    needs_review=False,
                )
            ]
        ),
    )

    proposal_service.refine_with_llm(drafts)
    assert drafts[0].text == template_text  # 규칙 템플릿으로 되돌아간다
    assert drafts[0].needs_review is True


def test_llm_cannot_clear_needs_review(monkeypatch: pytest.MonkeyPatch) -> None:
    requirement = make_requirement("REQ-001", "유사사업 3건 이상을 수행해야 한다.", status="check")
    drafts = proposal_service.build_drafts([requirement], [make_evidence("REQ-001")])

    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        llm_client,
        "complete_structured",
        lambda **_: GeneratedSectionDraft(
            sentences=[
                GeneratedSentence(
                    requirement_id="REQ-001",
                    text="유사사업 수행 경험을 충분히 보유하고 있습니다.",
                    uses_evidence=True,
                    needs_review=False,
                )
            ]
        ),
    )

    proposal_service.refine_with_llm(drafts)
    assert drafts[0].needs_review is True


def test_llm_failure_keeps_rule_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**_: object) -> GeneratedSectionDraft:
        raise llm_client.LLMUnavailableError("키 없음")

    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "complete_structured", boom)

    section = proposal_service.generate_section(FIXTURE_ID)
    assert section.generation_method == "RULE"
    assert len(section.sentences) > 10


# --------------------------------------------------------------------------
# 실제 합성 RFP 전체 생성
# --------------------------------------------------------------------------


def test_generate_section_on_synthetic_rfp() -> None:
    section = proposal_service.generate_section(FIXTURE_ID)

    assert section.procurement_id == FIXTURE_ID
    assert section.generation_method == "RULE"
    assert section.mandatory_total == 23
    assert section.sentences
    assert section.requirements_with_sentence == len(section.sentences)

    # 채택 근거가 있는 요구사항은 회사 근거 문장이 된다.
    assert section.evidence_grounded_count >= 10
    # 근거가 없거나 모호한 요구사항은 확인 필요로 남는다 (자동 충족 금지).
    assert section.needs_review_count >= 1
    assert all(
        s.grounding_type != "COMPANY_EVIDENCE_GROUNDED" or s.evidence_id
        for s in section.sentences
    )
    # 확인 필요 문장은 반드시 그렇게 말한다.
    assert all("확인 필요" in s.text for s in section.sentences if s.needs_review)


def test_generated_numbers_all_traceable_to_source() -> None:
    """생성된 모든 수치는 요구사항 원문 또는 인용한 Evidence 원문에 존재해야 한다."""
    from app.services.text_match import extract_numbers

    parsed = rfp_parser.load_generated(FIXTURE_ID)
    links = proposal_service.load_evidence_links(FIXTURE_ID)
    drafts = proposal_service.build_drafts(parsed.requirements, links)

    for draft in drafts:
        # 발췌·유사도 표기를 뺀 실제 인용 문구만 대상으로 한다.
        assert not proposal_service.has_unsupported_number(
            draft.text.split("(후보 근거:")[0], draft
        ), draft.requirement.requirement_id
    assert extract_numbers("총 12회")  # 토크나이저가 살아 있는지 확인


def test_evidence_links_loader_reads_demo_scenario() -> None:
    links = proposal_service.load_evidence_links(FIXTURE_ID)
    assert links
    assert all(link.source_text for link in links)
    assert any(link.selected for link in links)
    # 실제 공고는 아직 회사자료 매칭 결과가 없다 → 지어내지 않는다.
    assert proposal_service.load_evidence_links("g2b-R26BK01687776-000") == []


def test_injected_evidence_links_override_loader() -> None:
    """팀원의 실제 매칭기 결과를 그대로 주입할 수 있어야 한다(교체 지점)."""
    section = proposal_service.generate_section(FIXTURE_ID, evidence_links=[])
    assert section.evidence_grounded_count == 0


# --------------------------------------------------------------------------
# 저장 / 조회 / API
# --------------------------------------------------------------------------


def test_store_and_load_roundtrip() -> None:
    generated = proposal_service.generate_section(FIXTURE_ID, section_title="교육 운영계획")
    loaded = proposal_service.load_section(FIXTURE_ID)
    assert loaded.title == "교육 운영계획"
    assert len(loaded.sentences) == len(generated.sentences)


def test_proposal_path_rejects_path_like_id() -> None:
    with pytest.raises(rfp_parser.RfpFixtureNotFoundError):
        proposal_service.proposal_path("../../etc/passwd")


def test_api_generate_and_get() -> None:
    client = build_client()

    response = client.post("/api/proposal/generate", json={"procurement_id": FIXTURE_ID})
    assert response.status_code == 200
    body = response.json()
    assert body["sentences"]
    assert {"id", "title", "sentences"} <= set(body)
    first = body["sentences"][0]
    assert {"id", "text", "grounding_type", "requirement_id", "evidence_id", "needs_review"} <= set(
        first
    )

    saved = client.get(f"/api/proposal/{FIXTURE_ID}")
    assert saved.status_code == 200
    assert len(saved.json()["sentences"]) == len(body["sentences"])


def test_api_rejects_unknown_id() -> None:
    client = build_client()
    assert (
        client.post("/api/proposal/generate", json={"procurement_id": "not-registered"}).status_code
        == 404
    )
    assert client.get("/api/proposal/unknown-id").status_code == 404
