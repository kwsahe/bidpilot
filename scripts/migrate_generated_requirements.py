"""저장된 요구사항 파일에 항목 유형(item_type 등)을 영구 반영한다.

읽을 때는 rfp_parser.load_generated가 같은 규칙으로 즉석 마이그레이션하므로 이 스크립트 없이도
API는 동작한다. 파일까지 고쳐 두고 싶을 때(diff 검토·Gold 작업) 실행한다.

    backend/.venv/Scripts/python.exe scripts/migrate_generated_requirements.py           # dry-run
    backend/.venv/Scripts/python.exe scripts/migrate_generated_requirements.py --write   # 실제 반영

- requirement_id(REQ-nnn)는 바꾸지 않는다.
- 이미 item_type이 있는 항목(사람이 고친 것 포함)은 건드리지 않는다.
- 쓰기는 임시 파일 → 교체 (app.core.storage).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core import storage  # noqa: E402
from app.services import rfp_parser  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="파일에 반영한다 (기본은 dry-run)")
    args = parser.parse_args()

    files = sorted(rfp_parser.GENERATED_DIR.glob("*.requirements.json"))
    if not files:
        print(f"파일이 없습니다: {rfp_parser.GENERATED_DIR}")
        return

    for path in files:
        try:
            payload = storage.read_json(path)
        except storage.CorruptJsonError as exc:
            print(f"[깨짐] {path.name}: {exc}")
            continue
        if not isinstance(payload, dict):
            print(f"[형식 오류] {path.name}")
            continue
        before = storage.schema_version_of(payload)
        changed = rfp_parser.migrate_payload(payload)
        counts = Counter(r.get("item_type", "?") for r in payload.get("requirements", []))
        summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        flag = "변경" if changed else "그대로"
        print(f"[{flag}] {path.name}: v{before} → v{payload.get('schema_version')} · {summary}")
        if changed and args.write:
            storage.write_json_atomic(path, payload)

    if not args.write:
        print("\ndry-run 이었습니다. 반영하려면 --write 를 붙이세요.")


if __name__ == "__main__":
    main()
