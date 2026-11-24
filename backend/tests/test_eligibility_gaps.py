"""갭 리포트 — 「무엇을 갖추면 몇 건이 열리는가」 (0921.md §4-B).

담당자가 목록에서 보는 것은 「불가 41건」이다. 그 41건이 **영영 불가**인지 **서류 한 장이면
열리는지**는 다른 이야기다. 검수자의 기준 답안은 「개발 공고 15건 중 9건이 소프트웨어사업자
(1468) 등록 업체만 투찰 가능」이라고 적었다 — 신고 한 번이면 9건이 열린다는 뜻이다.

여기서 지키는 약속 셋.

1. **조건이 붙지 않은 다른 불가가 있으면 세지 않는다.** 그 조건을 갖춰도 안 열리기 때문이다.
2. **「불가가 풀린다」와 「판정이 확정된다」를 합치지 않는다.** 확정 결과가 「가능」이라는
   보장은 없다.
3. **한 공고를 두 번 세지 않는다.** 같은 조건이 여러 규칙에 붙을 수 있다(등록 마감·입찰
   마감이 둘 다 촉박인 경우).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.schemas.organization import AnalysisContext
from app.services import eligibility_engine, eligibility_gap_service, procurement_service

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 17, 3, 0, tzinfo=timezone.utc)
ORG = "org-sample"


def notice(nid: str, **fields: Any) -> procurement_service.NoticeView:
    from app.schemas.procurement import ProcurementNotice
    from app.services.opportunity_filter import classify

    raw = {"source": "g2b", "item": {"bidNtceNo": nid, "bidNtceOrd": "000", **fields}}
    model = ProcurementNotice(
        id=f"g2b-{nid}-000",
        notice_no=f"{nid}-000",
        title="생성형 AI 활용 교육 운영 용역",
        agency="시험기관",
        published_at=NOW - timedelta(days=2),
        deadline_at=NOW + timedelta(days=30),
        budget=fields.get("_budget"),
        region=None,
        description=None,
        source_url=None,
        raw_data=raw,
    )
    return procurement_service.NoticeView(notice=model, match=classify(model))


@pytest.fixture()
def context() -> AnalysisContext:
    return AnalysisContext(organization_id=ORG, evidence_scope="internal")


def build(views: list[procurement_service.NoticeView], monkeypatch: pytest.MonkeyPatch, context: AnalysisContext,
          company: eligibility_engine.CompanyFacts | None = None) -> dict[str, Any]:
    async def _list(**_kwargs: object) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(notices=views)

    monkeypatch.setattr(procurement_service, "list_ai_candidates", _list)
    monkeypatch.setattr(
        eligibility_engine, "company_facts_for", lambda _org: company or eligibility_engine.CompanyFacts()
    )
    return asyncio.run(eligibility_gap_service.build(context=context, days=30, now=NOW))


def gap_for(report: dict[str, Any], needle: str) -> dict[str, Any] | None:
    for gap in report["gaps"]:
        if needle in gap["condition"]:
            return gap
    return None


# ---------------------------------------------------------------------------


def test_업종을_적으면_몇_건이_확정되는지_센다(monkeypatch: pytest.MonkeyPatch, context: AnalysisContext) -> None:
    """면허제한 목록이 실제로 오면 코드·이름까지 말한다 (0922 §4-A-4)."""
    views = [notice("R1", indstrytyLmtYn="Y"), notice("R2", indstrytyLmtYn="Y"), notice("R3", indstrytyLmtYn="N")]
    for view in views[:2]:
        view.notice.raw_data["license_limits"] = [
            {"name": "소프트웨어사업자(컴퓨터관련서비스사업)", "code": "1468", "allowed_industries": []}
        ]
        view.notice.raw_data["allowed_regions"] = []
    report = build(views, monkeypatch, context)
    gap = gap_for(report, "1468")
    assert gap is not None
    assert gap["pending"] == 2
    assert gap["rule_id"] == "ELIG-INDUSTRY"


def test_자격_정보를_아직_못_받았으면_그렇게_말한다(
    monkeypatch: pytest.MonkeyPatch, context: AnalysisContext
) -> None:
    """업종제한 공고인데 그 날의 자격 정보가 없다 — 「제한 없음」이 아니라 「미수집」이다."""
    report = build([notice("R1", indstrytyLmtYn="Y")], monkeypatch, context)
    gap = gap_for(report, "자격 정보를 받으면")
    assert gap is not None and gap["pending"] == 1


def test_등록_업종이_맞지_않으면_불가이고_열리는_조건을_말한다(
    monkeypatch: pytest.MonkeyPatch, context: AnalysisContext
) -> None:
    """면허제한 목록이 실제로 오면 「1468 등록 시 가능」을 이름까지 말할 수 있다(공동수급 불허 — 44차 결정 4 이후 불가는 불허만)."""
    raw_extra = {"indstrytyLmtYn": "Y", "cmmnSpldmdMethdNm": "(없음)공동수급불허"}
    view = notice("R9", **raw_extra)
    view.notice.raw_data["license_limits"] = [
        {"name": "소프트웨어사업자", "code": "1468", "allowed_industries": ["1468"]}
    ]
    report = build(
        [view],
        monkeypatch,
        context,
        company=eligibility_engine.CompanyFacts(registered_industry_codes=("1169",)),
    )
    gap = gap_for(report, "1468")
    assert gap is not None
    assert gap["blocked"] == 1
    assert report["blocked_total"] == 1


def test_공동수급_허용이면_확인_필요라도_갭_보고가_계속_센다(monkeypatch: pytest.MonkeyPatch, context: AnalysisContext) -> None:
    """44차 결정 4 — 업종 없음 · 공동수급 허용은 「확인 필요」(파트너형)지만 「1468 등록 시」는 그대로 센다(확정을 막는 수)."""
    view = notice("R7", indstrytyLmtYn="Y", cmmnSpldmdMethdNm="(전자)공동이행")
    view.notice.raw_data["license_limits"] = [{"name": "소프트웨어사업자", "code": "1468", "allowed_industries": ["1468"]}]
    report = build([view], monkeypatch, context, company=eligibility_engine.CompanyFacts(registered_industry_codes=("1169",)))
    gap = gap_for(report, "1468")
    assert gap is not None and gap["blocked"] == 0 and gap["pending"] == 1


def test_다른_이유로도_막혀_있으면_세지_않는다(monkeypatch: pytest.MonkeyPatch, context: AnalysisContext) -> None:
    """업종을 등록해도 취소된 공고는 열리지 않는다."""
    view = notice("R8", indstrytyLmtYn="Y", ntceKindNm="취소공고")
    view.notice.raw_data["license_limits"] = [
        {"name": "소프트웨어사업자", "code": "1468", "allowed_industries": ["1468"]}
    ]
    report = build(
        [view],
        monkeypatch,
        context,
        company=eligibility_engine.CompanyFacts(registered_industry_codes=("1169",)),
    )
    # 9차부터는 「막는 0 · 확정 0」인 줄을 아예 내려보내지 않는다 (0923 §3-1 · ISSUE-091).
    # 「0건이 열린다」는 줄은 「등록하면 뭔가 생긴다」는 잘못된 인상만 남긴다.
    assert gap_for(report, "1468") is None, "취소공고는 업종을 갖춰도 열리지 않는다"


def test_촉박은_막는_조건이_아니다(monkeypatch: pytest.MonkeyPatch, context: AnalysisContext) -> None:
    """37차 D3(담당자 결정 2026-10-14) — 등록 마감 · 입찰 마감이 둘 다 촉박해도 「불가」가 아니라 「확인 필요 · 촉박」이다.

    예전에는 「준비 일수를 줄이면 후보로 돌아옵니다」가 두 규칙에 붙어 한 공고를 두 번 세지 않는지 쟀다. 이제 숨기지 않으므로
    막는 조건(갭)으로 세지 않는다.
    """
    soon = (NOW + timedelta(days=1)).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
    view = notice("R7", bidQlfctRgstDt=soon, bidClseDt=soon)
    view.notice.deadline_at = NOW + timedelta(days=1)
    report = build([view], monkeypatch, context)
    assert gap_for(report, "준비 일수") is None
    assert report["blocked_total"] == 0


def test_막고_있는_건수는_전체_불가를_넘지_않는다(monkeypatch: pytest.MonkeyPatch, context: AnalysisContext) -> None:
    soon = (NOW + timedelta(days=1)).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
    views = [notice(f"R{i}", bidQlfctRgstDt=soon, bidClseDt=soon) for i in range(5)]
    for view in views:
        view.notice.deadline_at = NOW + timedelta(days=1)
    report = build(views, monkeypatch, context)
    for gap in report["gaps"]:
        assert gap["blocked"] <= report["blocked_total"]


def test_불가가_풀리는_것과_판정이_확정되는_것을_합치지_않는다(
    monkeypatch: pytest.MonkeyPatch, context: AnalysisContext
) -> None:
    """갖추면 판정이 확정될 뿐, 결과가 「가능」이라는 보장은 없다."""
    view = notice("R6", indstrytyLmtYn="Y")
    view.notice.raw_data["license_limits"] = [
        {"name": "소프트웨어사업자(컴퓨터관련서비스사업)", "code": "1468", "allowed_industries": []}
    ]
    report = build([view], monkeypatch, context)
    gap = gap_for(report, "1468")
    assert gap is not None
    assert gap["blocked"] == 0 and gap["pending"] == 1
    assert "가능이라는 뜻은 아닙니다" in report["note"]


def test_아무것도_붙잡지_않는_조건은_목록에_없다(
    monkeypatch: pytest.MonkeyPatch, context: AnalysisContext
) -> None:
    """「막는 0 · 확정 0」인 줄은 내려보내지 않는다 (0923 §3-1 · ISSUE-091).

    공고가 「국내외여행업(1262)」을 요구하면서 **동시에 취소공고**이면, 그 업종을 등록해도
    열리지 않고 확정되지도 않는다. 실측에서 그런 줄이 여덟 개 있었고 전부 0 · 0 이었다.
    """
    view = notice("R9", indstrytyLmtYn="Y", ntceKindNm="취소공고")
    view.notice.raw_data["license_limits"] = [
        {"name": "국내외여행업", "code": "1262", "allowed_industries": ["1262"]}
    ]
    report = build(
        [view],
        monkeypatch,
        context,
        company=eligibility_engine.CompanyFacts(registered_industry_codes=("1169",)),
    )
    assert gap_for(report, "1262") is None, "0 · 0 인 조건이 목록에 남아 있다"
    for gap in report["gaps"]:
        assert gap["blocked"] or gap["pending"], f"0 · 0 인 줄이 남았다: {gap['condition']}"
    # 뺐다는 사실 자체는 숨기지 않는다.
    assert report["empty_dropped"] >= 1
