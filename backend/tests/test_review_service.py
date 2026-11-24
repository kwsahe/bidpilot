"""담당자 최종 검토 저장/조회 테스트.

핵심 계약 (CLAUDE.md 4-I, 25)
    - 체크리스트를 다 채우지 않으면 '승인'으로 갈 수 없다.
    - 보류·불참은 체크리스트와 무관하게 언제든 남길 수 있다.
    - 결정에는 근거(누가·언제·어떤 Auditor 실행을 보고)가 함께 남는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.review import ReviewChecklist, ReviewDecisionRequest
from app.services import review_service

PROCUREMENT_ID = "synthetic-rfp-0001"


@pytest.fixture(autouse=True)
def temp_review_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """실제 data/ 디렉터리를 건드리지 않는다."""
    monkeypatch.setattr(review_service, "REVIEW_DIR", tmp_path / "reviews")
    yield


def full_checklist() -> ReviewChecklist:
    return ReviewChecklist(
        auditor_findings_reviewed=True,
        eligibility_check_resolved=True,
        evidence_confirmed=True,
        numbers_verified=True,
    )


def request(**kwargs) -> ReviewDecisionRequest:
    payload = {
        "procurement_id": PROCUREMENT_ID,
        "status": "on_hold",
        "reviewer": "홍길동",
        "checklist": ReviewChecklist(),
    }
    payload.update(kwargs)
    return ReviewDecisionRequest(**payload)


# --------------------------------------------------------------------------
# 승인 게이트
# --------------------------------------------------------------------------


def test_체크리스트를_다_채우지_않으면_승인할_수_없다() -> None:
    with pytest.raises(review_service.ReviewNotAllowedError) as exc:
        review_service.save_decision(request(status="approved"))
    # 무엇이 남았는지 알려준다
    # 이름은 화면에 그대로 찍히므로 영문 단계 이름을 쓰지 않는다 (규칙 11 · 0922 §4-D-6).
    assert "제출 전 점검 발견 항목 확인" in str(exc.value)


def test_일부만_체크해도_승인할_수_없다() -> None:
    partial = ReviewChecklist(auditor_findings_reviewed=True, evidence_confirmed=True)
    with pytest.raises(review_service.ReviewNotAllowedError):
        review_service.save_decision(request(status="approved", checklist=partial))


def test_체크리스트를_다_채우면_승인된다() -> None:
    decision = review_service.save_decision(
        request(status="approved", checklist=full_checklist())
    )
    assert decision.status == "approved"
    assert decision.checklist.all_checked


def test_보류와_불참은_체크리스트_없이도_남길_수_있다() -> None:
    """확인이 덜 끝난 상태를 정직하게 남기는 것이 목적이다."""
    for status in ("on_hold", "rejected"):
        decision = review_service.save_decision(request(status=status))
        assert decision.status == status


# --------------------------------------------------------------------------
# 저장 / 조회 / 근거
# --------------------------------------------------------------------------


def test_저장한_결정을_다시_읽을_수_있다() -> None:
    review_service.save_decision(request(status="on_hold", note="자격조건 확인 중"))
    loaded = review_service.load_decision(PROCUREMENT_ID)
    assert loaded.status == "on_hold"
    assert loaded.note == "자격조건 확인 중"
    assert loaded.reviewer == "홍길동"


def test_결정에_시각과_담당자가_남는다() -> None:
    decision = review_service.save_decision(request())
    assert decision.decided_at is not None
    assert decision.reviewer


def test_다시_저장하면_최신_결정으로_덮어쓴다() -> None:
    review_service.save_decision(request(status="on_hold"))
    review_service.save_decision(request(status="rejected", note="예산 초과"))
    loaded = review_service.load_decision(PROCUREMENT_ID)
    assert loaded.status == "rejected"
    assert loaded.note == "예산 초과"


def test_저장된_적_없으면_ReviewNotFoundError() -> None:
    with pytest.raises(review_service.ReviewNotFoundError):
        review_service.load_decision(PROCUREMENT_ID)


def test_없는_Auditor_실행을_적으면_coverage를_비워둔다() -> None:
    """근거를 못 읽으면 지어내지 않는다."""
    decision = review_service.save_decision(request(audit_run_id="audit-000000000000"))
    assert decision.coverage_covered is None
    assert decision.coverage_total is None


# --------------------------------------------------------------------------
# 경로 안전성
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["../secret", "a/b", "", "x" * 65])
def test_경로로_쓸_수_없는_id는_거부한다(bad: str) -> None:
    with pytest.raises(review_service.InvalidProcurementIdError):
        review_service.review_path(bad)


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def test_api_저장과_조회가_이어진다() -> None:
    client = TestClient(app)
    body = {
        "procurement_id": PROCUREMENT_ID,
        "status": "approved",
        "reviewer": "홍길동",
        "checklist": {
            "auditor_findings_reviewed": True,
            "eligibility_check_resolved": True,
            "evidence_confirmed": True,
            "numbers_verified": True,
        },
        "note": "제출 가능",
    }
    saved = client.post("/api/review", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "approved"

    fetched = client.get(f"/api/review/{PROCUREMENT_ID}")
    assert fetched.status_code == 200
    assert fetched.json()["note"] == "제출 가능"


def test_api_체크하지_않고_승인하면_422() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/review",
        json={"procurement_id": PROCUREMENT_ID, "status": "approved", "reviewer": "홍길동"},
    )
    assert response.status_code == 422
    assert "승인" in response.json()["detail"]


def test_api_파싱된_적_없는_공고는_404() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/review",
        json={"procurement_id": "g2b-NOPE0000-000", "status": "on_hold", "reviewer": "홍길동"},
    )
    assert response.status_code == 404


def test_api_저장_전_조회는_404() -> None:
    client = TestClient(app)
    # 「아직 저장 안 함」은 오류가 아니다 — 본문 없는 204 (ISSUE-037).
    assert client.get(f"/api/review/{PROCUREMENT_ID}").status_code == 204
