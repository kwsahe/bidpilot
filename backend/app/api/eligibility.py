"""입찰 참가자격 판정 API.

라우터에 prefix를 두지 않고 경로를 전체로 적는다 (저장소의 다른 라우터와 동일한 방식).
비즈니스 로직은 전부 `services/eligibility_engine.py`에 있다.
"""

from fastapi import APIRouter, HTTPException, Query, Request

from app.api import deps
from app.core import requester, storage
from app.schemas.eligibility import (
    ClauseReviewEntry,
    ClauseReviewList,
    ClauseReviewRequest,
    EligibilityReport,
    EligibilityRequest,
)
from app.services import (
    audit_log_service,
    eligibility_engine,
    eligibility_gap_service,
    organization_service,
    qualification_review_service,
)

router = APIRouter(tags=["eligibility"])


@router.post("/api/eligibility/evaluate", response_model=EligibilityReport)
async def evaluate_eligibility(body: EligibilityRequest) -> EligibilityReport:
    """공고 필드 + 파싱된 RFP 자격 조항으로 PASS/CHECK/FAIL을 판정한다. 지역 규칙은 선택한 회사의 활동 지역을 쓴다."""
    context = deps.context_or_400(body.organization_id, body.evidence_scope, procurement_id=body.procurement_id)
    try:
        return await eligibility_engine.evaluate(
            body.procurement_id,
            as_of=body.as_of,
            use_llm=body.use_llm,
            regions=organization_service.preferred_regions(context.organization_id),
            context=context,
        )
    except eligibility_engine.EligibilityDataError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"공고 정보도 파싱된 요구사항도 없어 판정할 수 없습니다: {exc}",
        ) from exc


@router.get("/api/eligibility/gaps")
async def eligibility_gaps(
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=60),
) -> dict:
    """**무엇을 갖추면 몇 건이 열리는가** (0921 §4-B).

    이 경로는 아래 `/{procurement_id}` 보다 **먼저** 등록해야 한다 — 뒤에 두면
    「gaps」가 공고번호로 잡힌다.

    조회만 한다. 네트워크·LLM 을 부르지 않는다.
    """
    context = deps.context_or_400(organization_id, evidence_scope)
    return await eligibility_gap_service.build(context=context, days=days)


@router.get("/api/eligibility/{procurement_id}", response_model=EligibilityReport)
async def get_eligibility(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> EligibilityReport:
    """마지막 판정 결과를 돌려준다. 없으면 즉시 다시 판정한다 (캐시 키에 조직·범위 포함)."""
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    cached = eligibility_engine.get_last_report(procurement_id, context)
    if cached is not None:
        return cached
    try:
        return await eligibility_engine.evaluate(
            procurement_id,
            regions=organization_service.preferred_regions(context.organization_id),
            context=context,
        )
    except eligibility_engine.EligibilityDataError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"공고 정보도 파싱된 요구사항도 없어 판정할 수 없습니다: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# 참가자격 조항마다 담당자 확인 (20차 §4-C · ISSUE-139)
# ---------------------------------------------------------------------------


def _safe_id(procurement_id: str) -> str:
    try:
        return storage.safe_id(procurement_id, what="공고 id")
    except storage.InvalidIdError as exc:
        raise HTTPException(status_code=404, detail="공고를 찾을 수 없습니다.") from exc


@router.get("/api/eligibility/{procurement_id}/review", response_model=ClauseReviewList)
async def get_clause_reviews(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> ClauseReviewList:
    """저장된 조항 확인. 확인한 뒤 조항 원문이 바뀌었으면 `stale`. 파일만 읽는다."""
    procurement_id = _safe_id(procurement_id)
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    texts = eligibility_engine.clause_texts(procurement_id)
    entries = [
        ClauseReviewEntry(
            clause_id=clause_id,
            state=entry["state"],
            note=entry.get("note"),
            decided_by=entry.get("decided_by") or "",
            decided_at=entry["decided_at"],
            stale=qualification_review_service.clause_hash(texts.get(clause_id, "")) != entry.get("clause_hash"),
        )
        for clause_id, entry in sorted(qualification_review_service.load(procurement_id, context).items())
    ]
    return ClauseReviewList(procurement_id=procurement_id, reviews=entries)


@router.put("/api/eligibility/{procurement_id}/review/{clause_id}", response_model=EligibilityReport)
async def put_clause_review(
    request: Request,
    procurement_id: str,
    clause_id: str,
    body: ClauseReviewRequest,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> EligibilityReport:
    """조항 하나를 충족·미충족·보류로 확인하고, 그것을 합친 판정을 돌려준다.

    충족·미충족은 근거 메모가 있어야 저장된다 — 빈 메모는 422. 이 공고에 없는 조항 id 는 404.
    """
    procurement_id = _safe_id(procurement_id)
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    texts = eligibility_engine.clause_texts(procurement_id)
    if clause_id not in texts:
        raise HTTPException(status_code=404, detail=f"이 공고에 없는 조항입니다: {clause_id}")
    try:
        qualification_review_service.save(
            procurement_id,
            clause_id,
            state=body.state,
            note=body.note,
            decided_by=body.decided_by,
            clause_text=texts[clause_id],
            context=context,
            recorded_by=requester.recorded_by(request),
            check_version="expected_decided_at" in body.model_fields_set,
            expected_decided_at=body.expected_decided_at,
        )
    except qualification_review_service.ReviewNoteRequiredError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # 누가 어느 조항을 언제 무엇으로 — 메모 본문은 남기지 않는다(활동 기록 규칙: 본문을 적지 않는다).
    who = requester.current()
    audit_log_service.append(
        user=who.user if who is not None else body.decided_by,
        role=who.role if who is not None else "local",
        method="PUT",
        path=f"/api/eligibility/{procurement_id}/review/{clause_id}",
        organization_id=context.organization_id,
        status=200,
        event={"kind": "clause_review", "procurement_id": procurement_id, "clause_id": clause_id, "state": body.state},
    )
    try:
        return await eligibility_engine.evaluate(
            procurement_id,
            use_llm=False,
            regions=organization_service.preferred_regions(context.organization_id),
            context=context,
        )
    except eligibility_engine.EligibilityDataError as exc:
        raise HTTPException(status_code=404, detail=f"공고 정보도 파싱된 요구사항도 없어 판정할 수 없습니다: {exc}") from exc
