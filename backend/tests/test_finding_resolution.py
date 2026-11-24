"""Auditor 발견 항목 해결 처리(Finding Resolution) 테스트.

핵심 계약
    - 발견 항목 id(AF-001)는 검사마다 바뀌므로 키로 쓰지 않는다. 같은 문제면 같은 키가 나온다.
    - 해결/재오픈 기록에는 누가·언제·무슨 메모로 했는지 남는다 (method=HUMAN).
    - Auditor 검사 결과 파일은 건드리지 않는다. 저장은 reviews 디렉터리의 별도 파일이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.audit import AuditFinding
from app.schemas.finding_resolution import FindingResolutionRequest
from app.services import finding_resolution_service as svc

PROCUREMENT_ID = "synthetic-rfp-0001"


@pytest.fixture(autouse=True)
def temp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(svc, "RESOLUTION_DIR", tmp_path / "reviews")
    yield


def finding(**kwargs) -> AuditFinding:
    payload = {
        "id": "AF-001",
        "finding_type": "missing_requirement",
        "severity": "high",
        "requirement_id": "REQ-015",
        "recommendation": "대응 문장을 추가한다",
    }
    payload.update(kwargs)
    return AuditFinding(**payload)


# --------------------------------------------------------------------------
# 안정 키
# --------------------------------------------------------------------------


def test_같은_문제면_AF_id가_달라도_키가_같다() -> None:
    assert svc.resolution_key(finding(id="AF-001")) == svc.resolution_key(finding(id="AF-009"))
    assert svc.resolution_key(finding()) == "missing_requirement:req:REQ-015"


def test_요구사항_없는_발견은_문장_fingerprint로_키를_만든다() -> None:
    a = finding(finding_type="unsupported_claim", requirement_id=None, proposal_text="만족도 99%를 달성한다.")
    b = finding(finding_type="unsupported_claim", requirement_id=None, proposal_text="만족도  99%를 달성한다. ")
    c = finding(finding_type="unsupported_claim", requirement_id=None, proposal_text="다른 문장이다.")
    assert svc.resolution_key(a) == svc.resolution_key(b)
    assert svc.resolution_key(a) != svc.resolution_key(c)
    assert svc.resolution_key(a).startswith("unsupported_claim:text:")


def test_fnv1a는_고정_값을_낸다() -> None:
    # 프론트엔드(lib/cosmos/graph.ts)의 구현과 같은 결과여야 한다.
    assert svc.fnv1a32("") == "811c9dc5"
    assert svc.fnv1a32("a") == "e40c292c"


# --------------------------------------------------------------------------
# 저장 / 조회
# --------------------------------------------------------------------------


def test_해결_처리는_근거와_함께_저장되고_다시_읽힌다() -> None:
    request = FindingResolutionRequest(
        key="missing_requirement:req:REQ-015",
        status="resolved",
        finding_type="missing_requirement",
        requirement_id="REQ-015",
        finding_id="AF-001",
        audit_run_id="audit-abc",
        reviewer="홍길동",
        note="운영계획 섹션에 JetPack/CUDA 환경구성 문장 추가",
    )
    saved = svc.save_resolution(PROCUREMENT_ID, request)
    assert saved.method == "HUMAN"
    assert saved.decided_at is not None

    loaded = svc.load_resolutions(PROCUREMENT_ID)
    assert [r.key for r in loaded.resolutions] == ["missing_requirement:req:REQ-015"]
    assert loaded.resolutions[0].note == request.note
    assert loaded.resolutions[0].reviewer == "홍길동"


def test_재오픈하면_같은_키가_open으로_덮어써진다() -> None:
    base = dict(
        key="number_mismatch:req:REQ-002",
        finding_type="number_mismatch",
        requirement_id="REQ-002",
        reviewer="홍길동",
    )
    svc.save_resolution(PROCUREMENT_ID, FindingResolutionRequest(status="resolved", **base))
    svc.save_resolution(PROCUREMENT_ID, FindingResolutionRequest(status="open", note="다시 확인 필요", **base))
    loaded = svc.load_resolutions(PROCUREMENT_ID)
    assert len(loaded.resolutions) == 1
    assert loaded.resolutions[0].status == "open"


def test_저장_경로로_쓸_수_없는_id는_거부한다() -> None:
    with pytest.raises(svc.InvalidProcurementIdError):
        svc.resolution_path("../evil")


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def test_api_저장_후_조회() -> None:
    client = TestClient(app)
    body = {
        "key": "missing_requirement:req:REQ-015",
        "status": "resolved",
        "finding_type": "missing_requirement",
        "requirement_id": "REQ-015",
        "reviewer": "홍길동",
        "note": "문장 추가함",
    }
    res = client.put(f"/api/auditor/{PROCUREMENT_ID}/resolutions", json=body)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "resolved"

    res = client.get(f"/api/auditor/{PROCUREMENT_ID}/resolutions")
    assert res.status_code == 200
    assert res.json()["resolutions"][0]["key"] == body["key"]


def test_api_파싱된_적_없는_공고는_404() -> None:
    client = TestClient(app)
    body = {
        "key": "missing_requirement:req:REQ-001",
        "status": "resolved",
        "finding_type": "missing_requirement",
        "reviewer": "홍길동",
    }
    res = client.put("/api/auditor/no-such-notice/resolutions", json=body)
    assert res.status_code == 404


def test_api_잘못된_키_형식은_422() -> None:
    client = TestClient(app)
    body = {"key": "AF-001", "status": "resolved", "finding_type": "missing_requirement", "reviewer": "홍길동"}
    res = client.put(f"/api/auditor/{PROCUREMENT_ID}/resolutions", json=body)
    assert res.status_code == 422
