"""「오늘 브리핑」 — 사업담당자 형식(SAMPLEEDU-DAILY-OPPORTUNITY-BRIEF · 인수인계 §9 · §10.1) 한 장 (37차 §3-H · 기획서 1-5 ~ 1-7).

## 규율

- **새 판정 · 새 문장을 만들지 않는다.** 목록 응답(`opportunity_service.list_opportunities`)이 이미 만든 값 — 판정 · 사유 ·
  분류 칸 · 유형(근사) · 접수방식 · 「갖추면 가능」 · 「다음 할 일」(`review_queue_service.next_step_of_state`) — 을 형식만 바꿔 적는다.
- 머리에 **「BidPilot 저장본 기준 · 출처: 나라장터 · 기업마당만」** — 웹 전수조사가 아니다(사업담당자 GPT 브리핑과 다르다).
- 데이터가 없는 칸(기관 자체접수/PMS/이메일형)은 지우지 않고 **「BidPilot 이 아직 모으지 않음」**으로 남긴다(실무 문서 §2.6).
  선제준비 칸은 사전규격 · 발주계획으로 채운다 — 39차 결정 1 부터 목록 응답의 `prepare`(입찰 목록 밖 · `prespec_service.section`)다.
  사전규격은 매출 순위표 · 「지난 브리핑 대비」 비교에 들지 않는다(PRESPEC-04).
- **매출(입찰 · 수행기관 모집)과 지원금(수혜)을 나눈다**(D6). 순서는 회사 방식(샘플에듀 = 실무 우선순위).
- 점수 칸 이름은 「회사 기준 검토 우선순위」 — 낙찰확률이 아니다(CLAUDE.md §12).
- **지난 브리핑 대비 변화**: 브리핑을 만들 때 순위표 JSON 을 회사 폴더(`exports/briefs/`)에 남기고, 다음 브리핑이 그것과 견준다.
  보관은 내보내기와 같은 규칙(최근 20개 · `export_store.MAX_FILES`). 같은 저장본끼리면 두 기준시각과 「변화 없음」을 함께 적는다.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from app.core import storage
from app.core.config import get_settings
from app.core.money import won, won_pair
from app.schemas.business_opportunity import SOURCE_NAMES, PrepareSection, UnifiedOpportunity, UnifiedOpportunityListResponse
from app.core import requester
from app.services import export_store
from app.services import opportunity_priority as priority
from app.services import practical_priority as practical
from app.services import notice_inbox_service
from app.services import prespec_service
from app.services import review_queue_service
from app.services import watchlist_service

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

#: TOP 표에 올리는 유형(근사) — 실무 문서 §9 · 기획서 1-5(B2 · D 는 후보풀에만).
FIT_TYPES: tuple[str, ...] = ("A1", "A2", "B1", "C")
#: TOP 표 줄 수.
TOP_ROWS = 10
#: 지난 브리핑 대비 「오름 · 내림」으로 적는 계단 수 — 한두 칸 흔들림은 적지 않는다.
MOVE_STEPS = 3
#: 변화 표 한 칸에 적는 공고 수(나머지는 수만).
CHANGE_LIST = 5
NOT_COLLECTED = "BidPilot 이 아직 모으지 않음"
SOURCE_LINE = "BidPilot 저장본 기준 · 출처: 나라장터(입찰공고 · 사전규격 · 발주계획) · 기업마당 · 직접 넣은 공고"
SCORE_NAME = "회사 기준 검토 우선순위"

#: 판단 낱말(실무 문서 §9 「적극도전 · 조건부 검토 · 선제준비 · 파트너형 · 긴급검토 · 비추천 · 직접입찰 불가」) — 규칙으로 고른다.
#: (2.0.6) 「간접 참여」 — 공급기업 등 회사가 직접 신청하지 않는 지원사업(사업기회 행 · 지원사업 화면 · 엑셀 「간접」과 같은 뜻).
VERDICTS: tuple[str, ...] = ("적극도전", "조건부 검토", "선제준비", "파트너형", "긴급검토", "비추천", "직접입찰 불가", "간접 참여")


#: 기업마당 「불가」 중 지역 사유 — 판정 사유 첫 조각이 지역 · 소재 요건이다.
_REGION_REASON_RE = re.compile(r"^(?:지역|소재 요건)\s*:")
#: 대학 · 산학협력단 발주(시장 신호).
_UNIVERSITY_RE = re.compile(r"대학|산학협력단|과학기술원|과기원")


# --------------------------------------------------------------------------
# 한 줄 도우미
# --------------------------------------------------------------------------


def _kst(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(KST)


#: 마크다운이 뜻을 붙이는 글자 — 제목 · 기관 · 사유 같은 **사람 · 바깥이 준 글**은 이 글자를 백슬래시로 막는다(BRIEF-07 · 38차 §3-E).
#: 직접 넣은 공고 · 붙여 넣은 후보의 제목이 표를 깨거나 링크 · 굵게로 바뀌지 않게 한다.
_MD_SPECIAL = "\\`*_[]<>|"


class _Raw(str):
    """이미 이스케이프했거나 우리가 만든 링크가 든 칸 — 표가 다시 이스케이프하지 않는다(그 밖의 칸은 모두 이스케이프)."""


def _md(text: Any) -> str:
    flat = " ".join(str(text if text is not None else "").split())
    return "".join("\\" + ch if ch in _MD_SPECIAL else ch for ch in flat)


def _safe_url(url: str | None) -> str | None:
    """링크 주소 — https 만, 괄호 · 공백 · 꺾쇠는 퍼센트로(마크다운 링크가 중간에 끊기지 않게)."""
    text = (url or "").strip()
    if not text.lower().startswith("https://"):
        return None
    # 40차 MANUAL-05 — 「|」도(GFM 이 링크 안의 | 에서 표 칸을 갈랐다)
    for ch, code in (("(", "%28"), (")", "%29"), (" ", "%20"), ("<", "%3C"), (">", "%3E"), ('"', "%22"), ("|", "%7C")):
        text = text.replace(ch, code)
    return text


def _url_link(url: str | None, text: str) -> _Raw:
    safe = _safe_url(url)
    return _Raw(f"[{_md(text)}]({safe})" if safe else "링크 없음")


def _short(title: str, limit: int = 48) -> str:
    title = title.strip()
    return title if len(title) <= limit else title[: limit - 1] + "…"


def _day(moment: datetime | None, today: date) -> str:
    local = _kst(moment)
    if local is None:
        return "-"
    return f"{local.month}/{local.day}" if local.year == today.year else f"{local:%y/%m/%d}"


def _left(item: UnifiedOpportunity, today: date) -> str:
    left = practical.days_left(item, today)
    if left is None:
        return "마감 미상" if practical.deadline_unknown(item) else "마감일 없음"
    return "오늘 마감" if left == 0 else f"{left}일"


def _deadline_cell(item: UnifiedOpportunity, today: date) -> str:
    """실제 마감 — 등록 · 참가신청 마감이 더 이르면 「11/15(등록 마감) · 입찰 11/16」(43차 M1 · `practical.deadline_display` 하나)."""
    return practical.deadline_display(item, today)


def _link(item: UnifiedOpportunity, text: str = "바로가기") -> _Raw:
    return _url_link(item.detail_url, text)


def _app_url(path: str) -> str:
    """이 PC 의 BidPilot 화면 주소(설정 `FRONTEND_URL` — 키트는 자기 포트)."""
    return get_settings().frontend_url.rstrip("/") + path


def is_pre_spec(item: UnifiedOpportunity) -> bool:
    return item.opportunity_type == "pre_spec"


def _open_link(item: UnifiedOpportunity) -> str:
    """「BidPilot 에서 열기(이 PC)」 — 공식 링크 옆에 둔다(38차 §3-C-6). 나라장터는 대시보드, 기업마당은 지원사업 신청 분석.
    사전규격은 본공고가 나왔을 때만 그 공고를 연다(분석할 공고문이 없다)."""
    if is_pre_spec(item):
        return _Raw(f"[{prespec_service.MAIN_OUT_LABEL}]({_app_url(f'/analysis?notice={item.main_notice_id}')})") if item.main_notice_id else _Raw("본공고 전")
    if item.source_type == "manual":
        path = f"/opportunities?tab=manual&manual={item.id}"
    else:
        path = f"/analysis?notice={item.id}" if item.source_type == "g2b" else f"/support/{item.id}"
    return _Raw(f"[BidPilot에서 열기]({_app_url(path)})")  # 43차 NUM-13 — 회사 서버에서도 「(이 PC)」라 했다


def _links(item: UnifiedOpportunity, text: str = "공고") -> _Raw:
    return _Raw(f"{_link(item, '규격서' if is_pre_spec(item) else text)} · {_open_link(item)}")


def _source_name(item: UnifiedOpportunity) -> str:
    if is_pre_spec(item):
        return "나라장터 사전규격"
    return SOURCE_NAMES.get(item.source_type, item.source_type)


def _next_paths(item: UnifiedOpportunity) -> str:
    """「오늘 실제 행동」 줄 끝의 경로 — 요구사항 정리 · 제안서 / 사업계획서 작성(38차 §3-C-6)."""
    if is_pre_spec(item):
        return _Raw("본공고가 나오면 공고 분석 · 제안서") if not item.main_notice_id else _open_link(item)
    if item.source_type == "manual":
        return _Raw("공고문 원문으로 자격 확인 · 「직접 넣기 · 후보함」에서 고치기")
    if item.source_type == "g2b":
        return _Raw(
            f"[요구사항 정리]({_app_url(f'/opportunities?tab=sheet&notice={item.id}')}) · "
            f"[제안서 작성]({_app_url(f'/plan?notice={item.id}')})"
        )
    return _Raw(f"[사업계획서 작성]({_app_url(f'/plan?support={item.id}')})")


def _evidence(item: UnifiedOpportunity, limit: int = 90) -> str:
    """후보풀 · 표 칸에 싣는 근거 줄. 없으면 「-」. 43차 BRIEF-17 — 상투 머리말(「입찰참가자격 … 다음 각 호」)만 남고 업종 코드 · 지역이 잘렸다:
    머리말을 덜어내고 업종 코드(4자리) · 지역이 보이게 90자까지."""
    line = (item.evidence_line or "-").removeprefix("근거: ")
    line = re.sub(r"「\s*(?:\d+\.\s*)?(?:입찰\s*)?참가\s*자격[^」]{0,30}?(?:다음|아래)[^」]{0,12}?(?:각\s*호|요건)[^」]{0,10}?(?:모두\s*)?(?:갖춘|충족한)?\s*", "「", line)
    return line if len(line) <= limit else line[:limit].rstrip() + "…"


def _budget(item: UnifiedOpportunity) -> str:
    """예산 칸 — 「규모 큼(단독 상한 n억)」 · 대형 꼬리표가 붙은 공고는 반올림해 상한과 같아지면 정확한 금액(43차 BRIEF-16)."""
    if not item.budget:
        return "-"
    hit = re.search(r"단독 상한 (\d+(?:\.\d+)?)억", " ".join(filter(None, [item.scale_tag, item.partner_tag])))
    ceiling = int(float(hit.group(1)) * 100_000_000) if hit else priority.RECOMMENDED_CEILING_KRW
    return won_pair(item.budget, ceiling)[0]


def _methods(item: UnifiedOpportunity) -> str:
    return " · ".join(item.submission_methods or ()) or "미상"


def _score(item: UnifiedOpportunity) -> str:
    return "미산정" if item.company_priority_score is None else str(item.company_priority_score)


def is_revenue(item: UnifiedOpportunity) -> bool:
    """매출 공고인가 — 나라장터 입찰 · 수행기관 모집 · 직접 넣은 입찰(D6 · 실무 문서 §4.2)."""
    return item.source_type == "g2b" or item.recruit_kind in (practical.RECRUIT_OPERATOR, practical.RECRUIT_BID)


def verdict_of(item: UnifiedOpportunity) -> str:
    """판단 칸 — 판단 낱말 하나(`verdict_word`)에 행 꼬리표(`practical.tags_of` — 「규모 큼」 · 「주제 확인」 · AI 「본업 아닐 수 있음」)를 붙인 것.
    TOP · 🥇 상세 · 「가장 먼저 볼 것」 · 후보풀 · 엑셀 브리핑 시트가 이 한 함수를 쓴다(40차 RANK-05)."""
    word = verdict_word(item)
    # 44차 M4 — 저장된 결정(참여 · 신청 · 보류 · 검토 중 · 안 함)이 있으면 「결정: …」 — 엑셀 「결정」 칸 · 이번 주 할 일과 같은 값
    decided = [f"결정: {item.decision_text}"] if item.decision_text else []
    return " · ".join([word, *(t for t in practical.tags_of(item) if t != word), *decided])


def verdict_word(item: UnifiedOpportunity) -> str:
    """판단 낱말 하나 — 위에서부터 처음 맞는 것. 판정 · 분류 · D8 을 읽기만 한다."""
    if item.eligibility_gate == "FAIL" or item.closed:
        return "직접입찰 불가"
    if item.practical_group == "비추천":
        return "비추천"
    if item.practical_group == "선제준비":
        return "선제준비"
    if item.participation:
        # (2.0.6 values-6) 공급기업 등 간접 참여 — 사업기회 행 · 지원사업 화면은 「간접 참여」인데 여기만 「조건부 검토」라 직접 신청으로 읽혔다
        return "간접 참여"
    if item.partner_tag:
        # 대형 꼬리표 그대로 — 사업기회 행 꼬리표와 같은 함수(`practical.partner_tag`)의 값이다(38차 D14 · DOCS-01).
        # 공동수급 불허면 「파트너형」이라 하지 않는다(실무 문서 §4.3).
        return item.partner_tag
    if item.practical_group == "긴급":
        return "긴급검토"
    if item.eligibility_gate == "PASS":
        return "적극도전"
    return "조건부 검토"


def split_unlocks(conditions: list[str] | tuple[str, ...] | None) -> tuple[list[str], list[str]]:
    """(갖추면 가능, 직접 확인) — 등록증 확인 같은 「직접 확인」은 갖출 조건이 아니다(32차 화면 결정을 브리핑 · 엑셀에도 · 43차 M7 · ELIG-05).
    본사 이전(「○○ 소재 시 가능」)은 어느 쪽에도 넣지 않는다(N3)."""
    from app.services import eligibility_engine

    direct, unlock = [], []
    for c in conditions or ():
        if eligibility_engine.is_relocation(c):
            continue
        (direct if "등록증에서" in c else unlock).append(c)
    return unlock, direct


def unlock_cell(conditions: list[str] | tuple[str, ...] | None) -> str:
    """엑셀 한 칸 — 「갖추면 가능: … / 직접 확인: …」."""
    unlock, direct = split_unlocks(conditions)
    parts = ([f"갖추면 가능: {' · '.join(unlock)}"] if unlock else []) + ([f"직접 확인: {' · '.join(direct)}"] if direct else [])
    return " / ".join(parts)


def next_step_of(item: UnifiedOpportunity) -> str:
    """「오늘 실제 행동」 한 줄 — **이미 있는 문장**만 쓴다(새 문장을 짓지 않는다).

    나라장터는 검토 목록의 「다음 할 일」(대시보드 「지금 할 일」과 같은 순서 · `review_queue_service`), 지원사업은 그 화면으로
    가는 단추 이름. 「갖추면 가능」 첫 줄이 있으면 덧붙인다.
    """
    if item.source_type == "g2b":
        step = review_queue_service.next_step_of_state(item.analysis_state)
    else:
        step = item.next_route.label
    unlock, direct = split_unlocks(item.unlock_conditions)
    if unlock:
        more = f" (남은 조건 {len(unlock) - 1 + len(direct)}개 더)" if len(unlock) + len(direct) > 1 else ""
        return f"{step} · 갖추면 가능: {unlock[0]}{more}"
    if direct:
        return f"{step} · 직접 확인: {direct[0]}"
    return step


# --------------------------------------------------------------------------
# 순서 · 칸
# --------------------------------------------------------------------------


def ordered(items: Iterable[UnifiedOpportunity], method: str) -> list[UnifiedOpportunity]:
    """회사 방식 순서(실무순이면 `practical_order` · 점수순이면 목록 순서 `priority_rank`)."""
    rows = list(items)
    if method == "practical":
        return sorted(rows, key=lambda i: (i.practical_order or 10**9, i.id))
    return sorted(rows, key=lambda i: (i.priority_rank or 10**9, i.id))


def _live(item: UnifiedOpportunity) -> bool:
    return item.practical_group not in ("제외", "비추천")


def _table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) if isinstance(cell, _Raw) else _md(cell) for cell in row) + " |")
    return lines


# --------------------------------------------------------------------------
# 순위표 JSON (지난 브리핑 대비 변화)
# --------------------------------------------------------------------------


def briefs_dir(organization_id: str) -> Path:
    return export_store.exports_dir(organization_id) / "briefs"


def bizinfo_is_sample(listing: UnifiedOpportunityListResponse) -> bool:
    """기업마당이 받아 둔 목록 없이 가상 예시로 떨어졌나(키트 · 키 없음) — 브리핑 머리에 경고 · 순위표는 남기지 않는다(38차 BRIEF-01)."""
    return listing.source_status.get("bizinfo") == "sample"


#: 출처 이름(조사까지) — 「⚠ ○○ 읽지 못했습니다」 줄.
_SOURCE_OBJECTS: dict[str, str] = {"g2b": "나라장터를", "bizinfo": "기업마당을", "manual": "직접 넣은 공고를"}


def failed_sources(listing: UnifiedOpportunityListResponse) -> dict[str, str]:
    """읽지 못해 칸이 빈 출처(출처 → 사유). 오류가 있어도 항목이 왔으면(캐시로 대신) 넣지 않는다.

    (2.0.6 fallback-4) 실패한 날의 브리핑이 「매출 0건」을 사유 없이 적고, 그 순위표가 그날 기준으로 굳어 다음 날 공고 전부가 「새로」였다.
    """
    present = {i.source_type for i in listing.items}
    return {key: str(error) for key, error in (listing.source_errors or {}).items() if error and key not in present}


def failure_lines(listing: UnifiedOpportunityListResponse) -> list[str]:
    """브리핑 머리 · 엑셀 브리핑 시트가 같은 글을 쓴다."""
    return [
        f"⚠ {_SOURCE_OBJECTS.get(key, key)} 읽지 못했습니다 — {reason} · 이 출처 칸은 비어 있습니다. 이번 순위표는 남기지 않습니다(다음 브리핑이 빈 목록과 견주지 않게)"
        for key, reason in failed_sources(listing).items()
    ]


def revenue_top(listing: UnifiedOpportunityListResponse) -> list[UnifiedOpportunity]:
    """「오늘 핵심 결론 · 매출」 TOP — 본업 덩어리의 매출을 회사 방식 순서 앞에서부터 10건(비추천 · 제외 뺌 · 38차 §3-B-5 ·
    사전규격은 39차부터 목록 밖).

    정밀도 검사(`scripts/check_precision.py` · 39차 D18 ①)도 이 함수 하나를 쓴다 — 브리핑과 검사가 다른 10건을 보지 않게.
    """
    revenue = ordered([i for i in brief_items(listing) if is_revenue(i)], listing.ranking_method)
    return [i for i in revenue if _live(i) and (i.practical_block or practical.BLOCK_CORE) == practical.BLOCK_CORE][:TOP_ROWS]


def brief_items(listing: UnifiedOpportunityListResponse) -> list[UnifiedOpportunity]:
    """브리핑이 보는 항목 — 실제 회사(가상 예시 · 시험 회사가 아닌)면 시연 고정 공고를 뺀다(38차 BRIEF-08 · 9/7~9/18 마감 넷이 제외 표에 음수 남은기간)."""
    from app.services import organization_service

    try:
        real = organization_service.get_organization(listing.organization_id).data_class == "real"
    except organization_service.OrganizationNotFoundError:
        real = False
    return [i for i in listing.items if not (real and i.pinned)]


def _stamp_of(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def snapshot_of(listing: UnifiedOpportunityListResponse, *, now: datetime) -> dict[str, Any]:
    """이번 브리핑의 순위표 — 공고 id · 갈래 안 자리 · 분류 · 판정 · 점수 · 제목 · 계산 방식 · 기간 · 출처마다 받은 때."""
    method = listing.ranking_method
    rows: dict[str, dict[str, Any]] = {}
    items = brief_items(listing)
    for part, members in (("매출", [i for i in items if is_revenue(i)]), ("지원금", [i for i in items if not is_revenue(i)])):
        live = [i for i in ordered(members, method) if _live(i)]
        rank = {i.id: n for n, i in enumerate(live, start=1)}
        for item in members:
            rows[item.id] = {
                "part": part,
                "rank": rank.get(item.id),
                "group": item.practical_group,
                "gate": item.eligibility_gate,
                "score": item.company_priority_score,
                "title": item.title[:80],
                "source": item.source_type,
            }
    return {
        "created_at": now.astimezone(timezone.utc).isoformat(),
        "fetched_at": (listing.summary.fetched_at or listing.fetched_at).isoformat() if (listing.summary.fetched_at or listing.fetched_at) else None,
        "ranking_method": method,
        "days": listing.summary.days,
        "fetched": {key: _stamp_of(value) for key, value in (listing.source_fetched_at or {}).items()},
        "bizinfo_sample": bizinfo_is_sample(listing),
        # (2.0.6 fallback-4) 읽지 못한 출처 — 있으면 순위표를 남기지 않고, 비교에서도 그 출처 줄을 뺀다
        "source_failed": sorted(failed_sources(listing)),
        "organization_id": listing.organization_id,
        # 43차 Q27 · BRIEF-04 · NUM-08 — 규칙 판이 다르면 순위를 견주지 않는다 · 계정마다 기준을 따로 둔다
        "rules_version": _rules_version(),
        "account": requester.current_recorded_by(),
        "rows": rows,
        # 39차 결정 1 — 사전규격은 순위표(rows) 밖이다. 「새 본업 사전규격」을 세려고 보이는 것의 id 만 따로 남긴다.
        "prespec_ids": [i.id for i in (listing.prepare.items if listing.prepare else [])],
        # 43차 M14 — 본공고가 나온 본업 사전규격(지난 브리핑 뒤 새로 나온 것을 세려고)
        "merged_core_ids": [i.id for i in (listing.prepare.merged if listing.prepare else []) if _core_prespec(i)],
    }


def _rules_version() -> int:
    from app.services import support_application_service

    return support_application_service.RULES_VERSION


def _snapshots(organization_id: str) -> list[dict[str, Any]]:
    """남긴 순위표(최근 것 먼저) — 깨진 파일은 건너뛴다."""
    folder = briefs_dir(organization_id)
    try:
        files = sorted(folder.glob("brief_*.json"), reverse=True)
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for path in files:
        try:
            payload = storage.read_json(path, default=None)
        except storage.CorruptJsonError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("rows"), dict):
            out.append(payload)
    return out


def latest_snapshot(organization_id: str, *, account: str | None = None) -> dict[str, Any] | None:
    """견줄 순위표 — **이 계정이 남긴 가장 최근 것**(43차 Q27 · TEAM-01), 없으면 회사의 가장 최근 것(누가 · 언제 남겼는지 함께 적는다).
    없거나 깨졌으면 None — 「비교할 지난 브리핑 없음」."""
    snapshots = _snapshots(organization_id)
    if account:
        mine = next((snap for snap in snapshots if snap.get("account") == account), None)
        if mine is not None:
            return mine
    return snapshots[0] if snapshots else None


def save_snapshot(organization_id: str, snapshot: dict[str, Any], *, now: datetime) -> Path | None:
    """하루 한 번만 — 같은 계정(인증이 꺼졌으면 회사)이 오늘(KST) 이미 남겼으면 남기지 않는다(43차 Q27 · N11 · 같은 날 두 번 받으면 두 번째가
    「변화 0」이 되던 것)."""
    today = now.astimezone(KST).date()
    for snap in _snapshots(organization_id):
        try:
            made = datetime.fromisoformat(str(snap.get("created_at"))).astimezone(KST).date()
        except ValueError:
            continue
        if made == today and snap.get("account") == snapshot.get("account"):
            return None
    return _save_snapshot(organization_id, snapshot, now=now)


def _save_snapshot(organization_id: str, snapshot: dict[str, Any], *, now: datetime) -> Path | None:
    """순위표를 남기고 오래된 것부터 지운다(내보내기와 같은 보관 규칙 · 최근 `export_store.MAX_FILES`개).

    기업마당이 가상 예시면 남기지 않는다(38차 BRIEF-01 — 다음 판에 예시 200건이 「새로」로 나왔다). 그때는 None.
    읽지 못한 출처가 있어도 같다(2.0.6 fallback-4).
    """
    if snapshot.get("bizinfo_sample") or snapshot.get("source_failed"):
        return None
    folder = briefs_dir(organization_id)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = now.astimezone(KST).strftime("%Y%m%d-%H%M%S")
    path = folder / f"brief_{stamp}.json"
    index = 2
    while path.exists():
        path = folder / f"brief_{stamp}_{index}.json"
        index += 1
    storage.write_json_atomic(path, snapshot)
    for old in sorted(folder.glob("brief_*.json"), reverse=True)[export_store.MAX_FILES :]:
        try:
            old.unlink(missing_ok=True)
        except OSError:
            logger.warning("옛 브리핑 순위표를 지우지 못했습니다: %s", old.name)
    return path


def changes(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """새로 · 오름 · 내림 · 마감/탈락. `previous` 가 없으면 `first=True`."""
    if previous is None:
        return {"first": True}
    def alive(row: dict | None) -> bool:
        return bool(row) and row.get("rank") is not None
    # 38차 순위표에는 사전규격이 매출 줄로 들어 있다 — 39차부터는 비교에서 뺀다(PRESPEC-04 · 아니면 첫 브리핑에 수십 건이 「탈락」).
    raw_before = previous.get("rows") or {}
    # (2.0.6 fallback-4) 이번에 읽지 못한 출처의 옛 줄은 견주지 않는다 — 그 출처 공고가 모두 「탈락」으로 적혔다
    failed = set(current.get("source_failed") or ())
    before = {
        pid: row for pid, row in raw_before.items()
        if not pid.startswith(prespec_service.ID_PREFIX) and row.get("source") not in failed
    }
    after = current.get("rows") or {}
    seen_pre = set(previous.get("prespec_ids") or [pid for pid, row in raw_before.items() if pid.startswith(prespec_service.ID_PREFIX) and alive(row)])
    new_prespec = [pid for pid in current.get("prespec_ids") or [] if pid not in seen_pre]
    new = [pid for pid, row in after.items() if alive(row) and pid not in before]
    # RANK_BRIEF-02 — 차수가 바뀐 공고(g2b-…-000 → -001)는 같은 공고다: 「새로 + 탈락」이 아니라 ✏️ 공고 변경(차수)
    def series(pid: str) -> str:
        return pid.rsplit("-", 1)[0] if pid.startswith("g2b-") else pid
    before_alive = {series(pid): pid for pid, row in before.items() if alive(row) and pid not in after}
    reissued = [(before_alive[series(pid)], pid) for pid in new if pid.startswith("g2b-") and series(pid) in before_alive]
    moved = {old for old, _ in reissued} | {fresh for _, fresh in reissued}
    new = [pid for pid in new if pid not in moved]
    up = [(pid, before[pid]["rank"], row["rank"]) for pid, row in after.items()
          if alive(row) and alive(before.get(pid)) and before[pid].get("part") == row.get("part") and before[pid]["rank"] - row["rank"] >= MOVE_STEPS]
    down = [(pid, before[pid]["rank"], row["rank"]) for pid, row in after.items()
            if alive(row) and alive(before.get(pid)) and before[pid].get("part") == row.get("part") and row["rank"] - before[pid]["rank"] >= MOVE_STEPS]
    gone = [pid for pid, row in before.items() if alive(row) and not alive(after.get(pid)) and pid not in moved]
    # 마감된 공고는 이번 목록에 아예 없다 — 제목은 지난 순위표에서 읽는다(37차 마지막 검토 · 전에는 공고 id 가 찍힘)
    gone_titles = [((after.get(pid) or {}).get("title") or before[pid].get("title") or pid) for pid in gone]
    # BRIEF-03 — 제외 · 비추천에서 살아난 것 · 매출 ↔ 지원금이 바뀐 것(새로 · 오름 · 내림 · 탈락 어디에도 들지 않았다)
    revived = [pid for pid, row in after.items() if alive(row) and pid in before and not alive(before[pid])]
    switched = [pid for pid, row in after.items() if alive(row) and alive(before.get(pid)) and before[pid].get("part") != row.get("part")]
    # BRIEF-02 — 계산 방식 · 기간이 다르면 오름 · 내림을 내지 않는다(같은 저장본인데 오름 181 · 내림 99 가 나왔다)
    method_changed = previous.get("ranking_method") != current.get("ranking_method")
    days_changed = previous.get("days") is not None and previous.get("days") != current.get("days")
    # 43차 Q27 · BRIEF-04 — 규칙 판이 다르면 이동은 공고 변화가 아니라 규칙 변화다(옛 순위표는 판이 없어 비교하지 않음)
    rules_changed = previous.get("rules_version") != current.get("rules_version")
    if method_changed or days_changed or rules_changed:
        up, down = [], []
    # BRIEF-04 — 「같은 저장본」은 두 출처의 받은 때가 **모두** 같을 때만(옛 순위표는 출처마다 받은 때가 없어 단정하지 않는다)
    before_fetched, after_fetched = previous.get("fetched") or {}, current.get("fetched") or {}
    same_data = bool(before_fetched) and all(before_fetched.get(k) for k in ("g2b", "bizinfo")) and all(
        before_fetched.get(k) == after_fetched.get(k) for k in ("g2b", "bizinfo")
    )
    return {
        "first": False,
        "same_data": same_data,
        "revived": revived,
        "switched": switched,
        "not_comparable": "계산 방식" if method_changed else "조회 기간" if days_changed else "규칙 판" if rules_changed else None,
        "previous_account": previous.get("account"),
        "previous_created_at": previous.get("created_at"),
        "previous_fetched_at": previous.get("fetched_at"),
        "new": new,
        "up": sorted(up, key=lambda t: t[2] - t[1]),
        "down": sorted(down, key=lambda t: t[1] - t[2]),
        "gone": gone,
        "gone_titles": gone_titles,
        "new_prespec": new_prespec,
        "new_merged": [pid for pid in current.get("merged_core_ids") or [] if pid not in set(previous.get("merged_core_ids") or [])],
        "reissued": reissued,
    }


# --------------------------------------------------------------------------
# 마크다운 한 장
# --------------------------------------------------------------------------


def _stamp(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    local = _kst(moment)
    return f"{local:%Y-%m-%d %H:%M}" if local else iso


def _edited(items: Sequence[UnifiedOpportunity], previous: dict[str, Any] | None, now: datetime) -> list[tuple[UnifiedOpportunity, list[str]]]:
    """지난 브리핑 뒤로 바뀐 나라장터 공고(마감 · 첨부 · 차수 · 종류). 첫 브리핑이면 최근 7일(`changed_fields`)."""
    from app.services import notice_version_service

    since: datetime | None = None
    if previous and previous.get("created_at"):
        try:
            since = datetime.fromisoformat(str(previous["created_at"]))
        except ValueError:
            since = None
    out: list[tuple[UnifiedOpportunity, list[str]]] = []
    for item in items:
        if item.source_type != "g2b" or item.closed or item.relevance_note:
            continue
        labels = notice_version_service.notable_changes_since(item.id, since) if since else list(item.changed_fields or [])
        if labels:
            out.append((item, labels))
    return out


def _edited_row(edited: Sequence[tuple[UnifiedOpportunity, list[str]]], first: bool) -> list[str]:
    when = "최근 7일" if first else "지난 브리핑 뒤"
    if not edited:
        return ["✏️", f"공고 변경({when} · 마감 · 첨부 · 차수 · 종류) 없음"]
    shown = ", ".join(f"{_md(_short(i.title, 26))}({' · '.join(l)}) {_link(i, '공고')}" for i, l in edited[:CHANGE_LIST])
    rest = len(edited) - min(len(edited), CHANGE_LIST)
    return ["✏️", _Raw(f"공고 변경({when}) {len(edited)}건 — {shown}{f' 외 {rest}건' if rest > 0 else ''}")]


def _plan_range(section: PrepareSection) -> str:
    """발주계획 표의 실제 범위 — 받은 계획의 발주 달(43차 M14 · PREP-04 — 「이번 달부터 3달」이라 적었는데 실제로는 최근 며칠 등록분 · 10월뿐이었다)."""
    months = sorted({p.when for p in section.plans if p.when and p.when != "-"})
    if not months:
        return "최근 등록분"
    span = months[0] if len(months) == 1 else f"{months[0]}~{months[-1]}"
    return f"최근 등록분 · 발주 {span}"


def _core_prespec(item: UnifiedOpportunity) -> bool:
    """본업 사전규격인가(비추천 · 연구 · 감리 · 구매 · 대형이 아님)."""
    return item.practical_group != "비추천" and (item.practical_block or practical.BLOCK_CORE) == practical.BLOCK_CORE


def _blue_row(diff: dict[str, Any], section: PrepareSection) -> list[str]:
    """🔵 줄 — 본업 사전규격(새로) · 본공고 나옴(본업 · 지난 브리핑 뒤) · 의견 마감 지남 · 본공고 대기(본업) · 발주계획 수
    (38차 §3-D-5 · 39차 결정 1 · 43차 M14 · Q16 — 「본공고 나옴 118」은 30일 치 전부라 본업 47 옆에서 넘어온 수가 더 많아 보였다)."""
    shown = {i.id: i for i in section.items}
    merged = {i.id: i for i in section.merged}
    new = [pid for pid in (diff.get("new_prespec") or []) if pid in shown]
    plans = sum(1 for p in section.plans if not p.main_out and not p.prespec_out)
    waiting = sum(1 for i in section.opinion_passed if _core_prespec(i))
    head = f"본업 사전규격 {len(shown)}건" if diff.get("first") else f"새 본업 사전규격 {len(new)}건(지금 {len(shown)}건)"
    names = ", ".join(f"{_md(_short(shown[pid].title, 26))} {_link(shown[pid], '규격서')}" for pid in new[:CHANGE_LIST])
    if diff.get("first"):
        merged_text = f"본공고 나옴(본업) {sum(1 for i in section.merged if _core_prespec(i))}건"
    else:
        fresh = [pid for pid in (diff.get("new_merged") or []) if pid in merged]
        merged_text = f"본공고 나옴(본업) 지난 브리핑 뒤 {len(fresh)}건" + (
            " — " + ", ".join(_md(_short(merged[pid].title, 22)) for pid in fresh[:CHANGE_LIST]) if fresh else ""
        )
    return ["🔵", _Raw(
        f"{head}{(' — ' + names) if names else ''} · {merged_text} · 의견 마감 지남 · 본공고 대기(본업) {waiting}건 · "
        f"발주 예정(발주계획) 후보 {plans}건 — 아래 「🔵 선제준비」 칸"
    )]


def _change_lines(
    diff: dict[str, Any],
    by_id: dict[str, UnifiedOpportunity],
    current: dict[str, Any],
    *,
    edited: Sequence[tuple[UnifiedOpportunity, list[str]]] = (),
    section: PrepareSection | None = None,
) -> list[str]:
    section = section or PrepareSection()
    lines = ["## 지난 브리핑 대비 달라진 것", ""]
    if diff.get("first"):
        lines += _table(["변화", "내용"], [
            ["🆕", "비교할 지난 브리핑 없음 — 이번이 첫 브리핑입니다(이번 순위표를 남겨 다음 브리핑이 견줍니다)"],
            ["⬆️", "비교할 지난 브리핑 없음"], ["⬇️", "비교할 지난 브리핑 없음"], ["❌", "비교할 지난 브리핑 없음"],
            _edited_row(edited, True),
            _blue_row(diff, section),
        ])
        return lines + [""]

    def names(ids: Sequence[str]) -> str:
        shown = [f"{_md(_short(by_id[pid].title, 30))} {_link(by_id[pid], '공고')}" if pid in by_id else _md(pid) for pid in ids[:CHANGE_LIST]]
        rest = len(ids) - len(shown)
        return ", ".join(shown) + (f" 외 {rest}건" if rest > 0 else "")

    def moves(rows: Sequence[tuple[str, int, int]]) -> str:
        shown = [f"{_md(_short(by_id[pid].title, 26))}({a}→{b}위)" for pid, a, b in rows[:CHANGE_LIST] if pid in by_id]
        rest = len(rows) - len(shown)
        return ", ".join(shown) + (f" 외 {rest}건" if rest > 0 else "")

    gone_titles = diff.get("gone_titles") or diff["gone"]
    revived, switched = diff.get("revived") or [], diff.get("switched") or []
    nothing = not (diff["new"] or diff["up"] or diff["down"] or diff["gone"] or revived or switched)
    not_comparable = diff.get("not_comparable")
    who = diff.get("previous_account")
    mine = requester.current_recorded_by()
    whose = "" if not who or who == mine else f"{who} 님이 "
    stamp_line = f"지난 브리핑({whose}{_stamp(diff.get('previous_created_at'))} 만듦)과 비교 · 그때 목록 받은 때 {_stamp(diff.get('previous_fetched_at'))}"
    no_rank = f"{not_comparable}이 바뀌어 순위 비교는 하지 않음 — 새로 · 탈락만" if not_comparable else None
    if nothing:
        same = " — 두 브리핑 모두 같은 저장본입니다(그 사이 새로 받지 않음)" if diff.get("same_data") else ""
        rows = [["—", f"변화 없음 · {stamp_line}{same}"]]
        if no_rank:
            rows.append(["⬆️⬇️", no_rank])
        lines += _table(["변화", "내용"], [*rows, _edited_row(edited, False), _blue_row(diff, section)])
        return lines + [""]
    lines += [f"> {stamp_line}{' · 같은 저장본' if diff.get('same_data') else ''}", ""]
    back = " · ".join(
        part for part in (
            f"다시 들어옴(제외 · 비추천이던 것) {len(revived)}건 — {names(revived)}" if revived else "",
            f"갈래 바뀜(매출 ↔ 지원금) {len(switched)}건 — {names(switched)}" if switched else "",
        ) if part
    )
    lines += _table(["변화", "내용"], [
        ["🆕", _Raw(f"새로 들어온 것 {len(diff['new'])}건 — {names(diff['new'])}") if diff["new"] else "없음"],
        ["🆕", _Raw(back) if back else "다시 들어옴 · 갈래 바뀜 없음"],
        ["⬆️", no_rank or (_Raw(f"{MOVE_STEPS}계단 이상 오른 것 {len(diff['up'])}건 — {moves(diff['up'])}") if diff["up"] else "없음")],
        ["⬇️", no_rank or (_Raw(f"{MOVE_STEPS}계단 이상 내린 것 {len(diff['down'])}건 — {moves(diff['down'])}") if diff["down"] else "없음")],
        ["❌", _Raw(f"마감 · 탈락(불가 · 관련 낮음) {len(diff['gone'])}건 — {', '.join(_md(_short(str(t), 26)) for t in gone_titles[:CHANGE_LIST])}{' …' if len(gone_titles) > CHANGE_LIST else ''}") if diff["gone"] else "없음"],
        _edited_row(edited, False),
        _blue_row(diff, section),
    ])
    return lines + [""]


def _top_rows(items: Sequence[UnifiedOpportunity], today: date) -> list[list[Any]]:
    medals = ["🥇", "🥈", "🥉"]
    out = []
    for n, item in enumerate(items, start=1):
        out.append([
            medals[n - 1] if n <= 3 else str(n),
            _Raw(f"**{_md(_short(item.title))}**"),
            _short(item.agency, 18),
            _day(item.published_at, today),
            _deadline_cell(item, today),
            _left(item, today),
            _methods(item),
            item.fit_type or "-",
            _score(item),
            _Raw(f"**{_md(_top_verdict(item))}**"),
            _links(item),
        ])
    return out


#: TOP 줄 중 마감 13일 이내 본업 — 「본업 · 긴급」(38차 §3-B-5 · TOP 이 비면 본업 긴급 공고가 위로 온다).
URGENT_CORE = "본업 · 긴급"


def _top_verdict(item: UnifiedOpportunity) -> str:
    # 꼬리표는 다른 판단 칸과 같은 함수(`verdict_of` — 낱말과 같은 꼬리표는 한 번만 · 42차 BACK-R41-01)
    verdict = verdict_of(item)
    if item.time_tier in ("T5", "T6") and (item.practical_block or practical.BLOCK_CORE) == practical.BLOCK_CORE:
        return f"{URGENT_CORE} · {verdict}"
    return verdict


TOP_HEADER = ("순위", "공고", "기관", "공고일", "마감", "남은기간", "접수방식", "유형(근사)", SCORE_NAME, "판단", "바로가기")
POOL_HEADER = ("분류", "후보", "출처", "접수방식", "공고일", "마감", "남은기간", "유형(근사)", "판단", "근거", "바로가기")


def _pool_rows(items: Sequence[UnifiedOpportunity], today: date) -> list[list[Any]]:
    return [
        [
            item.practical_group or "-",
            _short(item.title, 40),
            _source_name(item),
            _methods(item),
            _day(item.published_at, today),
            _deadline_cell(item, today),
            _left(item, today),
            item.fit_type or "-",
            verdict_of(item),
            _evidence(item),
            _links(item, "바로가기"),
        ]
        for item in items
    ]


_KEYWORDS_RE = re.compile(r"키워드\s*(\d+)\s*개")


def seen_counts(listing: UnifiedOpportunityListResponse) -> dict[str, Any]:
    """「오늘 BidPilot 이 본 것」 숫자 (38차 §3-C-3) — 지금 목록에서 센다(지어내지 않는다)."""
    from app.services import support_application_service

    # RANK_BRIEF-04 — 본문과 같은 항목(실제 회사면 시연 고정 공고 뺌 · `brief_items`) — 머리 숫자가 본문 합과 달랐다
    items = brief_items(listing)
    g2b = [i for i in items if i.source_type == "g2b"]
    biz = [i for i in items if i.source_type == "bizinfo"]
    match = _KEYWORDS_RE.search(listing.collected_by or "")
    section = listing.prepare or PrepareSection()
    return {
        "g2b": len(g2b),
        # 사전규격은 「마감 전 나라장터」에 세지 않는다(PRESPEC-07) — 따로 전부 · 본업(의견 마감 남음).
        "prespec": section.total,
        "prespec_core": len(section.items),
        "orderplan": len(section.plans) + len(section.plans_folded) + section.plans_low,
        "keywords": int(match.group(1)) if match else None,
        "bizinfo": len(biz),
        "manual": sum(1 for i in items if i.source_type == "manual"),
        "inbox": len(notice_inbox_service.pending(listing.organization_id)),
        "opened": watchlist_service.opened_today(listing.organization_id),
        "g2b_read": sum(1 for i in g2b if i.clause_count),
        "clause_lines": sum(i.clause_count for i in g2b),
        "bizinfo_read": sum(1 for i in biz if i.document_read),
        "excluded": sum(1 for i in items if i.practical_group in ("제외", "비추천")),
        "rules_version": support_application_service.RULES_VERSION,
    }


def seen_line(listing: UnifiedOpportunityListResponse) -> str:
    """「오늘 BidPilot 이 본 것」 한 줄 — 브리핑 머리 · 엑셀 브리핑 시트가 같은 글을 쓴다."""
    c = seen_counts(listing)
    words = f"(공고명 낱말 {c['keywords']}개)" if c["keywords"] else ""
    return (
        f"오늘 BidPilot 이 본 것: 나라장터 마감 전 입찰 {c['g2b']}건{words} · 사전규격 {c['prespec']}건(본업 · 의견 마감 남음 {c['prespec_core']}건) · "
        f"발주계획 {c['orderplan']}건 · 기업마당 {c['bizinfo']}건 전수 · "
        f"직접 넣음 {c['manual']}건 · 확인 전 후보 {c['inbox']}건 · 오늘 사람이 열어 본 곳 {c['opened'][0]}/{c['opened'][1]} · "
        f"공고문 읽음 나라장터 {c['g2b_read']}건(참가자격 조항 {c['clause_lines']}줄 · 쪽 번호) · 기업마당 {c['bizinfo_read']}건 · "
        f"제외 · 비추천 {c['excluded']}건 사유 기록 · 링크는 공식(API) 주소 · 규칙 판 {c['rules_version']}"
    )


def ai_note_line(listing: UnifiedOpportunityListResponse) -> str | None:
    """「AI:」 꼬리표가 하나라도 있으면 그 풀이 한 줄(40차 결정 2 · D24) — 브리핑 머리 · 엑셀 브리핑 시트가 같은 글. 없으면 None(키트 · 꺼 둔 회사)."""
    from app.services.ai_fit_service import REFERENCE_NOTE

    section = getattr(listing, "prepare", None)
    prepared = list(section.items) if section else []
    if not any(getattr(item, "ai_fit_note", None) for item in [*listing.items, *prepared]):  # 41차 AIFIT-06 — 선제준비도
        return None
    return (f"「AI: 본업 아닐 수 있음」 꼬리표는 {REFERENCE_NOTE}입니다 — 새 공고의 공고명 · 조달분류 · 기관 · 예산만 보고 물었고, "
            "판정 · 점수 · 「가능」에는 쓰지 않습니다(본업 칸 안에서 뒤로만)")


def _low_bundle(note: str | None) -> str:
    """비추천 사유의 묶음 이름 — 사유 괄호 글(「(여행 · 국외연수)」 · 「(정보시스템 유지관리 · 운영)」)이 있으면 그것, 없으면 첫 마디."""
    text = (note or "").strip()
    if not text:
        return "관련 낮음(낱말 조합이 후보가 아님)"
    paren = re.findall(r"\(([^()]{2,40})\)", text)
    if paren:
        return paren[-1].split(" — ")[0].split(" · 공고명")[0]
    return text.split(" — ")[0][:30]


def collect_line(listing: UnifiedOpportunityListResponse) -> str | None:
    """자동 받기 한 줄(39차 §3-F-2 · 40차 D30 · `auto_collect.collect_state`) — 브리핑 머리 · 엑셀 브리핑 시트가 같은 글을 쓴다.
    키트(기록 없음)면 None · 경고 표시(⚠)는 오늘 아직일 때만(받는 중 · 꺼 둠은 경고가 아니다)."""
    state = listing.collect_state
    if state is None or state.kind == "none" or not state.text:
        return None
    if state.kind == "missed":
        return f"⚠ {state.text}"
    # 43차 NUM-13 — 「자동 받기: 자동 받기 꺼 둠」처럼 머리말을 두 번 적지 않는다
    return state.text if state.text.startswith("자동 받기") else f"자동 받기: {state.text}"


def _direct_note(listing: UnifiedOpportunityListResponse) -> str:
    """직접도전 칸 안내 — 회사자료 빈칸 안내와 같은 수(38차 §3-C-7 · DOCS-04: 등록 업종을 적어도 나라장터 「가능」은 사람 확인 뒤다)."""
    from app.services import company_blank_fields, eligibility_engine

    company = eligibility_engine.company_facts_for(listing.organization_id, evidence_scope="internal")
    fields = {f.key: f for f in company_blank_fields.count_fields(
        list(listing.items), company, company_blank_fields.left_blank_of(listing.organization_id))}  # 41차 D31 「안 적음」은 권하지 않음
    industry = fields.get("registered_industries")
    tail = (
        f" 회사자료 「나라장터 등록 업종」이 비어 「확인 필요」로 남은 공고가 {len(industry.ids)}건입니다(회사자료 › 입찰 자격 자료 빈칸 안내)."
        if industry and industry.blank and not industry.left_blank
        else ""
    )
    # 43차 결정 2 · M7 — 「충족 확인을 골라야」라는 거짓 안내를 고친다(그 단추는 없다). 실제 길은 회사 단위 확인 세 칸이다.
    checks = dict((k, v) for k, *v in company.company_checks)
    if len(checks) < 3 and "company_checks" in company_blank_fields.left_blank_of(listing.organization_id):
        # 44차 대표 결정 1 — 회사 단위 확인을 비워 두기로 했다. 「적으면 통과」를 권하지 않는다.
        return (" — 회사 단위 확인(등록 · 제재 · 체납)은 대표 결정으로 비워 둠 — 나라장터 「가능」은 나오지 않고 가장 높은 칸은"
                " 「조건부 검토」입니다(정상). 공고마다 남은 조항을 원문과 보고 확인하세요." + tail)
    head = (
        " — 나라장터 등록 · 결격 줄은 회사자료 › 입찰 자격 자료의 「회사 단위 확인」(나라장터 등록 · 부정당 제재 없음 · 체납 없음 · 유효기간)을 "
        "적으면 공고마다 통과합니다. 그다음 공고마다 남은 업종 · 실적 · 기업 유형 조항을 원문과 보고 확인합니다."
        if len(checks) < 3 else " — 회사 단위 확인(등록 · 제재 · 체납)이 적혀 있습니다. 공고마다 남은 조항을 원문과 보고 확인하세요."
    )
    return head + tail


def build_markdown(listing: UnifiedOpportunityListResponse, *, now: datetime, previous: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """`(마크다운, 이번 순위표)`. 순위표는 부르는 쪽이 남긴다(`save_snapshot`)."""
    today = _kst(now).date()
    method = listing.ranking_method
    items = brief_items(listing)
    by_id = {i.id: i for i in items}
    current = snapshot_of(listing, now=now)
    diff = changes(previous, current)
    revenue = ordered([i for i in items if is_revenue(i)], method)
    benefit = ordered([i for i in items if not is_revenue(i)], method)
    live_rev = [i for i in revenue if _live(i)]
    live_ben = [i for i in benefit if _live(i)]
    calm = ("신규+여유", "직접도전", "조건부", "일반 접수 중", "선제준비")
    fetched = _kst(listing.summary.fetched_at or listing.fetched_at)
    method_text = (
        "실무 우선순위(회사 설정 — 본업 안에서 주제 맞음 먼저(「주제 확인」 · AI 「본업 아닐 수 있음」은 뒤) · 최근 신규 · 실제 마감까지 남은 기간 · "
        "접수방식 · 유형(근사) · 점수, 마감 임박은 아래 긴급 칸)"
        if method == "practical" else "회사 기준 검토 우선순위 점수순(회사 설정 — 같으면 마감 빠른 순)"
    )

    L: list[str] = []
    w = L.extend
    L.append(f"# 오늘 브리핑 — {listing.organization_name}")
    L.append("")
    L.append(f"**{fetched:%Y-%m-%d %H:%M} 기준**(목록 받은 때 · 브리핑 만든 때 {_kst(now):%Y-%m-%d %H:%M})으로 맞춤형 공고를 정리했습니다." if fetched else f"브리핑 만든 때 {_kst(now):%Y-%m-%d %H:%M}.")
    L.append("")
    opened, sites = watchlist_service.opened_today(listing.organization_id, now=now)
    L.append(
        f"> **{SOURCE_LINE}** — 웹 전수조사가 아닙니다. 기관 자체공고(이메일 · PMS · 온라인폼)는 BidPilot 이 자동으로 모으지 않습니다 — "
        f"사람이 「직접 넣기 · 후보함」에 넣은 것만 있습니다. **오늘 사람이 열어 본 곳 {opened}/{sites}**."
    )
    if bizinfo_is_sample(listing):
        L.append("> ⚠ **기업마당은 받아 둔 목록이 없어 가상 예시로 대신했습니다** — 아래 기업마당 칸은 실제 공고가 아닙니다. 이번 순위표는 남기지 않습니다(다음 브리핑이 예시와 견주지 않게).")
    L += [f"> **{_md(line)}**." for line in failure_lines(listing)]
    collect = collect_line(listing)
    if collect:
        L.append(f"> **{_md(collect)}**" if collect.startswith("⚠") else f"> {_md(collect)}")
    if ai_note := ai_note_line(listing):
        L.append(f"> {_md(ai_note)}.")
    L.append(f"> {seen_line(listing)}.")
    L.append(f"> 순서: {method_text}. 「{SCORE_NAME}」는 회사가 먼저 볼 순서를 위한 점수이고 **낙찰확률 · 선정확률이 아닙니다**. 유형(A1~D)은 근사치입니다.")
    L.append(f"> 매출(나라장터 입찰 · 기업마당 수행기관 모집) {len(live_rev)}건과 지원금(기업마당 수혜 — 매출 아님) {len(live_ben)}건을 나눠 적습니다(불가 · 관련 낮음 제외 수).")
    L.append("")

    # 2. 지난 브리핑 대비 — 38차 §3-C-5: 공고 변경(마감 · 첨부 · 차수 · 종류 · 지역 뺌)도 한 줄로
    section = listing.prepare or PrepareSection()
    edited = _edited(items, previous, now)
    seen_edit = {i.id for i, _ in edited}
    # RANK_BRIEF-02 — 차수가 바뀐 공고를 ✏️ 줄에 「차수」로 싣는다(버전 기록에 아직 없어도)
    edited += [(by_id[fresh], ["차수"]) for _old, fresh in diff.get("reissued") or [] if fresh in by_id and fresh not in seen_edit]
    w(_change_lines(diff, by_id, current, edited=edited, section=section))

    # 3. 오늘 핵심 결론 — 38차 §3-B-5: 본업 덩어리의 매출을 회사 방식 순서 앞에서부터 10건(대형 구축 · 연구는 아래 「파트너형 후보」 칸).
    top = revenue_top(listing)
    L += ["# 오늘 핵심 결론", "", "## 매출 — 입찰 · 수행기관 모집", ""]
    if top:
        first = top[0]
        L.append(
            f"가장 먼저 볼 것은 **{_md(_short(first.title, 40))}**(유형(근사) {first.fit_type} · 공고 "
            f"{_day(first.published_at, today)} · {practical.left_phrase(first, today)} · {verdict_of(first)})입니다. "
            f"TOP 표는 **본업 덩어리**(A1 · A2 · B1 · C 중 대형 아님 · 수행기관 모집)만 올립니다 — 대형 구축 · 연구는 아래 「🤝 대형 · 파트너형 후보」 칸"
            f"(광주 · 전남 발주 대형은 본업 칸에 꼬리표 「단독으로는 큼」만 달고 남깁니다), "
            f"연구 · 감리 · 구매(B2 · D)는 후보풀에. 마감 13일 이내 본업은 「본업 · 긴급」으로 표시합니다."
        )
        L.append("")
        w(_table(TOP_HEADER, _top_rows(top, today)))
        # 43차 설명(BRIEF-10 · RANK-01) — 주제 확인이 시간 등급보다 앞이라 마감 여유가 커도 긴급 공고 뒤(40차 D23)
        L += ["", "> 순서: 「주제 확인」 공고는 마감 여유가 커도 주제가 맞는 긴급 공고 뒤에 섭니다(회사 결정 D23 — 숨기지 않고 꼬리표로 남김)."]
        L += ["", f"> 「{SCORE_NAME}」 — 낙찰확률이 아닙니다. 규모 칸은 혼자 맡기 쉬운 크기를 높게 칩니다(매출 크기 아님 · 43차 설명 RANK-08). 판단 낱말은 판정 · 분류 · 규모에서 규칙으로 골랐습니다(가능 → 적극도전 · 확인 필요 → 조건부 검토 · 공급기업 등 간접 참여 → 간접 참여(회사가 직접 신청하는 자리가 아님) · 단독으로는 큰 개발 · 연구 → 「단독으로는 큼 · 파트너형」(공동수급 허용) · 「단독으로는 큼 · 공동수급 불허」 · 13일 이내 → 긴급검토).", ""]
        for n, item in enumerate(top[:3], start=1):
            L += [f"### {['🥇', '🥈', '🥉'][n - 1]} {n}순위 — {_md(item.title)}", ""]
            L.append(f"{_md(item.agency)} · 예산 {_budget(item) if item.budget else '미공개'}{(' · ' + item.award_line) if item.award_line else ''}")
            L.append("")
            L.append("**왜 맞는가**")
            L.append(f"- 유형(근사) {item.fit_type}({_md(item.fit_type_basis or '-')}) · {_md(item.fit_line or '적어 둔 사유 없음')}")
            L.append(f"- {item.practical_group} · 시간 등급 {practical.TIER_LABELS.get(item.time_tier or '', '-')} · 접수 {_methods(item)}")
            L.append("")
            L.append("**확인할 자격**")
            L.append(f"- 판정 {'가능' if item.eligibility_gate == 'PASS' else '확인 필요' if item.eligibility_gate == 'CHECK' else '불가'} — {_md(item.gate_reason or '-')}")
            unlocks, direct = split_unlocks(item.unlock_conditions)
            for unlock in unlocks[:2]:
                L.append(f"- 갖추면 가능: {_md(unlock)}")
            if len(unlocks) > 2:
                L.append(f"- 남은 조건 {len(unlocks) - 2}개 더(공고 상세에서)")
            for check in direct[:1]:
                L.append(f"- 직접 확인: {_md(check)}")
            briefing = practical.briefing_text(item, today)
            if briefing:
                L.append(f"- {briefing}")
            if item.caution_line:
                L.append(f"- 주의: {_md(item.caution_line)}")
            # 근거 줄에는 올린 공고문의 조항 원문이 실린다 — 신뢰하지 않는 글이라 이스케이프한다(38차 검토).
            L.append(f"- **{_md(item.evidence_line or '근거: -')}**" if (item.evidence_line or "").startswith("근거") else f"- 근거: {_md(item.evidence_line or '-')}")
            L.append("")
            L.append(f"**판단** {verdict_of(item)} — {_link(item, '공고 바로가기')} · {_open_link(item)}")
            L.append("")
    else:
        L += ["오늘 TOP 표에 올릴 본업 매출 공고가 없습니다 — 아래 칸들을 보세요.", ""]
    ben_top = [i for i in live_ben if i.practical_group in calm][:5]
    L += ["## 지원금 — 기업마당 수혜(매출 아님)", ""]
    # 43차 설명(BRIEF-19 · BIZ-12 · NUM-07) — 지원금은 점수 먼저(39차 D17) · 마감 13일 이내는 🚨 칸 · 순위 숫자는 지원금 안 순위
    fresh_ben_n = sum(1 for i in live_ben if i.practical_group == "신규+여유")
    L += [f"> 지원금은 점수 먼저입니다(회사 결정 D17) — 신규 {fresh_ben_n}건은 아래 「신규 · 준비여유」 칸, 마감 13일 이내는 🚨 긴급 칸에 따로 있습니다. 표의 순위는 지원금 안 순위입니다.", ""]
    if ben_top:
        w(_table(TOP_HEADER, _top_rows(ben_top, today)))
    else:
        L.append("오늘 먼저 볼 지원금 공고가 없습니다.")
    L.append("")

    # 4. 신규 · 준비여유 최우선
    fresh_rev = [i for i in live_rev if i.practical_group == "신규+여유"]
    # 43차 Q10 · BIZ-09 — 지원금은 대상 안내(참가 · 출품 · 개인 모집)를 빼고 「우선 검토」만
    fresh_ben = [i for i in live_ben if i.practical_group == "신규+여유" and not i.audience_note and i.priority_label == "우선 검토"]
    L += ["# 신규 · 준비여유 최우선 후보", "", f"공고 {practical.FRESH_DAYS}일 이내 · 실제 마감까지 21일 이상 — 매출 {len(fresh_rev)}건 · 지원금 {len(fresh_ben)}건.", ""]
    if fresh_rev or fresh_ben:
        w(_table(POOL_HEADER, _pool_rows([*fresh_rev, *fresh_ben], today)))
        L.append("")

    # 5. 직접도전
    direct_rev = [i for i in live_rev if i.practical_group == "직접도전"]
    direct_ben = [i for i in live_ben if i.practical_group == "직접도전"]
    L += ["# 직접도전 후보", ""]
    L.append(f"- 매출: 판정 「가능」 · 마감까지 14일 이상 {len(direct_rev)}건" + (_direct_note(listing) if not direct_rev else "."))
    L.append(f"- 지원금(수혜 — 매출 아님): {len(direct_ben)}건")
    L.append("")
    if direct_rev or direct_ben:
        w(_table(POOL_HEADER, _pool_rows([*direct_rev, *direct_ben], today)))
        L.append("")

    # 6. 기관 자체접수 / PMS / 이메일형 — 38차 §3-E-3: 직접 넣은 공고로 처음 찬다
    operator_calls = [i for i in live_rev if i.source_type == "bizinfo"]
    manual_live = [i for i in ordered([i for i in items if i.source_type == "manual"], method) if _live(i)]
    L += ["# 기관 자체접수 / PMS / 이메일형 후보", ""]
    L.append(
        f"기관 홈페이지 자체공고(P1 — 대학 · 산학협력단 · RISE · 전담기관의 이메일 · PMS · 온라인폼 접수)는 **{NOT_COLLECTED}**입니다(자동으로 읽지 않음). "
        f"사람이 「직접 넣기 · 후보함」에 **직접 넣은 공고 {len(manual_live)}건**(불가 · 관련 낮음 뺌) — 판정은 공고문 원문을 사람이 확인한 뒤에야 「가능」입니다."
    )
    L.append("")
    if manual_live:
        w(_table(POOL_HEADER, _pool_rows(manual_live, today)))
        L.append("")
    if operator_calls:
        L.append(f"기업마당에 올라온 **수행기관 모집(매출)** {len(operator_calls)}건:")
        L.append("")
        w(_table(POOL_HEADER, _pool_rows(operator_calls, today)))
        L.append("")
    direct_bid = [i for i in live_rev if i.source_type == "g2b" and any(m.startswith("직찰") for m in (i.submission_methods or ()))]
    L.append(f"나라장터에 올라왔지만 기관에 직접 내는 **직찰** {len(direct_bid)}건은 아래 「나라장터 후보」에 「직찰」로 적혀 있습니다.")
    L.append("")

    # 7. 나라장터 후보
    g2b_live = [i for i in live_rev if i.source_type == "g2b"]
    L += ["# 나라장터 후보", "", f"불가 · 관련 낮음을 뺀 {len(g2b_live)}건 — 회사 방식 순서(사전규격은 아래 「🔵 선제준비」 칸).", ""]
    w(_table(POOL_HEADER, _pool_rows(g2b_live, today)))
    L.append("")

    # 8. 선제준비 — 39차 결정 1: 본업 · 의견 마감 남은 사전규격 · 본공고 안 나온 발주계획만(나머지는 사업기회 「선제준비」 탭에 접음)
    pre_live = section.items
    L += ["# 🔵 선제준비 — 사전규격 · 본공고 예정", ""]
    L.append(
        f"본업 사전규격 {len(pre_live)}건 — 「의견 마감」은 **입찰 마감이 아닙니다**. 판정은 모두 「확인 필요 — 본공고 전」입니다. "
        f"다른 사전규격 {len(section.others)}건 · 의견 마감 지남 {len(section.opinion_passed)}건은 사업기회 「선제준비」 탭에 접어 두었고, "
        f"본공고가 나온 {len(section.merged)}건은 본공고 행에 「사전규격 n일 전 공개」로 합쳤습니다."
    )
    L.append("")
    if pre_live:
        w(_table(
            ("사전규격", "기관", "배정예산", "공개", "의견 마감", "유형(근사)", SCORE_NAME, "판단", "본공고 예상 · 할 일", "링크"),
            [[_short(i.title, 40), _short(i.agency, 16), _budget(i), _day(i.published_at, today),
              i.deadline_text or "-", i.fit_type or "-", _score(i), verdict_of(i), _short(i.prespec_plan or "-", 90), _links(i)] for i in pre_live],
        ))
        L.append("")
    plans = [p for p in section.plans if not p.main_out and not p.prespec_out]
    pre_out = sum(1 for p in section.plans if p.prespec_out and not p.main_out)
    L += ["## 발주 예정(발주계획)", ""]
    L.append(
        f"받아 둔 발주계획({_plan_range(section)}) 중 나라장터 공고와 같은 수집 낱말 · 후보 규칙에 맞고 본공고 · 사전규격이 아직 안 난 것 {len(plans)}건"
        f"(본공고가 이미 난 것 {sum(1 for p in section.plans if p.main_out)}건 · 사전규격이 이미 나와 위 선제준비에 있는 것 {pre_out}건 · "
        f"낱말만 걸리거나 행사 · 대행이라 후보 아님 {section.plans_low}건 · 유형(근사)이 연구 · 감리 · 구매 · 제작이라 본업 덩어리 밖 {len(section.plans_folded)}건은 뺌). "
        "발주계획은 기관이 미리 적은 계획이라 실제 공고와 다를 수 있습니다."
        + (f" ⚠ {section.plans_note}." if section.plans_note else "")
    )
    L.append("")
    if plans:
        w(_table(
            ("사업", "기관", "발주 시기", "금액", "계약방법", "링크"),
            [[_short(p.title, 44) + (" · 발주 지연" if p.delayed else ""), _short(p.agency, 16), p.when, won(p.amount) if p.amount else "-", p.method,
              _url_link(p.url, "발주계획")] for p in plans],
        ))
        L.append("")

    # 8-1. GPT · 사람이 찾은 확인 전 후보 (38차 §3-E-5) — 점수 · 판정 없음
    inbox = notice_inbox_service.pending(listing.organization_id)
    # 43차 SOURCE-06 · Q19 — 「이미 있음」 · GPT 가 이미 제외로 적은 줄은 새로 볼 것에서 따로 센다
    inbox_existing = [e for e in inbox if e.existing_id]
    inbox_gpt_out = [e for e in inbox if not e.existing_id and e.gpt_note]
    inbox_new = len(inbox) - len(inbox_existing) - len(inbox_gpt_out)
    L += [f"# 📥 GPT · 사람이 찾은 확인 전 후보 {len(inbox)}건", ""]
    if inbox:
        L += [f"새로 볼 것 {inbox_new}건 · 이미 있음 {len(inbox_existing)}건 · GPT 가 제외로 적음 {len(inbox_gpt_out)}건.", ""]
    L.append("붙여 넣은 결과에서 링크 · 공고명 · 기관 · 날짜 글자만 기계적으로 뽑은 것입니다 — **점수 · 판정을 붙이지 않았습니다**. "
             "「직접 넣기 · 후보함」에서 「정식으로 넣기」 하면 판정이 붙습니다.")
    L.append("")
    if inbox:
        rows_inbox = []
        for entry in inbox:
            hit = by_id.get(entry.existing_id or "")
            state = (
                f"이미 있음({hit.source_rank}위 · {verdict_of(hit)})" if hit is not None
                else "이미 있음(지금 목록 밖)" if entry.existing_id else (entry.gpt_note or "확인 전")
            )
            rows_inbox.append([_short(entry.title or "(공고명 못 뽑음)", 44), _short(entry.agency or "-", 16), entry.date_text or "-", state, _url_link(entry.url, "원문")])
        w(_table(("후보", "기관", "날짜(붙여 넣은 글)", "상태", "링크"), rows_inbox))
        L.append("")

    # 9. 긴급
    urgent_rev = [i for i in live_rev if i.practical_group == "긴급"]
    # RANK_BRIEF-05 — 「대형 · 파트너형 후보」 중 13일 이내는 아래 🤝 칸에만 있다 — 수는 여기에도 따로 적는다(긴급 일감을 적게 읽지 않게)
    urgent_partner = [i for i in live_rev if i.practical_group == practical.GROUP_PARTNER and i.time_tier in ("T5", "T6")]
    urgent_ben = [i for i in live_ben if i.practical_group == "긴급"]
    partner_note = f"(그 밖에 대형 · 파트너형 후보 중 13일 이내 {len(urgent_partner)}건은 아래 「🤝」 칸)" if urgent_partner else ""
    L += ["# 🚨 긴급 · 마감 임박", "",
          f"실제 마감까지 13일 이내 — 매출 {len(urgent_rev)}건{partner_note} · 지원금 {len(urgent_ben)}건. "
          "8~13일은 **긴급 검토**, 7일 이하는 **자료 · 파트너가 이미 있을 때만** 움직입니다(실무 문서 §2.5).", ""]
    rows = []
    for item in [*urgent_rev, *urgent_ben]:
        why = practical.left_phrase(item, today)
        briefing = practical.briefing_text(item, today)
        if briefing:
            why += f" · {briefing}"
        if item.deadline_note:
            why += f" · {item.deadline_note}"
        rows.append([_short(item.title, 44), _source_name(item), _deadline_cell(item, today), f"{item.fit_type or '-'} · {_score(item)}", why, _link(item)])
    if rows:
        w(_table(("공고", "출처", "마감", f"유형(근사) · {SCORE_NAME}", "왜 아래 칸인가", "링크"), rows))
        L.append("")

    # 9-1. 대형 · 파트너형 후보 (38차 §3-B-5 · D12 · D14) — 긴급 칸 뒤 · 제외 칸 앞
    partners = [i for i in live_rev if i.practical_group == practical.GROUP_PARTNER]
    by_industry = sum(1 for i in partners if i.industry_partner)
    L += ["# 🤝 대형 · 파트너형 후보", ""]
    L.append(
        # 40차 RANK-04 — 39차 결정 2 뒤로 교육 · 컨설팅도 상한의 2배를 넘으면 이 칸이다(개발 · 연구라고만 적으면 틀린 설명)
        # 44차 결정 4 — 등록 업종에 없는 업종 + 공동수급 허용 · 모름도 크기 · 지역과 상관없이 이 칸(마지막 검토 — 설명이 빠져 있었다)
        f"사업비가 회사 단독 상한을 넘는 공고 — 개발 · 연구 · 그 밖은 상한 초과, 교육 · 컨설팅은 상한의 2배 초과"
        f"(광주 · 전남 발주는 본업 칸에 남김) {len(partners) - by_industry}건 · 우리 등록 업종에 없는 업종을 요구해 공동수급"
        f"(그 업종을 가진 회사와 함께)이 필요한 공고 {by_industry}건(크기 · 지역과 상관없이) — TOP 에서 뺀 것입니다"
        "(실무 문서 「대형 SI · 순수 연구는 후순위」). 공동수급이 허용되면 「단독으로는 큼 · 파트너형」, 불허면 「단독으로는 큼 · 공동수급 불허」 — "
        "공동수급이 안 되는데 파트너로 자격을 보완한다고 가정하지 않습니다."
    )
    L.append("")
    if partners:
        w(_table(
            ("공고", "기관", "예산", "마감", "남은기간", "유형(근사)", "판단", "링크"),
            [[_short(i.title, 40), _short(i.agency, 16), _budget(i), _deadline_cell(i, today), _left(i, today),
              i.fit_type or "-", verdict_of(i), _link(i)] for i in partners],
        ))
        L.append("")

    # 10. 제외 · 비추천 (D4)
    g2b_out = [i for i in revenue if i.source_type == "g2b" and i.practical_group == "제외"]
    biz_out = [i for i in benefit + [i for i in revenue if i.source_type == "bizinfo"] if i.practical_group == "제외"]
    biz_region = [i for i in biz_out if _REGION_REASON_RE.match(i.gate_reason or "")]
    biz_other = [i for i in biz_out if i not in biz_region]
    # 「유형은 맞는데」 — 사업 목적이 회사 갈래(AI 교육 · 컨설팅 · 개발 · 공공 · 학술)인 것(`kind_fit` · D4)
    biz_region_related = [i for i in biz_region if i.kind_fit]
    low = [i for i in items if i.practical_group == "비추천"]
    L += ["# ❌ 제외 · 비추천", ""]
    L.append(f"나라장터 제외 {len(g2b_out)}건은 전부 사유와 함께 적습니다. 기업마당 제외 {len(biz_out)}건 중 지역이 아닌 사유 {len(biz_other)}건은 전부, "
             f"지역 사유 {len(biz_region)}건은 건수와 「유형은 맞는데 지역 때문에 빠진 것」(사업 목적이 회사 갈래) {len(biz_region_related)}건만 적습니다. 관련 낮음 · 후보 아님(비추천) {len(low)}건은 엑셀 「사업기회」 시트에 있습니다.")
    L.append("")
    if g2b_out:
        L += ["**나라장터**", ""]
        w(_table(("공고", "제외 사유", "링크"), [[_short(i.title, 44), (i.gate_reason or ("마감" if i.closed else "-"))[:160], _link(i)] for i in g2b_out]))
        L.append("")
    # 43차 M16 · SOURCE-01 — 직접 넣은 공고의 제외 · 비추천은 이름과 사유를 따로 적는다(사람이 넣은 것이 브리핑에서 사라졌다)
    manual_out = [i for i in items if i.source_type == "manual" and i.practical_group in ("제외", "비추천")]
    if manual_out:
        L += [f"**직접 넣은 공고 — 제외 · 비추천 {len(manual_out)}건**", ""]
        w(_table(("공고", "칸", "사유", "링크"), [
            [_short(i.title, 44), i.practical_group or "-", _short(i.relevance_note or i.gate_reason or ("마감" if i.closed else "-"), 120), _link(i)]
            for i in manual_out
        ]))
        L.append("")
    if biz_other:
        L += ["**기업마당 — 지역이 아닌 사유**", ""]
        w(_table(("공고", "제외 사유", "링크"), [[_short(i.title, 44), (i.gate_reason or "-")[:160], _link(i)] for i in biz_other]))
        L.append("")
    if biz_region_related:
        L += [f"**기업마당 — 유형은 맞는데 지역 때문에 빠진 것 {len(biz_region_related)}건**(지역 불가 전체 {len(biz_region)}건)", ""]
        w(_table(("공고", "지역 사유", "링크"), [[_short(i.title, 44), (i.gate_reason or "-")[:120], _link(i)] for i in biz_region_related]))
        L.append("")
    if low:
        # 43차 BRIEF-01 · D15 — 비추천은 사유 묶음별 건수 + 대표 한 줄(전체 사유는 엑셀 「비추천 사유」 열)
        bundles: dict[str, list[UnifiedOpportunity]] = {}
        for item in low:
            bundles.setdefault(_low_bundle(item.relevance_note), []).append(item)
        L += [f"**비추천(관련 낮음 · 후보 아님) {len(low)}건 — 사유 묶음별**", ""]
        w(_table(
            ("사유 묶음", "건수", "대표 공고 · 사유"),
            [[name, f"{len(rows)}", f"{_short(rows[0].title, 34)} — {_short(rows[0].relevance_note or '관련 낮음', 70)}"]
             for name, rows in sorted(bundles.items(), key=lambda kv: -len(kv[1]))],
        ))
        L.append("")

    # 11. 광주 · 전남 / 대학 시장 신호
    home = [i for i in g2b_live if priority.home_ground(i.agency, i.demand_agency)]
    univ = [i for i in g2b_live if _UNIVERSITY_RE.search(i.agency or "")]
    edu_univ = [i for i in univ if (i.fit_type or "") in ("A1", "A2")]
    urgent_univ = [i for i in edu_univ if i.practical_group == "긴급"]
    home_ben = [i for i in live_ben if priority.home_ground(i.agency, i.executing_agency)]
    L += ["# 광주 · 전남 / 대학 시장 신호", ""]
    L.append(f"- 대학 · 산학협력단 발주: 나라장터 후보 {len(g2b_live)}건 중 {len(univ)}건 — 그중 교육(유형(근사) A1 · A2) {len(edu_univ)}건, 그중 긴급 {len(urgent_univ)}건.")
    L.append("- 광주 · 전남 발주 나라장터: " + (", ".join(f"{_md(_short(i.title, 30))}({i.practical_group}) {_link(i)}" for i in home) if home else "없음"))
    L.append(f"- 광주 · 전남 소관 기업마당(지원금): {len(home_ben)}건.")
    L.append("")

    # 12. 전체 후보풀
    pool_ben = [i for i in live_ben if i.practical_group in ("신규+여유", "직접도전", "조건부")]
    L += ["# 오늘 전수조사 전체 후보풀", ""]
    # 43차 BRIEF-22 — 나라장터 매출은 위 「나라장터 후보」 표에 이미 있다(같은 206행이 두 번 실려 1,081줄이었다)
    pool_rev = [i for i in live_rev if i.source_type != "g2b"]
    L.append(f"나라장터 매출 {len(live_rev) - len(pool_rev)}건은 위 「나라장터 후보」 표에 있어 다시 적지 않습니다. 여기는 그 밖의 매출(직접 넣음 · 기업마당 수행기관 모집) "
             f"{len(pool_rev)}건과 지원금 신규+여유 · 직접도전 · 조건부 {len(pool_ben)}건입니다. "
             f"나머지 지원금(일반 접수 중 · 긴급 {len(live_ben) - len(pool_ben)}건)은 엑셀 「사업기회」 시트에 있습니다.")
    L.append("")
    w(_table(POOL_HEADER, _pool_rows([*pool_rev, *pool_ben], today)))
    L.append("")

    # 13. 오늘 실제 행동
    L += ["# 오늘 실제 행동 우선순위", ""]
    actions = [*top[:4], *direct_ben[:1]]
    if not actions:
        actions = live_rev[:3]
    for n, item in enumerate(actions, start=1):
        L.append(f"{n}. **{_md(_short(item.title, 40))}** — {_md(next_step_of(item))} {_links(item, '공고')} · {_next_paths(item)}")
    # 43차 Q5 — 끝에 선제준비 1건(의견 마감 가까운 A1 · A2 · 칸 순서 그대로)
    prep = next((i for i in (listing.prepare.items if listing.prepare else []) if i.fit_type in ("A1", "A2")), None)
    if prep is not None:
        L.append(
            f"{len(actions) + 1}. **{_md(_short(prep.title, 40))}** — 선제준비: 규격서 읽기 → 자격 · 실적 미리 확인 → "
            f"의견 마감({_md(prep.deadline_text or '-')}) 전 의견 등록 {_link(prep, '규격서')}"
        )
    if not actions:
        L.append("오늘 움직일 공고가 없습니다.")
    L.append("")
    L.append("> 「오늘 실제 행동」은 공고마다 BidPilot 이 이미 적어 둔 「다음 할 일」 · 「갖추면 가능」 · 「직접 확인」을 옮긴 것입니다. 참여 여부는 사람이 정합니다.")
    L.append("")
    return "\n".join(L), current


# --------------------------------------------------------------------------
# 엑셀 「브리핑」 시트
# --------------------------------------------------------------------------

SHEET_COLUMNS: tuple[str, ...] = (
    "갈래", "칸", "순", "공고명", "기관", "공고일", "마감", "남은기간", "접수방식", "유형(근사)", SCORE_NAME, "판단", "판정 사유", "링크",
)


def sheet_rows(listing: UnifiedOpportunityListResponse, *, now: datetime) -> tuple[list[list[Any]], list[str]]:
    """`(행들, 맨 아래 메모 줄)`. 매출 → 지원금, 각 회사 방식 순서 · 제외는 맨 아래(사유와 함께)."""
    today = _kst(now).date()
    method = listing.ranking_method
    out: list[list[Any]] = []
    items = brief_items(listing)
    for part, members in (("매출", [i for i in items if is_revenue(i)]), ("지원금(수혜)", [i for i in items if not is_revenue(i)])):
        rank = 0
        for item in ordered(members, method):
            if item.practical_group == "비추천":
                continue
            live = item.practical_group != "제외"
            if live:
                rank += 1
            real = practical.effective_deadline(item)
            out.append([
                part,
                item.practical_group or "",
                rank if live else "",
                item.title,
                item.agency,
                _kst(item.published_at).replace(tzinfo=None) if item.published_at else "",
                (practical.deadline_stamp(item) if not practical.deadline_time_known(item) else _kst(real).replace(tzinfo=None))
                if real else (item.deadline_text or ""),
                _left(item, today),
                _methods(item),
                item.fit_type or "",
                item.company_priority_score if item.company_priority_score is not None else "미산정",
                verdict_of(item),
                item.gate_reason or "",
                item.detail_url or "",
            ])
    fetched = _kst(listing.summary.fetched_at or listing.fetched_at)
    notes = [
        f"{SOURCE_LINE} · 목록 받은 때 {fetched:%Y-%m-%d %H:%M}" if fetched else SOURCE_LINE,
        *failure_lines(listing),
        *([line] if (line := collect_line(listing)) else []),
        *([line] if (line := ai_note_line(listing)) else []),
        seen_line(listing),
        f"「{SCORE_NAME}」는 낙찰확률 · 선정확률이 아닙니다 · 유형(근사)는 제목 · 요약 낱말로 짐작한 갈래입니다 · 관련 낮음 · 후보 아님(비추천)은 이 시트에서 뺐습니다(「사업기회」 시트에 있음)",
        f"기관 자체공고(이메일 · PMS · 온라인폼): {NOT_COLLECTED} · 「의견 마감」(사전규격)은 입찰 마감이 아닙니다",
    ]
    # 사전규격(본업 · 의견 마감 남음) · 발주 예정(본공고 안 난 것) — 입찰 목록 밖이라 맨 아래에 따로(38차 §3-D-4 · 39차 결정 1)
    section = listing.prepare or PrepareSection()
    for item in section.items:
        out.append([
            "사전규격(선제준비)", "선제준비", "", item.title, item.agency,
            _kst(item.published_at).replace(tzinfo=None) if item.published_at else "", item.deadline_text or "", "", "-",
            item.fit_type or "", item.company_priority_score if item.company_priority_score is not None else "미산정",
            verdict_of(item), item.gate_reason or "", item.detail_url or "",
        ])
    for plan in section.plans:
        if plan.main_out or plan.prespec_out:
            continue
        out.append([
            "발주 예정(발주계획)", "선제준비", "", plan.title, plan.agency, "", f"발주 {plan.when}", "", plan.method, "",
            "미산정", "선제준비", "발주계획 — 공고 전", plan.url or "",
        ])
    return out, notes


def filename(organization_name: str, *, now: datetime) -> str:
    stamp = _kst(now).strftime("%Y%m%d-%H%M")
    name = re.sub(r"[^0-9A-Za-z가-힣._-]+", "", organization_name or "회사") or "회사"
    return f"BidPilot_오늘브리핑_{name}_{stamp}.md"
