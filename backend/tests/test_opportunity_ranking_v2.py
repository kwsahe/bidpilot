"""그룹·순위·「왜 맞나」 (0921.md §4-C).

## 무엇이 틀렸나

1. **개발형 상한 0.45 가 조건 없이 걸려 있었다.** 「샘플에듀의 주된 일은 교육」이라는 전제로
   건 상한인데, 회사 사업영역에는 「AI SaaS·소프트웨어 개발」이 적혀 있다. 실측에서
   검수자가 손으로 고른 1~3순위(한양사이버대 챗봇·한남대 RAG·KISTI 군 장병 AI 교육)가
   전부 53점으로 묶여 목록 아래에 깔려 있었다.
2. **참가할 수 없는 사업 1,002건이 목록에 그대로 있었다.** 대부분 다른 지역 사업이다.
3. **카드에 「왜 맞나」 한 줄이 없었다.** 이유가 여러 줄 붙어 있는데 담당자가 100건을
   훑을 때 읽는 것은 첫 줄 하나다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import opportunity_priority as priority, work_kinds

NOW = datetime(2026, 9, 17, 3, 0, tzinfo=timezone.utc)


def profile(domains: list[str]) -> Any:
    return SimpleNamespace(business_domains=domains, preferred_regions=["광주광역시"])


def skill(name: str, level: str = "proven", aliases: tuple[str, ...] = ()) -> Any:
    return SimpleNamespace(name=name, level=level, aliases=aliases)


def capacity(*skills: Any) -> Any:
    return SimpleNamespace(skills=list(skills))


# ---------------------------------------------------------------------------
# 개발형 상한 (§4-C-2)
# ---------------------------------------------------------------------------


def test_회사가_개발을_한다고_적었으면_개발형_상한을_두지_않는다() -> None:
    assert priority._company_develops(profile(["AI SaaS·소프트웨어 개발", "AI 교육"])) is True
    assert priority._company_develops(profile(["AI 활용 교육", "ESG 컨설팅"])) is False


def test_판단은_회사가_적은_값으로_한다() -> None:
    """시스템이 「이 회사는 교육 회사」라고 단정하지 않는다."""
    assert priority._company_develops(profile([])) is False
    assert priority._company_develops(profile(["시스템 구축"])) is True


# ---------------------------------------------------------------------------
# 갈래 (§4-C-1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "classification, expected",
    [
        ("정보시스템개발서비스", ["development"]),
        ("패키지소프트웨어개발및도입서비스", ["development"]),
        ("정보화교육서비스", ["education"]),
        ("기타교육서비스", ["education"]),
        ("정보시스템감리서비스", ["audit"]),
        ("기타연구조사서비스", ["research"]),
        ("숙박서비스", []),
        (None, []),
    ],
)
def test_조달_분류명이_갈래를_직접_말해_준다(classification: str | None, expected: list[str]) -> None:
    """공고명만 보면 「AI 활용 역량 강화」가 교육인지 개발인지 흐린데, 조달청 분류는 정해 두었다."""
    assert work_kinds.classification_kinds(classification) == expected


def test_분류는_낱말_규칙을_덮어쓰지_않고_더한다() -> None:
    """분류가 개발이라고 해서 교육 과업이 없는 것은 아니다."""
    from app.schemas.procurement import ProcurementNotice

    notice = ProcurementNotice(
        id="g2b-X-000",
        notice_no="X-000",
        title="생성형 AI 교육과정 운영 위탁",
        agency="시험기관",
        published_at=NOW,
        deadline_at=NOW + timedelta(days=10),
        budget=None,
        region=None,
        description=None,
        source_url=None,
        raw_data={"procurement_class": "정보시스템개발서비스"},
    )
    # 43차 결정 4 — 제목이 갈래(교육 운영)를 말하면 제목 먼저 · 조달 분류는 제목에 갈래가 없을 때만 더한다
    result = work_kinds.of_notice(notice)
    assert result["kinds"] == ["education"]
    untitled = notice.model_copy(update={"title": "생성형 AI 활용 위탁 사업"})
    result = work_kinds.of_notice(untitled)
    assert "development" in result["kinds"]


# ---------------------------------------------------------------------------
# 「왜 맞나」·「주의」 (§4-C-3)
# ---------------------------------------------------------------------------


def test_검증된_역량만_왜_맞나에_적는다() -> None:
    """「해 본 적 있다」와 「검증했다」는 다른 사실이다."""
    cap = capacity(skill("RAG", aliases=("검색증강",)), skill("블록체인", level="claimed"))
    assert priority.proven_skill_hits(cap, "철도 도메인 RAG 기반 안전교관 시스템") == ["RAG"]
    assert priority.proven_skill_hits(cap, "블록체인 기반 인증 시스템") == []


def test_별칭으로도_찾는다() -> None:
    cap = capacity(skill("RAG", aliases=("검색증강", "지식 검색")))
    assert priority.proven_skill_hits(cap, "지식 검색 서비스 구축") == ["RAG"]


def test_왜_맞나는_역량_갈래_분류_예산_마감을_한_줄로() -> None:
    line = priority.fit_line(
        text="철도 RAG 기반 AI 안전교관 시스템 구축",
        tracks=["development"],
        procurement_class="정보시스템개발서비스",
        budget=130_000_000,
        days_left=11.4,
        capacity=capacity(skill("RAG")),
    )
    assert line is not None
    assert "해 본 일: RAG" in line
    assert "개발형" in line and "정보시스템개발서비스" in line
    assert "1.3억" in line
    # 소수가 화면에 새면 안 된다.
    assert "마감까지 11일" in line and "." not in line.split("마감까지 ")[1]


def test_근거가_하나도_없으면_빈_말을_만들지_않는다() -> None:
    assert priority.fit_line(
        text="무엇인지 알 수 없는 공고", tracks=[], procurement_class=None,
        budget=None, days_left=None, capacity=None,
    ) is None


def test_주의는_규모_상단과_마감_촉박을_말한다() -> None:
    over = priority.caution_line(
        budget=300_000_000, ceiling=200_000_000, days_left=20, lead_days=4,
        joint_allowed=True, out_of_scope=False,
    )
    assert over and "규모 큼" in over and "함께 입찰 권장" in over

    blocked = priority.caution_line(
        budget=300_000_000, ceiling=200_000_000, days_left=20, lead_days=4,
        joint_allowed=False, out_of_scope=False,
    )
    assert blocked and "함께 입찰 안 됨" in blocked and "혼자는 어렵고" not in blocked  # 33차 — 회사 기준이라 단정하지 않는다

    urgent = priority.caution_line(
        budget=None, ceiling=None, days_left=2, lead_days=4, joint_allowed=None, out_of_scope=False,
    )
    assert urgent and "마감 2일 남음 — 준비 시간 부족" in urgent


def test_상한을_안_적었으면_큰_건에만_말한다() -> None:
    """회사 상한이 없다고 모든 공고에 「규모 상단」을 붙이면 경고가 배경 소음이 된다."""
    assert priority.caution_line(
        budget=30_000_000, ceiling=None, days_left=20, lead_days=4, joint_allowed=None, out_of_scope=False,
    ) is None
    big = priority.caution_line(
        budget=200_000_000, ceiling=None, days_left=20, lead_days=4, joint_allowed=None, out_of_scope=False,
    )
    assert big and "혼자 맡을 수 있는 금액" in big


def test_볼_것이_없으면_주의를_만들지_않는다() -> None:
    assert priority.caution_line(
        budget=30_000_000, ceiling=200_000_000, days_left=20, lead_days=4,
        joint_allowed=None, out_of_scope=False,
    ) is None
