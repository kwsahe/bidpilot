"""45차 §2-B — 역할 · 이름(M4 · SEC-R37-02). 호출 없음.

- M4 `GET /api/auth/me` — 서버가 지금 보는 역할(`users.json` 기준 · 세션 사진 아님) · 로컬은 빈 값.
- M11 충돌 알림 · 「… 고침」 · 「열어 봄」은 계정 아이디가 아니라 표시 이름(저장본은 아이디).
- SEC-R37-02 「원문 확인함 — 가능으로」는 서버가 본 계정을 `recorded_by` 에 · 「고친 사람」도 그 계정.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.core import identity, storage
from app.core.config import get_settings
from app.main import app
from app.schemas.manual_notice import ManualNoticeInput
from app.services import audit_log_service, manual_notice_service, user_service

ORG = get_settings().default_organization_id
KST = timezone(timedelta(hours=9))

SECRET = "bidpilot-round45-roles-token-31"


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
    user_service.add_user("staff1", "old-password-1", role="viewer", display_name="직원 하나")
    user_service.clear_snapshot_cache()
    yield users
    user_service.clear_snapshot_cache()


def _headers(user: str, role: str) -> dict[str, str]:
    return {"X-API-Token": SECRET, "X-User": user, "X-User-Role": role, "X-User-Signature": identity.signature_for(user, role, SECRET)}


def test_M4_me_는_세션이_아니라_파일의_역할(signed: Path) -> None:
    client = TestClient(app)
    # 세션에는 편집자로 적혀 있어도(로그인 뒤 관리자가 낮춤) 파일은 열람자
    response = client.get("/api/auth/me", headers=_headers("staff1", "editor"))
    assert response.status_code == 200
    assert response.json() == {"user": "staff1", "role": "viewer", "display_name": "직원 하나"}


def test_M4_me_로컬은_빈_값(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "api_token", "")
    response = TestClient(app).get("/api/auth/me")
    assert response.status_code == 200
    assert response.json() == {"user": None, "role": None, "display_name": None}


def _manual() -> ManualNoticeInput:
    return ManualNoticeInput(url="https://www.univ.ac.kr/notice/4501", title="AI 교육 운영 위탁", agency="시험대학",
                             deadline=datetime(2026, 11, 30, 16, 0, tzinfo=KST), recruit="bid", methods=["이메일"])


def test_M11_충돌_알림은_표시_이름(signed: Path) -> None:
    error = storage.StaleWriteError("staff1", datetime(2026, 10, 24, 12, 17, tzinfo=timezone.utc))
    assert str(error).startswith("직원 하나 님이 10/24 21:17에 먼저 바꿨습니다")
    # 계정이 아닌 이름(사람이 적은 값)은 그대로
    assert str(storage.StaleWriteError("대표", None)).startswith("대표 님이 방금")


def test_M11_SEC_R37_02_직접_넣은_공고_이름과_기록_계정(signed: Path) -> None:
    client = TestClient(app)
    viewer = _headers("staff1", "viewer")
    notice = manual_notice_service.create(ORG, _manual(), created_by="staff1").notice
    assert notice is not None
    listed = [n for n in client.get("/api/manual-notices", headers=viewer).json() if n["id"] == notice.id][0]
    assert listed["created_by"] == "staff1" and listed["created_by_name"] == "직원 하나"
    marked = manual_notice_service.set_human_pass(ORG, notice.id, by="아무 이름", reason="원문 확인", gate_now="CHECK", recorded_by="staff1")
    assert marked.human_pass is not None and marked.human_pass.recorded_by == "staff1" and marked.human_pass.by == "아무 이름"
    assert marked.updated_by == "staff1"  # 사람이 적은 이름이 아니라 서버가 본 계정
    # 로그인 없는 로컬(계정 없음)은 적은 이름
    local = manual_notice_service.set_human_pass(ORG, notice.id, by="대표", reason=None)
    assert local.updated_by == "대표"
