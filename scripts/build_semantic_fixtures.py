"""의미 매칭 시험용 **합성 벡터** 생성기 (CLAUDE.md §4-C · §22).

## 왜 합성인가

`semantic_matcher` 의 「우리 회사 적합도」는 임베딩 코사인으로 순서를 매긴다. 그런데 이
저장소가 도는 환경에는 OpenAI 크레딧이 없다(`insufficient_quota`). 진짜 임베딩을 받을 수
없으니 순서를 시험할 수도 없고, conftest 가 네트워크를 막으므로 막아서도 안 된다.

그래서 **손으로 만든 결정적 벡터**를 픽스처로 둔다. 이 파일이 만드는 벡터는
**진짜 임베딩이 아니다.** 숨길 이유가 없으므로 픽스처의 `note`, 테스트 docstring, 보고서
어디에나 「합성 벡터」라고 적는다. 이 벡터로 확인하는 것은 오직 하나다 —
**`semantic_matcher` 의 계산·경계·정렬 코드가 기대한 순서를 내는가.**
실제 임베딩의 품질(한국어 문장을 얼마나 잘 가르는가)은 이것으로 증명되지 않는다.

## 어떻게 만드는가 — 「개념 가방」

1. 손으로 정한 **개념 축**(교육·운영, 컨설팅, 개발·구축 …)마다 그 축을 나타내는 낱말을 둔다.
2. 텍스트 하나에서 축별 낱말이 몇 번 나오는지 세고(가중치 곱), 그 벡터를 L2 정규화한다.
3. 앞에 **공통 축** 하나를 붙인다. 한국어 임베딩은 서로 무관한 두 문장에서도 코사인이
   0.6 안팎으로 나온다(`semantic_matcher._COSINE_FLOOR` 가 존재하는 이유). 공통 축이
   그 배경값을 흉내낸다. 덕분에 코사인이 `BASELINE + (1-BASELINE) x 개념유사도` 가 되어
   바닥에 눌려 붙는(전부 0점이 되는) 일이 없다.

낱말 가중치는 네 단계다. 「모집」·「공고」처럼 **사업의 성격 자체를 가르는** 말은 크게 잡았다 —
「교육생 모집 공고」는 교육 이야기가 나와도 수행사를 뽑는 입찰이 아니라 참가자를 뽑는
안내문이고, 샘플에듀가 제안서를 낼 대상이 아니기 때문이다.

## 쓰는 법

    python scripts/build_semantic_fixtures.py            # 픽스처를 다시 만든다
    python scripts/build_semantic_fixtures.py --dry-run  # 파일을 쓰지 않고 점수표만 본다

결과: `backend/tests/fixtures/llm/semantic_vectors.json`
(키·조직 내부정보·개인정보는 넣지 않는다. 공개된 공고 제목과 회사 사업영역 문구뿐이다.)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services import semantic_matcher  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "backend" / "tests" / "fixtures" / "llm" / "semantic_vectors.json"

# ---------------------------------------------------------------------------
# 개념 축과 낱말
# ---------------------------------------------------------------------------

#: 공통 축이 차지하는 비중. 코사인의 바닥값이기도 하다 —
#: 개념이 하나도 겹치지 않는 두 텍스트의 코사인이 정확히 이 값이다.
#: `_COSINE_FLOOR`(0.55)보다 높게 둬서 아무것도 0점으로 눌리지 않게 한다.
BASELINE = 0.60

COMMON_AXIS = "공통(어느 공고에나 깔려 있는 배경)"

# 가중치 단계 — 숫자 자체보다 「무엇을 더 크게 볼 것인가」가 중요하다.
DECISIVE = 3.0  # 사업의 성격을 가르는 말
STRONG = 2.0  # 성격을 강하게 시사하는 말
NORMAL = 1.0  # 보통
WEAK = 0.5  # 어디에나 붙어 혼자서는 근거가 못 되는 말

#: 축 이름 -> {낱말: 가중치}
WORDS: dict[str, dict[str, float]] = {
    "교육·운영": {
        "부트캠프": 1.5,
        "아카데미": 1.5,
        "교육과정": 1.2,
        "교육프로그램": NORMAL,
        "실무교육": 1.2,
        "교육": NORMAL,
        "연수": NORMAL,
        "강사": NORMAL,
        "강의": NORMAL,
        "워크숍": NORMAL,
        "커리큘럼": NORMAL,
        "리터러시": NORMAL,
        "Literacy": NORMAL,
        "인력양성": NORMAL,
        "역량 강화": 0.8,
        "역량강화": 0.8,
        "운영": NORMAL,
        "기획": 0.6,
        "프로그램": 0.4,
        "활용": WEAK,
    },
    "컨설팅": {
        "컨설팅": NORMAL,
        "자문": NORMAL,
        "전략수립": NORMAL,
    },
    "개발·구축": {
        "고도화": NORMAL,
        "시스템": NORMAL,
        "플랫폼": NORMAL,
        "솔루션": NORMAL,
        "인프라": NORMAL,
        "개발": NORMAL,
        "구축": NORMAL,
        "서버": NORMAL,
    },
    "데이터": {
        "데이터베이스": NORMAL,
        "빅데이터": NORMAL,
        "데이터": NORMAL,
        "DB": NORMAL,
    },
    "행사·전시": {
        "경진대회": NORMAL,
        "박람회": NORMAL,
        "엑스포": NORMAL,
        "페스티벌": NORMAL,
        "전시": NORMAL,
        "축제": NORMAL,
    },
    # 참가자·수혜자를 뽑는 안내문이라는 신호. 수행사를 뽑는 입찰과 가르는 축이라 크게 잡는다.
    "모집·선발": {
        "참여기업": STRONG,
        "참가기업": STRONG,
        "주관기관": 1.5,
        "교육생": DECISIVE,
        "참가자": STRONG,
        "모집": DECISIVE,
        "공고": STRONG,
        "신청": STRONG,
        "접수": STRONG,
        "선정": 1.5,
        "지정": 1.5,
    },
    "제조·유통": {
        "스마트공장": NORMAL,
        "제조": NORMAL,
        "공장": NORMAL,
        "유통": NORMAL,
        "공예": NORMAL,
        "식품": NORMAL,
    },
    "연구": {
        "연구개발": NORMAL,
        "연구소": NORMAL,
        "연구": NORMAL,
    },
    "AI·디지털": {
        "인공지능": NORMAL,
        "생성형": NORMAL,
        "에이전트": NORMAL,
        "Agentic": NORMAL,
        "ChatGPT": NORMAL,
        "Copilot": NORMAL,
        "자동화": NORMAL,
        "디지털": WEAK,
        "LLM": NORMAL,
        "AI": NORMAL,
    },
    "수요기관·고객": {
        "공공기관": NORMAL,
        "교육기관": NORMAL,
        "대학교": NORMAL,
        "대학": NORMAL,
        "고객": WEAK,
        # 「중소기업」·「참여기업」처럼 아무 공고에나 붙는 말이라 혼자서는 근거가 약하다.
        "기업": 0.4,
        "기관": 0.4,
    },
    "발주형태(용역·위탁)": {
        "위탁 용역": 0.8,
        "위탁": 0.8,
        "수탁": 0.8,
        "용역": 0.8,
    },
}

AXES: list[str] = [COMMON_AXIS, *WORDS.keys()]

#: 긴 낱말부터 집어내고 그 자리를 지운다 — 「교육생」을 「교육」으로 두 번 세지 않게.
_SCAN_ORDER: list[tuple[str, str, float]] = sorted(
    ((word, axis, weight) for axis, table in WORDS.items() for word, weight in table.items()),
    key=lambda item: -len(item[0]),
)

# ---------------------------------------------------------------------------
# 픽스처에 넣을 텍스트 — 검수에서 이름이 확인된 공고 12건과 샘플에듀 프로필
# ---------------------------------------------------------------------------

EDUCATION_NOTICES: list[str] = [
    "가천대학교 AI부트캠프 사업 피지컬 AI 교육 기획·운영 위탁 용역",
    "가천대학교 AI부트캠프 사업 생성형 AI 활용 교육 기획·운영 위탁 용역",
    "네이버클라우드 아카데미 교육과정 운영 용역(소버린 AI Literacy)",
    "Agentic AI 교육 프로그램 기획 및 운영 지원 용역",
]

DEVELOPMENT_NOTICES: list[str] = [
    "경성대학교 소방공무원 맞춤형 AI 다중모달 심리진단 및 통합 데이터 관리 시스템 개발 용역",
    "마운트 에이전트 개발을 위한 DB 구축 용역",
]

OTHER_NOTICES: list[str] = [
    "2026년 공예 온라인 유통 및 AI 활용 역량 강화 교육프로그램 교육생 모집 공고",
    "2026년 중소기업 특성화고 인력양성사업 참여기업 모집 공고",
    "2026년 제2회 반려동물 창업 아이디어 경진대회 참가자 모집 공고",
    "제24회 전주국제발효식품엑스포 참가기업 4차 추가모집 공고",
    "2027년 스마트공장 구축지원사업 주관기관 모집 공고",
    "2026년 성장단계별 우수 연구소기업(라이징스타ㆍ스타) 지정 신청 공고",
]

#: CLAUDE.md §6 의 공개 가능한 회사 Profile. 매출·인력·실적 같은 민감정보는 넣지 않는다.
BUSINESS_DOMAINS: list[str] = [
    "AI 활용 교육",
    "생성형 AI 교육",
    "ChatGPT / Copilot 활용 교육",
    "업무자동화 교육",
    "디지털 역량 교육",
    "AI 컨설팅",
    "ESG 교육 및 컨설팅",
]

TARGET_CLIENTS: list[str] = ["공공기관", "대학", "기업", "교육기관"]

NOTE = (
    "합성 벡터 — 진짜 임베딩이 아니다. 손으로 정한 개념 축에 낱말이 몇 번 나오는지를 센 "
    "「개념 가방」을 L2 정규화한 값이며, scripts/build_semantic_fixtures.py 가 만든다. "
    f"첫 번째 축은 공통 배경(비중 {BASELINE})으로, 개념이 전혀 겹치지 않는 두 텍스트의 "
    "코사인이 그 값이 된다. 합성 벡터는 실제 임베딩보다 훨씬 또렷하게 갈리므로 교육 공고는 "
    "정규화 상한(1.0)에 붙는다. 이 벡터로 확인한 순서는 semantic_matcher 의 계산이 "
    "기대대로 도는지를 볼 뿐, 실제 임베딩의 품질을 증명하지 않는다."
)


# ---------------------------------------------------------------------------
# 벡터 만들기
# ---------------------------------------------------------------------------


def concept_counts(text: str) -> dict[str, float]:
    """축별 낱말 가중치 합. 긴 낱말부터 집어내고 지운다."""
    remaining = text
    counts: dict[str, float] = {axis: 0.0 for axis in WORDS}
    for word, axis, weight in _SCAN_ORDER:
        hits = remaining.count(word)
        if hits:
            counts[axis] += hits * weight
            remaining = remaining.replace(word, " ")
    return counts


def vectorize(text: str) -> list[float]:
    """텍스트 하나의 합성 벡터. 길이는 `AXES` 와 같고 L2 노름이 1이다."""
    counts = concept_counts(text)
    norm = math.sqrt(sum(value * value for value in counts.values()))
    if norm == 0.0:
        # 축에 하나도 걸리지 않으면 그 텍스트는 다른 모든 텍스트와 똑같은 거리에 놓인다.
        # 순서를 시험할 수 없으니 조용히 넘기지 말고 낱말 목록을 보완하게 한다.
        raise ValueError(f"개념 축에 걸리는 낱말이 없습니다: {text!r}. WORDS 에 낱말을 추가하세요.")
    concept_scale = math.sqrt(1.0 - BASELINE)
    vector = [math.sqrt(BASELINE)]
    vector.extend(concept_scale * counts[axis] / norm for axis in WORDS)
    return [round(value, 8) for value in vector]


def fixture_texts() -> list[str]:
    """픽스처에 들어갈 텍스트 전부 — 공고 12건 + 회사 프로필 문구."""
    notices = [
        semantic_matcher.notice_text(title=title)
        for title in (*EDUCATION_NOTICES, *DEVELOPMENT_NOTICES, *OTHER_NOTICES)
    ]
    phrases = semantic_matcher.profile_phrases(
        business_domains=BUSINESS_DOMAINS,
        target_clients=TARGET_CLIENTS,
    )
    return [*notices, *phrases]


def build() -> dict:
    return {
        "note": NOTE,
        "axes": AXES,
        "vectors": {text: vectorize(text) for text in fixture_texts()},
    }


# ---------------------------------------------------------------------------
# 점수표 — 무엇이 어떤 문구와 붙었는지 사람이 보고 판단할 수 있게
# ---------------------------------------------------------------------------


def score_table(vectors: dict[str, list[float]]) -> list[tuple[str, str, float | None, str]]:
    phrases = semantic_matcher.profile_phrases(
        business_domains=BUSINESS_DOMAINS,
        target_clients=TARGET_CLIENTS,
    )
    rows: list[tuple[str, str, float | None, str]] = []
    for group, titles in (
        ("교육", EDUCATION_NOTICES),
        ("개발", DEVELOPMENT_NOTICES),
        ("그 외", OTHER_NOTICES),
    ):
        for title in titles:
            notice = semantic_matcher.notice_text(title=title)
            best_phrase, best_raw = "", -1.0
            for phrase in phrases:
                raw = semantic_matcher.cosine(vectors[notice], vectors[phrase])
                if raw > best_raw:
                    best_raw, best_phrase = raw, phrase
            score = semantic_matcher._normalize(best_raw)
            rows.append((group, title, round(score, 4), f"{best_phrase} (코사인 {best_raw:.3f})"))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="의미 매칭 시험용 합성 벡터 픽스처 생성")
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 점수표만 출력")
    args = parser.parse_args()

    payload = build()
    for group, title, score, reason in score_table(payload["vectors"]):
        print(f"[{group:>3}] {score!s:<6} {title[:44]:<46} <- {reason}")

    if args.dry_run:
        print("\n--dry-run: 파일을 쓰지 않았습니다.")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n합성 벡터 {len(payload['vectors'])}건 저장: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
