#!/usr/bin/env python
"""추출 규칙을 고칠 때마다 P/R 을 바로 잰다 (0917.md §4-4).

## 왜 필요한가

`evaluate_requirements.py` 는 **저장된 결과 파일**을 정답셋과 대조한다. 그래서 규칙을 고친
효과를 보려면 먼저 공고를 다시 파싱해 파일을 덮어써야 하는데, 그 파일은 git 이 추적하고
시연이 그 숫자에 걸려 있다. 규칙을 한 줄 고칠 때마다 시연 자료를 흔들 수는 없다.

이 스크립트는 **저장하지 않고** 잰다. 첨부 원본을 열어 지금 코드로 추출하고, 그 결과를
메모리에서 정답셋과 대조한다. 작업 트리는 그대로다.

    python scripts/measure_extraction.py                 # 정답셋이 있는 공고 전부
    python scripts/measure_extraction.py --only g2b-R26BK01699556-000
    python scripts/measure_extraction.py --missed         # 못 찾은 항목의 원문도 출력

`--save-baseline` 으로 지금 값을 기록해 두면, 다음 실행에서 **변화량**을 함께 보여 준다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services import document_extractor, rfp_extractor  # noqa: E402

# 채점은 **공식 채점기와 같은 함수**로 한다. 예전에는 여기서 따로 「부분 문자열이면 맞힘」으로
# 셌는데, docstring 은 「evaluate_requirements.py 와 같은 느슨한 대조」라고 적어 두었다.
# 실제로는 더 **엄격했다** — 공식 채점기는 포함 비율이나 difflib 유사도가 0.85 이상이면
# 맞힘으로 보고 1:1 로 짝짓는다. 그래서 같은 추출 결과를 두고 이 스크립트는 가천대 맞힘을
# 58건, 공식 채점기는 61건으로 셌다(P 0.75 대 0.80). 규칙을 고치며 보는 숫자가 보고서에
# 적히는 숫자보다 낮으면, 이미 기준을 넘은 개선을 「아직 멀었다」로 오해하게 된다.
import evaluate_requirements as official  # noqa: E402

GOLD_DIR = ROOT / "data" / "public" / "sample_rfp"
ATTACH_DIR = ROOT / "data" / "public" / "real_rfp"
BASELINE = ROOT / "docs" / "reports" / ".extraction_baseline.json"

#: 정답셋 파일 → (공고 id, 첨부를 고르는 방법)
GOLD_FILES = {
    "g2b-R26BK01699556-000": "gold_requirements.g2b-R26BK01699556-000.json",
    "g2b-R26BK01718593-000": "gold_requirements.g2b-R26BK01718593-000.json",
}


def gold_items(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("requirements") if isinstance(payload, dict) else payload
    return [i for i in (items or []) if isinstance(i, dict)]


def pick_attachment(procurement_id: str, document_hint: str | None = None) -> Path | None:
    """정답셋이 검수한 그 문서를 연다. 공고문(PDF)이 아니라 제안요청서·과업지시서다."""
    folder = ATTACH_DIR / procurement_id
    if not folder.exists():
        return None
    files = sorted(p for p in folder.iterdir() if p.is_file())
    if not files:
        return None
    if document_hint:
        stem = normalize(Path(document_hint).stem)
        for path in files:
            if stem and (stem in normalize(path.stem) or normalize(path.stem) in stem):
                return path
    # 파일명에 「제안요청」·「과업」이 있으면 그것이다. 없으면 가장 큰 파일.
    # 정답셋이 어느 문서를 검수한 것인지는 gold 파일의 `document` 가 말한다.
    # 같은 공고에 제안요청서와 과업지시서가 함께 오는 경우가 있어, 이름이 다른 쪽을 열면
    # 맞힘이 0 이 된다(실제로 그랬다).
    for keyword in ("제안요청", "과업지시", "과업내용"):
        for path in files:
            if keyword in path.name:
                return path
    return max(files, key=lambda p: p.stat().st_size)


def normalize(text: str) -> str:
    return "".join(ch for ch in (text or "") if not ch.isspace())


def as_record(draft, index: int, procurement_id: str) -> dict:
    """추출 결과 한 건을 채점기가 읽는 모양(저장 파일의 항목)으로 옮긴다."""
    return {
        "requirement_id": f"REQ-{index:03d}",
        "procurement_id": procurement_id,
        "content": getattr(draft, "content", "") or "",
        "source_text": " ".join(getattr(draft, "source_lines", []) or [])
        or (getattr(draft, "content", "") or ""),
        "page": getattr(draft, "page", None),
        "status": "unmatched",
    }


def score(predicted: list, gold: list[dict], procurement_id: str = "") -> dict:
    """공식 채점기(`evaluate_requirements.evaluate`)에 그대로 먹인다.

    저장 파일을 만들지 않는 것이 이 스크립트의 존재 이유이므로, 파일 대신 **같은 모양의
    딕셔너리**를 만들어 넘긴다. 채점 규칙은 한 벌만 둔다 — 두 벌이면 반드시 갈라진다.
    """
    preds = [as_record(draft, i, procurement_id) for i, draft in enumerate(predicted, 1)]
    golds = [g for g in gold if normalize(g.get("source_text") or g.get("content") or "")]
    report = official.evaluate({"requirements": preds}, {"requirements": golds})
    missed_ids = set(report.unmatched_gold_ids)
    return {
        "predicted": report.predicted_count,
        "gold": report.gold_count,
        "hit": report.true_positives,
        "precision": round(report.precision, 4),
        "recall": round(report.recall, 4),
        "f1": round(report.f1, 4),
        "missed": [g for g in golds if g.get("requirement_id") in missed_ids],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="공고 id 하나만")
    parser.add_argument("--missed", action="store_true", help="못 찾은 항목의 원문도 출력")
    parser.add_argument("--save-baseline", action="store_true", help="지금 값을 기준선으로 저장")
    args = parser.parse_args()

    baseline = {}
    if BASELINE.exists():
        try:
            baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        except ValueError:
            baseline = {}

    results = {}
    for procurement_id, gold_name in GOLD_FILES.items():
        if args.only and args.only != procurement_id:
            continue
        gold_path = GOLD_DIR / gold_name
        if not gold_path.exists():
            print(f"{procurement_id}: 정답셋 없음 ({gold_name})")
            continue
        gold_payload = json.loads(gold_path.read_text(encoding="utf-8"))
        hint = gold_payload.get("document") if isinstance(gold_payload, dict) else None
        attachment = pick_attachment(procurement_id, hint)
        if attachment is None:
            print(f"{procurement_id}: 첨부 원본 없음 ({ATTACH_DIR / procurement_id})")
            continue

        doc = document_extractor.extract_document(attachment)
        drafts = rfp_extractor.extract_requirements_from_document(procurement_id, doc)
        outcome = score(list(drafts), gold_items(gold_path), procurement_id)
        results[procurement_id] = {k: v for k, v in outcome.items() if k != "missed"}

        before = baseline.get(procurement_id) or {}
        def delta(key: str) -> str:
            if key not in before:
                return ""
            change = outcome[key] - before[key]
            if abs(change) < 0.0005:
                return "  (변화 없음)"
            return f"  ({'+' if change > 0 else ''}{change:.4f})"

        print(f"\n== {procurement_id}  [{attachment.name}]")
        print(f"   예측 {outcome['predicted']}건 · 정답 {outcome['gold']}건 · 맞힘 {outcome['hit']}건")
        print(f"   Precision {outcome['precision']:.4f}{delta('precision')}")
        print(f"   Recall    {outcome['recall']:.4f}{delta('recall')}")
        print(f"   F1        {outcome['f1']:.4f}{delta('f1')}")

        if args.missed:
            print(f"   못 찾은 {len(outcome['missed'])}건:")
            for item in outcome["missed"]:
                text = (item.get("source_text") or item.get("content") or "").strip()
                print(f"     p{item.get('page')} {text[:88]}")

    if args.save_baseline and results:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n기준선 저장: {BASELINE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
