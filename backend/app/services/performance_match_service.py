"""실적 요건 자동 대조 — 공고의 실적 조건 문장 ↔ 회사 실적 원장(외부 가능 행).

입력: 실적 조건 문장(예: "최근 3년 이내 유사 용역 수행실적 1건 이상, 계약금액 5천만원 이상")
      + data/company/performance_ledger.json (scripts/import_performance_ledger.py 산출, eligible 행만 사용)
출력: 조건 해석(연수·건수·금액·분야·발주기관 유형) + 해당 실적 목록 + 충족 가능성 힌트

원칙
- 규칙만 쓴다. 조건 문장에 **명시된** 숫자만 해석하고, 없는 기준을 만들지 않는다.
- "유사"·"동종" 여부는 어휘 일치로 후보를 좁힐 뿐, 최종 판단은 사람이 한다. 결과는 PASS가 아니라 힌트다.
- 원장이 없으면 대조하지 않는다(None). 가짜 실적을 만들지 않는다.
- 금액은 원장 기준 천원 단위(계산서 명세). VAT 포함 여부 등은 원장 「증빙 기준」을 따른다.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core import storage
from app.core.paths import DATA_ROOT

LEDGER_FILE = DATA_ROOT / "company" / "performance_ledger.json"

# 실적 조건이라고 볼 문장 — 이 낱말이 없으면 대조를 시도하지 않는다.
PERFORMANCE_HINT_RE = re.compile(r"실적|수행\s*경험|납품\s*경험|용역\s*경험|계약\s*(?:건수|금액)")

_YEARS_RE = re.compile(r"최근\s*(\d{1,2})\s*(?:개\s*)?년|(\d{1,2})\s*년\s*이내|(\d{1,2})\s*개년")
_COUNT_RE = re.compile(r"(\d{1,3})\s*건\s*이상")
# 금액 조건. **여러 단위가 이어 붙은 표기**를 한 덩어리로 읽는다.
#
# 예전 정규식 `(\d[\d,]*)\s*(억|천만|…)?\s*원\s*이상` 은 숫자 하나 + 단위 하나만 봤다.
# 그래서 「3억 5천만원 이상」에서 `3억` 은 뒤에 「원 이상」이 안 붙어 실패하고,
# 그 다음 위치의 `5천만원 이상` 만 잡아 **5천만원**으로 읽었다 — 실제 기준의 1/7 이다.
# 「1억 2천만원 이상」도 2천만원(1/6)이 됐다. 실적 조건의 기준값이 조용히 틀리면
# 못 넘는 요건을 넘었다고 판정하게 되므로 가장 위험한 종류의 오류다.
#
# 단위를 하나씩 잘라 더하는 것으로도 부족하다. 「3천5백만원」은 (3천5백)×만 이지
# 3천 + 5백만 이 아니다 — 앞의 천·백은 **뒤의 만에 걸린다.** 그래서 한국어 수 표기
# 규칙(억 > 만 > 천 > 백 > 십)을 그대로 따라 읽는다.
_AMOUNT_TOKEN_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)|([억만천백십])")
# 각 조각은 «숫자» 또는 «단위» 하나다 — 「5천만」의 마지막 「만」처럼 숫자가 앞에 없는 단위도
# 삼켜야 한다. 숫자에 단위를 붙여 한 조각으로 묶으면 그 「만」을 먹지 못해 매칭이 통째로 실패한다.
# 괄호는 반복 **바깥**에 둔다. 안쪽에 두면 마지막 조각(「만」)만 잡힌다.
# 수량자에 `+` 를 붙여 **소유(possessive)** 로 만든다 — 한 번 먹은 숫자열을 되돌려주지 않는다.
#
# 예전 패턴은 숫자열을 여러 가지로 쪼개 볼 수 있었고, 뒤에 「원 이상」이 없으면 그 모든
# 분할을 시도했다. 자릿수당 약 1.6배씩 늘어 24자리에 2초, 40자리는 끝나지 않았다.
# 핸들러가 async 라 그동안 /health 를 포함한 **모든 요청이 멈춘다**. RFP 첨부의 긴 숫자열로
# 촉발될 수 있으므로 성능이 아니라 가용성 문제다.
# 되돌려줄 필요가 없는 이유: 「원」과 「이상」은 토큰 집합에 없어서, 숫자열을 짧게 잡아도
# 매칭이 성립하는 경우가 없다. (Python 3.11+ 문법)
#: 「원」과 「이상」 사이 괄호(「3천만원(VAT포함) 이상」 · 「(부가세 포함)」)도 읽는다(43차 H5 — 「금액 기준 없음 · 후보 42건」이라 했다).
_AMOUNT_RE = re.compile(r"((?:(?:\d[\d,]*+(?:\.\d+)?+|[억만천백십])\s*+)+)원\s*(?:\([^()]{0,24}\)\s*)?이상")
_KOREAN_UNIT_TO_WON = {"억": 100_000_000.0, "만": 10_000.0, "천": 1_000.0, "백": 100.0, "십": 10.0}
#: 한 건 기준 — 「단일 계약금액」 · 「건당」 · 「(단, 2.5천만원 이상의 건만 인정)」(1699556). 이것이 있으면 「누적」보다 먼저다(35차 G2B-01).
_SINGLE_RE = re.compile(r"단일\s*(?:계약|건|실적)|1\s*건당|건당|건만\s*인정|이상(?:의|인)\s*건만")
_CUMULATIVE_RE = re.compile(r"누적|합산|합계|총액")

# 조건 문장의 분야 낱말 → 원장 사업명·내용에서 찾을 어휘군
_DOMAIN_GROUPS: dict[str, tuple[str, ...]] = {
    "AI": ("AI", "인공지능", "생성형", "GPT", "에이전트", "챗봇", "프롬프트", "머신러닝", "딥러닝"),
    "교육": ("교육", "훈련", "과정", "강의", "아카데미", "캠프", "자격"),
    "데이터": ("데이터", "빅데이터", "분석", "라벨링", "시각화"),
    # 「전환 · DX」는 뺐다 — 「DX 전환교육」 같은 교육 실적이 컨설팅 실적으로 맞았다(1736492 · 35차 G2B-02)
    "컨설팅": ("컨설팅", "진단"),
    "소프트웨어": ("소프트웨어", "시스템", "플랫폼", "SaaS", "개발", "구축"),
    "ESG": ("ESG",),
}
_DOMAIN_TRIGGERS: dict[str, tuple[str, ...]] = {
    "AI": ("AI", "인공지능", "생성형", "LLM", "에이전트"),
    "교육": ("교육", "훈련", "연수", "강의", "역량", "아카데미"),
    "데이터": ("데이터", "빅데이터"),
    "컨설팅": ("컨설팅", "진단", "자문"),
    "소프트웨어": ("소프트웨어", "시스템", "플랫폼", "구축", "개발", "SaaS"),
    "ESG": ("ESG",),
}
# 발주기관 유형 낱말 → 원장 분야
_AGENCY_TYPES: dict[str, tuple[str, ...]] = {
    "대학·교육기관": ("대학", "학교", "교육기관", "산학협력단"),
    "공공·지자체": ("공공기관", "지자체", "지방자치단체", "국가기관", "공공", "관공서", "정부"),
    "기업·재직자·컨설팅": ("기업", "민간", "재직자"),
}

_UNIT_TO_THOUSAND = {"억": 100_000.0, "천만": 10_000.0, "백만": 1_000.0, "만": 10.0, "천": 1.0, None: 0.001}


class PerformanceCriteria(BaseModel):
    """조건 문장에서 읽어낸 기준. None이면 문장에 그 기준이 없다는 뜻이다."""

    years: int | None = None
    min_count: int | None = None
    # 천원 단위
    min_amount_thousand: float | None = None
    amount_mode: str | None = None  # single | cumulative | None(문장에 명시 없음 → 단일 건 기준으로 보수적 해석)
    domains: list[str] = Field(default_factory=list)
    agency_types: list[str] = Field(default_factory=list)
    similar: bool = False
    source_text: str


class LedgerHit(BaseModel):
    seq: int
    year: str
    period: str
    field: str
    title: str
    agency: str
    summary: str
    amount_thousand_krw: float | None
    amount_basis: str
    evidence_note: str
    # 어느 기준에 걸려 뽑혔는지
    matched_on: list[str] = Field(default_factory=list)


class PerformanceMatchReport(BaseModel):
    criteria: PerformanceCriteria
    ledger_available: bool
    ledger_date: str | None = None
    eligible_rows: int = Field(ge=0)
    hits: list[LedgerHit]
    hit_count: int = Field(ge=0)
    total_amount_thousand: float = 0.0
    max_amount_thousand: float | None = None
    # True: 기준을 넘는 실적이 있어 보임 · False: 원장 기준으로는 부족 · None: 문장에 판정할 기준이 없거나 원장 없음
    likely_sufficient: bool | None = None
    verdict_hint: str
    notes: list[str] = Field(default_factory=list)
    method: str = "RULE"


def load_ledger(path: Path | None = None) -> dict[str, Any] | None:
    """경로를 주면 그 원장, 아니면 레거시 위치(data/company). 조직별 원장은 load_ledger_for 를 쓴다."""
    payload = storage.read_json(path or LEDGER_FILE, default=None)
    return payload if isinstance(payload, dict) and isinstance(payload.get("rows"), list) else None


def ledger_path_for(organization_id: str) -> Path:
    """조직의 실적 원장 읽기 경로 (기본 조직은 레거시 대체 조회)."""
    from app.core import org_storage

    return org_storage.storage_for(organization_id).read_path("ledger")


def load_ledger_for(context: Any) -> dict[str, Any] | None:
    """컨텍스트의 조직 원장. public_demo·컨텍스트 없음이면 None — 실제 회사 원장을 합성 데모에 섞지 않는다."""
    if context is None or getattr(context, "evidence_scope", None) != "internal":
        return None
    return load_ledger(ledger_path_for(context.organization_id))


def eligible_rows(ledger: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not ledger:
        return []
    return [r for r in ledger.get("rows", []) if isinstance(r, dict) and r.get("eligible")]


def _to_thousand(number: str, unit: str | None) -> float:
    value = float(number.replace(",", ""))
    return value * _UNIT_TO_THOUSAND.get(unit, 0.001)


def _amount_to_thousand(chunk: str) -> float:
    """한국어 금액 표기를 천원 단위로 읽는다.

    억·만은 앞에 쌓인 값 전체에 걸리고(「3천5백만」 = 3500 × 만), 천·백·십은 그 자리에서 더한다.
    단위만 있고 숫자가 없으면 1로 본다 (「만원」 = 10,000원).
    """
    won = 0.0
    section = 0.0  # 만·억이 아직 안 걸린 누적분
    pending = 0.0  # 방금 읽은 숫자
    for number, unit in _AMOUNT_TOKEN_RE.findall(chunk):
        if number:
            pending = float(number.replace(",", ""))
            continue
        if unit in ("억", "만"):
            value = section + pending
            won += (value or 1.0) * _KOREAN_UNIT_TO_WON[unit]
            section = 0.0
        else:  # 천·백·십 — 뒤의 만·억에 걸릴 수 있으므로 section 에 쌓아 둔다
            section += (pending or 1.0) * _KOREAN_UNIT_TO_WON[unit]
        pending = 0.0
    return (won + section + pending) / 1000.0


def parse_criteria(text: str) -> PerformanceCriteria:
    compact = " ".join(text.split())
    years = None
    m = _YEARS_RE.search(compact)
    if m:
        years = int(next(g for g in m.groups() if g))
    count = None
    m = _COUNT_RE.search(compact)
    if m:
        count = int(m.group(1))
    amount = None
    m = _AMOUNT_RE.search(compact)
    if m:
        amount = _amount_to_thousand(m.group(1))
    mode = None
    if amount is not None:
        # 금액 숫자에 가까운 낱말로 정한다 — 「단일 계약금액 2,500만원 이상 3건 이거나 **누적** 수료 인원 100명」(1751800)의 「누적」은
        # 금액이 아니라 인원에 걸린다. 한 건 기준 낱말이 있으면 그것이 먼저 이긴다(35차 G2B-01).
        near = compact[max(0, m.start() - 15): m.end() + 8]
        if _SINGLE_RE.search(compact):
            mode = "single"
        elif _CUMULATIVE_RE.search(near):
            mode = "cumulative"
    domains = [d for d, triggers in _DOMAIN_TRIGGERS.items() if any(t.lower() in compact.lower() for t in triggers)]
    agency_types = [a for a, triggers in _AGENCY_TYPES.items() if any(t in compact for t in triggers)]
    return PerformanceCriteria(
        years=years,
        min_count=count,
        min_amount_thousand=amount,
        amount_mode=mode,
        domains=domains,
        agency_types=agency_types,
        similar=bool(re.search(r"유사|동종|동일|준하는", compact)),
        source_text=text.strip(),
    )


def _row_year(row: dict[str, Any]) -> int | None:
    numbers = re.findall(r"20\d{2}", str(row.get("year") or "") + " " + str(row.get("period") or ""))
    return max(int(n) for n in numbers) if numbers else None


#: 실적 내용 속 기관 이름 — 「가상여성인력개발센터」의 「개발」이 소프트웨어 분야로 걸렸다(43차 H3 · 1780566).
_ORG_NAME_RE = re.compile(
    r"[가-힣A-Za-z0-9·]{2,30}?(?:센터|재단|진흥원|협회|공단|공사|대학교|대학|학교|연구원|위원회|교육청|사업단|협의회|조합|산학협력단)(?![가-힣])"
)


def work_text(title: str, summary: str) -> str:
    """분야 대조에 쓰는 글 — 실적 **제목과 사업 내용**만, 기관 이름 조각은 뺀다(발주기관 칸도 넣지 않는다 · 43차 H3)."""
    return f"{_ORG_NAME_RE.sub(' ', title or '')} {_ORG_NAME_RE.sub(' ', summary or '')}"


def _row_text(row: dict[str, Any]) -> str:
    # 분야(field)는 발주기관 유형 기준으로 따로 쓴다. 어휘 대조에 넣으면 "지원사업·기관자격"의 '자격'이 교육 실적처럼 잡힌다.
    return work_text(str(row.get("title") or ""), str(row.get("summary") or ""))


def match_rows(criteria: PerformanceCriteria, rows: list[dict[str, Any]], *, as_of: date | None = None) -> list[LedgerHit]:
    today = as_of or storage.kst_today()
    hits: list[LedgerHit] = []
    for row in rows:
        matched: list[str] = []
        year = _row_year(row)
        if criteria.years is not None:
            if year is None or year < today.year - criteria.years:
                continue
            matched.append(f"최근 {criteria.years}년")
        text = _row_text(row)
        if criteria.domains:
            if not any(any(w.lower() in text.lower() for w in _DOMAIN_GROUPS[d]) for d in criteria.domains):
                continue
            matched.append("분야 어휘 " + "·".join(criteria.domains))
        if criteria.agency_types:
            if str(row.get("field")) not in criteria.agency_types:
                continue
            matched.append("발주기관 유형 " + str(row.get("field")))
        amount = row.get("amount_thousand_krw")
        if criteria.min_amount_thousand is not None and criteria.amount_mode != "cumulative":
            if not isinstance(amount, (int, float)) or amount < criteria.min_amount_thousand:
                continue
            matched.append(f"금액 ≥ {criteria.min_amount_thousand:,.0f}천원")
        hits.append(
            LedgerHit(
                seq=int(row.get("seq") or 0),
                year=str(row.get("year") or ""),
                period=str(row.get("period") or ""),
                field=str(row.get("field") or ""),
                title=str(row.get("title") or ""),
                agency=str(row.get("agency") or ""),
                summary=str(row.get("summary") or ""),
                amount_thousand_krw=float(amount) if isinstance(amount, (int, float)) else None,
                amount_basis=str(row.get("amount_basis") or ""),
                evidence_note=str(row.get("evidence_note") or ""),
                matched_on=matched,
            )
        )
    hits.sort(key=lambda h: (-(_row_year({"year": h.year, "period": h.period}) or 0), -(h.amount_thousand_krw or 0)))
    return hits


def build_report(text: str, *, ledger: dict[str, Any] | None = None, as_of: date | None = None) -> PerformanceMatchReport:
    criteria = parse_criteria(text)
    ledger = ledger if ledger is not None else load_ledger()
    rows = eligible_rows(ledger)
    notes: list[str] = []
    if not rows:
        return PerformanceMatchReport(
            criteria=criteria,
            ledger_available=False,
            eligible_rows=0,
            hits=[],
            hit_count=0,
            likely_sufficient=None,
            verdict_hint="실적 목록이 없어 견주지 못했습니다 — 회사자료 화면에서 실적 목록(엑셀)을 올리면 견줘 봅니다.",
            notes=["실적 목록 없음"],
        )
    hits = match_rows(criteria, rows, as_of=as_of)
    total = sum(h.amount_thousand_krw or 0 for h in hits)
    max_amount = max((h.amount_thousand_krw for h in hits if h.amount_thousand_krw is not None), default=None)

    if criteria.similar:
        notes.append("「유사 · 동종」은 낱말이 맞는 실적으로 후보를 좁힌 것입니다 — 인정 범위는 공고문 기준으로 담당자가 정합니다.")
    if criteria.min_amount_thousand is not None and criteria.amount_mode is None:
        notes.append("금액 기준이 한 건 기준인지 합계 기준인지 문장에 없어 더 엄격한 한 건 기준으로 봤습니다.")
    if not criteria.domains and not criteria.agency_types:
        notes.append("분야 · 발주기관 종류 낱말이 없어 실적 목록의 채택 실적을 모두 후보로 두었습니다.")
    missing_amount = [h for h in hits if h.amount_thousand_krw is None]
    if missing_amount and criteria.min_amount_thousand is not None:
        notes.append(f"금액이 없는 실적 {len(missing_amount)}건은 금액 기준에서 뺐습니다.")

    judgeable = criteria.min_count is not None or criteria.min_amount_thousand is not None or criteria.years is not None
    likely: bool | None
    if not judgeable:
        likely = None
        hint = f"문장에 건수 · 금액 · 기간 기준이 없어 충족 여부는 판정하지 않습니다 — 관련 실적 후보 {len(hits)}건."
    else:
        need_count = criteria.min_count or 1
        count_ok = len(hits) >= need_count
        amount_ok = True
        if criteria.min_amount_thousand is not None:
            if criteria.amount_mode == "cumulative":
                amount_ok = total >= criteria.min_amount_thousand
            else:
                amount_ok = max_amount is not None and max_amount >= criteria.min_amount_thousand
        likely = count_ok and amount_ok
        if likely:
            hint = f"실적 목록 기준으로 조건을 넘는 실적이 {len(hits)}건 있어 보입니다(합계 {total:,.0f}천원) — 증빙(계약서 · 계산서 · 완료확인서)을 맞춰 본 뒤 담당자가 확정합니다."
        elif not count_ok:
            hint = f"실적 목록에서 기준에 맞는 실적이 {len(hits)}건으로 필요 건수 {need_count}건에 못 미칩니다 — 인정 범위를 넓게 볼 수 있는지 담당자가 확인하세요."
        else:
            hint = f"건수는 맞지만 금액 기준({criteria.min_amount_thousand:,.0f}천원)을 넘는 실적이 없습니다."
    return PerformanceMatchReport(
        criteria=criteria,
        ledger_available=True,
        ledger_date=str(ledger.get("ledger_date") or "") if ledger else None,
        eligible_rows=len(rows),
        hits=hits[:20],
        hit_count=len(hits),
        total_amount_thousand=round(total, 1),
        max_amount_thousand=max_amount,
        likely_sufficient=likely,
        verdict_hint=hint,
        notes=notes,
    )


def is_performance_text(text: str) -> bool:
    return bool(PERFORMANCE_HINT_RE.search(text))


def project_rows(ledger: dict[str, Any] | None) -> list[dict[str, Any]]:
    """수행실적표에 실을 행 — 인증·지정·설립이 아닌 실제 교육·컨설팅·사업 수행 실적만."""
    return [r for r in eligible_rows(ledger) if str(r.get("field")) in ("대학·교육기관", "공공·지자체", "기업·재직자·컨설팅")]
