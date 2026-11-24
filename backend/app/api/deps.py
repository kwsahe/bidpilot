"""API 공통 의존성 — 분석 컨텍스트(회사 + 근거 범위) 해석과 쓰기 차단.

- 새 API는 `organization_id`를 명시한다. 호환 API(/api/company, 기존 분석 API에서 파라미터 생략)는
  설정의 기본 조직(`org-sample`)으로 위임한다 — 암묵 기본값은 여기(호환 계층)에서만 쓴다.
- 공개 배포(읽기 전용 데모) 모드에서는 회사 생성·자료 업로드·승인·색인 API를 403으로 막는다.
"""

from __future__ import annotations

from fastapi import HTTPException, Response

from app.core import org_storage
from app.schemas.organization import AnalysisContext
from app.services import organization_service


def context_or_400(
    organization_id: str | None,
    evidence_scope: str | None,
    *,
    procurement_id: str | None = None,
) -> AnalysisContext:
    """쿼리/본문 파라미터 → AnalysisContext. 잘못된 조직·범위는 4xx 로 바꾼다."""
    try:
        return organization_service.resolve_context(organization_id, evidence_scope, procurement_id=procurement_id)
    except org_storage.InvalidOrganizationIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except organization_service.OrganizationNotFoundError:
        raise HTTPException(status_code=404, detail="등록되지 않은 조직입니다")
    except organization_service.OrganizationInactiveError:
        raise HTTPException(status_code=409, detail="비활성 조직으로는 분석을 시작할 수 없습니다. 먼저 활성화하세요.")
    except organization_service.InvalidEvidenceScopeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def organization_or_404(organization_id: str) -> str:
    """URL 의 조직 id 검증 + 등록 확인. 형식 위반(경로 조작)도 404 로만 답한다 (존재 여부 누출 방지)."""
    try:
        org_id = org_storage.validate_organization_id(organization_id)
        organization_service.get_organization(org_id)
    except (org_storage.InvalidOrganizationIdError, organization_service.OrganizationNotFoundError):
        raise HTTPException(status_code=404, detail="등록되지 않은 조직입니다")
    return org_id


def require_writable() -> None:
    try:
        organization_service.require_writable()
    except organization_service.PublicDemoWriteError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


def stamp_context_headers(response: Response, context: AnalysisContext, *, compat: bool = False) -> None:
    """응답 헤더에 회사·범위·호환 API 사용 여부를 남긴다 (프론트가 표시·검증할 수 있게)."""
    response.headers["X-Organization-Id"] = context.organization_id
    response.headers["X-Evidence-Scope"] = context.evidence_scope
    if compat:
        response.headers["X-Compat-Api"] = "company"
