"""평일 아침 슬랙 브리핑(2.6.0 · 대표 11-06 「슬랙으로 평일 아침마다 브리핑 내용 전송하는 기능 추가해줘」).

화면 「오늘 브리핑」(`opportunity_brief_service`)과 **같은 고르기 함수**로 짧은 슬랙 글을 만든다 — 새 판정 · 점수 · 순서를 만들지 않는다.
받은 때 한 줄 · 출처 실패 · 매출 TOP 5 · 지원금 TOP 3 · 마감 13일 이내 본업 · 선제준비 건수 · 「낙찰 · 선정 확률이 아님」.

- 보내는 곳은 슬랙 「Incoming Webhook」 주소 하나(`SLACK_WEBHOOK_URL` · **회사 서버 `.env` 에만** — 노트북도 매일 받으므로
  둘 다 적으면 두 번 간다). 주소는 비밀이라 로그 · 오류 글에 싣지 않고, `https://hooks.slack.com/` 주소만 받는다(오타로 다른 곳에 회사 글이 가지 않게).
- 언제: 평일(KST 월~금)에 **하루 한 번**(`slack_brief.json` 에 보낸 날을 적는다). 오늘 나라장터 목록을 받은 뒤에만 보내되,
  `FINAL_HOUR`(11시) 넘은 마지막 시도는 받지 못했어도 그 사실(받은 때 한 줄)과 함께 보낸다. 공휴일은 따로 거르지 않는다.
- 브리핑 「지난 브리핑 대비」 순위표(`save_snapshot`)는 남기지 않는다 — 사람이 화면에서 내려받을 때의 비교 기준을 바꾸지 않게.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from app.core import storage
from app.core.config import get_settings
from app.core.paths import DATA_ROOT
from app.schemas.business_opportunity import UnifiedOpportunity, UnifiedOpportunityListResponse
from app.services import opportunity_brief_service as brief
from app.services import practical_priority as practical

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
SENT_FILE = DATA_ROOT / "private" / "slack_brief.json"
#: 이 시각(KST) 뒤 시도는 오늘 목록을 받지 못했어도 보낸다(cron 07:40 · 09:40 · 11:40 의 마지막).
FINAL_HOUR = 11
WEBHOOK_PREFIX = "https://hooks.slack.com/"
BRIEF_DAYS = 30  # 화면 브리핑 내려받기와 같은 기간(`/api/business-opportunities/export` 기본)
TOP_REVENUE = 5
TOP_BENEFIT = 3
URGENT_SHOW = 3
PREPARE_SHOW = 2
TITLE_LIMIT = 46
#: 슬랙 칸 하나 글자 상한(3000)보다 넉넉히 짧게.
SECTION_LIMIT = 2800
WEEKDAYS = "월화수목금토일"


class SlackBriefError(RuntimeError):
    """보내지 못함 — 글은 한국어 한 줄(주소 · 응답 원문 긴 글은 싣지 않는다)."""


# --------------------------------------------------------------------------
# 언제 보낼까
# --------------------------------------------------------------------------


def webhook_url() -> str | None:
    """설정된 슬랙 주소 — 없으면 None(보내지 않음). `hooks.slack.com` 이 아니면 잘못 적은 것으로 본다."""
    url = (get_settings().slack_webhook_url or "").strip()
    if not url:
        return None
    if not url.startswith(WEBHOOK_PREFIX):
        raise SlackBriefError("SLACK_WEBHOOK_URL 이 슬랙 주소(https://hooks.slack.com/…)가 아닙니다 — 서버 .env 를 확인하세요")
    return url


def sent_on() -> date | None:
    """보낸 날 — 파일이 없거나 깨졌으면 None(깨진 파일은 `read_json` 이 옆으로 비킨다 · 다음 보내기가 새로 쓴다)."""
    try:
        data = storage.read_json(SENT_FILE, default=None)
    except (storage.CorruptJsonError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return date.fromisoformat(str(data.get("sent_on")))
    except ValueError:
        return None


def mark_sent(now: datetime) -> None:
    storage.write_json_atomic(SENT_FILE, {"sent_on": now.astimezone(KST).date().isoformat(), "sent_at": now.isoformat()})


def is_final(now: datetime) -> bool:
    """그날 마지막 시도인가(`FINAL_HOUR` 뒤) — 받지 못했어도 보낸다."""
    return now.astimezone(KST).hour >= FINAL_HOUR


def precheck(now: datetime) -> str | None:
    """받기 기록을 보기 전의 값싼 검사 — 안 보내는 까닭(주말 · 오늘 이미 보냄) 또는 None. 받기 잠금 기다림보다 먼저 부른다."""
    local = now.astimezone(KST)
    if local.weekday() >= 5:
        return f"{WEEKDAYS[local.weekday()]}요일 — 평일 아침에만 보냅니다"
    if sent_on() == local.date():
        return "오늘 이미 보냄"
    return None


def due(now: datetime) -> tuple[bool, str | None]:
    """지금 보낼까 — `(보낸다, 안 보내는 까닭)`. 네트워크를 쓰지 않는다(받기 기록 · 보낸 날 파일만 읽는다)."""
    from app.services import auto_collect

    if why := precheck(now):
        return False, why
    if any(ok for _moment, ok in auto_collect.attempts_today(now)):
        return True, None
    if is_final(now):
        return True, None  # 마지막 시도 — 받지 못한 사실을 받은 때 한 줄로 알린다
    return False, "오늘 나라장터 목록을 아직 받지 못함 — 다음 시도에 다시"


# --------------------------------------------------------------------------
# 글 만들기
# --------------------------------------------------------------------------


def _esc(text: Any) -> str:
    """슬랙 mrkdwn 이스케이프(&amp; · &lt; · &gt;) — 공고명 · 기관명은 바깥에서 온 글이다. 줄바꿈은 한 칸으로."""
    flat = " ".join(str(text if text is not None else "").split())
    return flat.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _link(url: str | None, text: str) -> str:
    """`<주소|글>` — https 만(`brief._safe_url` · 「|」 「>」 퍼센트). 주소가 없으면 글만."""
    safe = brief._safe_url(url)
    label = _esc(text).replace("|", "/")
    return f"<{safe}|{label}>" if safe else label


def _short(title: str) -> str:
    return brief._short(title, TITLE_LIMIT)


def item_line(n: int, item: UnifiedOpportunity, today: date) -> str:
    """「1. <공고|공고명> — 기관 · 마감 11/20 · 13일 · *조건부 검토*」 — 판단 칸은 브리핑 TOP 표와 같은 함수(`_top_verdict`)."""
    deadline = practical.deadline_display(item, today)
    when = f"마감 {deadline}" if deadline[:1].isdigit() else deadline  # 「마감 미상 — …」 · 「예산 소진시까지」에는 붙이지 않는다
    left = practical.days_left(item, today)
    if left is not None:  # 「마감일 없음 · 마감 미상」은 앞 칸이 이미 말한다
        when += f" · {brief._left(item, today)}"
    return f"{n}. {_link(item.detail_url, _short(item.title))} — {_esc(item.agency)} · {_esc(when)} · *{_esc(brief._top_verdict(item))}*"


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": _fit(text.split("\n"))}}


def _fit(lines: list[str]) -> str:
    """칸 글자 상한 안에서 **줄 단위로** 자른다(링크 `<주소|글>` 가운데서 끊지 않게) — 못 실은 줄은 「외 n줄」."""
    out: list[str] = []
    for n, line in enumerate(lines):
        rest = len(lines) - n
        if len("\n".join([*out, line])) > SECTION_LIMIT - 20:
            out.append(f"…외 {rest}줄")
            break
        out.append(line)
    return "\n".join(out)


def _context(text: str) -> dict[str, Any]:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": _fit(text.split("\n"))}]}


def build_message(listing: UnifiedOpportunityListResponse, *, now: datetime) -> dict[str, Any]:
    """슬랙 글(`{"text", "blocks"}`) — 화면 브리핑과 같은 목록 · 고르기 함수. 새 판정을 만들지 않는다."""
    local = now.astimezone(KST)
    today = local.date()
    method = listing.ranking_method
    items = brief.brief_items(listing)
    revenue_top = brief.revenue_top(listing)[:TOP_REVENUE]
    benefit = brief.ordered([i for i in items if not brief.is_revenue(i) and brief._live(i)], method)
    calm = ("신규+여유", "직접도전", "조건부", "일반 접수 중", "선제준비")
    benefit_top = [i for i in benefit if i.practical_group in calm][:TOP_BENEFIT]
    shown = {i.id for i in revenue_top}
    urgent = [
        i for i in brief.ordered([i for i in items if brief.is_revenue(i) and brief._live(i)], method)
        if i.time_tier in ("T5", "T6") and (i.practical_block or practical.BLOCK_CORE) == practical.BLOCK_CORE
    ]
    prepare = (listing.prepare.items if listing.prepare else []) or []

    title = f"📋 오늘 브리핑 — {listing.organization_name} · {local:%m/%d}({WEEKDAYS[local.weekday()]})"
    blocks: list[dict[str, Any]] = [{"type": "header", "text": {"type": "plain_text", "text": title[:150], "emoji": True}}]
    head = [_esc(line) for line in brief.failure_lines(listing)]
    if collect := brief.collect_line(listing):
        head.insert(0, _esc(collect))
    if head:
        blocks.append(_context("\n".join(head)))

    if revenue_top:
        lines = [item_line(n, item, today) for n, item in enumerate(revenue_top, start=1)]
        blocks.append(_section(f"*💼 매출 — 입찰 · 수행기관 모집 TOP {len(revenue_top)}*\n" + "\n".join(lines)))
    else:
        blocks.append(_section("*💼 매출 — 입찰 · 수행기관 모집*\n오늘 TOP 에 올릴 본업 매출 공고가 없습니다."))
    if benefit_top:
        lines = [item_line(n, item, today) for n, item in enumerate(benefit_top, start=1)]
        blocks.append(_section(f"*💰 지원금 — 기업마당 수혜(매출 아님) TOP {len(benefit_top)}*\n" + "\n".join(lines)))
    more_urgent = [i for i in urgent if i.id not in shown][:URGENT_SHOW]
    if urgent:
        text = f"*🚨 마감 13일 이내 본업 {len(urgent)}건*"
        if more_urgent:
            text += "(위 TOP 밖)\n" + "\n".join(item_line(n, i, today) for n, i in enumerate(more_urgent, start=1))
        else:
            text += " — 모두 위 TOP 에 있습니다."
        blocks.append(_section(text))
    if prepare:
        names = " · ".join(_link(i.detail_url, _short(i.title)) for i in prepare[:PREPARE_SHOW])
        extra = f" 외 {len(prepare) - PREPARE_SHOW}건" if len(prepare) > PREPARE_SHOW else ""
        blocks.append(_section(f"*🔵 선제준비(사전규격 · 의견 마감 남음) {len(prepare)}건* — {names}{extra}"))

    app = get_settings().frontend_url.rstrip("/")
    footer = f"「{brief.SCORE_NAME}」 순서는 회사가 먼저 볼 순서이고 *낙찰 · 선정 확률이 아닙니다*."
    if app.startswith("https://"):
        footer += f" 전체 브리핑 · 판정 근거는 {_link(app + '/opportunities', 'BidPilot 사업기회')}에서."
    blocks.append(_context(footer))
    fallback = f"오늘 브리핑 — {listing.organization_name} · 매출 TOP {len(revenue_top)} · 지원금 {len(benefit_top)} · 마감 13일 이내 본업 {len(urgent)}"
    return {"text": fallback, "blocks": blocks}


# --------------------------------------------------------------------------
# 보내기
# --------------------------------------------------------------------------


def send(payload: dict[str, Any], url: str, *, timeout: float = 15.0, transport: httpx.BaseTransport | None = None) -> None:
    """슬랙 웹훅으로 보낸다. 실패면 `SlackBriefError`(주소 · 바깥 예외 원문은 싣지 않는다 — httpx 글에 주소가 들 수 있다)."""
    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            response = client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise SlackBriefError(f"슬랙에 보내지 못했습니다 — 연결 오류({type(exc).__name__})") from None
    body = (response.text or "").strip()
    if response.status_code != 200 or body != "ok":
        # 슬랙 오류 낱말(no_service · invalid_payload · channel_is_archived …)만 앞 60자
        raise SlackBriefError(f"슬랙이 받지 않았습니다 — {response.status_code} {body[:60]}")


async def listing_for(organization_id: str, now: datetime) -> UnifiedOpportunityListResponse:
    """화면 브리핑과 같은 목록(`insights._brief_listing` — 두 출처 · 불가 포함 · 마감 뺌 · 선제준비 포함)."""
    from app.schemas.organization import AnalysisContext
    from app.services import opportunity_service

    return await opportunity_service.list_opportunities(
        context=AnalysisContext(organization_id=organization_id, evidence_scope="internal"),
        source="all", days=BRIEF_DAYS, sort=None, include_closed=False, include_blocked=True, with_prepare=True, now=now,
    )


async def run(now: datetime, *, force: bool = False, send_it: bool = True) -> dict[str, Any]:
    """한 번 실행 — 로그 한 줄(dict)을 돌려준다. `force` 는 평일 · 하루 한 번 · 받기 기다림을 건너뛴다(시험 보내기).
    `send_it=False` 면 글만 만든다(네트워크 0 · 보낸 날도 적지 않음)."""
    row: dict[str, Any] = {"시각": now.isoformat(), "보냄": False}
    try:
        url = webhook_url() if send_it else None
    except SlackBriefError as exc:
        return {**row, "실패": True, "사유": str(exc)}
    if send_it and url is None:
        return {**row, "사유": "SLACK_WEBHOOK_URL 이 없습니다 — 슬랙 브리핑 꺼 둠(회사 서버 .env 에만 적습니다)"}
    if send_it and not force:
        go, why = due(now)
        if not go:
            return {**row, "사유": why}
    organization_id = get_settings().default_organization_id
    listing = await listing_for(organization_id, now)
    payload = build_message(listing, now=now)
    row["회사"] = organization_id
    row["칸"] = len(payload["blocks"])
    if not send_it:
        return {**row, "사유": "글만 만듦(보내지 않음)", "글": payload}
    try:
        send(payload, url or "")
    except SlackBriefError as exc:
        logger.warning("슬랙 브리핑 실패: %s", exc)
        return {**row, "실패": True, "사유": str(exc)}
    if not force:
        mark_sent(now)
    return {**row, "보냄": True}
