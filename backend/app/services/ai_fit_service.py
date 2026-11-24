"""AI 적합도 보조 (40차 담당자 결정 2 · D24) — 매일 받기 때 **규칙이 본업이라 한 새 공고만** 하루 한 번 묶어 Claude 에 묻는다.

- **보내는 것(허용 목록 · `sent_line` · `SYSTEM`)**: 공고마다 공고명 · 조달분류 요약 · 기관 · 예산, 실무 문서 §2.3 관심 분야 1~14,
  판정 정의(recheck31 precision.md 「방법과 기준」 — 회사 이름 「샘플에듀」과 단독 상한 「2억」 숫자가 든 정의 글이다 · 41차 문서 바로잡음).
  **회사 값 · 회사자료 · 실적은 보내지 않는다**(시험이 막는다 — 회사 값을 채운 시험 회사로도).
- **언제 · 얼마나**: `collect_daily` 끝에 회사마다(`ai_fit_assist` 를 켠 곳만) **하루 최대 1회** CLI 호출 · 한 번에 최대 120건
  (넘으면 마감 가까운 것부터 · 나머지는 다음 날) · 시간 상한 240초. 처음 보는 것만 묻는다(열쇠 = 공고 id + 보낸 글 해시 + 프롬프트 판).
- **쓰는 곳**: AI 「아님」만 — 꼬리표 「AI: 본업 아닐 수 있음 · <이유>」 + 「주제 확인」과 같은 자리(`practical_priority.topic_rank`).
  AI 「본업 · 인접」은 아무것도 바꾸지 않는다. 판정 · 점수 · 「가능」 · 비추천 접기 · 기업마당에는 쓰지 않는다. 화면 「AI 판단 — 참고용」.
- **실패 · 시간 초과** → 규칙만(받기는 성공으로 끝남 · 로그에 이유) · 실패한 호출도 그날 1회로 세어 **다음 날** 받기에서 다시.
  **CLI 없음**은 부르지 않았으니 세지 않는다(41차 AIFIT-07 — 같은 날 로그인 뒤 지금 받기에서 다시 묻는다).
- **나라장터 목록을 못 받은 실행은 이 단계를 건너뛴다**(41차 AIFIT-01 · `collect_daily`).
- 저장: Git 밖 `data/private/organizations/<org>/ai_fit.json`(원자적 쓰기) · usage 는 기존 기록(`llm_usage.jsonl`) 그대로.

39차 `scripts/probe_ai_fit.py` 의 보낼 글 · 정의 · 관심 분야를 여기로 옮겼다 — 탐침도 이 함수들을 쓴다.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from pydantic import BaseModel, Field

from app.core import org_storage, storage
from app.schemas.business_opportunity import UnifiedOpportunity
from app.services import practical_priority as practical

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
#: 보낸 글 · 정의가 바뀌면 올린다 — 열쇠에 들어가 같은 공고를 새 판으로 다시 묻는다.
PROMPT_VERSION = 1
#: 한 번에 묻는 공고 수 상한 · 시간 상한 · 하루 호출 상한(D24).
MAX_ITEMS = 120
TIME_LIMIT_SECONDS = 240
DAILY_CALL_LIMIT = 1
AI_FIT_FILE = "ai_fit.json"
NOTE_PREFIX = "AI: 본업 아닐 수 있음"
#: 화면 · 브리핑 · 엑셀의 풀이 한 줄.
REFERENCE_NOTE = "AI 판단 — 참고용"

#: 실무 문서(신규공고_서칭_완전이관_20260918_v1.md) §2.3 관심 분야 — 순서가 우선순위다. 회사 값이 아니라 관심 분야 글이다.
INTERESTS: tuple[str, ...] = (
    "직업훈련", "교육훈련", "AI·디지털 인력양성", "재직자·청년·대학생 AI 교육", "대학 비교과", "생성형 AI/AI Agent 교육",
    "AI 직무·역량체계", "교육과정·콘텐츠 개발", "초중등 AI·SW·STEAM", "기업 AX 진단 + 교육", "RAG·업무자동화·AI Agent PoC",
    "AI 솔루션 실증", "AI R&D 컨소시엄", "대형 SI·순수 연구는 후순위",
)

#: 판정 정의 — recheck31 precision.md 「방법과 기준」 그대로(검수자가 기준 답안을 만든 정의).
DEFINITIONS = """\
- core(본업): 위 관심 분야 1~11 과 회사 사업영역(AI 활용 · 생성형 AI · 업무자동화 · 디지털 역량 교육, AI · ESG 컨설팅) 안에 드는 일.
  AI·디지털·데이터·ESG 교육운영과 인력양성, 디지털 주제 강사섭외형 위탁교육, 교육과정·이러닝 콘텐츠 개발(주제 무관 · 관심 분야 8),
  AX·AI·ESG 컨설팅, 2억 안팎의 AI 에이전트·RAG·챗봇 개발.
- adjacent(인접): 일의 종류는 맞다. 다만 원격교육 콘텐츠 라이브러리나 전문 주제 파트너가 필요하거나, 2억의 2배(4억)를 넘는 AI 일.
- not_ours(샘플에듀 일 아님): IT 운영·유지보수 SI, AI 가 아닌 웹·시스템 구축, 시설·장비·공간, 여행·견학·행사 대행, 어학,
  산림·생태 체험교육, 농촌 지역역량강화, ODA PMC, 의료·인허가."""

SYSTEM = (
    "너는 공공조달 공고를 분류하는 검토자다. 각 공고의 공고명 · 조달분류 · 기관 · 예산만 보고 한 회사(AI 교육 · AI 컨설팅 회사)의 "
    "「본업(core) / 인접(adjacent) / 아님(not_ours)」 중 하나를 고른다. 공고문은 볼 수 없다. 모르는 것을 지어내지 말고, 이유는 한 줄(40자 안팎)로 쓴다.\n\n"
    "관심 분야(순서가 우선순위):\n" + "\n".join(f"{n}. {t}" for n, t in enumerate(INTERESTS, start=1)) +
    "\n\n판정 정의:\n" + DEFINITIONS +
    "\n\n출력은 스키마 그대로: items 에 입력의 n 마다 하나씩(빠짐 · 중복 없이)."
)

#: 보낼 글에 이런 꼴이 섞이면 묻지 않는다(연락처 · 메일 — 공고명에 섞여 들어온 것).
_LEAK_RE = re.compile(r"\d{2,3}-\d{3,4}-\d{4}|[\w.]+@[\w.]+")


class AiFitItem(BaseModel):
    n: int
    label: str = Field(pattern="^(core|adjacent|not_ours)$")
    reason: str


class AiFitAnswer(BaseModel):
    items: list[AiFitItem]


# --------------------------------------------------------------------------
# 보낼 글 (허용 목록)
# --------------------------------------------------------------------------


def eok(value: int | None) -> str:
    return f"{value / 100_000_000:.2f}억" if value else "미공개"


def klass_summary(raw: dict | None, *, pre_spec: bool = False, pre_raw: dict | None = None) -> str:
    """조달분류 요약 — 나라장터 대 > 중 > 세분류 · 사전규격은 업무 구분. 없으면 「분류 없음」."""
    if pre_spec:
        return f"사전규격 · {(pre_raw or {}).get('bsnsDivNm') or '용역'}"
    item = (raw or {}).get("item") if isinstance(raw, dict) else None
    parts = [(item or {}).get(k) for k in ("pubPrcrmntLrgClsfcNm", "pubPrcrmntMidClsfcNm", "pubPrcrmntClsfcNm")]
    return " > ".join(str(p) for p in parts if p) or "분류 없음"


def sent_body(title: str, klass: str, agency: str, budget: int | None) -> str:
    """한 공고의 보낼 글(번호 뺀) — **공고명 · 조달분류 요약 · 기관 · 예산만**(D24 허용 목록). 이 글의 해시가 열쇠다."""
    return f"{title} | 분류: {klass} | 기관: {agency or '기관 미상'} | 예산: {eok(budget)}"


def sent_line(n: int, body: str) -> str:
    return f"{n}. {body}"


def user_text(bodies: Sequence[str]) -> str:
    return f"공고 {len(bodies)}건:\n" + "\n".join(sent_line(n, b) for n, b in enumerate(bodies, start=1))


def body_hash(body: str) -> str:
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------
# 저장 (Git 밖 · 회사마다)
# --------------------------------------------------------------------------


def store_path(organization_id: str) -> Path:
    return org_storage.storage_for(organization_id).root / AI_FIT_FILE


#: 41차 REGRESS-06 · AIFIT-09 — 목록 요청 한 번에 입찰 · 선제준비 두 번 읽었다 — 파일 크기 · 고친 시각이 같으면 읽은 것을 다시 쓴다.
_LOAD_MEMO: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
#: 답은 이 날수가 지나고 이번 묻기 대상에도 없으면 지운다(AIFIT-09 — 닫힌 공고의 답이 끝없이 쌓였다).
ENTRY_KEEP_DAYS = 60


def load(organization_id: str) -> dict[str, Any]:
    """저장한 답 · 실행 기록 — **고쳐 쓰지 않는다**(읽은 것을 메모로 다시 쓰므로 바꿀 때는 `load_for_update`)."""
    path = store_path(organization_id)
    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    memo = _LOAD_MEMO.get(str(path))
    if stamp is not None and memo is not None and memo[0] == stamp:
        return memo[1]
    payload = load_for_update(organization_id)
    if stamp is not None:
        _LOAD_MEMO[str(path)] = (stamp, payload)
    return payload


def load_for_update(organization_id: str) -> dict[str, Any]:
    try:
        payload = storage.read_json(store_path(organization_id), default=None)
    except storage.CorruptJsonError:
        payload = None
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("entries", {})
    payload.setdefault("runs", [])
    return payload


def _save(organization_id: str, payload: dict[str, Any], *, keep_ids: Iterable[str] = (), now: datetime | None = None) -> None:
    payload["runs"] = payload.get("runs", [])[-60:]  # 실행 기록은 최근 60번만
    if now is not None:
        keep = set(keep_ids)
        cutoff = (now - timedelta(days=ENTRY_KEEP_DAYS)).isoformat()
        payload["entries"] = {k: v for k, v in payload.get("entries", {}).items() if k in keep or str(v.get("at") or "") >= cutoff}
    storage.write_json_atomic(store_path(organization_id), payload)


def enabled(organization_id: str) -> bool:
    """회사 설정 `ai_fit_assist`(기본 꺼짐 · 담당자 결정 2 로 샘플에듀 만 켬)."""
    from app.services import delivery_capacity_service

    return bool(getattr(delivery_capacity_service.load(organization_id), "ai_fit_assist", False))


# --------------------------------------------------------------------------
# 대상 고르기 · 목록에 쓰기
# --------------------------------------------------------------------------


def targets(listing) -> list[UnifiedOpportunity]:
    """규칙이 본업이라 한 나라장터 입찰(본업 덩어리 · 살아 있는 것) · 사전규격(선제준비 「보임」) — 마감 가까운 순."""
    bids = [
        i for i in listing.items
        if i.source_type == "g2b" and i.opportunity_type == "procurement"
        and (i.practical_block or practical.BLOCK_CORE) == practical.BLOCK_CORE and i.practical_group not in ("제외", "비추천")
    ]
    pre = list(listing.prepare.items) if getattr(listing, "prepare", None) else []

    def due(item: UnifiedOpportunity) -> float:
        moment = item.opinion_deadline if item.opportunity_type == "pre_spec" else practical.effective_deadline(item)
        return moment.timestamp() if moment else float("inf")

    return sorted([*bids, *pre], key=lambda i: (due(i), i.id))


def bodies_for(items: Iterable[UnifiedOpportunity], *, raw_of: Callable[[str], dict | None],
               pre_raw_of: Callable[[str], dict | None]) -> dict[str, str]:
    """공고 id → 보낼 글(번호 뺀). 조달분류는 원자료에서(나라장터 `raw_data.item` · 사전규격 `bsnsDivNm`)."""
    out: dict[str, str] = {}
    for item in items:
        pre = item.opportunity_type == "pre_spec"
        klass = klass_summary(raw_of(item.id), pre_spec=pre, pre_raw=pre_raw_of(item.id) if pre else None)
        out[item.id] = sent_body(item.title, klass, item.agency, item.budget)
    return out


def fresh(bodies: dict[str, str], store: dict[str, Any]) -> list[str]:
    """처음 보는 공고 id — 저장한 답이 없거나 보낸 글 · 프롬프트 판이 바뀐 것."""
    entries = store.get("entries", {})
    return [
        i for i, body in bodies.items()
        if not (e := entries.get(i)) or e.get("hash") != body_hash(body) or e.get("prompt_version") != PROMPT_VERSION
    ]


def note_of(entry: dict | None) -> str | None:
    """저장한 답 → 꼬리표. AI 「아님」만(본업 · 인접은 아무것도 바꾸지 않는다)."""
    if not entry or entry.get("label") != "not_ours":
        return None
    reason = " ".join(str(entry.get("reason") or "").split())[:60]
    return f"{NOTE_PREFIX} · {reason}" if reason else NOTE_PREFIX


def apply_notes(items: Sequence[UnifiedOpportunity], organization_id: str) -> int:
    """목록에 AI 꼬리표를 단다 — 설정을 켠 회사 · 본업 덩어리 · 답을 받을 때와 공고명이 같을 때만. 판정 · 점수는 그대로.

    목록 항목에는 조달분류 원문이 없어 보낸 글 해시를 다시 잴 수 없다 — 공고명이 같으면 그 답을 쓰고, 기관 · 예산 · 분류가 바뀐 드문 경우는
    다음 묻기(`fresh` — 해시가 다르면 다시 묻는다)가 답을 새로 받는다(40차 마지막 검토 — 설명을 코드와 맞춤)."""
    if not enabled(organization_id):
        return 0
    entries = load(organization_id).get("entries", {})
    count = 0
    for item in items:
        entry = entries.get(item.id)
        if entry is None or (item.practical_block or practical.BLOCK_CORE) != practical.BLOCK_CORE or item.source_type != "g2b":
            continue
        if entry.get("prompt_version") != PROMPT_VERSION or entry.get("title") != item.title:
            continue
        note = note_of(entry)
        if note:
            item.ai_fit_note = note
            count += 1
    return count


# --------------------------------------------------------------------------
# 묻기 (CLI 한 번)
# --------------------------------------------------------------------------


def ask_cli(bodies: Sequence[str], *, timeout: float = TIME_LIMIT_SECONDS, purpose: str = "ai_fit:40차") -> dict[int, AiFitItem]:
    """Claude CLI **한 번**(스키마 재요청 · 토큰 겹침 재시도 없음) — 기존 경로(`llm_client._complete_via_cli` · `--safe-mode` · 도구 끔 ·
    빈 임시 폴더 · usage 기록). 못 부르면 `LLMUnavailableError` · 검증 실패면 `LLMValidationError`."""
    from app.services import llm_client

    if llm_client.claude_cli_path() is None:
        raise llm_client.LLMUnavailableError(llm_client.PLAN_WRITER_NO_CLI_REASON)
    # 42차 — 로그인 전이면 부르지 않는다(회사 서버 설치 직후 · 못 읽으면 그대로 부른다)
    if llm_client.claude_cli_auth_status().get("loggedIn") is False:
        raise llm_client.LLMUnavailableError(llm_client.CLAUDE_NOT_LOGGED_IN_REASON)
    target = llm_client._CompletionTarget("claude_cli", model_name(), None)
    answer = llm_client._complete_via_cli(
        system=SYSTEM, user=user_text(bodies), schema=AiFitAnswer,
        json_schema=llm_client._response_schema(AiFitAnswer, "claude_cli"),
        target=target, purpose=purpose, timeout=timeout, attempts=1, retry_token_race=False,
        # 41차 AIFIT-02 — 시도 한 번의 상한도 240초(설정 `LLM_TIMEOUT_SECONDS` 기본 180 이 먼저 끊었다)
        attempt_cap=timeout,
    )
    return {item.n: item for item in answer.items if 1 <= item.n <= len(bodies)}


def model_name() -> str | None:
    """묻는 모델 이름(41차 AIFIT-08 — 답 · 실행 기록에 함께 적는다 · CLI 기본이면 None)."""
    from app.services import llm_client

    return llm_client.plan_writer_model("claude")


def run_daily(organization_id: str, listing, *, now: datetime, raw_of: Callable[[str], dict | None],
              pre_raw_of: Callable[[str], dict | None], ask: Callable[..., dict[int, AiFitItem]] = ask_cli) -> dict[str, Any]:
    """매일 받기 끝 한 단계(D24) — 켠 회사만 · 하루 최대 1회 · 처음 보는 것만 · 120건 · 240초. 로그 한 줄(dict)을 돌려준다.

    실패해도 예외를 밖으로 내지 않는다 — 받기는 성공으로 끝나고 다음 날 다시 묻는다(CLI 없음은 세지 않아 같은 날 다시 · 41차 AIFIT-07)."""
    line: dict[str, Any] = {"회사": organization_id, "물은_수": 0, "아님_수": 0, "호출_수": 0, "실패_이유": None}
    if not enabled(organization_id):
        return {**line, "건너뜀": "AI 적합도 꺼짐(회사 설정)"}
    store = load_for_update(organization_id)
    today = now.astimezone(KST).date().isoformat()
    if sum(int(r.get("calls") or 0) for r in store["runs"] if r.get("day") == today) >= DAILY_CALL_LIMIT:
        return {**line, "건너뜀": "오늘 이미 물음(하루 1회)"}
    pool = targets(listing)
    bodies = bodies_for(pool, raw_of=raw_of, pre_raw_of=pre_raw_of)
    todo = fresh(bodies, store)[:MAX_ITEMS]  # 마감 가까운 순 그대로 · 나머지는 다음 날
    if not todo:
        return {**line, "건너뜀": "새로 물을 공고 없음"}
    # 40차 마지막 검토 — 연락처 꼴이 섞인 공고는 **그 공고만** 빼고 묻는다(한 건 때문에 날마다 단계 전체가 건너뛰어졌다)
    leaked = [i for i in todo if _LEAK_RE.search(bodies[i])]
    todo = [i for i in todo if i not in leaked]
    if not todo:
        return {**line, "건너뜀": f"보낼 글에 연락처 꼴이 있어 묻지 않음({len(leaked)}건)"}
    sent = [bodies[i] for i in todo]
    if _LEAK_RE.search(user_text(sent)):
        return {**line, "건너뜀": "보낼 글에 연락처 꼴이 있어 묻지 않음"}
    started = time.monotonic()
    model = model_name()
    run: dict[str, Any] = {"day": today, "at": now.isoformat(), "asked": len(todo), "calls": 1, "not_ours": 0, "error": None,
                           "model": model}
    try:
        answers = ask(sent, timeout=TIME_LIMIT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 규칙만 쓰고 받기는 성공으로 끝낸다(D24)
        from app.services import llm_client

        run["error"] = f"{type(exc).__name__}: {exc}"[:200]
        # 41차 AIFIT-07 — CLI 를 찾지 못했으면 부르지 않았다(호출 0 · 그날 1회 몫을 쓰지 않음) · 42차 로그인 전도 같다
        no_cli = isinstance(exc, llm_client.LLMUnavailableError) and str(exc) in (
            llm_client.PLAN_WRITER_NO_CLI_REASON, llm_client.CLAUDE_NOT_LOGGED_IN_REASON)
        run["calls"] = 0 if no_cli else 1
        store["runs"].append(run)
        _save(organization_id, store)
        logger.warning("AI 적합도 실패 — 규칙만 씁니다: %s", run["error"])
        return {**line, "물은_수": 0 if no_cli else len(todo), "호출_수": run["calls"], "실패_이유": run["error"]}
    by_id = {item.id: item for item in pool}
    for n, item_id in enumerate(todo, start=1):
        got = answers.get(n)
        if got is None:
            continue
        store["entries"][item_id] = {
            "label": got.label, "reason": " ".join(got.reason.split())[:80], "hash": body_hash(bodies[item_id]),
            "title": by_id[item_id].title, "prompt_version": PROMPT_VERSION, "at": now.isoformat(), "model": model,
        }
        run["not_ours"] += int(got.label == "not_ours")
    run["seconds"] = round(time.monotonic() - started, 1)
    run["answered"] = len(answers)
    store["runs"].append(run)
    _save(organization_id, store, keep_ids=bodies, now=now)
    return {**line, "물은_수": len(todo), "답한_수": len(answers), "아님_수": run["not_ours"], "호출_수": 1, "초": run["seconds"]}
