"""마감 상태 — 「마감」과 「종료」와 「상시」를 섞지 않는다.

화면에서 D-29 인 기업마당 공고가 「신청 종료」로 읽히던 문제가 있었다.
원인은 마감 «여부» 판정이 아니라 그 위에 얹히는 «용어» 선택이었지만,
용어를 고르려면 세 가지가 응답에 정확히 실려 있어야 한다:

  1. closed        — 이미 지났는가 (목록과 상세가 같은 값이어야 한다)
  2. deadline      — 언제 지나는가 (기업마당은 그날 23:59 KST)
  3. apply_period_kind — 날짜가 없는 이유 (상시인가, 예산 소진인가, 그냥 미상인가)

셋 중 하나라도 빠지면 화면은 추측할 수밖에 없고, 추측하면 틀린다.
여기서는 그 세 가지가 실제로 실려 나가는지, 그리고 목록과 상세가 갈리지 않는지를 고정한다.

네트워크를 쓰지 않는다 — 서비스 함수를 직접 부른다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.core import storage
from app.schemas.business_opportunity import SupportProgram, UnifiedOpportunity
from app.services import opportunity_service, support_application_service
from app.services.opportunity_service import KST, _closed, _deadline_of_program


def _program(**kwargs) -> SupportProgram:
    base = dict(id="biz-test-1", title="테스트 지원사업", agency="테스트기관")
    base.update(kwargs)
    return SupportProgram(**base)


# ---------------------------------------------------------------------------
# 마감 시각 — 기업마당은 날짜만 온다
# ---------------------------------------------------------------------------


def test_기업마당_마감은_그날_23시_59분_KST다():
    """날짜만 오는 apply_end 를 그날 끝까지로 읽는다.

    UTC 자정으로 읽으면 KST 오전 9시가 되어, 마감 당일 오전부터 마감 처리된다.
    """
    deadline = _deadline_of_program(_program(apply_end=date(2026, 10, 9)))
    assert deadline == datetime(2026, 10, 9, 23, 59, tzinfo=KST)


def test_마감일이_없으면_None이고_0으로_취급하지_않는다():
    assert _deadline_of_program(_program(apply_end=None)) is None


def test_마감_당일_오전에는_아직_마감이_아니다():
    """UTC 자정 해석 회귀 방지 — 이 시각은 KST 10월 9일 오전 9시다."""
    deadline = _deadline_of_program(_program(apply_end=date(2026, 10, 9)))
    morning = datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)
    assert _closed(deadline, morning) is False


def test_마감_다음날에는_마감이다():
    deadline = _deadline_of_program(_program(apply_end=date(2026, 10, 9)))
    after = datetime(2026, 10, 10, 12, 0, tzinfo=KST)
    assert _closed(deadline, after) is True


# ---------------------------------------------------------------------------
# 접수 기간의 성격이 통합 목록까지 내려온다
# ---------------------------------------------------------------------------


def test_통합항목이_접수기간_성격을_담는다():
    """상시·예산 소진을 「신청 종료」로 읽지 않으려면 이 필드가 필요하다."""
    assert "apply_period_kind" in UnifiedOpportunity.model_fields


def test_나라장터_항목의_접수기간_성격은_None이다():
    """이 축은 기업마당에만 있다. 나라장터에 억지로 값을 넣지 않는다."""
    item = UnifiedOpportunity(
        id="g2b-1",
        source_type="g2b",
        opportunity_type="procurement",
        title="t",
        agency="a",
        organization_id="org-sample",
        priority_rank=1,
        priority_label="검토",
        confidence="medium",
        score_components=[],
        next_route={"kind": "procurement_analysis", "path": "/", "label": "l"},
        source="g2b",
    )
    assert item.apply_period_kind is None


@pytest.mark.parametrize("kind", ["always_open", "until_budget", "conditional", "unknown", "dated"])
def test_다섯_가지_접수기간_성격을_모두_담을_수_있다(kind: str):
    program = _program(apply_period_kind=kind)
    assert program.apply_period_kind == kind


# ---------------------------------------------------------------------------
# 목록과 상세가 같은 마감 여부를 말한다
# ---------------------------------------------------------------------------


def test_상세도_실제_마감여부를_쓴다_하드코딩이_아니다():
    """예전에는 상세가 closed=False 로 굳어 있어, 접수가 끝난 사업이
    목록에서는 「마감」인데 상세에서는 「검토」로 나왔다."""
    끝난_사업 = _program(apply_end=storage.kst_today() - timedelta(days=30))
    남은_사업 = _program(apply_end=storage.kst_today() + timedelta(days=30))

    assert support_application_service._program_closed(끝난_사업) is True
    assert support_application_service._program_closed(남은_사업) is False


def test_상세의_마감판정이_목록과_같은_함수를_쓴다():
    """규칙이 두 벌이 되면 언젠가 갈린다. 같은 결과가 나오는지 확인한다.

    **두 쪽이 앱의 같은 시계를 읽는다** (ISSUE-133 · prompt_07 §4-A). 예전에는 목록 쪽에
    `datetime.now()` 를 넘기고 상세는 자기 시계를 읽었다. 시계를 7일 앞당겨 돌리면
    상세만 움직여 「같은 함수를 쓰는데 값이 다르다」가 됐다 — 재려는 것은 규칙이 한 벌인지다.
    """
    program = _program(apply_end=storage.kst_today() + timedelta(days=5))
    now = storage.utc_now()

    목록_판정 = _closed(_deadline_of_program(program), now)
    상세_판정 = support_application_service._program_closed(program)
    assert 목록_판정 == 상세_판정


def test_마감일이_없는_사업은_마감으로_단정하지_않는다():
    """상시 접수를 「종료」로 만들지 않는다."""
    상시 = _program(apply_end=None, apply_period_kind="always_open")
    assert support_application_service._program_closed(상시) is False


# ---------------------------------------------------------------------------
# 기준일은 KST — 서버 시간대에 흔들리지 않는다
# ---------------------------------------------------------------------------


def test_지원적합도_기준일이_KST다():
    """date.today() 는 서버 로컬이라 UTC 서버에서 KST 기준 하루 전이 된다."""
    from app.services import bizinfo_service, opportunity_priority

    program = _program(apply_end=storage.kst_today() + timedelta(days=10))
    fit = bizinfo_service.support_fit(program, organization_id="org-sample")

    # 명시적으로 넘긴 기준일과 기본 기준일이 같은 날을 가리켜야 한다.
    fit_explicit = bizinfo_service.support_fit(
        program, today=opportunity_priority._today(None), organization_id="org-sample"
    )
    assert fit.score == fit_explicit.score
