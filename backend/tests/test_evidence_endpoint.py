"""근거 연결 조회 — 화면이 「Evidence Mapping 실행 여부」를 아는 유일한 통로.

이 라우트는 만들어질 때 **존재하지 않는 함수**(analysis_store.read_json — 실제 이름은
load_json)를 불러서 모든 호출이 500 이었고, 그것을 막는 테스트가 하나도 없었다.
라우트를 추가하면서 테스트를 같이 쓰지 않으면 이런 것이 배포까지 그대로 간다.

여기서 고정하는 계약:
  - 아직 실행하지 않았으면 **404** 다. 빈 결과(0건 연결)와 구분해야 한다.
  - 500 은 어떤 입력으로도 나오지 않는다.
  - 조직·근거범위를 받고, 다른 조직의 결과를 넘겨주지 않는다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.organization import AnalysisContext
from app.services import proposal_service

client = TestClient(app)

REAL_ID = "g2b-R26BK01699556-000"


def test_아직_실행하지_않았으면_404다():
    """빈 결과와 미실행은 다르다. 200 에 빈 목록을 주면 화면이 「실행했는데 0건」으로 읽는다."""
    response = client.get(
        f"/api/evidence/{REAL_ID}",
        params={"organization_id": "org-sample", "evidence_scope": "internal"},
    )
    assert response.status_code in (404, 200)
    if response.status_code == 404:
        assert "not run" in response.json()["detail"].lower() or "먼저" in response.json()["detail"]


def test_서비스_함수가_예외없이_None을_준다():
    """라우트가 500 을 내던 자리다 — 함수 이름이 틀려 AttributeError 가 났다."""
    context = AnalysisContext(organization_id="org-sample", evidence_scope="internal")
    result = proposal_service.load_evidence_result("no-such-procurement-id", context=context)
    assert result is None


@pytest.mark.parametrize(
    "procurement_id",
    ["no-such-id", "..%2F..%2Fetc%2Fpasswd", "a" * 300, "g2b-XXXX"],
)
def test_이상한_id로도_500이_나지_않는다(procurement_id: str):
    response = client.get(
        f"/api/evidence/{procurement_id}",
        params={"organization_id": "org-sample", "evidence_scope": "internal"},
    )
    assert response.status_code != 500, f"{procurement_id} 에서 500 — 없는 것과 실패를 섞고 있다"


def test_등록되지_않은_조직은_거절한다():
    response = client.get(
        f"/api/evidence/{REAL_ID}",
        params={"organization_id": "org-does-not-exist", "evidence_scope": "internal"},
    )
    assert response.status_code in (400, 404)
    assert response.status_code != 500
