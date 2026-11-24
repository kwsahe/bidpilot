"""사람이 입력하는 문자열의 공통 제약 (ISSUE-013).

## 왜 필요한가

두 가지가 같이 새고 있었다.

1. **공백만 있는 이름이 저장된다.** `reviewer="   "`, `decided_by="\\t\\n"`,
   `ActionCreateRequest(title="          ")` 가 전부 201 로 통과했다. `min_length=1` 은
   길이만 보기 때문에 공백 문자를 막지 못한다. BLOCKER 를 CLEARED 로 바꾼 사람이
   「   」으로 기록되면 나중에 누가 판단했는지 추적할 방법이 없다 — 이 시스템에서
   마지막 책임은 사람에게 있다는 전제(CLAUDE.md §I)가 무너진다.

2. **목록·자유 입력에 상한이 없다.** `reasons: list[str]` 은 항목 수(20)만 막고
   항목 하나의 길이는 무제한이라 1MB 짜리 사유 20개가 그대로 JSON 파일에 들어간다.
   주소·전화·사업영역·서식 `manual` dict 도 마찬가지였다.

## 쓰는 법

`str` 대신 아래 별칭을 쓴다. `strip_whitespace=True` 라서 앞뒤 공백은 저장 전에
사라지고, 공백만 있는 값은 `min_length=1` 에 걸려 422 가 된다.

    reviewer: PersonName
    owner: PersonName | None = None
    reasons: list[ShortText] = Field(default_factory=list, max_length=20)

`Field(...)` 로 다시 `max_length` 를 주면 별칭의 상한을 덮어쓰므로, 길이를 바꿔야 하면
여기에 별칭을 하나 더 만든다.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

#: 사람 이름 — 검토자·결정자·담당자. 공백만 있는 값 금지.
PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]

#: 제목 한 줄 — 조치 항목 등.
TitleText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

#: 목록 안의 짧은 문자열 — 사유·사업영역·인증 등. 항목 하나의 상한.
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]

#: 주소·웹사이트처럼 한 줄이지만 비워 둘 수 있는 값. `| None` 과 함께 쓴다.
LineText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

#: 전화번호.
PhoneText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]

#: 서식 채움값처럼 담당자가 직접 넣는 짧은 값 (대표자명·법인등록번호 등).
FillText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]

#: 서식 채움값의 키. 서식이 정의한 자리 이름이라 공백만 있는 키는 의미가 없다.
FillKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
