"""입찰 제안서 양식 대조 — 받아 둔 원문(24건)에서 앱이 읽은 제안서 목차 · 평가표 · 형식 규정을 정답지와 맞춰 본다(11-06 판 2.5.0 A-7).

정답지 `docs/reports/2026-11-06_proposal_format/sweep_result.json` 은 사람이 원문을 읽고 적은 목차 · 평가표 · 형식 규정이다 —
고치지 않는다(정답지가 틀린 곳은 보고에 적는다). 네트워크는 부르지 않는다(받아 둔 파일만 · 나라장터 · 기업마당 · 첨부 받기 끔).

    backend/.venv/Scripts/python.exe scripts/check_bid_outline.py
    backend/.venv/Scripts/python.exe scripts/check_bid_outline.py --only g2b-R26BK01805118-000 --show
    backend/.venv/Scripts/python.exe scripts/check_bid_outline.py --json out.json

판정:
  목차 — 대항목이 모두 맞음(제목을 번호 · 괄호 · 서식 표기 · ※ 꼬리 · 띄어쓰기를 빼고 비교) · 소항목 일치 수 · 표준 목차로 대신함 ·
         문서 목차를 잡음(읽은 대항목에 제안요청서 장 낱말이 둘 이상)
  평가표 — 총점이 맞음: 앱 합(전체 또는 정성만)이 정답지 총점 또는 정답지 항목 합과 같다(정답지는 공고마다 정량을 넣기도 빼기도 했다)
  형식 — 정답지 형식 규정 글에서 뽑은 쪽수 상한 · 평가본 회사명 금지 · 가로 · PPT · 두 권과 비교(참고 · 합격선 밖)

합격선(지시서 A-7): 원문에 목차가 있는 18건 중 대항목이 모두 맞는 것 15건 이상 · 표준 목차로 대신하는 것 1건 이하 · 문서 목차를 잡는 것 0 ·
1786460 그대로(고치기 전 앱 결과 = 대항목 7 · 소항목 18 · 평가 15항목 100점) · 평가표 총점이 맞는 것 20건 중 15건 이상.
분모는 정답지 기준으로 고정한다(목차 18 · 평가 20) — 원문을 못 읽은 공고 · 1786460 을 못 본 것은 실패로 센다(11-06 검토: 원문이 없으면
합격선이 비어 넘어갔다). `--only` 일 때만 합격선을 건너뛴다.
참고(합격선 밖): 평가 항목 이름 일치 · 종류(정량 · 정성) 일치(정답지 영역 이름에 「정량」 · 「정성」이 있는 항목만) · 앱이 더 읽은 소항목 수.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "reports" / "2026-11-06_proposal_format"
KEEP_ID = "g2b-R26BK01786460-000"
for _name in ("LIVE_FETCH", "G2B_LIVE_FETCH", "BIZINFO_LIVE_FETCH", "ATTACHMENT_FETCH", "EMBEDDING_LIVE", "SEMANTIC_FIT", "LLM_LIVE"):
    os.environ[_name] = "0"
sys.path.insert(0, str(ROOT / "backend"))

from app.services import bid_proposal_service as bid  # noqa: E402


def norm(text: str) -> str:
    """비교용 제목 — 앞 번호 · 괄호 · 서식 표기 · ※ 꼬리 · 문장부호 · 띄어쓰기를 뺀다."""
    text = re.sub(r"\([^)]*\)|<[^>]*>|【[^】]*】|\[[^\]]*\]", "", text or "").split("※")[0]
    text = re.sub(r"^\s*(?:\d{1,2}(?:\s*[.-]\s*\d{1,2})*\s*\.?|[가-하]\s*\.|\d{1,2}\s*\))\s*", "", text)
    return re.sub(r"[^가-힣A-Za-z0-9]", "", text)


def gold_format(rules: list[str]) -> dict[str, Any]:
    """정답지 형식 규정 글 → 비교할 값(참고)."""
    joined = " / ".join(rules)
    pages = [int(m.group(1)) for rule in rules if not re.search(r"감리원|없음", rule)
             for m in re.finditer(r"(\d{1,3})\s*(?:쪽|페이지|page|매)", rule, re.I) if "요약" not in rule[max(0, m.start() - 12):m.start()]]
    return {
        "page_limit": max(pages) if pages else None,
        "blind": bool(re.search(r"미표기|표기\s*금지|표시도\s*불가|식별\s*정보\s*삭제|미기재|무기명|기재\s*안\s*함|업체식별", joined)),
        "landscape": bool(re.search(r"가로형|A4\s*가로|가로\s*방향", joined)),
        "ppt": bool(re.search(r"제안서\(PPT\)|PPT\)\s*\d부", joined)),
        "two_volume": bool(re.search(r"정량적 평가제안서|사업수행능력평가서|정량\)와", joined)),
    }


def gold_kind(area: str | None) -> str | None:
    """정답지 평가 항목의 종류 — 영역 이름(「정량평가(10)」 · 「기술평가 · 정성 평가」)에 적힌 것만. 없으면 모른다."""
    words = re.sub(r"\s+", "", area or "")
    return "정량" if "정량" in words else "정성" if "정성" in words else None


def check(gold: dict[str, Any], before: dict[str, Any]) -> dict[str, Any]:
    pid = gold["id"]
    row: dict[str, Any] = {"id": pid, "title": gold["title"][:40]}
    try:
        _parsed, docs = bid.load_documents(pid)
    except bid.NoRfpError:
        row.update(verdict="제안요청서 없음(쓰지 않음)", no_rfp=True)
        return row
    except bid.SourceMissingError as exc:
        row.update(verdict=f"원문 없음 — {exc}", missing=True)
        return row
    layout = bid.read_layout(docs)
    outline = layout["outline"] if layout["outline_source"] == "rfp" else []
    evaluation = layout["evaluation"]
    fmt = layout["format"]
    row["documents"] = [f"{d['role']}:{d['name'][:40]}" for d in docs]
    row["outline_source"] = layout["outline_source"]
    row["outline_where"] = layout["outline_where"]
    row["outline"] = [{"no": m["no"], "title": m["title"], "items": [i["title"] for i in m.get("items") or []]} for m in outline]
    row["rejected"] = layout["outline_rejected"]
    row["chapter_majors"] = sum(1 for m in outline if bid._CHAPTER_WORDS_RE.search(m["title"]))
    want = gold.get("required_outline") or []
    if gold["required_outline_exists"]:
        majors_ok = len(outline) == len(want) and all(norm(a["title"]) == norm(b["title"]) for a, b in zip(outline, want))
        items_hit = sum(1 for a, b in zip(outline, want) for item in b["items"] if norm(item) in {norm(i["title"]) for i in a.get("items") or []})
        items_extra = sum(1 for a, b in zip(outline, want) for i in a.get("items") or [] if norm(i["title"]) not in {norm(t) for t in b["items"]})
        items_extra += sum(len(a.get("items") or []) for a in outline[len(want):])
        row.update(majors_ok=majors_ok, items_hit=items_hit, items_want=sum(len(b["items"]) for b in want), items_extra=items_extra,
                   standard=not outline, majors=f"{len(outline)}/{len(want)}")
    else:
        row.update(extra_outline=bool(outline))
    items = evaluation.get("items") or []
    total_all = sum(i["points"] for i in items) if items else None
    total_qual = sum(i["points"] for i in items if i.get("kind") != "정량") if items else None
    row["evaluation"] = {"items": len(items), "total": total_all, "qualitative": total_qual,
                         "where": evaluation.get("where"), "names": [f"{i.get('kind')}|{i['name'][:30]}|{i['points']}" for i in items]}
    if gold["evaluation_exists"]:
        targets = {gold.get("evaluation_total"), sum(e["points"] for e in gold["evaluation"])}
        row["eval_ok"] = bool(items) and bool({total_all, total_qual} & targets)
        row["eval_want"] = f"{len(gold['evaluation'])}항목 {gold.get('evaluation_total')}"
        kinds = {norm(i["name"]): i.get("kind", "정성") for i in items}
        named = [e for e in gold["evaluation"] if norm(e["name"]) in kinds]
        typed = [e for e in named if gold_kind(e.get("area"))]
        row.update(eval_names_hit=len(named), eval_names_want=len(gold["evaluation"]),
                   eval_kinds_hit=sum(1 for e in typed if kinds[norm(e["name"])] == gold_kind(e.get("area"))), eval_kinds_want=len(typed))
    expected = gold_format(gold.get("format_rules") or [])
    row["format"] = {key: fmt.get(key) for key in expected}
    row["format_diff"] = [f"{key}: 앱 {fmt.get(key)} · 정답지 {value}" for key, value in expected.items() if fmt.get(key) != value]
    if pid == KEEP_ID:
        old = [(m["title"], m["items"]) for m in before.get("app_outline") or []]
        new = [(m["title"], m["items"]) for m in row["outline"]]
        row["keep_ok"] = new == old and len(items) == before.get("app_eval_items") and total_all == before.get("app_eval_total")
    return row


def verdict(row: dict[str, Any]) -> str:
    if row.get("no_rfp") or row.get("missing"):
        return row["verdict"]
    parts = []
    if "majors_ok" in row:
        parts.append("목차 맞음" if row["majors_ok"] else "표준 목차로 대신" if row["standard"] else f"목차 틀림({row['majors']})")
        parts.append(f"소항목 {row['items_hit']}/{row['items_want']}")
    else:
        parts.append("목차 없어야 함 — 읽음" if row["extra_outline"] else f"목차 없음 맞음({row['outline_source']})")
    if "eval_ok" in row:
        parts.append(("평가 맞음" if row["eval_ok"] else "평가 틀림")
                     + f"(앱 {row['evaluation']['items']}항목 {row['evaluation']['total']}/정성 {row['evaluation']['qualitative']} · 정답지 {row['eval_want']}"
                     + f" · 이름 {row['eval_names_hit']}/{row['eval_names_want']} · 종류 {row['eval_kinds_hit']}/{row['eval_kinds_want']})")
    elif row["evaluation"]["items"]:
        parts.append(f"평가표 없어야 함 — {row['evaluation']['items']}항목 읽음")
    if row.get("chapter_majors", 0) >= 2:
        parts.append("문서 목차를 잡음")
    if "keep_ok" in row:
        parts.append("1786460 그대로" if row["keep_ok"] else "1786460 달라짐!")
    if row["format_diff"]:
        parts.append("형식 차이 " + "; ".join(row["format_diff"]))
    return " · ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", action="append", help="이 공고만(여러 번)")
    parser.add_argument("--show", action="store_true", help="읽은 목차 · 평가표를 자세히")
    parser.add_argument("--json", dest="json_out", help="결과 JSON 을 남길 곳")
    args = parser.parse_args()
    golds = json.loads((REPORT / "sweep_result.json").read_text(encoding="utf-8"))
    befores = {r["id"]: r for r in json.loads((REPORT / "app_reading.json").read_text(encoding="utf-8"))}
    rows = []
    for gold in golds:
        if args.only and gold["id"] not in args.only:
            continue
        row = check(gold, befores.get(gold["id"], {}))
        rows.append(row)
        print(f"{row['id']} | {row['title']}\n  {verdict(row)}")
        if args.show:
            print(f"  문서: {row.get('documents')}\n  목차 위치: {row.get('outline_where')} · 탈락: {row.get('rejected')}")
            for major in row.get("outline") or []:
                print(f"    {major['no']}. {major['title']} | {' / '.join(major['items'])}")
            for name in (row.get("evaluation") or {}).get("names") or []:
                print(f"    평가 {name}")
    # 분모는 정답지 기준(목차 18 · 평가 20) — 원문을 못 읽은 공고(행에 판정 칸이 없다)는 실패로 센다
    chosen = [g for g in golds if not args.only or g["id"] in args.only]
    outline_want = sum(1 for g in chosen if g["required_outline_exists"])
    eval_want = sum(1 for g in chosen if g["evaluation_exists"])
    outline_rows = [r for r in rows if "majors_ok" in r]
    eval_rows = [r for r in rows if "eval_ok" in r]
    majors_ok = sum(r["majors_ok"] for r in outline_rows)
    eval_ok = sum(r["eval_ok"] for r in eval_rows)
    keep = next((r["keep_ok"] for r in rows if "keep_ok" in r), None)
    summary = {
        "목차 대항목 모두 맞음": f"{majors_ok}/{outline_want}",
        "표준 목차로 대신": sum(r["standard"] for r in outline_rows),
        "문서 목차를 잡음": sum(1 for r in rows if r.get("chapter_majors", 0) >= 2),
        "목차 없는 원문에서 읽음": sum(1 for r in rows if r.get("extra_outline")),
        "소항목 일치": f"{sum(r['items_hit'] for r in outline_rows)}/{sum(r['items_want'] for r in outline_rows)}",
        "앱이 더 읽은 소항목": sum(r["items_extra"] for r in outline_rows),
        "평가표 총점 맞음": f"{eval_ok}/{eval_want}",
        "평가 항목 이름 일치": f"{sum(r['eval_names_hit'] for r in eval_rows)}/{sum(r['eval_names_want'] for r in eval_rows)}",
        "평가 종류 일치": f"{sum(r['eval_kinds_hit'] for r in eval_rows)}/{sum(r['eval_kinds_want'] for r in eval_rows)}",
        "1786460 그대로": keep,
    }
    if args.only:
        print("합계: " + " · ".join(f"{k} {v}" for k, v in summary.items()) + " · 합격선 건너뜀(--only)")
        passed = True
    else:
        passed = (majors_ok >= 15 and summary["표준 목차로 대신"] <= 1
                  and summary["문서 목차를 잡음"] == 0 and keep is True and eval_ok >= 15)
        print("합계: " + " · ".join(f"{k} {v}" for k, v in summary.items()) + f" · 합격선 {'넘음' if passed else '못 넘음'}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({"summary": summary, "passed": passed, "rows": rows}, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
