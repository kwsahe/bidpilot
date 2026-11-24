"""입찰 참여 결정(GO / HOLD / NO_GO) 저장 서비스.

- 사람이 저장한다. AI는 결정하지 않는다.
- GO는 미해결 BLOCKER(Critical Condition)가 없을 때만 저장할 수 있다.
  탐지한 적이 없으면(게이트 없음) GO를 막지는 않되 gate=None으로 남겨 "조건 미검토"임을 드러낸다.
- 저장은 data/public/decisions/<id>.decision.json
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.core import storage
from app.core.paths import DATA_ROOT
from app.schemas.organization import AnalysisContext
from app.services import analysis_store
from app.schemas.critical_condition import ConditionGate
from app.schemas.decision import BidDecision, DecisionRequest, GateSnapshot
from app.schemas.eligibility import EligibilityReport
from app.services import critical_condition_service

DECISION_DIR = DATA_ROOT / "public" / "decisions"

#: 지원사업(기업마당 · 직접 넣은 공고)도 같은 결정 꼴 · 같은 파일에 둔다(44차 M4 · BIZ-08 · Q11). 입찰 조건 게이트는 보지 않는다.
SUPPORT_PREFIXES: tuple[str, ...] = ("bizinfo-", "manual-")
#: 결정 낱말 — 입찰(매출)은 참여 · 보류 · 참여 안 함, 지원금(수혜)은 신청 · 검토 중 · 신청 안 함. 「결정 전」은 둘 다.
#: 화면 `lib/scoreNames.DECISION_LABELS` · `SUPPORT_DECISION_LABELS` 와 같은 글.
BID_LABELS: dict[str, str] = {"GO": "참여", "HOLD": "보류", "NO_GO": "참여 안 함", "UNREVIEWED": "결정 전"}
SUPPORT_LABELS: dict[str, str] = {"GO": "신청", "HOLD": "검토 중", "NO_GO": "신청 안 함", "UNREVIEWED": "결정 전"}


class DecisionBlockedError(ValueError):
    """미해결 BLOCKER가 있어 GO를 저장할 수 없다."""


class DecisionReasonRequiredError(ValueError):
    """GO / NO_GO / HOLD 에는 사유가 필요하다."""


class DecisionIneligibleError(ValueError):
    """참가자격 종합이 불가라 GO 를 저장할 수 없다 (20차 §4-C-4 · ISSUE-140).

    담당자 말: 「자격요건은 안 맞으면 입찰 신청 자체를 못 한다.」 규칙이 낸 불가든 담당자가 「미충족」으로
    확인한 불가든 같다. 보류·참여 안 함은 저장된다.
    """


def _refuse_ineligible_manual(procurement_id: str, context: "AnalysisContext | None") -> None:
    """직접 넣은 입찰 · 수행 공고는 판정이 「불가」면 「참여」를 받지 않는다(44차 마지막 검토 — 수혜는 지원사업처럼 사람이 정함).

    나라장터 판정 길(`offline_report`)은 직접 넣은 공고를 모른다 — 목록과 같은 길(`manual_notice_service.gate_now`)로 잰다."""
    from app.services import manual_notice_service

    if context is None:
        return
    try:
        notice = manual_notice_service.get(context.organization_id, procurement_id)
    except manual_notice_service.ManualNoticeNotFoundError:
        return
    if notice.recruit == "benefit":
        return
    if manual_notice_service.gate_now(context.organization_id, procurement_id) == "FAIL":
        raise DecisionIneligibleError("직접 넣은 공고의 판정이 「불가」입니다 — 불가 사유를 먼저 확인하세요")


def _refuse_ineligible(
    procurement_id: str, context: "AnalysisContext | None", eligibility: "EligibilityReport | None"
) -> None:
    from app.services import eligibility_engine

    report = eligibility if eligibility is not None else eligibility_engine.offline_report(procurement_id, context)
    if report is None or report.verdict != "FAIL":
        return
    row = next(r for r in report.results if r.status == "FAIL")
    text = " ".join((row.clause_text or row.reason or "").split())
    raise DecisionIneligibleError(f"{row.label}: {text[:60]}{'…' if len(text) > 60 else ''}")


def decision_path(procurement_id: str, context: "AnalysisContext | None" = None) -> Path:
    safe = storage.safe_id(procurement_id, what='공고 id')
    return analysis_store.resolve_path(context, safe, public_path=DECISION_DIR / f"{safe}.decision.json", file_name="decision.json")


def load_decision(procurement_id: str, context: "AnalysisContext | None" = None) -> BidDecision:
    payload = storage.read_json(decision_path(procurement_id, context), default=None)
    if not isinstance(payload, dict):
        return BidDecision(
            procurement_id=procurement_id,
            organization_id=context.organization_id if context else None,
            evidence_scope=context.evidence_scope if context else None,
        )
    analysis_store.assert_owner(payload, context)
    return BidDecision.model_validate(payload)


def _snapshot(gate: ConditionGate | None) -> GateSnapshot | None:
    if gate is None:
        return None
    return GateSnapshot(can_go=gate.can_go, blocker_count=len(gate.blocker_ids), reason=gate.reason)


def _refuse_stale_go(procurement_id: str, context: "AnalysisContext | None") -> None:
    """구버전 판정으로 GO 를 저장하지 못하게 막는다.

    요구사항 집합이 바뀌면 저장된 자격판정·조건·제안서·Auditor 결과는 **이전 기준**의 값이다.
    화면은 그것을 「구버전」으로 표시하지만, 표시만으로는 담당자가 그 숫자를 근거로 GO 를
    누르는 것을 막지 못한다. 참여 결정은 되돌리기 어려우므로 저장 자체를 거절한다.

    막는 것은 GO 뿐이다 — HOLD·NO_GO 는 구버전 상태에서도 남길 수 있어야 한다
    (「지금은 판단 보류」가 정확한 기록이다).
    """
    # 순환 import 를 피한다: analysis_state 가 proposal_service 를 거쳐 이 모듈을 부를 수 있다.
    from app.services import analysis_state

    try:
        readiness = analysis_state.audit_readiness(procurement_id, context=context)
    except Exception:  # noqa: BLE001 — 판정을 못 하면 막지 않는다. 기존 동작을 지운 적 없다.
        return
    if "stale_requirements" in readiness.blockers:
        raise DecisionBlockedError(
            "현재 요구사항 이전에 만든 결과입니다. 다시 분석하거나 새 제안서 버전을 만든 뒤 「참여」를 저장하세요. "
            + readiness.message
        )


def _refuse_stale_conditions(procurement_id: str, context: "AnalysisContext | None") -> None:
    """구버전 조건 보고서의 통과 판정으로 GO 를 저장하지 못하게 막는다 (ISSUE-012).

    게이트(`can_go`)는 **저장된** 조건 보고서에서 나온다. 요구사항을 다시 뽑아
    BLOCKER 가 늘어도, 담당자가 「조건 다시 찾기」를 누르지 않으면 보고서는 예전
    그대로고 `can_go=True` 도 그대로다. 그 상태로 GO 가 저장되면, 지금은 막혀 있는
    공고가 「참여 가능」으로 기록된다.

    `freshness == "stale"` — 두 해시를 실제로 대조해 **다르다는 것을 아는** 경우에만
    막는다. `"unknown"`(한쪽 해시가 없어 대조 자체가 불가능)은 막지 않는다. 모르는 것을
    이유로 결정을 거절하면, 해시가 기록되기 전에 저장된 공고에서는 영원히 GO 를
    누를 수 없다. 화면은 그 경우를 「조건을 다시 찾아야 합니다」로 이미 안내한다.
    """
    try:
        report = critical_condition_service.load_report(procurement_id, context)
    except Exception:  # noqa: BLE001 — 보고서가 없으면 게이트도 없다. 막지 않는다.
        return
    if report.freshness == "stale":
        raise DecisionBlockedError(
            "요구사항이 바뀐 뒤 조건을 다시 찾지 않았습니다. 「조건 다시 찾기」를 실행한 뒤 「참여」를 저장하세요. "
            + (report.stale_reason or "")
        )


def save_decision(
    procurement_id: str,
    request: DecisionRequest,
    *,
    gate: ConditionGate | None = None,
    context: "AnalysisContext | None" = None,
    recorded_by: str | None = None,
    eligibility: "EligibilityReport | None" = None,
) -> BidDecision:
    if request.status != "UNREVIEWED" and not [r for r in request.reasons if r.strip()]:
        raise DecisionReasonRequiredError("결정에는 사유가 최소 1개 필요하다.")
    if "expected_decided_at" in request.model_fields_set:
        # 44차 M4 — 처음 읽은 뒤 다른 사람이 먼저 정했으면 막는다(남의 결정을 말없이 덮지 않게)
        path = decision_path(procurement_id, context)
        current = load_decision(procurement_id, context) if path.exists() else None
        storage.ensure_unchanged(current.decided_at if current else None, request.expected_decided_at,
                                 stored_by=current.decided_by if current else None)
    support = procurement_id.startswith(SUPPORT_PREFIXES)
    if request.status == "GO" and procurement_id.startswith("manual-"):
        _refuse_ineligible_manual(procurement_id, context)
    if support:
        gate = None  # 지원사업은 입찰 조건 게이트 · 참가자격 종합을 보지 않는다(신청 여부는 사람이 정함)
    elif gate is None:
        gate = critical_condition_service.gate_for(procurement_id, context)
    if request.status == "GO" and gate is not None and not gate.can_go:
        raise DecisionBlockedError(gate.reason)
    if request.status == "GO" and not support:
        _refuse_ineligible(procurement_id, context, eligibility)
        _refuse_stale_conditions(procurement_id, context)
        _refuse_stale_go(procurement_id, context)

    decision = BidDecision(
        procurement_id=procurement_id,
        status=request.status,
        reasons=[r.strip() for r in request.reasons if r.strip()],
        decided_by=request.decided_by,
        # 본문의 `decided_by` 는 클라이언트의 주장이고, 이것은 서명된 신원에서 온 사실이다 (S12).
        recorded_by=recorded_by,
        decided_at=datetime.now(timezone.utc),
        note=request.note,
        gate=_snapshot(gate),
        organization_id=context.organization_id if context else None,
        evidence_scope=context.evidence_scope if context else None,
    )
    payload = decision.model_dump(mode="json")
    analysis_store.stamp(payload, context)
    storage.stamp(payload)
    storage.write_json_atomic(decision_path(procurement_id, context), payload)
    return decision


def decisions_for(context: "AnalysisContext | None") -> dict[str, BidDecision]:
    """조직이 저장한 결정 전부(공고 id → 결정) — 목록이 한 번 읽어 행마다 붙인다(44차 M4 · 파일이 없으면 넣지 않는다)."""
    out: dict[str, BidDecision] = {}
    if not analysis_store.is_private(context) or context is None:
        return out
    for path in analysis_store.iter_private_results(context.organization_id, "decision.json"):
        try:
            out[path.parent.name] = BidDecision.model_validate(storage.read_json(path, default={}))
        except (ValueError, storage.CorruptJsonError):
            continue
    return out
