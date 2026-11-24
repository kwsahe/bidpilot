"""사업계획서 뼈대가 공고문 조항을 본다 (ISSUE-112 · prompt_01 §4-D-1·§4-D-4).

## 무엇이 틀렸나

담당자: 「사업계획서 초안 생성은 어디 갔는지.」

지원사업 6단계의 뼈대는 **공고문을 안 봤다.** 126482 는 공고문에서 「과제별 최대
1억원」·「창업 7년 이내」를 읽어 목록에 적어 놓고도, 뼈대 05 예산·자부담은
「지원 규모·자부담 조건이 **목록 정보에** 없습니다」로 굳어 있었고 02 는 무조건
「업력·제외 대상은 원문 확인 후 보완하세요」였다. 이미 손에 든 조항을 안 쓴 것이다.

## 여기서 지키는 약속

1. 공고문을 읽은 공고는 **조항 원문을 그대로 인용**한다 (요약·재작성 금지).
2. 공고문을 **못 읽은** 공고는 예전 문구가 한 글자도 바뀌지 않는다.
3. 7단계가 초안을 읽어 **아직 안 담긴 조항**을 센다 — 규칙만, LLM 없이.
4. 회사 사실은 **맞은 것만** 적는다. 미입력 값(상시근로자 수·매출 등)을 지어내지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.support_application_service import (
    CLAUSE_MISSING_NOTE,
    draft_outline,
    uncovered_clauses,
)


# ---------------------------------------------------------------------------
# 최소 대역 — 조항 컨테이너와 프로그램. 실호출·파일 읽기 없이 문자열만 쓴다.
# ---------------------------------------------------------------------------


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
    summary: str | None = "사업 개요입니다."
    category: str | None = "창업"
    attachments: list[Any] = field(default_factory=list)
    apply_period_kind: str = "dated"
    apply_period_text: str = "2026-09-01 ~ 2026-09-30"


@dataclass
class _Item:
    key: str
    status: str
    label: str = "항목"


def _items(**overrides: list[_Item]) -> dict[str, list[_Item]]:
    base = {
        "eligibility": [_Item("target", "confirmed")],
        "conditions": [],
        "schedule": [_Item("period", "confirmed")],
        "documents": [],
    }
    base.update(overrides)
    return base


# 126482 공고문에서 뽑힌 실제 조항 문장 (0924.md §2 기준 답안).
MONEY_TEXT = "과제별 최대 1억원"
AGE_TEXT = "창업 7년 이내"

READ = _Requirements(
    document_read=True,
    clauses={
        "money": [_Clause("최대 1억원", MONEY_TEXT, {"kind": "grant"})],
        "founding_years": [_Clause("창업 7년 이내", AGE_TEXT, {"years": 7})],
    },
)
UNREAD = _Requirements(document_read=False)


def _section(outline: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(s for s in outline if s["section"] == name)


# ---------------------------------------------------------------------------


def test_공고문을_읽으면_예산_절이_조항을_인용한다() -> None:
    outline = draft_outline(_Program(), _items(), [], requirements=READ)
    budget = _section(outline, "예산·자부담 계획")

    assert budget["grounded"] is True, "조항을 찾았으면 근거 있음"
    assert budget["basis"] == "최대 1억원"
    assert budget["quotes"] == [MONEY_TEXT], "원문 그대로"
    assert budget["note"] is None


def test_공고문을_못_읽으면_예전_문구_그대로() -> None:
    """회귀 방지 — 목록만 본 공고의 말이 바뀌면 안 된다."""
    outline = draft_outline(_Program(), _items(), [], requirements=UNREAD)
    budget = _section(outline, "예산·자부담 계획")

    assert budget["grounded"] is False
    assert budget["basis"] == "미확인"
    assert budget["note"] == "지원 규모·자부담 조건이 목록 정보에 없습니다. 공고문에서 확인해야 작성할 수 있습니다."
    assert budget["quotes"] == []


def test_requirements_를_안_넘기면_예전_그대로() -> None:
    """기존 호출부·테스트가 그대로 살아야 한다 (선택 인자)."""
    outline = draft_outline(_Program(), _items(), [])
    assert _section(outline, "예산·자부담 계획")["basis"] == "미확인"
    assert _section(outline, "신청 자격 충족 설명")["note"] == "창업 연차 · 제외 대상은 공고 원문에서 확인한 뒤 보완하세요."


def test_신청_자격_절이_조항을_인용하면_보완_문구가_사라진다() -> None:
    outline = draft_outline(_Program(), _items(), [], requirements=READ)
    eligibility = _section(outline, "신청 자격 충족 설명")

    assert AGE_TEXT in eligibility["quotes"]
    assert eligibility["note"] is None, "원문을 이미 인용했으면 「원문 확인 후 보완」이라 하지 않는다"


def test_공고문을_읽고도_조항이_없으면_다른_말을_한다() -> None:
    """「목록 정보에 없다」와 「공고문에서 못 찾았다」는 다른 사실이다."""
    empty_read = _Requirements(document_read=True)
    outline = draft_outline(_Program(), _items(), [], requirements=empty_read)

    assert _section(outline, "예산·자부담 계획")["note"] == CLAUSE_MISSING_NOTE
    assert _section(outline, "신청 자격 충족 설명")["note"] == CLAUSE_MISSING_NOTE


def test_섹션은_여섯_개이고_키가_보존된다() -> None:
    outline = draft_outline(_Program(), _items(), [], requirements=READ)
    assert len(outline) == 6
    for section in outline:
        assert set(section) == {"section", "basis", "grounded", "note", "quotes", "company_facts"}


def test_회사_사실은_맞은_것만_적는다() -> None:
    """규칙이 없으면 빈 목록. 없는 값을 지어내지 않는다."""
    outline = draft_outline(_Program(), _items(), [], requirements=READ, rules=())
    assert _section(outline, "신청 자격 충족 설명")["company_facts"] == []


# ---------------------------------------------------------------------------
# 7단계 — 미반영 조항
# ---------------------------------------------------------------------------


def test_초안에_담긴_조항은_미반영으로_세지_않는다() -> None:
    outline = draft_outline(_Program(), _items(), [], requirements=READ)
    assert uncovered_clauses(outline, READ) == []


def test_초안에_없는_조항을_센다() -> None:
    extra = _Requirements(
        document_read=True,
        clauses={
            "money": [_Clause("최대 1억원", MONEY_TEXT, {"kind": "grant"})],
            "exclusion": [_Clause("제외 대상", "교육·훈련을 주 사업으로 하는 훈련기관은 제외", {})],
        },
    )
    outline = draft_outline(_Program(), _items(), [], requirements=extra)
    # 신청 자격 절이 exclusion 을 인용하므로 미반영은 0 이어야 한다.
    assert uncovered_clauses(outline, extra) == []

    # 초안을 비우면 돈 조항이 미반영이다. 제외 조항은 초안이 싣지 않는 종류라 세지 않는다 — 초안 경로와 같은 규칙
    # (26차 ISSUE-147 · 검수 R26-D-OUTLINE-EXCL). 예전 기대값(2건)은 제외 조항도 「반영 안 됨」으로 셌다.
    empty_outline = [{"section": "x", "basis": "", "grounded": False, "note": None, "quotes": [], "company_facts": []}]
    missing = uncovered_clauses(empty_outline, extra)
    assert missing == [MONEY_TEXT]


def test_공고문을_못_읽으면_미반영을_세지_않는다() -> None:
    """읽은 적 없는 원문을 두고 「반영 안 됐다」고 말할 수 없다."""
    outline = draft_outline(_Program(), _items(), [], requirements=UNREAD)
    assert uncovered_clauses(outline, UNREAD) == []
    assert uncovered_clauses(outline, None) == []


# ---------------------------------------------------------------------------
# 신청 전 점검 문구 (ISSUE-116 · prompt_02 §4-D)
# ---------------------------------------------------------------------------


def test_공고문을_읽었으면_못_찾았다고_적는다() -> None:
    """읽고도 못 찾은 것과 아예 못 본 것은 다른 사실이다."""
    from app.services.support_application_service import _unknown_check_line

    read = _unknown_check_line(["소재 요건"], document_read=True)
    assert read == "공고문에서 못 찾은 항목: 소재 요건 — 원문에서 확인하세요"
    assert "미확인" not in read


def test_공고문을_못_읽었으면_예전_문구_그대로() -> None:
    from app.services.support_application_service import _unknown_check_line

    assert _unknown_check_line(["소재 요건"], document_read=False) == "기업마당 요약에 없는 항목: 소재 요건 — 공고 원문 · 첨부파일에서 확인하세요"


def test_규칙_줄들에_모두_같은_규칙이_걸린다() -> None:
    """§4-D — 조직 형태·인원·연차·매출도 같은 말로 갈린다."""
    from app.services.support_application_service import _unknown_check_line

    for label in ("조직 형태", "고용 인원", "창업 연차", "매출 요건"):
        assert _unknown_check_line([label], document_read=True) == f"공고문에서 못 찾은 항목: {label} — 원문에서 확인하세요"
