#!/usr/bin/env python
"""이미 저장된 체크리스트의 중복 제목을 정리한다 (ISSUE-015 · TASK-016).

규칙을 고친 뒤에도 **예전에 저장된** 체크리스트에는 같은 제목이 두 번 남아 있다.
파일을 다시 만들지 않는 한 사라지지 않는다 — 항목마다 사람이 체크한 상태·메모가
붙어 있어서 통째로 지울 수 없기 때문이다.

이 스크립트는 지우지 않는다. 겹치는 제목 뒤에 그 항목이 나온 **요구사항 번호**를
붙여 서로 구분되게만 한다. 어느 쪽도 사라지지 않으므로 체크 상태·메모는 그대로다.

    # 무엇이 바뀌는지만 본다 (기본값)
    python scripts/dedupe_action_titles.py

    # 실제로 쓴다
    python scripts/dedupe_action_titles.py --write

주의: `data/public/` 아래는 git 이 추적하는 발표용 자료다. 쓰기 전에 `git status` 로
무엇이 바뀌는지 확인하고, 되돌리려면 `git checkout -- <파일>` 을 쓴다.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parent.parent / "data"

#: 정리 대상 — 공용 데모 체크리스트와 회사별 분석 폴더의 체크리스트.
PATTERNS = (
    "public/actions/*.actions.json",
    "private/organizations/*/analyses/*/actions.json",
)


def dedupe(items: list[dict]) -> int:
    """제목이 겹치는 항목에 요구사항 번호를 붙인다. 바꾼 개수를 돌려준다."""
    counts = collections.Counter(item.get("title") for item in items)
    seen: set[str] = set()
    changed = 0
    for item in items:
        title = item.get("title")
        if not isinstance(title, str) or counts[title] < 2:
            continue
        if title not in seen:
            # 첫 번째는 그대로 둔다 — 사람이 이미 그 이름으로 기억하고 있다.
            seen.add(title)
            continue
        requirement_id = item.get("requirement_id")
        if not requirement_id:
            continue
        suffix = f" — {requirement_id}"
        if title.endswith(suffix):
            continue
        item["title"] = title + suffix
        changed += 1
    return changed


def _conditions_path(actions_path: Path) -> Path:
    """이 체크리스트와 짝이 되는 조건 보고서 경로."""
    if actions_path.name == "actions.json":
        return actions_path.with_name("conditions.json")
    pid = actions_path.name.removesuffix(".actions.json")
    return actions_path.parent.parent / "conditions" / f"{pid}.conditions.json"


def live_condition_ids(actions_path: Path) -> set[str] | None:
    """지금 조건 보고서에 살아 있는 조건 id. 보고서를 못 읽으면 None (판정하지 않는다)."""
    path = _conditions_path(actions_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    report = payload.get("report") if isinstance(payload, dict) else None
    conditions = (report or payload or {}).get("conditions")
    if not isinstance(conditions, list):
        return None
    return {c.get("id") for c in conditions if isinstance(c, dict) and c.get("id")}


def orphans(items: list[dict], live: set[str]) -> list[dict]:
    """규칙이 더 이상 만들지 않는 조건에 붙어 있던 «자동» 항목.

    규칙을 고치면(예: 인력 요건 오탐 제거) 그 조건은 사라지는데, 이미 저장된 체크리스트의
    항목은 남는다. 화면에는 근거가 없어진 할 일이 그대로 보인다.

    **사람이 손댄 것은 절대 지우지 않는다.** 직접 추가한 항목(origin != auto), 체크했거나
    진행 중인 항목, 담당자·기한·완료 근거를 적어 둔 항목은 남긴다 — 그것들은 기록이다.
    """
    result = []
    for item in items:
        source = item.get("source_condition_id")
        if not source or source in live:
            continue
        if item.get("origin") != "auto" or item.get("status") != "todo":
            continue
        if item.get("owner") or item.get("due_at") or item.get("evidence"):
            continue
        result.append(item)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="실제로 파일에 쓴다 (기본은 미리보기)")
    parser.add_argument(
        "--prune-orphans",
        action="store_true",
        help="규칙이 더 이상 만들지 않는 조건에 붙어 있던 «자동·미착수» 항목을 지운다 (사람이 손댄 것은 남긴다)",
    )
    args = parser.parse_args()

    renamed = 0
    pruned = 0
    for pattern in PATTERNS:
        for path in sorted(DATA_ROOT.glob(pattern)):
            payload = json.loads(path.read_text(encoding="utf-8"))
            items = payload.get("items")
            if not isinstance(items, list):
                continue
            rel = path.relative_to(DATA_ROOT.parent)
            touched = False

            if args.prune_orphans:
                live = live_condition_ids(path)
                if live is None:
                    print(f"{rel}: 조건 보고서를 읽지 못해 정리를 건너뜁니다")
                else:
                    dead = orphans(items, live)
                    if dead:
                        print(f"{rel}: 근거 없는 자동 항목 {len(dead)}건 삭제")
                        for item in dead:
                            print(f"    - {item.get('title')}  (조건 {item.get('source_condition_id')} 없음)")
                        dead_ids = {id(d) for d in dead}
                        payload["items"] = [i for i in items if id(i) not in dead_ids]
                        items = payload["items"]
                        pruned += len(dead)
                        touched = True

            before = [item.get("title") for item in items]
            changed = dedupe(items)
            if changed:
                renamed += changed
                touched = True
                print(f"{rel}: 겹치는 제목 {changed}건")
                for old_title, item in zip(before, items):
                    if old_title != item.get("title"):
                        print(f"    {old_title}  ->  {item['title']}")

            if touched and args.write:
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")

    if renamed == 0 and pruned == 0:
        print("정리할 것이 없습니다.")
    elif not args.write:
        print(f"{chr(10)}미리보기입니다 — 제목 {renamed}건 · 삭제 {pruned}건. 실제로 쓰려면 --write 를 붙이세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
