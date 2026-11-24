"""**무엇을 갖추면 몇 건이 열리는가** — 갭 리포트 (0921.md §4-B).

## 왜 필요한가

담당자가 목록에서 보는 것은 「불가 42건」이다. 그런데 그 42건이 **영영 불가**인지,
**서류 한 장이면 열리는지**는 다른 이야기다. 검수자가 손으로 조사한 기준 답안은
「개발 공고 15건 중 9건이 소프트웨어사업자(1468) 등록 업체만 투찰할 수 있다」고 적었다 —
등록 신고 한 번이면 9건이 열린다는 뜻이다. 그 계산을 사람이 매번 하게 두지 않는다.

## 세는 규칙

판정 결과의 `unlock_condition`(「…하면 가능」)을 조건별로 모은다. 한 판정이 「1426·1468·
1469·1470 **중 하나**」를 요구하면 `unlock_options` 로 낱개가 함께 온다 — 그때는 낱개마다
센다. 그래야 「소프트웨어사업자(컴퓨터관련서비스사업, 1468) 등록 시 +N건」이 나온다
(0922 §4-A-5).

- **막고 있는 건수(`blocked`)** — 지금 「불가」인데, 그 조건을 붙인 규칙들이 **그 공고의
  유일한 불가 사유**일 때만 센다. 다른 이유로도 막혀 있으면 이 조건을 갖춰도 안 열린다.
- **확정을 막고 있는 건수(`pending`)** — 「확인 필요」에 붙은 조건. 갖추면 판정이
  확정된다(가능일 수도, 불가일 수도 있다) — **「가능해진다」고 적지 않는다.**

두 수를 합쳐 하나로 보여 주지 않는다. 뜻이 다르기 때문이다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core import storage
from app.schemas.organization import AnalysisContext
from app.services import (
    eligibility_engine,
    industry_hints,
    organization_service,
    procurement_service,
)

logger = logging.getLogger(__name__)

#: 한 조건에 붙여 보여 줄 공고 id 상한. 화면은 몇 건만 예로 보여 주고 나머지는 목록에서 본다.
MAX_EXAMPLES = 8


@dataclass
class Gap:
    """조건 하나와 그것이 붙잡고 있는 공고들."""

    condition: str
    rule_id: str
    label: str
    blocked_ids: list[str] = field(default_factory=list)
    pending_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "rule_id": self.rule_id,
            "label": self.label,
            #: 이 조건만 갖추면 「불가」가 풀리는 공고 수.
            "blocked": len(self.blocked_ids),
            #: 이 조건을 갖추면 판정이 확정되는(지금은 「확인 필요」인) 공고 수.
            "pending": len(self.pending_ids),
            "blocked_examples": self.blocked_ids[:MAX_EXAMPLES],
            "pending_examples": self.pending_ids[:MAX_EXAMPLES],
        }


def _conditions_of(entry: Any) -> list[str]:
    """이 판정이 「무엇을 갖추면」 뒤집히는가. 「중 하나」면 낱개로 편다."""
    if not entry.unlock_condition:
        return []
    # 본사 이전(「○○ 소재 시 가능」)은 갖출 조건으로 세지 않는다(43차 N3 — 매일 첫 줄이 이전 권유였다)
    return [c for c in (list(entry.unlock_options) or [entry.unlock_condition]) if not eligibility_engine.is_relocation(c)]


async def build(
    *,
    context: AnalysisContext | None,
    days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    """조회 기간 안의 나라장터 공고를 전부 판정해 조건별로 모은다. **네트워크를 부르지 않는다.**"""
    moment = now or storage.utc_now()
    organization_id = context.organization_id if context else None
    company = eligibility_engine.company_facts_for(organization_id)
    regions = organization_service.preferred_regions(organization_id) if organization_id else ()

    try:
        result = await procurement_service.list_ai_candidates(days=days)
    except Exception as exc:  # noqa: BLE001 — 목록이 없으면 셀 것도 없다
        logger.warning("갭 리포트: 공고 목록을 읽지 못했습니다: %s", exc)
        return {
            "organization_id": organization_id,
            "days": days,
            "evaluated_at": moment.isoformat(),
            "total": 0,
            "blocked_total": 0,
            "gaps": [],
            "note": f"공고 목록을 읽지 못해 셀 수 없었습니다: {exc}",
        }

    gaps: dict[str, Gap] = {}
    total = 0
    blocked_total = 0
    for view in result.notices:
        # 후보만 센다 — 사업영역 밖 공고까지 넣으면 「무엇을 갖추면」이 흐려진다.
        if not view.match.is_candidate:
            continue
        total += 1
        results = eligibility_engine.evaluate_notice_fields(
            view.notice.raw_data, as_of=moment, regions=regions, company=company, notice_id=view.notice.id
        )
        failed = [r for r in results if r.status == "FAIL"]
        if failed:
            blocked_total += 1

        # 「이 조건만 갖추면 열리는가」 — 조건이 붙지 않은 다른 불가가 있으면 안 열린다.
        for entry in results:
            if not entry.unlock_condition:
                continue
            # 「중 하나」인 조건은 낱개로 센다. 없으면 한 줄짜리 조건 하나다.
            for condition in _conditions_of(entry):
                gap = gaps.setdefault(
                    condition,
                    Gap(condition=condition, rule_id=entry.rule_id, label=entry.label),
                )
                if entry.status == "FAIL":
                    # 같은 조건이 여러 규칙에 붙을 수 있다(등록 마감·입찰 마감이 둘 다 촉박인 경우).
                    # 그것들은 「다른 불가」가 아니다 — 같은 조건 하나로 함께 풀린다.
                    others = [r for r in failed if condition not in _conditions_of(r)]
                    # 공고 하나를 두 번 세면 「불가 47건」이 「불가 총 41건」보다 커진다.
                    if not others and view.notice.id not in gap.blocked_ids:
                        gap.blocked_ids.append(view.notice.id)
                elif entry.status == "CHECK" and not failed and view.notice.id not in gap.pending_ids:
                    gap.pending_ids.append(view.notice.id)

    # **아무것도 붙잡고 있지 않은 조건은 내려보내지 않는다** (0923 §3-1 · ISSUE-091).
    #
    # 「국내외여행업(1262) 등록 시 가능 — 막는 0 · 확정 0」 같은 줄이 여덟 개 있었다.
    # 그 공고들은 다른 이유로도 막혀 있어서 이 업종을 등록해도 열리지 않는다. 0 을
    # 보여 주는 것은 「등록하면 뭔가 생긴다」는 잘못된 인상만 남긴다.
    listed = [g for g in gaps.values() if g.blocked_ids or g.pending_ids]
    dropped = len(gaps) - len(listed)
    ordered = sorted(listed, key=lambda g: (-len(g.blocked_ids), -len(g.pending_ids), g.condition))
    return {
        "organization_id": organization_id,
        "days": days,
        "evaluated_at": moment.isoformat(),
        #: 판정한 공고 수 (후보만).
        "total": total,
        #: 지금 「불가」인 공고 수.
        "blocked_total": blocked_total,
        "gaps": [gap.to_dict() for gap in ordered],
        #: 「막는 0 · 확정 0」이라 목록에서 뺀 조건 수. 숨겼다는 사실 자체는 숨기지 않는다.
        "empty_dropped": dropped,
        # 사업자등록증 종목 → 나라장터 등록 업종 「등록 후보」 힌트 (0922 §4-A-6).
        # 갭이 「1468 을 등록하면 열린다」고 말할 때, 담당자가 **등록 신청이 가능한지**를
        # 같은 자리에서 알 수 있어야 한다.
        "registration_hints": industry_hints.hints_for(organization_id),
        "note": (
            "「막고 있는 건수」는 그 조건만 갖추면 불가가 풀리는 공고 수입니다. "
            "「확정을 막고 있는 건수」는 갖추면 판정이 확정되는 공고 수이며, 확정 결과가 "
            "가능이라는 뜻은 아닙니다. "
            "두 수가 모두 0 인 조건은 지금 아무것도 붙잡고 있지 않아 목록에서 뺐습니다."
        ),
    }
