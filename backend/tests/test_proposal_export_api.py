"""제안서 내보내기 **API 경로** 테스트 (ISSUE-001).

## 무엇을 막는가

`tests/test_proposal_export.py` 는 `build_document()` 를 직접 불러 문서 «내용»만 본다.
그래서 `export_section()` → `_evidence_index()` → `evidence_service.match_requirements()`
로 이어지는 실제 호출 사슬은 한 번도 지나가지 않았다.

다회사 구조(2026-09-07)에서 `match_requirements()` 가 `context` 를 키워드 필수 인자로
받게 바뀌었는데 `_evidence_index()` 는 그것을 넘기지 않았다. 결과:

    GET /api/proposal/{id}/export        → 500 (모든 format)
    GET /api/proposal/{id}/full/export   → 500

화면의 「초안 내려받기 DOCX / PDF / TXT」가 전부 죽어 있었는데도 1,027개 테스트는
모두 통과했다. 그래서 여기서는 **HTTP 로** 부른다.

또 하나: 내보내기는 «요청의 회사·범위»를 그대로 써야 한다. context 를 빠뜨리면
호출이 깨지거나(지금 사고) 다른 회사의 근거가 문서에 실린다. 그 전달을 여기서 고정한다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import evidence_service, proposal_export

DEMO_ID = "synthetic-rfp-0001"
DEMO_PARAMS = {"organization_id": "org-sample", "evidence_scope": "public_demo"}


@pytest.fixture()
def api() -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize("fmt", ["txt", "docx"])
def test_핵심_섹션_내보내기가_200을_준다(api: TestClient, fmt: str) -> None:
    """Word 가 없는 환경에서도 되는 두 형식만 기본으로 본다 (pdf 는 아래에서 따로)."""
    response = api.get(f"/api/proposal/{DEMO_ID}/export", params={"format": fmt, **DEMO_PARAMS})
    assert response.status_code == 200, response.text
    assert len(response.content) > 0
    assert "attachment" in response.headers.get("content-disposition", "")


def test_전체_초안_내보내기가_200을_준다(api: TestClient) -> None:
    response = api.get(f"/api/proposal/{DEMO_ID}/full/export", params=DEMO_PARAMS)
    assert response.status_code == 200, response.text
    assert len(response.content) > 0


def test_txt_본문에_요구사항_근거가_실린다(api: TestClient) -> None:
    """내용이 비어 있는 200 은 성공이 아니다."""
    response = api.get(f"/api/proposal/{DEMO_ID}/export", params={"format": "txt", **DEMO_PARAMS})
    text = response.content.decode("utf-8-sig")
    assert "사업수행계획" in text
    assert "번 요구사항" in text and "RFP p." not in text  # 32차 R31-24


def test_pdf는_변환기가_없으면_503이고_한국어로_말한다(api: TestClient) -> None:
    """Word 가 없는 서버에서 500 이 아니라 «왜 안 되는지»가 나와야 한다."""
    response = api.get(f"/api/proposal/{DEMO_ID}/export", params={"format": "pdf", **DEMO_PARAMS})
    assert response.status_code in (200, 503), response.text
    if response.status_code == 503:
        detail = response.json()["detail"]
        assert any(ch.isalpha() and ord(ch) > 0x3000 for ch in detail), f"한국어 사유가 아니다: {detail}"


def test_요청의_회사_범위가_근거_조회에_그대로_전달된다(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """이것이 ISSUE-001 의 본체다 — 빠뜨리면 호출이 깨지거나 다른 회사 근거가 섞인다."""
    seen: list[object] = []
    original = evidence_service.match_requirements

    def spy(requirements, *, context=None):
        seen.append(context)
        return original(requirements, context=context)

    monkeypatch.setattr(proposal_export.evidence_service, "match_requirements", spy)

    response = api.get(f"/api/proposal/{DEMO_ID}/export", params={"format": "txt", **DEMO_PARAMS})
    assert response.status_code == 200, response.text
    assert seen, "근거 조회가 아예 불리지 않았다"
    for context in seen:
        assert context is not None, "context 없이 불렸다 — 다른 회사 근거가 섞일 수 있다"
        assert context.organization_id == "org-sample"
        assert context.evidence_scope == "public_demo"
