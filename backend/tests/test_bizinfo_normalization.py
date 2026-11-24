"""기업마당 전체 수집과 정규 필드 (0921.md §4-A-4).

## 무엇이 틀렸나

앱이 기업마당을 **100건만** 받고 있었다. 클라이언트 상한(`MAX_COUNT=500`)과 수집
스크립트의 기본값(`DEFAULT_COUNT=100`)이 겹친 결과다. 그 상한 때문에 검수자가 손으로 고른
**기준 답안 16건 중 15건이 목록에 아예 없었다** — 회사에 맞는 지원사업이 없는 것이 아니라
못 본 것이었다(실측: `docs/reports/2026-09-20_apply_candidates.csv` 대조).

## 여기서 지키는 약속 셋

1. **지역 이름을 하나로 접는다.** 통합 이후 이름은 「전남광주」이고 해시태그에는 옛 이름
   (「광주」·「전남」)이 섞여 있다. 같은 지역을 두 이름으로 세면 소재지와 대조할 때 어긋난다.
2. **대상 요건은 원문 그대로 싣는다.** 요약문의 「☞ …」 문장을 가공하지 않는다
   (0921 §4-B: 생성 금지).
3. **저장할 때 한 번만 계산한다.** 1,600건을 목록 요청마다 다시 파싱하면 화면이 느려진다.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services import bizinfo_client, bizinfo_service

NOW = datetime(2026, 9, 17, 3, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 지역 이름
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hashtags, expected",
    [
        ("#전남광주 #AI", ["전남광주"]),
        ("#광주 #교육", ["전남광주"]),
        ("#전남 #사회적경제", ["전남광주"]),
        ("#광주광역시", ["전남광주"]),
        ("#전라남도", ["전남광주"]),
        ("#경기 #성남", ["경기"]),
        ("#AI #교육", []),
    ],
)
def test_옛_이름과_통합_이름을_한_이름으로_접는다(hashtags: str, expected: list[str]) -> None:
    """「광주」와 「전남」이 따로 잡히면 한 사업이 두 지역으로 세어진다."""
    assert bizinfo_service.region_tags_of(hashtags, None, None) == expected


def test_지역_표시가_없으면_빈_목록이다() -> None:
    """빈 목록은 「전국 사업」이 아니라 **「지역 표시를 못 찾았다」**이다 — 판정은 확인 필요로 간다."""
    assert bizinfo_service.region_tags_of(None, None, None) == []


def test_기관명과_제목에서도_찾는다() -> None:
    assert bizinfo_service.region_tags_of(None, "광주정보문화산업진흥원", None) == ["전남광주"]
    assert bizinfo_service.region_tags_of(None, None, "[경기] 성남시 지원사업") == ["경기"]


# ---------------------------------------------------------------------------
# 「☞」 대상 문장
# ---------------------------------------------------------------------------


def test_요약문의_대상_문장을_원문_그대로_뽑는다() -> None:
    plain = bizinfo_service._plain_text(
        "<p>사업 개요입니다.</p><p>☞&nbsp;디지털 제품을 보유한 광주 본사 ICT/SW기업</p>"
        "<p>☞ 창업 7년 이내</p>"
    )
    assert bizinfo_service.requirement_sentences_of(plain) == [
        "디지털 제품을 보유한 광주 본사 ICT/SW기업",
        "창업 7년 이내",
    ]


def test_한_줄에_여러_개가_붙어도_나눈다() -> None:
    assert bizinfo_service.requirement_sentences_of("☞ 중소기업 ☞ 창업 7년 이내") == [
        "중소기업",
        "창업 7년 이내",
    ]


def test_표시가_없으면_지어내지_않는다() -> None:
    assert bizinfo_service.requirement_sentences_of("대상 요건이 본문에만 있는 공고") == []
    assert bizinfo_service.requirement_sentences_of(None) == []


# ---------------------------------------------------------------------------
# 저장·복원
# ---------------------------------------------------------------------------


def test_캐시에_정규_필드를_적어_둔다() -> None:
    """목록 요청마다 1,600건을 다시 파싱하지 않으려는 것이다."""
    normalized = bizinfo_service._normalize_item(
        {
            "pblancId": "PBLN_X",
            "pblancNm": "시험 사업",
            "hashtags": "#광주,#AI",
            "jrsdInsttNm": "광주테크노파크",
            "bsnsSumryCn": "<p>☞ 중소기업</p>",
        }
    )
    assert normalized["region_tags"] == ["전남광주"]
    assert normalized["requirement_sentences"] == ["중소기업"]
    # 원본 키는 하나도 지우지 않는다 — 나중에 다른 값을 봐야 할 때 근거가 남아야 한다.
    assert normalized["bsnsSumryCn"] == "<p>☞ 중소기업</p>"


def test_옛_캐시도_그대로_읽는다() -> None:
    """정규 필드가 없던 시절의 캐시 항목은 읽는 시점에 계산한다."""
    program = bizinfo_service.map_program(
        {
            "pblancId": "PBLN_Y",
            "pblancNm": "[전남광주] 시험 사업",
            "jrsdInsttNm": "광주정보문화산업진흥원",
            "bsnsSumryCn": "<p>☞ 사회적기업</p>",
        }
    )
    assert program is not None
    assert program.region_tags == ["전남광주"]
    assert program.requirement_sentences == ["사회적기업"]


def test_저장된_값이_있으면_그것을_쓴다() -> None:
    program = bizinfo_service.map_program(
        {
            "pblancId": "PBLN_Z",
            "pblancNm": "시험",
            "region_tags": ["제주"],
            "requirement_sentences": ["저장해 둔 문장"],
            "bsnsSumryCn": "<p>☞ 다른 문장</p>",
        }
    )
    assert program is not None
    assert program.region_tags == ["제주"]
    assert program.requirement_sentences == ["저장해 둔 문장"]


# ---------------------------------------------------------------------------
# 전체를 받는다
# ---------------------------------------------------------------------------


def test_한_번에_전체를_받을_수_있는_상한이다() -> None:
    """500 상한이 기준 답안 16건 중 15건을 가리고 있었다 (실측 1,604건)."""
    assert bizinfo_client.FULL_COUNT == bizinfo_client.MAX_COUNT
    assert bizinfo_client.MAX_COUNT >= 2000
