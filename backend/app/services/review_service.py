"""담당자 최종 검토 저장/조회 서비스.

CLAUDE.md 4-I / 25: AI가 제출을 확정하지 않는다. 최종 상태는 사람이 정하고
그 결정을 근거와 함께 남긴다. 저장은 파일 기반 JSON이다(MVP 규모).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.core import storage
from app.core.paths import DATA_ROOT
from app.schemas.organization import AnalysisContext
from app.schemas.review import APPROVED, ReviewDecision, ReviewDecisionRequest
from app.services import analysis_store, auditor_service, rfp_parser

REVIEW_DIR = DATA_ROOT / "public" / "reviews"

# 저장 경로에 쓸 수 있는 id 형태만 허용한다 (경로 이동 차단).
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


class ReviewNotFoundError(LookupError):
    """아직 저장된 검토 결과가 없음."""


class ReviewNotAllowedError(ValueError):
    """체크리스트를 채우지 않은 채 승인하려 함."""


class InvalidProcurementIdError(ValueError):
    """저장 경로로 쓸 수 없는 id."""


class AuditRunUnknownError(LookupError):
    """모르는 검사 id 로 승인하려 함 — 근거로 삼은 검사가 존재하지 않는다."""


def review_path(procurement_id: str, context: AnalysisContext | None = None) -> Path:
    if not _SAFE_ID_RE.match(procurement_id):
        raise InvalidProcurementIdError(f"허용되지 않는 공고 id입니다: {procurement_id}")
    return analysis_store.resolve_path(context, procurement_id, public_path=REVIEW_DIR / f"{procurement_id}.review.json", file_name="review.json")


def load_decision(procurement_id: str, context: AnalysisContext | None = None) -> ReviewDecision:
    if not _SAFE_ID_RE.match(procurement_id):
        raise InvalidProcurementIdError(f"허용되지 않는 공고 id입니다: {procurement_id}")
    payload, legacy = analysis_store.load_json(
        context, procurement_id, public_path=REVIEW_DIR / f"{procurement_id}.review.json", file_name="review.json"
    )
    if payload is None:
        raise ReviewNotFoundError(procurement_id)
    decision = ReviewDecision.model_validate(payload)
    if legacy:
        decision.organization_id = None
        decision.evidence_scope = "public_demo"
        decision.legacy_result = True
    return decision


def _latest_coverage(
    procurement_id: str, audit_run_id: str | None, context: AnalysisContext | None = None
) -> tuple[int | None, int | None]:
    """결정 시점의 Coverage를 함께 남긴다. 못 읽으면 None (지어내지 않는다)."""
    if not audit_run_id:
        return None, None
    try:
        run = auditor_service.load_run(audit_run_id, context=context)
    except (auditor_service.AuditRunNotFoundError, OSError, ValueError):
        return None, None
    if run.procurement_id != procurement_id:
        return None, None
    return run.coverage.covered, run.coverage.total


def _assert_run_matches_now(
    procurement_id: str, audit_run_id: str, context: AnalysisContext | None
) -> None:
    """승인의 근거가 «지금 화면의» 검사 결과인지 확인한다 (ISSUE-012).

    여기까지 오면 체크리스트는 다 채워져 있고 요구사항도 최신이다. 그래도 한 칸이
    비어 있었다: 승인 요청이 들고 온 `audit_run_id` 를 아무도 확인하지 않았다.

    - **모르는 id** 도 통과했다. `_latest_coverage` 는 못 읽으면 조용히 `None` 을
      돌려주고 승인은 그대로 저장됐다. 근거가 없는 승인이 근거가 있는 것처럼 남는다.
    - 제안서를 다시 만들어 v2 가 됐어도 **v1 기준 검사 id** 로 승인이 저장됐다.
      담당자가 본 Coverage 는 지금 초안의 것이 아니다.
    - `change_impact` 는 「이전 초안을 최신 요구사항과 견주기」다. 그 결과로 지금
      초안을 승인할 수는 없다.

    맞지 않으면 막고 무엇을 하면 되는지 말한다. 승인은 되돌리기 어려운 기록이다.
    """
    try:
        run = auditor_service.load_run(audit_run_id, context=context)
    except auditor_service.AuditRunNotFoundError:
        raise AuditRunUnknownError(
            "승인 근거로 지정한 제출 전 점검 결과를 찾을 수 없습니다. 점검을 다시 실행한 뒤 승인하세요."
        ) from None
    except (OSError, ValueError):
        raise ReviewNotAllowedError(
            "승인 근거로 지정한 제출 전 점검 결과를 읽지 못했습니다. 점검을 다시 실행한 뒤 승인하세요."
        ) from None

    if run.procurement_id != procurement_id:
        raise AuditRunUnknownError(
            "승인 근거로 지정한 점검 결과가 다른 공고의 것입니다. 이 공고에서 점검을 다시 실행하세요."
        )

    if run.mode != "standard":
        raise ReviewNotAllowedError(
            "「요구사항 변화 확인」으로 돌린 점검 결과로는 승인할 수 없습니다. "
            "지금 초안으로 제출 전 점검을 다시 실행한 뒤 승인하세요."
        )

    current_set_hash = _current_requirement_set_hash(procurement_id)
    if current_set_hash and run.requirement_set_hash and run.requirement_set_hash != current_set_hash:
        raise ReviewNotAllowedError(
            "점검 결과가 이전 요구사항 기준입니다. 제출 전 점검을 다시 실행한 뒤 승인하세요."
        )

    current_proposal_hash = _current_proposal_hash(procurement_id, context)
    if current_proposal_hash and run.proposal_hash and run.proposal_hash != current_proposal_hash:
        raise ReviewNotAllowedError(
            "점검한 뒤 제안서가 바뀌었습니다. 지금 초안으로 제출 전 점검을 다시 실행한 뒤 승인하세요."
        )


def _current_requirement_set_hash(procurement_id: str) -> str | None:
    try:
        return rfp_parser.load_generated(procurement_id).requirement_set_hash
    except Exception:  # noqa: BLE001 — 못 읽으면 이 항목은 판정하지 않는다
        return None


def _current_proposal_hash(procurement_id: str, context: AnalysisContext | None) -> str | None:
    from app.services import proposal_service

    try:
        section = proposal_service.load_section(procurement_id, context)
    except Exception:  # noqa: BLE001 — 초안이 없으면 비교할 것이 없다
        return None
    return section.proposal_hash or proposal_service.section_hash(section.sentences)


def _readiness_or_none(procurement_id: str, context: AnalysisContext | None):
    """분석 기준이 최신인지. 판정하지 못하면 None — 못 읽는다고 승인을 막지는 않는다."""
    from app.services import analysis_state

    try:
        return analysis_state.audit_readiness(procurement_id, context=context)
    except Exception:  # noqa: BLE001
        return None


def save_decision(request: ReviewDecisionRequest, *, context: AnalysisContext | None = None) -> ReviewDecision:
    """검토 결과를 저장한다.

    승인(approved)은 체크리스트를 모두 채웠을 때만 허용한다 — 사람이 실제로
    확인하지 않은 상태가 '승인'으로 남지 않게 한다.
    """
    path = review_path(request.procurement_id, context)

    if request.status == APPROVED and not request.checklist.all_checked:
        raise ReviewNotAllowedError(
            "승인하려면 확인 항목을 모두 체크해야 합니다. 남은 항목: "
            + ", ".join(request.checklist.unchecked())
        )

    # 구버전 결과로는 승인할 수 없다.
    #
    # 요구사항 집합이 바뀌면 저장된 제안서·Auditor·조건 판정은 «이전 기준»의 값이다.
    # 체크리스트를 다 채웠더라도 담당자가 본 것이 옛 기준의 숫자라면 그 승인은 근거가 없다.
    # 보류(on_hold)·불참(rejected)은 막지 않는다 — 그 상태에서도 남길 수 있어야 하는 기록이다.
    if request.status == APPROVED:
        readiness = _readiness_or_none(request.procurement_id, context)
        if readiness is not None and "stale_requirements" in readiness.blockers:
            raise ReviewNotAllowedError(
                "현재 요구사항 이전에 생성된 결과입니다. 다시 분석하거나 새 제안서 버전을 만든 뒤 승인하세요. "
                + readiness.message
            )

    if request.status == APPROVED and request.audit_run_id:
        _assert_run_matches_now(request.procurement_id, request.audit_run_id, context)

    covered, total = _latest_coverage(request.procurement_id, request.audit_run_id, context)
    decision = ReviewDecision(
        procurement_id=request.procurement_id,
        status=request.status,
        checklist=request.checklist,
        reviewer=request.reviewer,
        note=request.note,
        decided_at=datetime.now(timezone.utc),
        audit_run_id=request.audit_run_id,
        proposal_id=request.proposal_id,
        coverage_covered=covered,
        coverage_total=total,
        organization_id=context.organization_id if context else None,
        evidence_scope=context.evidence_scope if context else None,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = decision.model_dump(mode="json")
    analysis_store.stamp(payload, context)
    storage.write_json_atomic(path, payload)
    return decision


def known_procurement(procurement_id: str) -> bool:
    """파싱된 적 있는 공고인지 (오타로 만든 검토 파일이 쌓이지 않게)."""
    try:
        rfp_parser.load_generated(procurement_id)
    except (rfp_parser.RfpNotParsedError, rfp_parser.RfpFixtureNotFoundError, ValueError):
        return False
    return True
