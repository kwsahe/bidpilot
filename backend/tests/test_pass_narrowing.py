"""「가능」 좁히기(담당자 결정 2026-10-10) — 공고 원문 대조 감사 11건이 근거. 네트워크 0.

- 공고문을 못 읽고 요약의 대상 줄만 맞춘 공고는 「확인 필요」(요약 경로 「가능」 6건이 모두 요약 밖 조건으로 틀렸다).
- 지역 전략산업은 우선 선정 가산이라 「가능」의 근거가 아니다(123682).
- 제외 조항 사유는 규칙이 한 일만 말한다(122145 · 123682 — 「회사에 해당하는 것은 없습니다」).
"""

from __future__ import annotations

from app.services import support_application_service as sas
from app.services.support_requirement_extractor import SupportRequirements


def _requirements(document_read: bool) -> SupportRequirements:
    return SupportRequirements(program_id="P", document_read=document_read, pages=1 if document_read else 0,
                               target_sentence="지원대상 문장" if document_read else None, clauses=[])


def test_요약만_맞춘_공고는_가능이_아니라_확인_필요() -> None:
    rules = [sas._rule("BIZ-TARGET", "대상 요건", "PASS", "대상 요건 「(예비)사회적기업」", "대상 요건의 「사회적기업」을(를) 우리 회사가 갖고 있습니다.")]
    gate, reason = sas.verdict_of(_requirements(False), rules, indirect=None)
    assert gate == "CHECK"
    assert reason.startswith(sas.SUMMARY_ONLY_PREFIX) and "사회적기업" in reason  # 맞은 것은 그대로 적는다
    # 공고문을 읽은 공고에서 같은 맞음이면 가능
    assert sas.verdict_of(_requirements(True), rules, indirect=None)[0] == "PASS"


def test_전략산업만_맞으면_가능이_아니다() -> None:
    rules = [sas._rule("BIZ-STRATEGY", "지역 전략산업", "PASS", "전략산업 표", "공고문이 회사 지역(광주)의 전략산업으로 「ICT」를 지목합니다.")]
    gate, reason = sas.verdict_of(_requirements(True), rules, indirect=None)
    assert gate == "CHECK" and reason.startswith(sas.UNCONFIRMED_PREFIX)
    # 「왜 맞나」에는 그대로 남는다
    assert sas.company_match_of(_requirements(True), rules) == ["BIZ-STRATEGY"]
    both = rules + [sas._rule("BIZ-ORG-TYPE", "조직 형태", "PASS", "s", "공고문이 요구하는 형태 중 「사회적기업」을 회사가 갖고 있습니다.")]
    assert sas.verdict_of(_requirements(True), both, indirect=None)[0] == "PASS"


def test_제외_조항_사유는_규칙이_가린_것만_말한다() -> None:
    from app.core import storage  # noqa: F401
    from app.services import bizinfo_document_store as store
    from app.services import support_requirement_extractor as extractor
    from types import SimpleNamespace

    text = store.join_pages(["□ 참여 제외\n- 국세 · 지방세 체납 기업은 제외\n- 임금체불 명단 공개 사업주 참여 제한"])
    req = extractor.extract_from_text("P", text)
    rule = sas._biz_exclusion(req, SimpleNamespace(certifications=("사회적기업",)))
    assert rule is not None and rule.status == "PASS"
    assert "해당하는 것은 없습니다" not in rule.reason and "직접 확인" in rule.reason


def _headcount(company_kwargs: dict, waiver: str):
    from app.services import bizinfo_document_store as store
    from app.services import support_requirement_extractor as extractor
    from types import SimpleNamespace

    req = extractor.extract_from_text("P", store.join_pages([f"○ 참여기업 자격\n고용보험 피보험자 수 10인 이상 기업, 공공기관,\n{waiver}"]))
    company = SimpleNamespace(**{"certifications": ("사회적기업",), "employee_count": None, **company_kwargs})
    return req, sas._biz_headcount(req, company)


def test_인원을_직접_채우면_조건_붙은_예외를_보지_않는다() -> None:
    """예외 검사가 앞서면 인증 있는 회사가 오히려 확인 필요로 떨어졌다(검토 10-10)."""
    _req, rule = _headcount({"employee_count": 15}, "지침상 인정 요건 충족 시 10인 미만 기업도 참여 가능")
    assert rule.status == "PASS" and "15인" in rule.reason


def test_조건_붙은_예외_확인은_공고_쪽이고_근로자_수_안내가_있다() -> None:
    req, rule = _headcount({}, "지침상 인정 요건 충족 시 10인 미만 기업도 참여 가능")
    assert rule.status == "CHECK" and rule.unlock_condition is None
    assert "10인 이상이면 예외 없이 맞습니다" in rule.reason
    signals = sas.clause_signals(req, [rule], indirect=None)
    assert signals["company_side_checks"] == []  # 「이번 주 할 일」에서 빠지지 않는다
    # 근로자 수가 비어 있어 생긴 확인 필요는 여전히 회사 쪽
    _req2, plain = _headcount({"certifications": ()}, "")
    assert plain.status == "CHECK" and plain.unlock_condition
    assert sas.clause_signals(_req2, [plain], indirect=None)["company_side_checks"] == ["BIZ-HEADCOUNT"]


def test_제외_조항의_훈련기관은_주_사업이_없으면_확인_필요() -> None:
    from app.services import bizinfo_document_store as store
    from app.services import support_requirement_extractor as extractor
    from types import SimpleNamespace

    req = extractor.extract_from_text("P", store.join_pages(["□ 참여 제외\n- 직업능력개발훈련기관은 참여 제한"]))
    rule = sas._biz_exclusion(req, SimpleNamespace(certifications=("사회적기업", "프리미엄 훈련기관")))
    assert rule is not None and rule.status == "CHECK" and "훈련기관" in rule.reason
    other = sas._biz_exclusion(req, SimpleNamespace(certifications=("사회적기업",)))
    assert other.status == "PASS" and "훈련기관" not in other.reason


def test_가능_사유에_제외_조항_안내가_붙는다() -> None:
    from app.services import bizinfo_document_store as store
    from app.services import support_requirement_extractor as extractor

    req = extractor.extract_from_text("P", store.join_pages(["○ 지원대상 : 사회적기업\n□ 신청 제외\n- 국세 체납 기업은 제외"]))
    rules = [sas._rule("BIZ-ORG-TYPE", "조직 형태", "PASS", "s", "공고문이 요구하는 형태 중 「사회적기업」을 회사가 갖고 있습니다.")]
    gate, reason = sas.verdict_of(req, rules, indirect=None)
    assert gate == "PASS" and sas.EXCLUSION_REMINDER.format(n=len(req.of("exclusion"))) in reason
