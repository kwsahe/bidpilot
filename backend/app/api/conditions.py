"""Critical Condition · Action Checklist · 입찰 참여 결정 API.

- POST /api/conditions/detect            규칙으로 조건을 탐지·저장한다 (LLM 없음)
- GET  /api/conditions/{id}              저장된 보고서 (없으면 요구사항이 있을 때 자동 탐지)
      저장본이 지금 요구사항 집합보다 낡았으면 stale=True·stale_reason 을 그대로 실어 보낸다.
      낡았다고 조건을 감추거나 서버가 멋대로 다시 탐지하지 않는다 — «다시 탐지»는 사람이 누른다.
      예외 하나: 제안요청서를 읽기 전에 만든 자리표시(조건 0 · 사람이 본 결과 아님)는 요구사항이 생기면 열 때 다시 찾는다(2.1.5).
      판정은 서비스에서만 만든다. 이 파일에는 로직을 두지 않는다.
- PUT  /api/conditions/{id}/{cid}        담당자가 상태를 바꾼다 (CLEARED는 사람만)
- GET  /api/actions/{id}                 체크리스트 (조건 보고서가 있으면 자동 씨앗)
- POST /api/actions/{id}                 항목 추가
- PUT  /api/actions/{id}/{aid}           항목 수정 (완료 표시 포함)
- DELETE /api/actions/{id}/{aid}         항목 삭제
- GET  /api/decision/{id}                결정 (없으면 UNREVIEWED)
- PUT  /api/decision/{id}                결정 저장 (미해결 BLOCKER면 GO 422)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.api import deps
from app.core import requester, storage
from app.schemas.organization import AnalysisContext
from app.schemas.action import ActionChecklist, ActionCreateRequest, ActionItem, ActionUpdateRequest
from app.schemas.critical_condition import (
    ConditionDetectRequest,
    ConditionUpdateRequest,
    CriticalConditionReport,
)
from app.schemas.decision import BidDecision, DecisionRequest
from app.services import (
    action_service,
    analysis_store,
    critical_condition_service,
    decision_service,
    eligibility_engine,
    organization_service,
    procurement_service,
    rfp_parser,
)

router = APIRouter(tags=["conditions"])


def _check_id(procurement_id: str) -> str:
    try:
        return storage.safe_id(procurement_id, what="공고 id")
    except storage.InvalidIdError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


async def _detect(procurement_id: str, context: AnalysisContext, as_of=None) -> CriticalConditionReport:
    try:
        parse_result = rfp_parser.load_generated(procurement_id)
    except (rfp_parser.RfpNotParsedError, rfp_parser.RfpFixtureNotFoundError):
        parse_result = None
    except storage.CorruptJsonError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    notice = None
    if rfp_parser.is_real_notice_id(procurement_id):
        try:
            notice = await procurement_service.get_notice(procurement_id)
        except procurement_service.NoNoticeDataError:
            notice = None

    if parse_result is None and notice is None:
        raise HTTPException(
            status_code=404,
            detail="파싱된 요구사항도 공고 원문 필드도 없어 조건을 탐지할 수 없습니다. RFP 파싱을 먼저 실행하세요.",
        )

    eligibility = None
    if notice is not None or parse_result is not None:
        # 규칙만 (LLM 끔). FAIL은 BLOCKER로 옮긴다.
        eligibility = eligibility_engine.evaluate_from_sources(
            procurement_id,
            notice=notice,
            parse_result=parse_result,
            as_of=as_of,
            use_llm=False,
            regions=organization_service.preferred_regions(context.organization_id),
            # 목록·상세와 **같은 회사 사실**(담당자의 조항 확인 포함)로 본다 — 빠지면 담당자가 「미충족」으로 확인한
            # 조항이 참가 차단 조건이 되지 못한다 (20차).
            company=eligibility_engine.company_facts_for(context.organization_id, evidence_scope=context.evidence_scope),
            context=context,
        )

    report = critical_condition_service.build_report(
        procurement_id,
        parse_result=parse_result,
        eligibility=eligibility,
        notice_available=notice is not None,
        as_of=as_of,
        context=context,
    )
    critical_condition_service.save_report(report, context=context)
    # 행동이 필요한 조건은 체크리스트에 씨앗을 뿌린다 (멱등).
    action_service.seed_from_report(report, context=context)
    return report


def _ctx(procurement_id: str, organization_id: str | None, evidence_scope: str | None) -> AnalysisContext:
    return deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)


@router.post("/api/conditions/detect", response_model=CriticalConditionReport)
async def detect_conditions(body: ConditionDetectRequest) -> CriticalConditionReport:
    procurement_id = _check_id(body.procurement_id)
    return await _detect(procurement_id, _ctx(procurement_id, body.organization_id, body.evidence_scope), body.as_of)


@router.get("/api/conditions/{procurement_id}", response_model=CriticalConditionReport)
async def get_conditions(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> CriticalConditionReport:
    procurement_id = _check_id(procurement_id)
    context = _ctx(procurement_id, organization_id, evidence_scope)
    try:
        report = critical_condition_service.load_report(procurement_id, context)
    except critical_condition_service.ConditionReportNotFoundError:
        return await _detect(procurement_id, context)
    except storage.CorruptJsonError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    # 제안요청서를 읽기 전에 만든 자리표시는 사람이 본 결과가 아니다 — 그 뒤 요구사항을 뽑았으면 다시 찾는다
    # (11-01 3순위 시험: 분석 뒤에도 「공고 분석도 아직 하지 않았습니다」). 사람 기록(overrides)은 따로 남아 다시 덧입혀진다.
    if not report.requirements_available and report.current_requirement_set_hash:
        try:
            return await _detect(procurement_id, context)
        except analysis_store.PublicDemoReadOnlyError:
            return report  # 공용 데모에 쓸 수 없는 다른 회사 — 저장본(낡음 표시) 그대로
    return report


@router.put("/api/conditions/{procurement_id}/{condition_id}", response_model=CriticalConditionReport)
async def update_condition(
    request: Request,
    procurement_id: str,
    condition_id: str,
    body: ConditionUpdateRequest,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> CriticalConditionReport:
    procurement_id = _check_id(procurement_id)
    context = _ctx(procurement_id, organization_id, evidence_scope)
    try:
        return critical_condition_service.update_condition(
            procurement_id, condition_id, body, context=context, recorded_by=requester.recorded_by(request)
        )
    except critical_condition_service.ConditionReportNotFoundError:
        raise HTTPException(status_code=404, detail="조건을 아직 탐지하지 않은 공고입니다.")
    except critical_condition_service.ConditionNotFoundError:
        raise HTTPException(status_code=404, detail=f"보고서에 없는 조건 id입니다: {condition_id}")
    except critical_condition_service.ConditionNoteRequiredError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# --------------------------------------------------------------------------
# Action Checklist
# --------------------------------------------------------------------------


@router.get("/api/actions/{procurement_id}", response_model=ActionChecklist)
async def get_actions(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> ActionChecklist:
    procurement_id = _check_id(procurement_id)
    context = _ctx(procurement_id, organization_id, evidence_scope)
    try:
        report = critical_condition_service.load_report(procurement_id, context)
    except critical_condition_service.ConditionReportNotFoundError:
        return action_service.load_checklist(procurement_id, context)
    return action_service.seed_from_report(report, context=context)


@router.post("/api/actions/{procurement_id}", response_model=ActionItem, status_code=201)
async def create_action(
    procurement_id: str,
    body: ActionCreateRequest,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> ActionItem:
    procurement_id = _check_id(procurement_id)
    return action_service.create_action(procurement_id, body, context=_ctx(procurement_id, organization_id, evidence_scope))


@router.put("/api/actions/{procurement_id}/{action_id}", response_model=ActionItem)
async def update_action(
    procurement_id: str,
    action_id: str,
    body: ActionUpdateRequest,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> ActionItem:
    procurement_id = _check_id(procurement_id)
    try:
        return action_service.update_action(procurement_id, action_id, body, context=_ctx(procurement_id, organization_id, evidence_scope))
    except action_service.ActionNotFoundError:
        raise HTTPException(status_code=404, detail=f"없는 항목입니다: {action_id}")


@router.delete("/api/actions/{procurement_id}/{action_id}", status_code=204)
async def delete_action(
    procurement_id: str,
    action_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> None:
    procurement_id = _check_id(procurement_id)
    try:
        action_service.delete_action(procurement_id, action_id, context=_ctx(procurement_id, organization_id, evidence_scope))
    except action_service.ActionNotFoundError:
        raise HTTPException(status_code=404, detail=f"없는 항목입니다: {action_id}")


# --------------------------------------------------------------------------
# GO / HOLD / NO_GO
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# GO / HOLD / NO_GO
# --------------------------------------------------------------------------


@router.get("/api/decision/{procurement_id}", response_model=BidDecision)
async def get_decision(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> BidDecision:
    procurement_id = _check_id(procurement_id)
    return decision_service.load_decision(procurement_id, _ctx(procurement_id, organization_id, evidence_scope))


@router.put("/api/decision/{procurement_id}", response_model=BidDecision)
async def put_decision(
    request: Request,
    procurement_id: str,
    body: DecisionRequest,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> BidDecision:
    procurement_id = _check_id(procurement_id)
    context = _ctx(procurement_id, organization_id, evidence_scope)
    try:
        return decision_service.save_decision(
            procurement_id, body, context=context, recorded_by=requester.recorded_by(request)
        )
    except decision_service.DecisionBlockedError as exc:
        raise HTTPException(status_code=422, detail=f"참가를 막는 조건이 남아 있어 「참여」를 저장할 수 없습니다: {exc}")
    except decision_service.DecisionReasonRequiredError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except decision_service.DecisionIneligibleError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"참가자격이 「불가」라 「참여」를 저장할 수 없습니다 — {exc}. 「참여 안 함」이나 「보류」로 기록하세요.",
        )
