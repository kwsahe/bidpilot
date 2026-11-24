"""입찰 참가자격 판정 엔진 (규칙 우선, LLM은 선택).

원칙 (CLAUDE.md 4-D, 11, 20):
- **규칙이 먼저, 항상 돈다.** LLM은 이유 문장을 다듬고 CHECK로 라우팅할 뿐이며,
  단독으로 PASS를 만들 수 없다. 키가 없거나 호출이 실패해도 결과는 항상 완전하다.
- 구조화된 공고 필드(지역/업종/기한/계약방법)처럼 **명확히 확인 가능한 조건만** PASS/FAIL.
- 문서를 읽어야 아는 조건(유사실적·경력·컨소시엄 요건 등)은 **절대 자동 PASS 금지 → CHECK**.
- 모든 판정에는 실제 근거(공고 API 필드명=값 또는 RFP 페이지+원문)를 남긴다.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

import functools
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Final, Literal

from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.money import won, won_pair
from app.core import storage
from app.schemas.eligibility import (
    EligibilityCounts,
    EligibilityReport,
    EligibilityResult,
    EligibilityStatus,
    ClauseDocument,
    ReviewTally,
)
from app.schemas.requirement import Requirement, RfpParseResult
from app.services import g2b_mapper, llm_client, procurement_service, rfp_parser, wording

if TYPE_CHECKING:  # pragma: no cover
    from app.schemas.organization import AnalysisContext

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# 회사 프로필 — **합성 데모 데이터**
# ---------------------------------------------------------------------------
# CLAUDE.md 6 / 21: 공개 데모에는 실제 샘플에듀 민감정보(매출·인력·실적·인증)를 쓰지 않는다.
# 아래 값은 판정 규칙을 돌리기 위한 최소한의 합성 프로필이며 실데이터가 아니다.


@dataclass(frozen=True)
class CompanyProfile:
    name: str
    business_domains: tuple[str, ...]
    preferred_regions: tuple[str, ...]
    # 공동수급 없이 단독 수행이 가능한가 (합성 가정)
    can_perform_alone: bool
    # 사업자등록 완료 여부 (합성 가정)
    business_registration_done: bool
    # 단독 수행을 가정할 때 무리 없이 검토 가능한 사업 규모(원). 합성 기준값이며
    # 실제 회사 경영상태·실적 자료가 아니다. 초과하면 FAIL이 아니라 CHECK로 보낸다.
    solo_capacity_budget: int
    synthetic: bool = True


COMPANY_PROFILE: Final[CompanyProfile] = CompanyProfile(
    name="샘플에듀",
    business_domains=(
        "AI 활용 교육",
        "생성형 AI 교육",
        "업무자동화 교육",
        "AI 컨설팅",
        "ESG 교육 및 컨설팅",
    ),
    preferred_regions=("광주광역시", "전라남도", "전국"),
    can_perform_alone=True,
    business_registration_done=True,
    solo_capacity_budget=300_000_000,
)

# 지역 문자열 표기 차이를 흡수하기 위한 별칭 (합성 프로필 기준).
_REGION_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "광주광역시": ("광주",),
    "전라남도": ("전남",),
    "전국": (),
}

# 문서를 읽어야 확인 가능한 자격 요건 키워드 → 자동 PASS 금지, CHECK로 보낸다.
DOC_CHECK_KEYWORDS: Final[tuple[str, ...]] = (
    "유사",
    "경력",
    "실적",
    "등급",
    "인증",
    "면허",
    "등록",
    "자격증",
)
_CONSORTIUM_KEYWORDS: Final[tuple[str, ...]] = ("공동수급", "컨소시엄", "공동이행")
_SOLO_ALLOWED_KEYWORDS: Final[tuple[str, ...]] = ("허용하지 않", "불허", "단독")

# 요구사항에서 뽑는 자격 규칙 수 상한 (UI가 자격 항목으로 뒤덮이지 않게).
MAX_REQUIREMENT_RULES: Final[int] = 12
# LLM에 물어볼 요구사항 수 상한.
MAX_LLM_ITEMS: Final[int] = 8

_QUOTE_LIMIT: Final[int] = 140
_LABEL_LIMIT: Final[int] = 40


class EligibilityDataError(RuntimeError):
    """공고 필드도 없고 파싱된 요구사항도 없어 판정 근거가 전혀 없음."""


# ---------------------------------------------------------------------------
# 공용 헬퍼
# ---------------------------------------------------------------------------


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _notice_field(raw: dict[str, Any], *keys: str) -> str:
    """공고 raw_data에서 필드값을 찾는다. item(원본 API 응답) → 상위 편의 키 순서."""
    item = raw.get("item")
    if isinstance(item, dict):
        for key in keys:
            value = _clean(item.get(key))
            if value:
                return value
    for key in keys:
        value = _clean(raw.get(key))
        if value:
            return value
    return ""


#: 판정 근거(`source`)에 적는 공고 필드의 한국어 이름 (DTL-26). 화면 「근거:」에 API 필드명
#: (「rgnLmtBidLocplcJdgmBssNm=(없음)」)이 그대로 나오던 것을 사람 말로 바꾼다. 값은 원문 그대로
#: 두고(Y/N 만 예/아니오), 필드명은 이 표로 거꾸로 찾는다.
_FIELD_NAMES: Final[dict[str, str]] = {
    "rgnLmtBidLocplcJdgmBssNm": "지역제한 판단기준",
    "jntcontrctDutyRgnNm1": "지역의무공동도급 지역",
    "indstrytyLmtYn": "업종 제한 여부",
    "bidPrtcptLmtYn": "참가제한 여부",
    "arsltCmptYn": "실적평가 여부",
    "cmmnSpldmdCorpRgnLmtYn": "공동수급체 지역제한 여부",
    "cntrctCnclsMthdNm": "계약방법",
    "sucsfbidMthdNm": "낙찰방법",
    "bidQlfctRgstDt": "참가자격 등록 마감",
    "bidClseDt": "입찰서 제출 마감",
    "asignBdgtAmt": "배정예산",
    "presmptPrce": "추정가격",
    "ntceKindNm": "종류",
}
_YES_NO: Final[dict[str, str]] = {"Y": "예", "N": "아니오"}


#: 금액 칸 — 근거 줄에 「30000000」 대신 「3,000만원」(32차 어려운 글 #9).
_MONEY_FIELDS: Final[frozenset[str]] = frozenset({"asignBdgtAmt", "presmptPrce"})


def _field_value(key: str, value: str) -> str:
    if key in _MONEY_FIELDS and value.strip().isdigit():
        return won(int(value.strip()))
    return _YES_NO.get(value.upper(), value) or "없음"


def _fields(*pairs: tuple[str, str]) -> str:
    """「지역제한 판단기준: 없음 · …」 — 공고 필드 이름을 한국어로, 값은 원문 그대로(금액만 원 단위 글로)."""
    return " · ".join(f"{_FIELD_NAMES[key]}: {_field_value(key, value)}" for key, value in pairs)


def _shorten(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _quote_requirement(req: Requirement) -> str:
    """RFP 원문 인용. 페이지·원문은 요구사항에서 그대로 가져온다 (창작 금지)."""
    page = f"제안요청서 {req.page}쪽" if req.page is not None else "제안요청서"
    return f'{page} "{_shorten(req.source_text, _QUOTE_LIMIT)}"'


# 판정 중인 조직의 활동 지역. evaluate_from_sources 가 넣고 끝나면 되돌린다. None 이면 합성 기본 프로필(레거시 진입점).
_ACTIVE_REGIONS: ContextVar[tuple[str, ...] | None] = ContextVar("eligibility_active_regions", default=None)


@dataclass(frozen=True)
class CompanyFacts:
    """판정에 쓰는 **회사 쪽 사실** (0921 §4-B).

    **모르는 것은 None·빈 목록이고, 그것이 「없다」를 뜻하지 않는다.** 등록 업종이 비어
    있으면 「업종이 없는 회사」가 아니라 「아직 안 적었다」이므로, 판정은 「불가」가 아니라
    「확인 필요」로 간다.

    합성 기본 프로필(`COMPANY_PROFILE`)과 달리 이것은 **실제 회사가 적은 값**이다.
    호출자가 넣지 않으면 전부 「미입력」으로 본다 — 지어내지 않는다.
    """

    #: 나라장터 등록 업종 코드 (예 "1468").
    registered_industry_codes: tuple[str, ...] = ()
    #: 같은 업종의 이름. 화면 문구에 쓴다.
    registered_industry_names: tuple[str, ...] = ()
    #: 회사 소재 광역 (예 "전남광주"). 「활동 지역」과 다르다.
    location_region: str | None = None
    #: 단독 수행 가능 규모 상한(원). None 이면 판정하지 않는다.
    budget_ceiling_krw: int | None = None
    #: 공동수급 파트너를 확보할 수 있는가. None 이면 확인되지 않았다.
    joint_bid_available: bool | None = None
    #: 제안서 준비에 필요한 최소 일수.
    proposal_lead_days: int = 4
    # --- 기업마당 대상 요건 판정에 쓰는 값들 (0921 §4-B) -------------------
    #: 보유 인증 (사회적기업·데이터바우처 공급기업 …).
    certifications: tuple[str, ...] = ()
    #: 설립 연도. 「창업 7년 이내」 같은 요건을 이것으로 센다.
    founded_year: int | None = None
    #: 개업연월일(회사자료 › 사업계획서 일반현황 · 43차 COMPANY-07) — 창업 연차의 **경계 해**에만 쓴다. 비면 None(연도만으로 판정).
    founded_on: date | None = None
    #: 상시 근로자 수. None 이면 「미입력」 — 「N인 이상」 요건을 확정하지 못한다.
    employee_count: int | None = None
    #: 회사가 적은 **활동 지역**(`profile.preferred_regions`). 소재지와 다른 축이지만,
    #: 소재지 칸이 비었을 때 지역 판정의 대체 근거가 된다 — 이것도 회사가 적은 값이다.
    activity_regions: tuple[str, ...] = ()
    # --- 기업마당 공고문 판정 v2 (0924 §4-A-5) ---------------------------
    #: 지난해 매출(원). None 이면 「매출 N억 이상」을 판정하지 않는다.
    revenue_krw_last_year: int | None = None
    #: 기업부설연구소·연구개발전담부서 보유 여부. None 이면 확인되지 않았다.
    has_research_department: bool | None = None
    #: 「lab」 기업부설연구소 · 「dept_only」 연구개발전담부서만 · None 종류 모름(36차 R35-DV-02).
    research_department_kind: str | None = None
    #: 회사자료 준비 상태의 「중소기업(소상공인) 확인서」 줄(10-10 담당자 결정 — 준비 상태 중 이 줄만 판정에 쓴다).
    #: 있음 · 없음 · 모름(None) · 구분(중기업 · 소기업 · 소상공인) · 유효기간 끝나는 날.
    sme_held: bool | None = None
    sme_grade: str | None = None
    sme_valid_until: date | None = None
    #: 통합 전 지역(「광주」 · 「전남」) — 회사 주소의 구 · 시 · 군에서 읽는다. 「옛 전라남도 지역」 같은 소재 요건에 쓴다(35차 R34S-04).
    location_old_region: str | None = None
    #: 회사 주소의 광주 · 전남 시 · 군 · 구(「북구」 · 「나주시」) — 시 · 군 단위 참가지역 목록과 견준다(43차 H2). 모르면 None.
    location_district: str | None = None
    #: 인증·평가 대상이 되는 데이터 상품.
    data_products: tuple[str, ...] = ()
    #: 등록해 둔 공급기업 풀.
    supplier_registrations: tuple[str, ...] = ()
    #: 완료한 선행 사업. 「없음 확인」 한 줄이면 **확인된 「없다」**로 읽는다.
    completed_programs: tuple[str, ...] = ()
    #: 실적 원장 중 외부에 쓸 수 있는 **수행 사업** 행 — 참가자격 **실적 조항**과 견준다 (19차 §4-B).
    #: 판정 메모 열쇠에 들어가야 해서(해시) 행을 (키, 값) 튜플로 둔다. 원장은 **내부 범위에서만** 읽는다 —
    #: 공개 시연(public_demo)에서 실제 실적 제목이 판정 사유에 실리면 안 된다(CLAUDE.md §21).
    ledger_rows: tuple[tuple[tuple[str, Any], ...], ...] = ()
    #: 원장을 읽었는가. False 면 실적 조항을 「원장 없음」으로 두고 확정하지 않는다.
    ledger_available: bool = False
    #: 회사가 실제로 적어 둔 값이 하나라도 있는가. False 면 **합성 기본 프로필**로 보는 것이
    #: 아니라 「아직 안 적었다」다 (0922 §4-D-1 · ISSUE-086).
    from_real_company: bool = False
    #: 참가자격 조항마다 **담당자가 확인한 것** (20차 §4-C) — (공고 id, 조항 id, 상태, 메모, 확인한 사람,
    #: 확인 시각, 조항 해시). 회사가 스스로 확인한 사실이라 여기 둔다: 목록 게이트와 상세 판정이 같은
    #: 함수(`company_facts_for`)로 읽고, 판정 메모의 열쇠(`hash(company)`)에도 들어가 저장 즉시 새로 판정된다.
    clause_reviews: tuple[tuple[str, str, str, str, str, str, str], ...] = ()
    #: 회사 단위 한 번 확인(43차 결정 2) — (열쇠, 확인일 ISO, 유효기간 ISO, 확인한 사람). 비면 모름.
    company_checks: tuple[tuple[str, str, str, str], ...] = ()
    #: 직접생산확인 보유 품명(43차 Q24). 비면 모름.
    direct_production_items: tuple[str, ...] = ()
    #: 보유 디지털 제품(서비스) 이름(43차 Q14). 비면 모름.
    digital_products: tuple[str, ...] = ()
    #: 인증 이력(지난 지정 · 만료 · 43차 Q23) — **판정에 쓰지 않는다.** 빈칸 안내 · 「안 적음」(44차 대표 결정 1)만 본다.
    certification_history: tuple[str, ...] = ()

    @property
    def completed_programs_confirmed_none(self) -> bool:
        """담당자가 「선행 사업 없음」을 **확인해 적었는가**. 빈 목록(모름)과 다르다."""
        return any("없음" in entry for entry in self.completed_programs)


_ACTIVE_COMPANY: ContextVar[CompanyFacts | None] = ContextVar("eligibility_active_company", default=None)


def active_company() -> CompanyFacts:
    """지금 판정 중인 회사의 사실. 넣지 않았으면 전부 「미입력」이다."""
    return _ACTIVE_COMPANY.get() or CompanyFacts()


#: 회사가 상한을 안 적었을 때 «참고로만» 견주는 권장 상한 (개발 3명 기준, 0922 §2·§4-D-1).
#:
#: **판정에 쓰지 않는다.** 규모로 「불가」를 내려면 회사가 정한 값이 있어야 한다. 순위에서
#: 쓰는 것과 같은 값이며 단일 출처는 `opportunity_priority.RECOMMENDED_CEILING_KRW` 다 —
#: 여기서 다시 정의하면 두 화면이 다른 숫자를 말한다.
RECOMMENDED_CEILING_KRW: Final[int] = 200_000_000

#: 주소 문자열에서 읽어 낼 광역 이름. 긴 이름부터 맞춘다.
_ADDRESS_REGIONS: tuple[tuple[str, str], ...] = (
    ("전남광주통합특별시", "전남광주"),
    ("광주광역시", "전남광주"),
    ("전라남도", "전남광주"),
    ("서울특별시", "서울"),
    ("부산광역시", "부산"),
    ("대구광역시", "대구"),
    ("인천광역시", "인천"),
    ("대전광역시", "대전"),
    ("울산광역시", "울산"),
    ("세종특별자치시", "세종"),
    ("경기도", "경기"),
    ("강원특별자치도", "강원"),
    ("충청북도", "충북"),
    ("충청남도", "충남"),
    ("전북특별자치도", "전북"),
    ("경상북도", "경북"),
    ("경상남도", "경남"),
    ("제주특별자치도", "제주"),
)


def _region_from_address(address: str | None) -> str | None:
    """회사 주소에서 소재 광역을 읽는다. 지어내는 것이 아니라 **회사가 적은 값**을 읽는 것이다.

    소재지 칸(`delivery_capacity.location_region`)이 비어 있을 때의 대체 경로다. 주소도
    없으면 None — 그때는 지역 판정을 「확인 필요」로 둔다.
    """
    if not address:
        return None
    for token, canonical in _ADDRESS_REGIONS:
        if token in address:
            return canonical
    return None


#: 원장 행에서 판정에 쓰는 칸 — 값이 전부 문자열·숫자·None 이라 해시된다.
_LEDGER_KEYS: Final[tuple[str, ...]] = (
    "seq", "year", "period", "field", "title", "agency", "summary",
    "amount_thousand_krw", "amount_basis", "evidence_note",
)


#: 옛 광주광역시의 자치구 — 전남광주통합특별시 주소에서 이 구가 보이면 옛 광주다(옛 전라남도에는 자치구가 없다).
_OLD_GWANGJU_GU = re.compile(r"(?<![가-힣])(?:동구|서구|남구|북구|광산구)(?![가-힣])")
#: 옛 전라남도의 시 · 군(통합특별시 이름 뒤).
_OLD_JEONNAM_CITY = re.compile(r"통합특별시\s+[가-힣]{1,4}(?:시|군)(?![가-힣])")


def _old_region_from_address(address: str | None) -> str | None:
    """주소가 통합 전 어느 쪽인가 — 「광주」 · 「전남」 · 모르면 None(35차 R34S-04)."""
    text = address or ""
    if "광주광역시" in text:
        return "광주"
    if "전라남도" in text:
        return "전남"
    if "전남광주통합특별시" in text:
        if _OLD_GWANGJU_GU.search(text):
            return "광주"
        if _OLD_JEONNAM_CITY.search(text):
            return "전남"
    return None


#: 광주 · 전남(통합특별시 포함) 이름 바로 뒤의 시 · 군 · 구 — 「전남광주통합특별시 영암군」 · 「광주광역시 북구」 · 「전라남도 나주시」(43차 H2).
_HOME_UNIT_RE = re.compile(
    r"(전남광주통합특별시|광주광역시|전라남도|광주|전남)\s*([가-힣]{1,5}(?:시|군|구))"
    r"(?=$|[^가-힣]|에|의|내|소재|관내|지역|와|과|및|또는)"  # 「영암군에 주된 영업소」 · 「북구 소재」
)
#: 시 · 군 · 구 없이 옛 한쪽만 가리키는 이름.
_HOME_OLD_ONLY: Final = {"광주광역시": "광주", "전라남도": "전남"}


def _home_units(text: str) -> list[str]:
    """글 속 광주 · 전남 시 · 군 · 구 이름(「북구」 · 「영암군」). 옛 전남에는 구가 없어 이름이 겹치지 않는다."""
    # 「광주광역시」 · 「전남광주통합특별시」 자체를 「광주」 + 「광역시」로 읽지 않는다
    return [m.group(2) for m in _HOME_UNIT_RE.finditer(text or "") if not m.group(2).endswith(("특별시", "광역시", "자치시"))]


def _home_scope_verdict(names: Sequence[str], company: CompanyFacts) -> bool | None:
    """광주 · 전남 안 참가지역(시 · 군 · 구 · 옛 광주 · 옛 전남 · 통합 전체)에 회사가 드는가 — 대조를 못 하면 None(43차 H2).

    「전남광주통합특별시 ○○시 · 군」 22곳 목록을 광역 이름만 보고 광주 북구 회사에게 「가능」이라 했다(1776501)."""
    olds = {o for name in names if not _home_units(name) for token, o in _HOME_OLD_ONLY.items() if token in name}
    if olds >= {"광주", "전남"}:
        return True  # 「광주광역시 · 전라남도」 둘 다 열림 = 통합 전체
    unknown = False
    for name in names:
        units = _home_units(name)
        if units:
            if company.location_district is None:
                unknown = True
            elif company.location_district in units:
                return True
            continue
        old = next((o for token, o in _HOME_OLD_ONLY.items() if token in name), None)
        if old is None:
            return True  # 통합 전체 · 「광주 · 전남」 — 시 · 군을 가리지 않는다
        if company.location_old_region is None:
            unknown = True
        elif company.location_old_region == old:
            return True
    return None if unknown else False


def _ledger_facts(organization_id: str, evidence_scope: str | None) -> tuple[tuple, bool]:
    """실적 원장의 외부 사용 가능 행. **내부 범위가 아니면 읽지 않는다.**"""
    if evidence_scope != "internal":
        return (), False
    from app.services import performance_match_service as _pm

    try:
        ledger = _pm.load_ledger(_pm.ledger_path_for(organization_id))
    except Exception:  # noqa: BLE001 — 원장이 깨져도 판정은 한다(실적 조항은 확인 필요로 남는다)
        logger.warning("실적 원장을 읽지 못했습니다 (%s)", organization_id, exc_info=True)
        return (), False
    # **실제 수행 사업 행만** — 인증·지정·저작권·설립 행은 「실적」이 아니다(원장의 `project_rows` 와 같은 기준).
    # 실측: 한양사이버대 구축 실적 조항에 「저작권 등록 … 데이터세트」 행이 맞았었다.
    rows = tuple(
        tuple((key, row.get(key)) for key in _LEDGER_KEYS) for row in _pm.project_rows(ledger)
    )
    return rows, ledger is not None


#: 준비 상태 줄 이름 — 띄어쓰기 · 괄호 안을 빼고 견준다(화면 `firstTimeGuide.nameKey` 와 같은 규칙).
_SME_CERT_KEYS: Final[frozenset[str]] = frozenset({"중소기업확인서", "중소기업·소상공인확인서", "중소기업소상공인확인서"})
#: 확인서가 「있음」인지 · 유효한지 — 두 판정(나라장터 기업 유형 조항 · 기업마당 BIZ-SME)이 같은 말을 쓴다.
SmeState = Literal["valid", "expired", "none", "unknown"]


def sme_credential(credentials: Any) -> Any | None:
    """회사자료 준비 상태의 「중소기업(소상공인) 확인서」 줄. 없으면 None."""
    for row in credentials or ():
        if re.sub(r"\([^)]*\)|\s+", "", getattr(row, "name", "") or "") in _SME_CERT_KEYS:
            return row
    return None


def sme_state(company: CompanyFacts, today: date) -> SmeState:
    """있음 + 유효기간 안(모르면 유효로 본다) · 있음 + 지남 · 없음(확인함) · 모름."""
    if company.sme_held is None:
        return "unknown"
    if company.sme_held is False:
        return "none"
    if company.sme_valid_until is not None and company.sme_valid_until < today:
        return "expired"
    return "valid"


def company_facts_for(organization_id: str | None, *, evidence_scope: str | None = None) -> CompanyFacts:
    """조직이 적어 둔 값으로 판정용 사실을 만든다 (0921 §4-B).

    **여기가 「회사 쪽 사실」의 단일 출입구다.** 목록 게이트와 상세 판정이 같은 함수를 써야
    두 화면이 같은 답을 낸다. 파일이 없거나 값이 비어 있으면 그대로 「미입력」으로 둔다 —
    없는 값을 지어내면 근거 없는 「가능」이 생긴다(CLAUDE.md §11).
    """
    if not organization_id:
        return CompanyFacts()
    ledger_rows, ledger_available = _ledger_facts(organization_id, evidence_scope)
    # 늦게 들여온다 — 모듈 맨 위에서 부르면 import 고리가 생긴다.
    from app.services import delivery_capacity_service

    from app.services import organization_service as _orgs

    capacity = delivery_capacity_service.load(organization_id)
    try:
        profile = _orgs.load_profile(organization_id)
    except Exception:  # noqa: BLE001 — 프로필이 없어도 입찰 자격은 판정한다
        profile = None
    sme = sme_credential(capacity.credentials)
    return CompanyFacts(
        from_real_company=True,
        certifications=tuple(getattr(profile, "certifications", ()) or ()),
        certification_history=tuple(getattr(profile, "certification_history", ()) or ()),
        location_region=capacity.location_region or _region_from_address(getattr(profile, "address", None)),
        location_old_region=_old_region_from_address(getattr(profile, "address", None)),
        location_district=next(iter(_home_units(getattr(profile, "address", None) or "")), None),
        activity_regions=tuple(getattr(profile, "preferred_regions", ()) or ()),
        founded_year=getattr(profile, "founded_year", None),
        founded_on=_opened_on(organization_id),
        employee_count=getattr(profile, "employee_count", None),
        revenue_krw_last_year=capacity.revenue_krw_last_year,
        has_research_department=capacity.has_research_department,
        research_department_kind=capacity.research_department_kind if capacity.has_research_department else None,
        sme_held=sme.held if sme is not None else None,
        sme_grade=sme.grade if sme is not None else None,
        sme_valid_until=sme.valid_until if sme is not None else None,
        data_products=tuple(capacity.data_products or ()),
        supplier_registrations=tuple(capacity.supplier_registrations or ()),
        completed_programs=tuple(capacity.completed_programs or ()),
        registered_industry_codes=tuple(i.code for i in capacity.registered_industries if i.code),
        registered_industry_names=tuple(i.name for i in capacity.registered_industries if i.name),
        budget_ceiling_krw=capacity.budget_ceiling_krw,
        joint_bid_available=(
            capacity.joint_bid_partner.available if capacity.joint_bid_partner is not None else None
        ),
        proposal_lead_days=capacity.proposal_lead_days,
        ledger_rows=ledger_rows,
        ledger_available=ledger_available,
        clause_reviews=_clause_review_facts(organization_id, evidence_scope),
        company_checks=tuple(
            (key, check.confirmed_on.isoformat(), check.valid_until.isoformat(), check.confirmed_by)
            for key, check in sorted(capacity.company_checks.items())
        ),
        direct_production_items=tuple(capacity.direct_production_items or ()),
        digital_products=tuple(capacity.digital_products or ()),
    )


def _opened_on(organization_id: str) -> date | None:
    """일반현황의 개업연월일 — 없거나 못 읽으면 None(지어내지 않는다)."""
    from app.services import organization_service as _orgs

    try:
        return _orgs.load_plan_general(organization_id).opened_on
    except Exception:  # noqa: BLE001 — 일반현황이 없어도 판정은 연도로 한다
        return None


#: 경계 날짜와 오늘이 이만큼 가까우면 공고 기준일(공고일 · 마감일)에 따라 갈린다 — 확인 필요로 둔다.
_FOUNDING_EDGE_MARGIN_DAYS = 30


def founding_edge(company: CompanyFacts, limit: int, today: date) -> tuple[EligibilityStatus, str] | None:
    """창업 연차 경계 해(설립 뒤 `limit` 년)를 개업일로 가른다(43차 COMPANY-07 — 설립일이 문서에 있는데 연도만 봐서 사람에게 넘겼다).
    개업일이 없거나 경계 날짜가 오늘과 30일 안이면 None(지금처럼 확인 필요)."""
    opened = company.founded_on
    if opened is None:
        return None
    try:
        boundary = opened.replace(year=opened.year + limit)
    except ValueError:  # 2월 29일
        boundary = opened.replace(year=opened.year + limit, day=28)
    if abs((boundary - today).days) <= _FOUNDING_EDGE_MARGIN_DAYS:
        return None
    if today < boundary:
        return "PASS", f"개업일 {opened.isoformat()}(일반현황) — 창업 {limit}년이 {boundary.isoformat()}까지라 오늘 기준으로 맞습니다"
    return "FAIL", f"개업일 {opened.isoformat()}(일반현황) — 창업 {limit}년이 {boundary.isoformat()}에 지났습니다"


def company_check_state(company: CompanyFacts, keys: Sequence[str], today: date) -> tuple[str, str]:
    """회사 단위 확인 칸들의 상태 — (「valid」 · 「expired」 · 「missing」, 화면 글). 하나라도 없으면 missing, 지났으면 expired(43차 결정 2)."""
    from app.schemas.delivery_capacity import COMPANY_CHECK_LABELS

    found = {key: (on, until, by) for key, on, until, by in company.company_checks}
    missing = [COMPANY_CHECK_LABELS[k] for k in keys if k not in found]
    if missing:
        return "missing", " · ".join(missing)
    expired = [(COMPANY_CHECK_LABELS[k], found[k][1]) for k in keys if date.fromisoformat(found[k][1]) < today]
    if expired:
        return "expired", " · ".join(f"{name}(유효 {until} 지남)" for name, until in expired)
    latest = max(found[k][0] for k in keys)
    return "valid", latest


def _clause_review_facts(organization_id: str, evidence_scope: str | None) -> tuple[tuple[str, ...], ...]:
    from app.services import qualification_review_service as _qr

    try:
        return _qr.facts_for(organization_id, evidence_scope)
    except Exception as exc:  # noqa: BLE001 — 확인 기록을 못 읽어도 규칙 판정은 한다
        logger.warning("조항 확인 기록을 읽지 못했습니다: %s", exc.__class__.__name__)
        return ()


def _region_tokens(region: str | None) -> tuple[str, ...]:
    """소재지 이름 하나를 대조용 별칭까지 펼친다.

    통합 이후 이름은 「전남광주」인데 공고의 참가가능지역은 아직 「광주광역시」·「전라남도」로
    온다(2026-09-17 실측). 같은 곳을 다른 이름이라고 읽으면 들어갈 수 있는 공고를 버린다.
    """
    if not region:
        return ()
    text = region.strip()
    if not text:
        return ()
    aliases = {
        "전남광주": ("전남광주", "광주광역시", "광주", "전라남도", "전남"),
        "광주광역시": ("전남광주", "광주광역시", "광주"),
        "전라남도": ("전남광주", "전라남도", "전남"),
    }
    return aliases.get(text, (text,))


def active_regions() -> tuple[str, ...]:
    regions = _ACTIVE_REGIONS.get()
    if regions is None and get_settings().neutral_company_defaults:
        return ()  # 키트 — 회사가 적지 않은 지역을 광주·전남으로 채우지 않는다(30차 §3-G · 「확인 필요」)
    return COMPANY_PROFILE.preferred_regions if regions is None else regions


def _region_allowed(text: str) -> bool:
    # 대표 이름끼리 견준다 — 낱말 포함(「광주」 in 「경기도 광주시」)으로 보면 다른 도의 시 · 군에 맞았다(34차 R33-D1)
    wanted = set(_region_names(text))
    mine = {name for region in active_regions() if region != "전국" for name in (_region_names(region) or [region])}
    return bool(wanted & mine)


def _parse_notice_datetime(value: str) -> datetime | None:
    return g2b_mapper.parse_datetime(value)


def _as_aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=KST)


# ---------------------------------------------------------------------------
# 1) 공고 원문 필드 기반 규칙
# ---------------------------------------------------------------------------


def _allowed_regions(raw: dict[str, Any]) -> list[str] | None:
    """공고의 참가가능지역. **None 은 「받아 본 적 없음」**이고 [] 는 「지역 제한 없음」이다."""
    value = raw.get("allowed_regions")
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return None


def _rule_region(raw: dict[str, Any]) -> EligibilityResult:
    # 0921 §4-B — 참가가능지역 목록이 있으면 **그것이 먼저다.** 판단기준 이름
    # (「본사또는참여지사소재지」)은 지역이 아니라 «무엇으로 판단할지»의 이름이라,
    # 대상 지역을 실제로 담은 이 목록보다 약한 근거다.
    allowed = _allowed_regions(raw)
    if allowed:
        company = active_company()
        tokens = _region_tokens(company.location_region)
        source = f"공고 참가가능지역 {' · '.join(allowed)}"
        if not tokens:
            return EligibilityResult(
                rule_id="ELIG-REGION",
                label="지역제한",
                status="CHECK",
                method="RULE",
                source=source,
                reason="공고에 참가 가능 지역이 정해져 있는데 회사 소재지가 아직 없습니다. 회사자료에 소재지를 적어야 판정할 수 있습니다.",
                unlock_condition="회사자료에 소재 광역을 적으면 판정할 수 있습니다",
                check_side="company",
            )
        # 대표 이름끼리 견준다 — 「경기도 광주시」는 경기다(34차 R33-D1 · 1761269)
        mine = set(_region_names(company.location_region or "") or [company.location_region or ""])
        same_province = [name for name in allowed if mine & set(_region_names(name) or [name])]
        home = "전남광주" in mine and same_province and not [n for n in same_province if _PROVINCE_CITY_RE.search(n) and not _home_units(n)]
        verdict = _home_scope_verdict(same_province, company) if home else None
        listed = ", ".join(same_province[:3]) + (f" 외 {len(same_province) - 3}곳" if len(same_province) > 3 else "")
        if verdict is True and any(_home_units(n) or any(t in n for t in _HOME_OLD_ONLY) for n in same_province):
            return EligibilityResult(
                rule_id="ELIG-REGION", label="지역제한", status="PASS", method="RULE", source=source,
                reason=f"참가 가능 지역 {listed}에 회사 주소({company.location_district or company.location_old_region})가 듭니다.",
            )
        if verdict is False:
            # 이전을 권하지 않는다 — 열리는 조건 없음(43차 N3)
            return EligibilityResult(
                rule_id="ELIG-REGION", label="지역제한", status="FAIL", method="RULE", source=source,
                reason=f"참가 가능 지역이 {listed}(시 · 군 단위)이고 회사 주소({company.location_district or company.location_old_region})는 거기에 없습니다.",
            )
        if home and verdict is None:
            return EligibilityResult(
                rule_id="ELIG-REGION", label="지역제한", status="CHECK", method="RULE", source=source,
                reason=f"참가 가능 지역이 {listed}(시 · 군 단위)입니다. 회사 주소의 시 · 군 · 구가 거기에 드는지 확인하세요.",
                check_side="company",
            )
        if same_province and all(_PROVINCE_CITY_RE.search(name) for name in same_province):
            # 우리 도 안의 **시 · 군**만 열린 공고 — 회사 주소의 시 · 군을 모르면 확정하지 않는다
            return EligibilityResult(
                rule_id="ELIG-REGION",
                label="지역제한",
                status="CHECK",
                method="RULE",
                source=source,
                reason=f"참가 가능 지역이 {', '.join(same_province)}(시 · 군 단위)입니다. 회사 주소의 시 · 군이 거기에 드는지 확인하세요.",
                check_side="company",
            )
        if same_province:
            return EligibilityResult(
                rule_id="ELIG-REGION",
                label="지역제한",
                status="PASS",
                method="RULE",
                source=source,
                reason=f"회사 소재지({company.location_region})가 참가 가능 지역에 듭니다.",
            )
        return EligibilityResult(
            rule_id="ELIG-REGION",
            label="지역제한",
            status="FAIL",
            method="RULE",
            source=source,
            reason=f"참가 가능 지역이 {', '.join(allowed)} 이고 회사 소재지({company.location_region})는 거기에 없습니다.",
            # 갭 리포트가 「○○ 소재였다면 몇 건」을 셀 수 있게 지역마다 하나씩 (0922 §4-A-5).
            # **갖출 수 있는 조건이 아니다** — 그래도 담당자가 「어디에 있었다면 되는가」를
            # 알면 지사·컨소시엄을 판단할 수 있다.
            unlock_condition=f"{allowed[0]} 소재 시 가능" + (f" (또는 {len(allowed) - 1}곳)" if len(allowed) > 1 else ""),
            unlock_options=[f"{name} 소재 시 가능" for name in allowed],
        )

    limit = _notice_field(raw, "rgnLmtBidLocplcJdgmBssNm")
    if allowed == []:
        # **받았는데 지역 제한 행이 없다.** 판단기준 이름(「본사또는참여지사소재지」)이 붙어
        # 있어도, 대상 지역을 실제로 담은 이 목록이 비었으면 지역으로 막지 않는 공고다.
        return EligibilityResult(
            rule_id="ELIG-REGION",
            label="지역제한",
            status="PASS",
            method="RULE",
            source="공고 참가가능지역 (없음)"
            + (f" · {_fields(('rgnLmtBidLocplcJdgmBssNm', limit))}" if limit else ""),
            reason="나라장터에 지역 제한이 등록돼 있지 않습니다 — 어느 지역 업체든 참가할 수 있습니다.",
        )
    if not limit:
        # 참가가능지역 목록(`allowed_regions`)이 지역 제한의 근거다 — 판단기준 칸은 제한 공고에서도 자주 비어 온다(10-08 저장본:
        # 목록이 있는 9건 중 8건이 칸이 빔). 목록을 **받아 본 적 없으면**(받은 뒤 게시 · 그날 자격 미수집) 확정하지 않는다(34차 R33-D2).
        return EligibilityResult(
            rule_id="ELIG-REGION",
            label="지역제한",
            status="CHECK",
            method="RULE",
            source="공고 참가가능지역 — 자격 정보 미수집",
            reason="이 공고의 참가가능지역(자격 정보)을 아직 받지 못해 지역 제한을 확인하지 못했습니다. 다음 목록 받기 때 다시 보거나 공고문에서 확인하세요.",
            check_side="notice",
            unlock_condition="자격 정보를 받으면 지역 제한이 확정됩니다",
        )
    regions = active_regions()
    if not regions:
        return EligibilityResult(
            rule_id="ELIG-REGION",
            label="지역제한",
            status="CHECK",
            method="RULE",
            source=f"나라장터 기본정보 — {_fields(('rgnLmtBidLocplcJdgmBssNm', limit))}",
            reason="회사 프로필에 활동 지역이 없어 지역제한 충족 여부를 판정하지 못했습니다. 회사자료에 활동 지역을 적으면 다시 판정합니다.",
            check_side="company",
        )
    if not g2b_mapper.contains_region_name(limit):
        # 「본사또는참여지사소재지」처럼 이 필드에는 지역 «이름»이 아니라 소재지를 무엇으로
        # 판단할지 정하는 «기준의 이름»이 들어오는 쪽이 오히려 흔하다 (캐시 76건 중 53건).
        # 그것을 지역으로 읽어 회사 활동 지역과 다르다고 FAIL 을 내고 있었다 — 대상 지역을
        # 모르는데 참가 불가로 단정한 것이고, 들어갈 수 있는 공고를 버리는 판정이다.
        return EligibilityResult(
            rule_id="ELIG-REGION",
            label="지역제한",
            status="CHECK",
            method="RULE",
            source=f"나라장터 기본정보 — {_fields(('rgnLmtBidLocplcJdgmBssNm', limit))}",
            reason=(
                f"'{limit}'는 소재지 판단기준의 이름이지 대상 지역이 아닙니다. "
                "목록 응답에는 제한 대상 지역이 없으므로 공고문에서 지역제한 대상 지역을 직접 확인하세요."
            ),
        )
    if _region_allowed(limit):
        return EligibilityResult(
            rule_id="ELIG-REGION",
            label="지역제한",
            status="PASS",
            method="RULE",
            source=f"나라장터 기본정보 — {_fields(('rgnLmtBidLocplcJdgmBssNm', limit))}",
            reason=f"지역제한 대상 지역이 회사 소재·선호 지역({', '.join(regions)})에 포함됩니다.",
        )
    return EligibilityResult(
        rule_id="ELIG-REGION",
        label="지역제한",
        status="FAIL",
        method="RULE",
        source=f"나라장터 기본정보 — {_fields(('rgnLmtBidLocplcJdgmBssNm', limit))}",
        reason=f"지역제한 대상이 '{limit}'인데 회사 소재 · 활동 지역({', '.join(r for r in regions if r != '전국') or '아직 없음'})과 다릅니다.",
    )


def _rule_joint_region(raw: dict[str, Any]) -> EligibilityResult | None:
    duty_region = _notice_field(raw, "jntcontrctDutyRgnNm1")
    if not duty_region:
        return None
    matched = _region_allowed(duty_region)
    reason = (
        f"지역의무공동도급 대상 지역은 '{duty_region}'입니다. "
        + (
            "회사 소재 지역과 일치하지만 공동수급체 구성 여부는 직접 확인하세요."
            if matched
            else "회사 소재 지역과 달라 해당 지역 업체와의 공동수급 구성이 필요한지 확인하세요."
        )
    )
    return EligibilityResult(
        rule_id="ELIG-JOINT-REGION",
        label="지역의무공동도급",
        status="CHECK",
        method="RULE",
        source=f"나라장터 기본정보 — {_fields(('jntcontrctDutyRgnNm1', duty_region))}",
        reason=reason,
    )


def _license_limits(raw: dict[str, Any]) -> list[dict[str, Any]] | None:
    """공고의 면허제한 목록. **None 은 「받아 본 적 없음」**이고 [] 는 「제한 없음」이다."""
    value = raw.get("license_limits")
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return None


def industry_label(row: dict[str, Any]) -> str:
    """면허제한 한 줄을 사람이 읽는 이름으로. **코드와 이름을 그대로** 적는다 (0922 §4-A-4).

    「소프트웨어사업자(컴퓨터관련서비스사업, 1468)」. 코드가 없으면 이름만 — 지어내지 않는다.
    """
    name = str(row.get("name") or "").strip()
    code = str(row.get("code") or "").strip()
    if name and code:
        return f"{name}, {code}"
    return name or code or "업종 미상"


def industry_unlock(row: dict[str, Any]) -> str:
    """이 업종 하나를 등록하면 열린다는 조건 한 줄. 갭 리포트가 코드별로 센다."""
    return f"{industry_label(row)} 등록 시 가능"


def _industry_codes(limits: list[dict[str, Any]]) -> set[str]:
    """공고가 받아 주는 업종 코드 전부 (면허 코드 + 허용 업종 목록 안의 코드)."""
    allowed: set[str] = set()
    for row in limits:
        code = str(row.get("code") or "").strip()
        if code:
            allowed.add(code)
        for entry in row.get("allowed_industries") or []:
            match = _INDUSTRY_CODE_RE.search(str(entry))
            if match:
                allowed.add(match.group(1))
    return allowed


#: 허용 업종 목록은 「[식품제조·가공업/1399]」처럼 이름과 코드가 붙어 온다.
_INDUSTRY_CODE_RE = re.compile(r"(\d{3,5})\s*\]?\s*$")


def _rule_industry_limit(raw: dict[str, Any]) -> EligibilityResult:
    """ELIG-INDUSTRY — 등록 업종과 공고의 면허제한을 **코드로** 대조한다 (0922 §4-A-4).

    8차에서 값이 실제로 들어왔다. 7차까지는 면허제한 목록을 받지 못해 업종제한 공고가 전부
    「공고문 확인」이었는데(ISSUE-081), 하루 창으로 받으니 용역 공고의 업종 코드가 그대로
    온다 — 캐시 191건 중 125건에 제한이 있고 그중 64건이 1468 이다.

    판정 규칙 넷:
      - 제한 목록이 없음(`None`) → 확인 필요 (「자격 정보 미수집」)
      - 제한 목록이 빈 목록(`[]`) → 가능 (제한 없음)
      - 회사 등록 업종이 미입력 → **불가가 아니라 확인 필요** + 열리는 조건에 코드·이름
      - 교집합이 있으면 가능, 없으면 불가 + 열리는 조건
    """
    flag = _notice_field(raw, "indstrytyLmtYn", "industry_limit").upper()
    limits = _license_limits(raw)
    company = active_company()

    if limits:
        label_text = " · ".join(industry_label(row) for row in limits)
        options = list(dict.fromkeys(industry_unlock(row) for row in limits))
        source = f"나라장터 기본정보 — 요구 업종: {label_text}"
        allowed = _industry_codes(limits)
        if not company.registered_industry_codes:
            return EligibilityResult(
                rule_id="ELIG-INDUSTRY",
                label="업종 제한",
                status="CHECK",
                method="RULE",
                source=source,
                reason=(
                    f"공고가 요구하는 업종은 {label_text} 입니다. 회사의 나라장터 등록 업종이 "
                    "아직 없어 정하지 못했습니다 — 회사자료에 등록 업종을 적으면 판정합니다."
                ),
                # 채울 쪽은 회사다 — 조항 줄(QUAL-INDUSTRY)과 같은 표시를 단다.
                check_side="company",
                unlock_condition=" 또는 ".join(options) if len(options) <= 2 else f"{options[0]} (또는 {len(options) - 1}종 중 하나)",
                unlock_options=options,
            )
        if allowed & set(company.registered_industry_codes):
            hit = sorted(allowed & set(company.registered_industry_codes))
            return EligibilityResult(
                rule_id="ELIG-INDUSTRY",
                label="업종 제한",
                status="PASS",
                method="RULE",
                source=source,
                reason=f"회사 등록 업종 {', '.join(hit)} 이(가) 공고가 요구하는 업종({label_text})에 듭니다.",
            )
        # 44차 결정 4(담당자 2026-10-23) — 업종이 없어도 공동수급이 허용이면 「불가」가 아니라 「확인 필요 · 파트너형」이다.
        # 모르면(방식 칸 없음) 확인 필요 「공동수급 확인 필요」 · 불허만 그대로 불가. 열리는 조건(「… 등록 시 가능」)은 그대로 둬
        # 갭 보고(「1468 등록 시」)가 계속 센다. 「가능」은 나오지 않는다.
        joint = joint_allowed(raw)
        if joint is not False:
            method = _notice_field(raw, "cmmnSpldmdMethdNm", "joint_supply_method")
            how = re.sub(r"^\([^)]*\)\s*", "", method) or method
            return EligibilityResult(
                rule_id="ELIG-INDUSTRY",
                label="업종 제한",
                status="CHECK",
                method="RULE",
                source=f"{source} · 공동수급 방식: {method or '없음(나라장터 칸 비어 있음)'}",
                reason=(
                    f"{INDUSTRY_PARTNER_HEAD}{label_text}) — 공동수급 허용({how}): 이 업종을 가진 회사와 공동수급을 검토하세요"
                    " · 공동이행은 보통 구성원 모두 그 업종이 있어야 합니다(공고문 확인)."
                    if joint else
                    f"{INDUSTRY_PARTNER_HEAD}{label_text}) — 공동수급 확인 필요: 나라장터에 공동수급 방식이 없습니다. 허용이면 이 업종을"
                    " 가진 회사와 공동수급을 검토하고, 불허면 참가할 수 없습니다(공고문 확인)."
                ),
                check_side="company",
                unlock_condition=" 또는 ".join(options) if len(options) <= 2 else f"{options[0]} (또는 {len(options) - 1}종 중 하나)",
                unlock_options=options,
            )
        return EligibilityResult(
            rule_id="ELIG-INDUSTRY",
            label="업종 제한",
            status="FAIL",
            method="RULE",
            source=source,
            reason=(
                f"공고가 요구하는 업종({label_text})이 회사 등록 업종"
                f"({', '.join(company.registered_industry_codes)})에 없습니다."
            ),
            unlock_condition=" 또는 ".join(options) if len(options) <= 2 else f"{options[0]} (또는 {len(options) - 1}종 중 하나)",
            unlock_options=options,
        )

    if limits == []:
        # **받았는데 제한 행이 없다.** 「미확인」과 다른 사실이다 — 참가 업종을 제한하지 않는다.
        return EligibilityResult(
            rule_id="ELIG-INDUSTRY",
            label="업종 제한",
            status="PASS",
            method="RULE",
            source=f"나라장터 기본정보 — 요구 업종 없음 · {_fields(('indstrytyLmtYn', flag))}",
            reason="나라장터에 업종 제한이 등록돼 있지 않습니다.",
        )

    if flag == "Y":
        return EligibilityResult(
            rule_id="ELIG-INDUSTRY",
            label="업종 제한",
            status="CHECK",
            method="RULE",
            source=f"나라장터 기본정보 — {_fields(('indstrytyLmtYn', flag))} · 면허제한 자격 정보 미수집",
            reason=(
                "업종제한 공고인데 이 공고 게시일의 자격 정보를 아직 받지 못했습니다. "
                "공고 목록을 갱신하면 그 날의 면허제한을 받아 업종을 확정합니다."
            ),
            unlock_condition="자격 정보를 받으면 요구 업종이 확정됩니다",
        )
    return EligibilityResult(
        rule_id="ELIG-INDUSTRY",
        label="업종 제한",
        status="PASS",
        method="RULE",
        source=f"나라장터 기본정보 — {_fields(('indstrytyLmtYn', flag))}",
        reason="업종 제한이 없는 공고입니다.",
    )


def _rule_participation_limit(raw: dict[str, Any]) -> EligibilityResult:
    """ELIG-TRACK-RECORD — 실적·참가 제한 (0921 §4-B).

    예전 이름은 `ELIG-PARTICIPATION` 이었다. 실적평가 여부(`arsltCmptYn`)를 함께 보게 되면서
    「무엇 때문에 확인해야 하는가」를 말할 수 있게 됐으므로 이름을 그에 맞췄다.
    근거는 버리지 않는다 — 두 필드를 한 줄에 함께 적는다.
    """
    limit = _notice_field(raw, "bidPrtcptLmtYn", "participation_limit").upper()
    result_eval = _notice_field(raw, "arsltCmptYn", "result_evaluation").upper()
    source = f"나라장터 기본정보 — {_fields(('bidPrtcptLmtYn', limit), ('arsltCmptYn', result_eval))}"
    if result_eval == "Y":
        return EligibilityResult(
            rule_id="ELIG-TRACK-RECORD",
            label="실적·참가 제한",
            status="CHECK",
            method="RULE",
            source=source,
            reason="실적을 평가하는 공고입니다. 회사 실적 목록과 견줘 요구 실적을 채우는지 확인하세요.",
        )
    if limit == "Y":
        return EligibilityResult(
            rule_id="ELIG-TRACK-RECORD",
            label="실적·참가 제한",
            status="CHECK",
            method="RULE",
            source=source,
            reason="참가제한이 설정된 공고입니다. 제한 사유(실적·인증·지정업체 등)를 공고문에서 확인하세요.",
        )
    return EligibilityResult(
        rule_id="ELIG-TRACK-RECORD",
        label="실적·참가 제한",
        status="PASS",
        method="RULE",
        source=source,
        reason="실적 평가도 별도 참가 제한도 없는 공고입니다.",
    )


def _rule_consortium_region(raw: dict[str, Any]) -> EligibilityResult:
    value = _notice_field(raw, "cmmnSpldmdCorpRgnLmtYn")
    if joint_allowed(raw) is False:
        # 공동수급 불허 공고에 「함께 낼 때의 지역 제한 없음 — 가능」을 붙이지 않는다(43차 ELIG-09)
        return EligibilityResult(
            rule_id="ELIG-CONSORTIUM-REGION", label="공동수급체 지역제한", status="PASS", method="RULE",
            source=f"나라장터 기본정보 — 공동수급 방식: {_notice_field(raw, 'cmmnSpldmdMethdNm', 'joint_supply_method')}",
            reason="해당 없음(공동수급 불허).",
        )
    if value.upper() == "Y":
        return EligibilityResult(
            rule_id="ELIG-CONSORTIUM-REGION",
            label="공동수급체 지역제한",
            status="CHECK",
            method="RULE",
            source=f"나라장터 기본정보 — {_fields(('cmmnSpldmdCorpRgnLmtYn', value))}",
            reason="공동수급체 구성원에 지역제한이 있습니다. 단독 수행이 가능한지, 공동수급 시 지역 요건을 만족하는지 확인하세요.",
        )
    return EligibilityResult(
        rule_id="ELIG-CONSORTIUM-REGION",
        label="공동수급체 지역제한",
        status="PASS",
        method="RULE",
        source=f"나라장터 기본정보 — {_fields(('cmmnSpldmdCorpRgnLmtYn', value))}",
        # 회사가 혼자 내는지는 회사자료에 없다 — 사실만(33차 R32-07)
        reason="다른 회사와 함께 낼 때의 지역 제한이 없습니다.",
    )


def _rule_contract_method(raw: dict[str, Any]) -> EligibilityResult:
    """**더는 규칙 목록에 넣지 않는다** (0921 §4-B).

    「제한경쟁」이라는 이유만으로 「확인 필요」를 만들고 있었는데, 제한경쟁은 자격 문제가
    아니라 «어떻게 뽑는가»다. 그 정보는 `ELIG-AWARD` 가 계약방법·낙찰방식·기술:가격 비율과
    함께 한 줄로 알려 준다. 함수는 남겨 둔다 — 기존 테스트가 이 판정 자체를 재고 있다.
    """
    method_name = _notice_field(raw, "cntrctCnclsMthdNm", "contract_method")
    if not method_name:
        return EligibilityResult(
            rule_id="ELIG-CONTRACT-METHOD",
            label="계약방법",
            status="CHECK",
            method="RULE",
            source=f"나라장터 기본정보 — {_fields(('cntrctCnclsMthdNm', method_name))}",
            reason="계약체결방법이 나라장터 기본정보에 없습니다. 공고문에서 직접 확인하세요.",
        )
    if "일반경쟁" in method_name:
        return EligibilityResult(
            rule_id="ELIG-CONTRACT-METHOD",
            label="계약방법",
            status="PASS",
            method="RULE",
            source=f"나라장터 기본정보 — {_fields(('cntrctCnclsMthdNm', method_name))}",
            reason="일반경쟁이라 별도 참가 제한 없이 입찰할 수 있습니다.",
        )
    return EligibilityResult(
        rule_id="ELIG-CONTRACT-METHOD",
        label="계약방법",
        status="CHECK",
        method="RULE",
        source=f"나라장터 기본정보 — {_fields(('cntrctCnclsMthdNm', method_name))}",
        reason=f"'{method_name}' 공고입니다. 제한·지명 사유와 대상 요건을 공고문에서 확인하세요.",
    )


def _deadline_rule(
    *,
    rule_id: str,
    label: str,
    field_name: str,
    raw_value: str,
    as_of: datetime,
    passed_reason: str,
    missing_reason: str,
) -> EligibilityResult:
    if not raw_value:
        return EligibilityResult(
            rule_id=rule_id,
            label=label,
            status="CHECK",
            method="RULE",
            source=f"나라장터 기본정보 — {_fields((field_name, raw_value))}",
            reason=missing_reason,
        )
    moment = _parse_notice_datetime(raw_value)
    if moment is None:
        return EligibilityResult(
            rule_id=rule_id,
            label=label,
            status="CHECK",
            method="RULE",
            source=f"나라장터 기본정보 — {_fields((field_name, raw_value))}",
            reason="기한 형식을 읽지 못했습니다. 공고문에서 직접 확인하세요.",
        )
    return _moment_rule(
        rule_id=rule_id, label=label, moment=moment, as_of=as_of, passed_reason=passed_reason,
        source=f"나라장터 기본정보 — {_fields((field_name, raw_value))}",
    )


def _moment_rule(
    *, rule_id: str, label: str, moment: datetime, as_of: datetime, passed_reason: str, source: str
) -> EligibilityResult:
    """기한 하나(나라장터 필드 또는 공고문 일정표 · 43차)를 지남 · 촉박 · 여유로 판정한다."""
    if moment < as_of:
        return EligibilityResult(
            rule_id=rule_id,
            label=label,
            status="FAIL",
            method="RULE",
            source=source,
            reason=f"{passed_reason} (기준시각 {as_of.astimezone(KST):%Y-%m-%d %H:%M} KST)",
        )
    remaining = moment - as_of
    hours = int(remaining.total_seconds() // 3600)
    # 0921 §4-B — 마감까지 회사가 적은 준비 일수보다 적게 남았으면 「촉박」이다.
    # 제안서를 쓸 시간이 없는 공고를 「가능」이라고 적으면 담당자의 시간을 버린다.
    #
    # **37차 D3(담당자 결정 2026-10-14) — 「불가」(숨김)가 아니라 「확인 필요 · 촉박」이다.** 촉박한지는 회사가 자료 · 파트너를
    # 이미 가졌는지에 달려 있어 분명한 불가가 아니다(실무 문서 §2.5 · §4.2 「7일 이하도 자료 · 파트너가 있으면 상위 가능」 ·
    # BidPilot 「불가는 분명할 때만」). 그래도 「가능」은 나오지 않는다. 3일 이하는 「원칙적으로 후순위」를 함께 적는다.
    lead_days = active_company().proposal_lead_days
    if lead_days > 0 and remaining.total_seconds() < lead_days * 86_400:
        left = remaining.days
        late = " 3일 이하라 원칙적으로 후순위입니다." if remaining.total_seconds() <= 3 * 86_400 else ""
        return EligibilityResult(
            rule_id=rule_id,
            label=label,
            status="CHECK",
            method="RULE",
            source=source,
            reason=(
                f"확인 필요 · 촉박 — 기한까지 {left}일 {hours % 24}시간 남았습니다. 회사가 적은 제안서 준비 일수"
                f"({lead_days}일)보다 짧아, 자료 · 파트너가 이미 준비돼 있을 때만 검토하세요.{late}"
            ),
            check_side="company",
        )
    return EligibilityResult(
        rule_id=rule_id,
        label=label,
        status="PASS",
        method="RULE",
        source=source,
        reason=(f"마감까지 {hours // 24}일 남았습니다." if hours >= 24 else f"마감까지 {hours}시간 남았습니다."),
    )


def _rule_qualification_deadline(raw: dict[str, Any], as_of: datetime) -> EligibilityResult:
    return _deadline_rule(
        rule_id="ELIG-QUALIFICATION-DEADLINE",
        label="참가자격 등록 마감",
        field_name="bidQlfctRgstDt",
        raw_value=_notice_field(raw, "bidQlfctRgstDt", "qualification_deadline"),
        as_of=as_of,
        passed_reason="입찰참가자격 등록 마감이 이미 지났습니다. 이 공고에는 신규로 참가할 수 없습니다.",
        missing_reason="참가자격 등록 마감일이 나라장터 기본정보에 없습니다. 공고문에서 확인하세요.",
    )


def _rule_bid_deadline(raw: dict[str, Any], as_of: datetime) -> EligibilityResult:
    return _deadline_rule(
        rule_id="ELIG-BID-DEADLINE",
        label="입찰서 제출 마감",
        field_name="bidClseDt",
        raw_value=_notice_field(raw, "bidClseDt"),
        as_of=as_of,
        passed_reason="입찰서 제출 마감이 이미 지났습니다.",
        missing_reason="입찰 마감일시가 나라장터 기본정보에 없습니다. 공고문에서 확인하세요.",
    )


#: 결정 4 — 「업종 없음 · 공동수급 허용 · 모름」 판정 줄의 사유 머리. 실무순 덩어리 · 꼬리표가 `industry_partner` 로 읽는다.
INDUSTRY_PARTNER_HEAD: Final = "업종 없음(필요: "


def industry_partner(results: Sequence[EligibilityResult], raw: dict[str, Any]) -> Literal["allowed", "unknown"] | None:
    """등록 업종이 없어 혼자는 못 하지만 공동수급으로 볼 수 있는 공고인가(44차 결정 4) — 「allowed」(허용) · 「unknown」(방식 모름) · None.
    실무순은 이 꼴을 크기 · 지역과 상관없이 대형 · 파트너형 덩어리에 세운다(`practical_priority.block_of`)."""
    for r in results:
        if r.rule_id == "ELIG-INDUSTRY" and r.status == "CHECK" and r.reason.startswith(INDUSTRY_PARTNER_HEAD):
            return "allowed" if joint_allowed(raw) else "unknown"
    return None


def joint_allowed(raw: dict[str, Any]) -> bool | None:
    """공동수급을 허용하는가. 값을 못 읽으면 None.

    판정(사업 규모 · 공동수급 조항) · 「주의」 한 줄 · 규모 점수가 **이 함수 하나**로 본다(33차 §3-B-2).
    예전에는 「주의」와 점수가 `"공동이행" in 방식` 낱말로 따로 봐서 「(수기)분담이행」에서 판정은
    「확인」, 「주의」는 「함께 입찰도 안 됨」이라고 말이 갈렸다. 분담이행도 공동수급의 한 방식이다(가이드 2-6).
    """
    text = _notice_field(raw, "cmmnSpldmdMethdNm", "joint_supply_method")
    if not text:
        return None
    if "불허" in text or "없음" in text and "공동" not in text.replace("(없음)", ""):
        return False
    if any(token in text for token in ("공동", "분담", "혼합", "주계약")):
        return True  # 혼합방식 = 공동이행 · 분담이행을 섞은 공동수급(33차 마지막 검토 · R26BK01725538)
    return None


def _rule_budget(raw: dict[str, Any]) -> EligibilityResult:
    """ELIG-BUDGET — 회사가 적은 상한과 대조한다 (0921 §4-B).

    상한은 **회사가 정할 값**이다. 예전에는 합성 프로필의 3억을 썼는데, 그것은 시스템이
    지어낸 숫자라 그 값으로 판정할 수 없었다(언제나 CHECK).

    **상한을 넘어도 「불가」는 내지 않는다**(33차 §3-B-1 · 담당자 결정 2026-10-08). 상한은 법이 막는
    참가 조건이 아니라 회사 기준이라, 공동수급이 불허여도 「확인 필요」(혼자 맡을지 회사가 정함)다.
    허용이면 「확인 필요 + 공동수급 파트너 확보 시」, 모르면 공고문에서 방식을 확인한다.
    허용인데 회사가 파트너를 「있음」으로 적었으면 열리는 조건 없이 나눠 맡을지만 정한다(34차 R33-S1 —
    갖춘 것을 「갖추면 가능」으로 다시 약속하지 않는다).
    점수는 규모 항목(`opportunity_priority.scale_component`)에서만 낮아진다.
    """
    budget_raw = _notice_field(raw, "asignBdgtAmt", "assigned_budget")
    price_raw = _notice_field(raw, "presmptPrce", "estimated_price")
    budget = g2b_mapper.parse_amount(budget_raw) or g2b_mapper.parse_amount(price_raw)
    source = f"나라장터 기본정보 — {_fields(('asignBdgtAmt', budget_raw), ('presmptPrce', price_raw))}"
    if budget is None:
        return EligibilityResult(
            rule_id="ELIG-BUDGET",
            label="사업 규모",
            status="CHECK",
            method="RULE",
            source=source,
            reason="예산 · 추정가격이 나라장터 기본정보에 없어 혼자 맡을 수 있는 규모인지 판단할 수 없습니다.",
        )

    ceiling = active_company().budget_ceiling_krw
    if ceiling is None:
        # 회사가 상한을 안 적었다. 합성 기준으로 «참고만» 하고 확정하지 않는다.
        # 참고값의 이름을 바로 적는다 (0922 §4-D-1). 「합성 기준 3억」은 시스템이 지어낸
        # 숫자로 읽혀 담당자가 그것을 회사 값으로 오해할 수 있었다.
        budget_text, assumed_text = won_pair(budget, RECOMMENDED_CEILING_KRW)  # 반올림하면 같아지는 금액은 정확히(35차 G2B-04)
        hint = (
            f" 혼자 맡을 수 있는 금액을 아직 안 적어 권장 상한 {assumed_text}으로 가정했고, 그 "
            + ("금액을 넘습니다" if budget > RECOMMENDED_CEILING_KRW else "안에 듭니다")
            + ". 회사 값을 적기 전까지는 확인 필요로 둡니다."
        )
        return EligibilityResult(
            rule_id="ELIG-BUDGET",
            label="사업 규모",
            status="CHECK",
            method="RULE",
            source=source,
            reason=f"사업비 {budget_text} —{hint}",
            unlock_condition="회사자료에 혼자 맡을 수 있는 최대 사업비를 적으면 판정할 수 있습니다",
            check_side="company",
        )

    budget_text, ceiling_text = won_pair(budget, ceiling)  # 반올림하면 같아지는 금액은 정확히(34차 R33-04)
    if budget <= ceiling:
        return EligibilityResult(
            rule_id="ELIG-BUDGET",
            label="사업 규모",
            status="PASS",
            method="RULE",
            source=source,
            reason=f"사업비 {budget_text} — 회사가 적은 최대 사업비 {ceiling_text} 안입니다.",
        )

    joint = joint_allowed(raw)
    method_text = _notice_field(raw, "cmmnSpldmdMethdNm", "joint_supply_method") or "(없음)"
    if joint and active_company().joint_bid_available:
        return EligibilityResult(
            rule_id="ELIG-BUDGET",
            label="사업 규모",
            status="CHECK",
            method="RULE",
            source=f"{source} · 공동수급 {method_text}",
            reason=(
                f"사업비 {budget_text} — 회사가 적은 최대 사업비 {ceiling_text}보다 큽니다. "
                "함께 참가할 회사를 확보해 두었습니다 — 나눠 맡을지 정하세요."
            ),
            check_side="company",
        )
    if joint:
        return EligibilityResult(
            rule_id="ELIG-BUDGET",
            label="사업 규모",
            status="CHECK",
            method="RULE",
            source=f"{source} · 공동수급 {method_text}",
            reason=(
                f"사업비 {budget_text} — 회사가 적은 최대 사업비 {ceiling_text}보다 큽니다. "
                "다른 회사와 함께 참가(공동수급)할 수 있어, 함께할 회사를 구하면 나눠 맡을 수 있습니다."
            ),
            # 열쇠 그대로 — `_judge_consortium` 과 갭 리포트가 같은 글로 센다
            unlock_condition="공동수급 파트너 확보 시",
            check_side="company",
        )
    if joint is False:
        # 불허여도 「불가」가 아니다 — 법이 막는 것이 아니라 회사 기준이다(33차 §3-B-1).
        return EligibilityResult(
            rule_id="ELIG-BUDGET",
            label="사업 규모",
            status="CHECK",
            method="RULE",
            source=f"{source} · 공동수급 {method_text}",
            reason=(
                f"사업비 {budget_text} — 회사가 정한 최대 사업비 {ceiling_text}보다 크고, "
                "다른 회사와 함께 참가할 수도 없습니다(공동수급 불허). "
                "법이 막는 것이 아니라 회사 기준입니다 — 혼자 맡을지 정하세요"
            ),
            check_side="company",
        )
    return EligibilityResult(
        rule_id="ELIG-BUDGET",
        label="사업 규모",
        status="CHECK",
        method="RULE",
        source=f"{source} · 공동수급 {method_text}",
        reason=(
            f"사업비 {budget_text} — 회사가 적은 최대 사업비 {ceiling_text}보다 큽니다. "
            "다른 회사와 함께 참가할 수 있는지 공고문에서 공동수급 방식을 확인하세요."
        ),
        check_side="notice",
    )


def _rule_cancelled(raw: dict[str, Any]) -> EligibilityResult | None:
    """ELIG-CANCELLED — 취소공고 (0921 §4-A-2 · §4-B).

    취소된 차수는 참가할 수 없다. 취소가 아니면 규칙 자체를 내지 않는다 — 모든 공고에
    「취소 아님」 한 줄을 붙이면 목록이 길어지기만 한다.
    """
    kind = _notice_field(raw, "ntceKindNm", "notice_kind")
    if "취소" not in kind:
        return None
    return EligibilityResult(
        rule_id="ELIG-CANCELLED",
        label="취소공고",
        status="FAIL",
        method="RULE",
        source=f"나라장터 기본정보 — {_fields(('ntceKindNm', kind))}",
        reason="취소된 공고입니다. 이 차수로는 참가할 수 없습니다. 같은 사업이 재공고됐는지 확인하세요.",
    )


#: 낙찰 방식(나라장터 칸 값 「협상에의한계약-협상에 의한 낙찰자 결정」) → 처음 입찰하는 사람이 읽는 말. 앞쪽 낱말로 가른다 —
#: 모르는 값은 원문 그대로(지어내지 않는다).
_AWARD_WORDS: Final[tuple[tuple[str, str], ...]] = (
    ("협상에의한계약", "제안서 평가로 뽑음"),
    ("규격가격동시입찰", "규격 심사를 통과한 회사 중 가격으로 뽑음"),
    ("적격심사", "적격심사(수행 능력 · 가격 함께 심사)로 뽑음"),
    ("제한적최저가", "낙찰 하한율 위 최저가로 뽑음"),
    ("최저가", "가장 낮은 가격으로 뽑음"),
    ("소액수의견적", "소액 수의계약(견적 비교)"),
    ("수의시담", "수의계약(가격 협의)"),
)


def _award_text(award: str, rate: str) -> str | None:
    """「제안서 평가로 뽑음(기술 80 : 가격 20)」. 칸이 비면 None."""
    if not award and not rate:
        return None
    text = next((plain for head, plain in _AWARD_WORDS if award.startswith(head)), award)
    if rate.isdigit() and int(rate) <= 100:
        weight = f"기술 {rate} : 가격 {100 - int(rate)}"
        return f"{text}({weight})" if text else weight
    return text or None


def _joint_text(joint: str) -> str:
    """공동수급 칸(「(없음)공동수급불허」 · 「(전자)공동이행」) → 「다른 회사와 함께 참가할 수 없음」."""
    if "불허" in joint:
        return "다른 회사와 함께 참가할 수 없음(공동수급 불허)"
    if "공동이행" in joint and "분담이행" in joint:
        return "다른 회사와 함께 참가할 수 있음(공동이행 또는 분담이행)"
    if "분담이행" in joint:
        return "다른 회사와 함께 참가할 수 있음(분담이행)"
    if "공동이행" in joint:
        return "다른 회사와 함께 참가할 수 있음(공동이행)"
    if "혼합" in joint or "주계약" in joint:
        # `joint_allowed` 가 허용으로 보는 두 방식 — 한 줄도 같은 말을 해야 브리핑 「파트너형」이 빠지지 않는다(37차 마지막 검토)
        name = re.sub(r"^\([^)]*\)\s*", "", joint) or joint  # 「(전자)혼합방식」 → 「혼합방식」
        return f"다른 회사와 함께 참가할 수 있음({name})"
    return f"공동수급 {joint}"


def _rule_award(raw: dict[str, Any]) -> EligibilityResult | None:
    """ELIG-AWARD — 계약·낙찰 방식 (0921 §4-B, **정보만**).

    판정이 아니라 「어떻게 뽑는가」를 한 줄로 알려 준다. 협상 90:10 과 최저가는 준비해야
    할 것이 다르다. 값이 하나도 없으면 규칙을 내지 않는다.
    """
    contract = _notice_field(raw, "cntrctCnclsMthdNm", "contract_method")
    award = _notice_field(raw, "sucsfbidMthdNm", "award_method")
    rate = _notice_field(raw, "techAbltEvlRt", "tech_ability_rate")
    joint = _notice_field(raw, "cmmnSpldmdMethdNm", "joint_supply_method")
    if not any((contract, award, rate, joint)):
        return None
    parts = [p for p in (contract, _award_text(award, rate)) if p]
    if joint:
        parts.append(_joint_text(joint))
    return EligibilityResult(
        rule_id="ELIG-AWARD",
        label="계약·낙찰 방식",
        status="PASS",
        method="RULE",
        source=f"나라장터 기본정보 — {_fields(('cntrctCnclsMthdNm', contract), ('sucsfbidMthdNm', award))}",
        reason=" · ".join(parts),
    )

def is_relocation(condition: str | None) -> bool:
    """「○○ 소재 시 가능」 — 본사를 옮기라는 말이라 「갖추면 가능」 · 할 일 · 빈칸 안내에 올리지 않는다(43차 N3). 판정 줄에는 남긴다."""
    return bool(condition) and "소재 시 가능" in condition


#: ELIG-REGISTRATION 의 「열리는 조건」 — 적으면 확정되는 값이 아니라 **직접 확인할 일**이다. 「이번 주 할 일」은 이 조건에
#: 「확정됩니다」를 붙이지 않는다(rule_id 로 가른다 · 31차 §3-B).
#: 등록 · 결격 줄을 닫는 회사 단위 확인 칸(43차 결정 2).
REGISTRATION_CHECK_KEYS: Final[tuple[str, ...]] = ("g2b_registration", "no_sanction", "no_tax_arrears")
REGISTRATION_UNLOCK: Final[str] = "나라장터 경쟁입찰참가자격등록증에서 등록 여부와 업종을 직접 확인하세요. 처음이라면 등록부터 해야 합니다."


def _rule_business_registration(registration_req: Requirement | None, today: date | None = None) -> EligibilityResult:
    """ELIG-REGISTRATION — 사업자등록·입찰참가 결격 (0922 §4-D-1 · ISSUE-086).

    **합성 회사를 근거로 실제 회사를 판정하지 않는다.** 예전에는 합성 프로필의
    `business_registration_done=True` 를 읽어 샘플에듀에도 PASS 를 냈다 — 실제 회사의 근거가
    아닌 값으로 PASS 를 내면 CLAUDE.md §11 위반이다.

    실제 회사로 판정 중이면(`from_real_company`) 「확인 필요」이고, 무엇을 적으면 확정되는지
    열리는 조건에 적는다. 합성 데모에서는 예전처럼 합성 가정을 쓰되 **그렇다고 말한다.**
    """
    company = active_company()
    requirement_id = registration_req.requirement_id if registration_req is not None else None
    quote = f"{_quote_requirement(registration_req)} / " if registration_req is not None else ""

    if company.from_real_company and company.company_checks:
        # 43차 결정 2 — 회사 단위 한 번 확인(등록 · 부정당 제재 없음 · 체납 없음 · 유효기간)
        state, detail = company_check_state(company, REGISTRATION_CHECK_KEYS, today or storage.kst_today())
        if state == "valid":
            return EligibilityResult(
                rule_id="ELIG-REGISTRATION", label="입찰 참가 제한(결격)", status="PASS", method="HUMAN",
                source=f"{quote}회사 단위 확인 {detail}(회사자료 › 입찰 자격 자료)",
                reason=f"통과(회사 확인 {detail}) — 나라장터 등록 · 부정당 제재 없음 · 체납 없음을 회사 단위로 확인했습니다.",
                requirement_id=requirement_id,
            )
        return EligibilityResult(
            rule_id="ELIG-REGISTRATION", label="입찰 참가 제한(결격)", status="CHECK", method="RULE",
            source=f"{quote}회사 단위 확인(회사자료 › 입찰 자격 자료)",
            reason=(f"다시 확인 — {detail}. 회사자료 › 입찰 자격 자료에서 다시 확인하세요." if state == "expired"
                    else f"회사 단위 확인 중 {detail} 칸이 비어 있습니다. 회사자료 › 입찰 자격 자료에서 확인하세요."),
            unlock_condition=REGISTRATION_UNLOCK, requirement_id=requirement_id, check_side="company",
        )
    if company.from_real_company:
        return EligibilityResult(
            rule_id="ELIG-REGISTRATION",
            label="입찰 참가 제한(결격)",
            status="CHECK",
            method="RULE",
            source=f"{quote}나라장터 입찰참가자격 등록 (회사자료로 판정하지 않음)",
            reason=(
                "나라장터 입찰참가자격 등록 여부는 회사자료로 판정하지 않습니다. 등록은 모든 전자입찰의 전제라 "
                "등록증에서 직접 확인하세요."
            ),
            # 엔진은 사업자등록번호를 읽지 않는다 — 「적으면 판정」은 막다른 길이었다(31차 §3-B · 제품 반영 안 1-4).
            unlock_condition=REGISTRATION_UNLOCK,
            requirement_id=requirement_id,
            # 회사가 등록증으로 볼 일 — 「공고문에서 볼 것」 묶음에 섞이지 않게(34차 R33-03)
            check_side="company",
        )

    status: EligibilityStatus = "PASS" if COMPANY_PROFILE.business_registration_done else "CHECK"
    return EligibilityResult(
        rule_id="ELIG-REGISTRATION",
        label="입찰 참가 제한(결격)",
        status=status,
        method="RULE",
        source=f"{quote}가상 예시 회사 프로필: 사업자등록 {'완료' if COMPANY_PROFILE.business_registration_done else '확인 안 됨'}",
        reason=(
            "가상 예시 회사 프로필상 사업자등록이 완료되어 있고 입찰참가 제한 이력이 없습니다."
            if status == "PASS"
            else "사업자등록 상태를 확인할 수 없어 직접 확인하세요."
        ),
        requirement_id=requirement_id,
        check_side="company" if status == "CHECK" else None,
    )


# ---------------------------------------------------------------------------
# 2) 파싱된 RFP 요구사항 기반 규칙 (입찰참가자격 항목)
# ---------------------------------------------------------------------------


def _is_qualification_requirement(req: Requirement) -> bool:
    return "자격" in req.category or "입찰참가자격" in req.content


def _doc_check_hits(content: str) -> list[str]:
    # '사업자등록'의 '등록'은 문서 확인이 필요한 자격(입찰참가자격 등록 등)과 다르므로 제외한다.
    text = content.replace("사업자등록", "")
    return [kw for kw in DOC_CHECK_KEYWORDS if kw in text]


def _is_registration_only(req: Requirement) -> bool:
    """'사업자등록 완료' 류의 요구사항인지 (문서 확인이 필요한 키워드가 없어야 한다)."""
    return "사업자등록" in req.content and not _doc_check_hits(req.content)


def _consortium_result(req: Requirement) -> EligibilityResult:
    """공동수급 관련 요구사항. 단독 수행이 명시적으로 가능한 경우에만 PASS."""
    solo_ok = any(kw in req.content for kw in _SOLO_ALLOWED_KEYWORDS)
    if solo_ok and COMPANY_PROFILE.can_perform_alone:
        return EligibilityResult(
            rule_id=f"ELIG-{req.requirement_id}",
            label=_shorten(req.title or "공동수급 조건", _LABEL_LIMIT),
            status="PASS",
            method="RULE",
            source=_quote_requirement(req),
            reason="공동수급 없이 단독 수행하는 방침(가상 예시 프로필)이므로 이 조건과 충돌하지 않습니다.",
            requirement_id=req.requirement_id,
        )
    return EligibilityResult(
        rule_id=f"ELIG-{req.requirement_id}",
        label=_shorten(req.title or "공동수급 조건", _LABEL_LIMIT),
        status="CHECK",
        method="RULE",
        source=_quote_requirement(req),
        reason="공동수급 구성 조건이 있습니다. 단독 참여 가능 여부와 대표자·출자비율 요건을 직접 확인하세요.",
        requirement_id=req.requirement_id,
    )


def _requirement_result(req: Requirement) -> EligibilityResult:
    if any(kw in req.content for kw in _CONSORTIUM_KEYWORDS):
        return _consortium_result(req)

    hits = _doc_check_hits(req.content)
    if hits:
        reason = (
            f"'{'/'.join(hits)}' 관련 자격 요건입니다. 회사의 수행실적·인력 자격 증빙과 "
            "견줘야 알 수 있습니다 — 직접 확인하세요."
        )
    else:
        reason = "나라장터 기본정보만으로는 충족 여부를 판단할 수 없는 자격 조건입니다. 원문을 읽고 직접 확인하세요."
    return EligibilityResult(
        rule_id=f"ELIG-{req.requirement_id}",
        label=_shorten(req.title or "참가자격 조건", _LABEL_LIMIT),
        status="CHECK",
        method="RULE",
        source=_quote_requirement(req),
        reason=reason,
        requirement_id=req.requirement_id,
    )


# ---------------------------------------------------------------------------
# 3) 선택적 LLM 보강 — CHECK 라우팅과 이유 문장만 개선한다 (PASS 생성 금지)
# ---------------------------------------------------------------------------


class _LlmQualificationItem(BaseModel):
    requirement_id: str
    classification: Literal["clearly_satisfiable_by_rule", "needs_document_check"]
    reason: str


class _LlmQualificationBatch(BaseModel):
    items: list[_LlmQualificationItem]


_LLM_SYSTEM = (
    "당신은 한국 공공조달 입찰 참가자격 검토 보조자다. "
    "각 요구사항이 공고 필드/규칙만으로 확인 가능한지(clearly_satisfiable_by_rule), "  # 화면 문장 아님(모델 지시문)
    "아니면 회사 증빙 문서를 읽어야 확인 가능한지(needs_document_check) 분류하고 "  # 화면 문장 아님(모델 지시문)
    "한국어 한 문장으로 이유를 쓴다. "
    "충족 여부를 단정하지 말고, 원문에 없는 사실을 지어내지 마라."
)


def _llm_reasons(requirements: list[Requirement]) -> dict[str, _LlmQualificationItem]:
    """LLM 분류 결과. 실패하면 빈 dict를 돌려주고 호출자는 규칙 결과를 그대로 쓴다."""
    if not requirements or not llm_client.completion_configured():
        return {}
    lines = [
        f"- {req.requirement_id} (p.{req.page}): {_shorten(req.content, 300)}"
        for req in requirements[:MAX_LLM_ITEMS]
    ]
    user = "다음 입찰참가자격 요구사항을 분류하라.\n" + "\n".join(lines)
    try:
        batch = llm_client.complete_structured(
            system=_LLM_SYSTEM,
            user=user,
            schema=_LlmQualificationBatch,
            temperature=0.0,
        )
    except (llm_client.LLMUnavailableError, llm_client.LLMValidationError) as exc:
        logger.info("참가자격 LLM 보강 생략 (규칙 결과 유지): %s", exc)
        return {}
    return {item.requirement_id: item for item in batch.items}


def _apply_llm(results: list[EligibilityResult], reasons: dict[str, _LlmQualificationItem]) -> bool:
    """LLM 이유를 CHECK 항목에만 덧붙인다. 상태를 PASS로 바꾸지 않는다."""
    used = False
    for result in results:
        item = reasons.get(result.requirement_id or "")
        if item is None or result.status != "CHECK":
            continue
        note = _shorten(item.reason, 200)
        if item.classification == "clearly_satisfiable_by_rule":
            result.reason = f"{result.reason} (AI 판단: 규칙으로 확인 가능해 보이나 확정은 사람이 합니다 — {note})"
        else:
            result.reason = f"{result.reason} (AI 판단: 문서 확인 필요 — {note})"
        result.method = "AI_EXTRACTION"
        used = True
    return used


# ---------------------------------------------------------------------------
# 3-b) 참가자격 조항 (QUAL-*) — 공고문에서 가져온 조항을 회사 사실과 **따로** 견준다 (19차 §4-B)
# ---------------------------------------------------------------------------
#
# 담당자 지시(2026-09-23): 「자격요건은 확실하게 가져와서 판단해야 해. 따로 판단하도록 해줘.」
#
# 공고 필드 검사(ELIG-*)와 **다른 묶음**이다. 조항 원문은 `qualification_clause_service` 가
# 공고문에서 뽑아 파일로 둔다. 여기서는 그 파일(과 제안요청서의 같은 조항·파싱된 RFP 의 자격
# 요구사항)을 **조항마다 한 줄**로 판정한다(20차 §4-B · ISSUE-138 — 담당자가 하나씩 확인한다).
# 같은 조항이 두 출처에 있으면 한 줄이다(`_clauses_of`). 줄 이름은 `QUAL-<종류>-<조항 id>`.
# 조항 줄은 공고 필드 줄(`ELIG-*`)에 합치지 않는다 — 합치면 한 줄에 조항이 둘 이상 들어가 하나씩 확인할 수 없다.
#
# **양면 근거가 있을 때만 가능·불가다** (CLAUDE.md §11). 조항 원문과 회사 사실이 둘 다 있어야
# 확정하고, 한쪽이 없으면 확인 필요다 — 빈 `CompanyFacts` 로는 가능이 하나도 나오지 않는다.

QUAL_KIND_ORDER: Final[tuple[str, ...]] = (
    "industry", "region", "company_type", "track_record", "staff", "consortium", "disqualification", "other",
)
QUAL_LABELS: Final[dict[str, str]] = {
    "industry": "업종 조항",
    "region": "지역 조항",
    "company_type": "기업 유형 조항",
    "track_record": "실적 조항",
    "staff": "인력 조항",
    "consortium": "공동수급 조항",
    "disqualification": "결격·등록 조항",
    "other": "기타 조항",
}
_QUAL_RULE_KEY: Final[dict[str, str]] = {
    "industry": "INDUSTRY",
    "region": "REGION",
    "company_type": "TYPE",
    "track_record": "TRACK",
    "staff": "STAFF",
    "consortium": "CONSORTIUM",
    "disqualification": "DISQUAL",
    "other": "OTHER",
}

#: 조항 속 지역 이름 → 회사 소재와 같은 이름. 긴 이름부터 본다.
_REGION_CANON: Final[tuple[tuple[str, str], ...]] = (
    ("전남광주통합특별시", "전남광주"), ("광주광역시", "전남광주"), ("전라남도", "전남광주"),
    ("서울특별시", "서울"), ("부산광역시", "부산"), ("대구광역시", "대구"), ("인천광역시", "인천"),
    ("대전광역시", "대전"), ("울산광역시", "울산"), ("세종특별자치시", "세종"), ("경기도", "경기"),
    ("강원특별자치도", "강원"), ("강원도", "강원"), ("충청북도", "충북"), ("충청남도", "충남"),
    ("전북특별자치도", "전북"), ("전라북도", "전북"), ("경상북도", "경북"), ("경상남도", "경남"),
    ("제주특별자치도", "제주"),
    ("광주", "전남광주"), ("전남", "전남광주"), ("서울", "서울"), ("부산", "부산"), ("대구", "대구"),
    ("인천", "인천"), ("대전", "대전"), ("울산", "울산"), ("세종", "세종"), ("경기", "경기"),
    ("강원", "강원"), ("충북", "충북"), ("충남", "충남"), ("전북", "전북"), ("경북", "경북"),
    ("경남", "경남"), ("제주", "제주"),
)

#: 기업 유형 — (화면 이름, 조항에서 찾는 꼴, 열리는 조건)
_COMPANY_TYPES: Final[tuple[tuple[str, str, str], ...]] = (
    ("중소기업", r"중소기업|중[·ㆍ]\s*소기업", "중소기업·소상공인확인서(공공기관 입찰용) 발급 시"),
    ("소기업", r"(?<![중·ㆍ])소기업", "중소기업·소상공인확인서(공공기관 입찰용) 발급 시"),
    ("소상공인", r"소상공인", "중소기업·소상공인확인서(공공기관 입찰용) 발급 시"),
    ("사회적기업", r"사회적\s*기업", "사회적기업 인증 시"),
    ("여성기업", r"여성\s*기업", "여성기업 확인 시"),
    ("장애인기업", r"장애인\s*기업", "장애인기업 확인 시"),
    ("벤처기업", r"(?<!중소)벤처\s*기업", "벤처기업 확인 시"),  # 「중소벤처기업부」는 기관 이름
    ("협동조합", r"협동\s*조합", "협동조합 설립 시"),
)
_FOUNDED_WITHIN = re.compile(r"창업\s*(\d{1,2})\s*년")
#: 실측: 「공동계약이 허용되지 않습니다」(1722092)·「공동 수급(컨소시엄)은 허용하 지 않음」(가천대 AI부트캠프,
#: PDF 줄바꿈이 「하 지」로 갈랐다)을 「허용」으로 읽어 공고 필드와 거짓으로 어긋났다.
_CONSORTIUM_FORBID = re.compile(r"허용\s*[하되]\s*지\s*않|불허|불가|허용\s*안|단독")
#: 「공동수급체**를** 구성하여야」는 필수, 「공동수급체**는** 나라장터를 이용하여서만 구성하여야」는 방법 안내다.
#: 실측 3건(1725512·1732306·1734751)이 방법 안내를 「필수」로 읽어 「파트너 확보 여부」를 물었다 —
#: 회사가 「파트너 없음」을 적으면 근거 없는 불가가 된다.
_CONSORTIUM_REQUIRED = re.compile(r"(?:를|을)\s*(?:반드시\s*)?구성\s*(?:하여야|해야)|필수|의무")
_CONSORTIUM_ALLOW = re.compile(r"허용|가능|공동\s*이행|분담\s*이행")
#: 실적 조항이 요구하는 **일의 종류**. 「구축·개발 실적」과 「교육 실적」은 다른 실적이다 —
#: 실측: 한양사이버대 「… 소프트웨어 개발 분야 유사 구축 실적」에 AI 교육 과정 26건이 맞았다
#: (요약에 「플랫폼」「개발」이 들어 있어 분야 낱말만으로는 걸러지지 않았다). 행의 종류는 **제목**으로 본다.
#: 「영상 콘텐츠(K-MOOC 강좌 개발 우대) 개발 관련 용역」 — 콘텐츠를 만드는 일(43차 H3 · 1780566 에 3D 프린터 교육 실적이 맞았다).
_CONTENT_CLAUSE = re.compile(r"(?:영상|콘텐츠|컨텐츠|K-?MOOC|이러닝|e-?러닝|강좌|동영상)[^.]{0,30}?(?:개발|제작)")
_CONTENT_TITLE = re.compile(r"(?:영상|콘텐츠|컨텐츠|MOOC|이러닝|e-?러닝|강좌|동영상)[^.]{0,20}?(?:개발|제작)|(?:개발|제작)[^.]{0,10}?(?:영상|콘텐츠|컨텐츠|강좌)")
#: 「유사용역 수행실적에 따른 입찰참가자격 제한은 두지 않습니다」 — 실적 요건이 아니다(43차 H3 · 1784853).
_NO_TRACK_LIMIT = re.compile(r"(?:실적|자격)[^.]{0,30}?제한\s*(?:은|을|이)?\s*(?:두지\s*않|없|하지\s*않)")
_BUILD_CLAUSE = re.compile(r"(?:구축|개발|구현|납품)\s*(?:한\s*)?(?:실적|경험|이력|분야)|시스템\s*(?:구축|개발)")
_EDU_CLAUSE = re.compile(r"교육|강의|과정\s*(?:을\s*)?운영|훈련|연수|아카데미|캠프|부트캠프")
_BUILD_TITLE = re.compile(r"구축|개발|시스템|플랫폼|솔루션|구현|고도화|\b앱\b")
#: 컨설팅 실적 조항 — 교육 제목 행은 세지 않는다(1736492 「AI거버넌스 수립 및 컨설팅 사업 수행 실적」에 교육 2건이 맞았다 · 35차 G2B-02).
_CONSULT_CLAUSE = re.compile(r"컨설팅|자문|진단")
#: 「…이거나 누적 수료 인원 100명 이상」처럼 실적 목록으로 볼 수 없는 갈래(35차 G2B-01 · 1751800 · 1699556).
_UNSEEN_BRANCH = re.compile(r"(?:이거나|또는|혹은)[^.]{0,40}?(?:인원|수료|명\s*이상|인\s*이상|만족도)")
#: 「금융기관을 대상으로」 — 발주처 유형. 실적 목록의 발주기관 분류로 못 읽으면 확정하지 않는다(1736492 · 35차 G2B-02).
_TARGET_CLIENT = re.compile(r"([가-힣A-Za-z]{2,12}(?:\s*등\s*[가-힣A-Za-z]{2,10})?)\s*(?:을|를)\s*대상으로")
_EDU_TITLE = re.compile(r"교육|과정|강의|양성|캠프|훈련|아카데미|특강|워크숍|연수|클래스|세미나|만들기|실습|체험")
#: 「추정가격의 70% 이상 규모」처럼 금액이 **사업비 비율**로 적힌 실적 조항 — 원장 금액으로 확정할 수 없다.
_RELATIVE_AMOUNT = re.compile(r"(?:추정\s*가격|기초\s*금액|예정\s*가격|사업비|계약\s*금액)[^.]{0,24}?\d+\s*%")


@dataclass(frozen=True)
class _Clause:
    """판정에 쓰는 조항 하나 — 공고문·제안요청서·RFP 요구사항 어디서 왔든 같은 모양."""

    id: str
    text: str
    page: int | None
    origin: str  # 「입찰공고문」·「제안요청서」·「RFP」
    approx: bool
    kind: str
    requirement_id: str | None = None


def _clause_quote(clause: _Clause) -> str:
    page = f" {clause.page}쪽" if clause.page else ""  # 「p.4」 대신 「4쪽」(31차 §3-D)
    approx = "(근사)" if clause.approx and clause.page else ""
    return f'{clause.origin}{page}{approx} "{_shorten(clause.text, _QUOTE_LIMIT)}"'


def _qual(
    kind: str,
    clause: _Clause,
    status: EligibilityStatus,
    reason: str,
    *,
    side: str | None = None,
    unlock: list[str] | None = None,
) -> EligibilityResult:
    """조항 하나의 판정 줄. 원문·쪽·출처 문서·종류를 줄에 싣는다 — 화면 체크리스트가 이것으로 그린다."""
    options = list(dict.fromkeys(unlock or []))
    return EligibilityResult(
        rule_id=f"QUAL-{_QUAL_RULE_KEY[kind]}-{clause.id}",
        label=QUAL_LABELS[kind],
        status=status,
        method="RULE",
        source=_clause_quote(clause),
        reason=reason,
        # RFP 요구사항에서 온 조항이면 그 번호를 남긴다 — LLM 보강(`_apply_llm`)이 이 번호로 찾는다.
        requirement_id=clause.requirement_id,
        unlock_condition=(options[0] if len(options) == 1 else (" 또는 ".join(options[:2]) if options else None)),
        unlock_options=options,
        clause_id=clause.id,
        clause_text=clause.text,
        page=clause.page,
        source_document=clause.origin,
        kind=kind,
        check_side=side if status == "CHECK" else None,
    )


#: 도 이름 바로 뒤의 시 · 군 — 「경기도 광주시」 · 「강원도 고성군」은 그 도다(34차 R33-D1). 짧은 별칭(「광주」 · 「고성」)을
#: 따로 맞추면 경기 시 · 군 55곳 전용 공고(1761269)가 광주 회사에게 「가능」이 됐다.
_PROVINCE_CITY_RE: Final = re.compile(
    r"(경기도|강원특별자치도|강원도|충청북도|충청남도|전북특별자치도|전라북도|전라남도|경상북도|경상남도|제주특별자치도"
    # 줄임 도 이름 — 「경기 광주시」는 경기다(35차 G2B-05)
    r"|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
    r"\s*[가-힣]{1,5}(?:시|군)(?:\s*[가-힣]{1,5}구)?"
)


def _region_names(text: str) -> list[str]:
    found: list[str] = []
    rest = text
    for match in _PROVINCE_CITY_RE.finditer(text):
        canon = next(c for token, c in _REGION_CANON if token == match.group(1))
        if canon not in found:
            found.append(canon)
        rest = rest.replace(match.group(0), " ")
    for token, canon in _REGION_CANON:
        if token in rest:
            if canon not in found:
                found.append(canon)
            rest = rest.replace(token, " ")
    return found


def _company_region(company: CompanyFacts) -> str | None:
    if not company.location_region:
        return None
    names = _region_names(company.location_region)
    return names[0] if names else company.location_region


#: 업종 사이의 「와 · 과 · 및」 — 「(1468)과 정보통신공사업(0036)」은 둘 다 등록해야 한다(42차 BACK-R41-03).
_INDUSTRY_CONJ_RE: Final = re.compile(r"[)\]’']\s*(?:와|과|및)\s")
_INDUSTRY_ALL_RE: Final = re.compile(r"모두|및")
#: 「중 1개 이상」이면 하나만 맞아도 된다(어디에 있든 업종 목록을 두고 하는 말).
_INDUSTRY_ONE_OF_RE: Final = re.compile(r"중\s*(?:1\s*개|한\s*개|하나|어느)|하나\s*이상")


def _needs_all_industries(text: str, keys: Sequence[str]) -> bool:
    """업종 조항이 적힌 업종을 **모두** 요구하는가.

    「아래의 사항을 모두 등록한 자 [1169] 또는 [9999]」의 「모두」는 머리말이라 업종 **사이**의 「또는」이 이긴다. 「또는」은 첫 업종 ~ 마지막
    업종 사이에서만 본다 — 「단독 또는 공동수급으로 … A 및 B 를 모두 등록」의 「또는」에 속지 않게(42차 마지막 검토). 업종 사이에
    「와 · 과 · 및」이 있으면 섞인 꼴이라도 모두를 본다(하나만 맞으면 확인 필요 — 안전한 쪽).
    """
    if _INDUSTRY_CONJ_RE.search(text):
        return True
    found = [(text.find(k), len(k)) for k in keys if text.find(k) >= 0]
    between = text[min(i for i, _ in found):max(i + n for i, n in found)] if len(found) >= 2 else text
    one_of = "또는" in between or _INDUSTRY_ONE_OF_RE.search(text)
    return bool(_INDUSTRY_ALL_RE.search(text)) and not one_of


#: 「대기업 및 중견기업인 소프트웨어사업자의 입찰 참여를 제한함」 — 업종 요구가 아니라 **기업 규모 제한**(43차 N7 · 환경법정교육 9번).
_SIZE_LIMIT_RE = re.compile(r"(?:대기업|중견\s*기업)[^.]{0,40}?(?:참여|참가|입찰)[^.]{0,10}?제한")
#: 사업자등록증(세무서) 업태 · 종목 조항 — 나라장터 등록 업종이 아니다(`delivery_capacity.RegisteredIndustry` 주석). 나라장터 낱말이 함께면 그쪽 조항.
# 「사업자등록증을 교부받은 업체로서 … 훈련기관으로 등록된 업체」(1796954)는 등록 요건이다 — 업태 · 종목을 말할 때만(10-31 독립 검토)
_BIZ_REG_ITEM_RE = re.compile(r"업태|종목")
_G2B_REG_RE = re.compile(r"나라장터|입찰\s*참가\s*자격|전자\s*조달|조달\s*시스템")


def _judge_industry(clause: _Clause, raw: dict[str, Any], company: CompanyFacts) -> EligibilityResult:
    from app.services import qualification_clause_service as _qc

    if _SIZE_LIMIT_RE.search(clause.text) and not re.search(r"등록\s*(?:한|된|하고)", clause.text):
        sme = sme_state(company, storage.kst_today())
        if sme == "valid":
            return _qual("industry", clause, "PASS", "대기업 · 중견기업 참여 제한 조항입니다 — 회사는 중소기업(확인서 유효)이라 해당 없습니다.")
        return _qual(
            "industry", clause, "CHECK",
            "대기업 · 중견기업 참여 제한 조항입니다(업종 요구가 아님) — 중소기업이면 해당 없습니다. 중소기업(소상공인) 확인서로 확인하세요.",
            side="company",
        )
    codes = _qc.industry_codes(clause.text)
    names = _qc.industry_names(clause.text)
    if not codes and _BIZ_REG_ITEM_RE.search(clause.text) and not _G2B_REG_RE.search(clause.text):
        # 10-31 최종 점검 E — 사업자등록증 종목 조항을 나라장터 등록 업종(1169 = 학술 · 연구용역)과 견줘 「없습니다 · 학술연구용역 등록 시 가능」이 나왔다
        return _qual(
            "industry", clause, "CHECK",
            "사업자등록증의 업태 · 종목을 묻는 조항입니다 — 나라장터 등록 업종과는 다른 것이라 맞춰 보지 않았습니다."
            " 사업자등록증 종목에서 확인하세요.",
            side="company",
        )
    rows = {str(r.get("code") or "").strip(): r for r in (_license_limits(raw) or []) if r.get("code")}
    wanted = [industry_label(rows[c]) if c in rows else f"업종코드 {c}" for c in codes] or names
    unlock = [f"{w} 등록 시 가능" for w in wanted]
    # 공고 면허표(`ELIG-INDUSTRY`, 공고 필드 검사)와 같은 업종이면 그 사실을 적는다 — 두 줄을 합치지는 않는다.
    same = "공고 면허표와 같은 업종입니다. " if set(codes) & set(rows) else ""
    registered = set(company.registered_industry_codes)
    keys = codes or names
    hits = [c for c in codes if c in registered] if codes else [
        n for n in names if any(n.replace(" ", "") in r.replace(" ", "") for r in company.registered_industry_names)
    ]
    if hits and (len(hits) == len(keys) or not _needs_all_industries(clause.text, keys)):
        return _qual("industry", clause, "PASS", f"{same}회사 등록 업종({', '.join(hits)})이 조항이 요구하는 업종과 맞습니다.")
    if hits:
        missing = [w for k, w in zip(keys, wanted) if k not in hits]
        return _qual(
            "industry", clause, "CHECK",
            f"{same}조항은 {' · '.join(wanted)}을(를) 모두 등록해야 합니다. 회사 등록 업종에는 {', '.join(hits)}만"
            f" 있습니다 — {' · '.join(missing)}도 등록했는지 확인하세요.",
            side="company", unlock=[f"{w} 등록 시 가능" for w in missing],
        )
    if not registered and not company.registered_industry_names:
        reason = (
            f"{same}조항은 {' · '.join(wanted) or '특정 업종'} 등록을 요구합니다. 회사 등록 업종이 아직 비어 있어"
            " 정하지 못했습니다(비어 있다고 「없다」는 뜻은 아닙니다 — 회사자료에 등록 업종을 적으면 판정합니다)."
        )
    else:
        have = ", ".join(company.registered_industry_codes or company.registered_industry_names)
        reason = (
            f"{same}회사 등록 업종({have})에 조항의 업종({' · '.join(wanted)})이 없습니다. 원문에 대체 업종이"
            " 적혀 있는지 직접 확인하세요."
        )
    return _qual("industry", clause, "CHECK", reason, side="company", unlock=unlock)


def _judge_region(clause: _Clause, company: CompanyFacts) -> EligibilityResult:
    """지역 이름이 적혔을 때만 가능·불가. 「전국」은 **가능이 아니라 원문 확인**이다.

    「전국 대상이니 가능」은 회사 사실 없이 나온 가능이다 — 기업마당 쪽이 이미 막은 함정이다
    (「전국 대상으로 본다」만으로 가능 0건). 19차는 이 조항을 지역 줄에 붙였지만, 20차부터 조항은
    하나씩 확인하므로 제 줄을 갖는다(원문 확인).
    """
    names = _region_names(clause.text)
    if "전국" in clause.text and not names:
        return _qual(
            "region", clause, "CHECK",
            "「전국」 대상 조항입니다 — 지역을 제한하지 않는 것으로 보입니다. 원문을 직접 확인하세요.",
            side="notice",
        )
    if not names:
        why = "「관내 업체」 조항입니다 — 발주기관 관할이 어디인지 원문을 보고 직접 확인하세요." if "관내" in clause.text \
            else "지역 조항이지만 지역 이름을 읽지 못했습니다. 원문을 직접 확인하세요."
        return _qual("region", clause, "CHECK", why, side="notice")
    mine = _company_region(company)
    if mine is None:
        return _qual(
            "region", clause, "CHECK",
            f"조항은 {' · '.join(names)} 소재를 요구합니다. 회사 소재 광역이 비어 있어 확정하지 못합니다.",
            side="company", unlock=["회사자료에 소재 광역을 적으면 판정할 수 있습니다"],
        )
    if mine in names and mine == "전남광주" and _home_units(clause.text):
        # 「전남광주통합특별시 ○○시 · 군」 · 「광주광역시 북구」 — 회사 주소의 시 · 군 · 구와 견준다(43차 H2 · 필드 경로와 같은 함수)
        units = _home_units(clause.text)
        rest = _HOME_UNIT_RE.sub(" ", _PROVINCE_CITY_RE.sub(" ", clause.text))
        if mine not in _region_names(rest):
            verdict = _home_scope_verdict([f"전남 {u}" for u in units], company)
            listed = ", ".join(units[:4]) + (f" 외 {len(units) - 4}곳" if len(units) > 4 else "")
            if verdict is True:
                return _qual("region", clause, "PASS", f"조항은 {listed}(시 · 군 · 구 단위) 소재를 요구하고, 회사 주소는 {company.location_district}입니다.")
            # 「전남광주통합특별시 목포시 · 여수시 …」의 둘째부터는 도 이름이 없다 — 남은 시 · 군 · 구가 있으면 단정하지 않는다
            if verdict is False and not re.search(r"(?<![가-힣])[가-힣]{1,4}(?:시|군|구)(?![가-힣])", rest):
                return _qual("region", clause, "FAIL", f"조항은 {listed}(시 · 군 · 구 단위) 소재를 요구하는데 회사 주소는 {company.location_district}입니다.")
            if verdict is False:
                verdict = None
            return _qual(
                "region", clause, "CHECK",
                f"조항은 {listed}(시 · 군 · 구 단위) 소재를 요구합니다 — 회사 주소의 시 · 군 · 구가 거기에 드는지 확인하세요.",
                side="company",
            )
    if mine in names:
        rest = _PROVINCE_CITY_RE.sub(" ", clause.text)
        cities = [m.group(0) for m in _PROVINCE_CITY_RE.finditer(clause.text)
                  if next(c for token, c in _REGION_CANON if token == m.group(1)) == mine]
        if cities and mine not in _region_names(rest):
            # 우리 도 안의 **시 · 군**만 열린 조항 — 필드 경로와 같은 규칙(35차 G2B-05 · 「전라남도 나주시」)
            return _qual(
                "region", clause, "CHECK",
                f"조항은 {', '.join(cities)}(시 · 군 단위) 소재를 요구합니다 — 회사 주소의 시 · 군이 거기에 드는지 확인하세요.",
                side="company",
            )
        return _qual("region", clause, "PASS", f"조항은 {' · '.join(names)} 소재를 요구하고, 회사 소재는 {mine}입니다.")
    return _qual(
        "region", clause, "FAIL",
        f"조항은 {' · '.join(names)} 소재를 요구하는데 회사 소재는 {mine}입니다.",
        unlock=[f"{names[0]} 소재 시 가능"],
    )


def _judge_company_type(clause: _Clause, company: CompanyFacts, today: date) -> EligibilityResult:
    if re.search(r"직접\s*생산", clause.text):
        return _judge_direct_production(clause, company)  # 43차 M21 — 품명 대조(「기업 유형」 이름에 묻히지 않게)
    certs = [c.replace(" ", "") for c in company.certifications]
    within = _FOUNDED_WITHIN.search(clause.text)
    if within and company.founded_year:
        limit, years = int(within.group(1)), today.year - company.founded_year
        status: EligibilityStatus = "PASS" if years < limit else ("FAIL" if years > limit else "CHECK")
        edge = founding_edge(company, limit, today) if status == "CHECK" else None
        if edge is not None:
            return _qual("company_type", clause, edge[0], f"창업 {limit}년 이내 — {edge[1]}.", side="company")
        return _qual(
            "company_type", clause, status, f"창업 {limit}년 이내 — {company.founded_year}년 설립(설립 뒤 {years}년).",
            side="company",
        )
    types = [(name, fix) for name, pattern, fix in _COMPANY_TYPES if re.search(pattern, clause.text)]
    if not types:
        return _qual("company_type", clause, "CHECK", "기업 유형 조항의 요건을 규칙으로 가르지 못했습니다.", side="company")
    held = [name for name, _fix in types if any(name in cert for cert in certs)]
    if held:
        return _qual("company_type", clause, "PASS", f"{', '.join(held)} — 회사 인증에 있음.")
    kind = _sme_kind(clause.text)
    if kind in ("direct", "other"):
        return _judge_sme_other(clause, kind, company)
    if kind is not None:
        judged = _judge_sme_clause(clause, company, today, kind, [fix for _name, fix in types])
        if judged is not None:
            return judged
    return _qual(
        "company_type", clause, "CHECK",
        f"{'·'.join(name for name, _f in types)} — 회사 인증에 없습니다(확인서를 아직 안 적음).",
        side="company", unlock=[fix for _name, fix in types],
    )


#: 법 · 기관 · 서류 · 제도 이름 안의 「중소기업」 — 규모 요건이 아니다(「중소기업제품 구매촉진 …」 법 이름 때문에 직접생산 조항이 기업 유형으로
#: 들어온다 · 「중소기업(소상공인)확인서」는 서류 이름 · 「중소기업협동조합」 · 공공구매 정보망 · 간주 특별법인 · 우선조달 조문 제목 · 10-10 검토).
_SME_NAMES_RE = re.compile(
    r"[「｢『\"']?중소\s*기업[가-힣\s·ㆍ]{0,24}?(?:기본법|촉진법|지원법|진흥법|협동조합법|에\s*관한\s*법률|판로\s*지원)[」｣』\"']?"
    r"|중소벤처기업부|중소기업(?:청|중앙회|유통센터|기술정보진흥원|진흥공단)"
    r"|[「｢『\"']?중소\s*기업\s*범위\s*(?:및\s*)?확인에\s*관한\s*규정[」｣』\"']?"
    r"|중소\s*기업\s*[·ㆍ/]?\s*(?:\(?\s*소상공인\s*\)?)?\s*(?:등\s*)?확인\s*서"
    r"|중소\s*기업\s*협동\s*조합|중소\s*기업\s*(?:제품\s*)?공공\s*구매\s*종합\s*정보망"
    r"|중소\s*기업(?:자)?\s*(?:로|으로)\s*간주되는\s*특별\s*법인|\(\s*중소\s*기업자와의\s*우선\s*조달\s*계약\s*\)"
)
#: 확인서 이름 사이 구분 — 「·」 · 「ㆍ」 · 「/」(「소기업/소상공인확인서」 · 1725512 QC-03 · 10-10 검토) · 쉼표.
_SME_SEP = r"\s*[·ㆍ․‧,/]?\s*"
#: 확인서 종류 — 「중 · 소기업 · 소상공인」 · 「중소기업 · 소상공인」(셋 다) / 「소기업 · 소상공인」(둘만).
_SME_CERT_ANY_RE = re.compile(r"(?:중\s*[·ㆍ․‧/]?\s*소\s*기업)" + _SME_SEP + r"소상공인\s*(?:등\s*)?확인\s*서")  # 「중 소기업」 PDF 끊김(G2B-03)
_SME_CERT_SMALL_RE = re.compile(r"(?<![중·ㆍ․‧/])소\s*기업" + _SME_SEP + r"소상공인\s*확인\s*서")
#: 종류를 말하지 않는 확인서 이름 — 「다만 중소기업확인서를 마감 전일까지 신청한 업체는 …」(1758297 QC-07) 같은 확인서 절차 안내.
_SME_CERT_NAME_RE = re.compile(r"(?:중소\s*기업|소상공인)\s*(?:\(\s*소상공인\s*\))?\s*확인\s*서")
#: 직접생산확인 — PDF 줄바꿈으로 「직접생 산」처럼 끊긴다(1718615 QC-08 · 10-10 검토).
_DIRECT_PRODUCTION_RE = re.compile(r"직\s*접\s*생\s*산")
#: 확인서 말고 같은 조항에 붙은 다른 신청 요건(글머리표가 한 조항으로 합쳐진 경우 · 1754106 QC-01) — 사유에는 읽을 수 있는 이름으로.
_SME_OTHER_REQS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"입찰\s*참가\s*자격\s*(?:을\s*)?등록|나라장터[^\n]{0,20}?등록"), "나라장터 입찰참가자격 등록"),
    (re.compile(r"경쟁\s*입찰\s*참가\s*자격"), "경쟁입찰 참가자격"),
    (re.compile(r"부정당"), "부정당업자 제재"),
    (re.compile(r"업종\s*코드|면허"), "업종 · 면허"),
)
#: 대상 낱말 「중소기업」 · 「중 · 소기업」 · 「중기업」.
_SME_SME_WORD: Final[str] = r"중소\s*기업|중\s*[·ㆍ․‧/]\s*소\s*기업|중기업"
#: 판로지원법 시행령 제2조의2(우선조달계약) 1호 — 추정가격 1억 원 미만은 소기업 · 소상공인 대상이다.
_PRIORITY_SMALL_RE = re.compile(r"제\s*2\s*조\s*의\s*2[^\n]{0,40}?1\s*호")
#: 확인서를 **가져야 한다**는 자격 조항 — 안내 · 절차 조항(「… 경우」 · 「없어도」 · 「간주」)과 가른다.
_SME_MAIN_RE = re.compile(r"소지한\s*(?:자|업체|기업)|소지하여야|소지\s*하고\s*있는|보유한\s*(?:자|업체|기업)|(?:소기업|소상공인)\s*(?:만|에\s*한)")
#: 확인서 쪽 조항 갈래 — 셋 다(sme) · 소기업 · 소상공인만(small) · 직접생산(direct) · 확인서로 못 가리는 것(other: 적격조합 · 특별법인 · 정보망).
SmeKind = Literal["sme", "small", "direct", "other"]
SME_CERT_UNLOCK: Final[str] = "중소기업·소상공인확인서(공공기관 입찰용) 발급 시"


def _sme_kind(text: str) -> SmeKind | None:
    """기업 유형 조항이 요구하는 규모 · 서류. 규모와 상관없는 조항이면 None."""
    if _DIRECT_PRODUCTION_RE.search(text):
        return "direct"
    # PDF 가 끊은 「‘중 소기업ㆍ소상공인확인서’」(1750115 QC-03 · 04)는 셋 다 받는 확인서다 — 아래 대상 검사가 띄어 쓴 「소기업」을
    # 소기업 전용으로 읽었다(36차 R35-RULE-12). 뒤에 구분 기호 + 소상공인이 올 때만 붙인다 — 「중소기업자 중 소기업」(G2B-06)은 그대로.
    # 앞이 한글 낱말이면(「중소기업자 중 소기업·소상공인」) 붙이지 않는다 — 소기업 전용 조항이 셋 다로 읽혀 중기업 회사가 거짓 「가능」이었다(36차 R36-06)
    text = re.sub(r"(?<![가-힣])(?<![가-힣]\s)중\s+소\s*기업(?=\s*[·ㆍ․‧/]\s*소상공인)", "중소기업", text)
    # 요구하는 **확인서 종류**가 먼저다 — 「중소기업 또는 소상공인으로서 … 소기업 · 소상공인 확인서를 소지한 자」는 소기업 · 소상공인만
    # 받는 조항이다(1억 미만 용역 · 1756384 QC-05). 「중 · 소기업 · 소상공인 확인서」 · 「중소기업 · 소상공인 확인서」는 셋 다 된다.
    if _SME_CERT_ANY_RE.search(text):
        # 확인서 이름은 일반이어도 「…으로서」 앞 대상이 소기업 · 소상공인뿐이면 소기업 전용이다(1732306 QC-03 — 1호 제한 · 10-10 검토)
        subject = _SME_NAMES_RE.sub(" ", text.split("으로서", 1)[0])
        if re.search(r"중소\s*기업\s*(?:자\s*)?중\s*(?:소\s*기업|소상공인)", subject):
            return "small"  # 「중소기업자 중 소기업자로서 … 중소기업 · 소상공인 확인서」(35차 G2B-06)
        if re.search(r"(?<![중·ㆍ․‧/])소\s*기업|소상공인\s*(?:으로|$)", subject) and not re.search(_SME_SME_WORD, subject):
            return "small"
        return "sme"
    if _SME_CERT_SMALL_RE.search(text):
        return "small"
    t = _SME_NAMES_RE.sub(" ", text)
    if re.search(r"중소\s*기업\s*(?:자\s*)?중\s*(?:소기업|소상공인)", t):
        return "small"
    if re.search(r"중소\s*기업|중기업|중\s*[·ㆍ/]\s*소기업", t):
        return "sme"
    if re.search(r"(?<![중·ㆍ/])소기업|소상공인", t):
        return "small"
    if _SME_CERT_NAME_RE.search(text):
        return "sme"
    if re.search(r"중소\s*기업|소기업|소상공인", text):
        return "other"
    return None


#: 직접생산 세부품명 — 「기타행사기획 및 대행서비스(8014199001)」 · 「동영상제작서비스 8213160301」(43차 M21).
_DIRECT_ITEM_CODE_RE = re.compile(r"([가-힣A-Za-z][가-힣A-Za-z\s및·]{1,30}?)\s*[\(（]?\s*(\d{10})\s*[\)）]?")


def _direct_items(text: str) -> list[tuple[str, str]]:
    """조항이 요구하는 (품명, 10자리 번호)."""
    return [(" ".join(name.split()).strip(" 및·"), code) for name, code in _DIRECT_ITEM_CODE_RE.findall(text)]


def _judge_direct_production(clause: _Clause, company: CompanyFacts) -> EligibilityResult:
    """직접생산 조항 — 회사자료 「직접생산 보유 품명」과 요구 품명을 견준다(43차 M21 · Q24). 값이 비면 「확인 필요 — 보유 ○ · 요구 ○」.

    「중 1건 이상」이면 하나만 맞아도 되고, 아니면 모두. 맞아도 「가능」은 증명서 유효기간을 확인한 사람 몫이라 확인 필요로 두되 문장으로 말한다."""
    wanted = _direct_items(clause.text)
    held = [h.strip() for h in company.direct_production_items if h.strip()]
    want_text = " · ".join(f"{n}({c})" for n, c in wanted[:4]) or "공고문 세부품명"
    if not held:
        return _qual(
            "company_type", clause, "CHECK",
            f"직접생산확인증명서 — 요구 {want_text} · 보유 품명은 회사자료에 아직 없습니다(회사자료 › 입찰 자격 자료 「직접생산 보유 품명」).",
            side="company", unlock=[f"직접생산확인증명서({wanted[0][0] if wanted else '해당 세부품명'}) 보유 시"],
        )
    hit = [(n, c) for n, c in wanted if any(c in h or n.replace(" ", "") in h.replace(" ", "") for h in held)]
    one_of = bool(re.search(r"중\s*(?:1|한)\s*(?:건|개|종)|하나\s*이상|1건\s*이상", clause.text))
    enough = bool(hit) and (one_of or len(hit) == len(wanted))
    if enough:
        # 43차 마지막 검토 — 품명이 맞아도 증명서 유효기간은 회사자료에 없다(만료된 증명서 품명으로 「가능」이 됐다) · 확인 필요로 두고 문장으로 말한다
        return _qual(
            "company_type", clause, "CHECK",
            f"직접생산 — 요구 {want_text} · 보유 {' · '.join(f'{n}({c})' for n, c in hit)}(회사자료 · 품명은 맞음). 직접생산확인증명서 유효기간을 확인하세요.",
            side="company",
        )
    return _qual(
        "company_type", clause, "CHECK",
        f"확인 필요 — 직접생산 보유 {' · '.join(held[:3])} · 요구 {want_text}(요구 품명과 맞지 않습니다).",
        side="company", unlock=[f"직접생산확인증명서({wanted[0][0] if wanted else '해당 세부품명'}) 보유 시"],
    )


def _judge_sme_other(clause: _Clause, kind: SmeKind, company: CompanyFacts | None = None) -> EligibilityResult:
    """직접생산 · 적격조합 · 특별법인 · 정보망 조항 — 중소기업(소상공인) 확인서로 가릴 수 없다(10-10 검토 — 확인서 칸을 적은 회사에게도
    「확인서를 아직 안 적음 · 확인서 발급 시」가 나왔다)."""
    if kind == "direct" and company is not None:
        return _judge_direct_production(clause, company)
    if kind == "direct":
        return _qual(
            "company_type", clause, "CHECK",
            "직접생산확인증명서가 필요한 조항입니다 — 중소기업(소상공인) 확인서와 다른 서류라, 해당 세부품명의 증명서를 갖췄는지 직접 확인하세요.",
            side="company", unlock=["직접생산확인증명서(해당 세부품명) 발급 시"],
        )
    return _qual(
        "company_type", clause, "CHECK",
        "중소기업(소상공인) 확인서로 가릴 수 없는 조항입니다(적격조합 · 특별법인 · 공공구매 정보망 확인 등) — 공고 원문에서 확인하세요.",
        side="notice",
    )


def _judge_sme_clause(
    clause: _Clause, company: CompanyFacts, today: date, kind: SmeKind, fixes: list[str]
) -> EligibilityResult | None:
    """중소기업 · 소기업 · 소상공인 조항을 회사자료 준비 상태의 「중소기업(소상공인) 확인서」 줄로 판정한다(10-10 담당자 결정).

    「없음(확인함)」 · 지난 유효기간도 불가로 닫지 않는다 — 확인서는 받을 수 있는 서류이고, 마감 전일까지 신청만 해도 참가할 수 있는
    공고가 있다. 불가는 확인서 구분이 「중기업」인데 **자격 조항**(「… 소기업 · 소상공인 확인서를 소지한 자」)이 소기업 · 소상공인만
    받을 때뿐이다(가이드 1-3 「흔한 실수」). 같은 공고의 안내 · 절차 조항은 불가로 찍지 않는다 — 인용과 사유가 어긋났다.
    모름이면 None — 예전 문장(인증에 없음 · 발급 시)을 그대로 쓴다.
    """
    state = sme_state(company, today)
    main = bool(_SME_MAIN_RE.search(clause.text))
    what = "소기업 · 소상공인" if kind == "small" else "중소기업"
    unlock = fixes or [SME_CERT_UNLOCK]
    if state == "unknown":
        return None
    if state == "none":
        return _qual(
            "company_type", clause, "CHECK",
            f"{what} 조항인데 회사자료 준비 상태에 중소기업(소상공인) 확인서가 「없음」입니다 — 발급받으면 참가할 수 있는지 공고 원문에서 확인하세요.",
            side="company", unlock=unlock,
        )
    if state == "expired":
        return _qual(
            "company_type", clause, "CHECK",
            f"{what} 조항인데 중소기업(소상공인) 확인서 유효기간({company.sme_valid_until})이 지났습니다 — 새로 발급받아야 합니다.",
            side="company", unlock=unlock,
        )
    others = [label for pattern, label in _SME_OTHER_REQS if pattern.search(clause.text)]
    if others and (kind == "sme" or company.sme_grade in ("소기업", "소상공인")):
        # 글머리표가 합쳐진 조항(1754106 QC-01 — 확인서 · 나라장터 등록 · 부정당업자) — 확인서만 보고 가능이라 하지 않는다
        return _qual(
            "company_type", clause, "CHECK",
            f"확인서 부분은 맞습니다 — 같은 조항의 다른 요건({' · '.join(others)})은 직접 확인하세요.",
            side="company",
        )
    if kind == "sme" and company.sme_grade not in ("소기업", "소상공인") and _PRIORITY_SMALL_RE.search(clause.text):
        # 1호(소기업 · 소상공인 우선조달)를 들면서 대상은 「중소기업」으로 적은 공고(1752887 · 1750306) — 모호하니 불가도 가능도 아니다
        return _qual(
            "company_type", clause, "CHECK",
            "우선조달 1호(추정가격 1억 원 미만 — 소기업 · 소상공인 대상)를 들면서 대상을 중소기업으로 적은 조항입니다 — "
            "회사 확인서 구분으로 참가할 수 있는지 공고 원문이나 발주기관에 확인하세요.",
            side="notice",
        )
    if kind == "sme":
        return _qual("company_type", clause, "PASS", "중소기업(소상공인) 확인서 있음 — 회사자료 준비 상태.")
    if company.sme_grade in ("소기업", "소상공인"):
        return _qual("company_type", clause, "PASS", f"중소기업(소상공인) 확인서 구분 「{company.sme_grade}」 — 회사자료 준비 상태.")
    if not main:
        return _qual(
            "company_type", clause, "CHECK",
            "소기업 · 소상공인 확인서에 관한 안내 조항입니다 — 회사에 해당하는지 공고 원문에서 확인하세요.",
            side="notice",
        )
    if company.sme_grade == "중기업":
        return _qual("company_type", clause, "FAIL", "소기업 · 소상공인만 받는 조항인데 회사 확인서 구분이 「중기업」입니다.")
    return _qual(
        "company_type", clause, "CHECK",
        "소기업 · 소상공인만 받는 조항입니다 — 회사자료 준비 상태에 확인서 구분(중기업 · 소기업 · 소상공인)을 적으면 판정할 수 있습니다.",
        side="company", unlock=["회사자료 준비 상태에 중소기업(소상공인) 확인서 구분을 적으면 판정할 수 있습니다"],
    )


def _judge_track_record(
    clause: _Clause, company: CompanyFacts, today: date, *, notice_amount: tuple[float, str | None] | None = None
) -> EligibilityResult:
    """회사 실적 원장과 견준다 — **불가는 내지 않는다**(원장에 없다 ≠ 실적이 없다).

    `notice_amount` 는 같은 공고의 다른 실적 조항이 적은 금액 기준(천원 · 단일/누적) — 이 조항에 금액이 없으면 그것을 쓴다(43차 H5)."""
    from app.services import performance_match_service as _pm

    clauses = [clause]
    if _NO_TRACK_LIMIT.search(clause.text) and not re.search(r"\d+\s*건|원\s*(?:\([^()]{0,24}\)\s*)?이상", clause.text):
        return _qual(
            "track_record", clause, "PASS",
            "실적 제한을 두지 않는다는 조항입니다 — 실적 요건이 아닙니다(원문 확인).",
        )
    if not company.ledger_available:
        return _qual(
            "track_record", clause, "CHECK",
            "실적 조항입니다 — 회사 실적 목록(엑셀)을 회사자료에 올리면 견줘 봅니다. 지금은 직접 확인하세요.",
            side="company", unlock=["실적 목록(엑셀)을 회사자료에 올리면 견줘 볼 수 있습니다"],
        )
    rows = [dict(row) for row in company.ledger_rows]
    lines: list[str] = []
    enough_all = True
    undecided = False
    for clause in clauses:
        criteria = _pm.parse_criteria(clause.text)
        if criteria.min_amount_thousand is None and notice_amount is not None:
            criteria = criteria.model_copy(update={"min_amount_thousand": notice_amount[0], "amount_mode": notice_amount[1]})
        # 원장 대조기는 분야 낱말 중 **하나만** 맞아도 행을 센다(실적 대조 화면용). 자격 판정은 더 좁게 —
        # 조항의 분야를 **모두** 맞춰야 「유사 실적」이다. 실측: 한양사이버대 「AI/챗봇 … 소프트웨어 개발
        # 분야 유사 구축 실적 3건」에 AI **교육** 과정 26건이 맞았다 — 구축이 아니라 교육이었다.
        work = _clause_work(clause.text)
        hits = [
            h for h in _pm.match_rows(criteria, rows, as_of=today)
            if _covers_all_domains(h, criteria.domains) and _work_fits(work, h.title)
        ]
        need = criteria.min_count or 1
        relative = bool(_RELATIVE_AMOUNT.search(clause.text))
        unseen = bool(_UNSEEN_BRANCH.search(clause.text))
        client = _TARGET_CLIENT.search(clause.text)
        client_unread = bool(client) and not criteria.agency_types
        # 「교육」은 일의 종류지 **무엇의** 교육인지가 아니다. 주제 분야(AI·데이터 …)를 하나도 못 읽었으면
        # 확정하지 않는다 — 실측(1728220): 「K-pop 캠프·음악·영상 콘텐츠 창작 교육」에 AI 교육 12건이 맞아 가능이 났다.
        subject = [d for d in criteria.domains if d != "교육"]
        enough = bool(subject) and len(hits) >= need and not relative and not unseen and not client_unread
        if enough and criteria.amount_mode == "cumulative" and criteria.min_amount_thousand:
            enough = sum(h.amount_thousand_krw or 0 for h in hits) >= criteria.min_amount_thousand
        enough_all = enough_all and enough
        window = f"최근 {criteria.years}년 · " if criteria.years else ""
        found = ", ".join(f"{h.year} {_shorten(h.title, 22)}" for h in hits[:3])
        undecided = undecided or not subject or relative or unseen or client_unread
        lines.append(
            f"{wording.requirement_label(clause.id)}: {window}실적 {need}건 필요 · 실적 목록에 비슷한 일 {len(hits)}건"
            + (f"({found}{' 외' if len(hits) > 3 else ''})" if hits else "")
            + ("" if subject else (" — 조항의 분야가 「교육」뿐이라 무엇의 교육인지 실적 목록으로 정하지 않았습니다" if criteria.domains
                                   else " — 조항이 어떤 분야 실적을 원하는지 읽지 못했습니다"))
            + (" — 금액이 사업비 비율로 적혀 있어 실적 목록으로 정하지 않았습니다" if relative else "")
            + (" — 조항에 실적 목록으로 볼 수 없는 갈래(수료 인원 등)가 함께 있어 정하지 않았습니다" if unseen else "")
            + (f" — 발주처 「{client.group(1).strip()}」을(를) 실적 목록으로 가리지 못했습니다" if client_unread and client else "")
        )
    if enough_all:
        return _qual("track_record", clause, "PASS", "실적 목록과 맞췄습니다 — " + " / ".join(lines))
    head = "실적 목록만으로는 정하지 못했습니다" if undecided else "실적 목록의 건수 · 금액이 모자랍니다"
    return _qual(
        "track_record", clause, "CHECK",
        f"{head} — " + " / ".join(lines) + ". 원문을 보고 「충족 확인 · 미충족」을 골라 주세요.",
        side="company", unlock=["실적 증명서로 조항 건수를 채우면 가능"],
    )


def _clause_work(text: str) -> str | None:
    """조항이 요구하는 일의 종류 — 「content」(영상 · 콘텐츠 개발) · 「build」(구축·개발) · 「edu」(교육 운영) · 「consult」(컨설팅) · 모르면 None."""
    if _CONTENT_CLAUSE.search(text):
        return "content"
    if _BUILD_CLAUSE.search(text):
        return "build"
    if _EDU_CLAUSE.search(text):
        return "edu"
    if _CONSULT_CLAUSE.search(text):
        return "consult"
    return None


def _work_fits(work: str | None, title: str) -> bool:
    """원장 행이 조항의 일과 같은 종류인가. 컨설팅 조항은 교육 제목 행만 뺀다(컨설팅 행은 제목에 일 종류 낱말이 없을 수 있다)."""
    if work is None:
        return True
    if work == "content":
        return bool(_CONTENT_TITLE.search(title))
    if work == "consult":
        return _title_work(title) != "edu"
    return _title_work(title) == work


def _title_work(title: str) -> str | None:
    """원장 행 제목이 말하는 일의 종류. 교육 낱말이 있으면 교육이다(「AI 플랫폼 활용 교육」은 교육)."""
    if _EDU_TITLE.search(title):
        return "edu"
    if _BUILD_TITLE.search(title):
        return "build"
    return None


def _covers_all_domains(hit: Any, domains: list[str]) -> bool:
    """원장 행 하나가 조항의 분야 낱말을 **전부** 담는가 (제목·요약·발주기관에서)."""
    from app.services import performance_match_service as _pm

    text = _pm.work_text(hit.title, hit.summary).lower()
    return all(any(word.lower() in text for word in _pm._DOMAIN_GROUPS[d]) for d in domains)


def _judge_staff(clause: _Clause) -> EligibilityResult:
    return _qual(
        "staff", clause, "CHECK",
        "투입 인력의 자격·경력 조항 — 회사자료에 인력 정보(상시 근로자 수·자격 보유자)가 없어 확정하지 못합니다.",
        side="company", unlock=["투입 인력의 자격·경력 증빙을 갖추면 가능"],
    )


def _judge_consortium(clause: _Clause, raw: dict[str, Any] | None, company: CompanyFacts) -> EligibilityResult:
    """조항과 공고 필드가 다르면 원문 확인, 공동수급이 필수면 파트너 확보로 가른다.

    불허·허용(선택)이 필드와 같으면 판정이 아니라 **확인**이다 — 단독 수행 여부는 규모 규칙(ELIG-BUDGET)이
    본다. 19차는 이것을 계약 줄(ELIG-AWARD)에 붙였지만 20차부터 조항은 제 줄을 갖는다(원문 확인).
    """
    forbid = bool(_CONSORTIUM_FORBID.search(clause.text))
    required = bool(_CONSORTIUM_REQUIRED.search(clause.text)) and not forbid
    clause_allows: bool | None = False if forbid else (True if _CONSORTIUM_ALLOW.search(clause.text) else None)
    field_allows = joint_allowed(raw) if raw is not None else None
    field_text = _notice_field(raw or {}, "cmmnSpldmdMethdNm", "joint_supply_method")
    if clause_allows is not None and field_allows is not None and clause_allows != field_allows:
        return _qual(
            "consortium", clause, "CHECK",
            f"공고문은 공동수급 {'불허' if not clause_allows else '허용'}인데 나라장터 기본정보는 「{field_text}」입니다."
            " 원문이 우선이지만 직접 확인하세요.",
            side="notice",
        )
    if required:
        joint = company.joint_bid_available
        if joint is None:
            return _qual(
                "consortium", clause, "CHECK", "공동수급체 구성이 필요한 조항입니다. 회사의 파트너 확보 여부가 비어 있습니다.",
                side="company", unlock=["공동수급 파트너 확보 시"],
            )
        if joint:
            return _qual("consortium", clause, "PASS", "공동수급체 구성이 필요하고, 회사는 파트너를 확보해 두었습니다.")
        # 파트너는 구할 수 있다 — 「없음(확인함)」도 불가로 닫지 않는다(35차 기본값 · 확인서 「없음」과 같은 논리)
        return _qual(
            "consortium", clause, "CHECK",
            "공동수급체 구성이 필요한 조항인데 회사는 지금 파트너가 없다고 적었습니다 — 함께할 회사를 구하면 참가할 수 있습니다.",
            side="company", unlock=["함께할 회사(공동수급 파트너)를 구하면 가능"],
        )
    if clause_allows is not None and field_allows is not None:
        why = f"공동수급 {'허용' if clause_allows else '불허'} 조항 — 나라장터 기본정보 「{field_text}」와 같습니다. 원문을 확인하세요."
    elif clause_allows is not None:
        why = (f"공동수급 {'허용' if clause_allows else '불허'} 조항 — 나라장터 기본정보에 공동수급 방식이 없어 견주지 못했습니다."
               " 원문을 확인하세요.")
    else:
        why = "공동수급 조항 — 규칙으로 가르지 못했습니다. 원문을 직접 확인하세요."
    return _qual("consortium", clause, "CHECK", why, side="notice")


#: 결격 조항 속 안내문(콜센터 · 문의처) — 판정할 요건이 아니다(43차 M7).
_DISQUAL_RULE = re.compile(r"제재|체납|결격|제한|참가할\s*수\s*없|참여할\s*수\s*없|무효")
_DISQUAL_NOTICE = re.compile(r"콜센터|고객지원센터|문의\s*(?:처|전화)|☎|1588-?\d{4}")


#: 회사 단위 확인(등록 · 부정당 제재 · 체납)이 다루는 결격 낱말 — 이것을 말하는 조항만 「통과」시킨다(43차 마지막 검토).
_DISQUAL_SUBJECT: Final = re.compile(
    r"부정당|제재|체납|결격|참가\s*자격\s*(?:제한|정지)|입찰\s*참가\s*(?:제한|정지)|당사자로\s*하는\s*계약|시행령\s*제\s*(?:76|92)\s*조|"
    r"등록(?:을)?\s*하지\s*않|미등록|등록되지\s*않|"
    # 44차 마지막 검토 — 긍정형 등록 조항(「나라장터에 입찰참가자격을 등록한 자」 · 「등록을 필한 자」)도 회사 단위 확인(등록)이 다룬다
    r"(?:입찰\s*)?참가\s*자격(?:을)?\s*(?:등록한|등록을\s*필한|등록된)|등록을\s*필한"
)
#: 빼는 문장 꼴이어도 회사 단위 확인으로 풀 수 없는 조건 — 실적 · 지역 · 기업 형태 · 인력 · 면허(「유사 실적이 없는 자는 참가할 수 없다」).
_DISQUAL_OTHER: Final = re.compile(r"실적|소재|영업소|본사|지역|중소기업|중견|대기업|소상공인|인력|기술자|경력|면허|업종|자본금|매출")
#: 회사 단위 확인(등록 · 제재 · 체납)이 다루지 않는 결격 — 부도 · 회생 · 파산 · 상호출자 등(44차 R36-J-04 — 이것도 「통과」였다)
_DISQUAL_HARD: Final = re.compile(r"부도|회생|파산|화의|법정\s*관리|상호\s*출자|워크\s*아웃|해산|청산|휴업|폐업")


def _judge_disqualification(clause: _Clause, company: CompanyFacts | None = None, today: date | None = None) -> EligibilityResult:
    if _DISQUAL_OTHER.search(clause.text) and not _DISQUAL_SUBJECT.search(clause.text):
        # 빼는 문장 꼴이지만 실적 · 지역 · 기업 형태를 말한다 — 회사 단위 확인으로 「통과」시키지 않는다(근거 없는 가능 · §11)
        return _qual(
            "disqualification", clause, "CHECK",
            "빼는 조건이 실적 · 지역 · 기업 형태 같은 회사 사실을 말합니다 — 회사 단위 확인(등록 · 제재 · 체납)으로는 풀리지 않습니다. 원문을 읽고 「충족 확인 · 미충족」을 골라 주세요.",
            side="company",
        )
    mixed = bool(_DISQUAL_OTHER.search(clause.text))
    if _DISQUAL_HARD.search(clause.text):
        # 44차 R36-J-04 — 부도 · 회생 · 상호출자 같은 조건은 회사 단위 확인 세 칸이 다루지 않는다(「통과」로 새지 않는다)
        return _qual(
            "disqualification", clause, "CHECK",
            "부도 · 회생 · 파산 · 상호출자 같은 조건은 회사 단위 확인(등록 · 제재 · 체납)이 다루지 않습니다 — 원문을 읽고"
            " 「충족 확인 · 미충족」을 골라 주세요.",
            side="company",
        )
    # 「통과」는 회사 단위 확인이 다루는 결격(등록 · 부정당 · 제재 · 체납 …) 낱말이 있고 다른 조건이 섞이지 않았을 때만(R36-J-04)
    if company is not None and company.company_checks and not mixed and _DISQUAL_SUBJECT.search(clause.text):
        state, detail = company_check_state(company, REGISTRATION_CHECK_KEYS, today or storage.kst_today())
        if state == "valid":
            return _qual("disqualification", clause, "PASS", f"통과(회사 확인 {detail}) — 등록 · 부정당 제재 없음 · 체납 없음을 회사 단위로 확인했습니다.")
        if state == "expired":
            return _qual("disqualification", clause, "CHECK", f"다시 확인 — {detail}.", side="company")
    return _qual(
        "disqualification", clause, "CHECK",
        "입찰 참가 제한을 받은 적이 없는지(부정당업자 제재) · 세금 체납이 없는지 · 나라장터에 입찰참가자격을"
        " 등록했는지 직접 확인하세요.",
        side="company",
    )


def _judge_other(clause: _Clause) -> EligibilityResult:
    return _qual("other", clause, "CHECK", "규칙으로는 판단할 수 없는 조항입니다. 원문을 읽고 「충족 확인 · 미충족」을 골라 주세요.", side="notice")


def _doc_result(notice_id: str, payload: dict[str, Any] | None) -> EligibilityResult:
    """공고문을 못 읽었을 때의 한 줄 — **가능으로 새지 않는다.**"""
    status = (payload or {}).get("status") or "not_fetched"
    note = (payload or {}).get("note") or ""
    reasons = {
        "not_fetched": "공고문의 참가자격 부분을 아직 안 읽었습니다",
        "no_section": "공고문에서 참가자격 부분을 찾지 못했습니다",
        "image": "공고문이 스캔 이미지라 글자를 읽지 못했습니다",
        "error": "공고문을 여는 중 실패했습니다",
    }
    document = ((payload or {}).get("document") or {}).get("name")
    return EligibilityResult(
        rule_id="QUAL-DOC",
        label="공고문 참가자격 부분",
        status="CHECK",
        method="RULE",
        source=f"입찰공고문 {document}" if document else "입찰공고문: 참가자격 부분을 읽은 기록 없음",
        reason=f"{reasons.get(status, reasons['not_fetched'])}{' — ' + note if note else ''}. 원문을 직접 확인하세요.",
        check_side="notice",
    )


def _clauses_of(payload: dict[str, Any] | None, reqs: list[Requirement]) -> list[_Clause]:
    from app.services import qualification_clause_service as _qc

    out: list[_Clause] = []
    seen: set[str] = set()

    def fresh(text: str) -> bool:
        """두 출처의 **같은 조항**은 한 번만 센다 — 공고문과 제안요청서가 같은 문장을 옮겨 적는 일이 흔하다."""
        # 글머리(「– 」「- 」「• 」「○ 」)와 번호(「가.」「나)」「1.」「(2)」「①」)는 떼고 견준다 — 실측(한양사이버대):
        # 공고문 「최근 3년 이내 …」와 RFP 요구사항 「– 최근 3년 이내 …」, 공고문 「국가를 당사자로 …」와
        # RFP 「나. 국가를 당사자로 …」가 같은 조항인데 두 줄이 됐다(20차).
        body = _qc.clause_body(text)
        key = re.sub(r"[\s·ㆍ‧,.()「」『』'\"]", "", body)[:40]
        if key in seen:
            return False
        seen.add(key)
        return True

    if payload and payload.get("status") == "ok":
        approx = bool(payload.get("page_is_approximate"))
        for c in payload.get("clauses") or []:
            if fresh(str(c["text"])):
                out.append(_Clause(str(c["id"]), str(c["text"]), c.get("page"), "입찰공고문", approx, str(c.get("kind") or "other")))
    second = (payload or {}).get("second_source") or None
    if second:
        approx = bool(second.get("page_is_approximate"))
        for c in second.get("clauses") or []:
            if fresh(str(c["text"])):
                out.append(_Clause(f"RFP-{c['id']}", str(c["text"]), c.get("page"), "제안요청서", approx, str(c.get("kind") or "other")))
    for req in reqs:
        # 인용은 **원문 그대로**(`source_text`) — 요약한 `content` 를 원문처럼 적지 않는다.
        text = req.source_text or req.content or req.title or ""
        if fresh(text):
            out.append(_Clause(req.requirement_id, text, req.page, "제안요청서", False, _qc.classify(text), req.requirement_id))
    return out


def _kst_minutes(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def _apply_review(row: EligibilityResult, clause: _Clause, fact: tuple[str, ...] | None) -> EligibilityResult:
    """담당자 확인을 그 조항 줄에 합친다 (20차 §4-C).

    - 충족 → 가능(`HUMAN`) · 미충족 → 불가(`HUMAN`) · 보류 → 규칙 그대로(상태만 적는다).
    - 확인할 때의 원문 해시가 지금 원문과 다르면 **`stale`** — 그 확인은 판정에 쓰지 않는다.
    """
    if fact is None:
        return row
    from app.services import qualification_review_service as _qr

    _pid, _cid, state, note, decided_by, decided_at, hashed = fact
    when = datetime.fromisoformat(decided_at) if decided_at else None
    common: dict[str, Any] = {"reviewed_by": decided_by or None, "reviewed_at": when, "review_note": note or None}
    if hashed != _qr.clause_hash(clause.text):
        return row.model_copy(update={**common, "review_state": "stale"})
    if state not in ("met", "unmet"):
        return row.model_copy(update={**common, "review_state": "pending"})
    word = "충족" if state == "met" else "미충족"
    return row.model_copy(update={
        **common,
        "review_state": state,
        "status": "PASS" if state == "met" else "FAIL",
        "method": "HUMAN",
        "check_side": None,
        "source": f"담당자 확인 {decided_by} {_kst_minutes(decided_at)}: {note} / {row.source}",
        "reason": f"담당자가 「{word}」으로 확인했습니다 — 규칙 판정: {row.reason}",
    })


def _qualification_rows(
    notice_id: str | None,
    raw: dict[str, Any] | None,
    reqs: list[Requirement],
    as_of: datetime,
    *,
    review_key: str | None = None,
) -> list[EligibilityResult]:
    """참가자격 조항 줄 — **조항마다 한 줄**, 종류 순서(업종 → … → 기타) 안에서는 원문 순서.

    `raw` 가 None 이면 나라장터 공고가 아니다(합성 시나리오) — 공고문이 없으니 `QUAL-DOC` 을
    내지 않고 RFP 요구사항만 본다.
    """
    from app.services import qualification_clause_service as _qc
    from app.services import qualification_review_service as _qr

    company = active_company()
    today = as_of.astimezone(KST).date()
    payload = _qc.load(notice_id) if (notice_id and raw is not None) else None
    rows: list[EligibilityResult] = []
    if raw is not None and (payload is None or payload.get("status") != "ok"):
        rows.append(_doc_result(notice_id or "(공고 번호 없음)", payload))
    clauses = _clauses_of(payload, reqs)
    key = review_key or notice_id
    facts = [fact for fact in company.clause_reviews if fact[0] == key] if key else []
    reviews = {fact[1]: fact for fact in facts}
    # 조항 id 가 바뀌어도(조항 파일이 뒤에 와서 RFP 요구사항 REQ-011 이 공고문 조항 QC-03 으로 합쳐짐) **같은 원문**이면
    # 그 확인을 잇는다 — id 로만 찾으면 「미충족」이 조용히 사라져 「참여」를 막지 못한다. id 가 맞는 확인이 먼저다.
    # 41차 R40-CLAUSE-A — 원문 해시가 같은 확인이 여럿이면 **가장 최근**(번호 순 마지막이 남아 옛 「충족」이 새 「미충족」을 이겼다)
    by_text: dict[str, Any] = {}
    for fact in facts:
        if fact[6] and (fact[6] not in by_text or fact[5] > by_text[fact[6]][5]):
            by_text[fact[6]] = fact
    current_hashes = {_qr.clause_hash(c.text) for c in clauses}
    for kind in QUAL_KIND_ORDER:
        for clause in (c for c in clauses if (c.kind if c.kind in QUAL_LABELS else "other") == kind):
            if kind == "disqualification" and _DISQUAL_NOTICE.search(clause.text) and not _DISQUAL_RULE.search(clause.text):
                continue  # 「정부조달콜센터(☎ 1588-0800)로 문의」 같은 안내문 — 판정할 요건이 아니다(43차 M7)
            if kind == "industry":
                row = _judge_industry(clause, raw or {}, company)
            elif kind == "region":
                row = _judge_region(clause, company)
            elif kind == "company_type":
                row = _judge_company_type(clause, company, today)
            elif kind == "track_record":
                row = _judge_track_record(clause, company, today, notice_amount=_notice_amount(clauses))
            elif kind == "staff":
                row = _judge_staff(clause)
            elif kind == "consortium":
                row = _judge_consortium(clause, raw, company)
            elif kind == "disqualification" and _qc.industry_codes(clause.text):
                row = _judge_industry(clause, raw or {}, company)  # 「[행사대행업, 9901]으로 등록한 업체」 — 업종 조건(R36-J-04 · 옛 조항 파일도)
            elif kind == "disqualification":
                row = _judge_disqualification(clause, company, today)
            else:
                row = _judge_other(clause)
            if kind == "company_type" and row.status == "FAIL":
                row = _soften_by_exception(row, clause, clauses)
            hashed = _qr.clause_hash(clause.text)
            by_id = reviews.get(clause.id)
            # 40차 CLAUSE-06 — 원문 해시가 맞는 확인이 먼저(id 도 맞으면 그것) · 없을 때만 id 로(그 확인은 stale). 다시 뽑기로 번호가 밀리면
            # id 로 먼저 집은 다른 조항의 확인이 「stale」로 끝나 원문이 같은 「미충족」이 사라졌다(담당자가 닫은 공고가 「확인 필요」로 돌아옴).
            fact = by_text.get(hashed)
            if fact is None and by_id is not None and by_id[6] not in current_hashes:
                # id 만 맞는 옛 확인(stale) — 그 원문이 **지금 다른 줄**에 있으면 그 줄에 이미 붙었다(41차 R40-CLAUSE-B · 유령 「다시 확인」 줄을 만들지 않는다)
                fact = by_id
            rows.append(_apply_review(row, clause, fact))
    return rows


def _notice_amount(clauses: list[_Clause]) -> tuple[float, str | None] | None:
    """같은 공고 실적 조항 중 금액 기준이 있는 첫 조항의 (천원, 단일/누적) — 없으면 None(43차 H5)."""
    from app.services import performance_match_service as _pm

    for clause in clauses:
        if clause.kind == "track_record":
            criteria = _pm.parse_criteria(clause.text)
            if criteria.min_amount_thousand is not None:
                return criteria.min_amount_thousand, criteria.amount_mode
    return None


#: 같은 절의 「단, … 예외 … 참가를 허용」 — 기업 유형 요건을 풀어 주는 조항(40차 CLAUSE-07 · 1718593 「중소기업자 우선조달계약 예외를 적용하여 …
#: 법인 · 기관 · 단체 등의 입찰참가를 허용」).
_TYPE_EXCEPTION = re.compile(r"(?<![가-힣])단\s*[,，].{0,200}?예외.{0,160}?(?:참가|참여)\s*(?:를|을)?\s*허용")


def _soften_by_exception(row: EligibilityResult, clause: _Clause, clauses: list[_Clause]) -> EligibilityResult:
    """기업 유형 「불가」를 같은 절(같은 문서)의 예외 조항이 있으면 「확인 필요」로 낮춘다 — 판정은 조항을 하나씩만 봐서 옆 조항의 예외를 놓쳤다."""
    found = next((c for c in clauses if c is not clause and c.origin == clause.origin and _TYPE_EXCEPTION.search(c.text)), None)
    if found is None:
        return row
    return row.model_copy(update={
        "status": "CHECK",
        "check_side": "notice",
        "reason": f"{row.reason} 다만 같은 절에 「단, … 예외 … 참가를 허용」 조항({found.id})이 있어 원문을 확인해야 합니다.",
    })


def clause_texts(procurement_id: str) -> dict[str, str]:
    """이 공고의 참가자격 조항 `{조항 id: 원문}` — 판정 줄이 쓰는 목록(두 출처 같은 조항은 하나).

    담당자 확인 저장(`PUT /api/eligibility/{id}/review/{clause_id}`)이 조항이 있는지 보고, 그때 원문의
    해시를 남기는 데 쓴다. 파일만 읽는다(네트워크 없음).

    상세는 공고가 목록에 없으면 조항 파일 없이 RFP 요구사항만으로 줄을 만든다(`_evaluate_from_sources`).
    그래서 두 경우의 합집합이다 — 화면에 보이는 줄이 저장에서 404 가 나지 않게. 같은 id 는 두 경우 같은 원문이다.
    """
    from app.services import qualification_clause_service as _qc

    _registration, reqs, _total = _qualification_requirements(_load_parse(procurement_id))
    without_file = {c.id: c.text for c in _clauses_of(None, reqs)}
    return {**without_file, **{c.id: c.text for c in _clauses_of(_qc.load(procurement_id), reqs)}}


def offline_report(procurement_id: str, context: "AnalysisContext | None") -> EligibilityReport | None:
    """**네트워크 없이** 판정한다 — 저장된 공고 목록(`cached_only`)과 파싱 파일만 읽는다.

    「참여」 저장 거절(`decision_service`)이 쓴다. 저장 요청 하나가 나라장터를 부르면 안 된다.
    공고도 파싱도 없으면 None — 판정할 것이 없다(막지 않는다: 조건 게이트가 없을 때와 같은 규칙).
    """
    from app.services import organization_service as _orgs
    from app.services import procurement_service as _ps

    cached = _ps.cached_only(include_low=True)
    view = next((v for v in (cached.notices if cached else []) if v.notice.id == procurement_id), None)
    parse = _load_parse(procurement_id)
    if view is None and parse is None:
        return None
    organization_id = context.organization_id if context else None
    try:
        regions = _orgs.preferred_regions(organization_id) if organization_id else None
    except _orgs.OrganizationNotFoundError:
        regions = None  # 등록부에 없는 조직 — 활동 지역 없이 판정한다(지역 규칙은 확인 필요로 남는다)
    return evaluate_from_sources(
        procurement_id,
        notice=view,
        parse_result=parse,
        use_llm=False,
        regions=regions,
        company=company_facts_for(organization_id, evidence_scope=context.evidence_scope if context else None),
        context=context,
    )


def _clause_documents(payload: dict[str, Any] | None, raw: dict[str, Any] | None) -> list[ClauseDocument]:
    """조항을 읽은 문서와 원본 링크. 첨부 순번(`document.index`)은 공고의 첨부 목록 순번이다."""
    from app.services import attachment_service

    attachments = list((raw or {}).get("attachments") or [])
    documents: list[ClauseDocument] = []
    for role, block in (("입찰공고문", payload), ("제안요청서", (payload or {}).get("second_source"))):
        document = (block or {}).get("document") or {}
        if not document.get("name"):
            continue
        index = document.get("index")
        url = None
        if isinstance(index, int) and 0 <= index < len(attachments) and isinstance(attachments[index], dict):
            candidate = str(attachments[index].get("url") or "")
            url = candidate if candidate and attachment_service.is_allowed_url(candidate) else None
        documents.append(ClauseDocument(source_document=role, name=str(document["name"]), format=document.get("format"), url=url))
    return documents


def review_tally(results: list[EligibilityResult]) -> ReviewTally:
    """보고서 머리의 확인 수 — 조항 줄 기준. 기록이 없는 조항은 `pending` 에 센다(확인 전)."""
    rows = [r for r in results if r.clause_id]
    return ReviewTally(
        met=sum(1 for r in rows if r.review_state == "met"),
        unmet=sum(1 for r in rows if r.review_state == "unmet"),
        pending=sum(1 for r in rows if r.review_state not in ("met", "unmet")),
        stale=sum(1 for r in rows if r.review_state == "stale"),
    )


def clause_summary(results: list[EligibilityResult]) -> dict[str, int]:
    """참가자격 조항 줄의 종류별 개수 — 보고서 머리(`EligibilityReport.clause_summary`)."""
    summary: dict[str, int] = {}
    for row in results:
        if row.clause_id and row.kind:
            summary[row.kind] = summary.get(row.kind, 0) + 1
    return summary


def qualification_line(results: list[EligibilityResult]) -> str | None:
    """화면·순위 사유에 쓰는 한 줄 — 「공고문 조항 n개 · 회사 쪽 확인 m개 · 미확인 k개」 (19차 §4-B).

    `opportunity_priority` 의 고정 문구(「참가자격은 공고 원문에서 확인해야 합니다」)를 대신한다.
    조항을 못 읽었으면 그 사실을 말한다. 참가자격 조항 줄이 하나도 없으면 None.
    """
    doc = next((r for r in results if r.rule_id == "QUAL-DOC"), None)
    rows = [r for r in results if r.clause_id]
    clause_count = len(rows)
    company_side = sum(1 for r in rows if r.status == "CHECK" and r.check_side == "company")
    notice_side = sum(1 for r in rows if r.status == "CHECK" and r.check_side != "company")
    if doc is not None and not rows:
        return f"참가자격: {re.split(r' — |\. ', doc.reason)[0].rstrip('.')}"
    if not rows:
        return None
    failed = sum(1 for r in rows if r.status == "FAIL")
    line = f"참가자격 조항 {clause_count}개 — 회사 정보 필요 {company_side} · 공고문 더 읽기 {notice_side}"
    if failed:
        line += f" · 불가 {failed}"
    if doc is not None:
        line += " · 공고문은 못 읽어 제안요청서 조항만 봤습니다"
    return line


# ---------------------------------------------------------------------------
# 4) 조립
# ---------------------------------------------------------------------------


def overall_verdict(results: list[EligibilityResult]) -> EligibilityStatus:
    """FAIL이 하나라도 있으면 FAIL, 없고 CHECK가 있으면 CHECK, 전부 PASS면 PASS."""
    if any(r.status == "FAIL" for r in results):
        return "FAIL"
    if any(r.status == "CHECK" for r in results):
        return "CHECK"
    return "PASS"


def _counts(results: list[EligibilityResult]) -> EligibilityCounts:
    return EligibilityCounts(
        total=len(results),
        passed=sum(1 for r in results if r.status == "PASS"),
        check=sum(1 for r in results if r.status == "CHECK"),
        failed=sum(1 for r in results if r.status == "FAIL"),
    )


def award_line(raw: dict[str, Any]) -> str | None:
    """계약·낙찰 방식 한 줄. 규칙 하나만 돌린다 — 목록 100건에 전체 판정을 두 번 돌리지 않는다."""
    result = _rule_award(raw)
    return result.reason if result is not None else None


def _clause_pages(payload: dict[str, Any] | None) -> str | None:
    """「2쪽」·「2–3쪽(근사)」 — 화면 머리글 「참가자격 조항 — 입찰공고문 N쪽」에 쓴다."""
    section = (payload or {}).get("section") or {}
    start, end = section.get("page_from"), section.get("page_to")
    if not start:
        return None
    pages = f"{start}쪽" if not end or end == start else f"{start}–{end}쪽"
    return pages + ("(근사)" if (payload or {}).get("page_is_approximate") else "")


def _qualification_requirements(
    parse_result: RfpParseResult | None,
) -> tuple[Requirement | None, list[Requirement], int]:
    """RFP 요구사항 중 참가자격 조항. (사업자등록 조항, 나머지 앞 12개, 전체 개수)."""
    if parse_result is None:
        return None, [], 0
    qualification = [r for r in parse_result.requirements if _is_qualification_requirement(r)]
    registration = next((r for r in qualification if _is_registration_only(r)), None)
    rest = [r for r in qualification if r is not registration]
    return registration, rest[:MAX_REQUIREMENT_RULES], len(qualification)


def _overflow_result(total: int) -> EligibilityResult | None:
    if total <= MAX_REQUIREMENT_RULES:
        return None
    return EligibilityResult(
        rule_id="ELIG-REQ-OVERFLOW",
        label="추가 자격 조항",
        status="CHECK",
        method="RULE",
        source=f"입찰참가자격 요구사항 {total}건 중 {MAX_REQUIREMENT_RULES}건만 규칙화",
        reason=f"자격 관련 요구사항 {total - MAX_REQUIREMENT_RULES}건이 목록에서 생략되었습니다. 요구사항 정리표에서 전체를 확인하세요.",
    )


def _load_parse(notice_id: str | None) -> RfpParseResult | None:
    """목록 경로용 — 파싱해 둔 RFP 가 **파일로 있을 때만** 읽는다(네트워크 없음)."""
    if not notice_id or not (rfp_parser.is_fixture(notice_id) or rfp_parser.is_real_notice_id(notice_id)):
        return None  # 직접 넣은 공고(manual-…)처럼 분석 파일 꼴이 아닌 id — 읽을 RFP 가 없다(38차 §3-E)
    if not rfp_parser.generated_path(notice_id).exists():
        return None
    try:
        return rfp_parser.load_generated(notice_id)
    except (rfp_parser.RfpNotParsedError, ValueError, OSError):
        return None


def _collect_notice_rules(
    raw: dict[str, Any],
    as_of: datetime,
    registration_req: Requirement | None,
    *,
    notice_id: str | None = None,
    qual_reqs: list[Requirement] | None = None,
) -> list[EligibilityResult]:
    """공고 필드 검사(ELIG-*) + 참가자격 조항(QUAL-*). **목록과 상세가 같은 함수를 지난다.**"""
    fields = _schedule_rules(_collect_field_rules(raw, as_of, registration_req), raw, as_of, notice_id)
    quals = _qualification_rows(notice_id, raw, list(qual_reqs or []), as_of)
    if any(q.rule_id.startswith("QUAL-TRACK-") and q.status != "PASS" for q in quals):
        # 목록 API 의 참가제한 · 실적평가 칸만 보고 「없음 — 가능」이라 했다(34차 R33-D3 · 12건). 조항 줄이 따로 판정한다.
        # 실적 조항 줄이 모두 「가능」(담당자 확인 · 실적 목록)이면 바꾸지 않는다 — 영영 「가능」에 닿지 못했다(34차 마지막 검토).
        fields = [
            f.model_copy(update={
                "status": "CHECK",
                "check_side": "notice",
                "reason": "나라장터 기본정보에는 실적 · 참가 제한이 없지만 공고 문서에 실적 참가자격 조항이 있습니다 — 아래 조항 줄에서 확인하세요.",
            })
            if f.rule_id == "ELIG-TRACK-RECORD" and f.status == "PASS" else f
            for f in fields
        ]
    return fields + quals


def _schedule_rules(
    fields: list[EligibilityResult], raw: dict[str, Any], as_of: datetime, notice_id: str | None
) -> list[EligibilityResult]:
    """공고문 일정표(43차 결정 1 · H1 · ELIG-06) — 입찰 마감이 비면 개찰일을 마감으로 쓰지 않고 공고문의 참가신청 · 입찰등록 ·
    제출 마감 중 가장 이른 것으로 판정한다. 필수 현장설명은 「필수 — 불참 시 참가 불가」 줄(지나면 「사실상 마감」)."""
    from app.services import notice_schedule
    from app.services import qualification_clause_service as _qc

    payload = _qc.load(notice_id) if notice_id else None
    schedule = (payload or {}).get("schedule") if isinstance(payload, dict) else None
    published = _parse_notice_datetime(_notice_field(raw, "bidNtceDt", "rgstDt"))
    first = notice_schedule.earliest(schedule, after=published)
    brief = notice_schedule.briefing(schedule)
    opening = _parse_notice_datetime(_notice_field(raw, "opengDt", "opening_at"))
    out: list[EligibilityResult] = []
    for rule in fields:
        if rule.rule_id != "ELIG-BID-DEADLINE":
            out.append(rule)
            continue
        if _notice_field(raw, "bidClseDt"):
            out.append(rule)
            # 44차 R36-J-03 — 입찰 마감이 있어도 공고문 일정표 마감이 입찰 · 등록 마감보다 이르면 그 줄도 낸다. 목록의 실제 마감
            # (`practical_priority.effective_deadline` = 입찰 · 등록 · 일정 중 가장 이른 것)과 같은 날로 판정해 목록 「제외」 · 상세
            # 「N일 남음」이 갈리지 않는다. 촉박(D3)도 이 줄이 같은 `_moment_rule` 로 센다.
            if first is not None and first.get("kind") != "briefing":  # 필수 현장설명은 아래 ELIG-BRIEFING 줄
                at = datetime.fromisoformat(str(first["at"]))
                bid = _parse_notice_datetime(_notice_field(raw, "bidClseDt"))
                qual = _parse_notice_datetime(_notice_field(raw, "bidQlfctRgstDt", "qualification_deadline"))
                if all(other is None or at < other for other in (bid, qual)):
                    when = f"{at.astimezone(KST):%m/%d}" + (f" {at.astimezone(KST):%H:%M}" if first.get("time_known") else "(시각 원문 확인)")
                    out.append(_moment_rule(
                        rule_id="ELIG-SCHEDULE-DEADLINE", label=f"{first['label']}(공고문 일정)", moment=at, as_of=as_of,
                        passed_reason=f"공고문 일정표의 {first['label']}({when})이 이미 지났습니다 — 입찰 마감보다 이릅니다.",
                        source=f"공고문 p.{first.get('page') or '?'} — 「{_shorten(str(first.get('text') or ''), 70)}」",
                    ))
            continue
        # 입찰 마감이 비었다 — 개찰일은 제출 마감이 아니다(H1)
        if first is not None:
            at = datetime.fromisoformat(str(first["at"]))
            when = f"{at.astimezone(KST):%m/%d}" + (f" {at.astimezone(KST):%H:%M}" if first.get("time_known") else "(시각 원문 확인)")
            out.append(_moment_rule(
                rule_id="ELIG-BID-DEADLINE", label=f"{first['label']}(공고문 일정)", moment=at, as_of=as_of,
                passed_reason=f"공고문 일정표의 {first['label']}({when})이 이미 지났습니다.",
                source=f"공고문 p.{first.get('page') or '?'} — 「{_shorten(str(first.get('text') or ''), 70)}」",
            ))
            continue
        opened = f"개찰 {opening.astimezone(KST):%m/%d %H:%M}" if opening else "개찰일도 없음"
        if opening is not None and opening < as_of:
            out.append(rule.model_copy(update={
                "status": "FAIL",
                "reason": f"입찰 마감은 비어 있고 {opened}이 이미 지났습니다 — 접수가 끝난 공고입니다.",
            }))
            continue
        out.append(rule.model_copy(update={
            "reason": f"마감 미상 — 나라장터 기본정보에 입찰 마감이 없습니다({opened} · 제출 마감 아님). "
                      "공고문 일정표에서 참가신청 · 입찰등록 · 제출 마감을 확인하세요.",
            "check_side": "notice",
        }))
    if brief is not None and brief.get("required"):
        at = datetime.fromisoformat(str(brief["at"]))
        when = f"{at.astimezone(KST):%m/%d %H:%M}"
        source = f"공고문 p.{brief.get('page') or '?'} — 「{_shorten(str(schedule.get('briefing_required_text') or brief.get('text') or ''), 70)}」"
        if at < as_of:
            out.append(EligibilityResult(
                rule_id="ELIG-BRIEFING", label="필수 현장설명", status="FAIL", method="RULE", source=source,
                reason=f"사실상 마감 — 필수 현장설명({when})이 지났습니다. 불참하면 참가할 수 없습니다.",
            ))
        else:
            out.append(EligibilityResult(
                rule_id="ELIG-BRIEFING", label="필수 현장설명", status="CHECK", method="RULE", source=source,
                reason=f"필수 — 불참 시 참가 불가 · 현장설명 {when} (참가신청 · 준비서류를 공고문에서 확인하세요).",
                check_side="company", unlock_condition=f"필수 현장설명 {when} 참석 시 가능",
                unlock_options=[f"필수 현장설명 {when} 참석 시 가능"],
            ))
    return out


def _collect_field_rules(
    raw: dict[str, Any], as_of: datetime, registration_req: Requirement | None
) -> list[EligibilityResult]:
    results: list[EligibilityResult] = [
        _rule_qualification_deadline(raw, as_of),
        _rule_bid_deadline(raw, as_of),
        _rule_region(raw),
        _rule_industry_limit(raw),
        _rule_participation_limit(raw),
        _rule_consortium_region(raw),
        _rule_budget(raw),
        _rule_business_registration(registration_req, as_of.astimezone(KST).date()),
    ]
    joint = _rule_joint_region(raw)
    if joint is not None:
        results.insert(3, joint)
    # 0921 §4-B — 있을 때만 붙이는 규칙 둘.
    # 취소는 맨 앞(가장 센 사실), 계약·낙찰 방식은 맨 뒤(판정이 아니라 정보).
    cancelled = _rule_cancelled(raw)
    if cancelled is not None:
        results.insert(0, cancelled)
    award = _rule_award(raw)
    if award is not None:
        results.append(award)
    return results


def evaluate_notice_fields(
    raw: dict[str, Any],
    *,
    as_of: datetime,
    regions: tuple[str, ...] | None = None,
    company: CompanyFacts | None = None,
    notice_id: str | None = None,
) -> list[EligibilityResult]:
    """목록 단계의 규칙 결과 — 공고 필드 + **참가자격 조항**(19차 §4-B).

    `notice_id` 를 넘기면 저장된 조항 파일과 파싱해 둔 RFP 의 자격 요구사항을 **파일로만** 읽어
    상세와 같은 줄을 만든다. 넘기지 않으면 조항을 찾을 수 없으므로 「공고문 참가자격 절」
    한 줄이 확인 필요로 남는다 — 가능으로 새지 않는다.

    목록 화면에도 「내가 이 입찰에 참가할 수 있나」를 붙이려면 판정이 필요한데,
    그 판정을 새로 지어내면 근거 없는 FAIL 이 생긴다. 그래서 상세 화면이 이미 쓰고 있는
    규칙표를 그대로 재사용한다 — 규칙표가 단일 출처다. LLM·네트워크를 타지 않으므로
    목록 100여 건에 걸어도 같은 입력이면 항상 같은 결과가 나온다.
    """
    token = _ACTIVE_REGIONS.set(regions)
    # 회사 쪽 사실(등록 업종·소재지·상한·준비 일수)도 같은 방식으로 넣는다 (0921 §4-B).
    # 넣지 않으면 전부 「미입력」으로 보고 확정하지 않는다 — 지어내지 않는다.
    company_token = _ACTIVE_COMPANY.set(company)
    try:
        registration, qual_reqs, total = _qualification_requirements(_load_parse(notice_id))
        results = _collect_notice_rules(
            raw, _as_aware(as_of), registration, notice_id=notice_id, qual_reqs=qual_reqs
        )
        overflow = _overflow_result(total)
        return results + ([overflow] if overflow else [])
    finally:
        _ACTIVE_COMPANY.reset(company_token)
        _ACTIVE_REGIONS.reset(token)


def evaluate_from_sources(
    procurement_id: str,
    *,
    notice: procurement_service.NoticeView | None,
    parse_result: RfpParseResult | None,
    as_of: datetime | None = None,
    use_llm: bool = True,
    regions: tuple[str, ...] | None = None,
    company: CompanyFacts | None = None,
    context: "AnalysisContext | None" = None,
) -> EligibilityReport:
    """이미 확보한 공고/요구사항으로 판정한다 (네트워크 접근 없음, 테스트 진입점).

    regions: 판정 중인 조직의 활동 지역(프로필). None 이면 합성 기본 프로필(레거시 진입점)로 판정한다.
    """
    if notice is None and parse_result is None:
        raise EligibilityDataError(procurement_id)

    token = _ACTIVE_REGIONS.set(regions)
    # 상세 판정도 목록과 **같은 회사 사실**을 본다 (0921 §4-B). 두 화면이 다른 답을 내면
    # 담당자가 어느 쪽을 믿어야 할지 알 수 없다.
    company_token = _ACTIVE_COMPANY.set(company)
    try:
        return _evaluate_from_sources(
            procurement_id, notice=notice, parse_result=parse_result, as_of=as_of, use_llm=use_llm, context=context
        )
    finally:
        _ACTIVE_COMPANY.reset(company_token)
        _ACTIVE_REGIONS.reset(token)


def _evaluate_from_sources(
    procurement_id: str,
    *,
    notice: procurement_service.NoticeView | None,
    parse_result: RfpParseResult | None,
    as_of: datetime | None,
    use_llm: bool,
    context: "AnalysisContext | None",
) -> EligibilityReport:
    from app.services import qualification_clause_service as _qc

    moment = _as_aware(as_of) if as_of else storage.utc_now()
    registration_req, qual_reqs, qual_total = _qualification_requirements(parse_result)
    payload = _qc.load(procurement_id) if notice is not None else None
    clauses_status = (payload or {}).get("status") or "not_fetched"

    results: list[EligibilityResult] = []
    if notice is not None:
        results.extend(
            _collect_notice_rules(
                notice.notice.raw_data, moment, registration_req, notice_id=procurement_id, qual_reqs=qual_reqs
            )
        )
    else:
        results.append(
            EligibilityResult(
                rule_id="ELIG-NOTICE-DATA",
                label="공고 원문 필드",
                status="CHECK",
                method="RULE",
                source="공고 정보를 찾지 못함",
                reason="나라장터 기본정보를 읽지 못해 지역 · 업종 · 기한 규칙을 쓰지 못했습니다. 나라장터 공고문을 직접 확인하세요.",
            )
        )
        results.append(_rule_business_registration(registration_req, moment.astimezone(KST).date()))
        # 합성 시나리오처럼 공고가 없으면 공고문도 없다 — RFP 의 자격 요구사항만 조항으로 본다.
        qual = _qualification_rows(None, None, qual_reqs, moment, review_key=procurement_id)
        results.extend(qual)

    # 공고문 조항을 읽었으면 RFP 는 두 번째 출처다 — 「RFP 파싱 후 다시 판정」을 요구하지 않는다.
    if parse_result is None and clauses_status != "ok":
        results.append(
            EligibilityResult(
                rule_id="ELIG-RFP-DATA",
                label="제안요청서 자격 조항",
                status="CHECK",
                method="RULE",
                source="정리된 요구사항 없음 (공고 분석 전)",
                reason="요구사항 정리표를 아직 만들지 않아 제안요청서의 참가자격 조항은 못 봤습니다. 정리표를 만들면 다시 판정합니다.",
            )
        )

    # RFP 의 자격 요구사항은 이제 **참가자격 조항과 같은 분류기**로 판정된다(위 QUAL-* 줄) —
    # 예전의 `_requirement_result`(늘 확인 필요)를 대신한다 (19차 §4-B).
    llm_targets: list[Requirement] = list(qual_reqs)
    overflow = _overflow_result(qual_total)
    if overflow is not None:
        results.append(overflow)

    llm_used = False
    if use_llm and llm_targets:
        llm_used = _apply_llm(results, _llm_reasons(llm_targets))

    return EligibilityReport(
        procurement_id=procurement_id,
        verdict=overall_verdict(results),
        counts=_counts(results),
        evaluated_at=moment,
        notice_available=notice is not None,
        requirements_available=parse_result is not None,
        llm_used=llm_used,
        results=results,
        organization_id=context.organization_id if context else None,
        evidence_scope=context.evidence_scope if context else None,
        regions_used=list(active_regions()),
        clause_document=((payload or {}).get("document") or {}).get("name"),
        clause_count=len((payload or {}).get("clauses") or []) if clauses_status == "ok" else 0,
        clauses_status=clauses_status,
        clause_pages=_clause_pages(payload) if clauses_status == "ok" else None,
        clause_summary=clause_summary(results),
        review=review_tally(results),
        clause_documents=_clause_documents(payload, notice.notice.raw_data if notice is not None else None),
    )


async def load_sources(
    procurement_id: str,
) -> tuple[procurement_service.NoticeView | None, RfpParseResult | None]:
    """공고와 파싱된 요구사항을 최대한 확보한다. 없으면 None (판정은 계속된다)."""
    notice: procurement_service.NoticeView | None = None
    try:
        notice = await procurement_service.get_notice(procurement_id)
    except (procurement_service.NoNoticeDataError, RuntimeError) as exc:
        logger.info("공고 조회 실패 — 공고 필드 규칙 생략: %s", exc)

    parse_result: RfpParseResult | None = None
    try:
        parse_result = rfp_parser.load_generated(procurement_id)
    except (rfp_parser.RfpNotParsedError, ValueError, OSError) as exc:
        logger.info("파싱된 요구사항 없음 — RFP 자격 조항 규칙 생략: %s", exc)

    return notice, parse_result


# 마지막 판정 결과 캐시 (GET 재조회용). 프로세스 메모리에만 둔다. 키에 조직·근거 범위를 포함한다.
_LAST_REPORTS: dict[str, EligibilityReport] = {}


def _cache_key(
    procurement_id: str, context: "AnalysisContext | None", company: CompanyFacts | None = None
) -> str:
    """조직·범위에 **회사 사실**까지 넣는다 (19차 §4-D).

    실측: 시험 계정에 업종 1468 을 적자 목록(매번 새로 판정)은 「가능」, 3단계(이 메모)는 옛
    「확인 필요 — 등록 업종 미입력」을 그대로 돌려줘 두 화면이 어긋났다. 회사자료가 바뀌면 열쇠가
    바뀌어 새로 판정한다.
    """
    base = context.cache_key(procurement_id) if context else f"legacy|{procurement_id}"
    if company is None:
        company = company_facts_for(
            context.organization_id if context else None,
            evidence_scope=context.evidence_scope if context else None,
        )
    return f"{base}|{hash(company)}"


async def evaluate(
    procurement_id: str,
    *,
    as_of: datetime | None = None,
    use_llm: bool = True,
    regions: tuple[str, ...] | None = None,
    context: "AnalysisContext | None" = None,
) -> EligibilityReport:
    notice, parse_result = await load_sources(procurement_id)
    # 회사 쪽 사실은 조직에서 읽는다 — 목록 게이트와 **같은 함수**다 (0921 §4-B).
    company = company_facts_for(
        context.organization_id if context else None,
        evidence_scope=context.evidence_scope if context else None,
    )
    call = functools.partial(
        evaluate_from_sources,
        procurement_id,
        notice=notice,
        parse_result=parse_result,
        as_of=as_of,
        use_llm=use_llm,
        regions=regions,
        company=company,
        context=context,
    )
    # AI 보강(`_llm_reasons`)은 동기 호출(Claude CLI 는 subprocess)이다 — 이벤트 루프에서 돌면 그동안 서버 전체가 멈춘다
    # (ISSUE-144). 규칙만이면 그대로 부른다.
    report = await run_in_threadpool(call) if use_llm else call()
    _LAST_REPORTS[_cache_key(procurement_id, context, company)] = report
    return report


def get_last_report(procurement_id: str, context: "AnalysisContext | None" = None) -> EligibilityReport | None:
    return _LAST_REPORTS.get(_cache_key(procurement_id, context))
