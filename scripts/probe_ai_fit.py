"""AI 적합도 시험 1회 (39차 §3-E · 담당자 결정 3) — **제품에 붙이지 않는다.** 결과는 보고 폴더에만 둔다.

검수자 기준 답안(recheck31 `precision_gold_1017.json` · 167건)을 Claude 에게 「본업 / 인접 / 아님」으로 판정하게 하고,
기준 답안 · 규칙(39차 전 · 뒤)과 견준다. 판정(가능 · 불가) · 순서 · 화면 어디에도 쓰지 않는다.

    python scripts/probe_ai_fit.py --data-dir <고정 저장본 사본> --dry-run      # 보낼 글만 만든다(호출 0)
    python scripts/probe_ai_fit.py --data-dir <고정 저장본 사본>                # Claude CLI 1회

**보내는 것**: 공고마다 공고명 · 조달분류(요약) · 기관 · 예산, 실무 문서 §2.3 관심 분야 1~14, 판정 정의(recheck31 precision.md
「방법과 기준」). 회사자료 · 실적 · 회사 값(인증 · 소재 · 매출 · 등록 업종)은 보내지 않는다.
**부르는 길**: 기존 Claude CLI 경로(`llm_client._complete_via_cli` — 도구 끔 · `--safe-mode` · 빈 임시 폴더 · usage 기록).
한 번 실행 = CLI 한 번(스키마 재요청 · 토큰 겹침 재시도 끔). `llm_usage.jsonl` 이 152줄 이상이면 부르지 않는다(39차 L2 상한).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "docs" / "reports" / "2026-11-05_recheck31" / "precision_gold_1017.json"
FIXTURE = ROOT / "backend" / "tests" / "fixtures" / "precision_gold_1017.json"
OUT = ROOT / "docs" / "reports" / "2026-11-06_round39" / "ai_fit_probe.json"
#: 39차 L2 — usage 150 → 최대 152.
USAGE_CAP = 152

# 40차 §3-D — 보낼 글 · 관심 분야 · 판정 정의는 제품 서비스(`app.services.ai_fit_service`) 한 곳에 있다(탐침도 그것을 쓴다).
# 41차 REGRESS-01 — **앱은 DATA_DIR 을 정한 뒤에만** 들여온다(맨 위에서 들여오면 저장 위치가 저장소 data/ 로 굳어 --report 가 사본 대신
# 살아 있는 저장본을 쟀다). `rules_after` · `main` 이 DATA_DIR 을 세운 뒤 함수 안에서 들여온다.
sys.path.insert(0, str(ROOT / "backend"))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", required=True, help="고정 저장본의 사본(기업마당 분류만 읽는다)")
    parser.add_argument("--dry-run", action="store_true", help="보낼 글만 만든다 — 호출 0")
    parser.add_argument("--report", action="store_true", help="저장한 답으로 비교 보고(.md)만 쓴다 — 호출 0")
    parser.add_argument("--out", default=str(OUT))
    return parser.parse_args()


LABELS = ("core", "adjacent", "not_ours")
LABEL_KO = {"core": "본업", "adjacent": "인접", "not_ours": "아님", "boundary": "경계"}


def rule_label(group: str | None, block: str | None, note: str | None) -> str:
    """규칙의 세 갈래 — 접힘(비추천 · 관련 낮음) → 아님 · 본업 덩어리 → 본업 · 대형 · 연구 · 감리 · 구매 → 인접."""
    if group == "비추천" or note:
        return "not_ours"
    return "core" if (block or "본업") == "본업" else "adjacent"


def rules_after(data_dir: str) -> dict[str, str]:
    """지금 코드(39차)의 규칙 판정 — 고정 저장본 사본 · 10-16 12:00 KST · 마감 · 불가 포함 · 사전규격은 선제준비 칸 넷."""
    import asyncio

    os.environ["DATA_DIR"] = data_dir
    for name in ("LIVE_FETCH", "G2B_LIVE_FETCH", "BIZINFO_LIVE_FETCH", "ATTACHMENT_FETCH", "EMBEDDING_LIVE", "SEMANTIC_FIT", "LLM_LIVE"):
        os.environ[name] = "0"
    from app.schemas.organization import AnalysisContext
    from app.services import opportunity_service

    now = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)
    listing = asyncio.run(opportunity_service.list_opportunities(
        context=AnalysisContext(organization_id="org-sample", evidence_scope="internal"), source="all", days=30,
        include_closed=True, include_blocked=True, now=now, with_prepare=True,
    ))
    section = listing.prepare
    pre = [*section.items, *section.others, *section.opinion_passed, *section.merged] if section else []
    return {i.id: rule_label(i.practical_group, i.practical_block, i.relevance_note) for i in [*listing.items, *pre]}


def _confusion(pairs: list[tuple[str, str]], title: str) -> list[str]:
    golds = [g for g in ("core", "adjacent", "not_ours", "boundary") if any(p[0] == g for p in pairs)]
    lines = [f"**{title}** — 줄 = 기준 답안 · 칸 = 판정", "", "| 기준 답안 \\ 판정 | 본업 | 인접 | 아님 | 합 |", "| --- | --- | --- | --- | --- |"]
    for gold in golds:
        row = [sum(1 for g, p in pairs if g == gold and p == label) for label in LABELS]
        lines.append(f"| {LABEL_KO[gold]} | {' | '.join(map(str, row))} | {sum(row)} |")
    agree = sum(1 for g, p in pairs if g == p)
    labeled = sum(1 for g, _ in pairs if g in LABELS)
    core_hit = sum(1 for g, p in pairs if g == "core" and p == "core")
    core_total = sum(1 for g, _ in pairs if g == "core")
    not_kept = sum(1 for g, p in pairs if g == "not_ours" and p == "core")
    lines += ["", f"일치 {agree}/{labeled}({agree / labeled:.0%}) · 본업을 본업으로 {core_hit}/{core_total} · 「아님」을 본업으로 둔 것 {not_kept}건", ""]
    return lines


def write_report(data_dir: str, out: Path) -> Path:
    saved = json.loads(out.read_text(encoding="utf-8"))
    gold = {r["id"]: r for r in json.loads(GOLD.read_text(encoding="utf-8"))["items"]}
    after = rules_after(data_dir)
    rows = saved["rows"]
    ai = saved["ai"]
    table = []
    for r in rows:
        g = gold[r["id"]]
        r63 = g.get("rules63") or {}
        before = rule_label(r63.get("practical_group"), r63.get("practical_block"), r63.get("relevance_note")) if r63 else None
        table.append({**r, "ai": (ai.get(str(r["n"])) or {}).get("label"), "ai_reason": (ai.get(str(r["n"])) or {}).get("reason", ""),
                      "before": before, "after": after.get(r["id"]), "gold_reason": g.get("reason", "")})
    usage = saved.get("usage_line") or (saved.get("previous_ok") or {}).get("usage_line") or {}
    L = [
        "# 39차 §3-E AI 적합도 시험 1회 — Claude vs 기준 답안 vs 규칙",
        "",
        "**제품에 붙이지 않았다**(담당자 결정 3) — 이 결과는 어떤 판정 · 순서 · 화면에도 쓰지 않는다. 붙일지는 담당자가 정한다(보고 (7)).",
        "",
        f"- 기준 답안: recheck31 `precision_gold_1017.json` {len(rows)}건(검수자가 공고명 · 조달분류 · 기관 · 예산만 보고 판정 · 고치지 않음 — D21).",
        "- 보낸 것: 공고마다 공고명 · 조달분류(대 > 중 > 세분류 · 사전규격은 업무 구분 · 기업마당은 지원 분야) · 기관 · 예산, 실무 문서 §2.3 관심 분야 1~14, "
        "판정 정의(precision.md 「방법과 기준」). 회사자료 · 실적 · 회사 값은 보내지 않았다. 보낸 글 "
        f"{saved.get('sent_chars')}자(연락처 꼴 0).",
        f"- 부른 길: Claude Code CLI(이 PC 로그인 · `--safe-mode` · 도구 끔 · 빈 임시 폴더) **1회** · 모델 {saved.get('model')} · "
        f"걸린 시간 {saved.get('seconds')}초 · usage {saved.get('usage_before')} → {saved.get('usage_after')} · "
        f"토큰 입력 {usage.get('prompt_tokens', '-')} · 출력 {usage.get('completion_tokens', '-')} · "
        f"API 정가 환산 ${usage.get('api_equivalent_usd', '-')}(구독이라 따로 청구되지 않음).",
        "- 규칙 판정의 세 갈래: 접힘(비추천 · 관련 낮음) → 아님 · 살아 있는 본업 덩어리 → 본업 · 대형 · 파트너형 / 연구 · 감리 · 구매 → 인접. "
        "「전」 = 38차 후속 규칙 판 63(검수자가 기준 답안에 같이 적은 값) · 「뒤」 = 39차(§3-A · §3-B · 결정 1 — 고정 저장본 사본 · 10-16 12:00).",
        "",
        "## 혼동표",
        "",
    ]
    L += _confusion([(t["label"], t["ai"]) for t in table if t["ai"]], f"Claude(AI) — 답 {sum(1 for t in table if t['ai'])}건")
    L += _confusion([(t["label"], t["before"]) for t in table if t["before"]], "규칙 전(판 63)")
    L += _confusion([(t["label"], t["after"]) for t in table if t["after"]], "규칙 뒤(39차)")
    split = [t for t in table if len({t["label"], t["ai"], t["after"]} - {None}) > 1]
    L += [
        "## 셋이 갈리는 공고",
        "",
        f"기준 답안 · AI · 규칙(뒤) 중 하나라도 다른 것 {len(split)}건. 「검수자 판정 다시 보기」 후보는 AI 와 규칙(뒤)이 같고 기준 답안만 다른 줄이다(보고 (7)).",
        "",
        "| # | 구역 | 공고 | 기준 답안 | AI | 규칙 전 → 뒤 | AI 한 줄 이유 | 기준 답안 이유 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for t in split:
        mark = " ★" if t["ai"] == t["after"] and t["ai"] != t["label"] else ""
        L.append(
            f"| {t['n']} | {t['section']} | {t['title'][:46].replace('|', '/')} | {LABEL_KO.get(t['label'], t['label'])}{mark} | "
            f"{LABEL_KO.get(t['ai'] or '', '-')} | {LABEL_KO.get(t['before'] or '', '-')} → {LABEL_KO.get(t['after'] or '', '-')} | "
            f"{(t['ai_reason'] or '').replace('|', '/')[:50]} | {(t['gold_reason'] or '').replace('|', '/')[:40]} |"
        )
    L += ["", "★ = AI 와 규칙(뒤)이 같고 기준 답안만 다름 — 검수자 판정 다시 보기 후보(기준 답안은 고치지 않았다 · D21).", ""]
    md = out.with_suffix(".md")
    md.write_text("\n".join(L) + "\n", encoding="utf-8")
    return md


def _eok(value) -> str:
    from app.services.ai_fit_service import eok

    return eok(int(value) if value else None)


def _klass(row: dict, fixture: dict, bizinfo: dict) -> str:
    """조달분류 요약 — 나라장터 대 > 중 > 세분류 · 사전규격 업무 구분 · 기업마당 지원 분야(대 > 중)."""
    fx = fixture.get(row["id"]) or {}
    record = fx.get("cache_record")
    if record:
        item = (record.get("notice", {}).get("raw_data") or {}).get("item") or {}
        parts = [item.get(k) for k in ("pubPrcrmntLrgClsfcNm", "pubPrcrmntMidClsfcNm", "pubPrcrmntClsfcNm")]
        return " > ".join(p for p in parts if p) or "분류 없음"
    if fx.get("prespec_item"):
        return f"사전규격 · {fx['prespec_item'].get('bsnsDivNm') or '용역'}"
    raw = bizinfo.get(row["id"].removeprefix("bizinfo-"))
    if raw:
        parts = [raw.get("pldirSportRealmLclasCodeNm"), raw.get("pldirSportRealmMlsfcCodeNm")]
        return "기업마당 지원사업 · " + " > ".join(p for p in parts if p)
    return "분류 없음"


def build_rows(data_dir: str) -> list[dict]:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))["items"]
    fixture = {r["id"]: r for r in json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]}
    try:
        cache = json.loads((Path(data_dir) / "private" / "cache" / "bizinfo" / "bizinfo_cache.json").read_text(encoding="utf-8"))
        bizinfo = {str(i.get("pblancId")): i for i in cache.get("items") or []}
    except (OSError, ValueError):
        bizinfo = {}
    rows = []
    for n, row in enumerate(gold, start=1):
        rows.append({
            "n": n, "id": row["id"], "label": row["label"], "section": row["section"], "title": row["title"],
            "agency": row.get("agency") or "기관 미상", "budget": row.get("budget"), "klass": _klass(row, fixture, bizinfo),
        })
    return rows


def user_text(rows: list[dict]) -> str:
    from app.services.ai_fit_service import sent_body
    from app.services.ai_fit_service import user_text as service_text

    return service_text([sent_body(r["title"], r["klass"], r["agency"], int(r["budget"]) if r["budget"] else None) for r in rows])


def _usage_lines(path: Path) -> int:
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def main() -> int:
    args = _arguments()
    os.environ["DATA_DIR"] = str(Path(__file__).resolve().parents[1] / "data")  # usage 는 살아 있는 기록에 남긴다(앱과 같은 곳)
    os.environ["PLAN_WRITER_CLI"] = "1"
    sys.path.insert(0, str(ROOT / "backend"))
    if args.report:
        print(write_report(args.data_dir, Path(args.out)))
        return 0
    rows = build_rows(args.data_dir)
    text = user_text(rows)
    # 보내는 글 검사 — 연락처 · 회사 값 꼴이 섞이지 않았나(회사자료는 애초에 읽지 않는다)
    leaks = re.findall(r"\d{2,3}-\d{3,4}-\d{4}|[\w.]+@[\w.]+", text)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if leaks:
        print("보내는 글에 연락처 꼴이 있습니다 — 멈춤:", leaks[:3])
        return 2
    from app.services.ai_fit_service import SYSTEM

    if args.dry_run:
        print(SYSTEM)
        print(text[:2000])
        print(f"\n(공고 {len(rows)}건 · 본문 {len(text)}자 · 호출 0)")
        return 0

    from pydantic import BaseModel, Field

    from app.services import llm_client

    class Item(BaseModel):
        n: int
        label: str = Field(pattern="^(core|adjacent|not_ours)$")
        reason: str

    class Answer(BaseModel):
        items: list[Item]

    before = _usage_lines(llm_client.USAGE_LOG)
    if before >= USAGE_CAP:
        print(f"usage {before}줄 — 상한 {USAGE_CAP} 에 닿아 부르지 않습니다(39차 L2).")
        return 3
    ready, reason = llm_client.plan_writer_ready("claude")
    if not ready:
        print("Claude CLI 를 쓸 수 없습니다 —", reason)
        return 4
    llm_client.MAX_ATTEMPTS = 1  # 한 번 실행 = CLI 한 번(스키마 재요청 없음)
    llm_client._TOKEN_RACE_RE = re.compile(r"(?!x)x")  # 토큰 겹침 재시도도 끔
    target = llm_client._CompletionTarget("claude_cli", llm_client.plan_writer_model(), None)
    started = time.monotonic()
    error = None
    answer = None
    try:
        answer = llm_client._complete_via_cli(
            system=SYSTEM, user=text, schema=Answer, json_schema=llm_client._response_schema(Answer, "claude_cli"),
            target=target, purpose="probe_ai_fit:39차", timeout=900,
        )
    except (llm_client.LLMUnavailableError, llm_client.LLMValidationError) as exc:
        error = str(exc)
    seconds = round(time.monotonic() - started, 1)
    after = _usage_lines(llm_client.USAGE_LOG)
    last = None
    try:
        last = json.loads(llm_client.USAGE_LOG.read_text(encoding="utf-8").splitlines()[-1])
    except (OSError, ValueError, IndexError):
        pass
    result = {
        "at": datetime.now(timezone.utc).isoformat(),
        "model": target.model,
        "seconds": seconds,
        "usage_before": before,
        "usage_after": after,
        "usage_line": last if after > before else None,
        "error": error,
        "sent_chars": len(text),
        "rows": rows,
        "ai": {str(i.n): {"label": i.label, "reason": i.reason} for i in answer.items} if answer else {},
    }
    previous = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    if previous and previous.get("ai") and not result["ai"]:
        result["previous_ok"] = {k: previous[k] for k in ("at", "seconds", "usage_line") if k in previous}
        result["ai"] = previous["ai"]  # 앞 실행이 성공했으면 그 답을 지키고 이번 실패만 적는다
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{'실패: ' + error if error else '성공'} · {seconds}초 · usage {before} → {after} · 답 {len(result['ai'])}/{len(rows)} · {out}")
    return 0 if answer else 1


if __name__ == "__main__":
    raise SystemExit(main())
