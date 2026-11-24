"""금액을 사람이 읽는 말로 — 화면 금액 한 벌 (27차 §3-E UNI-08 · 검수 R27U-MSC-02).

프론트 `frontend/src/lib/cosmos/format.ts` 의 `formatBudgetCompact` 와 **같은 꼴**이다: 1억 이상 「1.2억원」(소수 한 자리 ·
끝의 .0 은 뺀다) · 1만 이상 「6,000만원」(만 단위 반올림 · 쉼표) · 그 밖 「5,000원」. 같은 공고의 예산이 한 카드 안에서
「2,793만원」과 「27,934,500원」으로 갈렸다. 원 단위를 정밀하게 대조해야 하는 자리(실적 조건 · 지원사업 사업비)는 쓰지 않는다.

서비스를 import 하지 않는 잎 모듈이라 어디서 불러도 순환 import 가 생기지 않는다.
"""

from __future__ import annotations


def won_pair(a: int | float, b: int | float) -> tuple[str, str]:
    """두 금액을 견주는 문장용. 반올림하면 같아지는데 실제로 다르면 정확한 금액으로 적는다(34차 R33-04 —
    「사업비 2억원 — 최대 사업비 2억원보다 큽니다」)."""
    a_text, b_text = won(a), won(b)
    if a_text == b_text and a != b:
        return f"{int(a):,}원", f"{int(b):,}원"
    return a_text, b_text


def won(amount: int | float) -> str:
    if amount >= 100_000_000:
        eok = amount / 100_000_000
        text = str(int(eok)) if float(eok).is_integer() else f"{eok:.1f}".removesuffix(".0")
        return f"{text}억원"
    if amount >= 10_000:
        return f"{round(amount / 10_000):,}만원"
    return f"{int(amount):,}원"
