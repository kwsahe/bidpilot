"""교육 갈래 분류 — 실측 공고 제목으로 고정한다 (0920.md §4-A-2 · ISSUE-073).

## 왜 넓혔나

담당자가 「우리가 넣을 수 있는 공고가 1건뿐인가」라고 물어 실측했더니, 마감 전 AI 후보
117건 중 **교육 갈래로 잡힌 것은 19건**인데 그 밖에도 교육을 운영하는 일이 9건 더 있었다.
「교육」이라는 낱말이 그 자리에 없었을 뿐이다 — 「제4기 AI ADVANCED **과정 운영**」·
「AI취업**캠프** **프로그램 위탁**」·「AI **교육 지원센터** 프로그램 위탁 **운영**」(2.27억).

## 정밀도가 먼저다

넓히면 오탐이 따라온다. 그래서 반대 방향도 함께 고정한다 —
「**연수시설 임차**」는 강의가 아니라 건물을 빌리는 일이고, 「교육관 **개관식** 행사」는
행사 대행이며, 「교육자료 콘텐츠 **개발**」은 만드는 일이다. 셋 다 교육 운영이 아니다.

제목은 전부 `docs/reports/2026-09-20_g2b_live_scan.csv`(203행 실측)와 QA 보고서 §1-2 에서
그대로 가져왔다. 지어낸 제목은 하나도 없다.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.services import work_kinds

ROOT = Path(__file__).resolve().parents[2]
SCAN_CSV = ROOT / "docs" / "reports" / "2026-09-20_g2b_live_scan.csv"


def tracks(title: str) -> list[str]:
    return work_kinds.work_tracks(work_kinds.detect_work_kinds(title))


# ---------------------------------------------------------------------------
# 넓힌 것 — QA 보고서 §1-2 「갈래 분류가 놓친 교육형 공고」
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "제4기 AI ADVANCED 과정 운영 용역",
        "2026학년도 AI취업캠프 프로그램 위탁용역",
        "[긴급]2026년 AI 교육 지원센터 프로그램 위탁 운영 용역 사업",
        "청주시 AI·ICT 교육 격차 해소를 위한 교육환경 조성 및 교육지원사업 『행복 AI 스터디 랩』 운영 용역 업체 선정",
        "[앵커] 생성형 AI 융합 K-pop 송캠프 운영 용역",
        "한양대학교 산학협력단 2026년 글로벌 AI 인재양성 해외협력 프로그램 총괄 운영지원 용역",
    ],
)
def test_교육을_운영하는_일인데_교육이라는_낱말이_없는_공고(title: str) -> None:
    assert "education" in tracks(title), title


@pytest.mark.parametrize(
    "title,why",
    [
        ("군 장병 맞춤형 AI 교육 서비스 개발 용역", "서비스를 «만드는» 일이라 교육 운영이 아니다"),
        ("AI광주미래교육박람회 대행 용역", "박람회 대행은 행사 운영이다 — 개관식과 같은 무리"),
        ("[긴급] 2026년 광주아이온(AI-ON) 운영 기능개선 및 유지관리 사업", "기능개선·유지관리는 개발 쪽 일이다"),
    ],
)
def test_보고서가_교육형으로_적었지만_교육_운영이_아닌_것(title: str, why: str) -> None:
    """QA 보고서의 「놓친 9건」 가운데 셋은 넓힌 어휘로도 교육이 되지 않는다 — 그게 맞다.

    0920 §4-A-2 가 더하라고 한 낱말만 넣었고, 이 셋에 닿는 낱말은 그 목록에 없다.
    같은 절이 「교육자료 콘텐츠 개발」을 오탐이라고 못박고 있으므로, 「교육 서비스 개발」도
    같은 무리로 본다. 정밀도가 먼저다.
    """
    assert "education" not in tracks(title), f"{title} — {why}"


def test_교육과정_개발은_교육과_개발_둘_다다() -> None:
    """보고서가 놓쳤다고 적은 것 중 하나는 **이미** 교육으로 잡히고 있었다."""
    assert tracks("화학3법 기반 AI·빅데이터 활용 교육과정 개발 용역") == ["education", "development"]


# ---------------------------------------------------------------------------
# 막은 것 — 넓히면 따라오는 오탐
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "[입찰참가자격확대]2026 AI·빅데이터 기반 학교 리더십 전략과정 직무연수 3기 연수시설 임차 용역",
        "[입찰참가자격확대]2026 AI·빅데이터 기반 학교 리더십 전략과정 직무연수 4기 연수시설 임차 용역",
        "2026년 AI 교육관 개관식 행사 대행 용역",
        "AI 교육자료 콘텐츠 개발 용역",
    ],
)
def test_교육_낱말이_있어도_교육_운영이_아닌_것(title: str) -> None:
    assert "education" not in tracks(title), title


def test_직무연수_자체는_여전히_교육이다() -> None:
    """오탐을 막느라 진짜 연수까지 지우면 안 된다 — 지운 것은 「시설 임차」뿐이다."""
    assert "education" in tracks("2026 AI·빅데이터 기반 학교 리더십 전략과정 직무연수 3기 위탁 용역")


def test_양성은_사람을_기르는_말일_때만_교육이다() -> None:
    """낱말만 보면 「양성 플랫폼 구축」처럼 «양성에 쓸 물건을 만드는» 사업이 끌려온다."""
    assert "education" in tracks("AI 자율제조 전문인력 양성 및 컨설팅 지원 용역")
    assert tracks("구미대학교 AI-Native 하이퍼링커 양성 플랫폼 구축") == ["development"]


# ---------------------------------------------------------------------------
# 실측 203행 전체 — 교육 갈래 19건이 그대로 교육이어야 한다
# ---------------------------------------------------------------------------


def scan_rows() -> list[dict[str, str]]:
    if not SCAN_CSV.exists():
        pytest.skip("실측 CSV 가 없다 (docs/reports/2026-09-20_g2b_live_scan.csv)")
    with SCAN_CSV.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def test_실측_교육_갈래는_시설_임차_둘을_빼고_그대로_교육이다() -> None:
    """CSV 의 갈래 열은 **제목+요약**으로 계산된 값이라 제목만으로는 다를 수 있다.

    그래서 「교육이어야 하는 것이 교육인가」만 본다. 예외는 「연수시설 임차」 두 건이고,
    그건 이번에 **일부러** 뺀 오탐이다.
    """
    rows = scan_rows()
    education = [r for r in rows if "education" in r["갈래"]]
    assert len(education) == 19, "실측 교육 갈래는 19건이다"

    missed = [
        r["제목"]
        for r in education
        if "education" not in tracks(r["제목"]) and "연수시설 임차" not in r["제목"]
    ]
    # 제목만으로는 판정하지 못하는 것이 있다(요약에 교육 낱말이 있는 경우).
    # 그것까지 강제하지 않되, 몇 건인지는 드러내 둔다.
    assert len(missed) <= 5, f"제목만으로 교육이 되지 않는 건이 너무 많다: {missed}"

    excluded = [r["제목"] for r in education if "연수시설 임차" in r["제목"]]
    assert len(excluded) == 2
    assert all("education" not in tracks(title) for title in excluded)


def test_실측_전체에서_교육이_지나치게_늘지_않는다() -> None:
    """넓힌 어휘가 개발·그 밖 공고를 교육으로 끌어오면 목록이 못 쓰게 된다.

    실측 203행에서 **제목만으로** 교육이 되는 비율의 상한을 둔다. 지금 값은 22/203 이다.
    """
    rows = scan_rows()
    education = [r for r in rows if "education" in tracks(r["제목"])]
    assert len(education) <= 30, f"교육 갈래가 {len(education)}건까지 늘었다"
