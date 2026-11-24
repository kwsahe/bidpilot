"""43차 §2-G — 공고 하나 끝까지(M17 · M18 · M19 · 결정 3 · Q22)."""

from __future__ import annotations

from app.services import auditor_service, critical_condition_service as ccs


def test_M18_확인_필요_꼬리는_앞_문장에_붙는다() -> None:
    sentences = auditor_service.split_sentences("[과업] \"원문\" — 회사 근거 연결을 꺼 두어 충족 여부를 확정할 수 없습니다. 확인 필요.")
    assert len(sentences) == 1 and sentences[0].text.endswith("확인 필요.")
    assert auditor_service.is_placeholder(sentences[0].text)


def test_M17_조건부_형식_문구는_업종_차단이_아니다() -> None:
    assert ccs._UNCERTAIN_LICENSE.search("허가·인가·면허·등록·신고 등을 요하거나 자격요건을 갖추어야 할 경우에는")
    assert not ccs._UNCERTAIN_GENERIC.search("현장설명에 참석하지 않은 경우에는 입찰에 참가할 수 없다")


def test_M18_원장_숫자는_근거_없는_숫자가_아니다() -> None:
    from app.schemas.audit import ProposalSentenceRef
    from app.schemas.requirement import Requirement

    req = Requirement(id="r1", procurement_id="p", requirement_id="REQ-001", title="t", content="교육 운영", requirement_type="mandatory", category="과업", source_text="교육 운영", page=1, status="unmatched")
    sentence = ProposalSentenceRef(id="S-001", index=0, text="당사는 2025년 30명 대상 아카데미를 운영했습니다.")
    found = auditor_service._unsupported_claims([req], [sentence])
    assert found
    ledger = {(2025.0, "년"): 16, (30.0, "명"): 16}
    assert auditor_service._unsupported_claims([req], [sentence], ledger_numbers=ledger) == []
