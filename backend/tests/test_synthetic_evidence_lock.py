"""실제 회사 결과에 합성 근거가 섞이면 그렇다고 적는다 (ISSUE-018 · TASK-017).

## 무엇이 문제였나

실제 공고 + 주식회사 샘플에듀(실제 자료) 조합인데, 저장된 제안서 문장의 근거가 전부
「AI 심화 커리큘럼(합성)」·「단기집중 부트캠프 운영 자료(합성)」 같은 **합성 문서**였다.
상단 배지는 「내부 승인자료 · 합성 데모자료 · 레거시」라고 세 값을 이어 붙여 말했다.

담당자 입장에서 「우리 회사 자료가 맞나? 이걸 제출 초안으로 써도 되나?」가 된다.
그리고 내려받기를 누르면 그 문장이 그대로 제출 문서로 흘러간다.

## 지금은 왜 다시 안 생기나, 그런데 왜 검사가 필요한가

생성 경로(`_resolve_links`)는 `internal` 범위에서 합성 연결을 읽지 않는다. 하지만
**그 규칙이 생기기 전에 저장된 초안**이 남아 있다. 저장본은 기록이라 고치지 않는다 —
읽을 때 사실을 덧붙이고, 화면이 그것을 보고 내려받기를 막는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.organization import AnalysisContext
from app.services import analysis_store, proposal_service

ORG = "org-test-alpha"
PID = "g2b-R26BK01707959-000"


def _section_payload(evidence_ids: list[str | None]) -> dict:
    return {
        "id": f"{PID}-section",
        "procurement_id": PID,
        "title": "사업 이해 및 추진방향",
        "organization_id": ORG,
        "evidence_scope": "internal",
        "evidence_summary": {
            "organization_id": ORG,
            "evidence_scope": "internal",
            "used_document_count": 2,
            "used_chunk_count": len([i for i in evidence_ids if i]),
            "synthetic_evidence_used": False,
            "real_evidence_used": True,
            "note": None,
        },
        "sentences": [
            {
                "id": f"S-{index}",
                "requirement_id": f"REQ-{index:03d}",
                "text": "교육 운영 경험이 있습니다.",
                "grounding_type": "COMPANY_EVIDENCE_GROUNDED",
                "evidence_id": evidence_id,
                "needs_review": False,
            }
            for index, evidence_id in enumerate(evidence_ids, start=1)
        ],
    }


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """저장소를 tmp 로 돌린다.

    **저장소의 실제 파일을 건드리지 않는다.** 처음 이 파일을 쓸 때 `public_demo` 케이스가
    추적 중인 `data/public/proposals/…json` 을 덮어썼다. 테스트가 발표용 자료를 바꾸면
    통과해도 틀린 것이다.
    """
    monkeypatch.setattr(proposal_service, "PROPOSALS_DIR", tmp_path / "public" / "proposals")
    monkeypatch.setattr(analysis_store, "private_dir", lambda ctx, pid: tmp_path / "private" / ctx.organization_id / pid)
    yield


@pytest.fixture()
def context() -> AnalysisContext:
    return AnalysisContext(organization_id=ORG, evidence_scope="internal")


def _write(context: AnalysisContext, payload: dict) -> Path:
    path = analysis_store.resolve_path(
        context, PID, public_path=proposal_service.PROPOSALS_DIR / f"{PID}.proposal.json", file_name="proposal.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_합성_근거를_인용하면_사실을_덧붙인다(context: AnalysisContext) -> None:
    """`EV-` 는 합성 회사자료 문단이다. 실제 회사 결과에 섞이면 안 된다."""
    _write(context, _section_payload(["CD-0001", "EV-0007"]))

    section = proposal_service.load_section(PID, context)

    summary = section.evidence_summary or {}
    assert summary["synthetic_evidence_used"] is True
    assert "가상 예시" in (summary["note"] or "")
    assert "다시 생성" in (summary["note"] or "")


def test_회사자료만_인용하면_건드리지_않는다(context: AnalysisContext) -> None:
    """고치면서 정상 결과에 경고를 붙이면 더 나쁘다."""
    _write(context, _section_payload(["CD-0001", "CD-0002"]))

    section = proposal_service.load_section(PID, context)

    summary = section.evidence_summary or {}
    assert summary["synthetic_evidence_used"] is False
    assert summary["note"] is None


def test_기존_사유_문장을_지우지_않는다(context: AnalysisContext) -> None:
    payload = _section_payload(["EV-0007"])
    payload["evidence_summary"]["note"] = "회사 수행근거 연결에 실패했습니다."
    _write(context, payload)

    note = (proposal_service.load_section(PID, context).evidence_summary or {})["note"]
    assert "연결에 실패했습니다" in note
    assert "가상 예시" in note


def test_합성_데모_범위는_그대로_둔다() -> None:
    """공개 데모는 합성 자료를 쓰는 것이 «정상»이다. 거기에 경고를 붙이면 안 된다."""
    demo = AnalysisContext(organization_id=ORG, evidence_scope="public_demo")
    payload = _section_payload(["EV-0007"])
    payload["evidence_scope"] = "public_demo"
    _write(demo, payload)

    summary = proposal_service.load_section(PID, demo).evidence_summary or {}
    assert summary["synthetic_evidence_used"] is False
