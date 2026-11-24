"""실제 제안요청서로 Gold Requirement Set을 만들기 위한 검수 작업지 생성기.

왜 필요한가
    합성 RFP(synthetic-rfp-0001)는 파서와 함께 만든 문서라, 그것으로 잰
    Precision/Recall은 자기 자신을 채점한 값이다. 실제 공고에서 재려면
    사람이 만든 정답셋이 있어야 한다 (CLAUDE.md 17).

무엇을 만드는가
    문서에서 "요구사항 후보가 될 수 있는 줄"을 **추출기 판정과 무관하게** 전부 모아
    작업지로 낸다. 담당자는 각 줄에 O/X만 표시하면 된다.
    - 추출기가 뽑은 줄(extracted=true)에 X  -> 오탐 (Precision 하락)
    - 추출기가 빠뜨린 줄(extracted=false)에 O -> 미탐 (Recall 하락)

    후보 풀을 추출기 결과로 한정하지 않기 때문에 Recall도 정직하게 잴 수 있다.

사용
    python scripts/build_gold_worksheet.py g2b-R26BK01699556-000
    (검수 후) python scripts/build_gold_worksheet.py g2b-R26BK01699556-000 --to-gold
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services import document_extractor, rfp_extractor  # noqa: E402

RFP_DIR = REPO_ROOT / "data" / "public" / "real_rfp"
GOLD_DIR = REPO_ROOT / "data" / "public" / "sample_rfp"
WORKSHEET_DIR = GOLD_DIR / "worksheets"

# 후보로 볼 최소 한글 길이. 이보다 짧으면 표 머리글·번호 조각이다.
MIN_CANDIDATE_CHARS = 10


def source_file(procurement_id: str) -> Path:
    folder = RFP_DIR / procurement_id
    if not folder.is_dir():
        raise SystemExit(f"내려받은 제안요청서가 없습니다: {folder}")
    files = [f for f in folder.iterdir() if f.is_file()]
    if not files:
        raise SystemExit(f"폴더가 비어 있습니다: {folder}")
    return files[0]


def build(procurement_id: str) -> dict:
    path = source_file(procurement_id)
    doc = document_extractor.extract_document(path, file_name=path.name)
    extracted = rfp_extractor.extract_with_stats(procurement_id, doc)

    # 추출기가 실제로 담은 본문(정규화 기준)
    taken = {rfp_extractor._normalize(r.content) for r in extracted.requirements}

    rows: list[dict] = []
    seen: set[str] = set()
    for line in rfp_extractor._iter_lines(doc):
        if rfp_extractor._is_noise(line.raw):
            continue
        body = line.body.strip()
        hangul = sum(1 for ch in body if "가" <= ch <= "힣")
        if hangul < MIN_CANDIDATE_CHARS:
            continue
        key = rfp_extractor._normalize(body)
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "line_id": f"L-{len(rows) + 1:03d}",
                "page": line.page,
                "text": body,
                "raw": line.raw,
                # 추출기가 이 줄을 요구사항으로 담았는지 (참고용, 정답이 아니다)
                "extracted": key in taken,
                # 담당자가 채울 칸: true = 제안서가 대응해야 할 요구사항
                "is_requirement": None,
            }
        )

    # 추출기가 담은 요구사항은 **전부** 작업지에 있어야 Precision을 잴 수 있다.
    # 줄 후보 풀에서 빠지는 경우가 있다 — 한글 길이가 짧거나(REQ-010 "교육용 계정 운영·관리"),
    # 여러 줄을 이어붙여 만든 요구사항(REQ-030)은 단일 줄과 일치하지 않는다.
    for requirement in extracted.requirements:
        key = rfp_extractor._normalize(requirement.content)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "line_id": f"L-{len(rows) + 1:03d}",
                "page": requirement.page,
                "text": requirement.content,
                "raw": requirement.source_text,
                "extracted": True,
                "is_requirement": None,
            }
        )
    rows.sort(key=lambda r: (r["page"] or 0, r["line_id"]))

    return {
        "_note": (
            "Gold Requirement Set 검수 작업지. is_requirement 에 true/false 를 채우세요. "
            "extracted 는 추출기 판정이며 정답이 아닙니다."
        ),
        "procurement_id": procurement_id,
        "document": doc.file_name,
        "page_count": doc.page_count,
        "candidate_count": len(rows),
        "extracted_count": len(extracted.requirements),
        "rows": rows,
    }


def to_gold(procurement_id: str) -> None:
    """검수가 끝난 작업지를 gold 형식으로 변환한다."""
    worksheet_path = WORKSHEET_DIR / f"{procurement_id}.worksheet.json"
    if not worksheet_path.exists():
        raise SystemExit(f"작업지가 없습니다: {worksheet_path}")
    sheet = json.loads(worksheet_path.read_text(encoding="utf-8"))

    unlabeled = [r for r in sheet["rows"] if r.get("is_requirement") is None]
    if unlabeled:
        raise SystemExit(
            f"아직 표시하지 않은 줄이 {len(unlabeled)}건 있습니다 "
            f"(첫 항목 {unlabeled[0]['line_id']}). 전부 채운 뒤 다시 실행하세요."
        )

    picked = [r for r in sheet["rows"] if r["is_requirement"]]
    gold = {
        "_note": "사람이 검수한 Gold Requirement Set. 추출 평가에만 사용한다.",
        "procurement_id": procurement_id,
        "document": sheet["document"],
        "page_count": sheet["page_count"],
        "requirements": [
            {
                "id": f"gold-{procurement_id}-{index:03d}",
                "procurement_id": procurement_id,
                "requirement_id": f"REQ-{index:03d}",
                "category": "미분류",
                "requirement_type": "mandatory",
                "content": row["text"],
                "page": row["page"],
                "source_text": row["raw"],
                "status": "unmatched",
            }
            for index, row in enumerate(picked, start=1)
        ],
    }
    target = GOLD_DIR / f"gold_requirements.{procurement_id}.json"
    target.write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"gold {len(picked)}건 저장: {target.relative_to(REPO_ROOT)}")
    print("평가:")
    print(
        f"  python scripts/evaluate_requirements.py "
        f"--predicted data/public/sample_rfp/generated/{procurement_id}.requirements.json "
        f"--gold {target.relative_to(REPO_ROOT).as_posix()}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("procurement_id")
    parser.add_argument("--to-gold", action="store_true", help="검수된 작업지를 gold로 변환")
    args = parser.parse_args()

    if args.to_gold:
        to_gold(args.procurement_id)
        return

    sheet = build(args.procurement_id)
    WORKSHEET_DIR.mkdir(parents=True, exist_ok=True)
    json_path = WORKSHEET_DIR / f"{args.procurement_id}.worksheet.json"
    json_path.write_text(json.dumps(sheet, ensure_ascii=False, indent=2), encoding="utf-8")

    # 읽기 쉬운 표도 함께 낸다 (검수는 JSON에 한다).
    md_lines = [
        f"# Gold 검수 작업지 — {args.procurement_id}",
        "",
        f"- 문서: {sheet['document']} ({sheet['page_count']}페이지)",
        f"- 후보 줄: {sheet['candidate_count']}건",
        f"- 추출기가 담은 것: {sheet['extracted_count']}건",
        "",
        "`추출` 열은 추출기 판정이며 **정답이 아닙니다**. 각 줄이 제안서가 대응해야 할",
        "요구사항이면 O, 아니면 X 로 판단해 JSON의 `is_requirement`를 채우세요.",
        "",
        "| ID | p | 추출 | 내용 |",
        "| --- | --- | --- | --- |",
    ]
    for row in sheet["rows"]:
        text = row["text"].replace("|", "\\|")[:110]
        md_lines.append(f"| {row['line_id']} | {row['page']} | {'O' if row['extracted'] else ''} | {text} |")
    md_path = WORKSHEET_DIR / f"{args.procurement_id}.worksheet.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"후보 {sheet['candidate_count']}건 (추출기가 담은 것 {sheet['extracted_count']}건)")
    print(f"  검수용 JSON : {json_path.relative_to(REPO_ROOT)}")
    print(f"  읽기용 표   : {md_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
