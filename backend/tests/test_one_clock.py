"""앱이 판정에 쓰는 「지금」은 한 자리에서 나온다 (ISSUE-133 · prompt_07 §4-A).

## 왜 검사가 필요한가

같은 결함이 **두 번** 났다.

- 14차 ISSUE-118 — 캐시 신선도를 재는 쪽과 캐시를 심는 테스트가 다른 시계를 봐서,
  `NOW + 15분` 을 넘긴 **다음 날부터** `test_daily_digest.py` 가 빨개졌다.
- 17차 ISSUE-133 — 목록은 주입된 시계로 메모 열쇠에 `today` 를 넣고 상세는
  `datetime.now()` 로 만들어서, **9-22 가 되자** 상세가 목록 메모를 못 찾고 다시
  계산했다(48 ≠ 7). 9-21 에는 두 날짜가 같아 통과했다.

둘 다 코드가 바뀌어서가 아니라 **날짜가 지나서** 났다. 그런 결함은 고친 날에는 보이지
않으므로, 「시계가 하나인가」를 검사로 못 박아 둔다.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core import storage

PINNED = datetime(2026, 3, 4, 20, 30, tzinfo=timezone.utc)  # KST 로는 3월 5일 05:30


@pytest.fixture()
def pinned_clock(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """문 하나만 고정한다. 나머지가 따라오는지 보는 것이 이 파일의 요지다."""
    monkeypatch.setattr(storage, "utc_now", lambda: PINNED)
    return PINNED


def test_문_하나를_고정하면_판정용_시계가_전부_따라온다(pinned_clock: datetime) -> None:
    """각 모듈의 「지금」 이음매가 전부 `storage.utc_now()` 를 지나는지 본다.

    여기 이름이 적힌 함수들은 판정에 쓰이는 값을 만든다 — 캐시 신선도 · 점수 기준시각 ·
    추천 기준시각 · 체크리스트 「기한 지남」.
    """
    from app.services import action_service, opportunity_priority, procurement_service, recommendation

    assert procurement_service._now() == PINNED
    assert opportunity_priority._now(None) == PINNED
    assert recommendation._now(None) == PINNED
    assert action_service._now() == PINNED


def test_업무_날짜도_같은_문에서_나온다(pinned_clock: datetime) -> None:
    """「오늘」이 「지금」과 다른 날을 가리키면, 마감 판정과 메모 열쇠가 하루 어긋난다."""
    from datetime import date

    assert storage.kst_today() == date(2026, 3, 5)  # UTC 3-4 20:30 = KST 3-5 05:30
    assert storage.kst_today() == storage.utc_now().astimezone(storage.KST).date()


def test_앞당김은_한_번만_적용된다(monkeypatch: pytest.MonkeyPatch) -> None:
    """**이 검사가 없으면 조용히 이틀이 간다.**

    `--timeshift-days` 는 예전에 `procurement_service._now` 와 `storage.utc_now` 를 각각
    앞당겼다. 지금은 앞쪽이 뒤쪽을 부르므로 둘을 다 앞당기면 **두 번** 앞당겨진다 —
    하루를 물었는데 이틀이 오고, 그러면 「내일 빨개지는가」를 재려던 실행이 모레를 잰다.
    """
    from app.services import procurement_service

    # 고정 시각으로 잰다 — 실제 시계를 두 번 읽으면 마이크로초가 달라 우연히 틀린다(19차에 한 번 났다).
    monkeypatch.setattr(storage, "utc_now", lambda: PINNED + timedelta(days=1))
    assert procurement_service._now() == PINNED + timedelta(days=1)


# ---------------------------------------------------------------------------
# 판정 모듈에는 「지금」을 직접 읽는 자리가 없다
# ---------------------------------------------------------------------------

#: 시계 값이 **판정**(마감 여부 · PASS/CHECK/FAIL · 점수 · 메모 열쇠 · 캐시 TTL ·
#: 걸러내기 · 「다시 실행 필요」)으로 흘러가는 모듈. 17차 쓸이에서 확인한 목록이다
#: (`datetime.now(`/`date.today(` 60자리 · 판정 19 · 경계 7 · 기록 34).
#:
#: 값은 **그 모듈에 남겨 둔 기록 시각의 개수**다. 0 이면 한 자리도 없어야 한다.
#: 기록 시각을 새로 더하려면 이 숫자를 올리고 왜 판정이 아닌지 한 줄 적으면 된다.
JUDGEMENT_MODULES: dict[str, int] = {
    "api/insights.py": 0,
    "services/action_service.py": 0,
    "services/auditor_service.py": 0,
    "services/bizinfo_service.py": 0,
    "services/critical_condition_service.py": 1,  # 담당자 상태 변경의 resolved_at — 표시만 한다
    "services/daily_digest_service.py": 0,
    "services/eligibility_engine.py": 0,
    "services/eligibility_gap_service.py": 0,
    "services/g2b_client.py": 0,
    "services/notice_version_service.py": 0,
    "services/opportunity_priority.py": 0,
    "services/opportunity_service.py": 0,
    "services/opportunity_workbook.py": 1,  # 내려받기 파일명의 날짜
    "services/procurement_service.py": 0,
    "services/proposal_service.py": 2,  # evidence.json · 전체 제안서의 generated_at
    "services/support_application_service.py": 1,  # 응답의 generated_at
}


def _direct_reads(path: Path) -> int:
    """`datetime.now(...)` · `date.today(...)` 호출 수.

    주석·독스트링에 적힌 설명 문장은 세지 않는다 — 옛 결함을 서술하는 문장이 많다.
    그래서 글자 찾기가 아니라 **구문 나무**에서 호출만 센다.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("now", "today")
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in ("datetime", "date")
    )


def test_판정_모듈은_시계를_직접_읽지_않는다() -> None:
    """새로 `datetime.now()` 를 적으면 여기서 막힌다.

    막는 것이 목적이 아니라 **분류하게 만드는 것**이 목적이다. 판정이면
    `storage.utc_now()`(또는 「오늘」이면 `storage.kst_today()`)를 쓰고, 아무도 견주지
    않는 기록 시각이면 위 표의 숫자를 올리고 이유를 적는다.
    """
    root = Path(storage.__file__).resolve().parents[1]  # backend/app
    found = {rel: _direct_reads(root / rel) for rel in JUDGEMENT_MODULES}
    assert found == JUDGEMENT_MODULES
