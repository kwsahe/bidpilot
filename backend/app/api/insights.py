"""지원사업(기업마당) · 통합 사업기회 · 발주기관 인사이트 · 공고 변경 이력 · 정정/Gold API.

- GET /api/support-programs                      기업마당 지원사업 (실호출→캐시→합성 샘플, 출처 표시)
- GET /api/business-opportunities                조달공고 + 지원사업 통합 목록 (점수 축은 섞지 않는다)
- GET /api/business-opportunities/prepare        「선제준비」 칸 — 사전규격 · 발주계획 (입찰 목록 밖 · 39차 결정 1)
- GET /api/agencies · /api/agencies/{name}       발주기관 인사이트 (캐시 공고에서 계산)
- GET /api/procurements/{id}/versions            공고 스냅샷 버전
- GET /api/procurements/{id}/changes             버전 간 변경 내역
- GET /api/rfp/{id}/corrections                  정정 이력
- PUT /api/rfp/{id}/items/{req_id}               담당자 정정 (유형·필수여부·내용·페이지·확정/반려)
- GET /api/exports/gold/{id}                     사람이 확정한 항목만 Gold 형식으로
- GET /api/business-opportunities/export         목록 내보내기 (md · csv · **xlsx**)
- GET /api/business-opportunities/exports        저장해 둔 엑셀 이력
- GET /api/business-opportunities/exports/{name} 저장해 둔 엑셀 다시 내려받기
- GET /api/collect-keywords                      「찾는 낱말」 — 기본 · 추가 낱말 · 오늘 바로 찾기 횟수 (2.0.7)
- POST /api/collect-keywords(/search · /remove)  추가 낱말 더하기(+ 바로 찾기) · 다시 찾기 · 지우기 (편집자 이상)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote, unquote

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api import deps
from app.api.procurement import refresh_was_ignored
from app.core import inflight, requester, storage
from app.schemas.business_opportunity import (
    PrepareSection,
    SupportProgramListResponse,
    UnifiedOpportunityListResponse,
)
from app.schemas.organization import AnalysisContext
from app.services import (
    audit_log_service,
    collect_keywords_service,
    llm_client,
    recollect_service,
    support_plan_service,
    opportunity_export_service,
    opportunity_brief_service,
    opportunity_workbook,
    agency_insight_service,
    bizinfo_client,
    bizinfo_service,
    eligibility_engine,
    eligibility_gap_service,
    export_store,
    organization_service,
    support_requirement_extractor,
    correction_service,
    daily_digest_service,
    notice_version_service,
    opportunity_service,
    performance_match_service,
    review_queue_service,
    procurement_service,
    rfp_parser,
    support_application_service,
    bizinfo_document_store,
    plan_draft_service,
    plan_form_service,
    plan_completeness_service,
    plan_export_service,
    plan_fill_service,
    plan_pdf_service,
    proposal_export,
    wording,
)

router = APIRouter(tags=["insights"])


@router.get("/api/support-programs", response_model=SupportProgramListResponse)
async def list_support_programs(
    request: Request,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> SupportProgramListResponse:
    """지원사업 목록. **조회만 한다** — 다시 받아 오려면 `POST /api/business-opportunities/refresh`.

    `refresh` 파라미터는 없앴다 (N1 · S8). 이유는 `api/procurement.py` 의 같은 자리에 적었다.
    """
    context = deps.context_or_400(organization_id, evidence_scope)
    response = await bizinfo_service.list_programs(organization_id=context.organization_id)
    if refresh_was_ignored(request):
        response.refresh_ignored = True
    return response


@router.get("/api/business-opportunities", response_model=UnifiedOpportunityListResponse)
async def list_business_opportunities(
    request: Request,
    organization_id: str | None = Query(default=None),
    source: str = Query(default="all", pattern="^(all|g2b|bizinfo|manual)$"),
    days: int = Query(default=14, ge=1, le=60),
    sort: str | None = Query(default=None, pattern="^(practical|priority|slack|deadline|recent|value)$"),
    limit: int | None = Query(default=None, ge=1, le=200),
    include_closed: bool = Query(default=False),
    include_low: bool = Query(default=False),
    # 참가할 수 없는 사업은 기본으로 숨긴다 (0921 §4-C-2). 켜면 그대로 돌아온다.
    include_blocked: bool = Query(default=False),
    # 레이더가 그리는 것만 — 사전규격(실무순 T3)과 나라장터 「관련 낮음」(D15 · 목록은 접어 둠)을 빼고 자른다(38차 §5 검토).
    for_radar: bool = Query(default=False),
    evidence_scope: str | None = Query(default=None),
) -> UnifiedOpportunityListResponse:
    """나라장터 입찰공고 + 기업마당 지원사업 통합 목록. **조회만 한다.**

    선택한 회사(organization_id) 기준 **검토 우선순위**로 정렬한다. 낙찰확률·선정확률이 아니다.
    원본 점수(추천등급·지원 적합도)는 source_specific_score 에 그대로 남는다.
    한쪽 출처가 실패해도 다른 쪽은 그대로 돌려주고 source_errors 에 사유를 남긴다.

    `refresh` 파라미터는 없앴다 (N1 · S8) — 다시 받아 오려면 아래 `POST …/refresh`.
    """
    # 목록 점수는 회사 프로필 규칙만 쓴다. 범위는 공개 데모 배포에서도 열리도록 기본값에 맡긴다.
    context = deps.context_or_400(organization_id, evidence_scope)
    response = await opportunity_service.list_opportunities(
        context=context,
        source=source,
        days=days,
        sort=sort,
        limit=limit,
        include_closed=include_closed,
        include_low=include_low,
        include_blocked=include_blocked,
        for_radar=for_radar,
    )
    if refresh_was_ignored(request):
        response.refresh_ignored = True
    return response


@router.get("/api/business-opportunities/prepare", response_model=PrepareSection)
async def prepare_section(
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
    part: Literal["all", "main", "folds"] = Query(default="all"),
) -> PrepareSection:
    """사업기회 「선제준비」 칸 — 사전규격(본업 · 다른 것 · 의견 마감 지남 · 본공고 나옴) · 발주계획. **조회만 한다.**

    입찰 목록과 같은 저장본을 읽는다. 본공고 잇기는 나라장터 30일 저장본으로 한다(브리핑과 같은 기간).
    45차 M2 — 한 번에 1.46MB(접힌 212 · 본공고 나옴까지)를 보내 처음 여는 데 10초가 넘었다. 화면은 `part=main`(보이는 칸 ·
    발주계획 · 접힌 묶음은 건수만)으로 열고, 묶음을 펼칠 때 `part=folds`(접힌 묶음 목록만)를 받는다. 기본 `all` 은 예전 그대로.
    """
    context = deps.context_or_400(organization_id, evidence_scope)
    listing = await opportunity_service.list_opportunities(
        context=context, source="g2b", days=PREPARE_DAYS, include_closed=True, include_blocked=True, with_prepare=True
    )
    section = listing.prepare or PrepareSection()
    # (2.0.6 fallback-2) 나라장터 목록을 못 읽으면 사전규격도 고르지 못한다 — 빈 칸이 「없음」으로 보이지 않게 사유를 싣는다.
    # 실패 판단은 브리핑과 같은 함수 — 실시간 받기가 실패해 저장본으로 대신한 날은 오류 글이 있어도 칸이 차 있다(실패 아님)
    section.source_error = opportunity_brief_service.failed_sources(listing).get("g2b")
    if part == "main":
        return section.model_copy(update={
            "others": [], "opinion_passed": [], "merged": [],
            "others_count": len(section.others), "opinion_passed_count": len(section.opinion_passed), "merged_count": len(section.merged),
        })
    if part == "folds":
        return section.model_copy(update={"items": [], "plans": []})
    return section


#: 「선제준비」 칸이 본공고를 잇는 나라장터 기간 — 브리핑 · 내보내기 기본값과 같다.
PREPARE_DAYS = 30


@router.get("/api/dashboard/today")
async def dashboard_today(
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
    # 기본값은 **서비스 상수 하나**에서 온다 (0920 §4-B-5 · ISSUE-078). 여기에 3·7 을 또
    # 적어 두면 한쪽만 고쳤을 때 띠와 목록이 다른 기간으로 세게 된다.
    new_days: int = Query(
        default=daily_digest_service.DEFAULT_NEW_DAYS, ge=1, le=30, description="「새 공고」로 볼 기간(일)"
    ),
    due_days: int = Query(
        default=daily_digest_service.DEFAULT_DUE_DAYS, ge=1, le=60, description="「곧 마감」으로 볼 기간(일)"
    ),
) -> dict:
    """「오늘 달라진 것」 한 줄 (0919 §4-B-1).

    **네트워크를 부르지 않는다** — 이미 받아 둔 목록에서만 센다. 그래서 「마지막으로 받아온
    시각」을 함께 돌려주고, 화면은 그것을 반드시 같이 적는다. 언제 기준인지 모르는 숫자는
    없느니만 못하다.
    """
    context = deps.context_or_400(organization_id, evidence_scope)
    return await daily_digest_service.build(context=context, new_days=new_days, due_days=due_days)


@router.get("/api/review-queue")
async def review_queue(
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """검토 중인 공고 — 손댄 흔적이 있는 것만 최근 활동 순으로 (0919 §4-B-3).

    **네트워크를 부르지 않는다.** 공고 제목·마감일은 이미 받아 둔 목록에서만 가져온다.

    「내 것 먼저」의 기준은 **서명된 신원**이다. 쿼리로 받지 않는다 — 남의 이름을 적어
    넣으면 남의 일이 내 일처럼 올라온다.
    """
    context = deps.context_or_400(organization_id, evidence_scope)
    return review_queue_service.build(context=context, mine=requester.current_recorded_by())


@router.get("/api/business-opportunities/export")
async def export_business_opportunities(
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
    source: str = Query(default="all", pattern="^(all|g2b|bizinfo|manual)$"),
    days: int = Query(default=30, ge=1, le=60),
    # brief = 「오늘 브리핑」 마크다운 한 장(37차 §3-H · 사업담당자 형식) — 화면 조건과 상관없이 전체(불가 포함 · 마감 뺌)를 회사 방식 순서로
        fmt: str = Query(default="md", alias="format", pattern="^(md|csv|xlsx|brief)$"),
    include_closed: bool = Query(default=False),
    include_blocked: bool = Query(default=False),
    sort: str | None = Query(default=None, pattern="^(practical|priority|slack|deadline|recent|value)$"),
    limit: int | None = Query(default=None, ge=1, le=3000),
    save: bool = Query(default=True, description="엑셀을 회사 폴더에도 남길지 (0924 §4-C-2)"),
) -> Response:
    """목록을 담당자가 **남에게 보낼 수 있는 형태**로 내려준다 (0921 §4-D-4 · 0924 §4-C).

    검수자가 손으로 만든 `apply_candidates.md/.csv`·`bizinfo_candidates.csv` 와 같은 열이다.
    **새 판정을 만들지 않는다** — 목록·갭 리포트가 이미 만든 값을 형식만 바꿔 적는다.

    `format=xlsx` 는 시트 일곱을 담고, 같은 워크북을 회사 폴더에도 한 벌 남긴다.

    이 경로는 `/{program_id}` 류보다 먼저 등록돼야 한다(같은 라우터 안에서는 위에서부터 맞춘다).
    """
    context = deps.context_or_400(organization_id, evidence_scope)
    if fmt == "brief":
        return await _brief_response(context=context, days=days, save=save)
    listing = await opportunity_service.list_opportunities(
        context=context,
        source=source,
        days=days,
        sort=sort,
        limit=limit,
        include_closed=include_closed,
        include_blocked=include_blocked,
    )
    if fmt != "xlsx":
        body, media_type, name = opportunity_export_service.build(listing, fmt)
        return Response(
            content=body,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
        )

    workbook, name, summary = await _build_workbook(
        listing,
        context=context,
        days=days,
        # 저장 이력의 「조건」은 **이 요청의 필터**를 적는다 (0925 §4-D-3).
        source=source,
        include_closed=include_closed,
        include_blocked=include_blocked,
    )
    if save:
        try:
            export_store.save(
                listing.organization_id,
                name=name,
                body=workbook,
                conditions=summary,
                rows=len(listing.items),
                sheets=list(opportunity_workbook.SHEET_NAMES),
            )
        except (OSError, ValueError):  # 저장에 실패해도 내려받기는 그대로 나간다
            pass
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


async def _brief_listing(context, days: int):
    """브리핑이 보는 목록 — 두 출처 전부 · 불가 포함(제외 표) · 마감 뺌 · 회사 방식 순서(37차 §3-H)."""
    return await opportunity_service.list_opportunities(
        context=context, source="all", days=days, sort=None, include_closed=False, include_blocked=True, with_prepare=True
    )


async def _brief_response(*, context, days: int, save: bool) -> Response:
    """「오늘 브리핑」 마크다운. `save` 면 순위표를 회사 폴더에 남겨 다음 브리핑이 견준다(지난 브리핑 대비 변화)."""
    listing = await _brief_listing(context, days)
    now = storage.utc_now()
    previous = opportunity_brief_service.latest_snapshot(listing.organization_id, account=requester.current_recorded_by())
    body, snapshot = opportunity_brief_service.build_markdown(listing, now=now, previous=previous)
    if save:
        try:
            opportunity_brief_service.save_snapshot(listing.organization_id, snapshot, now=now)
        except OSError:  # 남기지 못해도 내려받기는 그대로 나간다 — 다음 브리핑이 이번 것과 견주지 못할 뿐
            pass
    name = opportunity_brief_service.filename(listing.organization_name, now=now)
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


#: 저장 이력에 적을 출처 이름.
EXPORT_SOURCE_LABELS: dict[str, str] = {"all": "전체", "g2b": "나라장터", "bizinfo": "기업마당", "manual": "직접 넣음"}

#: 저장 이력에 적을 정렬 이름 — 화면 정렬 목록(사업기회 목록)과 같은 말이다 (OPP-14).
EXPORT_SORT_LABELS: dict[str, str] = {
    "practical": "실무 우선순위순",
    "priority": "회사 기준 검토 우선순위순",
    "slack": "마감 여유순",
    "deadline": "마감 임박순",
    "recent": "최신 등록순",
    "value": "예산순",
}


def export_conditions(
    listing,
    *,
    days: int,
    source: str,
    include_closed: bool,
    include_blocked: bool,
) -> str:
    """저장 이력의 「조건」 한 줄 (0925 §4-D-3).

    10차의 이 줄은 「최근 30일 · priority 정렬 · 200건 (나라장터 105 · 기업마당 1605)」
    이었다. 괄호 안의 둘은 **내보낸 행이 아니라 받아 둔 풀의 크기**다 — 200행짜리 파일을
    다시 열려는 사람이 「기업마당 1605건이 들어 있다」고 읽었다. 그리고 「마감 포함」·
    「불가 포함」을 켜고 뽑았는지가 어디에도 없어서, 같은 조건을 다시 만들 수 없었다.

    적는 것: 어떤 조건으로 걸렀나 + **그래서 몇 행이 들어갔나**(출처별).
    """
    rows = listing.items
    g2b = sum(1 for i in rows if i.source_type == "g2b")
    bizinfo = sum(1 for i in rows if i.source_type == "bizinfo")
    manual = sum(1 for i in rows if i.source_type == "manual")
    parts = [
        f"출처 {EXPORT_SOURCE_LABELS.get(source, source)}",
        f"최근 {days}일",
        EXPORT_SORT_LABELS.get(listing.sort, "회사 기준 검토 우선순위순"),
    ]
    if include_closed:
        parts.append("마감 포함")
    if include_blocked:
        parts.append("불가 포함")
    parts.append(f"내보낸 {len(rows)}행 (나라장터 {g2b} · 기업마당 {bizinfo}{f' · 직접 넣음 {manual}' if manual else ''})")
    return " · ".join(parts)


async def _build_workbook(
    listing,
    *,
    context,
    days: int,
    source: str = "all",
    include_closed: bool = False,
    include_blocked: bool = False,
) -> tuple[bytes, str, str]:
    """워크북 · 파일 이름 · 조건 한 줄. **판정은 다시 만들지 않고 규칙만 다시 읽는다.**"""
    try:
        gaps = await eligibility_gap_service.build(context=context, days=days)
    except Exception:  # noqa: BLE001 — 갭을 못 세도 나머지 시트는 나간다
        gaps = {"gaps": []}

    # 「자격 판정 근거」 시트 — 목록에 실린 것 중 **앞에서부터** 본다.
    #
    # 규칙을 다시 돌리는 것이라 1,700건을 전부 하면 파일 하나 만드는 데 몇십 초가 걸린다.
    # 잘랐다는 사실은 시트 끝에 한 줄로 적는다 — 조용히 줄이지 않는다 (0924 §4-C-1).
    company = eligibility_engine.company_facts_for(listing.organization_id)
    regions = organization_service.preferred_regions(listing.organization_id)
    profile = organization_service.load_profile(listing.organization_id)
    domains = tuple(profile.business_domains)
    today = storage.kst_today()
    moment = storage.utc_now()
    rules: dict[str, list] = {}
    notices = {v.notice.id: v.notice for v in (await procurement_service.list_ai_candidates(days=days)).notices}
    for item in listing.items[: opportunity_workbook.MAX_RULE_ROWS]:
        if item.source_type == "g2b":
            notice = notices.get(item.id)
            if notice is not None:
                rules[item.id] = eligibility_engine.evaluate_notice_fields(
                    notice.raw_data, as_of=moment, regions=regions, company=company, notice_id=item.id
                )
            continue
        program = _support_program(item.id)
        if program is None:
            continue
        requirements = support_requirement_extractor.load(program.id)
        if requirements.document_read:
            results, _ = support_application_service.biz_rules_v2(
                program, requirements, company=company, today=today, profile_domains=domains
            )
        else:
            results = support_application_service.biz_rules(program, company=company, today=today)
        rules[item.id] = results

    # 「브리핑」 시트(37차 §3-H) — 화면 조건과 상관없이 브리핑과 같은 목록(전체 · 불가 포함 · 회사 방식)
    try:
        brief_listing = await _brief_listing(context, days)
        brief = opportunity_brief_service.sheet_rows(brief_listing, now=moment)
    except Exception:  # noqa: BLE001 — 브리핑 시트를 못 만들어도 나머지 시트는 나간다
        brief = None
    body = opportunity_workbook.build(listing, gaps=gaps, rules=rules, brief=brief)
    name = opportunity_workbook.filename(listing.organization_name)
    summary = export_conditions(
        listing,
        days=days,
        source=source,
        include_closed=include_closed,
        include_blocked=include_blocked,
    )
    return body, name, summary


def _support_program(program_id: str):
    """받아 둔 기업마당 목록에서 프로그램 하나. 못 찾으면 None. (2.0.6) 찾기는 「검토 중」과 같은 한 함수."""
    return support_application_service.cached_programs({program_id}).get(program_id)


@router.get("/api/business-opportunities/exports")
async def list_saved_exports(
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """저장해 둔 엑셀 이력 (0924 §4-C-2). 날짜·조건·건수를 함께 돌려준다."""
    context = deps.context_or_400(organization_id, evidence_scope)
    files = export_store.load_index(context.organization_id)
    return {
        "organization_id": context.organization_id,
        "count": len(files),
        "files": files,
        "note": "내보낸 워크북을 회사 폴더에 남긴 이력입니다. 비공개이며 Git 이 추적하지 않습니다.",
    }


@router.get("/api/business-opportunities/exports/{name}")
async def download_saved_export(
    name: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> Response:
    """저장해 둔 엑셀을 다시 내려받는다. 이력에 없는 이름은 404 다."""
    context = deps.context_or_400(organization_id, evidence_scope)
    body = export_store.read(context.organization_id, unquote(name))
    if body is None:
        raise HTTPException(status_code=404, detail="저장된 내보내기 파일이 아닙니다.")
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(unquote(name))}"},
    )


@router.post("/api/business-opportunities/refresh", response_model=UnifiedOpportunityListResponse)
async def refresh_business_opportunities(
    organization_id: str | None = Query(default=None),
    source: str = Query(default="all", pattern="^(all|g2b|bizinfo|manual)$"),
    days: int = Query(default=14, ge=1, le=60),
    sort: str | None = Query(default=None, pattern="^(practical|priority|slack|deadline|recent|value)$"),
    limit: int | None = Query(default=None, ge=1, le=200),
    include_closed: bool = Query(default=False),
    include_low: bool = Query(default=False),
    # 참가할 수 없는 사업은 기본으로 숨긴다 (0921 §4-C-2). 켜면 그대로 돌아온다.
    include_blocked: bool = Query(default=False),
    evidence_scope: str | None = Query(default=None),
) -> UnifiedOpportunityListResponse:
    """통합 목록을 **다시 받아온다** (S8).

    위 GET 의 `refresh=true` 와 같은 일이지만 POST 다. 바깥(나라장터·기업마당)을 부르고
    캐시 파일을 덮어쓰는 일이라 조회가 아니다. POST 라야 역할 검사(편집자 이상)와
    활동 기록이 붙고, 다른 사이트의 링크 한 번으로 도달하지 않는다.
    시연 고정 모드에서는 이 경로도 저장된 목록만 쓴다 — 고정이 먼저다.
    """
    context = deps.context_or_400(organization_id, evidence_scope)
    return await opportunity_service.list_opportunities(
        context=context,
        source=source,
        days=days,
        sort=sort,
        limit=limit,
        include_closed=include_closed,
        include_low=include_low,
        include_blocked=include_blocked,
        refresh=True,
    )


class RecollectRequest(BaseModel):
    source: Literal["g2b", "bizinfo"]


@router.post("/api/business-opportunities/recollect")
async def recollect_business_opportunities(
    body: RecollectRequest,
    organization_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """사업기회 「재수집」 단추 (20차 §4-G · 담당자 「사업기회에 재수집 버튼 추가. 나라장터, 기업마당으로.」).

    그 출처의 실호출 문이 꺼져 있으면(시연 고정 모드) **네트워크를 부르지 않고** 409 와 사유를 돌려준다.
    이미 받는 중 · 캐시 축소 차단 · 받지 못함도 409 — 저장된 목록은 그대로다. 결과는 활동 기록에 남긴다.
    """
    who = requester.current()
    try:
        result = await recollect_service.recollect(body.source)
    except recollect_service.RecollectRefusedError as exc:
        _audit_recollect(who, organization_id, body.source, 409, None)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit_recollect(who, organization_id, body.source, 200, result)
    return result


def _audit_recollect(
    who: Any, organization_id: str | None, source: str, status: int, result: dict[str, Any] | None
) -> None:
    audit_log_service.append(
        user=who.user if who is not None else "local",
        role=who.role if who is not None else "local",
        method="POST",
        path="/api/business-opportunities/recollect",
        organization_id=organization_id,
        status=status,
        event={
            "kind": "recollect",
            "source": source,
            "before": (result or {}).get("before", {}).get("count"),
            "after": (result or {}).get("after", {}).get("count"),
        },
    )


class CollectKeywordRequest(BaseModel):
    word: str = Field(max_length=200)
    search: bool = True
    expected_updated_at: datetime | None = None


class CollectKeywordSearchRequest(BaseModel):
    word: str = Field(max_length=200)


class CollectKeywordRemoveRequest(BaseModel):
    word: str = Field(max_length=200)
    expected_updated_at: datetime | None = None


@router.get("/api/collect-keywords")
async def get_collect_keywords() -> dict[str, Any]:
    """「찾는 낱말」(2.0.7) — 기본 낱말 · 추가 낱말(이 서버 전체에 하나) · 오늘 바로 찾기 횟수 · 바로 찾기 문. 읽기만(바깥 호출 없음)."""
    return collect_keywords_service.state()


@router.post("/api/collect-keywords")
async def add_collect_keyword(body: CollectKeywordRequest) -> dict[str, Any]:
    """추가 낱말을 더하고(저장이 먼저) `search` 면 그 낱말 하나만 바로 찾는다 (2.0.7 · 대표 결정 ①).

    규칙 · 10개 상한 → 400 · 그사이 남이 바꿈 → 409(`stale_write`). 문 꺼짐 · 하루 한도 · 아침 받기 중 · 받기 실패는 200 + `search_error`."""
    try:
        outcome = await recollect_service.add_keyword(
            body.word, by=requester.current_recorded_by(), expected_updated_at=body.expected_updated_at, search=body.search
        )
    except collect_keywords_service.KeywordRuleError as exc:
        _audit_keyword("/api/collect-keywords", "collect_keyword_add", body.word, 400)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    word = outcome.pop("word")
    _audit_keyword("/api/collect-keywords", "collect_keyword_add", word, 200, outcome["search"], outcome["search_error"])
    return outcome


@router.post("/api/collect-keywords/search")
async def search_collect_keyword(body: CollectKeywordSearchRequest) -> dict[str, Any]:
    """이미 더한 추가 낱말 하나를 다시 바로 찾는다 — 응답 꼴은 더하기와 같다. 목록에 없는 낱말은 400."""
    try:
        outcome = await recollect_service.research_keyword(body.word)
    except collect_keywords_service.KeywordRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    word = outcome.pop("word")
    _audit_keyword("/api/collect-keywords/search", "collect_keyword_search", word, 200, outcome["search"], outcome["search_error"])
    return outcome


@router.post("/api/collect-keywords/remove")
async def remove_collect_keyword(body: CollectKeywordRemoveRequest) -> dict[str, Any]:
    """추가 낱말을 지운다. 기본 낱말 · 목록에 없는 낱말은 400 · 그사이 남이 바꿈 → 409."""
    try:
        word = collect_keywords_service.remove(
            body.word, by=requester.current_recorded_by(), expected_updated_at=body.expected_updated_at
        )
    except collect_keywords_service.KeywordRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_keyword("/api/collect-keywords/remove", "collect_keyword_remove", word, 200)
    return {"state": collect_keywords_service.state()}


def _audit_keyword(
    path: str, kind: str, word: str, status: int, search: dict[str, Any] | None = None, search_error: str | None = None
) -> None:
    """활동 기록 — 낱말 · 바로 찾기 건수(찾았으면) · 못 찾은 사유 여부. 이 서버 전체 설정이라 회사 id 는 없다."""
    who = requester.current()
    audit_log_service.append(
        user=who.user if who is not None else "local",
        role=who.role if who is not None else "local",
        method="POST",
        path=path,
        organization_id=None,
        status=status,
        event={
            "kind": kind,
            "word": word[:40],
            "found": (search or {}).get("found"),
            "new": (search or {}).get("new_notices"),
            "search_error": search_error[:120] if search_error else None,
        },
    )


@router.get("/api/support-programs/{program_id}")
async def get_support_program(
    program_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """지원사업 1건 상세 + 신청 분석 계획. 입찰이 아니라 **신청** 흐름이다 (용어가 다르다)."""
    context = deps.context_or_400(organization_id, evidence_scope)
    try:
        return await support_application_service.build(program_id, context=context)
    except support_application_service.ProgramNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class PlanDraftRequest(BaseModel):
    """초안 만들기 요청 (25차 §4-B-5 · §4-C-8). 둘 다 선택 — 화면은 예전처럼 `{}` 를 보내도 된다."""

    task_no: int | None = None
    #: 확인 창을 거쳐 「AI 초안 대신 규칙 초안으로 바꾼다」고 한 경우만 참.
    force_rules: bool = False
    #: 사업계획서 작성 페이지(/plan)만 참을 보낸다 — CLI 전용 문(28차 §3-D). 쓰는 이는 `writer`(29차 §3-A · 기본 claude).
    use_claude: bool = False
    writer: Literal["claude", "codex"] = "claude"
    #: 「규칙 초안 만들기(AI 없이)」 · 「규칙 초안으로 바꾸기」 — 서버 AI 가 켜져 있어도 끈다(29차 R28-01). `use_claude` 보다 앞선다.
    no_ai: bool = False


def _plan_form_view(context, program_id: str, form: dict) -> dict:
    """화면이 읽는 양식 요약 — 과제는 회사 낱말이 겹치는 순(규칙), 고르는 것은 사람."""
    from app.services import delivery_capacity_service, organization_service

    words: list[str] = []
    try:
        words += [str(d) for d in organization_service.load_profile(context.organization_id).business_domains or []]
    except Exception:  # noqa: BLE001
        pass
    capacity = delivery_capacity_service.load(context.organization_id)
    words += [s.name for s in capacity.skills] + list(capacity.business_items)
    view = {k: v for k, v in form.items() if k != "form_examples"}
    view["tasks"] = plan_form_service.rank_tasks(form.get("tasks") or [], words)
    # 과제소개서가 있으면 과제마다 「기준요건 및 요구사항」 ▪ 줄을 그대로 붙인다(고르기 돕기 · 점수 · 판정 없음 · 30차 §3-A)
    requirements = plan_form_service.annex_task_requirements(program_id) if view["tasks"] else {}
    if requirements:
        view["tasks"] = [{**t, "annex_requirements": requirements[t["no"]]} if t.get("no") in requirements else t for t in view["tasks"]]
    return view


def _plan_response(context, program_id: str, draft: dict, form: dict, **extra) -> dict:
    # 일반현황 자동 채움 — 화면에 보일 때만 회사자료로 채운다(저장본 · AI 본문에는 없다 · 29차 §3-B)
    draft = plan_fill_service.fill_for(draft, context.organization_id, context.evidence_scope)
    view = _plan_form_view(context, program_id, form)
    checklist = None
    if draft.get("sections"):
        try:
            region = eligibility_engine.company_facts_for(context.organization_id, evidence_scope=context.evidence_scope).location_region
        except Exception:  # noqa: BLE001 — 소재지를 몰라도 점검표는 낸다(가점만 「확인」)
            region = None
        checklist = plan_completeness_service.plan_completeness(draft, form, company_region=region)
    try:
        submit_blanks = None
        if draft.get("sections"):
            from app.services import organization_service

            meta = plan_export_service.export_meta(draft, form, notice=form.get("title") or "",
                                                   company=organization_service.load_profile(context.organization_id).name)
            submit_blanks = plan_export_service.submit_blank_count(draft, form, meta)
    except Exception:  # noqa: BLE001 — 못 세면 단추 옆 줄만 없다
        submit_blanks = None
    return {
        **draft,
        "sections": draft.get("sections", []),
        "form": view,
        "checklist": checklist,
        "submit_blanks": submit_blanks,  # 제출용 문서에 남는 「(담당자 입력)」 수(30차 §3-B)
        # **문이 둘이다** (ISSUE-130 · prompt_06 §4-A). `credit_ok` 는 「크레딧이 있는가」이고
        # `llm_live` 는 「AI 초안을 쓰기로 했는가」다.
        "credit_ok": llm_client.credit_ok(),
        "llm_live": llm_client.llm_live_enabled(),
        "llm_provider": llm_client.completion_provider(),
        **extra,
    }


@router.post("/api/support-programs/{program_id}/plan-draft")
async def create_support_plan_draft(
    program_id: str,
    body: PlanDraftRequest | None = Body(default=None),
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """사업계획서 초안을 **만든다** — 공고 양식 뼈대 위에 절마다 (25차 · prompt_15 §4-C).

    AI 가 꺼져 있거나 크레딧이 확인되지 않으면 규칙 초안(공고 양식 뼈대)이다. 과제가 여럿인 공고에서
    과제를 고르지 않았으면 AI 는 부르지 않는다(과제명 「(담당자 선택)」). 만드는 동안 이벤트 루프를 막지 않도록
    스레드에서 돌린다(`/health` 가 그동안에도 답한다 — ISSUE-031 과 같은 이유).
    """
    request = body or PlanDraftRequest()
    context = deps.context_or_400(organization_id, evidence_scope)
    # 같은 회사 · 같은 공고는 한 번에 하나만 — 쉬운 보기 두 단추 · 두 탭이 AI 를 두 번 부르지 않게 (27차 R26-05).
    try:
        with inflight.hold("plan_draft", context.organization_id, program_id):
            if request.use_claude and not request.no_ai:
                # 사업계획서 작성 문 — 서버에 한 건(28차 §3-D)
                with inflight.hold("plan_writer", message=inflight.PLAN_WRITER_BUSY):
                    return await _create_plan_draft(program_id, request, context)
            return await _create_plan_draft(program_id, request, context)
    except inflight.InFlightError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


async def _create_plan_draft(program_id: str, request: PlanDraftRequest, context: AnalysisContext) -> dict:
    try:
        analysis = await support_application_service.build(program_id, context=context)
        program, _fit, _source = await support_application_service.find_program(program_id, organization_id=context.organization_id)
    except support_application_service.ProgramNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    blocked = support_application_service.archived_block(program, _source)
    if blocked:
        # 마감돼 목록에서 빠진 사업 — 저장된 초안 보기 · 내려받기는 되고 새 초안은 막는다(33차 §3-A-6).
        # 마감일 전에 목록에서 내려간 사업은 막지 않는다(34차 R33-A1)
        raise HTTPException(status_code=409, detail=blocked)
    try:
        form = plan_form_service.form_for(context, program_id, task_no=request.task_no)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    plain_id = program_id.removeprefix("bizinfo-")
    requirements = support_requirement_extractor.load(program_id)
    facts = next((s.get("company_facts") or [] for s in analysis.get("draft_outline") or [] if s.get("section") == "신청 자격 충족 설명"), [])
    company = plan_draft_service.company_sources(context.organization_id, context.evidence_scope)
    annex = await run_in_threadpool(plan_form_service.annex_excerpt, program_id, form.get("selected_task"))  # 32차 R31-32
    draft = await run_in_threadpool(
        plan_draft_service.generate,
        program=program,
        form=form,
        requirements=requirements,
        company=company,
        facts=list(facts),
        matches=analysis.get("evidence_matches") or [],
        notice_text=bizinfo_document_store.load_text(plain_id),
        annex=annex,
        company_name=(company.get("profile") or {}).get("name"),
        notice_version=analysis.get("document_note") or None,
        plan_writer=request.use_claude and not request.no_ai,
        writer=request.writer,
        no_ai=request.no_ai,
    )
    shown, kept = support_plan_service.save_draft(draft, context=context, program_id=program_id, force_rules=request.force_rules)
    # 유지한 옛 AI 초안은 저장본 그대로라 옛 경고 글이 섞여 있다 — GET 처럼 새 말로(32차 마지막 검토)
    shown = plan_draft_service.read_view(wording.modernize(shown), form)
    if kept:
        # 옛 AI 초안을 유지했다 — 과제 선택도 그 초안의 것을 둔다(새 과제와 옛 초안이 짝이 되지 않게 · ISSUE-148).
        # 왜 새 AI 초안이 없는지를 함께 싣는다(AI 꺼짐 · 과제 미선택 · AI 작성 실패 사유).
        saved_form = plan_form_service.form_for(context, program_id)
        reason = plan_draft_service.rules_reason(draft)
        plan_form_service.remember_kept(context, program_id, reason)  # 다시 열어도 사유가 남게(R26-15)
        return await run_in_threadpool(_plan_response, context, program_id, shown, saved_form, kept_llm_draft=True, kept_reason=reason)
    plan_form_service.save_form(context, program_id, form)  # 새 초안이 실제로 저장될 때만 과제 선택을 저장한다
    return await run_in_threadpool(_plan_response, context, program_id, shown, form, kept_llm_draft=False)


# 사업계획서 초안 내려받기는 DOCX · PDF(29차 §3-D) — HWPX 는 28차 담당자 결정으로 없앴다(`?format=hwpx` 는 422).
_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PDF_MEDIA = "application/pdf"


@router.get("/api/support-programs/{program_id}/plan-draft/export")
async def export_support_plan_draft(
    program_id: str,
    format: Literal["docx", "pdf"] = Query(default="docx"),
    variant: Literal["submit", "review"] = Query(default="submit"),
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> Response:
    """저장된 초안을 **양식 순서 그대로** 내려받는다 (25차 §4-E · 29차 §3-D). 디스크에 쓰지 않고 응답으로 바로 보낸다.

    `variant` — 제출용(표식 · 검토 메모 없음 · 빈칸만 노란 배경) · 검토용(문장 유형 · AI 회색 · 근거 · 검토 메모).
    `format=pdf` — Edge/Chrome 헤드리스로(없으면 Word) · 스레드에서 · 둘 다 없으면 503 과 이유.
    """
    context = deps.context_or_400(organization_id, evidence_scope)
    draft = wording.modernize(support_plan_service.load(context=context, program_id=program_id))
    if not draft.get("sections"):
        raise HTTPException(status_code=404, detail="사업계획서 초안이 아직 없습니다 — 먼저 초안을 만드세요")
    form = plan_form_service.form_for(context, program_id)
    draft = plan_draft_service.read_view(draft, form)  # 만들 때의 표시 · 거르기를 옛 초안에도(36차 PLAN-01)
    try:
        program, _fit, _source = await support_application_service.find_program(program_id, organization_id=context.organization_id)
        program_title = program.title
    except support_application_service.ProgramNotFoundError:
        program_title = form.get("title")
    title = form.get("title") or program_title or "사업계획서 초안"
    # 문서 조립 때 회사자료로 채운다(29차 §3-B) · 검토용 메모가 읽는 점검표도 같은 초안으로
    draft = plan_fill_service.fill_for(draft, context.organization_id, context.evidence_scope)
    try:
        region = eligibility_engine.company_facts_for(context.organization_id, evidence_scope=context.evidence_scope).location_region
    except Exception:  # noqa: BLE001
        region = None
    draft = {**draft, "checklist": plan_completeness_service.plan_completeness(draft, form, company_region=region)}
    values = plan_fill_service.company_values(context.organization_id, context.evidence_scope)
    meta = plan_export_service.export_meta(draft, form, notice=program_title or title, company=values.get("name"))
    if format == "pdf":
        try:
            payload, _method = await run_in_threadpool(plan_pdf_service.build_pdf, draft, form, title=program_title or title, variant=variant, meta=meta)
        except proposal_export.PdfConverterUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        media = _PDF_MEDIA
    else:
        payload = await run_in_threadpool(plan_export_service.build_docx, draft, form, title=program_title or title, variant=variant, meta=meta)
        media = _DOCX_MEDIA
    file_name = plan_export_service.export_file_name(program_title, format, variant=variant)
    return Response(
        content=payload,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(file_name)}"},
    )


# ---------------------------------------------------------------------------
# 과제소개서([별첨 1]) 받기 (30차 §3-A · 담당자 지시 「과제소개서도 다운받도록」)
# ---------------------------------------------------------------------------

ANNEX_BUSY = "과제소개서를 받는 중입니다 — 끝난 뒤 다시 누르세요"


def _bizinfo_item(program_id: str) -> dict[str, Any] | None:
    """받아 둔 기업마당 목록의 원본 항목(첨부 주소가 여기 있다). 없으면 None."""
    plain = program_id.removeprefix("bizinfo-")
    payload = storage.read_json(bizinfo_service.CACHE_FILE, default=None)
    items = payload.get("items") if isinstance(payload, dict) else None
    return next((i for i in items or [] if isinstance(i, dict) and str(i.get("pblancId")) == plain), None)


def _annex_view(program_id: str, item: dict[str, Any] | None) -> dict[str, Any]:
    attachment = bizinfo_service.annex_attachment(item) if item else None
    record = bizinfo_document_store.annex_record(program_id.removeprefix("bizinfo-"))
    return {
        "attachment": {"name": attachment.name, "ext": attachment.ext} if attachment else None,
        "record": record.to_dict() if record else None,
        "running": inflight.running("annex"),
    }


@router.get("/api/support-programs/{program_id}/annex")
async def get_support_annex(program_id: str) -> dict:
    """과제소개서 첨부가 있는가 · 받아 두었는가(받은 시각 · 쪽 · 글자 수 · 원래 이름). 바깥을 부르지 않는다."""
    item = await run_in_threadpool(_bizinfo_item, program_id)
    return _annex_view(program_id, item)


@router.post("/api/support-programs/{program_id}/annex")
async def fetch_support_annex(program_id: str) -> dict:
    """「과제소개서 받기」 단추 — 기업마당에서 **파일 1개**를 받아 `data/private/bizinfo_docs/{id}.annex1.*` 에 둔다.

    사람이 누를 때만 · 한 번에 하나(`inflight`) · 시연 고정 모드에서도 된다(추적 캐시를 바꾸지 않고 비공개 폴더에만 쓴다).
    공개(읽기 전용) 배포에서는 막는다. 받은 결과는 활동 기록에 한 줄.
    """
    deps.require_writable()
    item = await run_in_threadpool(_bizinfo_item, program_id)
    attachment = bizinfo_service.annex_attachment(item) if item else None
    if item is None or attachment is None or attachment.index is None:
        raise HTTPException(status_code=404, detail="이 공고에는 과제소개서 첨부가 없습니다")
    who = requester.current()
    try:
        with inflight.hold("annex", message=ANNEX_BUSY):
            record = await bizinfo_document_store.fetch_annex(item, attachment.index)
    except inflight.InFlightError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except bizinfo_client.BizinfoDocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit_log_service.append(
        user=who.user if who is not None else "local",
        role=who.role if who is not None else "local",
        method="POST",
        path=f"/api/support-programs/{program_id}/annex",
        organization_id=None,
        status=200 if record.status == "text" else 502,
        event={"kind": "annex", "program": record.program_id, "status": record.status, "pages": record.pages, "chars": record.chars},
    )
    if record.status != "text":
        raise HTTPException(status_code=502, detail=f"과제소개서를 받지 못했습니다 — {record.note or '원인 모름'}")
    return _annex_view(program_id, item)


@router.get("/api/plan-drafts/pdf-status")
async def plan_pdf_status() -> dict:
    """사업계획서 PDF 를 만들 수 있는가(29차 §3-D) — Edge/Chrome · Word 가 있는지만 본다(프로세스를 띄우지 않는다)."""
    return plan_pdf_service.pdf_status()


@router.get("/api/plan-writer/status")
async def plan_writer_status() -> dict:
    """사업계획서 작성 페이지의 「Claude 연결」 · 「Codex 연결」 줄 (28차 §3-D · 29차 §3-A) — 켜짐 · 모델 · 로그인 방법 · 요금제.

    꺼져 있으면 프로세스를 띄우지 않는다. 켜져 있으면 `claude auth status` · `codex login status`(로컬만 읽음)를 스레드에서 각 15초 안에.
    Claude 칸은 맨 위(28차 모양 그대로) · Codex 는 `codex` 아래.
    """
    return await run_in_threadpool(llm_client.claude_cli_status)


@router.get("/api/plan-drafts")
async def list_plan_drafts(
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """이 회사가 저장한 사업계획서 · 제안서 초안 목록 — **메타만**(본문 없음 · 28차 §3-D)."""
    context = deps.context_or_400(organization_id, evidence_scope)
    return {"items": support_plan_service.list_saved(context), "running": inflight.running("plan_writer")}


@router.get("/api/support-programs/{program_id}/plan-draft/versions")
async def list_plan_draft_versions(
    program_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """이전 판 목록(메타만 · 읽기 전용 · 되살리기 없음 · 만든 시각 최신 순). 잘못된 공고 id 는 400(29차 R28-08)."""
    context = deps.context_or_400(organization_id, evidence_scope)
    try:
        return {"items": support_plan_service.list_versions(context, program_id)}
    except storage.InvalidIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/support-programs/{program_id}/plan-draft/versions/{name}")
async def get_plan_draft_version(
    program_id: str,
    name: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """이전 판 하나(읽기 전용 · 되살리기 없음). 폴더에 없는 이름이면 404 · 잘못된 공고 id 는 400(29차 R28-08 — 500 이었다)."""
    context = deps.context_or_400(organization_id, evidence_scope)
    try:
        version = support_plan_service.load_version(context, program_id, name)
    except storage.InvalidIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if version is None:
        raise HTTPException(status_code=404, detail="그 이전 판을 찾지 못했습니다")
    return plan_draft_service.read_view(wording.modernize(version), plan_form_service.form_for(context, program_id))


@router.get("/api/support-programs/{program_id}/plan-draft")
async def get_support_plan_draft(
    program_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """저장된 초안 + 양식 요약(과제 목록 · 고른 과제) + 완성도 점검표. 아직 만든 적이 없으면 `sections` 가 빈 배열이다."""
    context = deps.context_or_400(organization_id, evidence_scope)
    form = plan_form_service.form_for(context, program_id)
    draft = plan_draft_service.read_view(wording.modernize(support_plan_service.load(context=context, program_id=program_id)), form)
    # 마지막 요청이 옛 AI 초안을 유지했으면 그 사유를 다시 싣는다 — 단계를 여닫아도 한 줄이 사라지지 않게(27차 R26-15).
    reason = plan_form_service.kept_reason(context, program_id) if draft.get("generated_by") == "llm" else None
    extra = {"kept_llm_draft": True, "kept_reason": reason} if reason else {}
    # 새로고침한 화면이 「만드는 중」을 이어 기다린다 (28차 §3-D)
    extra["in_progress"] = inflight.running("plan_draft", context.organization_id, program_id)
    # 양식 보기(과제소개서 ▪ 줄) · 점검표가 파일을 읽는다 — 이벤트 루프를 막지 않게 스레드에서(32차 R31-32)
    return await run_in_threadpool(_plan_response, context, program_id, draft, form, **extra)


@router.get("/api/agencies")
async def list_agencies(days: int = Query(default=14, ge=1, le=60)) -> dict:
    try:
        return agency_insight_service.to_dict(await agency_insight_service.list_agencies(days=days))
    except procurement_service.NoNoticeDataError as exc:
        raise HTTPException(status_code=503, detail=f"나라장터 조회 실패, 캐시도 없음: {exc}")


@router.get("/api/agencies/{name}")
async def get_agency(name: str, days: int = Query(default=14, ge=1, le=60)) -> dict:
    try:
        agency = await agency_insight_service.get_agency(unquote(name), days=days)
    except procurement_service.NoNoticeDataError as exc:
        raise HTTPException(status_code=503, detail=f"나라장터 조회 실패, 캐시도 없음: {exc}")
    if agency is None:
        raise HTTPException(status_code=404, detail="현재 조회 창에 없는 발주기관입니다")
    return agency_insight_service.to_dict(agency)


def _safe(procurement_id: str) -> str:
    try:
        return storage.safe_id(procurement_id, what="공고 id")
    except storage.InvalidIdError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/api/procurements/{notice_id}/versions")
async def notice_versions(notice_id: str) -> dict:
    history = notice_version_service.load_history(_safe(notice_id))
    return {"procurement_id": history.procurement_id, "count": len(history.versions), "versions": [v.model_dump(mode="json") for v in history.versions]}


@router.get("/api/procurements/{notice_id}/changes")
async def notice_changes(notice_id: str) -> dict:
    history = notice_version_service.load_history(_safe(notice_id))
    return {
        "procurement_id": history.procurement_id,
        "version_count": len(history.versions),
        "change_count": sum(len(c.changes) for c in history.changes),
        "changes": [c.model_dump(mode="json") for c in history.changes],
        "note": "조회할 때마다 핵심 필드를 비교해 달라진 것만 기록한다. 조회 창에 들어온 뒤의 변경만 잡힌다.",
    }


def _load_parse(procurement_id: str):
    try:
        return rfp_parser.load_generated(procurement_id)
    except rfp_parser.RfpFixtureNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown RFP fixture id")
    except rfp_parser.RfpNotParsedError:
        raise HTTPException(status_code=404, detail="RFP not parsed yet. Call POST /api/rfp/parse first")
    except storage.CorruptJsonError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/rfp/{procurement_id}/corrections")
async def list_corrections(procurement_id: str) -> dict:
    history = correction_service.load_history(_safe(procurement_id))
    return history.model_dump(mode="json")


@router.put("/api/rfp/{procurement_id}/items/{requirement_id}")
async def correct_item(procurement_id: str, requirement_id: str, body: correction_service.ItemCorrectionRequest) -> dict:
    procurement_id = _safe(procurement_id)
    parsed = _load_parse(procurement_id)
    if not any(r.requirement_id == requirement_id for r in parsed.requirements):
        raise HTTPException(status_code=404, detail=f"없는 항목입니다: {requirement_id}")
    entry = correction_service.add_correction(procurement_id, requirement_id, body)
    updated = rfp_parser.load_generated(procurement_id)
    item = next(r for r in updated.requirements if r.requirement_id == requirement_id)
    return {"correction": entry.model_dump(mode="json"), "item": item.model_dump(mode="json"), "item_counts": updated.item_counts}


@router.get("/api/rfp/{procurement_id}/items/{requirement_id}/performance-match")
async def item_performance_match(
    procurement_id: str,
    requirement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """항목 문장의 실적 조건을 **선택한 회사의** 실적 원장(외부 가능 행)과 대조한다. 판정이 아니라 힌트다."""
    procurement_id = _safe(procurement_id)
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    parsed = _load_parse(procurement_id)
    item = next((r for r in parsed.requirements if r.requirement_id == requirement_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail=f"없는 항목입니다: {requirement_id}")
    text = f"{item.content}\n{item.source_text}"
    # public_demo·원장 없음이면 빈 원장을 넘겨 레거시 기본 경로로 떨어지지 않게 한다 (실제 회사 원장을 섞지 않는다).
    ledger = performance_match_service.load_ledger_for(context) or {"rows": []}
    report = performance_match_service.build_report(text, ledger=ledger)
    return {
        "procurement_id": procurement_id,
        "organization_id": context.organization_id,
        "evidence_scope": context.evidence_scope,
        "requirement_id": requirement_id,
        "is_performance_text": performance_match_service.is_performance_text(text),
        "report": report.model_dump(mode="json"),
    }


@router.get("/api/performance-ledger/summary")
async def performance_ledger_summary(organization_id: str | None = Query(default=None)) -> dict:
    """변환된 실적 원장 요약 (선택한 회사, 내부 전용 파일이 있을 때만). 행 본문은 돌려주지 않는다."""
    context = deps.context_or_400(organization_id, "internal")
    ledger = performance_match_service.load_ledger_for(context)
    if ledger is None:
        return {"available": False, "organization_id": context.organization_id, "note": "실적 원장이 변환되지 않았습니다. 회사자료 화면에서 원장을 올리세요."}  # 스크립트 경로 · 옛 화면 이름을 화면에 적지 않는다(27차 §3-H)
    return {
        "available": True,
        "organization_id": context.organization_id,
        "ledger_date": ledger.get("ledger_date"),
        "source_file": ledger.get("source_file"),
        "counts": ledger.get("counts"),
        "by_group": ledger.get("by_group"),
        "project_rows": len(performance_match_service.project_rows(ledger)),
    }


@router.get("/api/exports/gold/{procurement_id}")
async def export_gold(procurement_id: str, fmt: Literal["json", "csv"] = Query(default="json", alias="format")) -> Any:
    procurement_id = _safe(procurement_id)
    payload = _load_parse(procurement_id).model_dump(mode="json")
    try:
        gold = correction_service.export_gold(procurement_id, payload)
    except correction_service.NoConfirmedItemsError:
        raise HTTPException(status_code=422, detail="담당자가 확정(confirmed/corrected)한 항목이 없어 Gold를 만들 수 없습니다.")
    if fmt == "csv":
        # 45차 M20 — 화면 「확인한 항목 내려받기」는 표 파일(엑셀에서 바로 열림 · 한국어 머리) · json 은 평가 스크립트용 그대로
        name = quote(f"확인한항목_{procurement_id}.csv")
        return Response(
            content=correction_service.gold_csv(gold).encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=\"gold.csv\"; filename*=UTF-8''{name}"},
        )
    body = gold.model_dump(mode="json")
    body["_note"] = "사람이 확정한 항목만 담은 Gold 데이터셋. 파서 입력으로 쓰지 않는다 (평가 전용)."
    return body
