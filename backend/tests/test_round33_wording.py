"""33차 §3-F — 옛 글 바꾸기는 바꿀 칸만 · 원문 인용은 그대로(R32W-1)."""

from __future__ import annotations

from app.services import wording


def test_원문_칸은_그대로_바꿀_칸만_새_말() -> None:
    saved = {
        "requirement_id": "REQ-014",
        "source_text": "제출 서류: 회사소개서(합성) 1부 — CHECK 상태입니다",
        "source": 'RFP p.8 "원문 (합성) 그대로"',
        "quotes": ["공고 원문 (합성)」 인용"],
        "document_name": "회사소개서(합성)",
        "recommendation": "RFP p.4 REQ-021 조건은 원문만으로 충족을 확정할 수 없어 CHECK 상태입니다.",
        "sentences": [{"text": "확인 필요. (후보 근거: 「회사소개서(합성)」 p.2 — 미채택)", "source_text": "원문 「회사소개서(합성)」"}],
        "flags": ["공고 인용 밖 내용 — AI 제안"],
    }
    out = wording.modernize(saved)
    assert out["source_text"] == saved["source_text"]
    assert out["source"] == saved["source"]
    assert out["quotes"] == saved["quotes"]
    assert out["document_name"] == saved["document_name"]
    assert "「확인 필요」로 남아 있습니다" in out["recommendation"]
    assert out["sentences"][0]["text"] == "확인 필요. (후보 근거: 「회사소개서(가상 예시)」 p.2 — 미채택)"
    assert out["sentences"][0]["source_text"] == "원문 「회사소개서(합성)」"
    assert out["flags"] != saved["flags"]


def test_합성은_문서_이름_자리만() -> None:
    assert wording.modernize_text("「회사소개서(합성)」 p.3") == "「회사소개서(가상 예시)」 p.3"
    # 문서 이름 자리가 아닌 「(합성)」은 그대로 — 요구사항 원문을 옮긴 문장일 수 있다
    assert wording.modernize_text("교재 (합성) 수지 사용 금지") == "교재 (합성) 수지 사용 금지"


def test_점검_응답은_원문으로_만든_처리_키를_싣는다() -> None:
    """R32-12 — 화면이 새 말로 바뀐 응답 글로 키를 다시 만들지 않게, 서버가 바꾸기 전 원문으로 키를 싣는다."""
    from datetime import datetime, timezone

    from app.api.auditor import _shown
    from app.schemas.audit import AuditCoverage, AuditFinding, AuditRun
    from app.services import finding_resolution_service

    stored = AuditFinding(
        id="AF-1", finding_type="unsupported_claim", severity="medium",
        proposal_text="확인 필요. (후보 근거: 「회사소개서(합성)」 p.2 — 미채택)",
        recommendation="RFP p.4 REQ-021 조건은 원문만으로 충족을 확정할 수 없어 CHECK 상태입니다.",
    )
    run = AuditRun(
        id="RUN-1", procurement_id="g2b-TEST-000", created_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
        coverage=AuditCoverage(total=0, covered=0, partial=0, missing=0), findings=[stored],
    )
    shown = _shown(run)
    assert shown.findings[0].resolution_key == finding_resolution_service.resolution_key(stored)
    assert "「확인 필요」로 남아 있습니다" in shown.findings[0].recommendation  # 글은 새 말
    assert run.findings[0].resolution_key is None  # 저장본은 그대로


def test_공고문_색인_메모는_읽을_때_그대로_내보낼_때만_새_말(monkeypatch) -> None:
    """R32-13 — 읽을 때 바꾸면 다음 수집이 색인을 새 글로 다시 저장했다(「저장 파일은 그대로」와 어긋남)."""
    from app.services import bizinfo_document_store as store
    from app.services import support_requirement_extractor as extractor

    old = "공고문이 이미지입니다 — 요약문으로 판정합니다"
    record = store.DocumentRecord.from_dict({"program_id": "PBLN_000000000999999", "status": "image", "note": old})
    assert record is not None and record.note == old  # 읽은 값 그대로 — 다시 저장해도 같은 글
    monkeypatch.setattr(store, "load_text", lambda _pid: None)
    monkeypatch.setattr(store, "load_index", lambda: store.DocumentIndex(records={record.program_id: record}))
    shown = extractor.load("bizinfo-PBLN_000000000999999")
    assert shown.document_note == store.IMAGE_NOTE  # 화면으로는 새 말


def test_제안서_전체_만들기_응답도_새_말(monkeypatch) -> None:
    """R32W-2 — 「AI 초안 유지」면 저장된 옛 초안이 POST 응답으로 그대로 왔다(GET 은 새 말)."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.schemas.proposal import ProposalSection, ProposalSentence
    from app.schemas.proposal_document import ProposalDocument
    from app.services import proposal_service

    old = "교육을 20회 운영합니다. (RFP p.3 요구사항 준수)"
    doc = ProposalDocument(
        id="DOC-1", procurement_id="synthetic-rfp-0001", title="제안서",
        sections=[ProposalSection(id="S1", title="운영", sentences=[ProposalSentence(id="s1", text=old, grounding_type="RFP_GROUNDED")])],
    )
    monkeypatch.setattr(proposal_service, "generate_document", lambda *_a, **_kw: doc)
    response = TestClient(app).post(
        "/api/proposal/generate/full",
        json={"procurement_id": "synthetic-rfp-0001", "use_llm": False, "use_claude": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["sections"][0]["sentences"][0]["text"] == "교육을 20회 운영합니다. (제안요청서 p.3 요구사항 준수)"


def test_마지막_검토_점검의_제안서_인용도_새_말() -> None:
    """`proposal_text` 는 우리 제안서 문장을 옮긴 칸 — 빼니 점검 화면에 「(합성)」이 다시 보였다."""
    out = wording.modernize({"proposal_text": "확인 필요. (후보 근거: 「AI 심화 커리큘럼(합성)」 p.2 — 미채택)"})
    assert "(가상 예시)" in out["proposal_text"]
