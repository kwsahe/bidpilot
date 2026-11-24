"""보관된 실제 제안요청서 원문으로 요구사항을 다시 추출하고 저장한다.

왜 필요한가
-----------
`rfp_parser.parse_real_notice()` 는 나라장터에서 첨부를 내려받아 추출한다. 그래서
추출 규칙을 고쳐도 **저장된 예측 파일은 그대로**이고, `scripts/evaluate_requirements.py`
가 그 파일을 읽으므로 수치도 움직이지 않는다. 이 스크립트는 이미 받아 둔 원문
(`data/public/real_rfp/<id>/`)으로 같은 일을 네트워크 없이 한다.

재추출이 건드리는 것
--------------------
요구사항 id(REQ-001…)는 **문서 순서로 다시 매겨진다.** 추출 건수가 달라지면 같은 번호가
다른 문장을 가리키게 된다. 그래서 이 스크립트는 저장 전에 옛 결과를 읽어 두고,
재추출 뒤 **원문 대조로 옛 번호 → 새 번호 대응표**를 만들어 하류 참조를 함께 고친다.

  data/public/actions/<id>.actions.json         requirement_id
  data/public/conditions/<id>.conditions.json   overrides·report 의 requirement_id
  data/public/proposals/<id>.proposal.json      문장이 인용한 requirement_id
  data/public/proposals/<id>.document.json      같음
  data/private/organizations/*/analyses/<id>/proposal.json  사내 저장본

대응을 못 찾은 참조는 **지우지 않고 그대로 두고 경고한다.** 사람이 남긴 기록을 조용히
버리는 것보다 어긋난 채로 보이는 편이 낫다 — 지우면 되돌릴 수 없다.

audit_runs 는 건드리지 않는다. 그것은 「그때 이렇게 돌았다」는 과거 실행 기록이고,
지금 문서 상태로 고쳐 쓰면 기록이 아니게 된다.

사용법
------
    python scripts/reparse_real_rfp.py --list
    python scripts/reparse_real_rfp.py g2b-R26BK01699556-000 --dry-run
    python scripts/reparse_real_rfp.py g2b-R26BK01699556-000
    python scripts/reparse_real_rfp.py --all
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.requirement import PageInfo, RfpParseResult  # noqa: E402
from app.services import document_extractor, rfp_extractor, rfp_parser  # noqa: E402

REAL_RFP_DIR = ROOT / "data" / "public" / "real_rfp"
ACTIONS_DIR = ROOT / "data" / "public" / "actions"
CONDITIONS_DIR = ROOT / "data" / "public" / "conditions"
PROPOSALS_DIR = ROOT / "data" / "public" / "proposals"
PRIVATE_ANALYSES = ROOT / "data" / "private" / "organizations"

#: 옛 요구사항과 새 요구사항을 같은 문장으로 볼 최소 유사도.
#: evaluate_requirements.py 와 같은 값을 쓴다 — 두 곳이 다르면 판단이 갈린다.
MATCH_THRESHOLD = 0.85


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _stored_document_name(notice_id: str) -> str | None:
    """저장본이 어떤 첨부로 만들어졌는지. 같은 파일로 다시 뽑아야 비교가 성립한다."""
    path = ROOT / "data" / "public" / "sample_rfp" / "generated" / f"{notice_id}.requirements.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("document")
    except (ValueError, OSError):
        return None


def _source_document(notice_id: str) -> Path | None:
    """이 공고의 제안요청서 원문.

    한 폴더에 첨부가 여럿이다(입찰공고문·제안요청서·서식…). 아무거나 고르면
    엉뚱한 문서를 재추출한다 — 실제로 입찰공고문을 읽어 「120건이 20건으로 줄었다」는
    가짜 회귀를 만들었다. 고르는 순서는:

      1) 저장본이 쓴 파일 이름과 같은 것 (있으면 무조건 이것)
      2) 「제안요청서」·「과업지시서」가 이름에 든 것
      3) 그래도 없으면 첫 문서
    """
    folder = REAL_RFP_DIR / notice_id
    if not folder.is_dir():
        return None

    candidates = [p for p in sorted(folder.iterdir()) if p.suffix.lower() in (".hwp", ".hwpx", ".pdf")]
    if not candidates:
        return None

    stored = _stored_document_name(notice_id)
    if stored:
        for path in candidates:
            # 보관 파일에는 첨부 순번이 접두어로 붙는다 ("2_제안요청서.hwp").
            if path.name == stored or path.name.endswith(f"_{stored}"):
                return path

    for keyword in ("제안요청서", "과업지시서", "제안 요청서"):
        for path in candidates:
            if keyword in path.name:
                return path
    return candidates[0]


def available_ids() -> list[str]:
    if not REAL_RFP_DIR.is_dir():
        return []
    return sorted(p.name for p in REAL_RFP_DIR.iterdir() if p.is_dir() and _source_document(p.name))


def _load_previous(notice_id: str) -> list[dict]:
    """저장돼 있던 예측. 없으면 빈 목록 (첫 추출)."""
    try:
        payload = rfp_parser.load_generated(notice_id)
    except Exception:  # noqa: BLE001 - 없거나 읽을 수 없으면 대응표만 못 만든다
        return []
    return [
        {"id": r.requirement_id, "text": getattr(r, "source_text", None) or r.content}
        for r in payload.requirements
    ]


def build_id_map(previous: list[dict], current: list) -> tuple[dict[str, str], list[str]]:
    """옛 요구사항 번호 → 새 번호. 원문이 같은 것끼리 잇는다.

    번호가 아니라 **문장**으로 잇는 이유는, 재추출로 건수가 달라지면 같은 번호가
    다른 문장을 가리키기 때문이다. 사람이 「이 조건을 처리했다」고 남긴 기록은
    번호가 아니라 그 문장에 붙어 있어야 한다.
    """
    mapping: dict[str, str] = {}
    unmatched: list[str] = []
    used: set[int] = set()

    for old in previous:
        best_score, best_index = 0.0, None
        for index, new in enumerate(current):
            if index in used:
                continue
            new_text = getattr(new, "source_text", None) or new.content
            score = _similarity(old["text"], new_text)
            if score > best_score:
                best_score, best_index = score, index
        if best_score >= MATCH_THRESHOLD and best_index is not None:
            used.add(best_index)
            mapping[old["id"]] = current[best_index].requirement_id
        else:
            unmatched.append(old["id"])
    return mapping, unmatched


def reparse(notice_id: str) -> RfpParseResult:
    """보관된 원문으로 다시 추출한다. 저장은 하지 않는다."""
    source = _source_document(notice_id)
    if source is None:
        raise FileNotFoundError(f"{notice_id}: 보관된 원문을 찾지 못했습니다 ({REAL_RFP_DIR / notice_id})")

    doc = document_extractor.extract_document(source, file_name=source.name)
    extracted = rfp_extractor.extract_with_stats(notice_id, doc)

    return RfpParseResult(
        procurement_id=notice_id,
        source=rfp_parser.REAL_NOTICE_SOURCE,
        document=doc.file_name,
        doc_format=doc.doc_format,
        page_is_approximate=doc.doc_format in ("hwp", "hwpx"),
        page_count=doc.page_count,
        pages=[PageInfo(page=p.page, char_count=p.char_count) for p in doc.pages],
        empty_pages=doc.empty_pages,
        count=len(extracted.requirements),
        candidate_count=extracted.candidate_count,
        truncated=extracted.truncated,
        requirements=extracted.requirements,
        generated_at=datetime.now(timezone.utc),
    )


def _remap_json(path: Path, mapping: dict[str, str], *, dry_run: bool) -> tuple[int, int]:
    """파일 안의 requirement_id 를 새 번호로 바꾼다. (바꾼 수, 대응 없는 수)."""
    if not path.exists():
        return 0, 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    changed = missing = 0

    def walk(node):
        nonlocal changed, missing
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "requirement_id" and isinstance(value, str) and value:
                    if value in mapping:
                        if mapping[value] != value:
                            node[key] = mapping[value]
                            changed += 1
                    else:
                        missing += 1
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    if changed and not dry_run:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed, missing


_CITATION_RE = re.compile(r"^\s*\[([^\]]{6,})\]")


def repair_proposal_citations(notice_id: str, *, dry_run: bool) -> tuple[int, int]:
    """제안서 문장이 가리키는 요구사항 번호를 **문장이 인용한 원문**으로 다시 잇는다.

    대응표(옛 파일 → 새 파일)로는 이미 깨진 것을 고칠 수 없다. 옛 파일이 사라졌기 때문이다.
    다행히 제안서 문장은 자기가 어떤 요구사항을 근거로 삼았는지 본문 앞에
    「[요구사항 원문]」 형태로 들고 있다. 그 글로 지금 요구사항을 다시 찾는다.

    (수정 수, 못 찾은 수)를 돌려준다. 못 찾은 것은 **건드리지 않는다** —
    엉뚱한 번호를 새로 붙이는 것보다 어긋난 채 두고 사람이 보는 편이 낫다.
    """
    try:
        parsed = rfp_parser.load_generated(notice_id)
    except Exception:  # noqa: BLE001
        return 0, 0
    current = [(r.requirement_id, r.content) for r in parsed.requirements]

    fixed = missing = 0
    paths = [
        PROPOSALS_DIR / f"{notice_id}.proposal.json",
        PROPOSALS_DIR / f"{notice_id}.document.json",
    ]
    if PRIVATE_ANALYSES.is_dir():
        paths.extend(sorted(PRIVATE_ANALYSES.glob(f"*/analyses/{notice_id}/proposal*.json")))

    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for sentence in payload.get("sentences", []):
            text = sentence.get("text") or ""
            match = _CITATION_RE.match(text)
            if not match:
                continue
            cited = match.group(1).rstrip("…").strip()
            best_score, best_id = 0.0, None
            for rid, content in current:
                score = _similarity(cited, content[: len(cited) + 8])
                if score > best_score:
                    best_score, best_id = score, rid
            if best_score < MATCH_THRESHOLD or best_id is None:
                missing += 1
                continue
            if sentence.get("requirement_id") != best_id:
                sentence["requirement_id"] = best_id
                fixed += 1
                changed = True
        if changed and not dry_run:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return fixed, missing


def run(notice_id: str, *, dry_run: bool) -> None:
    previous = _load_previous(notice_id)
    result = reparse(notice_id)

    mapping, unmatched = build_id_map(previous, result.requirements)
    print(f"[{notice_id}]")
    print(f"  요구사항  {len(previous)}건 → {len(result.requirements)}건 (후보 {result.candidate_count})")
    if result.truncated:
        print(f"  ! 상한 {rfp_extractor.MAX_REQUIREMENTS}건에 잘렸습니다 — 뒤쪽 항목이 빠집니다")
    print(f"  옛 번호 대응  {len(mapping)}건 · 대응 못 찾음 {len(unmatched)}건")
    if unmatched:
        print(f"    대응 못 찾은 옛 번호: {', '.join(unmatched[:8])}{' …' if len(unmatched) > 8 else ''}")

    # 제안서를 빠뜨리면 문장이 엉뚱한 요구사항을 가리킨 채 화면에 나온다.
    # 실측: 재추출 뒤 18문장 중 4문장이 다른 요구사항을 인용하고 있었다
    # (REQ-010 이 「교육용 계정 운영·관리」를 인용하는데 지금 REQ-010 은 다른 문장).
    targets = [
        ACTIONS_DIR / f"{notice_id}.actions.json",
        CONDITIONS_DIR / f"{notice_id}.conditions.json",
        PROPOSALS_DIR / f"{notice_id}.proposal.json",
        PROPOSALS_DIR / f"{notice_id}.document.json",
    ]
    # 사내 저장본(조직별)도 같은 참조를 들고 있다.
    if PRIVATE_ANALYSES.is_dir():
        targets.extend(sorted(PRIVATE_ANALYSES.glob(f"*/analyses/{notice_id}/*.json")))

    for path in targets:
        changed, missing = _remap_json(path, mapping, dry_run=dry_run)
        if changed or missing:
            note = f"  {path.name}: {changed}건 갱신"
            if missing:
                note += f" · 대응 없는 참조 {missing}건은 **그대로 두었습니다** (사람이 확인해야 합니다)"
            print(note)

    fixed, missing = repair_proposal_citations(notice_id, dry_run=dry_run)
    if fixed or missing:
        note = f"  제안서 인용 재연결: {fixed}건 수정"
        if missing:
            note += f" · 원문을 못 찾은 {missing}건은 **그대로 두었습니다**"
        print(note)

    if dry_run:
        print("  (미리보기 — 저장하지 않았습니다)")
        return
    stored = rfp_parser.store_result(result)
    print(f"  저장 완료: {stored.count}건")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("notice_id", nargs="?", help="재추출할 공고 id")
    parser.add_argument("--all", action="store_true", help="보관된 원문 전부")
    parser.add_argument("--list", action="store_true", help="보관된 원문 목록만 보여준다")
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 결과만 보여준다")
    args = parser.parse_args()

    ids = available_ids()
    if args.list:
        print(f"보관된 원문 {len(ids)}건:")
        for notice_id in ids:
            print(f"  {notice_id}  ({_source_document(notice_id).name})")
        return 0

    targets = ids if args.all else ([args.notice_id] if args.notice_id else [])
    if not targets:
        parser.error("공고 id 를 지정하거나 --all 을 쓰세요 (--list 로 목록 확인)")

    for notice_id in targets:
        try:
            run(notice_id, dry_run=args.dry_run)
        except FileNotFoundError as exc:
            print(f"[{notice_id}] 건너뜀 — {exc}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
