"""요청을 보낸 사람이 «인증된 이름»으로 누구인지 (S12).

배경
----
검토자·결정자 이름은 지금까지 **본문에 실려 온 문자열**이다(`reviewer`·`decided_by`).
화면이 채워 보내는 값이라, 중계를 거치는 배포에서도 그것은 클라이언트의 «주장»일 뿐이다.
열람자 계정으로 로그인한 사람이 본문에 `reviewer: "박부장"` 이라고 적어 보내면 기록에는
박부장이 판단한 것으로 남는다.

미들웨어는 이미 서명된 신원을 확인했다(`core/auth.py`). 그 값을 `request.state` 로 넘겨,
저장할 때 **누가 실제로 눌렀는지**를 한 칸 더 남긴다.

`reviewer` 를 대체하지 않는 이유
--------------------------------
둘은 다른 것이다. `reviewer` 는 「이 판단에 책임지는 사람」이고 담당자가 동료 이름을 적을
수도 있다(현장에서 실제로 그렇게 쓴다). `recorded_by` 는 「이 요청을 보낸 계정」이다.
합치면 둘 중 하나의 뜻이 사라진다. 그래서 **필드를 더한다** — 스키마는 추가만 한다.

인증이 꺼진 로컬에서는 `local-admin` 이다 (0919.md §4-A-1).

4차에서는 여기를 `None` 으로 두고 「없는 것을 이름으로 채우면 거짓이 된다」고 적었는데,
다시 보니 그 판단이 틀렸다. `None` 은 **두 가지를 같은 값으로 뭉갠다** —
「이 필드가 생기기 전에 저장된 기록」과 「인증이 꺼진 기계에서 저장된 기록」이다.
나중에 기록을 읽는 사람은 그 둘을 구분할 수 없다.

`local-admin` 은 지어낸 이름이 아니다. 인증이 꺼진 상태에서 백엔드가 **실제로 쓰는 신원**
그대로다(`identity.resolve` 1항). 「인증 없이 돌던 기계에서 저장됐다」는 사실을 정확히 말한다.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.core import identity as identity_module

#: 지금 요청을 보낸 사람. 미들웨어가 넣고 서비스가 읽는다.
#:
#: `request.state` 만으로는 부족했다. 문서 업로드·승인·폐기, 조치 생성·수정·삭제 같은 쓰기는
#: 라우트 → `do_*` 도우미 → 서비스로 세 겹을 지나는데, 그 전부에 인자를 하나씩 더하면
#: 여섯 라우트 × 세 겹이 바뀐다. 「기능 변경 없는 대규모 손질 금지」에 걸리고, 무엇보다
#: **인자 하나를 빠뜨린 경로가 조용히 `None` 을 저장한다** — 기록이 비는 것을 아무도 모른다.
#:
#: contextvars 는 스레드풀(`run_in_threadpool`)을 건너가도 값이 따라간다(anyio 가 컨텍스트를
#: 복사한다 — 실측 확인). 그래서 CPU 를 오래 쓰는 문서 파싱 경로에서도 그대로 읽힌다.
_CURRENT: contextvars.ContextVar["identity_module.Identity | None"] = contextvars.ContextVar(
    "bidpilot_current_identity", default=None
)


@contextmanager
def acting_as(who: "identity_module.Identity | None") -> Iterator[None]:
    """이 블록 안의 저장에 `who` 를 기록한다. 미들웨어가 요청 하나를 감쌀 때 쓴다."""
    token = _CURRENT.set(who)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def current() -> "identity_module.Identity | None":
    """지금 요청의 신원. 인증이 꺼졌거나 요청 밖이면 None."""
    return _CURRENT.get()


def current_recorded_by() -> str | None:
    """지금 요청을 보낸 «인증된» 계정 아이디. 인증이 꺼졌거나 요청 밖이면 None.

    서비스가 요청 객체를 받지 않고도 「누가 저장했는가」를 남길 수 있게 한다.
    `recorded_by(request)` 와 같은 값이다 — 판정 규칙을 두 벌 두지 않는다.
    """
    who = _CURRENT.get()
    if who is None:
        return None  # 요청 밖(스크립트·테스트) — 기록할 요청 자체가 없다.
    return who.user


def recorded_by(request: Any) -> str | None:
    """이 요청을 보낸 «인증된» 계정 아이디. 인증이 꺼져 있으면 None.

    `request` 는 Starlette `Request` 지만 타입을 묶지 않는다 — 이 모듈이 라우팅 계층에
    의존하지 않게 하려는 것이고, 테스트에서 가짜 객체를 넣기도 쉽다.
    """
    state = getattr(request, "state", None)
    who = getattr(state, "identity", None) if state is not None else None
    if not isinstance(who, identity_module.Identity):
        return None
    # `local` 이면 `local-admin`, `token` 이면 `api-token` 이 그대로 남는다. 둘 다 사람 이름은
    # 아니지만 **무엇으로 저장됐는지**를 정확히 말한다 — 인증이 꺼진 기계인지, 스크립트인지.
    return who.user
