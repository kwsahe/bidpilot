"""구버전 결과로는 참여를 확정할 수 없다.

## 무엇을 막는가

요구사항 추출을 고치면 같은 공고의 필수 요구사항 수·구성이 바뀐다(32건 → 54건 같은 식).
그러면 그 전에 저장해 둔 자격판정·조건 분석·제안서·Auditor 결과는 **이전 기준**의 값이 된다.
숫자가 틀린 게 아니라 «다른 자를 대고 잰 값»이다.

화면에는 「구버전」 경고가 떠 있었지만, 그 아래 BLOCKER 건수와 조건 분석이 평소와 같은
빨강·초록으로 강하게 떠 있었다. 담당자가 그 값을 최신 판정으로 읽고 GO 나 승인을 누를 수 있었다.
참여 결정은 되돌리기 어려우므로 **저장 자체를 거절**한다.

막는 것은 GO / approved 뿐이다. HOLD · NO_GO · on_hold · rejected 는 구버전 상태에서도
남길 수 있어야 한다 — 「지금은 판단 보류」가 이 상황에서 정확한 기록이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.decision import DecisionRequest
from app.schemas.review import ReviewChecklist, ReviewDecisionRequest
from app.services import analysis_state, decision_service, review_service

PROCUREMENT_ID = "synthetic-rfp-0001"


def _stale() -> analysis_state.AuditReadiness:
    return analysis_state.AuditReadiness(
        ready=False,
        basis="stale_requirements",
        blockers=["stale_requirements"],
        message="필수 요구사항이 32건에서 54건으로 변경되었습니다. 현재 제안서는 이전 필수 요구사항 기준입니다.",
    )


def _current() -> analysis_state.AuditReadiness:
    return analysis_state.AuditReadiness(ready=True, basis="current", blockers=[], message="최신 기준입니다.")


@pytest.fixture
def stale_analysis(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(analysis_state, "audit_readiness", lambda *a, **k: _stale())


@pytest.fixture
def current_analysis(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(analysis_state, "audit_readiness", lambda *a, **k: _current())


@pytest.fixture(autouse=True)
def temp_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """실제 data/ 를 건드리지 않는다."""
    monkeypatch.setattr(review_service, "REVIEW_DIR", tmp_path / "reviews")
    monkeypatch.setattr(decision_service, "DECISION_DIR", tmp_path / "decisions")
    yield


def _decision(status: str) -> DecisionRequest:
    return DecisionRequest(status=status, reasons=["담당자 판단"], decided_by="홍길동", note=None)


def _review(status: str) -> ReviewDecisionRequest:
    return ReviewDecisionRequest(
        procurement_id=PROCUREMENT_ID,
        status=status,
        reviewer="홍길동",
        checklist=ReviewChecklist(
            auditor_findings_reviewed=True,
            eligibility_check_resolved=True,
            evidence_confirmed=True,
            numbers_verified=True,
        ),
    )


# ---------------------------------------------------------------------------
# GO (Go / Hold / No-Go)
# ---------------------------------------------------------------------------


def test_go_is_refused_while_analysis_is_stale(stale_analysis) -> None:
    with pytest.raises(decision_service.DecisionBlockedError) as exc:
        decision_service.save_decision(PROCUREMENT_ID, _decision("GO"))
    # 사유가 화면에 그대로 나가므로 «무엇을 하면 되는지»가 들어 있어야 한다.
    assert "이전에 만든 결과" in str(exc.value)
    assert "다시 분석" in str(exc.value)


@pytest.mark.parametrize("status", ["HOLD", "NO_GO"])
def test_hold_and_no_go_are_still_allowed_while_stale(stale_analysis, status: str) -> None:
    """보류·불참까지 막으면 담당자가 그 상황을 기록할 방법이 사라진다."""
    saved = decision_service.save_decision(PROCUREMENT_ID, _decision(status))
    assert saved.status == status


def test_go_passes_once_the_analysis_is_current(current_analysis) -> None:
    saved = decision_service.save_decision(PROCUREMENT_ID, _decision("GO"))
    assert saved.status == "GO"


def test_go_is_not_blocked_when_freshness_cannot_be_judged(monkeypatch: pytest.MonkeyPatch) -> None:
    """판정을 못 하면 막지 않는다 — 기존에 되던 일을 새 검사로 없애지 않는다."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("요구사항 파일을 읽을 수 없음")

    monkeypatch.setattr(analysis_state, "audit_readiness", boom)
    saved = decision_service.save_decision(PROCUREMENT_ID, _decision("GO"))
    assert saved.status == "GO"


# ---------------------------------------------------------------------------
# 사람의 최종 검토 (Human Review)
# ---------------------------------------------------------------------------


def test_approval_is_refused_while_analysis_is_stale(stale_analysis) -> None:
    """체크리스트를 다 채웠더라도, 본 것이 옛 기준의 숫자라면 그 승인은 근거가 없다."""
    with pytest.raises(review_service.ReviewNotAllowedError) as exc:
        review_service.save_decision(_review("approved"))
    assert "이전에 생성된 결과" in str(exc.value)


@pytest.mark.parametrize("status", ["on_hold", "rejected"])
def test_hold_and_reject_are_still_allowed_while_stale(stale_analysis, status: str) -> None:
    saved = review_service.save_decision(_review(status))
    assert saved.status == status


def test_approval_passes_once_the_analysis_is_current(current_analysis) -> None:
    saved = review_service.save_decision(_review("approved"))
    assert saved.status == "approved"


def test_checklist_rule_still_applies_first(current_analysis) -> None:
    """기존 규칙(체크리스트 미완 → 승인 불가)이 사라지지 않았는지."""
    request = _review("approved")
    request.checklist = ReviewChecklist()
    with pytest.raises(review_service.ReviewNotAllowedError) as exc:
        review_service.save_decision(request)
    assert "확인 항목을 모두 체크" in str(exc.value)


# ---------------------------------------------------------------------------
# 승인이 가리키는 «검사 결과» 자체 (ISSUE-012 · TASK-014)
#
# 위 검사들은 "요구사항이 최신인가"만 본다. 그 뒤에 한 칸이 비어 있었다:
# 승인 요청이 들고 온 `audit_run_id` 를 아무도 확인하지 않았다. 모르는 id 도,
# 다른 공고의 id 도, v1 초안을 검사한 id 도 그대로 저장됐다. 그러면 「승인 · Coverage
# 17/18」이라는 기록이 «지금 초안»과 아무 관계 없는 숫자가 된다.
# ---------------------------------------------------------------------------


def _run(**kwargs):
    from datetime import datetime, timezone

    from app.schemas.audit import AuditCoverage, AuditRun

    payload = {
        "id": "audit-aaaaaaaaaaaa",
        "procurement_id": PROCUREMENT_ID,
        "created_at": datetime(2026, 9, 16, tzinfo=timezone.utc),
        "coverage": AuditCoverage(total=18, covered=17, partial=1, missing=0),
        "findings": [],
        "mode": "standard",
        "requirement_set_hash": "hash-current",
        "proposal_hash": "proposal-current",
    }
    payload.update(kwargs)
    return AuditRun(**payload)


@pytest.fixture
def pinned(monkeypatch: pytest.MonkeyPatch, current_analysis):
    """요구사항·제안서의 «지금» 해시를 고정한다."""
    monkeypatch.setattr(review_service, "_current_requirement_set_hash", lambda *_a, **_k: "hash-current")
    monkeypatch.setattr(review_service, "_current_proposal_hash", lambda *_a, **_k: "proposal-current")


def _approve_with_run(monkeypatch: pytest.MonkeyPatch, run_or_exc) -> None:
    from app.services import auditor_service

    def load_run(_run_id: str, **_kwargs):
        if isinstance(run_or_exc, Exception):
            raise run_or_exc
        return run_or_exc

    monkeypatch.setattr(auditor_service, "load_run", load_run)
    review_service.save_decision(_review("approved").model_copy(update={"audit_run_id": "audit-aaaaaaaaaaaa"}))


def test_모르는_검사_id로는_승인할_수_없다(pinned, monkeypatch: pytest.MonkeyPatch) -> None:
    """예전에는 조용히 통과하고 coverage 만 비워 저장했다 — 근거 없는 승인이 남았다."""
    from app.services import auditor_service

    with pytest.raises(review_service.AuditRunUnknownError):
        _approve_with_run(monkeypatch, auditor_service.AuditRunNotFoundError("audit-aaaaaaaaaaaa"))


def test_다른_공고의_검사_결과로는_승인할_수_없다(pinned, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(review_service.AuditRunUnknownError):
        _approve_with_run(monkeypatch, _run(procurement_id="g2b-OTHER-000"))


def test_이전_요구사항_기준_검사로는_승인할_수_없다(pinned, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(review_service.ReviewNotAllowedError) as exc:
        _approve_with_run(monkeypatch, _run(requirement_set_hash="hash-old"))
    assert "다시 실행" in str(exc.value)


def test_검사_뒤_제안서가_바뀌면_승인할_수_없다(pinned, monkeypatch: pytest.MonkeyPatch) -> None:
    """제안서를 다시 만들어 v2 가 됐는데 v1 검사 id 로 승인이 저장되던 자리."""
    with pytest.raises(review_service.ReviewNotAllowedError) as exc:
        _approve_with_run(monkeypatch, _run(proposal_hash="proposal-v1"))
    assert "제안서가 바뀌었습니다" in str(exc.value)


def test_요구사항_변화_확인_모드의_결과로는_승인할_수_없다(pinned, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(review_service.ReviewNotAllowedError):
        _approve_with_run(monkeypatch, _run(mode="change_impact"))


def test_지금_초안을_검사한_결과면_승인된다(pinned, monkeypatch: pytest.MonkeyPatch) -> None:
    """막기만 하고 통과시키지 못하면 고친 게 아니다."""
    from app.services import auditor_service

    monkeypatch.setattr(auditor_service, "load_run", lambda *_a, **_k: _run())
    saved = review_service.save_decision(
        _review("approved").model_copy(update={"audit_run_id": "audit-aaaaaaaaaaaa"})
    )
    assert saved.status == "approved"
    assert (saved.coverage_covered, saved.coverage_total) == (17, 18)


# ---------------------------------------------------------------------------
# 구버전 «조건 보고서»로 GO
# ---------------------------------------------------------------------------


def _report(freshness: str):
    from datetime import datetime, timezone

    from app.schemas.critical_condition import ConditionCounts, ConditionGate, CriticalConditionReport

    return CriticalConditionReport(
        procurement_id=PROCUREMENT_ID,
        detected_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
        method="RULE",
        notice_available=True,
        requirements_available=True,
        eligibility_used=True,
        counts=ConditionCounts(total=0, blocker=0, action=0, check=0, cleared=0, info=0),
        gate=ConditionGate(can_go=True, reason="미해결 BLOCKER 없음"),
        conditions=[],
        freshness=freshness,  # type: ignore[arg-type]
        stale=freshness != "current",
        stale_reason="저장 당시 요구사항 집합과 지금 집합이 다릅니다." if freshness == "stale" else None,
    )


def test_조건을_다시_찾지_않은_상태에서는_GO를_막는다(current_analysis, monkeypatch: pytest.MonkeyPatch) -> None:
    """재파싱으로 BLOCKER 가 늘어도 옛 보고서의 can_go=True 로 GO 가 저장되던 자리."""
    from app.services import critical_condition_service

    monkeypatch.setattr(critical_condition_service, "load_report", lambda *_a, **_k: _report("stale"))
    with pytest.raises(decision_service.DecisionBlockedError) as exc:
        decision_service.save_decision(PROCUREMENT_ID, _decision("GO"))
    assert "조건 다시 찾기" in str(exc.value)


def test_대조할_수_없는_보고서는_GO를_막지_않는다(current_analysis, monkeypatch: pytest.MonkeyPatch) -> None:
    """해시가 기록되기 전에 저장된 공고에서 영원히 GO 를 못 누르게 되면 더 나쁘다."""
    from app.services import critical_condition_service

    monkeypatch.setattr(critical_condition_service, "load_report", lambda *_a, **_k: _report("unknown"))
    assert decision_service.save_decision(PROCUREMENT_ID, _decision("GO")).status == "GO"
