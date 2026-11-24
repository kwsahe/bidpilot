"""API 토큰 인증 미들웨어 (사내 호스팅 대비).

배경
----
백엔드에는 원래 인증이 없다. 로컬에서만 띄우는 동안은 문제가 없지만, 사내 도구로
호스팅하는 순간 URL만 알면 누구나 회사자료를 읽고 쓸 수 있게 된다.

구조상 브라우저는 이 백엔드를 **직접 부르지 않는다**. Next.js 서버가 중계하면서
비밀 토큰 헤더를 붙인다. 따라서 백엔드는 "토큰이 맞으면 통과, 아니면 거부"만 하면 된다.

동작 원칙
--------
- `API_TOKEN` 이 비어 있으면 **아무것도 막지 않는다**. 로컬 개발·기존 테스트가 그대로 돈다.
- 설정돼 있으면 `Authorization: Bearer <token>` 또는 `X-API-Token: <token>` 을 요구한다.
- 비교는 `hmac.compare_digest` 로 상수 시간에 한다(타이밍 공격 방지).
- 실패하면 401 JSON 을 돌려준다. **토큰 값은 응답에도 로그에도 절대 남기지 않는다**
  (CLAUDE.md 21 — 로그에 인증키 출력 금지).

공개 예외는 두 가지뿐이다.

- `GET /health` — 호스팅 플랫폼의 헬스체크가 토큰 없이 찔러야 한다.
- `OPTIONS` (CORS preflight) — 브라우저는 preflight 에 인증 헤더를 싣지 않으므로
  여기서 401 을 주면 정상 요청까지 막힌다. CORSMiddleware 가 응답하도록 통과시킨다.

`/docs`, `/redoc`, `/openapi.json` 은 **일부러 예외로 두지 않았다**. 이 문서 화면은
회사자료를 다루는 모든 엔드포인트의 경로·스키마·예시를 그대로 노출한다. 토큰을 설정한
호스팅 환경이라면 그 지도부터 잠그는 편이 안전하다. (토큰 미설정 로컬에서는 지금처럼
그냥 열린다.)

신원·역할·기록 (계약서 4·5·6장)
------------------------------
토큰 하나로는 **누가** 보냈는지 알 수 없다. 토큰 검사를 통과한 뒤 세 가지를 더 한다.

1. 신원 판정 — `core/identity.py`. 서명된 헤더가 맞으면 그 사람으로, 헤더가 없으면
   토큰 보유자(관리자)로 본다. 반쪽이거나 서명이 틀리면 401.
2. 역할 검사 — viewer 는 조회만, editor 는 쓰기까지, 조직 관리·활동 기록은 admin 만. 위반은 403.
3. 활동 기록 — 쓰기 요청이면 응답 상태가 정해진 뒤 한 줄 남긴다(`services/audit_log_service.py`).

세션 무효화 (S3)
---------------
세션은 12시간짜리라, 계정을 끄거나 역할을 낮춰도 이미 발급된 세션에는 반영되지 않았다.
퇴사자의 브라우저가 반나절 동안 그대로 열려 있는 셈이다. 그래서 **서명된 신원이 올 때마다**
`users.json` 을 다시 본다(파일이 그대로면 앞서 읽은 것을 쓴다 — `user_service.live_role`).

- 계정이 없어졌거나 꺼져 있으면 **401**. 403 이 아니다 — 할 수 없는 일을 하려는 것이 아니라
  더 이상 그 사람이 아니기 때문이다.
- 역할이 바뀌었으면 **파일 쪽을 쓴다.** 세션에 적힌 역할은 로그인 시점의 사진일 뿐이다.

신원을 라우트로 (S12)
--------------------
판정한 신원을 `scope["state"]["identity"]` 에 넣는다. 라우트는 `request.state.identity` 로
읽어 「누가 저장했는가」를 본문의 주장이 아니라 **인증된 이름**으로 남길 수 있다.

**셋 다 `API_TOKEN` 이 설정된 경우에만 동작한다.** 토큰이 비어 있으면 예전과 똑같이
아무 검사도 하지 않고, 기록 파일도 만들지 않는다 — 로컬 개발과 기존 테스트는 인증이 꺼진
상태로 돌기 때문에, 여기서 파일을 쓰기 시작하면 「막지 않는다」와 별개로 동작이 달라진다.
"""

from __future__ import annotations

import hmac
from urllib.parse import parse_qs

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import identity as identity_module
from app.core import requester
from app.core.config import get_settings
from app.services import audit_log_service, user_service

# 토큰 없이 열어 두는 경로. 값 비교는 정확히 일치 + 끝의 슬래시만 허용한다.
PUBLIC_PATHS: frozenset[str] = frozenset({"/health"})

# preflight 는 인증 헤더를 실을 수 없다. CORS 미들웨어가 처리하도록 통과시킨다.
PUBLIC_METHODS: frozenset[str] = frozenset({"OPTIONS"})

_UNAUTHORIZED_DETAIL = "인증 토큰이 필요합니다. Authorization: Bearer <token> 또는 X-API-Token 헤더를 보내세요."

#: 세션은 살아 있는데 계정이 없어졌거나 꺼진 경우 (S3). 어느 쪽인지는 알려주지 않는다 —
#: 「그 아이디는 있는데 꺼졌다」는 것도 정보다.
_STALE_SESSION_DETAIL = "계정 정보가 바뀌었습니다. 다시 로그인해 주세요."
#: 서명된 세션을 쥔 사람의 계정이 꺼졌을 때(45차 L9 — 「세션이 끝났습니다 · 다시 로그인」으로 보여 같은 비밀번호로 다시 들어가려 했다).
#: 이미 그 계정으로 들어와 있던 사람에게만 가는 말이라 「그 아이디가 있다」를 새로 알려 주지 않는다.
DISABLED_ACCOUNT_DETAIL = "계정이 꺼졌습니다 — 관리자에게 문의하세요."


def _confirm_account(who: identity_module.Identity) -> identity_module.Identity | None:
    """`users.json` 기준으로 신원을 다시 확인한다. 통과하지 못하면 None (S3).

    역할이 세션과 다르면 **파일 쪽**을 쓴다. 세션의 역할은 로그인 시점의 사진일 뿐이고,
    권한을 낮춘 뒤에도 반나절 동안 옛 권한이 사는 것이 이 항목의 본체다.
    """
    role = user_service.live_role(who.user)
    if role in (user_service.LIVE_UNKNOWN, user_service.LIVE_INACTIVE):
        return None
    if role not in identity_module.ROLES:
        # 파일에 오타가 들어간 역할. 낮은 권한으로 낮추지 않고 막는다 (identity.ROLES 와 같은 원칙).
        return None
    if role == who.role:
        return who
    return identity_module.Identity(who.user, role, who.source)


def token_required() -> bool:
    """토큰 인증이 켜져 있는지. `API_TOKEN` 이 비어 있으면 꺼진 상태다."""
    return bool(get_settings().api_token.strip())


def _normalized_path(scope: Scope) -> str:
    """서브패스 배포(root_path)를 감안한 경로."""
    path: str = scope.get("path", "") or ""
    root_path: str = scope.get("root_path", "") or ""
    if root_path and path.startswith(root_path):
        path = path[len(root_path) :] or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


def is_public(scope: Scope) -> bool:
    """토큰 없이 통과시킬 요청인지."""
    if scope.get("method", "") in PUBLIC_METHODS:
        return True
    return _normalized_path(scope) in PUBLIC_PATHS


def extract_token(headers: Headers) -> str | None:
    """요청 헤더에서 토큰을 꺼낸다. 없으면 None."""
    direct = headers.get("x-api-token")
    if direct and direct.strip():
        return direct.strip()

    authorization = headers.get("authorization")
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    return None


def _matches(candidate: str, expected: str) -> bool:
    """상수 시간 비교. 토큰에 비ASCII 문자가 있어도 안전하도록 바이트로 비교한다."""
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def organization_id_of(scope: Scope, headers: Headers) -> str | None:
    """기록에 남길 조직 id. 쿼리 파라미터 → 헤더 순으로 찾고 없으면 None.

    `X-Organization-Id` 는 지금 **아무도 요청에 붙이지 않는다**(응답에만 찍힌다). 계약서 6장이
    허용한 자리라 받아 두기만 한다 — 나중에 본문으로만 조직을 넘기는 호출을 기록에 남기려면
    그쪽이 이 헤더를 붙이면 된다.

    본문은 보지 않는다. 미들웨어에서 요청 본문을 읽으면 그 뒤 라우트가 같은 본문을
    다시 읽지 못한다 — 파일 업로드가 있는 이 앱에서는 특히 위험하다. 본문에만 조직 id 가
    실리는 호출은 기록에 `null` 로 남는다(계약서 6장이 허용하는 「없음」).
    """
    raw_query = scope.get("query_string", b"") or b""
    try:
        params = parse_qs(raw_query.decode("utf-8", errors="replace"))
    except (UnicodeDecodeError, ValueError):
        params = {}
    values = params.get("organization_id") or []
    candidate = values[0] if values else headers.get("x-organization-id")
    return audit_log_service.sanitize_organization_id(candidate)


class TokenAuthMiddleware:
    """`API_TOKEN` 이 설정된 경우에만 동작하는 순수 ASGI 미들웨어.

    BaseHTTPMiddleware 대신 순수 ASGI 로 둔 이유: 이 앱에는 파일 내려받기
    (StreamingResponse / Content-Disposition) 엔드포인트가 있어 응답 본문을 다시
    감싸지 않는 편이 안전하다. 신원·역할·기록을 얹을 때도 이 구조를 유지한다 —
    상태 코드만 엿보고 본문은 그대로 흘려보낸다.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or is_public(scope) or not token_required():
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        expected = get_settings().api_token.strip()
        supplied = extract_token(headers)
        if supplied is None or not _matches(supplied, expected):
            # 응답에는 토큰과 관련된 어떤 값도 싣지 않는다(입력값 에코 금지).
            await _reject(
                scope,
                receive,
                send,
                401,
                _UNAUTHORIZED_DETAIL,
                headers={"WWW-Authenticate": "Bearer"},
            )
            return

        # --- 여기부터는 「우리 중계자가 보낸 요청」이 확실하다. 이제 누구인지 본다. ---
        try:
            who = identity_module.resolve(headers, expected)
        except identity_module.IdentityError as exc:
            # 신원을 믿을 수 없으면 401 이다(403 아님). 누구인지 모르니 기록도 남기지 않는다 —
            # 확인되지 않은 이름을 활동 기록에 적으면 그 기록 전체를 믿을 수 없게 된다.
            await _reject(scope, receive, send, 401, exc.detail)
            return

        # 서명된 신원은 «지금 파일»과 대조한다 (S3).
        if who.source == "signed":
            confirmed = _confirm_account(who)
            if confirmed is None:
                inactive = user_service.live_role(who.user) == user_service.LIVE_INACTIVE
                await _reject(scope, receive, send, 401, DISABLED_ACCOUNT_DETAIL if inactive else _STALE_SESSION_DETAIL)
                return
            who = confirmed

        # 라우트가 「누가 보냈는지」를 알 수 있게 넘긴다 (S12).
        # Starlette 는 `scope["state"]` 를 `request.state` 로 보여 준다. 본문의 이름 대신
        # 이 값을 쓰면 저장 기록이 «클라이언트의 주장»이 아니라 인증된 사실이 된다.
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["identity"] = who

        method: str = scope.get("method", "") or ""
        path = _normalized_path(scope)
        # `?refresh=true` 가 붙은 목록 조회는 GET 이어도 쓰기다 (S8). 역할 검사와 기록에서
        # 같은 판정을 써야 한다 — 한쪽만 고치면 「막았는데 기록은 없는」 상태가 된다.
        query = (scope.get("query_string", b"") or b"").decode("utf-8", errors="replace")
        writing = identity_module.is_write_request(method, path, query)
        reason = identity_module.forbidden_reason(who, path, method, query)
        if reason is not None:
            await _reject(scope, receive, send, 403, reason)
            # 막힌 요청도 «쓰기 시도»였다면 남긴다. 조회 거절(viewer 의 활동기록 열람 시도 등)은
            # 계약서 6장이 기록 대상에서 제외한 GET 이라 남기지 않는다.
            if writing:
                self._record(who, method, path, scope, headers, 403)
            return

        if not writing:
            # 조회도 감싼다 — 서비스가 「지금 누구」를 물으면 같은 답이 나와야 한다.
            with requester.acting_as(who):
                await self.app(scope, receive, send)
            return

        # 쓰기 요청은 «결과»까지 기록한다. 상태 코드만 엿보고 본문은 건드리지 않는다.
        seen: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                seen["status"] = int(message["status"])
            await send(message)

        try:
            # 저장하는 서비스가 요청 객체 없이도 「누가 저장했는가」를 알 수 있게 한다 (S12).
            with requester.acting_as(who):
                await self.app(scope, receive, send_wrapper)
        finally:
            # 예외가 위로 빠져나가면 응답 시작조차 못 본다. 그때는 서버 오류로 남긴다.
            self._record(who, method, path, scope, headers, seen.get("status", 500))

    def _record(
        self,
        who: identity_module.Identity,
        method: str,
        path: str,
        scope: Scope,
        headers: Headers,
        status: int,
    ) -> None:
        """활동 기록 한 줄. 실패해도 요청에는 영향을 주지 않는다(기록은 부가 기능)."""
        audit_log_service.append(
            user=who.user,
            role=who.role,
            method=method,
            path=path,
            organization_id=organization_id_of(scope, headers),
            status=status,
        )


async def _reject(
    scope: Scope,
    receive: Receive,
    send: Send,
    status_code: int,
    detail: str,
    *,
    headers: dict[str, str] | None = None,
) -> None:
    """한국어 사유만 담은 JSON 응답. 입력값(토큰·서명·사용자명)은 절대 싣지 않는다."""
    response = JSONResponse(status_code=status_code, content={"detail": detail}, headers=headers)
    await response(scope, receive, send)
