"""개발 수행역량 판정 — 「이 공고를 우리 개발진이 할 수 있나」.

## 왜 필요한가

지금 파이프라인은 공고를 «교육·컨설팅 관점»으로만 본다. 그래서 실측(2026-09-10, 스냅샷 34건)에서
이런 일이 벌어진다.

    A 0.787  2026년 생성형AI 교육을 위한 **구독권(Google AI Pro) 및 기념품 제공**  ← 물품 구매인데 최우선
    A 0.853  AI기반 취약점 점검 소프트웨어 **도입** 사업                          ← 제품 도입인데 최우선
    A 0.853  미래 AI반도체 기술개발 로드맵 수립 **연구**                            ← 정책연구인데 최우선
    D 0.410  AI 활용 빌라시세 자동추정모델 **개발** 사업 (out_of_scope)            ← 진짜 개발인데 후순위

즉 등급은 «AI 라는 낱말이 있는가»는 보지만 «무슨 일을 시키는가»는 보지 않는다.
그리고 「마운트 에이전트 개발을 위한 DB 구축 용역」처럼 낱말이 통째로 다른 뜻인 경우도 있다 —
과업지시서를 읽어 보면 방진 마운트의 **제조장치 설계와 특성시험**이고 소프트웨어가 아니다.

## 규율

1. **양면 근거.** `supported`·`gap` 은 공고 쪽 근거 문장과 회사 쪽 사실이 **둘 다** 있을 때만 낸다.
   한쪽이라도 없으면 `unknown` 이다.
2. **부재는 부정이 아니다.** 회사자료에 적혀 있지 않은 기술은 «모른다»이지 «못 한다»가 아니다.
   그래서 unknown 사유에는 「못 한다·미보유·역량 없음·불가」 같은 말을 쓰지 않는다
   (테스트가 이 문구들을 막는다).
3. **상태를 바꾸지 않는다.** GO 를 막지 않고 자격판정·추천등급을 덮어쓰지 않는다.
4. **회사가 정할 값은 회사가 정한다.** 예산 상한이 비어 있으면 규모를 판정하지 않는다 —
   코드 상수로 대신 채우지 않는다.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Final, Iterable

from app.core.money import won, won_pair
from app.schemas.capability import (
    WORK_KIND_LABELS,
    CapabilityEvidence,
    CapabilityFinding,
    CapabilityReport,
    WorkKind,
)
from app.schemas.delivery_capacity import DeliveryCapacity
from app.schemas.procurement import ProcurementNotice
from app.services import delivery_capacity_service, eligibility_engine
from app.services.work_kinds import (
    NOT_OUR_ROLE as _NOT_OUR_ROLE,
    WORK_KIND_RULES as _WORK_KIND_RULES,
    detect_work_kinds,
    work_tracks,
)

KST = timezone.utc

# ---------------------------------------------------------------------------
# UNKNOWN 문구 — 부재가 부정으로 미끄러지는 것을 막는 고정 표현
# ---------------------------------------------------------------------------
# 「기록이 없다」와 「할 수 없다」는 완전히 다른 말이다. 사유 문장을 자유롭게 쓰게 두면
# 어느 순간 「미보유」로 새어 나가고, 화면을 본 담당자는 회사가 못 한다고 읽는다.
UNKNOWN_SKILL_NOTE: Final[str] = (
    "회사 역량자료에 이 기술에 대한 기록이 없습니다. 보유 여부가 확인되지 않았다는 뜻이며, "
    "수행할 수 없다는 뜻이 아닙니다."
)
UNKNOWN_QUAL_NOTE: Final[str] = (
    "이 자격의 보유 여부가 회사자료에 기록돼 있지 않습니다. 확인이 필요합니다."
)
UNKNOWN_SCALE_NOTE: Final[str] = (
    "혼자 맡을 수 있는 최대 사업비가 회사자료에 적혀 있지 않아 규모를 판정하지 않았습니다."
)
UNKNOWN_CAPACITY_NOTE: Final[str] = (
    "회사 개발역량 자료가 아직 등록되지 않아 판정할 근거가 없습니다."
)

# 사유 문장에 절대 나오면 안 되는 말 (테스트가 확인한다).
FORBIDDEN_IN_UNKNOWN: Final[tuple[str, ...]] = (
    "못 한다",
    "못한다",
    "미보유",
    "역량 없음",
    "수행 불가",
    "불가능",
)

# ---------------------------------------------------------------------------
# 소프트웨어인가 — 「마운트 에이전트」 같은 낱말 겹침을 걸러낸다
# ---------------------------------------------------------------------------
# 「에이전트」·「개발」·「DB」가 다 들어 있어도 실제로는 방진 마운트의 제조장치 설계와
# 특성시험인 공고가 있었다(한국기계연구원, 2026-09). 제목만으로는 구분할 수 없고
# 과업 어휘의 «무게»를 봐야 한다.
_SOFTWARE_TERMS: Final[re.Pattern[str]] = re.compile(
    r"소프트웨어|시스템\s*구축|서버|데이터베이스|(?<![A-Za-z])DB(?![A-Za-z])|(?<![A-Za-z])API(?![A-Za-z])"
    r"|웹|모바일|애플리케이션|앱|화면|사용자\s*인터페이스|(?<![A-Za-z])UI(?![A-Za-z])|(?<![A-Za-z])UX(?![A-Za-z])"
    r"|로그인|인증|배포|소스\s*코드|소스코드|형상관리|테스트\s*케이스|알고리즘|모델\s*학습|학습\s*데이터"
    r"|프로그램\s*개발|전산|정보화|클라우드|서비스\s*개발",
    re.IGNORECASE,
)
_NON_SOFTWARE_TERMS: Final[re.Pattern[str]] = re.compile(
    # 기계·재료
    r"하중|강성|변위|치구|제조\s*장치|제조장치|공차|재질|열처리|방진|진동|소음|유량|압력"
    r"|시험\s*장비|시험장비|시편|절삭|용접|금형|도면\s*작성"
    # 토목·건축·전기
    r"|측량|배수|포장\s*공사|수배전|접지|구조\s*안전|지반"
    # 화학·환경·생물
    r"|시료|폐기물|수질|대기\s*오염|배양|시약"
)

# ---------------------------------------------------------------------------
# 인원 요구 — 「N명 이상」
# ---------------------------------------------------------------------------
# 앵커 없이 `(\d+)\s*명\s*이상` 을 찾으면 「심사위원 8명 이상 구성」·「참석 인원 25명 이상」까지
# 요구 투입 인력으로 읽는다(실측: 파싱된 요구사항 805건에서 확인). 그래서 인력 맥락을 붙인다.
_STAFFING_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:투입|참여|전담|배치|보유|참여\s*기술|사업\s*수행)\s*(?:인력|기술자|인원|개발자)?[^.\n]{0,24}?"
    r"(\d{1,2})\s*(?:명|인)\s*이상"
    r"|(\d{1,2})\s*(?:명|인)\s*이상[^.\n]{0,16}?(?:투입|참여|배치|보유|상주)"
    # 「전담 PM 또는 기술담당자 1인을 지정하여야 하며」 — 이상 없이 **정확한 수**를 지정하는 형태.
    # 실측: 마운트 과업지시서 8-라. 이 문장을 놓치면 전담 인력 요구가 통째로 안 보인다.
    r"|(?:전담|상주|상근)[^.\n]{0,24}?(\d{1,2})\s*(?:명|인)\s*(?:을|를)?\s*(?:지정|배치|투입)"
)
# 인력 요구가 아닌 «N명». 이 말이 같은 문장에 있으면 인원 요구로 읽지 않는다.
_STAFFING_EXCLUDE_RE: Final[re.Pattern[str]] = re.compile(
    r"심사|평가위원|위원회|수강|교육생|참석|참가자|관람|모집\s*인원|정원"
)
# 「전담·상주·상근」이면 그 인력이 다른 사업에 함께 못 들어간다 — 한 단계 낮춰 본다.
_DEDICATED_RE: Final[re.Pattern[str]] = re.compile(r"전담|상주|상근")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _count(pattern: re.Pattern[str], text: str) -> int:
    return len(pattern.findall(text))


def software_balance(text: str) -> tuple[int, int]:
    """(소프트웨어 어휘 수, 비소프트웨어 어휘 수)."""
    return _count(_SOFTWARE_TERMS, text), _count(_NON_SOFTWARE_TERMS, text)


def required_headcount(text: str) -> tuple[int, str] | None:
    """요구 투입 인원과 그 근거 문장. 인력 맥락이 아니면 None."""
    for line in re.split(r"[\n。]|(?<=다\.)", text):
        if not line.strip() or _STAFFING_EXCLUDE_RE.search(line):
            continue
        found = _STAFFING_RE.search(line)
        if not found:
            continue
        raw = found.group(1) or found.group(2) or found.group(3)
        if not raw:
            continue
        return int(raw), line.strip()[:400]
    return None


def _quote_for(text: str, pattern: re.Pattern[str], *, width: int = 160) -> str | None:
    """패턴이 걸린 자리 **주변**을 인용한다. 문서 머리말을 인용하면 근거가 되지 않는다."""
    found = pattern.search(text)
    if not found:
        return None
    start = max(0, found.start() - width // 2)
    end = min(len(text), found.end() + width // 2)
    snippet = text[start:end].strip().replace("\n", " ")
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def _skill_finding(
    entry_name: str,
    capacity: DeliveryCapacity,
    text: str,
    pattern: re.Pattern[str],
    where: str,
    *,
    domain_uncertain: bool = False,
) -> CapabilityFinding | None:
    """공고에 등장한 기술 하나에 대한 판정. 등장하지 않으면 None(항목을 만들지 않는다).

    `domain_uncertain` 은 이 공고가 소프트웨어 사업이 아닐 수 있다는 뜻이다. 그때는
    낱말이 걸려도 **보유로 판정하지 않는다** — 실측 사례: 「마운트 에이전트 개발을 위한 DB 구축」의
    «에이전트»는 AI 에이전트가 아니라 방진 마운트 제품의 이름이었다.
    낱말이 같다고 같은 기술이라고 말하는 것이 이 화면이 낼 수 있는 가장 나쁜 거짓말이다.
    """
    quote = _quote_for(text, pattern)
    if quote is None:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", entry_name.lower()).strip("-")[:24] or "skill"
    finding_id = f"CAP-SKILL-{slug}"
    label = f"요구 기술 · {entry_name}"
    held = capacity.skill(entry_name)

    if held is None:
        return CapabilityFinding(
            finding_id=finding_id,
            label=label,
            status="unknown",
            reason=f"공고가 「{entry_name}」을(를) 요구합니다. {UNKNOWN_SKILL_NOTE}",
            evidence=CapabilityEvidence(notice_quote=quote, notice_where=where),
            next_action=f"회사 역량자료에 「{entry_name}」 보유 여부를 기록하세요.",
        )
    if held.level == "none":
        return CapabilityFinding(
            finding_id=finding_id,
            label=label,
            status="gap",
            reason=(
                f"공고가 「{entry_name}」을(를) 요구하는데, 회사자료에 보유하지 않는다고 "
                f"기록돼 있습니다."
            ),
            evidence=CapabilityEvidence(
                notice_quote=quote,
                notice_where=where,
                company_fact=held.note or f"「{entry_name}」 미보유로 기록됨",
                company_where=f"회사 수행역량 자료 · {held.source}",
            ),
            next_action="외주·컨소시엄으로 보완할 수 있는지 검토하세요.",
        )
    if domain_uncertain:
        return CapabilityFinding(
            finding_id=finding_id,
            label=label,
            status="unknown",
            reason=(
                f"공고에 「{entry_name}」과 같은 낱말이 나오지만, 이 사업은 소프트웨어 분야가 "
                "아닐 수 있어 같은 기술을 뜻하는지 확인되지 않았습니다. 원문을 직접 보세요."
            ),
            evidence=CapabilityEvidence(
                notice_quote=quote,
                notice_where=where,
                company_fact=held.note or f"「{entry_name}」 수행 경험 있음",
                company_where=f"회사 수행역량 자료 · {held.source}",
            ),
            next_action="과업 원문에서 이 낱말이 무엇을 가리키는지 확인하세요.",
        )
    return CapabilityFinding(
        finding_id=finding_id,
        label=label,
        status="supported",
        reason=f"공고가 요구하는 「{entry_name}」은(는) 개발진이 수행해 본 영역으로 기록돼 있습니다.",
        evidence=CapabilityEvidence(
            notice_quote=quote,
            notice_where=where,
            company_fact=held.note or f"「{entry_name}」 수행 경험 있음",
            company_where=f"회사 수행역량 자료 · {held.source}",
        ),
    )


def _skill_patterns(capacity: DeliveryCapacity) -> Iterable[tuple[str, re.Pattern[str]]]:
    """회사가 기록한 기술마다 «공고에서 이 말을 찾는» 패턴을 만든다 (이름 + 별칭)."""
    for entry in capacity.skills:
        words = [entry.name, *entry.aliases]
        alternatives = "|".join(re.escape(w) for w in words if w.strip())
        if not alternatives:
            continue
        yield entry.name, re.compile(alternatives, re.IGNORECASE)


def evaluate(
    notice: ProcurementNotice,
    *,
    organization_id: str,
    requirement_text: str = "",
    requirement_where: str = "과업 원문",
    now: datetime | None = None,
) -> CapabilityReport:
    """공고 하나의 개발 수행역량을 판정한다.

    `requirement_text` 는 파싱된 요구사항(과업지시서·제안요청서) 본문이다. 비어 있으면
    공고명·요약만 보고 판정하며, 그 사실을 `used_requirements=False` 로 남긴다 —
    제목만으로 「소프트웨어가 아니다」를 단정하지 않기 위해서다.
    """
    moment = now or _now()
    capacity = delivery_capacity_service.load(organization_id)

    head = " ".join(filter(None, [notice.title, notice.description or ""]))
    full = f"{head}\n{requirement_text}".strip()
    used_requirements = bool(requirement_text.strip())
    where = requirement_where if used_requirements else "공고명·요약"

    findings: list[CapabilityFinding] = []
    kinds = detect_work_kinds(full)
    # 목록 화면의 갈래와 **같은 규칙**을 쓴다. 여기서 따로 계산하면 목록이 「개발」이라 부른 것을
    # 상세가 「감리」라 부르는 모순이 생긴다.
    is_development = "development" in work_tracks(kinds)

    findings.append(_work_kind_finding(kinds, full))
    software_finding = _software_finding(full, kinds, used_requirements, where)
    if software_finding is not None:
        findings.append(software_finding)

    if not capacity.recorded:
        findings.append(
            CapabilityFinding(
                finding_id="CAP-CAPACITY",
                label="회사 개발역량 자료",
                status="unknown",
                reason=UNKNOWN_CAPACITY_NOTE,
                next_action="회사자료에 개발 인원·보유 기술을 등록하면 이 화면이 판정을 시작합니다.",
            )
        )
    else:
        # 분야가 의심스러우면(소프트웨어가 아닐 수 있거나, 애초에 우리 역할이 아니면)
        # 낱말이 걸려도 «보유»로 판정하지 않는다.
        domain_uncertain = (software_finding is not None and software_finding.status != "supported") or bool(
            [k for k in kinds if k in _NOT_OUR_ROLE]
        )
        for name, pattern in _skill_patterns(capacity):
            found = _skill_finding(
                name, capacity, full, pattern, where, domain_uncertain=domain_uncertain
            )
            if found is not None:
                findings.append(found)
        findings.append(_staffing_finding(capacity, full, where))
        findings.append(_scale_finding(capacity, notice))

    schedule = _schedule_finding(notice, moment)
    if schedule is not None:
        findings.append(schedule)

    counts: dict[str, int] = {"supported": 0, "gap": 0, "unknown": 0, "info": 0}
    for item in findings:
        counts[item.status] = counts.get(item.status, 0) + 1

    return CapabilityReport(
        procurement_id=notice.id,
        organization_id=organization_id,
        work_kinds=kinds,
        is_development=is_development,
        findings=findings,
        capacity_recorded=capacity.recorded,
        used_requirements=used_requirements,
        counts=counts,
        headline=_headline(kinds, counts, capacity, used_requirements),
        evaluated_at=moment,
    )


def _work_kind_finding(kinds: list[WorkKind], text: str) -> CapabilityFinding:
    if not kinds:
        return CapabilityFinding(
            finding_id="CAP-WORKKIND",
            label="일의 종류",
            status="unknown",
            reason="공고 문구에서 사업 유형을 가려낼 근거를 찾지 못했습니다. 과업 원문을 확인하세요.",
            next_action="「분석 실행」으로 과업지시서를 파싱하면 다시 판정합니다.",
        )

    labels = " · ".join(WORK_KIND_LABELS[k] for k in kinds)
    blocked = [k for k in kinds if k in _NOT_OUR_ROLE]
    if blocked:
        first = blocked[0]
        pattern = dict(_WORK_KIND_RULES)[first]
        return CapabilityFinding(
            finding_id="CAP-WORKKIND",
            label="일의 종류",
            status="gap",
            reason=f"이 공고는 「{labels}」로 읽힙니다. {_NOT_OUR_ROLE[first]}",
            evidence=CapabilityEvidence(
                notice_quote=_quote_for(text, pattern),
                notice_where="공고 원문",
            ),
            next_action="개발 수행 사업이 맞는지 과업 원문에서 확인하세요.",
        )
    # 일의 종류는 **공고 쪽 사실만으로** 읽는 항목이라 `supported` 를 쓰지 않는다.
    # `supported` 는 「공고 요구 ↔ 회사 사실」이 둘 다 있을 때만 쓰는 값이다.
    return CapabilityFinding(
        finding_id="CAP-WORKKIND",
        label="일의 종류",
        status="info",
        reason=f"이 공고는 「{labels}」로 읽힙니다.",
        evidence=CapabilityEvidence(
            notice_quote=_quote_for(text, dict(_WORK_KIND_RULES)[kinds[0]]),
            notice_where="공고 원문",
        ),
    )


def _software_finding(
    text: str, kinds: list[WorkKind], used_requirements: bool, where: str
) -> CapabilityFinding | None:
    """소프트웨어 개발이 맞는지. 개발로 읽힐 때만 따진다."""
    if "development" not in kinds:
        return None
    sw, non_sw = software_balance(text)
    if not used_requirements:
        # 제목·요약만으로는 분야를 단정하지 않는다. 「마운트 에이전트」는 제목이 소프트웨어처럼 보인다.
        return CapabilityFinding(
            finding_id="CAP-DOMAIN",
            label="소프트웨어 개발 여부",
            status="unknown",
            reason=(
                "공고명·요약만으로는 소프트웨어 개발인지 가릴 수 없습니다. "
                "낱말이 같아도 분야가 다른 사업이 있습니다."
            ),
            next_action="「분석 실행」으로 과업지시서를 파싱한 뒤 다시 확인하세요.",
        )
    if non_sw >= 3 and non_sw >= sw:
        return CapabilityFinding(
            finding_id="CAP-DOMAIN",
            label="소프트웨어 개발 여부",
            status="gap",
            reason=(
                f"과업 원문에 소프트웨어 어휘({sw}회)보다 다른 분야 어휘({non_sw}회)가 더 많습니다. "
                "이름은 개발이지만 소프트웨어 사업이 아닐 수 있습니다."
            ),
            evidence=CapabilityEvidence(
                notice_quote=_quote_for(text, _NON_SOFTWARE_TERMS),
                notice_where=where,
            ),
            next_action="과업 원문에서 실제 산출물이 무엇인지 확인하세요.",
        )
    return CapabilityFinding(
        finding_id="CAP-DOMAIN",
        label="소프트웨어 개발 여부",
        status="supported",
        reason=f"과업 원문의 어휘가 소프트웨어 개발 쪽입니다 (소프트웨어 {sw}회 · 타 분야 {non_sw}회).",
        evidence=CapabilityEvidence(
            notice_quote=_quote_for(text, _SOFTWARE_TERMS),
            notice_where=where,
        ),
    )


def _staffing_finding(capacity: DeliveryCapacity, text: str, where: str) -> CapabilityFinding:
    need = required_headcount(text)
    have = capacity.developer_count

    if need is None:
        return CapabilityFinding(
            finding_id="CAP-STAFFING",
            label="투입 인력",
            status="unknown",
            reason="공고 원문에서 요구 투입 인원을 찾지 못했습니다. 요구가 없는 것인지 확인하세요.",
            evidence=CapabilityEvidence(
                company_fact=None if have is None else f"개발 인원 {have}명",
                company_where=None if have is None else "회사 수행역량 자료",
            ),
        )
    count, quote = need
    if have is None:
        return CapabilityFinding(
            finding_id="CAP-STAFFING",
            label="투입 인력",
            status="unknown",
            reason=f"공고가 {count}명 이상을 요구합니다. 회사 개발 인원이 회사자료에 기록돼 있지 않습니다.",
            evidence=CapabilityEvidence(notice_quote=quote, notice_where=where),
            next_action="회사자료에 개발 인원을 기록하세요.",
        )
    if count > have:
        return CapabilityFinding(
            finding_id="CAP-STAFFING",
            label="투입 인력",
            status="gap",
            reason=f"공고가 {count}명 이상을 요구하는데 기록된 개발 인원은 {have}명입니다.",
            evidence=CapabilityEvidence(
                notice_quote=quote,
                notice_where=where,
                company_fact=f"개발 인원 {have}명",
                company_where="회사 수행역량 자료",
            ),
            next_action="공동수급·외주로 인원을 채울 수 있는지 검토하세요.",
        )
    if _DEDICATED_RE.search(quote):
        return CapabilityFinding(
            finding_id="CAP-STAFFING",
            label="투입 인력",
            status="unknown",
            reason=(
                f"공고가 {count}명 이상을 요구하고 기록된 개발 인원은 {have}명입니다. "
                "다만 전담·상주 조건이 있어 그 인원이 다른 사업에 함께 투입될 수 없습니다. "
                "동시 수행 여부는 확인되지 않았습니다."
            ),
            evidence=CapabilityEvidence(
                notice_quote=quote,
                notice_where=where,
                company_fact=f"개발 인원 {have}명",
                company_where="회사 수행역량 자료",
            ),
            next_action="같은 기간에 진행 중인 다른 사업이 있는지 확인하세요.",
        )
    return CapabilityFinding(
        finding_id="CAP-STAFFING",
        label="투입 인력",
        status="supported",
        reason=f"공고가 {count}명 이상을 요구하고 기록된 개발 인원은 {have}명입니다.",
        evidence=CapabilityEvidence(
            notice_quote=quote,
            notice_where=where,
            company_fact=f"개발 인원 {have}명",
            company_where="회사 수행역량 자료",
        ),
    )


def _scale_finding(capacity: DeliveryCapacity, notice: ProcurementNotice) -> CapabilityFinding:
    ceiling = capacity.budget_ceiling_krw
    if ceiling is None:
        return CapabilityFinding(
            finding_id="CAP-SCALE",
            label="사업 규모",
            status="unknown",
            reason=UNKNOWN_SCALE_NOTE,
            next_action="회사자료에 혼자 맡을 수 있는 최대 사업비를 적어 주세요.",
        )
    if notice.budget is None:
        return CapabilityFinding(
            finding_id="CAP-SCALE",
            label="사업 규모",
            status="unknown",
            reason="공고에 예산이 공개되지 않아 규모를 판정하지 않았습니다.",
        )
    if notice.budget > ceiling:
        # 다음 할 일은 공동수급 방식대로 — 불허인데 「공동수급을 검토하세요」라고 하지 않는다(33차 §3-B-4).
        joint = eligibility_engine.joint_allowed(notice.raw_data if isinstance(notice.raw_data, dict) else {})
        partner = capacity.joint_bid_partner is not None and capacity.joint_bid_partner.available
        if joint and partner:
            # 판정 줄(사업 규모)과 같은 말 — 파트너를 「있음」으로 적었으면 구할지가 아니라 나눌지다(34차 R33-S1 · 마지막 검토)
            next_action = "함께 참가할 회사를 확보해 두었습니다 — 나눠 맡을지 정하세요."
        elif joint:
            next_action = "다른 회사와 함께 참가(공동수급)할 수 있습니다 — 함께할 회사를 구할지 정하세요."
        elif joint is False:
            next_action = "다른 회사와 함께 참가할 수 없는 공고입니다(공동수급 불허) — 혼자 맡을지 정하세요."
        else:
            next_action = "다른 회사와 함께 참가할 수 있는지 공고문에서 공동수급 방식을 확인하세요."
        budget_text, ceiling_text = won_pair(notice.budget, ceiling)  # 반올림하면 같아지는 금액은 정확히(34차 R33-04)
        return CapabilityFinding(
            finding_id="CAP-SCALE",
            label="사업 규모",
            status="gap",
            reason=(
                f"예산 {budget_text}이 회사가 적은 최대 사업비 {ceiling_text}보다 큽니다."
            ),
            evidence=CapabilityEvidence(
                notice_quote=f"예산 {budget_text}",
                notice_where="공고 필드: 예산",
                company_fact=f"혼자 맡을 수 있는 최대 사업비 {ceiling_text}",
                company_where="회사 수행역량 자료",
            ),
            next_action=next_action,
        )
    budget_text, ceiling_text = won_pair(notice.budget, ceiling)  # 반올림하면 같아지는 금액은 정확히(35차 G2B-04)
    return CapabilityFinding(
        finding_id="CAP-SCALE",
        label="사업 규모",
        status="supported",
        reason=f"예산 {budget_text}이 회사가 적은 최대 사업비 {ceiling_text} 안입니다.",
        evidence=CapabilityEvidence(
            notice_quote=f"예산 {budget_text}",
            notice_where="공고 필드: 예산",
            company_fact=f"혼자 맡을 수 있는 최대 사업비 {ceiling_text}",
            company_where="회사 수행역량 자료",
        ),
    )


def _schedule_finding(notice: ProcurementNotice, now: datetime) -> CapabilityFinding | None:
    """참가자격 등록 마감. 판정하지 않고 공고 필드를 그대로 옮긴다 — 놓치면 입찰 자체가 불가능하다."""
    raw = notice.raw_data or {}
    value = raw.get("qualification_deadline")
    if not value:
        return None
    return CapabilityFinding(
        finding_id="CAP-SCHEDULE",
        label="참가자격 등록 마감",
        status="info",
        reason=(
            f"참가자격 등록 마감이 {value} 입니다. 입찰 마감과 별개이며, "
            "이 시각을 넘기면 입찰에 참여할 수 없습니다."
        ),
        evidence=CapabilityEvidence(
            notice_quote=str(value),
            notice_where="공고 필드: 참가자격 등록 마감",
        ),
        next_action="나라장터 입찰참가자격 등록 상태를 확인하세요.",
    )


def _headline(
    kinds: list[WorkKind],
    counts: dict[str, int],
    capacity: DeliveryCapacity,
    used_requirements: bool,
) -> str:
    if not capacity.recorded:
        return "회사 개발역량 자료가 없어 판정하지 못했습니다."
    blocked = [k for k in kinds if k in _NOT_OUR_ROLE]
    if blocked:
        return f"「{WORK_KIND_LABELS[blocked[0]]}」 사업으로 보입니다 — 개발 수행 사업인지 먼저 확인하세요."
    if "development" not in kinds:
        return "개발 사업으로 읽히지 않습니다."
    parts = [f"확인된 항목 {counts.get('supported', 0)}건"]
    if counts.get("gap"):
        parts.append(f"어긋나는 항목 {counts['gap']}건")
    if counts.get("unknown"):
        parts.append(f"확인이 필요한 항목 {counts['unknown']}건")
    tail = "" if used_requirements else " (공고명·요약만 보고 판정했습니다)"
    return " · ".join(parts) + tail
