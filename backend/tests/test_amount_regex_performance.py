"""금액 정규식이 긴 숫자열에서 서버를 멈추지 않는다 (ISSUE-014).

## 무엇을 막는가

`_AMOUNT_RE` 는 숫자열을 여러 가지로 쪼개 볼 수 있었고, 뒤에 「원 이상」이 없으면
그 **모든 분할**을 시도했다. 자릿수당 약 1.6배씩 늘어난다.

    18자리 0.03초 · 22자리 0.5초 · 24자리 2.0초 · 40자리 사실상 끝나지 않음

핸들러가 `async def` 라 그동안 `/health` 를 포함한 모든 요청이 멈춘다. 성능이 아니라
**가용성** 문제다. 진입점은 `PUT /api/rfp/{pid}/items/{req}` (content 2000자) →
`GET …/performance-match`, `POST /api/conditions/detect` 이고, 실제 RFP 첨부의 긴
숫자열로도 촉발될 수 있다.

시간을 재는 테스트는 기계가 느릴 때 흔들린다. 그래서 상한을 넉넉히(10ms) 잡았다 —
고쳐진 구현은 40자리를 0.01ms 에 끝내므로 1000배의 여유가 있고, 되돌아가면 초 단위라
이 상한을 반드시 넘는다.
"""

from __future__ import annotations

import time

import pytest

from app.services import performance_match_service as pms

BUDGET_MS = 10.0


def _elapsed_ms(text: str) -> float:
    start = time.perf_counter()
    pms._AMOUNT_RE.findall(text)
    return (time.perf_counter() - start) * 1000


@pytest.mark.parametrize("digits", [24, 40, 80])
def test_긴_숫자열이_즉시_끝난다(digits: int) -> None:
    assert _elapsed_ms("9" * digits) < BUDGET_MS


def test_단위가_섞인_긴_문자열도_즉시_끝난다() -> None:
    """숫자와 단위가 번갈아 나오는 경우가 가장 나쁜 입력이다."""
    assert _elapsed_ms("1억2천3백4십" * 30) < BUDGET_MS


def test_쉼표가_섞여도_즉시_끝난다() -> None:
    assert _elapsed_ms("1,234,567,890" * 20) < BUDGET_MS


@pytest.mark.parametrize(
    "text, expected",
    [
        ("3천5백만원 이상", "3천5백만"),
        ("1,200,000원 이상", "1,200,000"),
        ("10억원 이상", "10억"),
        ("12.5억원 이상", "12.5억"),
        ("100원이상", "100"),
        ("총 3억원 이상의 실적", "3억"),
    ],
)
def test_읽어내는_금액은_그대로다(text: str, expected: str) -> None:
    """빠르게 만들면서 뜻이 바뀌면 안 된다 — 고치기 전과 같은 값을 읽어야 한다."""
    found = pms._AMOUNT_RE.findall(text)
    assert found and found[0].strip() == expected


def test_원_이상이_없으면_잡지_않는다() -> None:
    assert pms._AMOUNT_RE.findall("3천5백만원") == []
    assert pms._AMOUNT_RE.findall("999999999999") == []
