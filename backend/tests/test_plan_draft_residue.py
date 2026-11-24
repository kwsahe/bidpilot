"""초안 잔여 셋 (ISSUE-119 · prompt_03 §4-D).

13차가 남긴 것과 재검증이 새로 잡은 것, 합쳐서 셋이다.

1. **「확인 필요」 안내에 「공고문 근거」 배지가 달렸다.** 근거가 없다는 말에 근거
   배지가 붙은 자리다 — 담당자가 그것을 근거로 읽는다.
2. **「기대 효과」의 근거가 분야 필드 한 낱말**(「창업」)이었다. 근거가 있는 척하는 빈칸.
3. **절차 서술이 자격 인용에 남았다.** 「검토는 전문기관 및 주관기관에서 상시 진행하며」가
   역할 조항으로 잡혔다 — 심사하는 쪽의 일하는 방식이지 신청자의 자격이 아니다.

셋 다 「틀린 값」이 아니라 **「근거가 아닌 것을 근거로 보이게 한 것」**이다. 그래서 여기서
재는 것은 숫자가 아니라 **무엇이 근거로 표시되는가**다.
"""

from __future__ import annotations

import pytest

from app.schemas.business_opportunity import SupportProgram
from app.services import support_plan_service as plan
from app.services import support_requirement_extractor as extractor
from app.services import bizinfo_document_store as store


def program(**fields) -> SupportProgram:
    base = dict(id="bizinfo-TEST", title="시험 공고", agency="시험 기관")
    base.update(fields)
    return SupportProgram(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# §4-D-1 — 「확인 필요」는 유형이 없다
# --------------------------------------------------------------------------


def test_확인_필요_안내에는_문장_유형이_없다() -> None:
    """유형이 있으면 화면이 「공고문 근거」 배지를 붙인다 — 근거가 아니라 빈칸이다."""
    outline = [{"section": "수행 역량·유사 실적", "note": "승인·색인된 회사자료에서 연결된 근거가 없습니다"}]

    sections = plan.build_sections(program(), outline)

    sentence = sections[0]["sentences"][0]
    assert sentence["text"].startswith("확인 필요 —")
    assert sentence["type"] is None, "안내 문장에 근거 유형이 달렸다"
    assert sentence["note"] is True
    assert sentence["source"] is None


def test_진짜_근거는_유형을_그대로_단다() -> None:
    """안내만 유형을 빼는 것이다. 근거까지 비면 화면이 아무것도 구분하지 못한다."""
    outline = [{"section": "사업 개요·추진 배경", "quotes": ["지원대상 : 광주광역시 본사소재 기업"]}]

    sentence = plan.build_sections(program(), outline)[0]["sentences"][0]

    assert sentence["type"] == plan.NOTICE
    assert "note" not in sentence


def test_유형_없는_문장은_AI_문장으로_세지_않는다() -> None:
    """`ai_sentence_count` 가 `sentence["type"]` 을 그대로 읽으므로 None 에서 터지면 안 된다."""
    draft = plan.generate(program(), [{"section": "기대 효과"}])

    assert draft["ai_sentence_count"] == 0
    assert draft["sentence_count"] == 1


# --------------------------------------------------------------------------
# §4-D-2 — 「기대 효과」는 목적 문장을 인용한다
# --------------------------------------------------------------------------


def test_기대_효과는_분야_한_낱말을_근거로_내지_않는다() -> None:
    """13차의 근거는 「창업」이었다. 그것으로는 기대 효과를 쓸 수 없다."""
    sections = plan.build_sections(
        program(category="창업", summary="신청 방법은 누리집을 참고하십시오."),
        [{"section": "기대 효과"}],
    )

    sentence = sections[0]["sentences"][0]
    assert sentence["type"] is None, f"근거가 아닌 것을 근거로 냈다: {sentence['text']}"
    assert "창업" not in sentence["text"].replace("확인 필요", "")


@pytest.mark.parametrize(
    "summary, expected_fragment",
    [
        (
            "지역 창업기업의 성장을 촉진하고자 함. 자세한 내용은 붙임 참조.",
            "촉진하고자",
        ),
        (
            "붙임 참조.\n중소기업의 디지털 전환을 지원하고자 합니다.",
            "지원하고자",
        ),
        (
            "AI 융합 인재 양성을 통해 지역 산업 경쟁력을 제고하기 위하여 추진합니다.",
            "제고",
        ),
    ],
)
def test_사업_개요의_목적_문장을_원문_그대로_인용한다(summary: str, expected_fragment: str) -> None:
    sections = plan.build_sections(
        program(category="창업", summary=summary), [{"section": "기대 효과"}]
    )

    sentence = sections[0]["sentences"][0]
    assert sentence["type"] == plan.NOTICE
    assert expected_fragment in sentence["text"]
    # **원문 그대로다.** 요약·의역하지 않는다 (CLAUDE.md §11).
    assert sentence["source"] and sentence["source"] in summary


def test_목적_문장이_없으면_확인_필요다() -> None:
    """없는 것을 지어내지 않는다 — 그것이 이 절의 규칙이다."""
    sections = plan.build_sections(
        program(category="창업", summary="접수는 9월 30일까지입니다."), [{"section": "기대 효과"}]
    )

    assert sections[0]["sentences"][0]["type"] is None


# --------------------------------------------------------------------------
# §4-D-3 — 절차 서술은 자격이 아니다
# --------------------------------------------------------------------------

#: `data/private/bizinfo_docs/PBLN_000000000126482.txt` 245행, 원문 그대로.
PROCEDURE_126482 = (
    "※ 신청기업의 요건 및 사업계획서 유사‧중복성 검토는 전문기관 및 주관기관에서 상시 진행하며,"
)


def test_검토는_진행하며_는_역할_조항이_아니다() -> None:
    """126482 245행. 「주관기관」이라는 낱말 때문에 역할 조항으로 잡혔다."""
    text = store.join_pages([f"○ 신청자격\n- 창업 7년 이내 기업\n{PROCEDURE_126482}"])

    result = extractor.extract_from_text("P", text)

    quoted = [c.source_text for c in result.clauses]
    assert PROCEDURE_126482 not in quoted, f"절차 서술이 조항으로 남았다: {quoted}"
    # 같은 절의 **진짜 요건**은 그대로 남는다.
    assert result.of("founding_years"), "절차 서술을 빼면서 진짜 요건까지 지웠다"


@pytest.mark.parametrize(
    "line",
    [
        "- 서면평가는 전문기관에서 진행합니다",
        "- 적격성 심사는 주관기관이 실시한다",
        "- 현장 점검은 위원회에서 수행하며",
    ],
)
def test_같은_모양의_절차_서술도_뺀다(line: str) -> None:
    text = store.join_pages([f"○ 신청자격\n{line}"])
    assert extractor.extract_from_text("P", text).clauses == []


@pytest.mark.parametrize(
    "line, kind",
    [
        ("- 광주광역시 본사소재 기업에 한하여 신청 가능", "location"),
        ("- 스마트제조혁신R&D 최종평가 결과 완료판정(60점 이상) 과제", "prerequisite"),
        ("- 공급기업 및 수요기업 형태의 컨소시엄 참여 필수", "role"),
    ],
)
def test_진짜_요건은_그대로_남는다(line: str, kind: str) -> None:
    """**좁게 잡았다는 증거.** 프롬프트가 지킨다고 한 세 모양이다 (§4-D-3)."""
    text = store.join_pages([f"○ 신청자격\n{line}"])

    assert extractor.extract_from_text("P", text).of(kind), f"진짜 요건이 사라졌다: {line}"


# --------------------------------------------------------------------------
# §4-F — 운영기관 이름을 늘어놓은 줄은 「자리」가 아니다 (15차 · prompt_05 §4-F)
# --------------------------------------------------------------------------

#: 전부 `data/private/bizinfo_docs/PBLN_000000000126482.txt` 원문이다. 행 번호를 적어 둔다 —
#: 지어낸 문장으로 검사하면 검사가 스스로를 속인다.
AGENCY_LINES = [
    "* (전문기관) 창업진흥원 (주관기관) 서울창조경제혁신센터",  # 247행 — 운영기관 나열
    "주관기관 또는 전문기관에서 별도 현장실사를 진행할 수 있음",  # 286행 — 심사하는 쪽의 일
    "전문기관/주관기관/창업기업 ◀ K-Startup 누리집 ◀ 주관기관 별도 안내",  # 318행 — 안내 흐름도
    "◦ 전문기관과 주관기관은 선정된 창업기업의 사업비 횡령, 편취 등",  # 419행 — 선정 뒤 관리
]


@pytest.mark.parametrize("line", AGENCY_LINES)
def test_운영기관_이름만_있는_줄은_역할_조항이_아니다(line: str) -> None:
    """「주관기관」이라는 낱말 하나로 역할 조항이 됐다 — 신청자의 자리가 아니다.

    이 줄들이 「신청 자격 충족 설명」에 인용되면 담당자가 자격 요건으로 읽는다.
    14차가 고친 절차 서술(「검토는 … 진행하며」)과 같은 부류인데 그 모양에 안 맞아 남았다.
    """
    result = extractor.extract_from_text("P", store.join_pages(["○ 신청자격" + chr(10) + line]))

    assert result.of("role") == [], "기관 나열이 역할 조항으로 남았다: " + line


@pytest.mark.parametrize(
    "line",
    [
        "- 주관기관 모집 공고에 따라 신청하는 기관",
        "- 참여기업이 주관기관과 협약을 맺어 신청",
        "- 운영기관으로 참여하려는 기업",
    ],
)
def test_신청_모집_참여가_있으면_그대로_남는다(line: str) -> None:
    """**좁게 잡았다는 증거.** 운영기관 이름 옆에 신청자 동사가 있으면 진짜 요건이다."""
    result = extractor.extract_from_text("P", store.join_pages(["○ 신청자격" + chr(10) + line]))

    assert result.of("role"), "진짜 요건이 사라졌다: " + line
