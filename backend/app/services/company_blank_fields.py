"""회사자료 빈칸 안내 — **비어 있어서 판정이 멈춘 칸**과 그 칸 때문에 「확인 필요」로 남은 공고 수 (38차 §3-C-7).

recheck30 §4-4: 입찰 자격 칸 17개 중 9개가 비어 판정 낱말이 거의 모두 「조건부 검토」였다. 회사 값 감사
(회사 값 점검)는 「적으면 무엇이 바뀌나」를 재지만 화면에는 없었다. 여기서는 그 앞 단계 —
**지금 비어 있는 칸**과 **그 칸이 비어 확인 필요로 남은 공고 수**만 센다(값을 가정하지 않는다).

## 세는 법

- 칸이 비었는지는 판정이 쓰는 회사 사실(`eligibility_engine.company_facts_for`)로 본다 — 「모름」 · 빈칸이면 빈칸이다.
- 공고는 지금 목록(마감 전 · 불가 포함 · 관련 낮음 뺌)의 **확인 필요** 공고이고, 규칙이 붙인 「갖추면 …」 조건
  (`unlock_conditions`)이 그 칸을 가리키면 센다. 한 공고가 두 칸에 걸리면 두 칸에 모두 센다.
- 판정을 새로 만들지 않는다 — 규칙이 이미 적은 조건 문장을 칸별로 묶을 뿐이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from app.schemas.organization import AnalysisContext
from app.services import eligibility_engine

#: 칸 하나 — (열쇠, 화면 이름, 회사자료에서 찾는 곳, 비었나, 조건 문장 무늬).
FieldRule = tuple[str, str, str, Callable[[Any], bool], re.Pattern[str]]

FIELDS: tuple[FieldRule, ...] = (
    (
        "registered_industries", "나라장터 등록 업종", "회사자료 › 입찰 자격 자료 「나라장터 등록 업종」",
        lambda c: not c.registered_industry_codes and not c.registered_industry_names,
        re.compile(r"\d{4}\s*등록\s*시|업\s*등록\s*시|사업자[^\n]{0,30}등록\s*시"),
    ),
    (
        "joint_bid_partner", "공동수급 파트너", "회사자료 › 입찰 자격 자료 「공동수급 파트너」",
        lambda c: c.joint_bid_available is None,
        re.compile(r"파트너"),
    ),
    (
        "sme_certificate", "중소기업(소상공인) 확인서", "회사자료 › 입찰 자격 자료 › 준비 상태 「중소기업(소상공인) 확인서」",
        lambda c: c.sme_held is None,
        re.compile(r"(중소기업|소상공인)[^\n]{0,20}확인서"),
    ),
    (
        "revenue", "지난해 매출", "회사자료 › 입찰 자격 자료 「지난해 매출」",
        lambda c: c.revenue_krw_last_year is None,
        re.compile(r"매출"),
    ),
    (
        "research_department", "기업부설연구소 · 연구개발전담부서", "회사자료 › 입찰 자격 자료 「연구소」",
        lambda c: c.research_department_kind is None and c.has_research_department is None,
        re.compile(r"연구소|전담부서"),
    ),
    (
        "employee_count", "상시 근로자 수", "회사자료 › 회사 프로필 「상시 근로자 수」",
        lambda c: c.employee_count is None,
        re.compile(r"근로자|상시\s*인원|고용보험"),
    ),
    (
        "data_products", "데이터 상품", "회사자료 › 입찰 자격 자료 「데이터 상품」",
        lambda c: not c.data_products,
        re.compile(r"데이터\s*상품"),
    ),
    (
        "supplier_registrations", "공급기업 등록", "회사자료 › 입찰 자격 자료 「공급기업 등록」",
        lambda c: not c.supplier_registrations,
        re.compile(r"공급기업"),
    ),
    # 44차 대표 결정 1(회사 자료 더 받지 않음) — 43차에 생긴 대표 값 칸도 「안 적음(그대로 둠)」을 고를 수 있게 한다
    (
        "company_checks", "회사 단위 확인(나라장터 등록 · 부정당 제재 없음 · 체납 없음)", "회사자료 › 입찰 자격 자료 「회사 단위 확인」",
        lambda c: len(c.company_checks) < 3,
        re.compile(r"경쟁입찰참가자격등록증|회사 단위 확인"),
    ),
    (
        "direct_production_items", "직접생산 보유 품명", "회사자료 › 입찰 자격 자료 「직접생산 보유 품명」",
        lambda c: not c.direct_production_items,
        re.compile(r"직접생산"),
    ),
    (
        "digital_products", "보유 디지털 제품(서비스)", "회사자료 › 입찰 자격 자료 「보유 디지털 제품(서비스)」",
        lambda c: not c.digital_products,
        re.compile(r"디지털\s*제품"),
    ),
    (
        "founded_on", "개업연월일", "회사자료 › 사업계획서 일반현황 「개업연월일」",
        lambda c: c.founded_on is None,
        re.compile(r"개업|일반현황"),
    ),
    (
        "women_enterprise", "여성기업 확인서", "회사자료 › 회사 프로필 「인증」",
        lambda c: not any("여성기업" in cert for cert in c.certifications),
        re.compile(r"여성\s*기업"),
    ),
    (
        "certification_history", "인증 이력(지난 지정 · 만료)", "회사자료 › 회사 프로필 「인증 이력」",
        lambda c: not c.certification_history,
        re.compile(r"인증\s*이력"),
    ),
)

#: 대표가 적는 칸(43차 Q23) — 걸린 공고가 0건이어도 빈칸 안내에 보인다(「안 적음」을 고를 자리 · 44차 대표 결정 1).
OWNER_KEYS: frozenset[str] = frozenset(
    {"company_checks", "direct_production_items", "digital_products", "founded_on", "women_enterprise", "certification_history"}
)

#: 칸마다 예로 싣는 공고 수.
EXAMPLES = 3

#: 적어도 판정을 바꾸지 못하는 칸(43차 Q25) — 공동수급 파트너는 공고마다 정하는 전략이라 「있음 · 없음」 어느 쪽으로 적어도
#: 판정이 그대로였다(대형 · 파트너형 후보 칸은 값과 상관없이 확인 필요). 「참고」로 적고 「채우면」 권유에서 뺀다.
REFERENCE_KEYS: frozenset[str] = frozenset({"joint_bid_partner"})


#: 「안 적음」으로 고를 수 있는 칸 열쇠(41차 D31).
FIELD_KEYS: frozenset[str] = frozenset(key for key, *_ in FIELDS)


@dataclass
class BlankField:
    key: str
    label: str
    where: str
    blank: bool
    ids: list[str] = field(default_factory=list)
    examples: list[dict[str, str]] = field(default_factory=list)
    #: 담당자가 「안 적음(그대로 둠)」으로 고른 빈칸 — 세지 않고 안내에서 뺀다(41차 D31 · 판정은 그대로 「확인 필요」).
    left_blank: bool = False
    #: 그 칸 **하나만** 걸린 공고(조건이 모두 이 칸) — 「이 칸도 걸린 n · 이 칸만 걸린 m」(43차 Q25 · n 만으로는 채워도 바뀌는 수를 몰랐다).
    only_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "where": self.where,
            "blank": self.blank,
            "count": len(self.ids),
            "examples": self.examples,
            "left_blank": self.left_blank,
            "only_count": len(self.only_ids),
            "reference": self.key in REFERENCE_KEYS,
            "owner_value": self.key in OWNER_KEYS,
        }


def count_fields(items: list[Any], company: Any, left_blank: frozenset[str] | set[str] = frozenset()) -> list[BlankField]:
    """빈 칸마다 그 칸을 가리키는 「확인 필요」 공고를 센다. 채운 칸은 `blank=False` · 0건으로 남긴다(화면이 「채움」으로 적는다).
    `left_blank` 칸(「안 적음」)은 세지 않는다 — 안내 · 「채우면 풀린다」 권유에서 빠진다(41차 D31)."""
    out: list[BlankField] = []
    for key, label, where, is_blank, pattern in FIELDS:
        entry = BlankField(key=key, label=label, where=where, blank=bool(is_blank(company)))
        entry.left_blank = entry.blank and key in left_blank
        if entry.blank and not entry.left_blank:
            for item in items:
                if item.closed or item.relevance_note or item.eligibility_gate != "CHECK":
                    continue
                conditions = [text or "" for text in (item.unlock_conditions or [])]
                if any(pattern.search(text) for text in conditions):
                    entry.ids.append(item.id)
                    if all(pattern.search(text) for text in conditions):
                        entry.only_ids.append(item.id)
                    if len(entry.examples) < EXAMPLES:
                        entry.examples.append({"id": item.id, "title": item.title[:60], "source": item.source_type})
        out.append(entry)
    # 참고 칸(판정을 못 바꿈)은 같은 빈칸 안에서 뒤로
    out.sort(key=lambda f: (not f.blank, f.key in REFERENCE_KEYS, -len(f.only_ids), -len(f.ids)))
    return out


def left_blank_of(organization_id: str) -> frozenset[str]:
    """회사가 「안 적음」으로 고른 칸(41차 D31)."""
    from app.services import delivery_capacity_service

    return frozenset(delivery_capacity_service.load(organization_id).left_blank) & FIELD_KEYS


async def build(context: AnalysisContext) -> dict[str, Any]:
    """지금 목록으로 센 빈칸 안내. 네트워크를 부르지 않는다(목록과 같은 저장본 · 고정 모드)."""
    from app.services import opportunity_service

    listing = await opportunity_service.list_opportunities(
        context=context, source="all", days=30, include_blocked=True, include_closed=False, limit=None
    )
    company = eligibility_engine.company_facts_for(context.organization_id, evidence_scope=context.evidence_scope)
    fields = count_fields(list(listing.items), company, left_blank_of(context.organization_id))
    return {
        "organization_id": context.organization_id,
        "fetched_at": listing.fetched_at,
        "fields": [f.to_dict() for f in fields],
        "note": "칸이 비어 「확인 필요」로 남은 공고 수입니다. 값을 적으면 다시 판정되고, 정말 안 되는 공고만 「불가」로 내려갑니다.",
    }
