"""scripts/evaluate_requirements.py 평가 로직 단위 테스트 (gold 파일과 무관한 합성 입력)."""

import importlib.util
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_requirements.py"
spec = importlib.util.spec_from_file_location("evaluate_requirements", SCRIPT)
assert spec is not None and spec.loader is not None
ev = importlib.util.module_from_spec(spec)
# dataclass가 문자열 타입 힌트를 해석하려면 모듈이 sys.modules에 있어야 한다.
sys.modules[spec.name] = ev
spec.loader.exec_module(ev)

SENTENCE_A = "계약상대자는 첫 교육일 10일 전까지 세부 커리큘럼, 교안, 실습파일을 제출해 발주기관의 승인을 받아야 한다."
SENTENCE_B = "교육은 총 12회 운영해야 하며, 회차당 교육시간은 최소 3시간으로 한다."


def gold(rid: str, text: str, page: int = 2, status: str = "unmatched") -> dict[str, Any]:
    return {"requirement_id": rid, "source_text": text, "page": page, "status": status}


def pred(
    rid: str,
    text: str,
    page: int = 2,
    status: str = "unmatched",
    content: str | None = None,
) -> dict[str, Any]:
    return {
        "requirement_id": rid,
        "source_text": text,
        "content": text if content is None else content,
        "page": page,
        "status": status,
    }


def run(preds: list[dict[str, Any]], golds: list[dict[str, Any]]) -> Any:
    return ev.evaluate({"requirements": preds}, {"page_count": 6, "requirements": golds})


def test_exact_match_gives_perfect_scores() -> None:
    report = run([pred("REQ-001", SENTENCE_A), pred("REQ-002", SENTENCE_B)],
                 [gold("REQ-001", SENTENCE_A), gold("REQ-002", SENTENCE_B)])
    assert (report.true_positives, report.precision, report.recall, report.f1) == (2, 1.0, 1.0, 1.0)
    assert report.page_agreement == 2 and report.status_agreement == 2


def test_label_prefix_in_source_text_still_matches_via_content() -> None:
    p = pred("REQ-001", f"사전승인 [제출] {SENTENCE_A}", content=SENTENCE_A)
    report = run([p], [gold("REQ-001", SENTENCE_A)])
    assert report.true_positives == 1


def test_fragments_and_empty_text_do_not_match() -> None:
    report = run(
        [pred("REQ-001", "한다."), pred("REQ-002", " "), pred("REQ-003", "제출해야 한다.")],
        [gold("REQ-001", SENTENCE_A), gold("REQ-002", SENTENCE_B)],
    )
    assert report.true_positives == 0
    assert report.precision == 0.0 and report.recall == 0.0
    assert report.unmatched_gold_ids == ["REQ-001", "REQ-002"]


def test_one_prediction_matches_at_most_one_gold() -> None:
    report = run([pred("REQ-001", SENTENCE_A)],
                 [gold("REQ-001", SENTENCE_A), gold("REQ-002", SENTENCE_A)])
    assert report.true_positives == 1
    assert report.precision == 1.0 and report.recall == 0.5


def test_tie_break_prefers_earlier_prediction() -> None:
    report = run([pred("REQ-001", SENTENCE_A), pred("REQ-002", SENTENCE_A)],
                 [gold("REQ-001", SENTENCE_A)])
    assert [m.predicted_id for m in report.matches] == ["REQ-001"]
    assert report.unmatched_predicted_ids == ["REQ-002"]


def test_page_and_status_disagreement_is_reported_not_penalized() -> None:
    report = run([pred("REQ-001", SENTENCE_A, page=3, status="check")],
                 [gold("REQ-001", SENTENCE_A, page=2, status="unmatched")])
    assert report.true_positives == 1
    assert report.page_agreement == 0 and report.status_agreement == 0


def test_missing_page_and_out_of_range_are_counted() -> None:
    report = run(
        [
            {"requirement_id": "REQ-001", "source_text": SENTENCE_A, "content": SENTENCE_A, "page": None},
            pred("REQ-002", SENTENCE_B, page=9),
        ],
        [gold("REQ-001", SENTENCE_A), gold("REQ-002", SENTENCE_B)],
    )
    assert report.missing_page == 1
    assert report.page_out_of_range == 1
