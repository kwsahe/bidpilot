"""사업계획서 핵심 섹션 생성 — 규칙 경로 (ISSUE-112 · prompt_02 §4-B).

## 무엇이 없었나

6단계는 12차까지 목차 뼈대뿐이었다. 절마다 「근거 있음 / 확인 필요」와 인용은 있어도
담당자가 그대로 옮겨 쓸 **문장**이 없었다. 재검증 10 §3-4 도 「생성 단추가 아직 없다」.

## 여기서 지키는 약속

1. 규칙 경로는 **지어내지 않는다** — 공고문 조항 원문과 이미 판정된 회사 사실뿐.
2. `AI_SUGGESTION` **0건**. AI 문장이 하나도 없다는 뜻이다.
3. 크레딧 0 이면 **LLM 을 부르지 않는다** — mock 으로 단언한다(§4-B-7).
4. 문장 유형은 기존 enum 만 쓴다(`NOTICE_GROUNDED` 는 저장소에 없다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.schemas.proposal import GroundingType
from app.services import llm_client, support_plan_service


@dataclass
class _Clause:
    label: str
    source_text: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Requirements:
    document_read: bool
    clauses: dict[str, list[_Clause]] = field(default_factory=dict)

    def of(self, kind: str) -> list[_Clause]:
        return self.clauses.get(kind, [])


@dataclass
class _Program:
    id: str = "bizinfo-PBLN_000000000126482"
    summary: str | None = "공공기관 제안형 창업기업을 모집합니다."
    category: str | None = "창업"
    apply_period_text: str = "2026-09-01 ~ 2026-09-30"


MONEY = "과제별 최대 1억원"
AGE = "창업 7년 이내"

OUTLINE = [
    {"section": "사업 개요·추진 배경", "basis": "공고 원문(사업 개요)", "grounded": True, "note": None,
     "quotes": [], "company_facts": []},
    # 126482 라이브 실측 그대로 — 자격 절 인용 넷과 회사 사실 하나.
    {"section": "신청 자격 충족 설명", "basis": "공고 원문(지원 대상)", "grounded": True, "note": None,
     "quotes": [
         AGE,
         "밋업(Meet-Up) : 발표평가 대상자와 공공기관과 온·오프라인",
         "⑨ 2026년 동 사업 주관기관의 전담조직의 장, 전담/겸직인력으로 참여 중 또는 참여",
         "협업 과제 1개 신청 가능(중복 신청 불가), 공공기관별 과제 세부내용은 [별첨 1]",
     ],
     "company_facts": ["창업 연차: 2021년 설립(5년차)이다."]},
    {"section": "수행 역량·유사 실적", "basis": "회사 근거 없음", "grounded": False,
     "note": "승인·색인된 회사자료에서 연결된 근거가 없습니다.", "quotes": [], "company_facts": []},
    {"section": "추진 계획·일정", "basis": "공고 원문(신청 기간)", "grounded": True, "note": None,
     "quotes": [], "company_facts": []},
    {"section": "예산·자부담 계획", "basis": "최대 1억원", "grounded": True, "note": None,
     "quotes": [MONEY], "company_facts": []},
    {"section": "기대 효과", "basis": "공고 원문(지원 분야)", "grounded": True, "note": None,
     "quotes": [], "company_facts": []},
]


def _all_sentences(draft: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for section in draft["sections"] for s in section["sentences"]]


def test_섹션_여섯에_문장이_여덟_이상() -> None:
    draft = support_plan_service.generate(_Program(), OUTLINE)
    assert len(draft["sections"]) == 6
    assert draft["sentence_count"] >= 8, draft["sentence_count"]


def test_AI_문장은_0건이고_규칙으로_만들었다고_적는다() -> None:
    draft = support_plan_service.generate(_Program(), OUTLINE)
    assert draft["generated_by"] == "rules"
    assert draft["ai_sentence_count"] == 0
    assert all(s["type"] != support_plan_service.SUGGESTION for s in _all_sentences(draft))


def test_문장_유형은_기존_enum_만_쓴다() -> None:
    """`NOTICE_GROUNDED` 는 저장소에 없다(12차 §5-1).

    **`None` 은 허용한다** (14차 · ISSUE-119 · prompt_03 §4-D-1). 「확인 필요 — …」는
    근거가 아니라 빈칸 표시라 유형이 없다 — 유형을 달아 두었더니 화면이 「공고문 근거」
    배지를 붙여, 근거가 없다는 말에 근거 배지가 달렸다. 대신 **유형이 없으면 반드시
    `note: True`** 여야 한다. 그래야 「유형을 빼먹은 문장」과 구분된다.
    """
    allowed = set(GroundingType.__args__)  # type: ignore[attr-defined]
    for sentence in _all_sentences(support_plan_service.generate(_Program(), OUTLINE)):
        if sentence["type"] is None:
            assert sentence.get("note") is True, f"유형도 없고 안내 표시도 없다: {sentence}"
            continue
        assert sentence["type"] in allowed, sentence


def test_조항은_원문_그대로_인용한다() -> None:
    draft = support_plan_service.generate(_Program(), OUTLINE)
    notice = [s for s in _all_sentences(draft) if s["type"] == support_plan_service.NOTICE]
    assert any(MONEY in s["text"] for s in notice), "예산 조항"
    assert any(AGE in s["text"] for s in notice), "자격 조항"
    # source 에도 원문이 그대로 남아 미반영 대조가 성립한다.
    assert MONEY in {s["source"] for s in notice}


def test_회사_사실은_회사_근거_유형이다() -> None:
    draft = support_plan_service.generate(_Program(), OUTLINE)
    company = [s for s in _all_sentences(draft) if s["type"] == support_plan_service.COMPANY]
    assert any("2021년 설립" in s["text"] for s in company)


def test_근거가_없는_절은_확인_필요로_남긴다() -> None:
    draft = support_plan_service.generate(_Program(), OUTLINE)
    section = next(s for s in draft["sections"] if s["section"] == "수행 역량·유사 실적")
    assert section["grounded"] is False
    assert section["sentences"][0]["text"].startswith("확인 필요")


def test_크레딧이_없으면_LLM_을_부르지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """§4-B-7 — mock 으로 단언한다."""
    monkeypatch.setattr(llm_client, "credit_ok", lambda: False)
    calls: list[str] = []
    monkeypatch.setattr(llm_client, "complete_structured", lambda **_: calls.append("llm"))

    draft = support_plan_service.generate(_Program(), OUTLINE)

    assert calls == [], "크레딧 0 에서 LLM 을 불렀다"
    assert draft["generated_by"] == "rules"


def test_크레딧이_있어도_다듬기는_아직_규칙으로_떨어진다(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 다듬기는 돌려본 적이 없어 일부러 비워 두었다 — 화면이 멈추지 않아야 한다."""
    monkeypatch.setattr(llm_client, "credit_ok", lambda: True)
    draft = support_plan_service.generate(_Program(), OUTLINE)
    assert draft["generated_by"] == "rules"
    assert draft["ai_sentence_count"] == 0


def test_미반영_조항은_초안_기준으로_센다() -> None:
    requirements = _Requirements(
        document_read=True,
        clauses={
            "money": [_Clause("최대 1억원", MONEY)],
            "founding_years": [_Clause("창업 7년 이내", AGE)],
            "prerequisite": [_Clause("보유 요건", "기업부설연구소를 보유한 기업")],
            "exclusion": [_Clause("제외", "교육·훈련을 주 사업으로 하는 훈련기관은 제외")],
        },
    )
    draft = support_plan_service.generate(_Program(), OUTLINE)
    missing = support_plan_service.uncovered_quotes(draft, requirements)

    assert MONEY not in missing, "초안이 담은 조항"
    assert AGE not in missing
    assert "기업부설연구소를 보유한 기업" in missing, "담지 않은 조항"
    # 26차 ISSUE-147 — 제외 조항은 초안이 싣지 않는다(route_clauses 와 같은 상수). 신청 전 점검의 「제외 대상」 줄이 따로 말한다.
    # 예전 기대값(제외 조항도 미반영으로 센다)은 새로 만든 초안마다 지울 수 없는 경고를 붙였다.
    assert "교육·훈련을 주 사업으로 하는 훈련기관은 제외" not in missing


def test_공고문을_못_읽었으면_미반영을_세지_않는다() -> None:
    draft = support_plan_service.generate(_Program(), OUTLINE)
    assert support_plan_service.uncovered_quotes(draft, _Requirements(document_read=False)) == []
    assert support_plan_service.uncovered_quotes(draft, None) == []
