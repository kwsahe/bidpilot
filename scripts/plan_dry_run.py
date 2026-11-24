#!/usr/bin/env python
"""사업계획서 초안 공개 자료 시험 한 벌 — 126482 공고 발췌 + 가상 회사 + 고른 과제 (26차 · prompt_16 §4-J).

회사 자료(`data/private/organizations`)는 **읽지 않는다.** 입력은 테스트 파일의 공개 발췌 상수뿐이다
(`tests.test_plan_form.FULL` — 126482 공고문 원문 발췌 · `tests.test_plan_draft.COMPANY/FACTS` — 가상 회사).
초안은 **저장하지 않는다**(`plan_draft_service.generate` 만 부른다). 요약 표만 쓴다 — 초안 원문은 커밋하지 않는다.

AI 를 부른다(한 벌 = 논리 호출 최대 절 수 + 2 = 10). 누계(`data/private/llm_usage.jsonl`)에 호출마다 한 줄이 남는다.

    backend\\.venv\\Scripts\\python.exe scripts\\plan_dry_run.py --summary docs\\reports\\2026-10-12_plan_dry_run.md
    backend\\.venv\\Scripts\\python.exe scripts\\plan_dry_run.py --provider claude_cli --task 4 --draft-out <저장소 밖 경로>.json

공급자는 셸 · `.env` 대신 `--provider` 로 정한다(기본 claude_cli). 나라장터 · 기업마당 · 임베딩은 끈다.
`--provider codex_cli` 는 사업계획서 작성 페이지와 같은 문(`plan_writer` · `writer="codex"`)으로 부른다 — 서버 전체 AI 는 끈 채(29차 §3-A).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
USAGE = ROOT / "data" / "private" / "llm_usage.jsonl"


def _usage_rows() -> list[dict]:
    if not USAGE.exists():
        return []
    return [json.loads(line) for line in USAGE.read_text(encoding="utf-8").splitlines() if line.strip()]


def _notice_demotions(draft: dict, compact) -> dict[str, list[str]]:
    """공고 근거 분기에서 내린 문장 — 갈래별(26차 §4-A 로 새로 생긴 갈래를 가른다)."""
    from app.services import plan_draft_service as pds  # backend 폴더로 옮긴 뒤 부른다(main 참고)

    kinds: dict[str, list[str]] = {"숫자가 인용에 없다": [], "인용을 공고에서 못 찾았다": [], "인용이 문장에 없다": [],
                                   "인용보다 계획이 길다": [], "평가 기준만 옮겼다": []}
    for section in draft["sections"]:
        for s in section["sentences"]:
            if not s.get("ai"):
                continue
            for flag in s.get("flags") or []:
                # 경고 글은 plan_draft_service 상수에서(32차 R31-19 — 손으로 적은 「평가 기준을 옮긴」이 실제 글과 달라 늘 0)
                if flag in (pds.FLAG_NOTICE_NOT_FOUND, pds.FLAG_NOTICE_SHORT):
                    kinds["인용을 공고에서 못 찾았다"].append(s["text"])
                elif flag.startswith(pds.FLAG_NOTICE_VALUES):
                    kinds["숫자가 인용에 없다"].append(f"{s['text']}  ⟶ {flag}")
                elif flag == pds.FLAG_NOTICE_EXTRA:
                    pieces = [p.strip() for p in (s.get("source") or "").split(" / ") if p.strip()]
                    present = any(compact(p) in compact(s["text"]) for p in pieces)
                    kinds["인용보다 계획이 길다" if present else "인용이 문장에 없다"].append(s["text"])
                elif flag == pds.FLAG_EVAL_ONLY:
                    kinds["평가 기준만 옮겼다"].append(s["text"])
    return kinds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", default="claude_cli", choices=("claude_cli", "codex_cli", "openai", "xai"))
    parser.add_argument("--task", type=int, default=4)
    parser.add_argument("--summary", type=Path, help="요약 표(마크다운)를 쓸 곳 — docs/reports/ 아래")
    parser.add_argument("--draft-out", type=Path, help="초안 JSON 을 쓸 곳(저장소 밖 · 커밋하지 않는다)")
    args = parser.parse_args()
    # 아래에서 backend 폴더로 옮겨 간다(tests 패키지) — 상대 경로는 그 전에 풀어 둔다.
    args.summary = args.summary.resolve() if args.summary else None
    args.draft_out = args.draft_out.resolve() if args.draft_out else None

    codex = args.provider == "codex_cli"
    os.environ.update({"LLM_LIVE": "0" if codex else "1", "PLAN_WRITER_CLI": "1" if codex else "0",
                       "LLM_PROVIDER": "openai" if codex else args.provider, "G2B_LIVE_FETCH": "0", "BIZINFO_LIVE_FETCH": "0",
                       "EMBEDDING_LIVE": "0", "SEMANTIC_FIT": "0"})
    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)
    from app.services import llm_client, plan_completeness_service, plan_draft_service, plan_form_service, plan_validation  # noqa: E402
    from app.services import support_requirement_extractor  # noqa: E402
    from tests.test_plan_draft import COMPANY, FACTS, PROGRAM  # noqa: E402 — 가상 회사
    from tests.test_plan_form import FULL  # noqa: E402 — 126482 공고문 원문 발췌

    ready, reason = llm_client.plan_writer_ready("codex") if codex else plan_draft_service.llm_ready()
    label = f"codex_cli · {llm_client.plan_writer_model('codex')}" if codex else f"{llm_client.completion_provider()} · {llm_client.completion_model()}"
    print(f"공급자 {label} · 준비 {ready}{f' ({reason})' if reason else ''}")
    if not ready:
        return 1
    form = plan_form_service.extract_form("bizinfo-PBLN_000000000126482", FULL)
    form["selected_task"] = next(t for t in form["tasks"] if t["no"] == args.task)
    before = len(_usage_rows())
    started = time.time()
    draft = plan_draft_service.generate(
        program=PROGRAM, form=form, requirements=support_requirement_extractor.extract_from_text("PBLN_000000000126482", FULL),
        company=COMPANY, facts=FACTS, matches=[], notice_text=FULL, annex=None, company_name="주식회사 시험",
        plan_writer=codex, writer="codex" if codex else "claude",
    )
    elapsed = round(time.time() - started, 1)
    rows = _usage_rows()[before:]
    checklist = plan_completeness_service.plan_completeness(draft, form)
    ai = [s for sec in draft["sections"] for s in sec["sentences"] if s.get("ai")]
    types = Counter(s["type"] for s in ai)
    tokens = [sum(r.get(k, 0) for r in rows) for k in ("prompt_tokens", "completion_tokens", "reasoning_tokens")]
    usd = round(sum(r.get("api_equivalent_usd", 0) for r in rows), 3)
    demotions = _notice_demotions(draft, plan_validation.compact)

    lines = [
        f"# 사업계획서 초안 공개 자료 시험 — {datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')}",
        "",
        "입력: 126482 공고문 원문 발췌(테스트 상수) + 가상 회사(테스트 상수) + 과제 "
        f"{args.task}번 · 저장하지 않음 · 회사 자료 읽지 않음 · `scripts/plan_dry_run.py`",
        "",
        "| 공급자 · 모델 | 시간 | 호출 | 입력/출력/추론 토큰 | 정가 환산 | AI 문장(회사·공고·제안) | 내림 | 빈칸 | 점검표 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        f"| {label} | {elapsed}초 | {len(rows)} "
        f"({', '.join(f'{k} {v}' for k, v in Counter(r['result'][:20] for r in rows).items())}) | "
        f"{tokens[0]:,} / {tokens[1]:,} / {tokens[2]:,} | ${usd} | {len(ai)} ({types.get(plan_draft_service.COMPANY, 0)}·"
        f"{types.get(plan_draft_service.NOTICE, 0)}·{types.get(plan_draft_service.SUGGESTION, 0)}) | "
        f"{draft['validation']['demoted']} | {len(draft['blanks'])} | {checklist['summary']} |",
        "",
        "공고 근거 분기에서 내린 문장(갈래별 · 예시는 앞 세 개):",
        "",
    ]
    for kind, texts in demotions.items():
        lines.append(f"- **{kind}** {len(texts)}")
        lines.extend(f"  - 「{t[:160]}」" for t in texts[:3])
    lines += ["", f"검증 셈: {json.dumps({k: v for k, v in draft['validation'].items() if k != 'budget'}, ensure_ascii=False)} · "
              f"사업비 {json.dumps(draft['validation'].get('budget'), ensure_ascii=False)}", ""]
    text = "\n".join(lines)
    print(text)
    if args.summary:
        args.summary.write_text(text, encoding="utf-8")
    if args.draft_out:
        args.draft_out.write_text(json.dumps(draft, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
