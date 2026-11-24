#!/usr/bin/env python
"""하루 한 번 공고 목록을 받아 둔다 (0919.md §4-B-2).

## 왜 필요한가

「오늘 달라진 것」(대시보드 한 줄 띠)의 「변경된 공고」는 **목록을 실제로 받아올 때만**
쌓인다. 공고 버전 기록이 `save_cache()` 안에서 직전 값과 비교해 만들어지기 때문이다.
그래서 아무도 목록을 새로 받지 않으면 그 숫자는 영영 0 이고, 화면은 「변경이 없다」가
아니라 「그동안 받아온 적이 없다」는 뜻의 0 을 보여주게 된다.

사람이 매일 화면을 여는 것으로도 되지만, 열지 않은 날은 비어 버린다. 이 스크립트를
스케줄러에 걸어 두면 그 구멍이 메워진다. 거는 방법은 `docs/getting_started.md`
「매일 아침 자동으로 받아 두기」에 있다.

## 무엇을 하는가 — 그리고 하지 않는가

**한다**: 나라장터·기업마당을 각각 **한 번씩** 조회하고, 그 결과로 캐시 파일과 공고 버전
기록을 갱신한다. 그리고 기업마당에서 **새로 들어온 관련 공고의 공고문**을 이어서 받는다
(0924 §4-A-2) — 공고당 한 번이고, 이미 받은 것은 건드리지 않는다. 파일 서버 호출이라
기업마당 OpenAPI 한도와 무관하다.

**한 가지 예외(40차 · 담당자 결정 2)**: 회사 설정 `ai_fit_assist` 를 켠 회사만, 마지막 단계에서 규칙이 본업이라 한 **새 공고**를
하루 최대 1회 Claude CLI 에 묻는다(`app.services.ai_fit_service` — 공고명 · 조달분류 · 기관 · 예산만 · 판정 · 점수는 바꾸지 않음).

**하지 않는다**: 그 밖의 분석 · LLM 호출 · 요구사항 추출 · 결정 변경 · 회사자료 색인. 하나도 건드리지
않는다. 받아 두기만 하는 스크립트다.

## 기본값이 `--dry-run` 인 이유

이 스크립트가 실제로 하는 일은 **바깥을 부르고 살아 있는 저장본을 덮어쓰는** 것이다
(`data/private/cache/g2b/g2b_cache.json` · Git 밖 — 33차부터. 추적 파일 `data/public/sample_procurements/g2b_cache.json` 은
기준본이라 이 스크립트가 쓰지 않는다). 시연 전날 무심코 돌리면 공고 건수와 순위가 바뀌어 큐시트·리허설 캡처와 어긋난다
(ISSUE-062).

그래서 아무 옵션 없이 돌리면 **무엇을 할 예정인지만** 말하고 끝난다. 실제로 받아오려면
`--run` 을 붙여야 한다. 스케줄러에 등록할 때 한 번 의식적으로 적게 하려는 것이다.

    python scripts/collect_daily.py            # 예정만 출력 (기본)
    python scripts/collect_daily.py --run      # 실제로 받아온다
    python scripts/collect_daily.py --run --json   # 결과를 JSON 한 줄로 (로그 수집용)

## 막는 법 — `.env` 로는 막히지 않는다

이 스크립트는 실시간 문을 `setdefault` 로 **스스로 연다**. 환경변수가 `.env` 보다 먼저라, `.env` 에 `G2B_LIVE_FETCH=0` 을
적어도 막히지 않는다(33차 · 옛 최신화 절차서 발견 B 실측 · 지금 절차는 `docs/refresh_procedure.md` §1). 서버의 `-Frozen` 도 다른 프로세스라 상관없다. 막히는 것은 **이 명령을
띄운 셸의 환경변수가 0** 일 때뿐이다(그때는 받아오지 않고 그 사실을 말한 뒤 종료 코드 0).

예약 작업으로 걸어 두었다면 시연 · 검수 기간에는 **`Disable-ScheduledTask -TaskName BidPilot-DailyCollect`** 로 끈다.

종료 코드: 0 = 정상(예정 출력·고정 모드 · 「오늘 이미 받음」 포함), 1 = 조회 실패, 3 = 이미 받는 중(지금 받기만),
4 = 네트워크 없음(41차 COLLECT-R40-02 — 지금 받기가 「다 받았습니다」라고 하지 않게).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

# ---------------------------------------------------------------------------
# **앱을 import 하기 전에** 실호출을 연다 (ISSUE-120 · prompt_03 §4-A-2).
#
# 설정 기본값이 「꺼짐」이다 — 아무것도 세우지 않고 앱을 import 하면 바깥을 부르지 못한다.
# 이 스크립트는 **받아 오는 것이 일**이므로 자기 손으로 연다. 여는 자리를 스크립트 안에
# 두는 이유는, 환경변수를 셸에 남겨 두면 그 셸에서 돌린 다음 스크립트까지 함께 열리기
# 때문이다(11·12·13차 사고가 전부 그 모양이었다).
#
# 순서가 핵심이다. 아래 import 가 설정을 읽으므로 그 뒤에 세우면 이미 늦다.
# `setdefault` 를 쓰는 이유: 셸이 `0` 으로 고정해 두었으면 그 뜻을 이긴다고 보지 않는다 —
# 시연 주간에 고정 모드로 바꿔 두면 스케줄러가 걸려 있어도 캐시가 바뀌지 않아야 한다.
os.environ.setdefault("G2B_LIVE_FETCH", "1")
os.environ.setdefault("BIZINFO_LIVE_FETCH", "1")
# 38차 §3-C-1 — 나라장터 입찰공고문(첨부)도 이 스크립트가 받는다(담당자 결정 5 · 하루 최대 20건). 셸이 0 이면 그 뜻을 따른다.
os.environ.setdefault("ATTACHMENT_FETCH", "1")

from app.core import storage  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.services import (  # noqa: E402
    bizinfo_client,
    bizinfo_service,
    collect_keywords_service,
    g2b_client,
    prespec_service,
    procurement_service,
)

OK = "  [OK]   "
SKIP = "  [건너뜀] "
BAD = "  [!!]   "

#: 한 번에 받아올 조회 기간(일). 화면 기본값(14)보다 넉넉히 잡는다 — 버전 기록은 여러 날에
#: 걸쳐 쌓이므로, 창이 좁으면 며칠 전 공고의 변경을 놓친다.
DEFAULT_DAYS = 30


def _short(path: Path) -> str:
    """저장소 안이면 상대 경로로, 밖이면(테스트가 `DATA_DIR` 을 옮겼을 때) 그대로."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _frozen() -> tuple[bool, list[str]]:
    """시연 고정 모드인가. 어느 쪽이 고정인지도 함께 돌려준다."""
    frozen_sources = []
    if not procurement_service.live_fetch_enabled():
        frozen_sources.append("나라장터(G2B_LIVE_FETCH=0)")
    if not bizinfo_service.live_fetch_enabled():
        frozen_sources.append("기업마당(BIZINFO_LIVE_FETCH=0)")
    return bool(frozen_sources), frozen_sources


async def _collect_g2b(days: int, *, full_window: bool = False) -> dict[str, Any]:
    result = await procurement_service.list_ai_candidates(
        days=days, refresh=True, full_window=full_window
    )
    return {
        "출처": "나라장터",
        "결과": result.source,
        "받아온_건수": result.total_fetched,
        "후보_건수": len(result.notices),
        "수집_방식": result.collected_by,
        "호출_횟수": result.collect_calls,
        # 자격(면허 · 지역 제한) 하루치 — 새로 받은 날 수 · 부른 횟수 · 못 받은 사유. 예약 작업 기록에 남지 않았다(34차 R33-R4).
        "자격_새로_받은_날": result.qualification_days_fetched,
        "자격_호출": result.qualification_calls,
        "자격_사유": result.qualification_note,
        # 받아 왔지만 분류가 none(본업 · 수집 낱말 없음)이라 저장하지 않은 수(39차 COLLECT-09)
        "분류_없음_버림": result.dropped_none,
        # 39차 DAILY-06 · 02 — 이번 실행의 실패 호출 수 · 낱말 일부 실패(그 몫은 지난 저장본으로 채움)
        "실패_호출": result.failed_calls,
        "일부_실패": result.partial_failure,
        "조회_시각": result.fetched_at.isoformat(),
        "오류": result.error,
    }


async def _collect_bizinfo() -> dict[str, Any]:
    # 전체를 받는다(호출은 1회). 기본값 100 으로 받아 온 것이 캐시가 100건이던 이유다
    # (0921 §4-A-4 · §3-10 기업마당 1회).
    response = await bizinfo_service.list_programs(refresh=True, count=bizinfo_client.FULL_COUNT)
    return {
        "출처": "기업마당",
        "결과": response.source,
        "받아온_건수": response.total_fetched,
        "후보_건수": response.count,
        "조회_시각": response.fetched_at.isoformat() if response.fetched_at else None,
        "오류": response.error,
    }


#: 하루에 새로 받을 공고문 수 상한. 남의 파일 서버라 한 번에 몰아 받지 않는다.
DAILY_DOCUMENT_LIMIT = 40


async def _collect_bizinfo_documents(limit: int = DAILY_DOCUMENT_LIMIT) -> dict[str, Any]:
    """새로 들어온 관련 공고의 공고문을 이어서 받는다 (0924 §4-A-2).

    받을 대상은 **관련 있고 마감 전인 것 중 검토 우선순위 상위**다. 이미 받은 공고는
    건너뛴다 — 공고당 한 번이다. 실패해도 목록 수집은 이미 끝나 있다.
    """
    from app.schemas.organization import AnalysisContext
    from app.services import bizinfo_document_store as store
    from app.services import opportunity_service

    settings = get_settings()
    context = AnalysisContext(
        organization_id=settings.default_organization_id, evidence_scope="internal"
    )
    # 43차 M8 · BIZ-07 — 점수 상위 200건 창을 없앤다(유일한 매출 공고 28점 · 372위의 공고문을 계속 받지 않았다 — 공고문이 없어 점수가
    # 낮고 점수가 낮아 공고문을 안 받는 고리). 양은 하루 상한이 막는다. 수행기관 모집 · 공급기업 공고를 먼저 받는다.
    listing = await opportunity_service.list_opportunities(
        context=context, source="bizinfo", days=30, sort="priority"
    )
    from app.services import auto_collect

    # 41차 D33 — 하루 상한은 그날 합계(일부 실패 뒤 다시 받기마다 새로 채우지 않는다)
    limit = max(0, limit - auto_collect.done_today(datetime.now(timezone.utc), "기업마당 공고문", "새로_받은_건수"))
    known = store.known_ids()
    payload = storage.read_json(bizinfo_service.CACHE_FILE, default=None)
    raw = {
        str(i.get("pblancId")): i
        for i in (payload.get("items") or [] if isinstance(payload, dict) else [])
        if isinstance(i, dict)
    }
    todo = []
    from app.services import practical_priority as practical

    first = [i for i in listing.items if i.recruit_kind == practical.RECRUIT_OPERATOR or "공급기업" in (i.title or "")]
    ordered = [*first, *(i for i in listing.items if i not in first)]
    for item in ordered:
        if len(todo) >= limit:
            break
        if item.closed or item.relevance_note:
            continue
        program_id = item.id.removeprefix("bizinfo-")
        if program_id in known or program_id not in raw:
            continue
        todo.append(raw[program_id])
        if len(todo) >= limit:
            break

    index, fresh = await store.fetch_many(todo)
    counts = index.counts()
    return {
        "출처": "기업마당 공고문",
        "결과": "받음" if fresh else "새로 받을 것 없음",
        "새로_받은_건수": len(fresh),
        "본문": counts["text"],
        "이미지": counts["image"],
        "실패": counts["failed"],
        "저장소_전체": counts["total"],
    }


#: 하루에 새로 받을 나라장터 입찰공고문 수 상한 (38차 §3-C-1 · 담당자 결정 5). 남의 파일 서버라 몰아 받지 않는다.
DAILY_G2B_DOCUMENT_LIMIT = 20
#: 나라장터 공고문 사이 쉬는 초.
G2B_DOCUMENT_DELAY = 0.6
#: 추출기 판이 바뀐 조항 파일을 한 번에 다시 뽑는 수 상한(39차 DAILY-01 · 받아 둔 첨부만 연다 · 네트워크 0).
G2B_REEXTRACT_LIMIT = 40
#: 담당자가 따로 허락할 때만 받는 공고(19차 메모 · `fetch_qualification_clauses.HOLD_BASE_NOS` 와 같은 값).
G2B_HOLD_BASE_NOS = frozenset({"R26BK01726154"})


def reextract_stale(items: list[Any], raw: dict[str, Any], limit: int = G2B_REEXTRACT_LIMIT) -> int:
    """추출기 판이 다른 조항 파일을 **받아 둔 첨부로** 다시 뽑아 Git 밖에 쓴다 — 네트워크 0 (39차 DAILY-01 · 40차 CLAUSE-03).

    내려받기 대상 고르기와 따로 돈다 — 그 고리 안에 있을 때는 20번째 내려받기 대상 뒤 공고에 닿지 못했고(break) 비추천은 아예 빠졌다
    (10-19 「추출기_판_다시_뽑음」 10 · 남은 옛 판 29). 마감 전이면 비추천도 넣는다 · 순서는 회사 방식 목록 그대로 · 상한은 이 고리 안에서만 센다.
    받다 실패한 파일(not_fetched · error)은 다시 뽑지 않는다(내려받기 대상이다)."""
    from app.services import attachment_service
    from app.services import qualification_clause_service as qc

    rebuilt = 0
    for item in items:
        if rebuilt >= limit:
            break
        if item.closed or item.id not in raw:
            continue
        stored = qc.load(item.id)
        if stored is None or stored.get("status") in ("not_fetched", "error"):
            continue
        if int(stored.get("extractor_version") or 0) == qc.EXTRACTOR_VERSION:
            continue
        notice = raw[item.id]
        attachments = list(notice.raw_data.get("attachments") or [])
        index = attachment_service.pick_notice_document(attachments)
        if index is None or attachment_service.cached_attachment(notice.id, index, str(attachments[index].get("name") or "")) is None:
            continue
        payload = qc.build_payload(notice.id, attachments, published_at=getattr(notice, "published_at", None))
        if payload.get("status") not in qc.READ_STATUSES:
            continue  # 다시 뽑다 실패(압축 검사 · 여는 중 오류 …) — 읽은 파일은 그대로 두고 상한에도 세지 않는다(40차 마지막 검토)
        qc.save(payload, private=True)
        rebuilt += 1
    return rebuilt


async def _collect_g2b_documents(limit: int = DAILY_G2B_DOCUMENT_LIMIT) -> dict[str, Any]:
    """마감 전 · 후보 · 조항 파일이 없는(또는 받다 실패한) 나라장터 공고의 **입찰공고문**을 받아 참가자격 조항을 뽑는다 (38차 §3-C-1).

    - 대상은 회사 방식(샘플에듀 = 실무순) 앞에서부터 `limit` 건. 공고당 첨부 하나(입찰공고문)만 받는다.
    - 새 조항 파일은 **Git 밖**(`data/private/qualification_clauses`)에 쓴다 — 매일 받기로 Git 추적 파일(공개 폴더 168)이
      바뀌거나 늘지 않는다. 받은 첨부는 원래대로 `data/public/real_rfp`(Git 밖)다.
    - 고정 모드(`G2B_LIVE_FETCH=0`)이거나 `ATTACHMENT_FETCH=0` 이면 받지 않는다.
    """
    import time

    from app.schemas.organization import AnalysisContext
    from app.services import attachment_service, auto_collect
    from app.services import opportunity_service
    from app.services import qualification_clause_service as qc

    settings = get_settings()
    # 41차 D33 · COLLECT-R40-01 — 하루 최대 20건은 **그날 합계**다(일부 실패 뒤 60분마다 다시 받을 때 20건씩 더 받았다)
    done = auto_collect.done_today(datetime.now(timezone.utc), "나라장터 공고문", "대상")
    limit = max(0, limit - done)
    context = AnalysisContext(organization_id=settings.default_organization_id, evidence_scope="internal")
    listing = await opportunity_service.list_opportunities(context=context, source="g2b", days=DEFAULT_DAYS, limit=None)
    cached = procurement_service.load_cache()
    raw = {view.notice.id: view.notice for view in (cached.notices if cached else [])}
    # 40차 CLAUSE-03 — 다시 뽑기는 내려받기와 따로 먼저(네트워크 0 · 첨부 내려받기가 꺼져 있어도 돈다)
    rebuilt = reextract_stale(list(listing.items), raw)
    if not attachment_service.attachment_fetch_enabled():
        return {"출처": "나라장터 공고문", "결과": None, "건너뜀": "첨부 내려받기가 꺼져 있습니다(ATTACHMENT_FETCH=0).",
                "추출기_판_다시_뽑음": rebuilt}
    todo = []
    no_document = 0
    for item in listing.items:
        if len(todo) >= limit:
            break
        if item.closed or item.relevance_note or item.id not in raw:
            continue
        notice = raw[item.id]
        if notice.notice_no.split("-")[0] in G2B_HOLD_BASE_NOS:
            continue
        if attachment_service.pick_notice_document(list(notice.raw_data.get("attachments") or [])) is None:
            # 첨부에 입찰공고문이 없다 — 하루치 칸을 매일 먼저 차지하지 않게 대상에서 뺀다(38차 검토 · 공고가 바뀌어 붙으면 다시 든다)
            no_document += 1
            continue
        stored = qc.load(item.id)
        if stored is not None and stored.get("status") not in ("not_fetched", "error"):
            continue  # 이미 읽음 — 추출기 판이 달라도 다시 뽑기(`reextract_stale`)가 맡는다
        if stored is not None and stored.get("status") == "error" and int(stored.get("extractor_version") or 0) == qc.EXTRACTOR_VERSION:
            continue  # 43차 M8 — 같은 판으로 이미 열다 실패했다 · 매일 하루치 칸을 다시 쓰지 않는다(판이 바뀌면 다시 시도)
        todo.append(notice)
        if len(todo) >= limit:
            break

    fetched = failed = 0
    status: dict[str, int] = {}
    lines = 0
    for notice in todo:
        attachments = list(notice.raw_data.get("attachments") or [])
        index = attachment_service.pick_notice_document(attachments)
        if index is not None:
            attachment = attachments[index]
            name = str(attachment.get("name") or "")
            if attachment_service.cached_attachment(notice.id, index, name) is None:
                try:
                    await attachment_service.download_attachment(str(attachment["url"]), file_name=name, notice_id=notice.id, index=index)
                    fetched += 1
                except attachment_service.AttachmentError:
                    failed += 1
                time.sleep(G2B_DOCUMENT_DELAY)
        payload = qc.build_payload(notice.id, attachments, published_at=getattr(notice, "published_at", None))
        qc.save(payload, private=True)
        status[payload["status"]] = status.get(payload["status"], 0) + 1
        lines += len(payload.get("clauses") or [])
    return {
        "출처": "나라장터 공고문",
        "결과": "받음" if fetched else "새로 받을 것 없음" if not todo else "받지 못함",
        "새로_받은_건수": fetched,
        "대상": len(todo),
        "실패": failed,
        "공고문_첨부_없음": no_document,
        "추출기_판_다시_뽑음": rebuilt,
        "조항_줄": lines,
        "상태": status,
        "오늘_앞서_받음": done,
    }


async def _collect_ai_fit(now: datetime | None = None) -> dict[str, Any]:
    """AI 적합도 보조(40차 담당자 결정 2 · D24) — `ai_fit_assist` 를 켠 회사마다 규칙이 본업이라 한 **새 공고만** 하루 한 번 묻는다.

    보내는 것은 공고명 · 조달분류 요약 · 기관 · 예산 · 관심 분야 · 판정 정의뿐(`ai_fit_service`). 실패 · 시간 초과 · CLI 없음이어도
    받기는 성공으로 끝난다(이 줄에 이유만 적는다 · 실패는 그날 1회로 세어 다음 날 다시 · CLI 없음은 세지 않음). 판정 · 점수에는 쓰지 않는다.
    """
    from app.schemas.organization import AnalysisContext
    from app.services import ai_fit_service, opportunity_service, organization_service

    current = now or datetime.now(timezone.utc)
    cached = procurement_service.load_cache()
    raw = {view.notice.id: view.notice.raw_data for view in (cached.notices if cached else [])}
    prespecs, _ = prespec_service.load_prespecs()
    pre_raw = {f"{prespec_service.ID_PREFIX}{item.get('bfSpecRgstNo')}": item for item in prespecs or []}
    lines = []
    for org in organization_service.list_organizations(include_inactive=False):
        if not ai_fit_service.enabled(org.organization_id):
            continue
        listing = await opportunity_service.list_opportunities(
            context=AnalysisContext(organization_id=org.organization_id, evidence_scope="internal"),
            source="g2b", days=DEFAULT_DAYS, limit=None, now=current, with_prepare=True,
        )
        lines.append(ai_fit_service.run_daily(org.organization_id, listing, now=current, raw_of=raw.get, pre_raw_of=pre_raw.get))
    if not lines:
        return {"출처": "AI 적합도", "결과": None, "건너뜀": "AI 적합도를 켠 회사가 없습니다(회사 설정 ai_fit_assist)."}
    skipped = next((line["건너뜀"] for line in lines if line.get("건너뜀")), None)
    failed = next((line["실패_이유"] for line in lines if line.get("실패_이유")), None)
    return {
        "출처": "AI 적합도",
        # 41차 AIFIT-07 — 묻지 않은 까닭(「오늘 이미 물음(하루 1회)」 등)을 윗줄 결과에 올린다
        # 11-03 — 로그인 없음 · CLI 없음으로 부르지 못한 날은 「새로 물을 것 없음」이 아니라 「묻지 못함」(이유는 실패_이유)
        "결과": "물음" if any(line.get("호출_수") for line in lines) else (skipped or ("묻지 못함" if failed else "새로 물을 것 없음")),
        "물은_수": sum(int(line.get("물은_수") or 0) for line in lines),
        "아님_수": sum(int(line.get("아님_수") or 0) for line in lines),
        "호출_수": sum(int(line.get("호출_수") or 0) for line in lines),
        "실패_이유": failed,
        "회사": lines,
    }


async def collect(days: int, *, full_window: bool = False, g2b_documents: int = DAILY_G2B_DOCUMENT_LIMIT) -> list[dict[str, Any]]:
    """고정이 아닌 출처를 한 번씩 조회한다. 한쪽이 실패해도 다른 쪽은 마친다.

    **출처마다 따로 본다.** 예전에는 한쪽만 고정이어도 통째로 그만뒀는데, 그러면
    「나라장터만 다시 받고 기업마당은 그대로 둔다」를 할 수 없다. 고정한 쪽을 건드리지
    않는 것이 목적이지 다른 쪽을 막는 것이 목적이 아니다.
    """
    rows: list[dict[str, Any]] = []
    jobs = (
        ("나라장터", procurement_service.live_fetch_enabled(), lambda: _collect_g2b(days, full_window=full_window)),
        ("기업마당", bizinfo_service.live_fetch_enabled(), _collect_bizinfo),
    )
    for name, live, make in jobs:
        if not live:
            rows.append({"출처": name, "결과": None, "건너뜀": "시연 고정 모드 — 저장된 목록을 그대로 둡니다."})
            continue
        try:
            rows.append(await make())
        except Exception as exc:  # noqa: BLE001 — 한쪽 실패가 다른 쪽을 막지 않는다
            rows.append({"출처": name, "결과": None, "오류": f"{exc.__class__.__name__}: {exc}"})

    # 38차 §3-C-1 — 나라장터 목록을 받았으면 마감 전 후보의 **입찰공고문**(참가자격 조항)을 이어서 받는다.
    # 39차 DAILY-06 — 목록을 받지 못했으면 건너뛴다(공고문 단계의 목록 조회가 키워드 수집을 한 번 더 되풀이했다).
    g2b_row = next((r for r in rows if r.get("출처") == "나라장터"), {})
    if procurement_service.live_fetch_enabled() and g2b_documents > 0 and (g2b_row.get("오류") or g2b_row.get("결과") != "g2b"):
        rows.append({"출처": "나라장터 공고문", "결과": None, "건너뜀": "나라장터 목록을 받지 못해 공고문은 건너뜁니다(같은 조회를 되풀이하지 않음)."})
    elif procurement_service.live_fetch_enabled() and g2b_documents > 0:
        try:
            rows.append(await _collect_g2b_documents(g2b_documents))
        except Exception as exc:  # noqa: BLE001 — 공고문을 못 받아도 목록 수집은 이미 끝났다
            rows.append({"출처": "나라장터 공고문", "결과": None, "오류": f"{exc.__class__.__name__}: {exc}"})

    # 38차 §3-D — 사전규격(등록일 7일 창) · 발주계획(이번 달부터 석 달). 같은 인증키 · 나라장터 실호출 문을 따른다.
    # 한 페이지 999행이라 서비스마다 1~3회다(상한 `g2b_client.AO_MAX_PAGES`). 캐시는 입찰공고와 따로(`prespec_service`).
    if procurement_service.live_fetch_enabled():
        for name, make in (("사전규격", prespec_service.collect_prespecs), ("발주계획", prespec_service.collect_order_plans)):
            try:
                rows.append(await make())
            except Exception as exc:  # noqa: BLE001 — 하나가 실패해도 다른 것은 마친다
                rows.append({"출처": name, "결과": None, "오류": f"{exc.__class__.__name__}: {exc}"})

    # 기업마당 목록을 새로 받았으면 **새로 들어온 관련 공고의 공고문**도 이어서 받는다.
    # 목록이 고정이면 새 공고도 없으므로 하지 않는다.
    if bizinfo_service.live_fetch_enabled():
        try:
            rows.append(await _collect_bizinfo_documents())
        except Exception as exc:  # noqa: BLE001 — 공고문을 못 받아도 목록 수집은 이미 끝났다
            rows.append({"출처": "기업마당 공고문", "결과": None, "오류": f"{exc.__class__.__name__}: {exc}"})

    # 40차 D24 — 마지막 단계: AI 적합도 보조(켠 회사만 · 하루 1회). 실패해도 받기는 성공이다 — 이 줄은 「오류」가 아니라 「실패_이유」로 남긴다.
    # 41차 AIFIT-01 — 나라장터 목록을 못 받은 실행은 건너뛴다(그 목록 조회가 키워드 수집을 되풀이하고 그날 1회 몫을 옛 목록에 썼다).
    if procurement_service.live_fetch_enabled() and (g2b_row.get("오류") or g2b_row.get("결과") != "g2b"):
        rows.append({"출처": "AI 적합도", "결과": None, "건너뜀": "나라장터 목록을 받지 못해 AI 적합도는 건너뜁니다(그날 1회 몫을 쓰지 않음)."})
    elif procurement_service.live_fetch_enabled():
        try:
            rows.append(await _collect_ai_fit())
        except Exception as exc:  # noqa: BLE001 — AI 단계가 무엇으로 깨져도 받기 결과를 바꾸지 않는다
            rows.append({"출처": "AI 적합도", "결과": None, "실패_이유": f"{exc.__class__.__name__}: {exc}"[:200]})
    return rows


def plan(days: int, frozen_sources: list[str], *, full_window: bool = False) -> list[str]:
    """`--run` 없이 돌렸을 때 보여 줄 「무엇을 할 예정인가」."""
    how = (
        f"조회 창을 통째로 순회(옛 방식, 호출 {g2b_client.MAX_PAGES}회 안팎)"
        if full_window
        else f"공고명 키워드 {len(collect_keywords_service.all_keywords())}개(기본 + 추가 낱말)로 마감 전 공고를 찾기"
        f"(호출 {g2b_client.MAX_COLLECT_CALLS}회 이내)"
    )
    lines = [
        f"나라장터를 최근 {days}일 기준으로 {how}.",
        "기업마당을 1회 조회하고 캐시를 갱신합니다.",
        f"나라장터 자격(면허 · 지역 제한)을 아직 다 받지 않은 날만 하루 단위로 받습니다"
        f" (호출 최대 {g2b_client.MAX_QUALIFICATION_CALLS}회 · 하루당 4~6회 · 그날 안에 받은 날은 다음에 다시).",
        f"새로 들어온 관련 기업마당 공고의 **공고문**을 최대 {DAILY_DOCUMENT_LIMIT}건 이어서 받습니다"
        " (공고당 1회 · 파일 서버 호출이라 OpenAPI 한도와 무관).",
        f"조항 파일이 없는 마감 전 나라장터 후보의 **입찰공고문**을 회사 방식 순서로 최대 {DAILY_G2B_DOCUMENT_LIMIT}건 받아 참가자격 조항을 뽑습니다"
        f" (공고당 1회 · {G2B_DOCUMENT_DELAY}초 간격 · 조항 파일은 Git 밖 data/private/qualification_clauses).",
        f"나라장터 사전규격(등록일 {prespec_service.PRESPEC_DAYS}일 창) · 발주계획(이번 달부터 {prespec_service.ORDERPLAN_MONTHS}달)을 받아"
        f" 같은 수집 낱말로 거릅니다 (서비스마다 최대 {g2b_client.AO_MAX_PAGES}회 · 한 번에 {g2b_client.AO_ROWS_PER_PAGE}행 ·"
        f" 저장 {_short(prespec_service.PRESPEC_CACHE_FILE)} · {_short(prespec_service.ORDERPLAN_CACHE_FILE)}).",
        "AI 적합도 보조(40차) — 회사 설정 ai_fit_assist 를 켠 회사만 규칙이 본업이라 한 새 공고를 하루 최대 1회 Claude CLI 에 묻습니다"
        " (최대 120건 · 240초 · 공고명 · 조달분류 · 기관 · 예산만 보냄 · 판정 · 점수는 바꾸지 않음 · 실패해도 받기는 성공).",
        "그 밖의 분석 · 요구사항 추출 · 결정 변경은 하지 않습니다.",
        f"덮어쓸 파일: {_short(procurement_service.CACHE_FILE)} (살아 있는 저장본 · Git 밖) · "
        f"기준본 {_short(procurement_service.BASELINE_CACHE_FILE)} 은 그대로",
    ]
    if frozen_sources:
        lines.append(f"지금은 시연 고정 모드입니다({' · '.join(frozen_sources)}) — --run 을 붙여도 받아오지 않습니다.")
    return lines


def row_detail(row: dict[str, Any]) -> str:
    """결과 한 줄의 뒤쪽 글. 공고문 줄은 받은 수를 적는다 — 예전에는 빈 줄이라 예약 작업 기록에서 받았는지 알 수 없었다(33차)."""
    got = row.get("받아온_건수")
    if got is not None:
        detail = f"{row.get('결과')} · 받아옴 {got} · 후보 {row.get('후보_건수')}"
        if row.get("수집_방식"):
            detail = f"{detail} · {row['수집_방식']} · 호출 {row.get('호출_횟수')}회"
        if row.get("자격_새로_받은_날") is not None:
            detail = f"{detail} · 자격 새로 받은 날 {row['자격_새로_받은_날']}일(호출 {row.get('자격_호출') or 0}회)"
        if row.get("자격_사유"):
            detail = f"{detail} · 자격: {row['자격_사유']}"
        return detail
    if row.get("조항_줄") is not None:
        return (
            f"{row.get('결과')} · 대상 {row.get('대상')}건 · 새로 받음 {row['새로_받은_건수']}건 · 실패 {row.get('실패')}"
            f" · 공고문 첨부 없음 {row.get('공고문_첨부_없음')} · 조항 {row['조항_줄']}줄"
        )
    if row.get("새로_받은_건수") is not None:
        return (
            f"{row.get('결과')} · 새로 받음 {row['새로_받은_건수']}건 · 저장소 {row.get('저장소_전체')}건"
            f"(글 {row.get('본문')} · 그림 {row.get('이미지')} · 실패 {row.get('실패')})"
        )
    if row.get("물은_수") is not None:  # 41차 AIFIT-07 — AI 적합도 줄
        detail = f"{row.get('결과')} · 물은 수 {row['물은_수']} · 아님 {row.get('아님_수') or 0} · 호출 {row.get('호출_수') or 0}회"
        return f"{detail} · 실패: {row['실패_이유']}" if row.get("실패_이유") else detail
    return ""


#: 네트워크 확인(40차 D30) — 잠금 해제 직후에는 무선 연결이 아직 없을 수 있다. 짧은 이름 조회로 보고 최대 이만큼 기다린다.
NETWORK_HOST = "apis.data.go.kr"
NETWORK_WAIT_SECONDS = 60
NETWORK_RETRY_SECONDS = 5
#: 네트워크 없음 종료 코드(41차 COLLECT-R40-02 · 지금_받기.bat 이 `if errorlevel 4` 로 본다).
NETWORK_EXIT_CODE = 4


def network_ready(wait: float = NETWORK_WAIT_SECONDS) -> bool:
    """이름 조회(`getaddrinfo`)가 되면 참 — 되지 않으면 `wait` 초까지 5초마다 다시 본다(요청은 보내지 않는다)."""
    import socket
    import time

    deadline = time.monotonic() + wait
    while True:
        try:
            socket.getaddrinfo(NETWORK_HOST, 443)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(NETWORK_RETRY_SECONDS)


def _emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"{SKIP}{payload.get('사유') or payload}")


def main() -> int:
    # 39차 §3-F-4 — pdfminer 경고(「Could not get FontBBox …」 · 공고문 하나에 수십 줄)가 로그의 JSON 줄 사이에 섞였다.
    # 예약 작업 명령(`>> collect_daily.log 2>&1`)은 그대로 두고 그 경고만 끈다 — 오류는 그대로 남는다.
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    parser = argparse.ArgumentParser(description="하루 한 번 공고 목록을 받아 둔다 (기본은 예정만 출력)")
    parser.add_argument("--run", action="store_true", help="실제로 받아온다 (기본은 --dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="무엇을 할 예정인지만 출력한다 (기본값)")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"나라장터 조회 기간(일, 기본 {DEFAULT_DAYS})")
    parser.add_argument("--json", action="store_true", help="결과를 JSON 한 줄로 출력한다 (로그 수집용)")
    parser.add_argument(
        "--g2b-documents",
        type=int,
        default=DAILY_G2B_DOCUMENT_LIMIT,
        help=f"나라장터 입찰공고문을 받을 최대 건수(기본 {DAILY_G2B_DOCUMENT_LIMIT} · 0 이면 받지 않음 · 38차 §3-C-1)",
    )
    parser.add_argument(
        "--full-window",
        action="store_true",
        help="옛 방식(조회 창 순회)으로 받는다. 기본은 공고명 키워드 조회다 (0920 §4-A-1)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="「하루 한 번」 검사를 건너뛰고 받는다 — 지금_받기.bat 이 쓴다(받기 잠금은 그대로 지킨다 · 40차 D30)",
    )
    args = parser.parse_args()

    # **첫 줄에 「내가 바깥을 연다」를 적는다** (prompt_03 §4-A-2).
    # 실호출은 기본이 꺼짐이고, 이 스크립트는 자기 손으로 열었다. 그 사실이 로그의
    # 맨 위에 있어야 나중에 「이 실행이 캐시를 덮었나」를 한 줄로 되짚을 수 있다.
    if not args.json:
        print(
            "실호출: 이 스크립트가 엽니다 — "
            f"G2B_LIVE_FETCH={os.environ.get('G2B_LIVE_FETCH')} · "
            f"BIZINFO_LIVE_FETCH={os.environ.get('BIZINFO_LIVE_FETCH')} "
            "(설정 기본값은 꺼짐 · 셸이 0 으로 고정해 두었으면 그 뜻을 따릅니다)",
        )

    # `--dry-run` 을 함께 준 경우에도 받아오지 않는다. 안전한 쪽이 이긴다.
    dry_run = args.dry_run or not args.run
    frozen, frozen_sources = _frozen()
    started = datetime.now(timezone.utc)

    if dry_run:
        payload = {
            "시각": started.isoformat(),
            "실행": False,
            "예정": plan(args.days, frozen_sources, full_window=args.full_window),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print("하루 한 번 공고 받아 두기 — 예정만 출력합니다 (실제로 받아오려면 --run)")
            for line in payload["예정"]:
                print(f"{SKIP}{line}")
        return 0

    # 두 출처가 **모두** 고정이면 할 일이 없다. 한쪽만 고정이면 그쪽만 건너뛴다.
    if frozen and len(frozen_sources) == 2:
        payload = {
            "시각": started.isoformat(),
            "실행": False,
            "사유": f"시연 고정 모드({' · '.join(frozen_sources)}) — 저장된 목록을 그대로 둡니다.",
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(f"{SKIP}{payload['사유']}")
        return 0

    # 40차 D29 — 받기 잠금(예약 작업 · 지금 받기 둘 다 여기를 지난다). 살아 있는 잠금이 있으면 「이미 받는 중」 한 줄로 끝낸다.
    from app.services import auto_collect

    if not auto_collect.acquire_lock(started):
        held = auto_collect.lock_info(started)
        since = f"{held['started'].astimezone(auto_collect.KST):%H:%M} 시작 · pid {held['pid']}" if held else "잠금 파일을 지우지 못함"
        _emit({"시각": started.isoformat(), "실행": False, "사유": f"이미 받는 중 — {since}"}, args.json)
        # 지금 받기(--force)만 3 — bat 이 「이미 받는 중」으로 알린다. 예약 작업(로그인 · 잠금 해제)은 0(작업 결과가 실패로 보이지 않게).
        return 3 if args.force else 0
    try:
        # 40차 D30 — 「켤 때 받기」: 로그인 · 잠금 해제 · 07:30 마다 불리므로 하루 한 번만 받는다(`--force` 는 건너뜀 · 지금 받기).
        if not args.force:
            go, why = auto_collect.daily_gate(started)
            if not go:
                _emit({"시각": started.isoformat(), "실행": False, "사유": why}, args.json)
                return 0
        if not network_ready():
            _emit({"시각": started.isoformat(), "실행": False,
                   "사유": f"네트워크가 아직 없습니다({NETWORK_WAIT_SECONDS}초 기다림) — 시도로 세지 않고 다음 켤 때 · 잠금 해제 때 다시 받습니다"}, args.json)
            # 41차 COLLECT-R40-02 — 0 이 아니다(지금 받기 bat 이 「다 받았습니다」 대신 「인터넷 연결을 확인하고 다시 누르세요」)
            return NETWORK_EXIT_CODE
        rows = asyncio.run(collect(args.days, full_window=args.full_window, g2b_documents=max(0, args.g2b_documents)))
    finally:
        auto_collect.release_lock()
    failed = [row for row in rows if row.get("오류")]
    for row in failed:
        # 44차 OPS-09 — 아는 실패는 한국어 할 일을 붙인다(원문 「오류」는 그대로) · collect_daily.err 에도 한 줄
        hint = auto_collect.failure_hint(str(row["오류"]))
        if hint:
            row["할_일"] = hint
        print(f"{started.astimezone(auto_collect.KST):%Y-%m-%d %H:%M} {row['출처']} 받기 실패 — {hint or '원인을 모름(원문을 보세요)'} "
              f"(원문: {str(row['오류'])[:300]})", file=sys.stderr)
    payload = {
        "시각": started.isoformat(),
        "실행": True,
        "소요_초": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
        "결과": rows,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"하루 한 번 공고 받아 두기 — {started.astimezone().strftime('%Y-%m-%d %H:%M')}")
        for row in rows:
            if row.get("건너뜀"):
                print(f"{SKIP}{row['출처']}  {row['건너뜀']}")
                continue
            mark = BAD if row.get("오류") else OK
            print(f"{mark}{row['출처']}  {row_detail(row)}")
            if row.get("오류"):
                print(f"          사유: {row['오류']}")
        print("  캐시와 공고 버전 기록만 갱신했습니다. 「오늘 달라진 것」의 「변경된 공고」가 여기서 쌓입니다.")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
