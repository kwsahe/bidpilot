"""44차 §2-E — 다듬기(S2 · S4 · S5 · S7 · S9 · S10). 호출 없음.

- S2 번호가 어긋난 옛 초안 · 옛 가상 예시 근거 초안은 내려받지 않고 「다시 만들기」를 요구한다.
- S4 활동 표에 계정의 표시 이름.
- S5 내 비밀번호 바꾸기 — 열람자도 · 지금 비밀번호 확인 · 규칙 · 연속 실패 잠금 · 값 없는 활동 기록 · 로컬은 403.
- S7 직접 넣은 공고 모집 대상을 바꾸면 올린 공고문을 새 규칙으로 다시 읽는다.
- S9 입찰 제안서 내려받기에 사업계획서 문서 모양. S10 협약 기간이 없으면 공고 「지원기간」 끝 연월.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.core import identity
from app.core.config import get_settings
from app.main import app
from app.schemas.manual_notice import ManualNoticeInput
from app.services import audit_log_service, manual_notice_service, plan_export_service, proposal_export, user_service
from app.services.plan_form_service import _agreement_period

ORG = get_settings().default_organization_id
KST = timezone(timedelta(hours=9))
SECRET = "bidpilot-round44-password-token-77"


def _sentence(rid: str, stable: str | None) -> SimpleNamespace:
    return SimpleNamespace(requirement_id=rid, stable_requirement_id=stable, grounding_type="RFP_GROUNDED", needs_review=False)


def test_S2_번호가_어긋난_옛_초안은_내려받지_않는다() -> None:
    parsed = SimpleNamespace(requirements=[SimpleNamespace(requirement_id="REQ-001", stable_id="s-aaa"), SimpleNamespace(requirement_id="REQ-002", stable_id="s-bbb")])
    fresh = SimpleNamespace(sentences=[_sentence("REQ-001", "s-aaa")], legacy_result=False, evidence_summary={})
    assert proposal_export.stale_reason([fresh], parsed, "g2b-X-000") is None
    shifted = SimpleNamespace(sentences=[_sentence("REQ-001", "s-bbb"), _sentence("REQ-009", None)], legacy_result=False, evidence_summary={})
    assert "2건" in proposal_export.stale_reason([shifted], parsed, "g2b-X-000")
    with pytest.raises(proposal_export.ProposalExportError, match="다시 만들기"):
        proposal_export._refuse_stale([shifted], parsed, "g2b-X-000")
    synthetic = SimpleNamespace(sentences=[_sentence("REQ-001", "s-aaa")], legacy_result=False, evidence_summary={"synthetic_evidence_used": True})
    assert proposal_export.stale_reason([synthetic], parsed, "g2b-X-000") is not None  # 실공고에 가상 예시 근거
    assert proposal_export.stale_reason([synthetic], parsed, "synthetic-rfp-0001") is None  # 공개 시연 공고는 그대로


def test_S9_입찰_제안서_문서에_사업계획서_모양() -> None:
    from docx import Document

    doc = Document()
    plan_export_service.apply_document_style(doc)
    normal = doc.styles["Normal"]
    assert normal.font.size.pt == 11
    assert doc.sections[0].left_margin.mm == pytest.approx(22, abs=0.5)


def test_S10_협약_기간이_없으면_공고_지원기간_끝_연월() -> None:
    assert _agreement_period("□ 지원기간 : 2026. 11. 1. ~ 2027. 3. 31.") == {"text": "지원기간 : 2026. 11. 1. ~ 2027. 3. 31.", "end": "2027-03", "months": 5}
    assert _agreement_period("○ 사업기간: 협약일 ~ 2026.12.31")["end"] == "2026-12"
    assert _agreement_period("○ 수행기간 : 별도 안내") is None  # 끝 연월이 없으면 지어내지 않는다
    assert _agreement_period("□ 협약기간 : 협약일 ～ ’27. 3월(5개월)")["months"] == 5  # 옛 꼴 그대로


def _manual(**kw) -> ManualNoticeInput:
    base = dict(url="https://www.univ.ac.kr/notice/5507", title="AI 교육 운영 위탁", agency="시험대학",
                deadline=datetime(2026, 11, 30, 16, 0, tzinfo=KST), recruit="bid", methods=["이메일"])
    base.update(kw)
    return ManualNoticeInput(**base)


def test_S7_모집_대상을_바꾸면_공고문을_다시_읽는다() -> None:
    from docx import Document

    from app.services import qualification_clause_service as qc

    notice = manual_notice_service.create(ORG, _manual()).notice
    doc = Document()
    doc.add_paragraph("1. 참가자격: 소프트웨어사업자(컴퓨터관련서비스사업, 1468)로 등록한 업체")
    doc.add_paragraph("2. 지원대상: 광주광역시 소재 중소기업")
    for n in range(3, 12):  # 수혜 갈래가 글을 남길 만큼(짧으면 「스캔 이미지」로 봄)
        doc.add_paragraph(f"{n}. 신청 방법 · 제출 서류 · 선정 절차 안내 문단입니다. 공고 원문을 참고하여 기한 안에 신청서를 제출합니다.")
    buffer = io.BytesIO()
    doc.save(buffer)
    manual_notice_service.attach_document(ORG, notice.id, file_name="공고문.docx", payload=buffer.getvalue())
    assert qc.clause_path(notice.id, private=True).exists()
    changed = manual_notice_service.update(ORG, notice.id, _manual(recruit="benefit"), updated_by="대표")
    assert changed.document is not None
    assert not qc.clause_path(notice.id, private=True).exists()  # 입찰 갈래 조항은 지움
    assert manual_notice_service.document_text(ORG, notice.id)  # 수혜 갈래로 다시 읽음


@pytest.fixture()
def signed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(get_settings(), "api_token", SECRET)
    users = tmp_path / "users.json"
    monkeypatch.setattr(user_service, "USERS_FILE", users)
    monkeypatch.setattr(audit_log_service, "AUDIT_LOG_FILE", tmp_path / "audit_log.jsonl")
    monkeypatch.delenv("DEMO_USER", raising=False)
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    auth_api.reset_login_throttle()
    user_service.clear_snapshot_cache()
    user_service.add_user("viewer1", "old-password-1", role="viewer", display_name="열람 담당")
    user_service.clear_snapshot_cache()
    yield users
    auth_api.reset_login_throttle()
    user_service.clear_snapshot_cache()


def _headers(user: str, role: str) -> dict[str, str]:
    return {"X-API-Token": SECRET, "X-User": user, "X-User-Role": role, "X-User-Signature": identity.signature_for(user, role, SECRET)}


def test_S5_열람자도_자기_비밀번호를_바꾼다_틀리면_400_연속이면_잠금(signed: Path) -> None:
    client = TestClient(app)
    headers = _headers("viewer1", "viewer")
    wrong = client.post("/api/auth/password", json={"old_password": "nope-nope", "new_password": "new-password-2"}, headers=headers)
    assert wrong.status_code == 400 and "nope" not in wrong.text  # 값을 되돌려 주지 않음
    short = client.post("/api/auth/password", json={"old_password": "old-password-1", "new_password": "short"}, headers=headers)
    assert short.status_code == 400 and "8자" in short.json()["detail"]
    ok = client.post("/api/auth/password", json={"old_password": "old-password-1", "new_password": "new-password-2"}, headers=headers)
    assert ok.status_code == 204
    assert user_service.authenticate("viewer1", "new-password-2").account is not None
    # 활동 기록 — 값 없이 요청만
    log = (signed.parent / "audit_log.jsonl").read_text(encoding="utf-8")
    assert "/api/auth/password" in log and "new-password-2" not in log and "old-password-1" not in log
    for _ in range(auth_api.MAX_FAILURES):
        client.post("/api/auth/password", json={"old_password": "wrong-again", "new_password": "x-password-3"}, headers=headers)
    locked = client.post("/api/auth/password", json={"old_password": "new-password-2", "new_password": "x-password-3"}, headers=headers)
    assert locked.status_code == 429


def test_S5_로컬_실행은_계정이_없어_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "api_token", "")
    res = TestClient(app).post("/api/auth/password", json={"old_password": "a", "new_password": "bbbbbbbb"})
    assert res.status_code == 403


def test_S4_활동_표에_표시_이름(signed: Path) -> None:
    client = TestClient(app)
    user_service.add_user("admin1", "admin-password-1", role="admin", display_name="대표")
    user_service.clear_snapshot_cache()
    client.post("/api/auth/password", json={"old_password": "old-password-1", "new_password": "new-password-2"}, headers=_headers("viewer1", "viewer"))
    rows = client.get("/api/audit-log?limit=10", headers=_headers("admin1", "admin")).json()["entries"]
    row = next(r for r in rows if r["user"] == "viewer1")
    assert row["display_name"] == "열람 담당"
