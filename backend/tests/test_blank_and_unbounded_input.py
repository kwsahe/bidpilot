"""공백만 있는 이름과 길이 없는 문자열을 거부한다 (ISSUE-013 · TASK-015).

## 무엇을 막는가

검수에서 `ActionCreateRequest(title="                    ")` 가 **201** 로 저장되는 것이
직접 재현됐다. `min_length=1` 은 글자 수만 보므로 공백 20개를 통과시킨다.
`reviewer="   "`, `decided_by="\\t\\n"` 도 같다.

이게 왜 실해인가: 이 시스템에서 BLOCKER 를 CLEARED 로 바꾸는 것은 **사람만** 할 수 있고,
그 사람 이름이 기록의 전부다. 「   」으로 저장되면 누가 판단했는지 다시는 알 수 없다.

두 번째로, `reasons: list[str]` 은 항목 수(20)만 막고 항목 하나의 길이는 무제한이라
1MB 짜리 사유 20개가 그대로 JSON 파일에 들어갔다. 주소·사업영역 배열·서식 `manual`
dict 도 상한이 없었다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.action import ActionCreateRequest, ActionUpdateRequest
from app.schemas.company import CompanyProfileUpdate
from app.schemas.critical_condition import ConditionUpdateRequest
from app.schemas.decision import DecisionRequest
from app.schemas.organization import OrganizationProfileUpdate
from app.schemas.review import ReviewDecisionRequest

#: 공백으로만 이루어진 값들 — 전부 거부되어야 한다.
BLANKS = ["   ", "\t\n", "   ", ""]


@pytest.mark.parametrize("blank", BLANKS)
def test_조치_제목이_공백만이면_거부한다(blank: str) -> None:
    with pytest.raises(ValidationError):
        ActionCreateRequest(title=blank)


@pytest.mark.parametrize("blank", BLANKS)
def test_검토자_이름이_공백만이면_거부한다(blank: str) -> None:
    with pytest.raises(ValidationError):
        ReviewDecisionRequest(procurement_id="p1", status="APPROVED", reviewer=blank)


@pytest.mark.parametrize("blank", BLANKS)
def test_결정자_이름이_공백만이면_거부한다(blank: str) -> None:
    with pytest.raises(ValidationError):
        DecisionRequest(status="GO", decided_by=blank)


@pytest.mark.parametrize("blank", BLANKS)
def test_조건_검토자가_공백만이면_거부한다(blank: str) -> None:
    with pytest.raises(ValidationError):
        ConditionUpdateRequest(status="CLEARED", reviewer=blank)


def test_담당자_이름도_같은_규칙을_쓴다() -> None:
    with pytest.raises(ValidationError):
        ActionCreateRequest(title="증빙 준비", owner="   ")
    with pytest.raises(ValidationError):
        ActionUpdateRequest(owner="\t")


def test_앞뒤_공백은_저장_전에_지운다() -> None:
    """공백을 남겨 두면 「김담당」과 「김담당 」이 다른 사람이 된다."""
    assert ActionCreateRequest(title="  증빙 준비  ").title == "증빙 준비"
    assert DecisionRequest(status="GO", decided_by=" 김담당 ").decided_by == "김담당"


# ---------------------------------------------------------------------------
# 길이 상한
# ---------------------------------------------------------------------------


def test_사유_항목_하나가_무제한으로_길_수_없다() -> None:
    with pytest.raises(ValidationError):
        DecisionRequest(status="HOLD", decided_by="김담당", reasons=["가" * 501])
    # 상한 안쪽은 그대로 통과한다.
    assert DecisionRequest(status="HOLD", decided_by="김담당", reasons=["가" * 500]).reasons


def test_회사_프로필의_배열과_주소에_상한이_있다() -> None:
    base = {"name": "테스트회사", "updated_by": "김담당"}
    with pytest.raises(ValidationError):
        CompanyProfileUpdate(**base, business_domains=["교육"] * 41)
    with pytest.raises(ValidationError):
        CompanyProfileUpdate(**base, business_domains=["가" * 501])
    with pytest.raises(ValidationError):
        CompanyProfileUpdate(**base, address="가" * 201)
    with pytest.raises(ValidationError):
        OrganizationProfileUpdate(**base, phone="0" * 41)
    # 회사 이름도 공백만이면 안 된다.
    with pytest.raises(ValidationError):
        OrganizationProfileUpdate(name="   ", updated_by="김담당")


def test_정상_입력은_그대로_통과한다() -> None:
    profile = OrganizationProfileUpdate(
        name="주식회사 샘플에듀",
        business_domains=["AI 활용 교육", "생성형 AI 교육"],
        preferred_regions=["광주광역시"],
        address="광주광역시 서구",
        phone="062-000-0000",
        updated_by="김담당",
    )
    assert profile.business_domains == ["AI 활용 교육", "생성형 AI 교육"]
