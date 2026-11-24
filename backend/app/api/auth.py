"""로그인 API — `POST /api/auth/login` (계약서 1장).

누가 부르는가
------------
브라우저는 이 엔드포인트를 **직접 부르지 않는다**. Next.js 서버가 로그인 폼을 받아
여기로 중계하고, 성공하면 서명된 세션 쿠키를 굽는다. `API_TOKEN` 이 설정된 배포에서는
이 경로도 토큰 미들웨어 뒤에 있다(`app/core/auth.py`) — 토큰을 모르는 쪽은 아이디·비밀번호를
넣어 볼 기회조차 없다.

무엇을 알려 주고 무엇을 감추는가
------------------------------
- 성공: `{user, display_name, role}` 200.
- 실패: 401 + 한국어 사유. **아이디가 틀렸는지 비밀번호가 틀렸는지 구분해 주지 않는다.**
  비활성 계정도 같은 401 이다. 「그 아이디는 있는데 잠겼다」는 말 자체가 정보다.
- 응답·로그 어디에도 비밀번호·해시를 싣지 않는다(CLAUDE.md 21).
- 실패 사유는 **서버 로그에만** 남긴다. 없는 아이디일 때는 아이디 값도 남기지 않는다 —
  비밀번호를 아이디 칸에 잘못 친 사람의 비밀번호가 로그에 박히는 사고를 막는다.

연속 실패 방어
-------------
같은 아이디로 연속 5회 틀리면 비밀번호 검사를 아예 하지 않고 같은 401 로 답한다.
잠금 시간은 **실패가 이어질수록 배로 늘어난다** — 60초 · 120 · 240 … 최대 15분 (S11).
고정 60초면 「5회 틀리고 60초 쉬기」를 반복해 시간당 300번을 두드릴 수 있다.
성공하면 그 아이디의 기록을 지우므로, 비밀번호를 아는 사람은 이 늘어남을 만나지 않는다.
- **왜 잠금인가**: 이 엔드포인트는 사람이 하루에 몇 번 부르는 경로다. 초당 수십 번
  두드리는 쪽은 사람이 아니다. pbkdf2 600,000회는 한 번이 0.2초라 느린 편이지만,
  그것만 믿으면 병렬로 두드릴 때 CPU 가 먼저 죽는다.
- **왜 아이디 기준인가**: 프런트엔드가 중계하므로 여기서 보는 IP 는 전부 같은 서버다.
  IP 로 세면 한 사람이 틀릴 때 전원이 잠긴다. **IP 단위 제한은 프런트엔드에서 한다** —
  거기서는 브라우저의 주소가 보인다(`frontend/src/app/api/login/route.ts`).
- **없는 아이디도 똑같이 센다.** 잠금 여부가 계정 존재 여부를 알려 주면 안 된다.
- 한계: 세는 곳이 **프로세스 메모리**라 워커가 여러 개면 각자 센다. 재시작하면 지워진다.
  분산 잠금이 필요할 만큼 노출된 경로가 아니라고 보고 여기까지만 했다.
- 남은 한계: 아이디를 매번 바꿔 가며 두드리면 잠금에 걸리지 않고 해시 계산만 시킬 수 있다
  (한 번에 0.2초). 전체 속도 제한은 두지 않았다 — 이 경로는 `API_TOKEN` 뒤에 있어
  토큰을 모르는 쪽은 애초에 닿지 못한다. 토큰 없이 여는 배포를 하게 되면 그때 다시 본다.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.core import requester
from app.services import user_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

#: 없는 아이디·틀린 비밀번호·비활성 계정에 **모두 같은 문장**을 쓴다(사유를 구분해 주지 않는다).
INVALID_CREDENTIALS_DETAIL = "아이디 또는 비밀번호가 올바르지 않습니다."
TOO_MANY_ATTEMPTS_DETAIL = "로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요."

#: 이 사유들은 **그 아이디가 실제로 있다**는 뜻이다. 그때만 로그에 아이디를 남긴다.
KNOWN_ACCOUNT_REASONS = frozenset({"wrong_password", "inactive", "invalid_role"})

MAX_FAILURES = 5
#: 처음 잠기는 시간(초). 이후 실패마다 배로 늘어난다 (S11).
LOCK_SECONDS = 60.0
#: 잠금 상한. 이보다 길게 잠그면 사람이 비밀번호를 기억해 내고도 못 들어와 운영이 막힌다.
MAX_LOCK_SECONDS = 900.0
#: 기억해 둘 아이디 수 상한. 임의의 문자열을 계속 보내 메모리를 불리지 못하게 한다.
MAX_TRACKED_IDS = 1024
#: 세는 열쇠로 쓸 아이디 길이 상한(긴 문자열을 그대로 키로 두지 않는다).
MAX_KEY_LENGTH = 128

#: 아이디 → (연속 실패 수, 마지막 실패 시각 monotonic). 값에 비밀번호는 절대 넣지 않는다.
_FAILURES: dict[str, tuple[int, float]] = {}


class LoginRequest(BaseModel):
    """로그인 요청 본문.

    `user`·`password` 에 길이 제약(min/max_length)을 **일부러 걸지 않았다.** 제약에 걸리면
    FastAPI 의 422 본문이 문제가 된 입력값을 그대로 되돌려 준다 — 비밀번호가 응답에
    실린다. 길이 검사는 아래 핸들러에서 하고, 걸리면 값 없이 401 로 답한다.
    """

    user: str
    password: str


class LoginResponse(BaseModel):
    """성공 응답. 해시·토큰은 담지 않는다."""

    user: str
    display_name: str
    role: str


def reset_login_throttle() -> None:
    """연속 실패 기록을 비운다(테스트·운영자용)."""
    _FAILURES.clear()


def _key(user: str) -> str:
    return user[:MAX_KEY_LENGTH]


def lock_seconds_for(count: int) -> float:
    """연속 실패 `count` 회일 때 잠글 시간 (S11).

    5회에서 60초, 6회 120초, 7회 240초 … 15분에서 멈춘다. 배로 늘리는 이유는 간단하다 —
    고정 시간이면 「한도만큼 틀리고 그만큼 쉬기」를 반복해 사실상 제한 없이 두드릴 수 있다.
    """
    if count < MAX_FAILURES:
        return 0.0
    return min(LOCK_SECONDS * (2 ** (count - MAX_FAILURES)), MAX_LOCK_SECONDS)


def _locked(user: str) -> bool:
    entry = _FAILURES.get(_key(user))
    if entry is None:
        return False
    count, last_failed_at = entry
    if count < MAX_FAILURES:
        return False
    if time.monotonic() - last_failed_at >= lock_seconds_for(count):
        # 잠금이 풀렸다. **기록은 지우지 않는다** — 지우면 다시 5회를 쓸 수 있어
        # 늘어남이 뜻을 잃는다. 다음 실패는 더 오래 잠긴다. 성공하면 그때 지운다.
        return False
    return True


def _note_failure(user: str) -> None:
    now = time.monotonic()
    key = _key(user)
    count, _ = _FAILURES.get(key, (0, now))
    _FAILURES[key] = (count + 1, now)
    if len(_FAILURES) > MAX_TRACKED_IDS:
        _prune(now)


def _prune(now: float) -> None:
    """잠금이 풀린 기록부터 버린다. 그래도 넘치면 통째로 비운다.

    비우는 쪽(잠금 해제)을 고른 이유: 이 표는 방어 장치일 뿐이라 기억을 잃어도 로그인은
    정상 동작한다. 반대로 무한히 쌓게 두면 그쪽이 진짜 공격 수단이 된다.

    여기서는 **상한(15분)이 지난 것**만 버린다. 잠금이 방금 풀린 기록을 버리면 늘어남이
    초기화되어, 표를 일부러 넘치게 만드는 것이 곧 잠금 해제 수단이 된다.
    """
    for key, (count, last_failed_at) in list(_FAILURES.items()):
        if count < MAX_FAILURES or now - last_failed_at >= MAX_LOCK_SECONDS:
            _FAILURES.pop(key, None)
    if len(_FAILURES) > MAX_TRACKED_IDS:
        _FAILURES.clear()


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail)


class PasswordChangeRequest(BaseModel):
    """내 비밀번호 바꾸기(44차 S5). 로그인과 같이 길이 제약을 일부러 걸지 않는다 — 422 본문이 입력값(비밀번호)을 되돌려 주지 않게."""

    old_password: str
    new_password: str


#: 지금 비밀번호가 틀렸을 때 — 401 이 아니다(화면이 401 을 「세션이 끝났습니다」로 읽는다).
WRONG_OLD_PASSWORD_DETAIL = "지금 비밀번호가 맞지 않습니다."


class MeResponse(BaseModel):
    user: str | None = None
    role: str | None = None
    display_name: str | None = None


@router.get("/api/auth/me", response_model=MeResponse)
def me() -> MeResponse:
    """서버가 지금 보는 나(45차 M4) — 역할은 `users.json` 기준(미들웨어가 세션 역할을 파일 값으로 바꿔 둔다).

    관리자가 역할을 바꾸면 서버는 바로 막는데, 화면 머리 표시 · 잠금은 다시 로그인할 때까지 옛 역할이었다.
    화면이 열릴 때 · 창으로 돌아올 때 이것을 읽어 표시를 맞춘다. 서명된 신원이 아니면(로컬 · 토큰) 빈 값."""
    who = requester.current()
    if who is None or who.source != "signed":
        return MeResponse()
    record = user_service.account_snapshot().get(who.user)
    return MeResponse(user=who.user, role=who.role, display_name=record.display_name if record else None)


@router.post("/api/auth/password", status_code=204)
def change_password(body: PasswordChangeRequest) -> Response:
    """로그인한 사람이 **자기** 비밀번호를 바꾼다(44차 S5) — 열람자도 된다(`identity.SELF_SERVICE_PATHS`).

    지금 비밀번호 확인 · 규칙은 관리 명령(`manage_users.py passwd`)과 같은 `user_service.validate_password` · 틀리면 로그인과 같은
    연속 실패 잠금 · 활동 기록에는 요청만 남는다(값 없음 · 미들웨어). 남의 비밀번호 초기화는 관리자 서버 명령 그대로."""
    who = requester.current()
    if who is None or who.source != "signed":
        raise HTTPException(status_code=403, detail="로그인한 계정에서만 비밀번호를 바꿀 수 있습니다.")
    user = who.user
    if _locked(user):
        raise HTTPException(status_code=429, detail=TOO_MANY_ATTEMPTS_DETAIL)
    try:
        outcome = user_service.authenticate(user, body.old_password)
    except user_service.UserStoreError as exc:
        logger.error("사용자 파일을 읽지 못해 비밀번호를 바꾸지 못했습니다: %s", exc)
        raise HTTPException(status_code=500, detail="사용자 정보를 읽지 못했습니다. 관리자에게 문의하세요.")
    if outcome.account is None or outcome.account.source != "file":
        _note_failure(user)
        logger.info("비밀번호 바꾸기 실패(지금 비밀번호 틀림): %s", user)
        raise HTTPException(status_code=400, detail=WRONG_OLD_PASSWORD_DETAIL)
    if body.new_password == body.old_password:
        raise HTTPException(status_code=400, detail="새 비밀번호가 지금 비밀번호와 같습니다.")
    try:
        user_service.set_password(user, body.new_password)
    except user_service.UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc))  # 사유만(값 없음 — UserError 는 값을 담지 않는다)
    _FAILURES.pop(_key(user), None)
    logger.info("비밀번호를 바꿨습니다: %s", user)
    return Response(status_code=204)


@router.post("/api/auth/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    """아이디·비밀번호를 판정한다. 세션 쿠키는 **프런트엔드가** 만든다(계약서 2장).

    `async def` 가 아니라 **일반 함수**다. pbkdf2 600,000회는 0.2초 동안 CPU 를 붙잡는데,
    코루틴으로 두면 그동안 다른 요청이 전부 멈춘다. 일반 함수면 FastAPI 가 스레드풀에서 돌린다.
    """
    user = body.user.strip()
    password = body.password

    if _locked(user):
        logger.warning("로그인 시도가 잠긴 상태에서 다시 들어왔습니다(연속 실패 %d회 이상).", MAX_FAILURES)
        raise _unauthorized(TOO_MANY_ATTEMPTS_DETAIL)

    try:
        outcome = user_service.authenticate(user, password)
    except user_service.UserStoreError as exc:
        # 계정 파일을 못 읽는 것은 「비밀번호가 틀림」이 아니다. 운영자가 알아야 고친다.
        logger.error("사용자 파일을 읽지 못해 로그인을 처리하지 못했습니다: %s", exc)
        raise HTTPException(status_code=500, detail="사용자 정보를 읽지 못했습니다. 관리자에게 문의하세요.")

    if outcome.account is None:
        _note_failure(user)
        if outcome.reason in KNOWN_ACCOUNT_REASONS:
            # 그 아이디가 실제로 있을 때만 값을 남긴다.
            logger.info("로그인 실패(%s): %s", outcome.reason, user)
        else:
            # 없는 아이디·빈 값은 값을 남기지 않는다(비밀번호를 아이디 칸에 친 경우가 있다).
            logger.info("로그인 실패(%s): 아이디 값은 남기지 않습니다.", outcome.reason)
        raise _unauthorized(INVALID_CREDENTIALS_DETAIL)

    _FAILURES.pop(_key(user), None)
    account = outcome.account
    logger.info("로그인 성공: %s (%s · %s)", account.user, account.role, account.source)
    return LoginResponse(user=account.user, display_name=account.display_name, role=account.role)
