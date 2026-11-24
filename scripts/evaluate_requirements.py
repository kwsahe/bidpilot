"""추출된 Requirement를 gold 정답셋과 비교해 Precision / Recall을 계산한다.

사용:
    python scripts/evaluate_requirements.py
    python scripts/evaluate_requirements.py --json out.json

- gold_requirements.json은 여기서만 읽는다 (파서 입력으로 사용하지 않는다).
- 매칭 기준: 공백을 제거한 gold source_text와 예측 source_text/content를 비교해,
  한쪽이 다른 쪽을 포함하면 (짧은 길이 / 긴 길이) 비율을, 아니면 difflib 유사도를 점수로 쓴다.
  점수가 임계값 이상인 쌍만 후보이며, 점수 높은 순으로 1:1 매칭한다 (동점이면 앞선 항목 우선).
  짧은 조각("한다.")이나 빈 문자열은 비율이 낮아 매칭되지 않는다.
- 모든 수치는 실제 파일에서 계산한다. 하드코딩된 성과 수치는 없다.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RFP_DIR = REPO_ROOT / "data" / "public" / "sample_rfp"
DEFAULT_PREDICTED = SAMPLE_RFP_DIR / "generated" / "synthetic-rfp-0001.requirements.json"
DEFAULT_GOLD = SAMPLE_RFP_DIR / "gold_requirements.json"
SIMILARITY_THRESHOLD = 0.85


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def containment_coverage(a: str, b: str) -> float:
    """한쪽이 다른 쪽을 포함하면 길이 비율(짧은 쪽/긴 쪽), 아니면 0. 빈 문자열은 0."""
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b))
    return 0.0


def match_score(pred: dict[str, Any], gold: dict[str, Any]) -> float:
    """예측-정답 쌍의 일치 점수 (0~1). source_text와 content 중 높은 쪽."""
    gold_text = normalize(gold.get("source_text", ""))
    best = 0.0
    for field in ("source_text", "content"):
        pred_text = normalize(pred.get(field, ""))
        best = max(
            best,
            containment_coverage(pred_text, gold_text),
            similarity(pred_text, gold_text),
        )
    return best


@dataclass
class Match:
    gold_id: str
    predicted_id: str
    score: float
    page_match: bool
    status_match: bool


@dataclass
class Report:
    predicted_count: int
    gold_count: int
    true_positives: int
    precision: float
    recall: float
    f1: float
    missing_page: int
    missing_source_text: int
    page_out_of_range: int
    page_agreement: int
    status_agreement: int
    unmatched_gold_ids: list[str]
    unmatched_predicted_ids: list[str]
    matches: list[Match]
    # 문서 형식 (pdf / hwp / hwpx / None) — 형식별 성능을 나눠 보기 위해 예측 파일에서 옮긴다.
    doc_format: str | None = None
    # 항목 유형별 집계 (gold에 item_type이 있을 때만 recall을 계산한다. 없으면 예측 분포만 담는다).
    by_item_type: dict[str, dict[str, Any]] | None = None
    # 항목 유형 일치 (gold·예측 둘 다 item_type이 있는 매칭 쌍 기준)
    item_type_agreement: int | None = None


def evaluate(predicted: dict[str, Any], gold: dict[str, Any]) -> Report:
    preds: list[dict[str, Any]] = predicted["requirements"]
    golds: list[dict[str, Any]] = gold["requirements"]
    page_count = int(gold.get("page_count") or predicted.get("page_count") or 0)

    # 모든 쌍의 점수를 계산한 뒤 점수 높은 순으로 1:1 greedy 매칭 (동점이면 앞선 gold/예측 우선)
    pairs: list[tuple[float, int, int]] = []
    for gi, g in enumerate(golds):
        for pi, p in enumerate(preds):
            score = match_score(p, g)
            if score >= SIMILARITY_THRESHOLD:
                pairs.append((score, gi, pi))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))

    used_gold: set[int] = set()
    used_pred: set[int] = set()
    matches: list[Match] = []
    for score, gi, pi in pairs:
        if gi in used_gold or pi in used_pred:
            continue
        used_gold.add(gi)
        used_pred.add(pi)
        g, p = golds[gi], preds[pi]
        matches.append(
            Match(
                gold_id=g["requirement_id"],
                predicted_id=p["requirement_id"],
                score=round(score, 3),
                page_match=g.get("page") == p.get("page"),
                status_match=g.get("status") == p.get("status"),
            )
        )
    matches.sort(key=lambda m: m.gold_id)

    tp = len(matches)
    precision = tp / len(preds) if preds else 0.0
    recall = tp / len(golds) if golds else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    # 항목 유형별 집계 — 예측 분포는 항상, recall은 gold에 item_type이 있을 때만.
    pred_by_id = {p["requirement_id"]: p for p in preds}
    gold_by_id = {g["requirement_id"]: g for g in golds}
    by_type: dict[str, dict[str, Any]] = {}
    for p in preds:
        key = str(p.get("item_type") or "REQUIREMENT")
        by_type.setdefault(key, {"predicted": 0, "gold": 0, "matched": 0, "recall": None})["predicted"] += 1
    gold_has_type = any(g.get("item_type") for g in golds)
    if gold_has_type:
        for g in golds:
            key = str(g.get("item_type") or "REQUIREMENT")
            by_type.setdefault(key, {"predicted": 0, "gold": 0, "matched": 0, "recall": None})["gold"] += 1
        for m in matches:
            key = str(gold_by_id[m.gold_id].get("item_type") or "REQUIREMENT")
            by_type.setdefault(key, {"predicted": 0, "gold": 0, "matched": 0, "recall": None})["matched"] += 1
        for entry in by_type.values():
            entry["recall"] = round(entry["matched"] / entry["gold"], 4) if entry["gold"] else None
    type_agreement = None
    if gold_has_type:
        type_agreement = sum(
            1 for m in matches
            if gold_by_id[m.gold_id].get("item_type") and pred_by_id[m.predicted_id].get("item_type") == gold_by_id[m.gold_id].get("item_type")
        )

    return Report(
        predicted_count=len(preds),
        gold_count=len(golds),
        true_positives=tp,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        doc_format=predicted.get("doc_format"),
        by_item_type=by_type,
        item_type_agreement=type_agreement,
        missing_page=sum(1 for p in preds if p.get("page") is None),
        missing_source_text=sum(1 for p in preds if not (p.get("source_text") or "").strip()),
        page_out_of_range=sum(
            1 for p in preds
            if p.get("page") is not None and not (1 <= p["page"] <= page_count)
        ),
        page_agreement=sum(1 for m in matches if m.page_match),
        status_agreement=sum(1 for m in matches if m.status_match),
        unmatched_gold_ids=[g["requirement_id"] for i, g in enumerate(golds) if i not in used_gold],
        unmatched_predicted_ids=[p["requirement_id"] for i, p in enumerate(preds) if i not in used_pred],
        matches=matches,
    )


def _display_path(path: Path) -> str:
    """저장소 기준 상대경로로 보여준다. 밖의 경로면 절대경로 그대로 쓴다."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def print_report(report: Report, predicted_path: Path, gold_path: Path) -> None:
    print(f"predicted : {_display_path(predicted_path)}")
    print(f"gold      : {_display_path(gold_path)}")
    print(f"doc_format: {report.doc_format or '(fixture pdf)'}")
    print()
    print(f"요구사항 수        predicted={report.predicted_count}  gold={report.gold_count}")
    print(f"page 누락          {report.missing_page}")
    print(f"source_text 누락   {report.missing_source_text}")
    print(f"page 범위 이탈     {report.page_out_of_range}")
    print()
    print(f"True positives     {report.true_positives}")
    print(f"Precision          {report.precision:.4f}")
    print(f"Recall             {report.recall:.4f}")
    print(f"F1                 {report.f1:.4f}")
    print(f"page 일치          {report.page_agreement}/{report.true_positives}")
    print(f"status 일치        {report.status_agreement}/{report.true_positives} (참고용)")
    print()
    if report.by_item_type:
        print("항목 유형별        (predicted / gold / matched / recall)")
        for key in sorted(report.by_item_type):
            entry = report.by_item_type[key]
            recall = f"{entry['recall']:.4f}" if entry["recall"] is not None else "gold에 유형 없음"
            print(f"  {key:18} {entry['predicted']:>3} / {entry['gold']:>3} / {entry['matched']:>3} / {recall}")
        if report.item_type_agreement is not None:
            print(f"item_type 일치     {report.item_type_agreement}/{report.true_positives}")
        print()
    print(f"미탐지 gold        {report.unmatched_gold_ids or '없음'}")
    print(f"gold 없는 예측     {report.unmatched_predicted_ids or '없음'}")
    print()
    print("matches (gold → predicted, score, page, status)")
    for m in report.matches:
        flags = f"page={'ok' if m.page_match else 'DIFF'} status={'ok' if m.status_match else 'diff'}"
        print(f"  {m.gold_id} → {m.predicted_id}  {m.score:.3f}  {flags}")


def gold_pairs() -> list[tuple[Path, Path]]:
    """저장소의 gold 파일마다 짝이 되는 예측 파일. gold_requirements.json은 합성 fixture 것이다."""
    pairs: list[tuple[Path, Path]] = []
    for gold in sorted(SAMPLE_RFP_DIR.glob("gold_requirements*.json")):
        name = gold.name
        if name == "gold_requirements.json":
            predicted = DEFAULT_PREDICTED
        else:
            procurement_id = name[len("gold_requirements."):-len(".json")]
            predicted = SAMPLE_RFP_DIR / "generated" / f"{procurement_id}.requirements.json"
        pairs.append((predicted, gold))
    return pairs


def run_all(json_dir: Path | None) -> None:
    """모든 gold 세트를 평가하고 형식별 요약을 출력한다."""
    rows: list[tuple[str, str, Report]] = []
    for predicted, gold in gold_pairs():
        if not predicted.exists():
            print(f"[건너뜀] 예측 파일 없음: {_display_path(predicted)}")
            continue
        report = evaluate(json.loads(predicted.read_text(encoding="utf-8")), json.loads(gold.read_text(encoding="utf-8")))
        rows.append((gold.name, _display_path(predicted), report))
        if json_dir:
            json_dir.mkdir(parents=True, exist_ok=True)
            (json_dir / f"{gold.stem}.report.json").write_text(
                json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8"
            )
    print("gold 세트별 요약 (doc_format · predicted/gold · P · R · F1 · page 일치)")
    for gold_name, predicted_label, report in rows:
        print(
            f"  {gold_name:48} {str(report.doc_format or 'pdf'):5} {report.predicted_count:>3}/{report.gold_count:<3} "
            f"P {report.precision:.3f}  R {report.recall:.3f}  F1 {report.f1:.3f}  page {report.page_agreement}/{report.true_positives}"
        )
        print(f"      ← {predicted_label}")
    if json_dir:
        print(f"\nsaved: {json_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--predicted", type=Path, default=DEFAULT_PREDICTED)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--json", type=Path, default=None, help="결과를 JSON으로 저장할 경로")
    parser.add_argument("--all", action="store_true", help="저장소의 모든 gold 세트를 평가하고 형식별로 요약한다")
    parser.add_argument("--json-dir", type=Path, default=None, help="--all 결과 JSON을 저장할 디렉터리")
    args = parser.parse_args()

    if args.all:
        run_all(args.json_dir)
        return

    if not args.predicted.exists():
        raise SystemExit(
            f"예측 파일이 없습니다: {args.predicted}\n"
            "먼저 POST /api/rfp/parse 를 호출하거나 backend 테스트를 실행해 생성하세요."
        )

    predicted = json.loads(args.predicted.read_text(encoding="utf-8"))
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    report = evaluate(predicted, gold)
    print_report(report, args.predicted, args.gold)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nsaved: {args.json}")


if __name__ == "__main__":
    main()
