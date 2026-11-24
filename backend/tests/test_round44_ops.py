"""44차 §2-F — 운영 준비(OPS-07 · 09 · 10 · 12). 호출 없음.

- OPS-07 계정 역할 바꾸기 · 다시 켜기(`manage_users.py role · enable`).
- OPS-09 받기 실패 원인별 한국어 할 일(서비스키 30 · 31 · 한도 22 · 연결 · 기업마당 키) — 원문은 그대로.
- OPS-10 기업마당 3일 넘게 못 받으면 받은 때 한 줄이 경고색 「기업마당 n일째 못 받음 — 관리자에게」.
- OPS-12 AI 적합도가 Claude 로그인 없음으로 쉬면 꼬리 · 서버의 Claude 만료 글은 「관리자에게 …」.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import auto_collect, llm_client, user_service

KST = timezone(timedelta(hours=9))


def _at(hour: int, minute: int = 0, day: int = 24) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=KST)


def _run(at: datetime, *, g2b_error: str | None = None, biz_error: str | None = None, ai_error: str | None = None) -> str:
    rows: list[dict] = [{"출처": "나라장터", "결과": "g2b", **({"오류": g2b_error} if g2b_error else {})},
                        {"출처": "기업마당", "결과": "bizinfo", **({"오류": biz_error} if biz_error else {})}]
    if ai_error:
        rows.append({"출처": "AI 적합도", "결과": None, "실패_이유": ai_error})
    return json.dumps({"시각": at.astimezone(timezone.utc).isoformat(), "실행": True, "결과": rows}, ensure_ascii=False)


@pytest.fixture
def cron(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLECT_SCHEDULER", "cron")
    monkeypatch.setattr(auto_collect, "task_state", lambda: "Ready")


@pytest.mark.parametrize(("error", "want"), [
    ("G2BApiError: ('30', 'SERVICE_KEY_IS_NOT_REGISTERED_ERROR')", "data.go.kr 에서 활용기간을 연장"),
    ("G2BApiError: ('31', 'DEADLINE_HAS_EXPIRED_ERROR')", "data.go.kr 에서 활용기간을 연장"),
    ("G2BApiError: ('22', 'LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR')", "내일 다시"),
    ("ConnectError: [Errno 11001] getaddrinfo failed", "관리자에게"),
    ("BizinfoError: 기업마당 인증/요청 오류: 존재하지 않는 인증키 입니다.", "기업마당 API 키"),
    # 10-31 — 조달청 점검 날 원문(나라장터는 <title> 앞에서 잘림 · 사전규격 · 발주계획은 제목까지 남음)
    ("나라장터 키워드 조회에서 한 건도 받지 못했습니다 (호출 21회 · 실패 21회). — 마지막 오류: G2B API returned non-JSON response: <!DOCTYPE html>", "시스템 점검"),
    ("G2BClientError: G2B API returned non-JSON response: <!DOCTYPE html>\r\n<title>시스템 점검 안내</title>", "시스템 점검"),
])
def test_OPS09_아는_실패는_할_일_한_줄(error: str, want: str) -> None:
    assert want in (auto_collect.failure_hint(error) or "")


def test_게이트웨이_XML_오류는_점검으로_읽지_않는다() -> None:
    """10-31 독립 검토 — 접근 거부 · IP 미등록은 기다려도 풀리지 않는다. HTML 안내 화면만 점검으로 본다."""
    xml = "G2B API returned non-JSON response: <OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>UNREGISTERED_IP_ERROR</returnAuthMsg>"
    assert "점검" not in (auto_collect.failure_hint(xml) or "")


def test_조달청_점검은_지금_받기를_권하지_않는다() -> None:
    """점검 중에 「지금 받기」를 눌러도 같은 까닭으로 실패한다 — 권유는 연결 문제(맨 끝 항목)일 때만이다."""
    hint = auto_collect.failure_hint("G2B API returned non-JSON response: <!DOCTYPE html>")
    assert hint is not None and hint != auto_collect._FAILURE_HINTS[-1][1]


def test_OPS09_모르는_실패는_원문만() -> None:
    assert auto_collect.failure_hint("ValueError: 이상한 값") is None


def test_OPS09_받은_때_한_줄에_원인(cron: None) -> None:
    auto_collect.LOG_FILE.write_text("\n".join([
        _run(_at(7, 31, day=23)),
        _run(_at(7, 32), g2b_error="G2BApiError: ('30', 'SERVICE_KEY_IS_NOT_REGISTERED_ERROR')"),
        _run(_at(9, 32), g2b_error="G2BApiError: ('30', 'SERVICE_KEY_IS_NOT_REGISTERED_ERROR')"),
        _run(_at(11, 32), g2b_error="G2BApiError: ('30', 'SERVICE_KEY_IS_NOT_REGISTERED_ERROR')"),
    ]) + "\n", encoding="utf-8")
    state = auto_collect.collect_state(_at(12))
    assert state["kind"] == "missed" and state["warn"] is True
    assert state["text"].endswith("원인: 서비스키 미등록 · 만료 — 대표가 data.go.kr 에서 활용기간을 연장하세요")
    # 45차 M10 — 키 · 한도 원인이면 「지금 받기」 권유를 빼고 원인의 할 일만(지금 받기도 같은 까닭으로 실패한다)
    assert "지금 받기" not in state["text"]


def test_OPS10_기업마당_3일_넘게_못_받으면_경고(cron: None) -> None:
    lines = [_run(_at(7, 31, day=19))]  # 마지막 기업마당 성공 10/19
    lines += [_run(_at(7, 31, day=d), biz_error="BizinfoError: 기업마당 인증/요청 오류: 존재하지 않는 인증키 입니다.") for d in (20, 21, 22, 23, 24)]
    auto_collect.LOG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    state = auto_collect.collect_state(_at(10))
    assert state["kind"] == "ok" and state["warn"] is True
    assert "기업마당 5일째 못 받음 — 관리자에게(기업마당 인증키 오류" in state["text"]


def test_OPS10_성공_기록이_없으면_실패가_시작된_날부터_센다(cron: None) -> None:
    # 성공 줄이 읽는 범위에 없을 때 「3일째」로 단정하지 않는다 — 첫 실패(10/21)부터 오늘(10/24)까지 4일째
    lines = [_run(_at(7, 31, day=d), biz_error="ConnectError: x") for d in (21, 22, 23, 24)]
    auto_collect.LOG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    state = auto_collect.collect_state(_at(10))
    assert state["warn"] is True and "기업마당 4일째 못 받음 — 관리자에게" in state["text"]


def test_OPS10_하루_못_받은_것은_보통색(cron: None) -> None:
    auto_collect.LOG_FILE.write_text("\n".join([_run(_at(7, 31, day=23)), _run(_at(7, 31), biz_error="ConnectError: x")]) + "\n", encoding="utf-8")
    state = auto_collect.collect_state(_at(10))
    assert state["warn"] is False and "기업마당 못 받음(인터넷 · 상대 서버 연결 문제" in state["text"]


def test_OPS12_AI_보조_쉼_꼬리_와_서버_Claude_만료_글(cron: None) -> None:
    auto_collect.LOG_FILE.write_text(_run(_at(7, 31), ai_error="LLMUnavailableError: " + llm_client.CLAUDE_NOT_LOGGED_IN_REASON) + "\n", encoding="utf-8")
    state = auto_collect.collect_state(_at(10))
    assert state["text"].endswith(auto_collect.AI_RESTING_NOTE)
    proc = subprocess.CompletedProcess(args=["claude"], returncode=1, stdout="", stderr="Invalid API key · Please run /login")
    message = llm_client._cli_failure({"result": "Invalid API key · Please run /login"}, proc)
    assert "관리자에게 Claude 다시 로그인을 부탁하세요" in message and "터미널" not in message


def test_OPS07_역할_바꾸기와_다시_켜기(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(user_service, "USERS_FILE", tmp_path / "users.json")
    user_service.add_user("hong", "pass-word-1", role="editor", display_name="홍길동")
    assert user_service.set_role("hong", "viewer").role == "viewer"
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import manage_users

    assert manage_users.main(["disable", "hong"]) == 0
    assert user_service.find_user("hong") is None or not user_service.find_user("hong").active
    assert manage_users.main(["enable", "hong"]) == 0
    assert manage_users.main(["role", "hong", "admin"]) == 0
    record = next(r for r in user_service.load_users() if r.user == "hong")
    assert record.active and record.role == "admin" and record.display_name == "홍길동"
    assert manage_users.main(["role", "nobody", "viewer"]) == 1  # 없는 아이디는 실패(값 없는 사유)
