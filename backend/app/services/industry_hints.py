"""사업자등록증 **종목** → 나라장터 **등록 업종** 후보 (0922.md §4-A-6).

## 두 가지는 다른 것이다

- **종목**은 세무서(사업자등록증)에 적힌 업태·종목이다. 「응용 소프트웨어 개발 및 공급업」.
- **나라장터 등록 업종**은 조달청 경쟁입찰참가자격 등록의 업종코드다. 「소프트웨어사업자
  (컴퓨터관련서비스사업)/1468」. 판정에 쓰는 것은 **이쪽뿐이다.**

종목이 있다고 업종이 자동으로 등록되는 것이 아니다. 소프트웨어사업자는 한국소프트웨어산업
협회 신고 뒤 나라장터에 업종을 추가해야 한다. 그래서 이 표는 **판정이 아니라 힌트**다 —
「이 종목이 있으니 등록 신청이 가능해 보인다. 나라장터 등록증에서 확인하라」.

값을 지어내지 말라는 규칙(CLAUDE.md §11)은 **등록 업종**에 대한 것이었다. 종목은 담당자가
확인해 준 값이므로 그대로 쓴다(0922 §2).
"""

from __future__ import annotations

import logging
from typing import Any, Final

logger = logging.getLogger(__name__)

#: 종목 → 업종코드·이름. 검수자가 대조한 표 그대로다 (2026-09-22 재검증 §3).
#:
#: 여기 없는 종목은 힌트를 만들지 않는다. 「빅데이터 전략 및 컨설팅업」이 학술·연구용역(1169)
#: 으로 이어지는지는 확인되지 않았다 — 별도 등록이라 적혀 있을 뿐이다.
INDUSTRY_HINTS: Final[tuple[tuple[str, str, str], ...]] = (
    ("컴퓨터 시스템 통합 자문 및 구축 서비스업", "1468", "소프트웨어사업자(컴퓨터관련서비스사업)"),
    ("응용 소프트웨어 개발 및 공급업", "1426", "소프트웨어사업자(패키지소프트웨어개발·공급사업)"),
    ("데이터베이스 및 온라인 정보 제공업", "1470", "소프트웨어사업자(데이터베이스제작및검색서비스사업)"),
)


def hints_for_items(items: list[str], *, registered_codes: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """종목 목록에서 「등록 후보」를 뽑는다. **이미 등록한 업종은 후보가 아니다.**"""
    out: list[dict[str, Any]] = []
    text = " ".join(items)
    for item, code, name in INDUSTRY_HINTS:
        if code in registered_codes:
            continue
        if item in text or any(item in entry or entry in item for entry in items if entry):
            out.append(
                {
                    "business_item": item,
                    "code": code,
                    "name": name,
                    "hint": (
                        f"사업자등록증에 「{item}」 종목이 있어 {name}({code}) 등록 신청이 "
                        "가능해 보입니다 — 나라장터 등록증에서 확인하세요."
                    ),
                }
            )
    return out


def hints_for(organization_id: str | None) -> list[dict[str, Any]]:
    """조직이 적어 둔 종목으로 힌트를 만든다. 못 읽으면 빈 목록 — 화면이 줄을 그리지 않는다."""
    if not organization_id:
        return []
    from app.services import delivery_capacity_service

    try:
        capacity = delivery_capacity_service.load(organization_id)
    except Exception:  # noqa: BLE001 — 힌트가 없다고 갭 리포트가 죽으면 안 된다
        logger.warning("등록 후보 힌트: 역량 자료를 읽지 못했습니다 (%s)", organization_id)
        return []
    return hints_for_items(
        list(capacity.business_items or ()),
        registered_codes=tuple(i.code for i in capacity.registered_industries if i.code),
    )
