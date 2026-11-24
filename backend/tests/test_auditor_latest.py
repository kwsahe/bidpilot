"""GET /api/auditor/{procurement_id}/latest — 저장된 검사 결과를 «다시 돌리지 않고» 읽는다 (ISSUE-060).

공용 데모 공고의 결과는 모든 회사가 함께 보는 한 파일이라 **쓰기**만 기본 회사로 한정돼 있다.
화면이 열릴 때마다 재검사(POST)를 요청하는 바람에 다른 회사에서는 403 이 났고, 저장된 결과가
있는데도 「검사하지 않음」처럼 보였다. 읽기는 회사 구분 없이 열려야 한다.

네트워크·LLM 없음. 저장 경로는 conftest 가 tmp 로 돌린다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core import org_storage
from app.main import app
from app.schemas.organization import AnalysisContext, OrganizationCreateRequest
from app.services import analysis_store, auditor_service, llm_client, organization_service, rfp_parser

client = TestClient(app)
PID = "synthetic-rfp-0001"
#: 저장된 결과가 하나도 없는 공고 id (형식은 유효하다).
PID_EMPTY = "synthetic-rfp-9999"
OTHER_ORG = "org-demo-other"

CTX_DEMO = AnalysisContext(organization_id=org_storage.DEFAULT_ORGANIZATION_ID, evidence_scope="public_demo")
DRAFT = "교육은 총 12회 운영한다. 만족도 조사를 실시한다."


@pytest.fixture(autouse=True)
def setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)
    organization_service.create_organization(
        OrganizationCreateRequest(
            display_name="다른데모회사", organization_id=OTHER_ORG, data_class="synthetic", created_by="test"
        )
    )
    rfp_parser.parse_and_store(PID)


def _latest(procurement_id: str, organization_id: str, scope: str = "public_demo"):
    return client.get(
        f"/api/auditor/{procurement_id}/latest",
        params={"organization_id": organization_id, "evidence_scope": scope},
    )


def test_다른_회사도_공용_데모_공고의_최신_검사결과를_읽는다() -> None:
    stored = auditor_service.run_and_store(PID, DRAFT, use_llm=False, context=CTX_DEMO)

    # 전제 확인: 같은 회사로 «쓰기»는 여전히 막혀 있다 (막는 규칙을 약화시키지 않았다).
    with pytest.raises(analysis_store.PublicDemoReadOnlyError):
        auditor_service.run_and_store(
            PID,
            DRAFT + " 추가 문장.",
            use_llm=False,
            context=AnalysisContext(organization_id=OTHER_ORG, evidence_scope="public_demo"),
        )

    response = _latest(PID, OTHER_ORG)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == stored.id
    assert body["procurement_id"] == PID
    assert body["coverage"]["total"] >= 1


def test_기본_회사도_같은_결과를_읽는다() -> None:
    stored = auditor_service.run_and_store(PID, DRAFT, use_llm=False, context=CTX_DEMO)
    response = _latest(PID, org_storage.DEFAULT_ORGANIZATION_ID)
    assert response.status_code == 200
    assert response.json()["id"] == stored.id


def test_저장된_결과가_없으면_204() -> None:
    """「아직 검사한 적 없음」은 오류가 아니다 — 404 는 콘솔에 빨간 줄을 남긴다."""
    response = _latest(PID_EMPTY, OTHER_ORG)
    assert response.status_code == 204
    assert not response.content


def test_다른_회사_내부결과는_보이지_않는다() -> None:
    """internal 범위는 회사별 폴더다. 남의 결과가 최신으로 새어 나오면 안 된다."""
    auditor_service.run_and_store(
        PID, DRAFT, use_llm=False, context=AnalysisContext(organization_id=OTHER_ORG, evidence_scope="internal")
    )
    # 기본 회사의 internal 폴더에는 아무것도 없다
    response = _latest(PID, org_storage.DEFAULT_ORGANIZATION_ID, scope="internal")
    assert response.status_code == 204


def test_여러_번_검사하면_가장_최근_것을_준다() -> None:
    first = auditor_service.run_and_store(PID, DRAFT, use_llm=False, context=CTX_DEMO)
    second = auditor_service.run_and_store(PID, DRAFT + " 강사는 3명 이상 투입한다.", use_llm=False, context=CTX_DEMO)
    assert first.id != second.id
    assert _latest(PID, OTHER_ORG).json()["id"] == second.id


def test_저장경로로_쓸_수_없는_공고_id_는_400() -> None:
    """파일명으로 쓸 수 없는 id 는 폴더를 뒤지기 전에 막는다 (경로 이동 차단)."""
    response = client.get("/api/auditor/bad%20id%21/latest", params={"organization_id": OTHER_ORG})
    assert response.status_code == 400
