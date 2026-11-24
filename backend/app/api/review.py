"""담당자 최종 검토 API.

- POST /api/review                   검토 결과 저장 (승인/보류/불참)
- GET  /api/review/{procurement_id}  저장된 검토 결과 조회

rfp.py와 같은 이유로 prefix 없이 전체 경로를 적는다.
비즈니스 로직은 review_service에 있고 여기서는 입출력과 오류 변환만 한다.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response

from app.api import deps
from app.schemas.review import ReviewDecision, ReviewDecisionRequest
from app.services import review_service

router = APIRouter(tags=["review"])


@router.post("/api/review", response_model=ReviewDecision)
async def save_review(body: ReviewDecisionRequest) -> ReviewDecision:
    """담당자 최종 검토 결과를 저장한다. AI가 아니라 사람이 확정하는 단계다."""
    if not review_service.known_procurement(body.procurement_id):
        raise HTTPException(
            status_code=404,
            detail="이 공고는 아직 분석 전입니다 — 「공고 분석 시작」으로 요구사항을 뽑은 뒤 저장하세요.",  # API 주소를 화면에 적지 않는다(27차 §3-H · DSH-02)
        )
    context = deps.context_or_400(body.organization_id, body.evidence_scope, procurement_id=body.procurement_id)
    try:
        return review_service.save_decision(body, context=context)
    except review_service.AuditRunUnknownError as exc:
        # 근거로 지정한 검사가 없다 — 승인 자체의 형식이 아니라 «가리키는 대상»이 없는 것이다.
        raise HTTPException(status_code=404, detail=str(exc))
    except review_service.ReviewNotAllowedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except review_service.InvalidProcurementIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/review/{procurement_id}", response_model=ReviewDecision, responses={204: {"description": "아직 저장된 검토 결과가 없음"}})
async def get_review(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
):
    """저장된 검토 결과. 아직 없으면 **204**다 (ISSUE-037).

    예전에는 404 를 돌려줬다. 화면은 그것을 「없음」으로 잘 다뤘지만, 브라우저 콘솔에는
    화면을 열 때마다 빨간 404 가 남았다. 진짜 오류가 그 사이에 묻힌다.
    「아직 저장하지 않았다」는 오류가 아니라 정상 상태다 — 본문 없는 204 가 그 뜻이다.
    """
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        return review_service.load_decision(procurement_id, context)
    except review_service.ReviewNotFoundError:
        return Response(status_code=204)
    except review_service.InvalidProcurementIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
