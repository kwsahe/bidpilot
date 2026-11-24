"""요청자의 신원과 역할을 정한다 (계약서 4·5장).

배경
----
`auth.py` 의 토큰 검사는 「이 요청이 우리 중계자에게서 왔는가」만 판정한다. 토큰은 하나뿐이라
**누가** 보냈는지는 알 수 없다. 사내에서 여러 사람이 같은 화면을 쓰기 시작하면 그것으로는
부족하다 — 조회만 해야 할 사람이 회사자료를 지울 수 있기 때문이다.

그래서 중계자(Next.js)가 토큰 옆에 신원 헤더 세 개를 더 붙인다.

    X-User            계정 아이디
    X-User-Role       viewer | editor | admin
    X-User-Signature  HMAC-SHA256(key = API_TOKEN, msg = "{user}\\n{role}") 의 소문자 hex

브라우저는 이 백엔드를 직접 부르지 않으므로, 헤더를 위조하려면 `API_TOKEN` 을 알아야 한다.
토큰을 아는 쪽은 이미 전권이므로 이 서명은 「토큰 보유자가 스스로 권한을 줄여 선언한 것」을
그대로 믿기 위한 장치다. 토큰 없이 밖에서 역할을 올리는 것은 막는다.

왜 신원 판정을 여기 따로 두는가
------------------------------
미들웨어(`auth.py`)는 ASGI 배관이라 테스트하기 번거롭다. 판정 규칙만 순수 함수로 떼어 두면
헤더 조합별 기대 동작을 직접 검사할 수 있다. 미들웨어는 이 함수를 부르기만 한다.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from urllib.parse import parse_qs

from starlette.datastructures import Headers

# 역할은 셋뿐이다. 모르는 값은 «낮은 권한»으로 낮추지 않고 거절한다 —
# 오타 하나가 조용히 권한을 바꾸는 것보다 로그인이 실패하는 편이 낫다.
ROLES: tuple[str, ...] = ("viewer", "editor", "admin")

# 신원 헤더 이름(소문자). 계약서 3장과 한 글자도 다르면 안 된다.
USER_HEADER = "x-user"
ROLE_HEADER = "x-user-role"
SIGNATURE_HEADER = "x-user-signature"

# 읽기만 하는 메서드. 이 밖은 전부 「쓰기」로 본다(기록·역할 검사 대상).
READ_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

# 조직 경로에서 «회사 자체를 다루는» 꼬리. 이것만 관리자 전용이다.
#
# 처음에는 `/api/organizations` 아래 POST·PATCH·DELETE 를 통째로 관리자 전용으로 뒀는데,
# 그러면 **편집자가 회사자료를 못 올린다.** 그 접두어 아래에는 자료 업로드·본문 추출·승인·
# 폐기·색인 재작성·실적원장 가져오기가 전부 들어 있기 때문이다.
# 0917.md §4-5-4 는 더 좁게 적었다 — 「editor: 분석·저장·**업로드** 등 쓰기
# (조직 생성·비활성·사용자 관리 제외)」. 그 문장을 따른다.
ORG_LIFECYCLE_TAILS: frozenset[str] = frozenset({"activate", "deactivate"})

# 관리자만 다룰 수 있는 경로는 두 갈래다 (`is_admin_only`).
# - 회사 자체 `/api/organizations`: 만들기·정보 고치기·켜고 끄기. 그 아래 자료·색인·원장은
#   편집자의 일이고, 조회(GET)는 누구나 한다.
# - 활동 기록 `/api/audit-log`: 누가 무엇을 했는지 담긴 목록이라 조회조차 관리자만 본다.
FORBIDDEN_WRITE_DETAIL = "이 작업은 편집자 이상만 할 수 있습니다."
FORBIDDEN_ADMIN_DETAIL = "이 작업은 관리자만 할 수 있습니다."

#: 서명은 소문자 hex 64자다. 형식을 «먼저» 본다 (S5).
#:
#: `hmac.compare_digest` 는 두 str 을 받을 때 둘 다 ASCII 여야 한다. 비ASCII 가 섞이면
#: TypeError 가 나고 미들웨어 밖으로 새어 500 이 된다 — 헤더 하나로 서버 오류를 만들 수 있다.
#: 어차피 hex 가 아닌 서명은 절대 맞지 않으므로, 모양이 틀리면 그 자리에서 401 이다.
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{64}$")

_BAD_SIGNATURE_DETAIL = "신원 서명이 올바르지 않습니다."
_BAD_ROLE_DETAIL = "알 수 없는 역할입니다."
_PARTIAL_IDENTITY_DETAIL = "신원 정보가 불완전합니다."


@dataclass(frozen=True)
class Identity:
    """이 요청을 보낸 사람. `source` 는 «무엇을 근거로 믿는가»다.

    - `local`  : `API_TOKEN` 이 없다 → 인증이 꺼진 로컬 개발. 전부 허용한다.
    - `signed` : 서명된 신원 헤더가 맞았다 → 그 사람의 역할을 그대로 쓴다.
    - `token`  : 신원 헤더 없이 토큰만 왔다 → 스크립트·운영자 직접 호출. 관리자로 본다.
    """

    user: str
    role: str
    source: str

    @property
    def can_write(self) -> bool:
        return self.role in ("editor", "admin")

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class IdentityError(Exception):
    """신원을 믿을 수 없다 → 401. 사유 문장은 한국어이며 입력값을 되비추지 않는다."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def signature_for(user: str, role: str, api_token: str) -> str:
    """계약서 3장의 서명. 입력 문자열은 정확히 `{user}\\n{role}` 이고 끝에 개행이 없다."""
    message = f"{user}\n{role}".encode("utf-8")
    return hmac.new(api_token.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _header(headers: Headers, name: str) -> str:
    """헤더 값에서 앞뒤 공백을 떼고 돌려준다. 빈 값은 「없음」과 같게 본다."""
    return (headers.get(name) or "").strip()


def resolve(headers: Headers, api_token: str) -> Identity:
    """헤더 → 신원. 계약서 4장의 판정 순서를 그대로 따른다.

    1. 토큰이 비어 있으면 인증 자체가 꺼진 상태다 → 로컬 관리자.
    2. 세 헤더가 모두 있으면 서명을 다시 계산해 상수 시간 비교한다.
    3. 하나도 없으면 토큰 보유자(스크립트·운영자)로 본다.
    4. 일부만 있으면 401. 반쪽 신원은 믿지 않는다 — 헤더 하나를 떼서 역할 검사를
       피해 가는 길을 남기지 않기 위해서다.
    """
    if not api_token.strip():
        return Identity("local-admin", "admin", "local")

    user = _header(headers, USER_HEADER)
    role = _header(headers, ROLE_HEADER)
    signature = _header(headers, SIGNATURE_HEADER)
    present = [bool(user), bool(role), bool(signature)]

    if all(present):
        # 모양부터 본다 — 비ASCII 서명이 오면 compare_digest 가 TypeError 로 터진다 (S5).
        if not _SIGNATURE_RE.match(signature):
            raise IdentityError(_BAD_SIGNATURE_DETAIL)
        expected = signature_for(user, role, api_token.strip())
        # 서명을 먼저 본다. 역할 오타를 서명 없이 확인할 수 있게 하지 않는다.
        if not hmac.compare_digest(signature, expected):
            raise IdentityError(_BAD_SIGNATURE_DETAIL)
        if role not in ROLES:
            raise IdentityError(_BAD_ROLE_DETAIL)
        return Identity(user, role, "signed")

    if not any(present):
        return Identity("api-token", "admin", "token")

    raise IdentityError(_PARTIAL_IDENTITY_DETAIL)


#: 조회처럼 생겼지만 바깥을 바꾸는 GET (S8).
#:
#: `GET /api/procurements?refresh=true` 는 나라장터를 실제로 부르고 그 결과로 Git 이
#: 추적하는 캐시 파일을 덮어쓴다. 메서드만 보면 조회라서 열람자도 부를 수 있었고,
#: 활동 기록에도 남지 않았다. 쿠키가 `SameSite=Lax` 라 다른 사이트의 «링크»만으로도
#: 도달한다 — 누가 링크를 눌렀는지도 알 수 없이 목록이 바뀌는 셈이다.
#:
#: 새 경로는 `POST /api/procurements/refresh` 다. 이 목록은 **옛 경로를 위한 것**이고,
#: 화면이 POST 로 옮겨 간 뒤에도 남겨 둔다 — 스크립트가 옛 주소를 계속 쓸 수 있다.
WRITE_LIKE_GET_PATHS: frozenset[str] = frozenset(
    {"/api/procurements", "/api/support-programs", "/api/business-opportunities"}
)


def is_write(method: str) -> bool:
    """쓰기 요청인지. 역할 검사와 활동 기록의 기준이다."""
    return method.upper() not in READ_METHODS


#: 프레임워크가 «참»으로 읽는 값. FastAPI 의 bool 파싱과 같은 집합이어야 한다 (N1).
#:
#: 예전에는 여기를 문자열 부분 대조로 했고 `1 · true · yes · on` 만 봤다. 그런데 pydantic 은
#: `t` 와 `y` 도 참으로 읽고, `%31` 은 URL 디코딩을 거쳐 `1` 이 된다. 그래서
#: `?refresh=t` 는 **판정에서는 읽기, 라우트에서는 새로고침**이 됐다 — 열람자가 막히지도
#: 기록되지도 않은 채 실호출을 일으킬 수 있었다.
#:
#: 이제 목록 GET 에서 `refresh` 자체를 없앴으므로(아래 라우트) 이 판정은 «두 번째 자물쇠»다.
#: 그래도 같은 실수를 되풀이하지 않도록 **직접 파싱해서** 프레임워크와 같은 눈으로 본다.
TRUTHY_QUERY_VALUES: frozenset[str] = frozenset({"1", "true", "t", "yes", "y", "on"})


def is_truthy_query(query: str, key: str) -> bool:
    """쿼리 문자열에서 `key` 가 «참»으로 들어왔는가. URL 디코딩까지 하고 본다."""
    try:
        values = parse_qs(query, keep_blank_values=True).get(key) or []
    except (UnicodeDecodeError, ValueError):
        # 해석할 수 없는 쿼리는 「참이 아니다」로 본다. 라우트도 그것을 읽지 못한다.
        return False
    return any(value.strip().lower() in TRUTHY_QUERY_VALUES for value in values)


def is_write_request(method: str, path: str, query: str = "") -> bool:
    """메서드와 «무엇을 하는지»를 함께 본다 (S8 · N1).

    `refresh=true` 가 붙은 목록 조회는 GET 이어도 쓰기다 — 바깥을 부르고 캐시 파일을
    덮어쓰기 때문이다. 지금은 그 라우트들이 `refresh` 를 아예 받지 않지만, 옛 주소를 쓰는
    스크립트가 남아 있을 수 있으므로 판정은 그대로 둔다.
    """
    if is_write(method):
        return True
    if path not in WRITE_LIKE_GET_PATHS:
        return False
    return is_truthy_query(query, "refresh")


def is_admin_only(path: str, method: str) -> bool:
    """관리자만 할 수 있는 요청인지 (계약서 5장).

    조직 경로에서 관리자 전용은 «회사 자체를 만들고 끄고 고치는» 것뿐이다.

        POST   /api/organizations              회사 만들기
        *      /api/organizations/{id}         회사 정보 고치기 (모든 쓰기 메서드)
        POST   /api/organizations/{id}/activate | deactivate

    그 아래 자료·색인·원장·프로필은 **편집자의 일**이다(0917.md §4-5-4 「업로드 등 쓰기」).
    회사 목록·프로필 조회는 화면이 늘 부르므로 조회는 누구나 한다.
    활동 기록은 메서드와 무관하게 전용이다 — 누가 무엇을 했는지가 그 자체로 민감하다.
    """
    if _under(path, "/api/audit-log"):
        return True
    if not _under(path, "/api/organizations"):
        return False
    verb = method.upper()
    if verb in READ_METHODS:
        return False
    rest = path[len("/api/organizations") :].strip("/")
    if not rest:
        return verb == "POST"  # 회사 만들기
    parts = rest.split("/")
    if len(parts) == 1:
        # `/api/organizations/{id}` 자체에 대한 **모든 쓰기**가 관리자 전용이다 (S6).
        #
        # 예전에는 `PATCH` 만 막았다. 그러면 나중에 누가 같은 경로에 `DELETE`(회사 삭제)나
        # `PUT`(통째로 덮어쓰기)을 더하는 순간, 아무 표시 없이 **편집자에게 열린다.**
        # 이 경로에 붙는 쓰기는 성질상 전부 「회사 자체를 다루는 일」이므로 통째로 막는다.
        # 조회는 위에서 이미 통과시켰고, 그 «아래» 자료·색인·원장은 편집자의 일이다.
        return True
    return len(parts) == 2 and parts[1] in ORG_LIFECYCLE_TAILS


def _under(path: str, prefix: str) -> bool:
    """`/api/audit-log` 자신과 그 아래 경로만 맞는다. `/api/organizations-x` 는 아니다."""
    return path == prefix or path.startswith(prefix + "/")


#: 로그인한 누구나(열람자 포함) 자기 것만 바꾸는 쓰기 — 내 비밀번호(44차 S5). 신원 확인은 라우트가 한다.
SELF_SERVICE_PATHS: frozenset[tuple[str, str]] = frozenset({("POST", "/api/auth/password")})


def forbidden_reason(identity: Identity, path: str, method: str, query: str = "") -> str | None:
    """막아야 하면 한국어 사유, 통과면 None.

    로컬(`API_TOKEN` 없음)에서는 아무것도 막지 않는다 — 호출하는 쪽에서 이미 걸러내지만,
    이 함수만 따로 불러도 같은 결론이 나오도록 여기서도 한 번 더 확인한다.

    `query` 를 받는 이유는 `?refresh=true` 때문이다 (S8). 넘기지 않으면 예전처럼
    메서드만 보고 판정한다 — 기존 호출부를 깨지 않는다.
    """
    if identity.source == "local":
        return None
    if (method.upper(), path) in SELF_SERVICE_PATHS:
        return None
    if not is_write_request(method, path, query) and not is_admin_only(path, method):
        return None
    if is_admin_only(path, method):
        return None if identity.is_admin else FORBIDDEN_ADMIN_DETAIL
    return None if identity.can_write else FORBIDDEN_WRITE_DETAIL
