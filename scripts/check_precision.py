"""정밀도 검사 — 샘플에듀 목록 맨 위가 정말 샘플에듀 일인가 (39차 §3-A-1 · D18 → 40차 §3-A-2 · D25).

검수자가 공고명 · 조달분류 · 기관 · 예산만 보고 판정한 **기준 답안**으로 지금 코드가 세운 목록을 잰다. 기준 답안의 판정은
고치지 않는다(D21) — 이견은 보고에 「검수자 판정 다시 보기」로 적는다.

    python scripts/check_precision.py --data-dir <10-16 고정 저장본 사본> --today 2026-10-16
    python scripts/check_precision.py --data-dir <10-19 고정 저장본 사본> --today 2026-10-19 --gold backend/tests/fixtures/precision_gold_1019.json
    python scripts/check_precision.py ... --json out.json

`--gold` 는 여러 번 줄 수 있다 — 같은 공고가 둘 이상에 있으면 **먼저 준 파일**의 판정을 쓴다(그 날 저장본의 답안을 먼저).
`--with-ai <ai_fit 픽스처>` 는 규칙 + AI 를 잰다 — 픽스처(40차 §3-D L2 결과 · `backend/tests/fixtures/ai_fit_1016.json` 등)를 **사본**의
회사 폴더 `ai_fit.json` 으로 넣고 사본의 `ai_fit_assist` 를 켠 뒤 제품 길 그대로 목록을 세운다(AI 를 다시 부르지 않는다).

**고정 저장본(`C:\\Users\\sangh\\BidPilotSnapshots\\store_20261016 · store_20261019\\data`)은 고치지 않는다** — 사본을 넘긴다.
이 스크립트는 목록 메모 캐시를 사본 안에 쓴다. 바깥 호출은 하지 않는다(G2B · 기업마당 · 첨부 · 임베딩 · AI 모두 끔).

D25 합격선(40차 검수자 기본값 · D18 을 대신):
  ① 브리핑 매출 TOP 10 의 「아님(not_ours)」 1건 이하(기준 답안에 없는 공고는 「판정 없음」으로 따로 센다)
  ② 본업 덩어리(나라장터 입찰 · 사전규격 뺌 · 살아 있는 것 · 실무순) @20 본업 + 인접 80% 이상 · @40 75% 이상
     (분모는 20 · 40 그대로 — 「판정 없음」은 맞지 않은 것으로 센다. 판정 있는 것만의 비율도 함께 적는다)
  ③ 기준 답안 「본업(core)」이 비추천으로 접힌 것 2건 이하 · precision.md 「숨은 본업」(d_fn core)은 0 ·
     「다른 사전규격」(선제준비 접힘)에 들어간 기준 답안 「본업」 3건 이하
  ④ (a) · (c) 「아님」이 본업 덩어리에 남은 비율 10% 이하(그 꼴 답안이 있을 때) · 본업 덩어리 **「주제 맞음」 구간**의 「아님」 15% 이하
  ⑤ 본업 덩어리 「주제 맞음」 구간의 본업 + 인접 80% 이상
  ④ · ⑤ 의 구간 비율은 판정 있는 것만으로 내고 「판정 없음」 수를 따로 적는다. 「주제 맞음」 구간 = 본업 덩어리에서 「주제 확인」 ·
  「AI: 본업 아닐 수 있음」 꼬리표가 없는 것(40차 §3-C · §3-D 전에는 본업 덩어리 전체).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: 기준 답안 — 시험 픽스처(10-16: 나라장터 입찰 · 사전규격 157건 · 10-19: 536건 · 원자료 포함). 보고 폴더 원본은 `--gold` 로.
DEFAULT_GOLD = ROOT / "backend" / "tests" / "fixtures" / "precision_gold_1017.json"
ORG = "org-sample"
#: 브리핑이 보는 기간(내보내기 · 브리핑 경로의 기본값 · `api/insights.py`).
BRIEF_DAYS = 30


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", required=True, help="고정 저장본의 **사본** (DATA_DIR)")
    parser.add_argument("--today", required=True, help="잴 날(YYYY-MM-DD) — 그날 12:00 KST 로 목록을 세운다")
    parser.add_argument("--gold", action="append", help="기준 답안 JSON(여러 번 · 겹치면 먼저 준 것 · 없으면 10-16 픽스처)")
    parser.add_argument("--json", dest="json_out", help="결과를 JSON 으로도 남길 곳")
    parser.add_argument("--top", type=int, default=40, help="본업 덩어리를 몇 위까지 적을지")
    parser.add_argument("--with-ai", dest="with_ai", help="AI 적합도 답 픽스처 — 사본에 넣고 규칙 + AI 로 잰다(호출 0)")
    return parser.parse_args()


def _install_ai_fixture(data_dir: str, fixture: str) -> None:
    """사본의 샘플에듀 폴더에 AI 답을 넣고 `ai_fit_assist` 를 켠다 — **사본만** 고친다(고정 저장본은 그대로)."""
    org = Path(data_dir) / "private" / "organizations" / ORG
    payload = json.loads(Path(fixture).read_text(encoding="utf-8"))
    (org / "ai_fit.json").write_text(json.dumps({"entries": payload["entries"], "runs": []}, ensure_ascii=False), encoding="utf-8")
    capacity_path = org / "delivery_capacity.json"
    capacity = json.loads(capacity_path.read_text(encoding="utf-8")) if capacity_path.exists() else {}
    capacity["ai_fit_assist"] = True
    capacity_path.write_text(json.dumps(capacity, ensure_ascii=False), encoding="utf-8")


def _prepare_env(data_dir: str) -> None:
    os.environ["DATA_DIR"] = data_dir
    for name in ("LIVE_FETCH", "G2B_LIVE_FETCH", "BIZINFO_LIVE_FETCH", "ATTACHMENT_FETCH", "EMBEDDING_LIVE", "SEMANTIC_FIT", "LLM_LIVE"):
        os.environ[name] = "0"
    sys.path.insert(0, str(ROOT / "backend"))


async def _listing(now: datetime):
    from app.schemas.organization import AnalysisContext
    from app.services import opportunity_service

    context = AnalysisContext(organization_id=ORG, evidence_scope="internal")
    return await opportunity_service.list_opportunities(
        context=context, source="all", days=BRIEF_DAYS, sort=None, include_closed=False, include_blocked=True, now=now, with_prepare=True,
    )


def _folded(item) -> bool:
    return item.practical_group == "비추천" or bool(item.relevance_note)


def _live(item) -> bool:
    return item.practical_group not in ("제외", "비추천")


def _topic_ok(item) -> bool:
    """「주제 맞음」 구간인가 — 「주제 확인」 · AI 「아님」 꼬리표가 없다(40차 §3-C · §3-D 전에는 늘 참)."""
    return not getattr(item, "topic_note", None) and not getattr(item, "ai_fit_note", None)


def merge_golds(paths: list[str]) -> dict:
    """기준 답안 여럿을 하나로 — 같은 id 는 먼저 준 파일의 판정(D21 · 판정을 고치지 않고 덮어쓰지도 않는다)."""
    items: dict[str, dict] = {}
    for path in paths:
        for row in json.loads(Path(path).read_text(encoding="utf-8"))["items"]:
            items.setdefault(row["id"], row)
    return {"items": list(items.values()), "files": paths}


def measure(listing, gold: dict, top_n: int) -> dict:
    from app.services import opportunity_brief_service as brief
    from app.services import practical_priority as practical

    labels = {row["id"]: row for row in gold["items"]}
    # 사전규격은 39차 결정 1 로 입찰 목록 밖 — 「선제준비」 칸 넷에서 찾는다(③ 본업 접힘은 사전규격도 센다).
    section = listing.prepare
    pre = [*section.items, *section.others, *section.opinion_passed, *section.merged] if section else []
    by_id = {item.id: item for item in [*listing.items, *pre]}

    def label(item_id: str) -> str:
        row = labels.get(item_id)
        return row["label"] if row else "판정 없음"

    # ① 브리핑 매출 TOP 10
    top = brief.revenue_top(listing)
    top_counts = Counter(label(i.id) for i in top)

    # ② 본업 덩어리(나라장터 입찰 · 사전규격 뺌 · 살아 있는 것) — 실무순
    core_block = sorted(
        (
            i for i in listing.items
            if i.source_type == "g2b" and i.opportunity_type != "pre_spec" and _live(i)
            and (i.practical_block or practical.BLOCK_CORE) == practical.BLOCK_CORE
        ),
        key=lambda i: (i.practical_order or 10**9, i.id),
    )

    topic_zone = [i for i in core_block if _topic_ok(i)]

    def zone() -> dict:
        counts = Counter(label(i.id) for i in topic_zone)
        labeled = len(topic_zone) - counts.get("판정 없음", 0)
        good = counts.get("core", 0) + counts.get("adjacent", 0)
        return {
            "rows": len(topic_zone), "of_block": len(core_block), "counts": dict(counts), "labeled": labeled,
            "core_adjacent_ratio": round(good / labeled, 3) if labeled else None,
            "not_ours_ratio": round(counts.get("not_ours", 0) / labeled, 3) if labeled else None,
        }

    def at(k: int) -> dict:
        rows = core_block[:k]
        counts = Counter(label(i.id) for i in rows)
        good = counts.get("core", 0) + counts.get("adjacent", 0)
        labeled = len(rows) - counts.get("판정 없음", 0)
        return {
            "k": k, "rows": len(rows), "counts": dict(counts),
            "core_adjacent": good,
            "ratio": round(good / k, 3) if k else 0.0,
            "ratio_labeled_only": round(good / labeled, 3) if labeled else None,
        }

    # ③ 기준 답안 「본업」이 비추천으로 접힌 것
    folded_core = []
    missing_core = []
    for row in gold["items"]:
        if row["label"] != "core":
            continue
        item = by_id.get(row["id"])
        if item is None:
            missing_core.append(row["id"])
            continue
        if _folded(item):
            folded_core.append({"id": row["id"], "section": row.get("section", "-"), "title": row["title"], "note": item.relevance_note})
    hidden = [r for r in folded_core if r.get("section") == "d_fn"]
    # 「다른 사전규격」(선제준비 접힘)에 들어간 기준 답안 「본업」 — 40차 D25 ③(39차 D18 은 사전규격을 세지 않았다)
    others_ids = {i.id for i in (section.others if section else [])}
    prespec_hidden = [{"id": r["id"], "title": r["title"], "type": by_id[r["id"]].fit_type, "group": by_id[r["id"]].practical_group,
                       "block": by_id[r["id"]].practical_block, "note": by_id[r["id"]].relevance_note}
                      for r in gold["items"] if r["label"] == "core" and r["id"] in others_ids]

    # ④ (a) · (c) 「아님」이 본업 덩어리(살아 있는 것)에 남은 비율
    ac_not = [r for r in gold["items"] if r.get("section") in ("a", "c") and r["label"] == "not_ours"]
    stuck = []
    for row in ac_not:
        item = by_id.get(row["id"])
        if item is not None and _live(item) and item.opportunity_type != "pre_spec" and (item.practical_block or practical.BLOCK_CORE) == practical.BLOCK_CORE:
            stuck.append({"id": row["id"], "title": row["title"], "group": item.practical_group, "type": item.fit_type})
    ac_present = sum(1 for r in ac_not if r["id"] in by_id)

    # 43차 Q6 — 선제준비 「보임」 정밀도(참고 · 합격선 아님) — 기준 답안 사전규격 줄 중 칸에 보인 것의 판정
    shown = list(section.items) if section else []
    shown_counts = Counter(label(i.id) for i in shown)
    shown_labeled = len(shown) - shown_counts.get("판정 없음", 0)
    result = {
        "prepare_shown": {
            "rows": len(shown), "counts": dict(shown_counts), "labeled": shown_labeled,
            "core_adjacent_ratio": round((shown_counts.get("core", 0) + shown_counts.get("adjacent", 0)) / shown_labeled, 3) if shown_labeled else None,
            "not_ours": [{"id": i.id, "title": i.title, "type": i.fit_type} for i in shown if label(i.id) == "not_ours"],
        },
        "top10": {
            "counts": dict(top_counts),
            "rows": [
                {"rank": n, "id": i.id, "label": label(i.id), "title": i.title, "budget": i.budget,
                 "group": i.practical_group, "type": i.fit_type, "tier": i.time_tier}
                for n, i in enumerate(top, start=1)
            ],
        },
        "core_block": {
            "at20": at(20), "at40": at(40),
            "rows": [
                {"rank": n, "id": i.id, "label": label(i.id), "title": i.title, "budget": i.budget,
                 "group": i.practical_group, "type": i.fit_type, "tier": i.time_tier}
                for n, i in enumerate(core_block[:top_n], start=1)
            ],
        },
        "folded_core": {"count": len(folded_core), "hidden_d_fn": len(hidden), "rows": folded_core, "missing_in_list": missing_core},
        # 41차 — 그중 대형 · 파트너형 후보(결정 1 · 2 로 일부러 접는 것)는 따로 센다(합격선은 그대로 · 보고에 함께 적는다)
        "prespec_hidden_core": {"count": len(prespec_hidden), "rows": prespec_hidden,
                                "large": sum(1 for r in prespec_hidden if r["block"] == practical.BLOCK_LARGE)},
        "topic_zone": zone(),
        "ac_not_ours_in_core": {
            "count": len(stuck), "of": len(ac_not), "present": ac_present,
            "ratio": round(len(stuck) / len(ac_not), 3) if ac_not else 0.0, "rows": stuck,
        },
    }
    tz = result["topic_zone"]
    result["d25"] = {
        "①": top_counts.get("not_ours", 0) <= 1,
        "②": result["core_block"]["at20"]["ratio"] >= 0.8 and result["core_block"]["at40"]["ratio"] >= 0.75,
        "③": len(folded_core) <= 2 and len(hidden) == 0 and len(prespec_hidden) <= 3,
        "④": (not ac_not or result["ac_not_ours_in_core"]["ratio"] <= 0.10) and (tz["not_ours_ratio"] or 0.0) <= 0.15,
        "⑤": tz["core_adjacent_ratio"] is not None and tz["core_adjacent_ratio"] >= 0.8,
    }
    return result


def _won(value) -> str:
    return "-" if not value else f"{value / 100_000_000:.2f}"


def _pct(value) -> str:
    return "-" if value is None else f"{value:.0%}"


def print_report(result: dict, *, sha: dict, today: str, rules: int, gold_files: list[str]) -> None:
    d25 = result["d25"]
    mark = lambda ok: "✓" if ok else "✗"  # noqa: E731
    print(f"# 정밀도 검사 — {today} · 규칙 판 {rules} · 저장본 {sha}")
    print()
    print(f"기준 답안: {' + '.join(Path(p).name for p in gold_files)}" + (f" · 규칙 + AI({Path(result['meta']['with_ai']).name})" if result.get("meta", {}).get("with_ai") else " · 규칙만"))
    print()
    tc = result["top10"]["counts"]
    a20, a40 = result["core_block"]["at20"], result["core_block"]["at40"]
    fc, ac, ph, tz = result["folded_core"], result["ac_not_ours_in_core"], result["prespec_hidden_core"], result["topic_zone"]
    tzc = tz["counts"]
    print("| D25 | 값 | 합격선 | |")
    print("| --- | --- | --- | --- |")
    print(f"| ① 브리핑 매출 TOP 10 「아님」 | {tc.get('not_ours', 0)} (본업 {tc.get('core', 0)} · 인접 {tc.get('adjacent', 0)} · 경계 {tc.get('boundary', 0)} · 판정 없음 {tc.get('판정 없음', 0)}) | ≤ 1 | {mark(d25['①'])} |")
    print(f"| ② 본업 덩어리 본업 + 인접 | @20 {a20['core_adjacent']}/20 = {a20['ratio']:.0%} (판정 없음 {a20['counts'].get('판정 없음', 0)} · 판정 있는 것만 {_pct(a20['ratio_labeled_only'])}) · @40 {a40['core_adjacent']}/40 = {a40['ratio']:.0%} (판정 없음 {a40['counts'].get('판정 없음', 0)} · {_pct(a40['ratio_labeled_only'])}) | @20 ≥ 80% · @40 ≥ 75% | {mark(d25['②'])} |")
    print(f"| ③ 기준 답안 「본업」 접힘 | 비추천 {fc['count']}(숨은 본업 {fc['hidden_d_fn']}) · 다른 사전규격 {ph['count']}(그중 대형 {ph.get('large', 0)}) | 비추천 ≤ 2 · 숨은 0 · 사전규격 ≤ 3 | {mark(d25['③'])} |")
    ac_text = f"(a) · (c) 「아님」 잔류 {ac['count']}/{ac['of']} = {ac['ratio']:.0%} · " if ac["of"] else ""
    print(f"| ④ 「아님」 잔류 | {ac_text}「주제 맞음」 구간 「아님」 {tzc.get('not_ours', 0)}/{tz['labeled']} = {_pct(tz['not_ours_ratio'])} | (a)(c) ≤ 10% · 구간 ≤ 15% | {mark(d25['④'])} |")
    print(f"| ⑤ 「주제 맞음」 구간 본업 + 인접 | {tzc.get('core', 0) + tzc.get('adjacent', 0)}/{tz['labeled']} = {_pct(tz['core_adjacent_ratio'])} (구간 {tz['rows']}/{tz['of_block']} · 판정 없음 {tzc.get('판정 없음', 0)} · 경계 {tzc.get('boundary', 0)}) | ≥ 80% | {mark(d25['⑤'])} |")
    ps = result["prepare_shown"]
    psc = ps["counts"]
    print()
    print(f"참고(43차 Q6 · 합격선 아님) — 선제준비 「보임」 {ps['rows']}건 중 기준 답안 판정 {ps['labeled']}건: 본업 {psc.get('core', 0)} · 인접 {psc.get('adjacent', 0)} · "
          f"경계 {psc.get('boundary', 0)} · 아님 {psc.get('not_ours', 0)} → 본업 + 인접 {_pct(ps['core_adjacent_ratio'])}")
    for row in ps["not_ours"]:
        print(f"  - 아님: {row['title'][:50]} ({row['type']})")
    print()
    print("## 브리핑 매출 TOP 10")
    print()
    print("| # | 판정 | 공고 | 예산(억) | 칸 · 유형 · 등급 |")
    print("| --- | --- | --- | --- | --- |")
    for row in result["top10"]["rows"]:
        print(f"| {row['rank']} | {row['label']} | {row['title'][:46]} | {_won(row['budget'])} | {row['group']} · {row['type']} · {row['tier']} |")
    print()
    print(f"## 본업 덩어리 상위 {len(result['core_block']['rows'])}")
    print()
    print("| # | 판정 | 공고 | 예산(억) | 칸 · 유형 · 등급 |")
    print("| --- | --- | --- | --- | --- |")
    for row in result["core_block"]["rows"]:
        print(f"| {row['rank']} | {row['label']} | {row['title'][:46]} | {_won(row['budget'])} | {row['group']} · {row['type']} · {row['tier']} |")
    print()
    if fc["rows"]:
        print("## 기준 답안 「본업」인데 비추천으로 접힌 것")
        print()
        for row in fc["rows"]:
            print(f"- [{row['section']}] {row['title'][:50]} — {row['note']}")
        print()
    if fc["missing_in_list"]:
        print(f"(기준 답안 「본업」 중 이 목록에 없는 것 {len(fc['missing_in_list'])}건 — 마감 · 기간 밖 · 기업마당 등: {', '.join(fc['missing_in_list'][:8])}{' …' if len(fc['missing_in_list']) > 8 else ''})")
        print()
    if ph["rows"]:
        print("## 기준 답안 「본업」인데 「다른 사전규격」에 접힌 것")
        print()
        for row in ph["rows"]:
            print(f"- {row['id']} {row['title'][:50]} — {row['block']} · {row['type']} · {row['note'] or '-'}")
        print()
    if ac["rows"]:
        print("## (a) · (c) 「아님」인데 본업 덩어리에 남은 것")
        print()
        for row in ac["rows"]:
            print(f"- {row['title'][:50]} — {row['group']} · {row['type']}")
        print()
    passed = all(d25.values())
    print(f"D25 {'모두 합격' if passed else '불합격 ' + ' · '.join(k for k, ok in d25.items() if not ok)}")


def main() -> int:
    args = _arguments()
    if args.with_ai:
        _install_ai_fixture(args.data_dir, args.with_ai)
    _prepare_env(args.data_dir)
    import hashlib

    from app.services import support_application_service

    gold_files = args.gold or [str(DEFAULT_GOLD)]
    gold = merge_golds(gold_files)
    day = date.fromisoformat(args.today)
    now = datetime(day.year, day.month, day.day, 3, 0, tzinfo=timezone.utc)  # 12:00 KST
    base = Path(args.data_dir)

    def sha(rel: str) -> str:
        path = base / rel
        return hashlib.sha1(path.read_bytes()).hexdigest()[:8] if path.exists() else "-"

    stamps = {"g2b": sha("private/cache/g2b/g2b_cache.json"), "bizinfo": sha("private/cache/bizinfo/bizinfo_cache.json"),
              "prespec": sha("private/cache/g2b_prespec/prespec_cache.json")}
    listing = asyncio.run(_listing(now))
    result = measure(listing, gold, args.top)
    result["meta"] = {"today": args.today, "sha1": stamps, "rules_version": support_application_service.RULES_VERSION,
                      "items": len(listing.items), "gold": gold_files, "with_ai": args.with_ai}
    print_report(result, sha=stamps, today=args.today, rules=support_application_service.RULES_VERSION, gold_files=gold_files)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if all(result["d25"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
