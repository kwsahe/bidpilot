"""31차 §3-B — 처음 하는 사람 안내(가이드 반영)의 백엔드 쪽.

- 신청 전 점검의 일반 절차 줄(K-Startup · 확인서 · 접수증 · 협약) — 조건부 · 마지막 「담당자 최종 검토」 줄 위치 그대로.
- 준비 상태 줄의 유효기간(`Credential.valid_until`) — 옛 파일 호환.
- 「나라장터 입찰참가자격 등록」은 사업계획서 초안의 보유 인증에 넣지 않는다(담당자 결정).
- ELIG-REGISTRATION 의 열리는 조건은 「적으면 판정」이 아니라 직접 확인할 일(막다른 길 없앰).
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.schemas.business_opportunity import SupportRequirementItem
from app.schemas.delivery_capacity import Credential, DeliveryCapacity
from app.services import eligibility_engine, plan_draft_service, support_application_service as s


def _program(**fields):
    base = {"attachments": [], "apply_period_kind": "fixed", "apply_period_text": "2026. 9. 15. ~ 10. 6."}
    return SimpleNamespace(**(base | fields))


def _items(value: str) -> dict:
    return {"eligibility": [SupportRequirementItem(key="target", label="지원 대상", value=value, status="confirmed")]}


def test_K_Startup_접수면_가입_기업인증_줄이_나오고_마지막_줄은_그대로() -> None:
    checks = s.pre_submit_checks(_items("창업 7년 이내 중소기업"), _program(apply_method="온라인 접수 (K-Startup)"))
    assert any(s.CHECK_KSTARTUP in c for c in checks)
    assert any(s.CHECK_STARTUP_CERT in c for c in checks) and any(s.CHECK_SME_CERT in c for c in checks)
    assert any(s.CHECK_RECEIPT in c for c in checks) and any(s.CHECK_AGREEMENT in c for c in checks)
    assert "담당자 최종 검토" in checks[-1]
    # 일반 절차 줄은 공고 조건과 섞이지 않게 머리가 붙는다(CLAUDE.md §11)
    assert all(c.startswith(s.GENERAL_PROCEDURE_HEAD) for c in checks if s.CHECK_RECEIPT in c or s.CHECK_KSTARTUP in c)


def test_K_Startup_이_아니면_그_줄은_빠지고_조건_없는_확인서_줄도_빠진다() -> None:
    checks = s.pre_submit_checks(_items("도내 사회적경제기업"), _program(apply_method="이메일 접수", reception_url="https://example.go.kr"))
    assert not any(s.CHECK_KSTARTUP in c for c in checks)
    assert not any(s.CHECK_STARTUP_CERT in c for c in checks) and not any(s.CHECK_SME_CERT in c for c in checks)
    assert any(s.CHECK_RECEIPT in c for c in checks)


def test_접수_방법_칸이_없는_객체도_깨지지_않는다() -> None:
    checks = s.pre_submit_checks({}, _program())
    assert "담당자 최종 검토" in checks[-1]


def test_화면에_숫자_기간_비용을_쓰지_않는다_예외는_3월_31일만() -> None:
    import re

    for line in (s.CHECK_KSTARTUP, s.CHECK_STARTUP_CERT, s.CHECK_SME_CERT, s.CHECK_RECEIPT, s.CHECK_AGREEMENT):
        assert not re.search(r"\d", line.replace("3월 31일", "")), line


def test_유효기간_칸은_옛_파일을_None_으로_읽고_날짜를_지킨다() -> None:
    assert Credential.model_validate({"name": "중소기업확인서", "held": None}).valid_until is None
    row = Credential(name="중소기업(소상공인) 확인서", held=True, valid_until=date(2027, 3, 31))
    again = Credential.model_validate(row.model_dump(mode="json"))
    assert again.valid_until == date(2027, 3, 31)
    capacity = DeliveryCapacity.model_validate({"organization_id": "org-x", "credentials": [row.model_dump(mode="json")]})
    assert capacity.credentials[0].valid_until == date(2027, 3, 31)


def test_나라장터_등록은_사업계획서_보유_인증에_넣지_않는다() -> None:
    capacity = {"credentials": [
        {"name": "나라장터 입찰참가자격 등록", "held": True},
        {"name": "직접생산확인증명서", "held": True},
        {"name": "신용평가등급확인서", "held": None},
    ]}
    assert plan_draft_service._credentials(capacity) == ["직접생산확인증명서"]


def test_만료된_줄과_공동인증서는_보유_인증에_넣지_않는다(monkeypatch) -> None:
    from datetime import date

    monkeypatch.setattr(plan_draft_service.storage, "kst_today", lambda: date(2026, 10, 4))
    capacity = {"credentials": [
        {"name": "중소기업(소상공인) 확인서", "held": True, "valid_until": "2026-03-31"},
        {"name": "사업자 범용 공동인증서", "held": True},
        {"name": "여성기업 확인서", "held": True, "valid_until": "2026-10-04"},
    ]}
    assert plan_draft_service._credentials(capacity) == ["여성기업 확인서"]


def test_등록_조항의_열리는_조건은_적으면_판정이_아니라_직접_확인할_일이다() -> None:
    token = eligibility_engine._ACTIVE_COMPANY.set(eligibility_engine.CompanyFacts(from_real_company=True))
    try:
        result = eligibility_engine._rule_business_registration(None)
    finally:
        eligibility_engine._ACTIVE_COMPANY.reset(token)
    assert result.status == "CHECK"
    assert result.unlock_condition == eligibility_engine.REGISTRATION_UNLOCK
    assert "사업자등록번호" not in result.unlock_condition and "등록증" in result.unlock_condition
