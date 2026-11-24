"""확인 필요 중 회사 사실이 맞은 공고는 덜 깎기(담당자 결정 2026-10-10) — 「가능」 좁히기로 검수자 1~3순위가 44 · 48위로 떨어졌다."""

from __future__ import annotations

from app.services import opportunity_priority as op


def test_확인_필요라도_회사_사실이_맞으면_다른_버킷() -> None:
    assert op._clause_bucket({"gate": "CHECK", "company_match": True, "company_side_checks": ["BIZ-HEADCOUNT"]}) == "check_matched"
    assert op._clause_bucket({"gate": "CHECK", "company_match": False, "company_side_checks": ["BIZ-HEADCOUNT"]}) == "check_company"
    assert op._clause_bucket({"gate": "CHECK", "company_match": False}) == "check"
    assert op._clause_bucket({"gate": "PASS", "company_match": True}) == "match"
    # 불가 · 간접은 맞음이 있어도 그대로
    assert op._clause_bucket({"gate": "FAIL", "company_match": True}) == "blocked"
    assert op._clause_bucket({"gate": "CHECK", "company_match": True, "indirect": True}) == "indirect"


def test_덜_깎는_값은_가능과_확인_필요_사이() -> None:
    s = op.SUPPORT_CLAUSE_SCORES
    assert s["check"] < s["check_matched"] < s["match"]
    assert op.SUPPORT_CHECK_ELIGIBILITY < op.SUPPORT_CHECK_MATCHED_ELIGIBILITY < 1.0
    assert "check_matched" in op.SUPPORT_CLAUSE_REASONS


def test_간접_참여는_신청자격도_덜_깎지_않는다() -> None:
    """사업영역 칸이 간접 0.4 그대로인 것처럼 신청자격도 0.5 그대로(검토 10-10 — 124433 · 121614)."""
    assert op.softened_check("CHECK", {"company_match": True})
    assert not op.softened_check("CHECK", {"company_match": True, "indirect": True})
    assert not op.softened_check("CHECK", {"company_match": False})
    assert not op.softened_check("PASS", {"company_match": True})
    assert not op.softened_check("CHECK", None)
