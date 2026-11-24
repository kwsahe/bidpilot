"""실제 HWP 제안요청서 추출 품질을 «지금 코드»로 재고 고정한다.

`scripts/evaluate_requirements.py` 는 **저장된 예측 파일**을 읽는다. 그래서 추출기를 고쳐도
그 스크립트의 숫자는 재추출 전까지 움직이지 않는다 — 개선했는지 확인하려면 코드를 직접 돌려야 한다.
이 테스트가 그 역할을 한다.

기준선(2026-09-10, 개선 전):

    N=30  gold=83  TP=24   P 0.800  R 0.289  F1 0.425  page 24/24

개선 후(2026-09-10):

    N=56  gold=83  TP=46   P 0.821  R 0.554  F1 0.662  page 46/46

절·어미 규칙 보강 후(2026-09-17, 0917.md §4-4):

    N=76  gold=83  TP=61   P 0.803  R 0.735  page 61/61

    무엇을 바꿨나: 번호 없는 낱말은 절을 닫지 않는다 · 끝의 괄호 주석은 어미가 아니다 ·
    평가 절에서만 「~성·~도·~력」을 인정한다 · 「기술」과 「명단/서류/자료 등」을 조건 어미에
    더한다 · 절을 연 줄 자체는 제목이므로 항목으로 내보내지 않는다.

    남은 오차의 성격: 정답에 없던 예측 15건을 전부 눈으로 봤더니 대부분이 «정답셋이 빠뜨린
    진짜 요구사항»이었다(교육과정 기획·운영, 계약 해지 사유, 대금 지급 조건, 참여인력 현황).
    그래서 여기 적힌 precision 은 실제 정확도의 «하한»이다. 다만 그 판단은 사람이 정답셋을
    다시 검수해야 확정되므로, 수치는 지금 정답셋 기준 그대로 둔다.

평가표 칸 항목화 후(2026-09-20, 0919.md §4-B-5):

    N=88  gold=83  TP=70   P 0.795  R 0.843  page 70/70

    무엇을 바꿨나: 평가·배점 절 안에서만 표의 칸을 나눠 항목으로 인정한다. 배점표의
    평가요소는 어미가 없는 명사구라 어떤 어미 규칙에도 걸리지 않았다.
    서식(별지) 본문이 시작되면 평가 절을 닫는다 — 닫지 않으면 양식의 빈 칸 이름
    (「회사 설립 년도」·「사업자 등록번호」) 14개가 요구사항으로 올라와 P 가 0.68 로 떨어진다.

    정밀도는 0.803 → 0.795 로 조금 내려갔고(§4-B-5 기준 0.75 유지), 재현율은
    0.735 → 0.843 으로 올랐다. 마운트 과업지시서와 합성 RFP 은 **숫자가 그대로다**
    (0.844/0.692 · 0.636/0.913) — 평가 절이 없거나 표가 없어서다.

여기서 지키는 계약:
  - precision 은 문서별 바닥(`DOCUMENTS`) 아래로 내려가지 않는다
  - recall 은 문서별 바닥 위에 있다 (개선을 고정하려고 올려 왔다)
  - page 일치는 TP 와 같다 (원문 줄의 page 를 그대로 옮기므로 어긋나면 파서를 건드린 것이다)

숫자를 맞추려고 gold 나 평가 규칙을 고치는 것은 금지다. gold 는 사람이 검수한 정답이다.
"""

from __future__ import annotations

import difflib
import inspect
import json
import unicodedata
from pathlib import Path

import pytest

from app.services import document_extractor, rfp_extractor

ROOT = Path(__file__).resolve().parents[2]

#: 재는 문서와 그 기준선. gold 가 한 건뿐이면 규칙이 그 문서에만 맞춰졌는지 알 수 없다.
#: 실제로 두 번째 gold 를 만들자마자 드러났다 — 첫 문서에서 R 0.289→0.554 로 올린 개선이
#: 두 번째 문서(과업지시서)에서는 **0.205 그대로**였다. 성격이 다른 문서를 함께 재야 한다.
DOCUMENTS = {
    # 교육 용역 제안요청서. 개선 전 30/83 · P 0.800 · R 0.289
    # 2026-09-17 실측 P 0.803 · R 0.735 — 재현율 바닥을 0.50 에서 올려 그 개선을 고정했다.
    # 2026-09-20 실측 P 0.795 · R 0.843 (0919 §4-B-5). 정밀도 바닥을 0.800 → 0.780 으로
    # **낮춘다.** 평가표 칸을 항목화하면서 0.008 을 내주고 재현율 0.108 을 얻었고,
    # §4-B-5 의 기준이 「P ≥ 0.75 유지, R 상승」이다. 0.780 은 지금 값 바로 아래라
    # 더 내주는 것은 여전히 잡힌다. 재현율 바닥은 0.65 → 0.80 으로 올려 이번 개선을 고정한다.
    "g2b-R26BK01699556-000": {"min_precision": 0.780, "min_recall": 0.80},
    # 기계 과업지시서. 두 번째 gold 를 만든 시점의 기준선 14/39 · P 0.571 · R 0.205
    # 2026-09-17 실측 P 0.844 · R 0.692 — 이 문서는 이번 규칙으로 정밀도가 올랐다.
    "g2b-R26BK01718593-000": {"min_precision": 0.750, "min_recall": 0.60},
}

#: scripts/evaluate_requirements.py 와 같은 임계. 낮추지 말 것.
SIMILARITY_THRESHOLD = 0.85

#: 개선 전 실측. 이 아래로 내려가면 회귀다.
BASELINE_PRECISION = 0.800
BASELINE_RECALL = 0.289

#: 개선 후 실측에서 남긴 여유. 규칙을 조금 손봐도 깨지지 않되, 크게 후퇴하면 잡힌다.
MIN_RECALL = 0.50


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _measure(notice_id: str) -> dict[str, float | int]:
    doc_dir = ROOT / "data" / "public" / "real_rfp" / notice_id
    gold_path = ROOT / "data" / "public" / "sample_rfp" / f"gold_requirements.{notice_id}.json"
    if not doc_dir.exists() or not gold_path.exists():
        pytest.skip(f"{notice_id}: 원문 또는 gold 가 없다")

    # 한 폴더에 첨부가 여럿이다(입찰공고문·제안요청서…). 제안요청서·과업지시서를 고른다.
    candidates = [p for p in sorted(doc_dir.iterdir()) if p.suffix.lower() in (".hwp", ".hwpx", ".pdf")]
    source = next((p for p in candidates if "제안요청서" in p.name or "과업지시서" in p.name), None)
    if source is None:
        source = candidates[0] if candidates else None
    if source is None:
        pytest.skip(f"{notice_id}: 원문 파일이 없다")

    doc = document_extractor.extract_document(source, file_name=source.name)
    result = rfp_extractor.extract_with_stats(notice_id, doc)
    predictions = result.requirements

    gold_raw = json.loads(gold_path.read_text(encoding="utf-8"))
    gold_items = gold_raw["requirements"] if isinstance(gold_raw, dict) else gold_raw

    used: set[int] = set()
    true_positives = 0
    page_agreement = 0
    for item in gold_items:
        gold_text = item.get("source_text") or item.get("content") or ""
        best_score, best_index = 0.0, None
        for index, prediction in enumerate(predictions):
            if index in used:
                continue
            predicted_text = getattr(prediction, "source_text", None) or prediction.content
            score = _similarity(gold_text, predicted_text)
            if score > best_score:
                best_score, best_index = score, index
        if best_score >= SIMILARITY_THRESHOLD and best_index is not None:
            used.add(best_index)
            true_positives += 1
            if item.get("page") is not None and item.get("page") == getattr(predictions[best_index], "page", None):
                page_agreement += 1

    predicted_count = len(predictions)
    gold_count = len(gold_items)
    return {
        "notice_id": notice_id,
        "predicted": predicted_count,
        "gold": gold_count,
        "true_positives": true_positives,
        "page_agreement": page_agreement,
        "precision": true_positives / predicted_count if predicted_count else 0.0,
        "recall": true_positives / gold_count if gold_count else 0.0,
    }


@pytest.mark.parametrize("notice_id", sorted(DOCUMENTS))
def test_정밀도가_기준선_아래로_내려가지_않는다(notice_id: str):
    """넓게 잡으면 재현율은 오르지만 엉뚱한 줄이 섞인다. 그 값이 기준선이다."""
    measured = _measure(notice_id)
    floor = DOCUMENTS[notice_id]["min_precision"]
    assert measured["precision"] >= floor, (
        f"{notice_id}: precision {measured['precision']:.3f} < 기준선 {floor} — "
        "새로 넣은 규칙이 gold 아닌 줄을 너무 많이 잡는다"
    )


@pytest.mark.parametrize("notice_id", sorted(DOCUMENTS))
def test_재현율이_기준선보다_확실히_높다(notice_id: str):
    """규칙이 한 문서에만 맞춰지지 않았는지 두 문서로 함께 확인한다."""
    measured = _measure(notice_id)
    floor = DOCUMENTS[notice_id]["min_recall"]
    assert measured["recall"] >= floor, (
        f"{notice_id}: recall {measured['recall']:.3f} < {floor} — "
        "절 인지나 이어붙이기 가드가 되돌아갔을 수 있다"
    )


@pytest.mark.parametrize("notice_id", sorted(DOCUMENTS))
def test_페이지_연결은_찾은_것과_같은_수다(notice_id: str):
    """page 는 원문 줄에서 그대로 옮긴다. 어긋나면 문서 추출기를 건드린 것이다."""
    measured = _measure(notice_id)
    assert measured["page_agreement"] == measured["true_positives"]


@pytest.mark.parametrize(
    "line,expected",
    [
        # 평가요소 칸 — 구(句)라 띄어쓰기가 있다. 이것이 요구사항이다.
        ("과업 및 발주기관에 대한 이해도", ["과업 및 발주기관에 대한 이해도"]),
        ("최근 3년 이내 유사 사업 수행 실적", ["최근 3년 이내 유사 사업 수행 실적"]),
        # 분류 칸 — 한 낱말로 붙여 쓴다. 요구사항을 «묶는 이름»이지 요구사항이 아니다.
        ("사업수행역량", []),
        ("사업수행계획", []),
        # 머리글·배점 칸
        ("평가항목", []),
        ("배점", []),
        ("5건 이상", []),
        ("20", []),
        # PDF 는 한 줄에 탭이나 여러 칸 공백으로 붙여 내려준다. 칸으로 나눠서 본다.
        ("사업수행역량	참여인력의 수행 역량	10", ["참여인력의 수행 역량"]),
        ("경영상태  최근연도 유동비율 평가  5", ["최근연도 유동비율 평가"]),
    ],
)
def test_평가표에서_요구사항이_되는_칸만_꺼낸다(line: str, expected: list[str]):
    """0919 §4-B-5. 배점표의 평가요소는 어미가 없어 어떤 어미 규칙에도 걸리지 않는다.

    띄어쓰기를 요구하는 것이 이 판정의 핵심이다 — 분류 칸은 붙여 쓰고 평가요소 칸은 구다.
    """
    from app.services.rfp_extractor import _Line, _evaluation_cells

    assert _evaluation_cells(_Line(page=1, raw=line)) == expected


def test_상한에_잘리지_않는다():
    """MAX_REQUIREMENTS 에 잘리면 조용한 재현율 손실이자 조건 누락이다."""
    assert rfp_extractor.MAX_REQUIREMENTS >= 120


# ---------------------------------------------------------------------------
# 회사자료 — 본문이 전부 인용(>)인 마크다운
# ---------------------------------------------------------------------------


def test_인용만_있는_문서도_문단을_만든다():
    """인용 제거는 문서 앞머리의 도구 안내문을 걸러내려는 규칙이다.

    본문 전체가 인용으로 적힌 문서에서는 그 규칙 때문에 문단이 하나도 남지 않아
    「추출 실패」로 끝났다 (실측: 06_curriculum.md — 제목·표·인용만 있는 마크다운).
    """
    from app.services import company_index_service as cis

    body = "> 샘플에듀는 생성형 AI 실무 교육과정을 운영한다. 2026년 기준 누적 수료 인원은 사내 기록으로 관리한다.\n"
    assert cis.split_chunks(body) == []
    kept = cis.split_chunks(body, keep_quotes=True)
    assert len(kept) == 1
    assert not kept[0].startswith(">"), "인용 표시는 벗겨서 본문으로 쓴다"


def test_인용_유지는_기본값이_아니다():
    """평소에는 도구 안내문을 계속 걸러야 한다 — 기본 동작은 그대로다."""
    from app.services import company_index_service as cis

    body = (
        "> 이 문서는 자동 분할되었습니다.\n\n"
        "샘플에듀는 공공기관 대상 AI 교육을 수행한다. 최근 3년간 대학 위탁교육 실적을 보유한다.\n"
    )
    chunks = cis.split_chunks(body)
    assert len(chunks) == 1
    assert "자동 분할" not in chunks[0]


# ---------------------------------------------------------------------------
# 저장 파일에 연락처가 새지 않는다
# ---------------------------------------------------------------------------


def test_저장된_요구사항에_전화번호가_없다():
    """요구사항 source_text 는 공고 원문을 그대로 옮긴다.

    입찰공고문에는 담당자 이름과 직통번호가 흔히 들어 있다
    (실측: 「… AI혁신팀 ○○○ (☎ 02-XXXX-XXXX)」가 재추출 결과에 그대로 들어갔다).
    이 파일은 Git 에 들어가고 데모 스냅샷으로도 퍼지므로 저장 지점에서 막아야 한다.

    이름·부서는 남긴다 — 입찰 실무에서 「어느 팀 담당인지」는 필요하고,
    번호가 없으면 연락 수단이 되지 않는다.
    """
    import json
    import re

    pattern = re.compile(r"(?<![\d-])0\d{1,2}-\d{3,4}-\d{4}(?![\d-])")
    generated = ROOT / "data" / "public" / "sample_rfp" / "generated"
    if not generated.is_dir():
        pytest.skip("생성된 요구사항 파일이 없다")

    leaked: list[str] = []
    for path in sorted(generated.glob("*.json")):
        text = json.dumps(json.loads(path.read_text(encoding="utf-8")), ensure_ascii=False)
        if pattern.search(text):
            leaked.append(path.name)
    assert not leaked, f"저장 파일에 전화번호가 남아 있다: {leaked}"


def test_저장_경로가_마스킹을_거친다():
    """규칙이 두 벌이 되지 않도록 procurement_service 의 것을 그대로 쓴다."""
    from app.services import procurement_service, rfp_parser

    source = inspect.getsource(rfp_parser.store_result)
    assert "mask_contact_fields" in source, "store_result 가 마스킹을 거치지 않는다"
    assert procurement_service.mask_contact_fields("☎ 02-6746-7396") != "☎ 02-6746-7396"


# ---------------------------------------------------------------------------
# 원문에 없는 숫자를 만들지 않는다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line,expected",
    [
        # 글머리표가 아니라 금액·비율·인원의 소수점이다. 떼면 원문에 없는 숫자가 된다.
        ("2.45억원 이상 ~ 3.5억원 미만", "2.45억원 이상 ~ 3.5억원 미만"),
        ("10.5% 이내 부담", "10.5% 이내 부담"),
        ("3.3명 이상 배치", "3.3명 이상 배치"),
        # 진짜 글머리표는 그대로 뗀다.
        ("1. 과업명", "과업명"),
        ("2) 마운트 특성시험", "마운트 특성시험"),
        ("(3) 항목", "항목"),
        ("가. 주요내용", "주요내용"),
    ],
)
def test_소수점을_글머리표로_먹지_않는다(line: str, expected: str):
    """「2.45억원」이 「45억원」이 되어 Auditor 가 없는 불일치를 지적한 적이 있다.

    원문에 없는 숫자를 만들어 확정 어조로 수정을 지시하는 것이라 CLAUDE.md 11 위반이다.
    """
    from app.services.rfp_extractor import _MARKER_RE

    assert _MARKER_RE.sub("", line).strip() == expected


# ---------------------------------------------------------------------------
# 실제 공고도 항목 유형을 분류한다
# ---------------------------------------------------------------------------


def test_실제_공고도_항목_유형을_채운다():
    """합성 fixture 경로만 item_classifier 를 불러서, 실공고 12건이 전부
    item_type=REQUIREMENT 한 유형으로 저장돼 있었다.

    Requirement 의 기본값이 그 값이고 읽기 시 보정은 «비어 있을 때만» 채우므로,
    한 번 기본값으로 저장되면 영영 고쳐지지 않는다. 그 바람에 화면의 유형 탭이
    모두 0건, 「행동 필요」 배지가 절대 뜨지 않았다.
    """
    from collections import Counter

    notice_id = "g2b-R26BK01699556-000"
    doc_dir = ROOT / "data" / "public" / "real_rfp" / notice_id
    if not doc_dir.exists():
        pytest.skip("실제 제안요청서 원문이 없다")
    source = next((p for p in sorted(doc_dir.iterdir()) if "제안요청서" in p.name), None)
    if source is None:
        pytest.skip("제안요청서 첨부가 없다")

    doc = document_extractor.extract_document(source, file_name=source.name)
    requirements = rfp_extractor.extract_with_stats(notice_id, doc).requirements

    kinds = Counter(r.item_type for r in requirements)
    assert len(kinds) > 1, f"유형이 하나뿐이다 — 분류기를 부르지 않는다: {dict(kinds)}"
    assert any(r.action_required for r in requirements), "「행동 필요」가 하나도 없다"
