"""나라장터 입찰공고 + 기업마당 지원사업 통합 사업기회 목록.

두 출처를 **한 화면에 나란히 놓기 위한 목록**을 만든다. 원본 점수(추천등급·지원 적합도)는 그대로
유지하고, 그 위에 선택한 회사 기준 검토 우선순위(company_priority_score)만 얹어 정렬한다.

- 하나의 사업기회 분석은 하나의 회사에 고정된다 → organization_id 를 받아 그 회사 프로필로 계산한다.
- 한쪽 출처가 실패해도 다른 쪽은 살린다 (source_errors 에 사유를 남기고 화면에서 숨기지 않는다).
- 조달공고를 지원사업처럼, 지원사업을 입찰처럼 표현하지 않는다 (opportunity_type·next_route 로 갈린다).
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Final, Sequence

from app.core import paths, storage

from app.schemas.business_opportunity import (
    SOURCE_TYPES,
    AnalysisState,
    CollectState,
    NextRoute,
    OpportunitySummary,
    PrepareSection,
    UnifiedOpportunity,
    UnifiedOpportunityListResponse,
)
from app.schemas.organization import AnalysisContext
from app.services import (
    auto_collect,
    notice_state_service,
    notice_version_service,
    qualification_clause_service,
    bizinfo_client,
    bizinfo_service,
    eligibility_engine,
    support_application_service,
    support_kinds,
    support_requirement_extractor,
    company_service,
    # 「새 공고」로 볼 기간의 단일 출처. 대시보드 띠를 만드는 쪽이 정하고 목록은 그것을
    # 그대로 응답에 싣는다 — 두 화면이 같은 기간으로 세게 하려는 것이다 (0920 §4-B-5).
    daily_digest_service,
    g2b_mapper,
    home_agencies,
    manual_notice_service,
    notice_schedule,
    opportunity_priority as priority,
    prespec_service,
    organization_service,
    practical_priority as practical,
    recommendation,
    procurement_service,
    qualification_store,
    work_kinds as work_kinds_service,
)

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

#: 정렬 — 실무 우선순위 · 회사 기준 검토 우선순위(점수) · 마감 여유 · 마감 임박 · 최신 등록 · 예산(레이더 「금액」) (37차 §3-C).
#: 비워 보내면 회사 방식(`ranking_method`)의 기본 정렬이다.
SORTS = ("practical", "priority", "slack", "deadline", "recent", "value")

NOTE = (
    "회사 기준 검토 우선순위입니다. 낙찰확률·선정확률이 아닙니다. "
    "조달공고의 추천등급과 지원사업의 지원 적합도는 원본 그대로 유지하며 서로 합치지 않습니다."
)


def _deadline_of_program(program) -> datetime | None:
    """신청 종료일 → 그날 23:59(KST). 날짜가 없으면 None (원문 문구는 deadline_text 로 간다)."""
    if program.apply_end is None:
        return None
    return datetime.combine(program.apply_end, time(23, 59), tzinfo=KST)


def _closed(deadline: datetime | None, now: datetime) -> bool:
    return deadline is not None and deadline < now


# --------------------------------------------------------------------------
# 출처별 수집 (한쪽이 실패해도 다른 쪽을 살린다)
# --------------------------------------------------------------------------


async def _collect_procurements(
    *,
    organization_id: str,
    context: AnalysisContext | None,
    profile,
    days: int,
    now: datetime,
    include_low: bool,
    refresh: bool = False,
) -> tuple[list[UnifiedOpportunity], str | None, str | None, procurement_service.ProcurementResult | None]:
    try:
        # refresh=True 면 TTL 캐시를 건너뛰고 나라장터를 다시 부른다.
        # 38차 · D15 — 후보 아님(`low`)도 늘 받는다. 기업마당 「관련 낮음」처럼 사유(`relevance_note`)를 달아 목록에 두고
        # 화면은 기본으로 접는다 — 숨겨서 「없는 것」처럼 만들지 않는다. `include_low` 는 예전 호출과의 호환으로만 남는다.
        del include_low
        result = await procurement_service.list_ai_candidates(
            days=days, include_low=True, refresh=refresh
        )
    except procurement_service.NoNoticeDataError as exc:
        return [], None, f"나라장터 조회 실패, 캐시도 없음: {exc}", None
    except Exception as exc:  # 통합 목록이 한쪽 때문에 통째로 죽지 않게 한다.
        logger.warning("나라장터 수집 실패: %s", exc)
        return [], None, f"나라장터 수집 오류: {exc}", None

    # 회사가 적어 둔 사실 — 「왜 맞나」·「주의」 한 줄이 이것을 읽는다 (0921 §4-C-3).
    from app.services import delivery_capacity_service

    capacity = delivery_capacity_service.load(organization_id)
    # 실적 원장은 **내부 범위에서만** 읽는다 — 상세 판정(`eligibility_engine.evaluate`)과 같은 규칙.
    company = eligibility_engine.company_facts_for(organization_id, evidence_scope=context.evidence_scope)
    regions = tuple(r for r in profile.preferred_regions if r)
    items: list[UnifiedOpportunity] = []
    for view in result.notices:
        # 공고 하나의 분석 상태. 손댄 적 없는 공고는 파일을 열지 않고 싼 값으로 끝난다 —
        # 목록이 100건이 넘으므로 전부 열면 화면이 몇 초씩 걸린다.
        state = notice_state_service.state_of(view.notice.id, context)
        notice = view.notice
        # **판정이 먼저다** (0922 §4-B-2). 자격 25점이 규칙 종합을 그대로 읽기 때문에,
        # 점수를 먼저 매기면 배지와 점수가 서로 다른 사실에서 나온다.
        # 규칙을 한 번만 돌리고 게이트·열리는 조건·계약방식을 모두 여기서 뽑는다.
        rules = eligibility_engine.evaluate_notice_fields(
            notice.raw_data, as_of=now, regions=regions, company=company, notice_id=notice.id
        )
        eligibility_gate, gate_reason = priority.procurement_eligibility_gate(
            notice, view.match, profile=profile, now=now, organization_id=organization_id, results=rules
        )
        # 일의 종류(갈래). 상세 분석과 같은 규칙표를 쓴다 — work_kinds 가 단일 출처다.
        work = work_kinds_service.of_notice(notice)
        components, reasons, checks, source_score = priority.score_procurement(
            notice,
            view.match,
            profile=profile,
            source=result.source,
            now=now,
            organization_id=organization_id,
            gate=eligibility_gate,
            capacity=capacity,
            tracks=list(work["tracks"]),
            rules=rules,
        )
        score = priority.normalize(components)
        unlocks = list(
            dict.fromkeys(
                r.unlock_condition for r in rules
                if r.unlock_condition and r.status in ("FAIL", "CHECK") and not eligibility_engine.is_relocation(r.unlock_condition)
            )
        )
        briefing_at, joint_deadline = practical.g2b_dates(notice.raw_data)
        clause_payload = qualification_clause_service.load(notice.id)
        # 43차 결정 1 — 공고문 일정표의 가장 이른 마감(참가신청 · 입찰등록 · 제출 · 필수 현장설명). 입찰 마감이 비어도 개찰일은 쓰지 않는다(H1).
        schedule = (clause_payload or {}).get("schedule") if isinstance(clause_payload, dict) else None
        first = notice_schedule.earliest(schedule, after=notice.published_at)
        schedule_deadline = datetime.fromisoformat(first["at"]) if first else None
        qual_deadline = g2b_mapper.parse_datetime((notice.raw_data or {}).get("qualification_deadline") or "")
        opening_at = g2b_mapper.parse_datetime((notice.raw_data or {}).get("opening_at") or "")
        # 실제 마감 — 입찰 · 등록 · 공고문 일정 중 가장 이른 것(카드 D-day 와 「마감까지 N일」 · 「마감 N일 남음」이 같은 날을 센다 · 40차 SCREEN-02)
        effective_close = min((d for d in (notice.deadline_at, qual_deadline, schedule_deadline) if d is not None), default=None)
        # 마감이 아무 데도 없으면 개찰이 지난 공고는 끝난 것이다(제출은 개찰 전) — 개찰일을 마감으로 보이지는 않는다.
        closed = _closed(effective_close, now) if effective_close is not None else _closed(opening_at, now)
        published_at, amended_at = _published_dates(notice)
        # 38차 §3-C — 근거 줄(참가자격 조항 파일 · 쪽 번호) · 최근 7일 공고 변경(마감 · 첨부 · 차수 · 종류 · 지역 뺌). 파일 읽기뿐이다.
        evidence, clause_count = qualification_clause_service.evidence_line(
            clause_payload, field_requires=qualification_clause_service.field_requires(rules)
        )
        changed = notice_version_service.notable_changes_since(notice.id, now - timedelta(days=practical.FRESH_DAYS))
        fit_type, fit_basis = practical.type_of_kinds(list(work["kinds"]), notice.title)
        items.append(
            UnifiedOpportunity(
                id=notice.id,
                source_type="g2b",
                opportunity_type="procurement",
                title=notice.title,
                agency=home_agencies.display_agency(notice.agency, (notice.raw_data or {}).get("demand_institution")),
                demand_agency=((notice.raw_data or {}).get("demand_institution") or None),
                summary=notice.description,
                deadline=notice.deadline_at,
                deadline_text=None if effective_close else (
                    f"마감 미상 — 개찰 {opening_at.astimezone(KST):%m/%d}(제출 마감 아님)" if opening_at else "공고에 마감일 없음"
                ),
                # 참가자격 등록·공동수급협정 마감. **실제 데드라인은 이쪽이 더 이르다**
                # (0922 §4-B-8) — 카드가 두 줄로 적고 D-day 는 더 이른 쪽을 쓴다.
                qualification_deadline=qual_deadline,
                schedule_deadline=schedule_deadline,
                schedule_deadline_label=first["label"] if first else None,
                schedule_deadline_time_known=bool(first.get("time_known")) if first else None,
                opening_at=opening_at,
                briefing_required=bool(schedule.get("briefing_required")) if isinstance(schedule, dict) else None,
                amended_at=amended_at,
                detail_url=notice.source_url,
                organization_id=organization_id,
                company_priority_score=score,
                # 자기 출처 안에서만 뜻이 있는 점수. 기업마당 점수와 나란히 세우지 않는다.
                procurement_fit_score=score,
                support_fit_score=None,
                review_priority_score=score,
                priority_rank=0,  # 정렬 후 부여
                # 라벨도 정렬 뒤에 매긴다 — 「우선 검토」가 **상위 15%** 를 보기 때문이다
                # (0922 §4-B-6). 여기서는 자리만 잡아 둔다.
                priority_label="미확인",
                eligibility_gate=eligibility_gate,
                gate_reason=gate_reason,
                confidence=priority.confidence_of(components, source=result.source),
                score_components=components,
                source_specific_score=source_score,
                next_route=NextRoute(
                    kind="procurement_analysis",
                    path=f"/analysis?notice={notice.id}",
                    # 이미 요구사항을 뽑아 둔 공고에 「시작」이라고 적으면 담당자가 처음부터
                    # 다시 하는 줄 안다 — 실제로 요구사항 55건·점검 47건이 있는 공고에도
                    # 「입찰 분석 시작」이 붙어 있었다 (ISSUE-076-c).
                    label="분석 계속 →" if state.parsed else "입찰 분석 열기",
                ),
                # 목록 행·레이더가 그대로 그리는 분석 상태 (0920 §4-B-3).
                analysis_state=AnalysisState(**state.to_dict()),
                source=result.source,
                pinned=view.pinned,
                closed=closed,
                reasons=reasons,
                checks=checks,
                budget=notice.budget,
                # 카드의 분류 칸에는 지역 «이름»만 넣는다. 캐시에 남은 공고에는
                # 「본사또는참여지사소재지」 같은 판단기준 이름이 region 에 들어 있어,
                # 그대로 두면 분류 칩이 지역인 척하는 문구를 보여 준다.
                category=g2b_mapper.region_name(notice.region),
                work_kinds=work["kinds"],
                work_tracks=work["tracks"],
                work_basis=work["basis"],
                # 「왜 맞나」·「주의」 한 줄 (0921 §4-C-3). 담당자가 100건을 훑을 때
                # 읽는 것은 첫 줄 하나다. LLM 을 쓰지 않고 회사가 적어 둔 검증 역량과
                # 공고의 갈래·분류·예산·마감만 규칙으로 잇는다.
                fit_line=priority.fit_line(
                    text=f"{notice.title} {notice.description or ''}",
                    tracks=list(work["tracks"]),
                    procurement_class=(notice.raw_data or {}).get("procurement_class"),
                    budget=notice.budget,
                    # 등록마감이 먼저 닫히면 그쪽까지 — 카드 D-day(더 이른 쪽)와 「마감까지 N일」이 하루 어긋났다(27차 검수 R27U-MSC-01)
                    # 40차 SCREEN-02 — 셈도 D-day 와 같은 KST 달력 날짜 차(`calendar_days_left`)
                    days_left=recommendation.calendar_days_left(effective_close, now),
                    capacity=capacity,
                ),
                # 계약·낙찰 방식 한 줄. 자격 규칙(ELIG-AWARD)이 만든 문장을 그대로 쓴다 —
                # 여기서 다시 조립하면 상세 화면과 말이 갈린다.
                award_line=next((r.reason for r in rules if r.rule_id == "ELIG-AWARD"), None),
                industry_partner=eligibility_engine.industry_partner(rules, notice.raw_data or {}),
                # 「무엇을 갖추면 열리는가」. 화면이 행 접기 안에 그대로 적는다 (0921 §4-D-1).
                unlock_conditions=unlocks,
                clause_ids=[r.clause_id for r in rules if r.clause_id],
                caution_line=priority.caution_line(
                    budget=notice.budget,
                    ceiling=company.budget_ceiling_krw,
                    days_left=recommendation.calendar_days_left(effective_close, now),
                    lead_days=company.proposal_lead_days,
                    joint_allowed=eligibility_engine.joint_allowed(notice.raw_data or {}),
                    out_of_scope=bool(getattr(view.match, "out_of_scope", False)),
                ),
                # 실무 우선순위 값 (37차 §3-B-1) — 모두 저장본에 있는 공고 필드다. 없으면 빈칸.
                # 43차 M2 — 변경공고(차수 001+)는 원공고 게시일(모르면 None · 신규로 세지 않음) · 변경 게시일은 `amended_at`.
                published_at=published_at,
                submission_methods=practical.g2b_methods(notice.raw_data),
                recruit_kind=practical.RECRUIT_BID,
                # 설명회 — 나라장터 필드가 없으면 공고문 일정표의 현장설명(43차 ELIG-06)
                briefing_at=briefing_at or (
                    datetime.fromisoformat(b["at"]) if (b := notice_schedule.briefing(schedule)) else None
                ),
                joint_agreement_deadline=joint_deadline,
                fit_type=fit_type,
                fit_type_basis=fit_basis,
                practical_company_gap=any(r.status == "CHECK" and r.check_side == "company" for r in rules),
                practical_candidate=bool(getattr(view.match, "is_candidate", True)),
                evidence_line=evidence,
                clause_count=clause_count,
                changed_fields=changed,
                # 38차 · D15 — 후보가 아닌 나라장터 공고의 사유(「본업이 아닌 교육 — 「안전교육」」 등). 기업마당 「관련 낮음」과 같은 칸이다.
                relevance_note=None
                if getattr(view.match, "is_candidate", True)
                else (getattr(view.match, "low_reason", None) or "후보 낱말 조합이 아닙니다(낱말 관련도 낮음)"),
            )
        )
    # 38차 §3-D — 사전규격(본공고 전). 저장본 읽기뿐이다(받기는 매일 아침 `collect_daily`). 본공고 행에 「사전규격 n일 전 공개」를
    # 다는 것도 여기서 한다. 39차 결정 1 — 사전규격은 입찰 목록 밖이다: `list_opportunities` 가 떼어 「선제준비」 칸(`prepare`)으로 보낸다.
    items.extend(
        prespec_service.build_items(
            notices=[view.notice for view in result.notices],
            organization_id=organization_id,
            profile=profile,
            capacity=capacity,
            now=now,
            main_items=items,
        )
    )
    # 결과 객체를 함께 올린다 — 수집 방식·호출 횟수·**캐시 시각**이 거기 들어 있고,
    # 지금까지 이 함수가 그것을 버려서 통합 목록이 「조회 시각 = 지금」을 적고 있었다.
    return items, result.source, result.error, result


#: 기업마당 판정 메모 (0922 §4-D-3 · ISSUE-088).
#:
#: 통합 목록 응답이 2.9초였다. 그 대부분이 **기업마당 1,605건에 규칙을 돌리는 시간**이다 —
#: 지역 태그·대상 요건·접수 기간·관련성·점수를 프로그램마다 잰다. 그런데 그 값들은
#: **받아 온 목록과 회사 자료가 같으면 같다.** 그래서 한 벌만 만들어 들고 있는다.
#:
#: 나라장터 쪽은 메모하지 않는다. 담당자가 결정·검토를 저장하면 목록 행의 분석 상태가
#: 즉시 바뀌어야 하기 때문이다(`notice_state_service`). 지원사업에는 그 축이 없다
#: (`analysis_state` 가 언제나 None 이다).
_SUPPORT_MEMO: dict[tuple, tuple[list[UnifiedOpportunity], str | None, str | None, bool, datetime | None]] = {}
#: 메모를 몇 벌까지 들고 있을까. 회사 수 × 날짜 수 — 몇 벌이면 충분하다.
_SUPPORT_MEMO_LIMIT = 8

#: **파일로도 남긴다** (0923 §3-4 · ISSUE-095).
#:
#: 프로세스 메모리만 쓰면 `uvicorn --reload` 가 파일을 저장할 때마다 메모가 사라진다.
#: 개발 중에는 저장이 잦아, 실제로는 거의 언제나 2.5~3.2 초짜리 첫 요청만 겪게 된다.
#: 캐시 시각이 파일 이름에 들어 있으므로 **새로 받아 오면 옛 파일은 저절로 쓰이지 않는다.**
_MEMO_DIR = paths.DATA_ROOT / "private" / ".cache"


#: 판정 결과를 바꾸는 코드 파일 — 내용이 바뀌면 메모가 무효다(R31-08).
_RULE_CODE_FILES: Final[tuple[str, ...]] = (
    "support_application_service.py",
    "support_requirement_extractor.py",
    "opportunity_priority.py",
    "support_kinds.py",
    "eligibility_engine.py",
    "bizinfo_service.py",  # 지원 적합도 사유도 메모에 든다(32차 — 낱말 사유를 고쳤다)
    # 메모에 실무 우선순위 값(접수방식 · 모집 성격 · 유형)도 든다(37차) — 그 계산 · 조립 코드를 고치면 옛 메모를 쓰지 않는다.
    "practical_priority.py",
    # 40차 REGRESS-03 — 유형(근사)이 39차부터 이 파일(부서 이름 조각 · 유지관리 꼴 · 제목 핵심)에 기댄다
    "opportunity_filter.py",
    "opportunity_service.py",
    "work_kinds.py",
    # 41차 — 사전규격 행(공고명 행사 꼴 접기 · 대체 유형)도 목록 메모에 든다
    "prespec_service.py",
)


@functools.lru_cache(maxsize=1)
def _rule_code_fingerprint() -> str:
    """판정 · 추출기 · 점수 파일 내용의 짧은 지문. 서버가 코드를 다시 읽으면(--reload) 새로 계산한다."""
    digest = hashlib.sha1()
    here = Path(__file__).resolve().parent
    for name in _RULE_CODE_FILES:
        try:
            digest.update((here / name).read_bytes())
        except OSError:
            digest.update(name.encode())
    return digest.hexdigest()[:8]


def _inputs_stamp() -> str:
    """판정의 **입력**이 바뀌었는지 한 문자열로. 바뀌면 메모가 무효다.

    넷을 본다.

    1. 기업마당 캐시 수정 시각 — 새로 받아 오면 목록이 달라진다.
    2. 공고문 목록 수정 시각 — 공고문을 더 받으면 판정이 바뀐다(0924 §4-A). 캐시 시각만
       보면 어제 판정이 그대로 남는다.
    3. **벡터 캐시의 지문** (prompt_05 §4-B-1 · ISSUE-129). 의미 유사도를 쓰는 동안 벡터가
       늘면 사업영역 점수가 달라진다 — 재검증에서 목록 85 · 상세 74 로 갈린 원인이다.
       `SEMANTIC_FIT` 이 꺼져 있으면 벡터를 읽지 않으므로 「off」 하나로 고정된다.
    4. 판정 규칙 판(`support_application_service.RULES_VERSION`) — 규칙 코드를 고친 날.
    5. **판정 · 추출기 · 점수 파일의 내용 지문**(32차 R31-08) — 판 상수를 올리지 않고 추출기 · 점수 코드만 고친 날에도
       옛 판정이 남지 않게.
    """
    from app.services import bizinfo_document_store, semantic_matcher
    from app.services.support_application_service import RULES_VERSION

    stamps: list[str] = [f"r{RULES_VERSION}", _rule_code_fingerprint()]  # 4 · 5
    for path in (bizinfo_service.CACHE_FILE, bizinfo_document_store.INDEX_FILE):
        try:
            stamps.append(str(path.stat().st_mtime_ns))
        except OSError:
            stamps.append("0")
    stamps.append(semantic_matcher.cache_fingerprint())
    return "-".join(stamps)


def _memo_file(organization_id: str, stamp: str) -> Path:
    return _MEMO_DIR / f"opportunities_{organization_id}_{stamp}.json"


def clear_support_memo() -> None:
    """회사 자료가 바뀌면 지운다. 테스트도 이것으로 되돌린다.

    파일로 남긴 것까지 지운다 — 메모리만 비우면 `--reload` 뒤에 옛 판정이 되살아난다.
    """
    _SUPPORT_MEMO.clear()
    try:
        for path in _MEMO_DIR.glob("opportunities_*.json"):
            path.unlink(missing_ok=True)
    except OSError:  # 캐시를 못 지운다고 목록이 죽지는 않는다
        logger.warning("지원사업 판정 메모 파일을 지우지 못했습니다", exc_info=True)


def _support_memo_key(*, organization_id: str, count: int, today: date, company: Any) -> tuple:
    """같은 답이 나오는 조건.

    입력 지문(`_inputs_stamp`)을 넣는다 — 기업마당 캐시·공고문 목록·**벡터 집합** 중
    하나라도 바뀌면 메모가 저절로 무효가 된다. 파일이 없으면 0 이다(샘플로 답하는 경우).
    """
    return (organization_id, count, today, company, _inputs_stamp())


def memoized_support_score(
    program_id: str, *, organization_id: str, today: date, company: Any
) -> int | None:
    """목록이 **이미 낸** 검토 우선순위. 없으면 None (prompt_05 §4-B-1).

    상세는 이것을 먼저 보고, 없을 때만 자기가 계산한다. 「같은 함수」(11차 ISSUE-097)에
    「같은 입력」을 더하는 자리다 — 메모가 살아 있다는 것은 `_inputs_stamp()` 가 같다는
    뜻이고, 지문에 벡터 집합이 들어 있으므로 **그 점수는 지금 계산해도 같은 값**이다.
    그래서 꺼내 쓰는 것이 안전하고, 꺼내 쓰면 두 화면이 갈릴 창이 아예 없어진다.

    `count`(몇 건 받아 왔는지)는 맞추지 않는다 — 한 건의 점수는 몇 건을 받아 왔는지에
    달려 있지 않고, 상세는 목록이 어떤 `count` 로 조회됐는지 알 수 없다.
    """
    stamp = _inputs_stamp()
    for key, outcome in _SUPPORT_MEMO.items():
        if key[0] != organization_id or key[2] != today or key[3] != company or key[4] != stamp:
            continue
        for item in outcome[0]:
            if item.id == program_id:
                return item.company_priority_score
    return None


def _memo_fingerprint(key: tuple) -> str:
    """메모 열쇠를 파일에 적어 둘 짧은 지문. 회사 자료·조회 조건이 바뀌면 달라진다."""
    return hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:16]


def _load_memo_file(key: tuple) -> tuple | None:
    """파일로 남겨 둔 판정. 지문이 다르면 쓰지 않는다 (조건이 바뀐 것이다)."""
    organization_id, _count, _today, _company, stamp = key
    path = _memo_file(str(organization_id), stamp)
    try:
        payload = storage.read_json(path, default=None)
    except storage.CorruptJsonError:
        return None
    if not isinstance(payload, dict) or payload.get("fingerprint") != _memo_fingerprint(key):
        return None
    try:
        items = [UnifiedOpportunity.model_validate(row) for row in payload.get("items") or []]
    except Exception:  # noqa: BLE001 — 옛 스키마로 저장된 파일은 그냥 버린다
        logger.info("지원사업 판정 메모 파일의 형식이 달라 다시 계산합니다: %s", path.name)
        return None
    fetched = payload.get("fetched_at")
    return (
        items,
        payload.get("source"),
        payload.get("error"),
        bool(payload.get("field_mapping_verified")),
        datetime.fromisoformat(fetched) if isinstance(fetched, str) else None,
    )


def _save_memo_file(key: tuple, outcome: tuple) -> None:
    """판정을 파일로 남긴다. 실패해도 목록은 그대로 나간다 — 캐시일 뿐이다."""
    organization_id, _count, _today, _company, stamp = key
    items, source, error, verified, fetched_at = outcome
    payload = {
        "_note": "통합 목록의 기업마당 판정 메모 (내부 전용, Git 제외). 지우면 다시 계산한다.",
        "fingerprint": _memo_fingerprint(key),
        "source": source,
        "error": error,
        "field_mapping_verified": verified,
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "items": [item.model_dump(mode="json") for item in items],
    }
    try:
        # 같은 회사의 **옛 캐시 시각** 파일은 이제 쓰이지 않는다 — 남겨 두면 쌓이기만 한다.
        for old_path in _MEMO_DIR.glob(f"opportunities_{organization_id}_*.json"):
            if old_path.name != _memo_file(str(organization_id), stamp).name:
                old_path.unlink(missing_ok=True)
        storage.write_json_atomic(_memo_file(str(organization_id), stamp), payload, compact=True)
    except OSError:
        logger.warning("지원사업 판정 메모를 파일로 남기지 못했습니다", exc_info=True)


async def _collect_support(
    *, organization_id: str, profile, now: datetime, refresh: bool, count: int
) -> tuple[list[UnifiedOpportunity], str | None, str | None, bool, datetime | None]:
    today = now.astimezone(KST).date()
    company = eligibility_engine.company_facts_for(organization_id)
    # **목록 조회보다 먼저 본다.** 2.7초의 대부분이 1,605건을 읽어 지원 적합도를 재는
    # `list_programs` 자체에 있다 — 그 뒤에서 메모해서는 시간이 줄지 않는다.
    memo_key = _support_memo_key(
        organization_id=organization_id, count=count, today=today, company=company
    )
    hit = _SUPPORT_MEMO.get(memo_key)
    if hit is None and not refresh:
        # 프로세스 메모리에 없으면 **파일**을 본다 (0923 §3-4 · ISSUE-095).
        # `--reload` 가 프로세스를 새로 띄워도 판정은 그대로 살아 있어야 한다.
        hit = _load_memo_file(memo_key)
        if hit is not None:
            _SUPPORT_MEMO[memo_key] = hit
    if hit is not None and not refresh:
        return _detached(hit)

    try:
        listing = await bizinfo_service.list_programs(refresh=refresh, count=count, organization_id=organization_id)
    except Exception as exc:  # noqa: BLE001 — 한쪽 실패가 전체를 죽이지 않게 한다.
        logger.warning("기업마당 수집 실패: %s", exc)
        return [], None, f"기업마당 수집 오류: {exc}", bizinfo_service.FIELD_MAPPING_VERIFIED, None

    from app.services import delivery_capacity_service

    capacity = delivery_capacity_service.load(organization_id)
    #: 「디지털 제품(서비스) 보유」 같은 요건을 **회사가 적어 둔 사업영역**으로 판정한다.
    domains = tuple(profile.business_domains)
    items: list[UnifiedOpportunity] = []
    for view in listing.items:
        program, fit = view.program, view.support_fit
        # **판정은 신청 분석 화면과 같은 함수가 한다** (0925 §4-B-1 · ISSUE-097).
        #
        # 10차까지는 여기와 `support_application_service.build()` 가 다른 경로였다 —
        # 목록은 공고문을 읽고, 상세는 요약문만 봤다. 같은 공고가 목록에서 「85점 · 가능」,
        # 상세에서 「57점 · 확인 필요」였다. 규칙을 두 벌 두지 않는다.
        judgement = support_application_service.judge(
            program, fit, company=company, profile=profile, source=listing.source, today=today
        )
        requirements = judgement.requirements
        biz, indirect = judgement.rules, judgement.indirect
        eligibility_gate, gate_reason = judgement.gate, judgement.gate_reason
        relevance = judgement.relevance
        components, reasons, checks, source_score = (
            judgement.components, judgement.reasons, judgement.checks, judgement.source_score
        )
        score = judgement.score
        deadline = _deadline_of_program(program)
        closed = _closed(deadline, now)
        recruit_kind = (
            practical.RECRUIT_OPERATOR
            if support_application_service.is_operator_call(program)
            else practical.RECRUIT_BENEFIT
        )
        fit_type, fit_basis = practical.bizinfo_type(program.title, program.summary, recruit_kind)
        items.append(
            UnifiedOpportunity(
                id=program.id,
                source_type="bizinfo",
                opportunity_type="support_program",
                title=program.title,
                agency=program.agency,
                summary=program.summary,
                deadline=deadline,
                deadline_text=None if deadline else (program.apply_period_text or "신청 기간 원문 확인 필요"),
                detail_url=program.url,
                organization_id=organization_id,
                company_priority_score=score,
                procurement_fit_score=None,
                support_fit_score=score,
                review_priority_score=score,
                priority_rank=0,
                priority_label="미확인",  # 정렬 뒤에 상위 15% 를 보고 매긴다 (0922 §4-B-6)
                eligibility_gate=eligibility_gate,
                gate_reason=gate_reason,
                confidence=priority.confidence_of(components, source=listing.source),
                score_components=components,
                source_specific_score=source_score,
                next_route=NextRoute(
                    kind="support_application",
                    path=f"/support/{program.id}",
                    label="지원사업 신청 분석 열기",
                ),
                source=listing.source,
                closed=closed,
                reasons=reasons,
                checks=checks,
                budget=None,  # 지원 규모는 목록 API에 없다. 0원으로 표시하지 않는다.
                category=program.category,
                # 마감일이 없는 이유를 화면이 구분할 수 있게 그대로 옮긴다.
                # 상시·예산 소진 건을 「신청 종료」로 읽지 않기 위해 필요하다.
                apply_period_kind=program.apply_period_kind,
                # 「왜 맞나」 한 줄 (0921 §4-C-3). 지원사업도 같은 모양으로 적는다 —
                # 담당자가 한 목록에서 두 출처를 훑기 때문이다.
                # **맞은 회사 사실만** 적는다 (0925 §4-D-4). 10차의 이 줄은
                # 「지원사업 · 인력 · 전남광주」였다 — 분류와 지역 해시태그이지
                # 「왜 맞나」의 답이 아니다. 분류·지역은 아래 `region_tags` 와
                # 카드의 분류 줄에 지금처럼 따로 있다.
                fit_line=judgement.company_facts,
                caution_line=(
                    " · ".join(checks[:2]) if checks else None
                ),
                unlock_conditions=judgement.unlock_conditions,
                # 「☞ 대상 문장」과 지역 태그를 목록 행이 그대로 보여 준다 (0921 §4-D-1).
                region_tags=list(program.region_tags),
                requirement_sentences=list(program.requirement_sentences[:3]),
                # 회사가 신청 주체가 아닐 때의 자리 표시 (0924 §4-A-4).
                participation=indirect,
                # 「회사에 뜻하는 것」 한 줄 — 역할 · 받는 것 · 부담 · 마감 (0924 §4-A-6).
                company_meaning=judgement.company_meaning,
                check_side=(
                    ("company" if judgement.signals.get("company_side_checks") else "notice")
                    if eligibility_gate == "CHECK"
                    else None
                ),
                document_read=requirements.document_read,
                # 38차 §3-C-2 — 기업마당 근거 줄은 공고문 인용(`clause_quotes`)에서. 공고문을 못 읽었으면 「공고문 아직 안 읽음」.
                evidence_line=(
                    f"근거: 공고문 「{_clip(judgement.clause_quotes[0])}」"
                    if judgement.clause_quotes
                    else None if requirements.document_read else qualification_clause_service.NOT_READ
                ),
                document_note=requirements.document_note,
                clause_quotes=judgement.clause_quotes,
                # 「관련 낮음」은 지우는 것이 아니라 기본으로 접는 것이다 (0922 §4-C-2).
                relevance_note=None if relevance.related else relevance.reason,
                # 회사가 신청 주체가 아닐 수 있다는 안내 (ISSUE-125). 「이번 주 할 일」이 본다.
                audience_note=fit.audience_note,
                executing_agency=program.executing_agency,
                # 실무 우선순위 값 (37차 §3-B-1) — 등록일 · 신청방법 · 접수처 주소 · 역할 규칙(제목).
                published_at=program.created_at,
                submission_methods=practical.bizinfo_methods(program.apply_method, program.reception_url),
                submission_text=(program.apply_method or "").replace("\n", " ").strip()[:120] or None,
                recruit_kind=recruit_kind,
                fit_type=fit_type,
                fit_type_basis=fit_basis,
                kind_fit=support_kinds.of_program(program).is_ours,
            )
        )
    outcome = (items, listing.source, listing.error, listing.field_mapping_verified, listing.fetched_at)
    if len(_SUPPORT_MEMO) >= _SUPPORT_MEMO_LIMIT:
        _SUPPORT_MEMO.clear()
    _SUPPORT_MEMO[memo_key] = outcome
    _save_memo_file(memo_key, outcome)
    return _detached(outcome)


def _clip(text: str, limit: int = qualification_clause_service.EVIDENCE_CHARS) -> str:
    """근거 줄에 싣는 원문 — 공백을 줄이고 `limit` 자에서 자른다."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit].rstrip() + "…"


def _detached(
    outcome: tuple[list[UnifiedOpportunity], str | None, str | None, bool, datetime | None],
) -> tuple[list[UnifiedOpportunity], str | None, str | None, bool, datetime | None]:
    """메모 속 항목의 사본을 돌려준다(37차 마지막 검토).

    정렬 · 순위 매기기가 항목을 고친다 — 메모 속 객체를 그대로 내주면 한 요청이 목록을 두 번 만들 때(엑셀의 「브리핑」 시트)
    뒤 목록의 순위가 앞 목록 항목의 「순」을 덮어썼다. 얕은 사본에 제자리에서 고치는 `track_ranks` 만 새로 둔다.
    """
    items, *rest = outcome
    return ([item.model_copy(update={"track_ranks": {}}) for item in items], *rest)


# --------------------------------------------------------------------------
# 정렬 — 같은 점수면 항상 같은 순서가 나오게 한다
# --------------------------------------------------------------------------

_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
_FAR_FUTURE = datetime(2999, 12, 31, tzinfo=timezone.utc)


def effective_deadline(item: UnifiedOpportunity) -> datetime | None:
    """실제 데드라인 — `practical_priority.effective_deadline` 하나(입찰 · 등록 · 공고문 일정 중 가장 이른 것 · 43차 결정 1 · 0922 §4-B-8).

    한남대·KISTI 는 입찰마감이 9-28 인데 참가자격 등록은 9-27 18:00 에 닫힌다. 가천대 해커톤은 입찰등록 11/10 인데 참가신청이
    10/30 이다. D-day·정렬·「이번 주 할 일」이 모두 이 값을 쓴다.
    """
    return practical.effective_deadline(item)


def _published_dates(notice) -> tuple[datetime | None, datetime | None]:
    """(공고일, 변경공고 게시일) — 43차 M2. 변경공고(차수 001+)는 원공고 게시일을 공고일로 쓴다: 자격 하루치 파일(게시일별)에서 처음 본 날,
    없으면 원공고(-000)를 앱이 처음 본 때. 둘 다 없으면 공고일 None(신규로 세지 않음)."""
    item = (notice.raw_data or {}).get("item") if isinstance(notice.raw_data, dict) else None
    order = str((item or {}).get("bidNtceOrd") or "000")
    if not item or order in ("", "000"):
        return notice.published_at, None
    bid_no = str(item.get("bidNtceNo") or "")
    day = qualification_store.first_published_days().get(bid_no)
    original: datetime | None = datetime(day.year, day.month, day.day, tzinfo=KST) if day else None
    if original is None:
        history = notice_version_service.load_history(f"g2b-{bid_no}-000")
        original = history.versions[0].observed_at if history.versions else None
    if original is not None and notice.published_at is not None and original >= notice.published_at:
        original = None
    return original, notice.published_at


def _sort_key(item: UnifiedOpportunity, sort: str) -> tuple:
    # 마감된 항목은 언제나 뒤로 (점수와 무관).
    closed_rank = 1 if item.closed else 0
    # 명확한 신청 불가 신호는 점수가 높아도 검토 가능한 항목 뒤로 보낸다.
    gate_rank = 1 if item.eligibility_gate == "FAIL" else 0
    deadline = effective_deadline(item) or _FAR_FUTURE
    score = item.company_priority_score
    # 점수 없음(계산 불가)은 뒤로. 정렬 안정성을 위해 마지막 키로 id를 둔다.
    score_rank = -(score if score is not None else -1)
    conf = _CONFIDENCE_ORDER.get(item.confidence, 3)
    if sort == "practical":
        # 실무 우선순위 — `practical.order` 가 먼저 매겨 둔 자리(제외 · 비추천은 이미 뒤에 있다 · 37차 §3-B).
        return (item.practical_order or 10**9, item.id)
    if sort == "deadline":
        return (closed_rank, gate_rank, deadline, score_rank, conf, item.id)
    if sort == "slack":
        # 마감 여유순 — 실제 마감이 먼 것부터. 마감일이 없는 건은 잴 수 없어 날짜 있는 것 뒤로 (37차 §3-C).
        real = effective_deadline(item)
        far = -real.timestamp() if real is not None else float("inf")
        return (closed_rank, gate_rank, far, score_rank, item.id)
    if sort == "recent":
        # 최신 등록순 — 나라장터 공고일 · 기업마당 등록일. 없으면 뒤로.
        posted = -item.published_at.timestamp() if item.published_at is not None else float("inf")
        return (closed_rank, gate_rank, posted, score_rank, item.id)
    if sort == "value":
        # 지원 규모가 목록에 없는 지원사업을 0원으로 취급하지 않는다 — 금액 없는 항목은 뒤로 보낸다.
        has_value = 0 if item.budget is not None else 1
        return (closed_rank, gate_rank, has_value, -(item.budget or 0), score_rank, deadline, item.id)
    return (closed_rank, gate_rank, score_rank, deadline, conf, item.id)


def sort_opportunities(items: list[UnifiedOpportunity], sort: str) -> list[UnifiedOpportunity]:
    """정렬하고 순위를 매긴다.

    순위는 **두 벌**이다:
      - priority_rank : 통합 목록 전체 순위. 두 출처가 섞여 있으므로 표시용이다.
      - source_rank   : 같은 출처 안에서의 순위. 화면이 실제로 보여줄 것은 이쪽이다.

    나라장터(우리가 수주하는 사업)와 기업마당(우리가 지원금을 신청하는 사업)은 목적이 달라
    하나의 1~N 위에 세우면 뜻이 없다. 그런데 한 화면에 함께 놓아야 하니 통합 순위도 남긴다 —
    대신 어느 쪽이 «비교 가능한 순위»인지 필드 이름으로 구분해 둔다.
    """
    ordered = sorted(items, key=lambda i: _sort_key(i, sort))
    for index, item in enumerate(ordered, start=1):
        item.priority_rank = index

    for source_type in SOURCE_TYPES:
        same = [i for i in ordered if i.source_type == source_type]
        for index, item in enumerate(same, start=1):
            item.source_rank = index
            item.source_total = len(same)
        # 갈래 안에서의 순위 (0922 §4-B-7). 기업마당은 갈래 축이 없어 「support」 하나로 둔다.
        tracks = {t for i in same for t in (i.work_tracks or ["support"])}
        for track in tracks:
            members = [i for i in same if track in (i.work_tracks or ["support"])]
            for index, item in enumerate(members, start=1):
                item.track_ranks[track] = index
        _label_cohort(same)
    return ordered


def interleave_sources(items: list[UnifiedOpportunity], sort: str) -> list[UnifiedOpportunity]:
    """「전체」 탭의 회사 순서 — 출처별 순위를 번갈아 세운다(39차 D22 · 나라장터 1 · 기업마당 1 · 직접 넣음 1 · 나라장터 2 …).

    순위는 갈래 안에서만이다(CLAUDE.md §12) — 실무순을 한 줄로 세우면 접수방식 규칙 때문에 첫 10행이 모두 기업마당이었다
    (recheck31). 번갈아 세우는 것은 같은 칸끼리다: 살아 있는 것 → (실무순) 비추천 → 마감 · 불가. 화면(`lib/interleave.ts`)과 같은
    규칙이라 내려받은 파일 순서가 화면과 같다. `priority_rank` · `source_rank` 는 건드리지 않는다.
    """
    def hold(item: UnifiedOpportunity) -> int:
        if item.closed or item.eligibility_gate == "FAIL":
            return 2
        return 1 if sort == "practical" and item.practical_group == "비추천" else 0

    out: list[UnifiedOpportunity] = []
    for cls in (0, 1, 2):
        lanes = [[i for i in items if i.source_type == source and hold(i) == cls] for source in SOURCE_TYPES]
        for index in range(max((len(lane) for lane in lanes), default=0)):
            out.extend(lane[index] for lane in lanes if index < len(lane))
        out.extend(i for i in items if i.source_type not in SOURCE_TYPES and hold(i) == cls)
    return out


def renumber_sources(items: list[UnifiedOpportunity]) -> None:
    """거른 뒤의 목록으로 `source_rank`·`source_total` 을 다시 매긴다 (0925 §4-D-2).

    `sort_opportunities` 는 **거르기 전**에 순위를 매긴다 — 「우선 검토」가 같은 출처
    상위 15% 를 보기 때문에 분모가 전체여야 한다. 그런데 화면의 「지원 1/1578」 칩은
    그 분모를 그대로 썼고, 바로 위 탭은 지금 조건의 578 을 말했다. 담당자가 한 화면에서
    기업마당 숫자 셋(탭 578 · 칩 1578 · 머리 1578)을 읽었다.

    칩은 **지금 목록에서 몇 번째인가**를 말해야 한다. 「우선 검토」 라벨과 요약(summary)
    분모는 위에서 이미 확정됐으므로 여기서 다시 세도 흔들리지 않는다.
    """
    for source_type in SOURCE_TYPES:
        same = [i for i in items if i.source_type == source_type]
        for index, item in enumerate(same, start=1):
            item.source_rank = index
            item.source_total = len(same)


def _label_cohort(items: list[UnifiedOpportunity]) -> None:
    """같은 출처 안에서 「우선 검토」를 매긴다 — 80점 이상 **또는 상위 15%** (0922 §4-B-6).

    예전 기준(70점 이상)으로는 목록 107건 중 41건이 「우선 검토」였다. 거의 전부가 그 이름을
    달면 담당자는 그 이름을 읽지 않는다. 그래서 「많아야 상위 15%」라는 뚜껑을 씌운다.

    **불가·마감은 세지 않는다.** 참가할 수 없는 사업이 상위 15% 자리를 차지하면, 담당자가
    실제로 손댈 수 있는 건이 「검토」로 밀려난다.
    """
    open_items = [
        i for i in items if not i.closed and i.eligibility_gate != "FAIL" and not i.relevance_note
    ]
    cut = priority.top_cut_of([i.company_priority_score for i in open_items if i.company_priority_score is not None])
    for item in items:
        if item.eligibility_gate == "FAIL" or item.relevance_note:
            # 게이트가 FAIL 이거나 회사와 관련이 낮으면 점수와 무관하게 「우선 검토」로 부르지
            # 않는다. 상위 15% 자리를 그런 건이 차지하면 실제로 손댈 수 있는 건이 밀려난다.
            item.priority_label = "마감" if item.closed else "후순위"
            continue
        item.priority_label = priority.label_of(
            item.company_priority_score, closed=item.closed, top_cut=None if item.closed else cut
        )


# --------------------------------------------------------------------------
# 진입점
# --------------------------------------------------------------------------


def build_summary(
    items: Sequence[Any], *, days: int, fetched_at: datetime | None
) -> OpportunitySummary:
    """건수의 **단일 분모**를 만든다 (0920 §4-B-2 · ISSUE-075).

    같은 화면 안에서도 숫자가 갈려 있었다 — 머리는 「전체 107 · 마감 1 제외」, 바로 아래
    탭은 「전체 (104)」. 마감을 세는 기준이 달랐기 때문이다: 응답의 `closed_count` 는
    **시연용 고정을 빼고** 세는데, 목록 화면은 고정이든 아니든 마감 행을 숨겼다.

    그래서 여기서 한 벌만 세고 화면은 그대로 적는다. 세는 규칙은 셋이다.

    - 「마감 전」은 정말 마감 전만이다 — 시연용 고정이라도 마감이면 들어가지 않는다.
    - 「마감」은 시연용 고정을 **포함**하고, 그중 몇 건이 고정인지 따로 말한다.
    - 「우선 검토」는 **전체 기준**이다. 레이더가 그린 12건 안에서 세면 같은 순간
      목록과 다른 숫자가 된다.
    """
    open_items = [i for i in items if not i.closed]
    return OpportunitySummary(
        open_total=len(open_items),
        open_g2b=sum(1 for i in open_items if i.source_type == "g2b"),
        open_bizinfo=sum(1 for i in open_items if i.source_type == "bizinfo"),
        open_manual=sum(1 for i in open_items if i.source_type == "manual"),
        priority=sum(1 for i in open_items if i.priority_label == "우선 검토"),
        # 참가·신청할 수 없다고 판정한 건수. **거르기 전에** 센다 (0922 §4-D-2 · ISSUE-087).
        # 예전에는 거른 뒤에 세어 언제나 0 이었고, 화면은 「1,052건을 숨겼다」를 말할 수 없었다.
        blocked=sum(1 for i in open_items if getattr(i, "eligibility_gate", None) == "FAIL"),
        closed=sum(1 for i in items if i.closed),
        closed_pinned=sum(1 for i in items if i.closed and i.pinned),
        days=days,
        fetched_at=fetched_at,
        # 「새 공고」 기간은 대시보드 띠를 만드는 서비스가 정한다. 목록이 따로 정하지 않는다.
        new_days=daily_digest_service.DEFAULT_NEW_DAYS,
    )


def _oldest_fetched_at(
    g2b_result: "procurement_service.ProcurementResult | None", bizinfo_at: datetime | None
) -> datetime | None:
    """두 출처의 캐시 시각 중 **오래된 쪽** (0920 §4-B-5 · ISSUE-078-a).

    한쪽이 낡았으면 목록 전체가 그만큼 낡은 것이다. 새것 쪽을 적으면 담당자가 낡은 줄을
    방금 받은 것으로 읽는다.

    기업마당은 정상적으로 시각이 없을 수 있다(저장된 것 없이 샘플로 답할 때). 그때는 있는
    쪽 하나를 쓰고, 둘 다 없으면 None 이다 — 지어내지 않는다.
    """
    stamps = [
        moment
        for moment in (g2b_result.fetched_at if g2b_result else None, bizinfo_at)
        if moment is not None
    ]
    if not stamps:
        return None
    aware = [m if m.tzinfo else m.replace(tzinfo=timezone.utc) for m in stamps]
    return min(aware)


def ranking_method_of(organization_id: str) -> str:
    """회사가 고른 순서 방식(37차 §3-A). 파일 · 칸이 없으면 「score」(점수순)."""
    from app.services import delivery_capacity_service

    method = delivery_capacity_service.load(organization_id).ranking_method
    return method if method in practical.DEFAULT_SORT_OF_METHOD else "score"


def default_sort_of(organization_id: str) -> str:
    """정렬을 고르지 않았을 때 — 회사 방식의 기본 정렬(샘플에듀 실무순 · 그 밖 점수순)."""
    return practical.DEFAULT_SORT_OF_METHOD[ranking_method_of(organization_id)]


def _home_of(item: UnifiedOpportunity) -> bool:
    """광주 · 전남 기관인가 — 기업마당은 수행기관도 본다(38차 PRACTICAL-05)."""
    return priority.home_ground(item.agency, item.demand_agency or item.executing_agency) is not None


def _annotate_practical(items: list[UnifiedOpportunity], *, organization_id: str, now: datetime) -> None:
    from app.services import delivery_capacity_service

    ceiling = delivery_capacity_service.load(organization_id).budget_ceiling_krw or priority.RECOMMENDED_CEILING_KRW
    practical.annotate(items, now=now, ceiling_krw=ceiling, home_of=_home_of)


def _apply_practical(items: list[UnifiedOpportunity], *, organization_id: str, now: datetime) -> None:
    """실무 우선순위 값(시간 등급 · 분류 · D8 · 자리)을 매긴다. **점수 · 판정은 그대로다** (37차 §3-B)."""
    _annotate_practical(items, organization_id=organization_id, now=now)
    # 40차 결정 2 · D24 — AI 적합도 「아님」 꼬리표(켠 회사만 · 본업 덩어리 · 저장한 답)를 순서 매기기 전에 단다 — 「주제 확인」과 같은 자리
    from app.services import ai_fit_service

    ai_fit_service.apply_notes(items, organization_id)
    practical.order(items, now=now, home_of=_home_of)
    _group_same_programs(items)


#: 같은 사업 열쇠에서 뺄 앞머리 — 「[경기]」 · 「[전남광주]」 같은 지역 괄호.
_REGION_BRACKET_RE = re.compile(r"^\s*[\[［(（][^\]］)）]{1,12}[\]］)）]\s*")


def _program_key(title: str) -> str:
    return prespec_service.title_key(_REGION_BRACKET_RE.sub("", title or ""))


def _group_same_programs(items: list[UnifiedOpportunity]) -> None:
    """같은 기업마당 사업이 여러 운영기관으로 오면 붙여 세우고 광주 · 전남 운영기관을 앞에 둔다(43차 Q9 · BIZ-03).

    「미래내일 일경험」이 경기 · 전남 · 대한상의 셋으로 2 · 5 · 8위에 흩어졌다. 묶음의 자리는 가장 앞선 행의 자리이고, 기업마당 안의
    순번만 다시 나눠 준다(다른 출처 · 점수 · 판정은 그대로)."""
    biz = sorted((i for i in items if i.source_type == "bizinfo"), key=lambda i: i.practical_order)
    groups: dict[str, list[UnifiedOpportunity]] = {}
    for item in biz:
        groups.setdefault(_program_key(item.title), []).append(item)
    multi = {k: v for k, v in groups.items() if len(v) > 1 and k}
    if not multi:
        return
    arranged: list[UnifiedOpportunity] = []
    placed: set[str] = set()
    for item in biz:
        key = _program_key(item.title)
        if key not in multi:
            arranged.append(item)
            continue
        if key in placed:
            continue
        placed.add(key)
        members = sorted(multi[key], key=lambda m: (0 if _home_of(m) else 1, m.practical_order))
        home = any(_home_of(m) for m in members)
        for member in members:
            member.same_program_note = f"같은 사업 {len(members)}건" + (" · 광주 · 전남 운영기관 먼저" if home else "")
        arranged.extend(members)
    for order, item in zip(sorted(i.practical_order for i in biz), arranged):
        item.practical_order = order


async def list_opportunities(
    *,
    context: AnalysisContext,
    source: str = "all",
    days: int = 14,
    sort: str | None = None,
    limit: int | None = None,
    include_closed: bool = False,
    include_low: bool = False,
    include_blocked: bool = False,
    refresh: bool = False,
    now: datetime | None = None,
    for_radar: bool = False,
    with_prepare: bool = False,
) -> UnifiedOpportunityListResponse:
    current = now or storage.utc_now()
    organization_id = context.organization_id
    profile = company_service.load_profile(organization_id)
    try:
        organization_name = organization_service.get_organization(organization_id).display_name
    except organization_service.OrganizationNotFoundError:
        organization_name = organization_id

    want_g2b = source in ("all", "g2b")
    want_bizinfo = source in ("all", "bizinfo")
    want_manual = source in ("all", "manual")

    async def procurements():
        if not want_g2b:
            return [], None, None, None
        return await _collect_procurements(
            organization_id=organization_id,
            context=context,
            profile=profile,
            days=days,
            now=current,
            include_low=include_low,
            refresh=refresh,
        )

    async def support():
        if not want_bizinfo:
            return [], None, None, bizinfo_service.FIELD_MAPPING_VERIFIED, None
        return await _collect_support(
            organization_id=organization_id,
            profile=profile,
            now=current,
            refresh=refresh,
            # 100 으로 묶여 있었다. 그 상한이 **기준 답안 16건 중 15건을 목록에서 지우고**
            # 있었다 (0921 §4-A-4) — 회사에 맞는 지원사업이 없는 것이 아니라 못 본 것이었다.
            count=bizinfo_client.FULL_COUNT,
        )

    (
        (g2b_items, g2b_source, g2b_error, g2b_result),
        (biz_items, biz_source, biz_error, verified, biz_fetched_at),
    ) = await asyncio.gather(procurements(), support())

    # 39차 결정 1 — 사전규격은 **입찰 목록 · 실무순 · 순번 · 건수 · limit 밖**이다(따로 「선제준비」 칸 · 따로 순서).
    pre_items = [i for i in g2b_items if i.opportunity_type == "pre_spec"]
    g2b_items = [i for i in g2b_items if i.opportunity_type != "pre_spec"]
    prepare: PrepareSection | None = None
    # 회사 방식(37차 §3-A) — 선제준비 칸 순서에도 쓴다(41차 TOPIC-02 — 점수순 회사는 주제로 순서를 바꾸지 않는다)
    method = ranking_method_of(organization_id)
    if with_prepare and want_g2b:
        _annotate_practical(pre_items, organization_id=organization_id, now=current)
        # 40차 마지막 검토 — 선제준비 「보임」도 AI 답의 대상이다(`ai_fit_service.targets`) — 꼬리표를 달아야 칸 안 순서(`topic_rank`)에 닿는다
        from app.services import ai_fit_service

        ai_fit_service.apply_notes(pre_items, organization_id)
        main_ids = {i.id for i in g2b_items}
        prepare = prespec_service.section(
            pre_items,
            now=current,
            main_ids=main_ids,
            # 40차 PRESPEC-02 — 본공고 원본의 발주계획 번호로 「본공고 나옴」을 다시 정한다(합쳐 남긴 옛 계획 행)
            plan_to_main=prespec_service.plan_mains([v.notice for v in (g2b_result.notices if g2b_result else [])], main_ids),
            by_topic=method == "practical",
        )

    # 38차 §3-E — 직접 넣은 공고. 회사 폴더의 파일과 규칙뿐이다(바깥을 부르지 않는다). 한 출처가 실패해도 다른 출처는 살린다.
    manual_items: list[UnifiedOpportunity] = []
    manual_error: str | None = None
    if want_manual:
        try:
            manual_items = manual_notice_service.unified_items(
                organization_id=organization_id, profile=profile, now=current, context=context
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("직접 넣은 공고를 읽지 못했습니다: %s", exc)
            manual_error = f"직접 넣은 공고 읽기 오류: {exc}"
    items = [*g2b_items, *biz_items, *manual_items]
    # 회사 방식(37차 §3-A) — 정렬을 고르지 않았으면 그 방식의 기본 정렬이다(샘플에듀 실무순 · 그 밖 점수순).
    chosen_sort = sort if sort in SORTS else practical.DEFAULT_SORT_OF_METHOD[method]
    # 실무 우선순위 값은 정렬과 상관없이 늘 매긴다 — 화면이 다시 부르지 않고 정렬을 바꿀 수 있게(`practical_order`).
    _apply_practical(items, organization_id=organization_id, now=current)
    # 44차 M4 — 저장된 결정 한 줄(입찰 · 지원사업 같은 꼴) · 브리핑 · 엑셀 · 이번 주 할 일이 같은 값을 쓴다
    from app.services import decision_service

    decisions = decision_service.decisions_for(context)
    for item in items:
        item.decision_text = practical.decision_text(item, decisions.get(item.id))
    # **순위·라벨을 먼저 매긴다.** 「우선 검토」가 상위 15% 를 보기 때문에(0922 §4-B-6),
    # 분모를 세기 전에 라벨이 확정돼 있어야 `summary.priority` 가 맞는다.
    items = sort_opportunities(items, chosen_sort)
    if source == "all" and chosen_sort in ("practical", "priority"):
        items = interleave_sources(items, chosen_sort)
    closed_count = sum(1 for i in items if i.closed and not i.pinned)
    # 분모는 **자르기(limit)·마감 거르기·불가 거르기보다 먼저** 센다 (0922 §4-D-2 · ISSUE-087).
    # 예전에는 `blocked_count` 를 거른 «뒤»에 세어 언제나 0 이었다 — 「1,052건을 숨겼다」는
    # 사실을 화면이 말할 수 없었다.
    summary = build_summary(items, days=days, fetched_at=_oldest_fetched_at(g2b_result, biz_fetched_at))
    # 화면의 「n건 숨김」은 **마감 전 기준**이다 — 마감된 불가는 이미 「마감」으로 세어진다.
    # 분모(summary)와 같은 수여야 한 화면이 두 숫자를 말하지 않는다.
    blocked_count = summary.blocked
    if not include_closed:
        # 시연용으로 고정해 둔 공고는 마감이어도 남긴다 (ISSUE-056).
        #
        # 고정 공고는 저장된 자료가 있어 마감 뒤에도 분석 화면이 그대로 열린다. 그런데 목록에서
        # 사라지면 시연이 «오늘 열려 있는 공고»에 묶인다 — 실제로 고정 4건 중 3건이 이미 마감이라
        # 큐시트가 가리키는 공고가 화면에 없었다. 마감 배지와 「참여 곤란」 상태는 그대로 둔다.
        items = [i for i in items if not i.closed or i.pinned]
    # 참가할 수 없는 사업은 기본으로 숨긴다 (0921 §4-C-2).
    #
    # 기업마당을 전부 받으면서 목록이 1,712건이 됐고 그중 1,002건이 「불가」다 — 대부분 다른
    # 지역 사업이다. 담당자가 볼 수 없는 것을 매번 스크롤해 지나가게 두지 않는다.
    # **지우는 것이 아니다** — 「불가 포함」을 켜면 그대로 돌아온다. 분모(summary)는 위에서
    # 이미 셌으므로 건수가 흔들리지 않는다.
    if not include_blocked:
        # 시연용으로 고정해 둔 공고는 불가여도 남긴다 (ISSUE-056 과 같은 이유).
        items = [i for i in items if i.eligibility_gate != "FAIL" or i.pinned]

    if for_radar:
        # 레이더는 나라장터 「관련 낮음」을 접을 곳이 없다 — 순번 · 건수 · 자르기 전에 뺀다(「그림에 보임 n / N」의 N 이 그릴 수 있는
        # 수여야 한다 · 38차 §5 검토 · 사전규격은 39차부터 목록에 아예 없다). 요약(summary)은 위에서 그대로다.
        # 직접 넣은 공고도 레이더 섹터(나라장터 · 기업마당 둘)에 그리지 않는다 — 화면에서만 빼면 「그림에 올림 n / N」의 N 이 하나씩 컸다(39차 FRONTEND-06).
        # 43차 M24 · NUM-06 — 기업마당 관련 낮음(비추천)과 마감된 고정 예시도 뺀다(레이더 210 · 526 vs 사업기회 206 · 212 · 풀이 「비추천 뺌」이 기업마당에는 거짓이었다)
        items = [
            item for item in items
            if item.source_type != "manual" and item.practical_group != "비추천" and not (item.source_type == "g2b" and item.relevance_note)
            and not (item.pinned and item.closed)
        ]

    # 칩의 분모를 **지금 목록**으로 다시 매긴다 (0925 §4-D-2). 라벨·요약은 위에서 확정됐다.
    renumber_sources(items)

    # 갈래별 건수는 **마감 거르기 뒤·자르기 전**에 센다.
    #   - 마감 뒤에 세는 이유: 칩이 「교육 4」인데 목록에 3건만 있으면 담당자가 사라진 1건을 찾는다.
    #     마감 여부는 include_closed 로 이미 사용자가 고른 것이라 그 선택을 따라야 한다.
    #   - 자르기 전에 세는 이유: limit 은 「상위 N건만 그린다」는 화면 사정이지 갈래의 크기가 아니다.
    track_counts: dict[str, int] = {}
    for item in items:
        for track in item.work_tracks:
            track_counts[track] = track_counts.get(track, 0) + 1

    # 건수는 **자르기 전**에 센다. track_counts 와 같은 기준이어야 한다.
    #
    # 예전에는 total_count·g2b_count·bizinfo_count 를 자른 뒤에 셌다. 레이더가 limit=20 으로
    # 부르면 「데이터 상태」에 「기업마당 16건」이라고 적혔는데 실제 수집은 100건이었고,
    # 같은 응답의 source_total(자르기 전)은 100 이라 한 화면이 두 가지 숫자를 말했다.
    # limit 은 「상위 N건만 그린다」는 화면 사정이지 수집한 양이 아니다.
    total_count = len(items)
    g2b_count = sum(1 for i in items if i.source_type == "g2b")
    bizinfo_count = sum(1 for i in items if i.source_type == "bizinfo")
    manual_count = sum(1 for i in items if i.source_type == "manual")
    returned_count = total_count

    if limit is not None and limit > 0:
        # 자르기는 **출처마다** 한다(38차 PRACTICAL-01 · 「순위는 갈래 안에서만」). 실무순은 두 출처를 한 줄로 세우므로
        # 한 줄 앞에서 자르면 기업마당 T1~T4 가 나라장터 긴급(T5 · T6)을 밀어내 대시보드 고르기 칸 · 레이더에서 나라장터가 빠졌다.
        if source == "all":
            taken: dict[str, int] = {}
            kept: list[UnifiedOpportunity] = []
            for item in items:
                if taken.get(item.source_type, 0) < limit:
                    kept.append(item)
                    taken[item.source_type] = taken.get(item.source_type, 0) + 1
            items = kept
        else:
            items = items[:limit]
        returned_count = len(items)

    return UnifiedOpportunityListResponse(
        organization_id=organization_id,
        organization_name=organization_name,
        total_count=total_count,
        g2b_count=g2b_count,
        bizinfo_count=bizinfo_count,
        manual_count=manual_count,
        returned_count=returned_count,
        closed_count=closed_count,
        blocked_count=blocked_count,
        source_status={"g2b": g2b_source, "bizinfo": biz_source, "manual": "manual" if manual_items else None},
        source_errors={"g2b": g2b_error, "bizinfo": biz_error, "manual": manual_error},
        # 「캐시」라고만 적으면 키가 없어서인지 일부러 안 부른 것인지 화면이 구분하지 못한다.
        frozen=not (procurement_service.live_fetch_enabled() and bizinfo_service.live_fetch_enabled()),
        # 「응답을 만든 시각」이 아니라 「자료를 마지막으로 받아온 시각」이다 (ISSUE-078-a).
        # 예전에는 여기에 `current` 를 넣어 대시보드 띠(캐시 시각)와 목록·레이더가 늘 달랐다.
        fetched_at=summary.fetched_at or current,
        summary=summary,
        # 나라장터를 「어떻게 받았는가」·「몇 번 불렀는가」 (0920 §4-A-3).
        # 레이더는 이 응답 하나만 보므로, 여기 없으면 레이더의 데이터 상태가 수집 방식을
        # 말할 길이 없다.
        collected_by=g2b_result.collected_by if g2b_result else None,
        collect_calls=g2b_result.collect_calls if g2b_result else None,
        auto_collect_at=auto_collect.fresh_success(current),
        # 40차 마지막 검토 — 예약 작업 상태 조회(PowerShell · 5분 메모)가 이벤트 루프를 멈추지 않게 스레드에서
        collect_state=CollectState(**(await asyncio.to_thread(auto_collect.collect_state, current))),
        source_fetched_at={"g2b": g2b_result.fetched_at if g2b_result else None, "bizinfo": biz_fetched_at},
        sort=chosen_sort,
        ranking_method=method,
        ranking_method_label=practical.RANKING_METHOD_LABELS[method],
        field_mapping_verified=verified,
        note=NOTE,
        track_counts=track_counts,
        items=items,
        prepare=prepare,
    )
