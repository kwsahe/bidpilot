"""참가자격 판정 엔진 테스트.

- 네트워크 호출 없음: 공고는 인라인 fixture, 요구사항은 저장소의 실제 파싱 결과를 읽는다.
- LLM은 monkeypatch로 대체한다. **LLM이 죽어도 규칙 결과가 완전해야** 한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import eligibility as eligibility_api
from app.schemas.procurement import ProcurementNotice
from app.schemas.requirement import RfpParseResult
from app.core.money import won
from app.services import eligibility_engine, llm_client, procurement_service, rfp_parser
from app.services.opportunity_filter import CandidateMatch

KST = timezone(timedelta(hours=9))
BEFORE_DEADLINE = datetime(2026, 8, 25, 9, 0, tzinfo=KST)
AFTER_DEADLINE = datetime(2026, 9, 3, 9, 0, tzinfo=KST)

SYNTHETIC_ID = "synthetic-rfp-0001"


def make_notice(**item_overrides: Any) -> procurement_service.NoticeView:
    """실제 나라장터 응답에서 확인한 필드명만 사용한 공고 fixture."""
    item: dict[str, Any] = {
        "bidNtceNo": "R26TEST00000001",
        "cntrctCnclsMthdNm": "일반경쟁",
        "bidQlfctRgstDt": "2026-08-31 18:00",
        "bidClseDt": "2026-09-01 10:00:00",
        "indstrytyLmtYn": "N",
        "bidPrtcptLmtYn": "N",
        "cmmnSpldmdCorpRgnLmtYn": "N",
        "jntcontrctDutyRgnNm1": "",
        "rgnLmtBidLocplcJdgmBssNm": "",
        "asignBdgtAmt": "55098630",
        "presmptPrce": "54947627",
    }
    item.update(item_overrides)
    notice = ProcurementNotice(
        id="g2b-TEST-000",
        notice_no="R26TEST00000001-000",
        title="AI 활용 실무교육 운영 용역",
        agency="테스트기관",
        published_at=datetime(2026, 8, 20, 10, 0, tzinfo=KST),
        raw_data={"source": "g2b", "item": item},
    )
    return procurement_service.NoticeView(
        notice=notice,
        match=CandidateMatch(tier="high", matched_ai=["AI"], matched_work=["교육"]),
    )


@pytest.fixture()
def synthetic_requirements() -> RfpParseResult:
    return rfp_parser.load_generated(SYNTHETIC_ID)


def result_by_id(report: Any, rule_id: str) -> Any:
    match = [r for r in report.results if r.rule_id == rule_id]
    assert match, f"{rule_id} 규칙이 없습니다: {[r.rule_id for r in report.results]}"
    return match[0]


def evaluate(notice: Any, parse_result: Any, as_of: datetime, company: Any = None) -> Any:
    """회사 쪽 사실은 **인자로 넘긴다** (0921 §4-B).

    진입점이 ContextVar 를 직접 세팅하므로 바깥에서 미리 넣어 둔 값은 덮인다 —
    운영 코드와 같은 길로 넣어야 테스트가 실제 동작을 잰다.
    """
    return eligibility_engine.evaluate_from_sources(
        SYNTHETIC_ID,
        notice=notice,
        parse_result=parse_result,
        as_of=as_of,
        use_llm=False,
        company=company,
    )


# ---------------------------------------------------------------------------
# 공고 필드 규칙
# ---------------------------------------------------------------------------


def test_deadline_passed_is_fail() -> None:
    report = evaluate(make_notice(), None, AFTER_DEADLINE)
    qual = result_by_id(report, "ELIG-QUALIFICATION-DEADLINE")
    assert qual.status == "FAIL"
    assert "참가자격 등록 마감: 2026-08-31 18:00" in qual.source
    assert report.verdict == "FAIL"


def test_근거는_API_필드명이_아니라_사람_말로_적는다(synthetic_requirements: RfpParseResult) -> None:
    """DTL-26 — 화면 「근거:」에 「rgnLmtBidLocplcJdgmBssNm=(없음)」 · 「procurement_service.get_notice(…)」가 나왔다.

    필드 이름은 한국어로, 값은 원문 그대로 남는다(위 시험들이 값을 본다).
    """
    import re

    report = evaluate(make_notice(), None, BEFORE_DEADLINE)
    # 34차 R33-D2 — 이 공고는 참가가능지역(자격 정보)을 받아 본 적이 없다 → 「미수집」이라고 사람 말로 적는다
    assert result_by_id(report, "ELIG-REGION").source == "공고 참가가능지역 — 자격 정보 미수집"
    assert result_by_id(report, "ELIG-BUDGET").source == f"나라장터 기본정보 — 배정예산: {won(55098630)} · 추정가격: {won(54947627)}"
    missing = evaluate(None, synthetic_requirements, BEFORE_DEADLINE)
    assert result_by_id(missing, "ELIG-NOTICE-DATA").source == "공고 정보를 찾지 못함"
    for result in [*report.results, *missing.results]:
        assert not re.search(r"[A-Za-z_]{6,}[=(]|\.json|COMPANY_PROFILE", result.source), (result.rule_id, result.source)


def test_open_deadline_is_pass() -> None:
    report = evaluate(make_notice(), None, BEFORE_DEADLINE)
    assert result_by_id(report, "ELIG-QUALIFICATION-DEADLINE").status == "PASS"
    assert result_by_id(report, "ELIG-BID-DEADLINE").status == "PASS"


def test_region_limit_outside_company_region_is_fail() -> None:
    report = evaluate(
        make_notice(rgnLmtBidLocplcJdgmBssNm="울산광역시"), None, BEFORE_DEADLINE
    )
    region = result_by_id(report, "ELIG-REGION")
    assert region.status == "FAIL"
    assert "울산광역시" in region.source


def test_region_limit_inside_company_region_is_pass() -> None:
    report = evaluate(
        make_notice(rgnLmtBidLocplcJdgmBssNm="광주광역시"), None, BEFORE_DEADLINE
    )
    assert result_by_id(report, "ELIG-REGION").status == "PASS"


def test_region_alias_matches_short_form() -> None:
    report = evaluate(make_notice(rgnLmtBidLocplcJdgmBssNm="전남"), None, BEFORE_DEADLINE)
    assert result_by_id(report, "ELIG-REGION").status == "PASS"


def test_판단기준_이름만_있으면_지역제한은_FAIL_이_아니라_CHECK() -> None:
    """rgnLmtBidLocplcJdgmBssNm 에는 지역 이름이 아니라 «판단기준의 이름»이 오는 쪽이 흔하다.

    캐시된 실응답 76건 중 53건이 「본사또는참여지사소재지」·「본사소재지」였고 지역 이름은 없었다.
    그것을 지역으로 읽어 회사 활동 지역과 다르다며 FAIL 을 내고 있었다 — 대상 지역을 모르는데
    참가 불가로 단정한 것이다. 모르면 CHECK 이고, 무엇을 확인해야 하는지 사유에 적는다.
    """
    for basis in ("본사또는참여지사소재지", "본사소재지"):
        report = evaluate(make_notice(rgnLmtBidLocplcJdgmBssNm=basis), None, BEFORE_DEADLINE)
        region = result_by_id(report, "ELIG-REGION")
        assert region.status == "CHECK", f"{basis} 는 지역 이름이 아니므로 FAIL 이 될 수 없다"
        assert basis in region.source  # 근거는 원문 필드 그대로 남긴다
        assert "대상 지역" in region.reason
        assert report.verdict != "FAIL"


def test_공고_필드만으로도_돌아가는_규칙표를_목록이_재사용할_수_있다() -> None:
    """목록 단계용 진입점. RFP 없이 공고 raw_data 만으로 완전한 결과가 나와야 한다."""
    raw = make_notice().notice.raw_data
    results = eligibility_engine.evaluate_notice_fields(
        raw, as_of=BEFORE_DEADLINE, regions=("광주광역시", "전라남도")
    )
    assert results and all(r.method == "RULE" for r in results)
    assert not [r for r in results if r.status == "FAIL"]

    # 활동 지역이 비어 있으면 합성 기본 프로필로 슬쩍 판정하지 않는다 — 확인 대상이다.
    empty_profile = eligibility_engine.evaluate_notice_fields(
        {"item": {"rgnLmtBidLocplcJdgmBssNm": "울산광역시"}}, as_of=BEFORE_DEADLINE, regions=()
    )
    region = next(r for r in empty_profile if r.rule_id == "ELIG-REGION")
    assert region.status == "CHECK"

    # 활동 지역이 있고 대상 지역이 실제로 다르면 그때는 FAIL 이다 (이 판정은 남아 있어야 한다).
    mismatched = eligibility_engine.evaluate_notice_fields(
        {"item": {"rgnLmtBidLocplcJdgmBssNm": "울산광역시"}},
        as_of=BEFORE_DEADLINE,
        regions=("광주광역시", "전라남도"),
    )
    assert next(r for r in mismatched if r.rule_id == "ELIG-REGION").status == "FAIL"


def test_industry_limit_is_check_never_pass() -> None:
    report = evaluate(make_notice(indstrytyLmtYn="Y"), None, BEFORE_DEADLINE)
    industry = result_by_id(report, "ELIG-INDUSTRY")
    assert industry.status == "CHECK"
    assert industry.method == "RULE"
    assert report.verdict == "CHECK"


def test_participation_limit_and_restricted_contract_are_check() -> None:
    """참가제한은 이제 `ELIG-TRACK-RECORD` 다 (0921 §4-B).

    실적평가 여부(`arsltCmptYn`)를 함께 보게 되면서 「무엇 때문에 확인해야 하는가」를
    말할 수 있게 됐다 — 이름을 그에 맞췄고, 근거 두 필드를 한 줄에 함께 적는다.
    """
    report = evaluate(
        make_notice(bidPrtcptLmtYn="Y", cntrctCnclsMthdNm="제한경쟁"), None, BEFORE_DEADLINE
    )
    track = result_by_id(report, "ELIG-TRACK-RECORD")
    assert track.status == "CHECK"
    assert "참가제한 여부: 예" in track.source
    # 「제한경쟁」은 자격 문제가 아니라 «어떻게 뽑는가»다 (0921 §4-B).
    # `ELIG-CONTRACT-METHOD` 를 목록에서 뺐고, 그 정보는 `ELIG-AWARD` 가 한 줄로 말한다.
    assert all(r.rule_id != "ELIG-CONTRACT-METHOD" for r in report.results)
    award = result_by_id(report, "ELIG-AWARD")
    assert award.status == "PASS"
    assert "제한경쟁" in award.reason


def test_실적평가_공고는_실적_원장과_대조하라고_말한다() -> None:
    report = evaluate(make_notice(arsltCmptYn="Y"), None, BEFORE_DEADLINE)
    track = result_by_id(report, "ELIG-TRACK-RECORD")
    assert track.status == "CHECK"
    assert "실적" in track.reason
    assert "실적평가 여부: 예" in track.source


def test_joint_duty_region_is_check_only_when_present() -> None:
    without = evaluate(make_notice(), None, BEFORE_DEADLINE)
    assert all(r.rule_id != "ELIG-JOINT-REGION" for r in without.results)

    with_duty = evaluate(
        make_notice(jntcontrctDutyRgnNm1="울산광역시"), None, BEFORE_DEADLINE
    )
    joint = result_by_id(with_duty, "ELIG-JOINT-REGION")
    assert joint.status == "CHECK"
    assert "울산광역시" in joint.source


def test_large_budget_is_check_not_fail() -> None:
    report = evaluate(make_notice(asignBdgtAmt="1200000000"), None, BEFORE_DEADLINE)
    budget = result_by_id(report, "ELIG-BUDGET")
    assert budget.status == "CHECK"
    assert report.verdict == "CHECK"


def test_budget_within_capacity_is_pass_and_verdict_pass() -> None:
    """상한은 **회사가 적은 값**이다 (0921 §4-B).

    예전에는 합성 프로필의 3억을 썼다. 그것은 시스템이 지어낸 숫자라 그 값으로 「가능」을
    말할 수 없다 — 회사가 적었을 때만 확정한다. 안 적었으면 「확인 필요」이고, 무엇을 하면
    판정할 수 있는지(「상한을 적으면」)를 함께 말한다.
    """
    unset = evaluate(make_notice(), None, BEFORE_DEADLINE)
    budget_unset = result_by_id(unset, "ELIG-BUDGET")
    assert budget_unset.status == "CHECK"
    assert budget_unset.unlock_condition and "최대 사업비" in budget_unset.unlock_condition

    report = evaluate(
        make_notice(),
        None,
        BEFORE_DEADLINE,
        company=eligibility_engine.CompanyFacts(budget_ceiling_krw=300_000_000),
    )
    assert result_by_id(report, "ELIG-BUDGET").status == "PASS"
    # 요구사항이 없으면 RFP 자격 조항 미검토 CHECK가 붙는다 (조용히 PASS 금지).
    assert result_by_id(report, "ELIG-RFP-DATA").status == "CHECK"
    assert report.verdict == "CHECK"


# ---------------------------------------------------------------------------
# RFP 요구사항 기반 규칙 (실제 파싱 결과 사용)
# ---------------------------------------------------------------------------


def test_registration_requirement_is_linked_to_pass(
    synthetic_requirements: RfpParseResult,
) -> None:
    report = evaluate(make_notice(), synthetic_requirements, BEFORE_DEADLINE)
    registration = result_by_id(report, "ELIG-REGISTRATION")
    assert registration.status == "PASS"
    assert registration.requirement_id == "REQ-009"
    assert "제안요청서 4쪽" in registration.source


def test_공동수급_불허_조항은_가능이_아니라_원문_확인이다(synthetic_requirements: RfpParseResult) -> None:
    """불허는 가능이 아니다 (19차 §4-B) — 단독 수행 여부는 규모 규칙이 본다.

    예전에는 합성 프로필의 「단독 수행 가능」으로 가능이라 했다 — 회사가 적은 적 없는 사실이었다.
    20차부터 조항은 하나씩 확인하므로 제 줄을 갖고, 필드와 같다는 것을 적은 원문 확인이다.
    """
    report = evaluate(make_notice(), synthetic_requirements, BEFORE_DEADLINE)
    consortium = result_by_id(report, "QUAL-CONSORTIUM-REQ-010")
    assert consortium.status == "CHECK" and consortium.check_side == "notice"
    assert "불허 조항" in consortium.reason
    assert "제안요청서 " in consortium.source and "쪽" in consortium.source
    assert result_by_id(report, "ELIG-AWARD").clause_id is None


def test_공동수급_조항과_필드가_다르면_확인_필요(synthetic_requirements: RfpParseResult) -> None:
    """RFP 는 「공동수급 없이 단독」인데 공고 필드는 공동이행 — 원문이 우선이지만 사람이 본다."""
    report = evaluate(make_notice(cmmnSpldmdMethdNm="(전자)공동이행"), synthetic_requirements, BEFORE_DEADLINE)
    consortium = result_by_id(report, "QUAL-CONSORTIUM-REQ-010")
    assert consortium.status == "CHECK"
    assert consortium.check_side == "notice"
    assert consortium.requirement_id == "REQ-010"


def test_similar_experience_requirement_is_check_with_source_quote(
    synthetic_requirements: RfpParseResult,
) -> None:
    report = evaluate(make_notice(), synthetic_requirements, BEFORE_DEADLINE)
    # 총괄책임자의 경력·유사사업 — 사람(인력) 조항이다. 회사 실적 원장으로 채우면 안 된다 (19차 §4-B).
    pm = result_by_id(report, "QUAL-STAFF-REQ-011")
    assert pm.status == "CHECK"
    assert pm.method == "RULE"
    assert pm.requirement_id == "REQ-011"
    # 원문 근거를 그대로 인용한다 (창작 금지).
    assert "제안요청서 4쪽" in pm.source
    assert "총괄책임자" in pm.source
    assert report.verdict == "CHECK"


def test_requirement_source_text_is_verbatim_prefix(
    synthetic_requirements: RfpParseResult,
) -> None:
    report = evaluate(make_notice(), synthetic_requirements, BEFORE_DEADLINE)
    pm = result_by_id(report, "QUAL-STAFF-REQ-011")
    original = next(
        r for r in synthetic_requirements.requirements if r.requirement_id == "REQ-011"
    )
    quoted = pm.source.split('"')[1].rstrip("…")
    assert " ".join(original.source_text.split()).startswith(quoted)


def test_requirement_rules_are_capped(synthetic_requirements: RfpParseResult) -> None:
    many = synthetic_requirements.model_copy(deep=True)
    base = next(r for r in many.requirements if r.requirement_id == "REQ-011")
    extras = []
    for index in range(20):
        clone = base.model_copy(deep=True)
        clone.requirement_id = f"REQ-{100 + index:03d}"
        clone.id = f"clone-{index}"
        extras.append(clone)
    many.requirements = many.requirements + extras

    report = evaluate(make_notice(), many, BEFORE_DEADLINE)
    requirement_rules = [r for r in report.results if r.rule_id.startswith("ELIG-REQ-")]
    assert len(requirement_rules) <= eligibility_engine.MAX_REQUIREMENT_RULES + 1
    assert result_by_id(report, "ELIG-REQ-OVERFLOW").status == "CHECK"


# ---------------------------------------------------------------------------
# 데이터 부재 / 판정 종합
# ---------------------------------------------------------------------------


def test_missing_notice_still_returns_complete_report(
    synthetic_requirements: RfpParseResult,
) -> None:
    report = evaluate(None, synthetic_requirements, BEFORE_DEADLINE)
    assert report.notice_available is False
    assert report.requirements_available is True
    assert result_by_id(report, "ELIG-NOTICE-DATA").status == "CHECK"
    assert report.verdict == "CHECK"
    assert report.counts.total == len(report.results)


def test_missing_everything_raises() -> None:
    with pytest.raises(eligibility_engine.EligibilityDataError):
        evaluate(None, None, BEFORE_DEADLINE)


def test_verdict_precedence() -> None:
    def result(status: str) -> Any:
        return eligibility_engine.EligibilityResult(
            rule_id=f"R-{status}",
            label="테스트",
            status=status,  # type: ignore[arg-type]
            method="RULE",
            source="테스트",
            reason="테스트",
        )

    assert eligibility_engine.overall_verdict([result("PASS")]) == "PASS"
    assert eligibility_engine.overall_verdict([result("PASS"), result("CHECK")]) == "CHECK"
    assert (
        eligibility_engine.overall_verdict([result("PASS"), result("CHECK"), result("FAIL")])
        == "FAIL"
    )


def test_counts_match_results(synthetic_requirements: RfpParseResult) -> None:
    report = evaluate(make_notice(), synthetic_requirements, BEFORE_DEADLINE)
    assert report.counts.total == len(report.results)
    assert report.counts.passed + report.counts.check + report.counts.failed == report.counts.total


# ---------------------------------------------------------------------------
# LLM 계층 — 선택 기능. 죽어도 규칙 결과가 남고, PASS를 만들 수 없다.
# ---------------------------------------------------------------------------


def test_llm_failure_keeps_rule_results(
    synthetic_requirements: RfpParseResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)

    def boom(**_kwargs: Any) -> Any:
        raise llm_client.LLMUnavailableError("키 없음")

    monkeypatch.setattr(llm_client, "complete_structured", boom)

    report = eligibility_engine.evaluate_from_sources(
        SYNTHETIC_ID,
        notice=make_notice(),
        parse_result=synthetic_requirements,
        as_of=BEFORE_DEADLINE,
        use_llm=True,
    )
    assert report.llm_used is False
    pm = result_by_id(report, "QUAL-STAFF-REQ-011")
    assert pm.status == "CHECK"
    assert pm.method == "RULE"
    assert report.verdict == "CHECK"


def test_llm_cannot_promote_check_to_pass(
    synthetic_requirements: RfpParseResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)

    def fake(**kwargs: Any) -> Any:
        schema = kwargs["schema"]
        return schema.model_validate(
            {
                "items": [
                    {
                        "requirement_id": "REQ-011",
                        "classification": "clearly_satisfiable_by_rule",
                        "reason": "회사 프로필로 충족된다",
                    }
                ]
            }
        )

    monkeypatch.setattr(llm_client, "complete_structured", fake)

    report = eligibility_engine.evaluate_from_sources(
        SYNTHETIC_ID,
        notice=make_notice(),
        parse_result=synthetic_requirements,
        as_of=BEFORE_DEADLINE,
        use_llm=True,
    )
    pm = result_by_id(report, "QUAL-STAFF-REQ-011")
    assert report.llm_used is True
    assert pm.status == "CHECK"  # LLM은 PASS를 만들 수 없다
    assert pm.method == "AI_EXTRACTION"
    assert "AI 판단" in pm.reason


def test_llm_not_called_when_not_configured(
    synthetic_requirements: RfpParseResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)

    def never(**_kwargs: Any) -> Any:  # pragma: no cover - 호출되면 실패
        raise AssertionError("키가 없는데 LLM을 호출했다")

    monkeypatch.setattr(llm_client, "complete_structured", never)

    report = eligibility_engine.evaluate_from_sources(
        SYNTHETIC_ID,
        notice=make_notice(),
        parse_result=synthetic_requirements,
        as_of=BEFORE_DEADLINE,
        use_llm=True,
    )
    assert report.llm_used is False


# ---------------------------------------------------------------------------
# API (main.py를 건드리지 않고 라우터만 올려서 검증)
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_load_sources(procurement_id: str) -> Any:
        return make_notice(), rfp_parser.load_generated(SYNTHETIC_ID)

    monkeypatch.setattr(eligibility_engine, "load_sources", fake_load_sources)
    monkeypatch.setattr(eligibility_engine, "_LAST_REPORTS", {})
    app = FastAPI()
    app.include_router(eligibility_api.router)
    return TestClient(app)


def test_api_evaluate_and_get(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/eligibility/evaluate",
        json={"procurement_id": SYNTHETIC_ID, "as_of": "2026-08-25T09:00:00+09:00", "use_llm": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["procurement_id"] == SYNTHETIC_ID
    assert payload["verdict"] in {"PASS", "CHECK", "FAIL"}
    assert payload["counts"]["total"] == len(payload["results"])
    assert {"rule_id", "label", "status", "method", "source", "reason"} <= set(
        payload["results"][0]
    )

    again = api_client.get(f"/api/eligibility/{SYNTHETIC_ID}")
    assert again.status_code == 200
    assert again.json()["counts"] == payload["counts"]


def test_api_returns_404_without_any_source(monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty_sources(procurement_id: str) -> Any:
        return None, None

    monkeypatch.setattr(eligibility_engine, "load_sources", empty_sources)
    monkeypatch.setattr(eligibility_engine, "_LAST_REPORTS", {})
    app = FastAPI()
    app.include_router(eligibility_api.router)
    client = TestClient(app)

    response = client.post("/api/eligibility/evaluate", json={"procurement_id": "g2b-UNKNOWN-000"})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 업종·지역을 **실제 코드·지역 값**으로 판정한다 (0922 §4-A-4 · ISSUE-081)
# ---------------------------------------------------------------------------


def _fields(**raw: Any) -> list[Any]:
    """소재지만 적고 **등록 업종은 비어 있는** 회사로 판정한다 — 지금 샘플에듀의 상태다."""
    return eligibility_engine.evaluate_notice_fields(
        {"item": {"bidNtceNo": "R26TEST", "bidClseDt": "2026-09-30 10:00:00"}, **raw},
        as_of=BEFORE_DEADLINE,
        regions=("광주광역시", "전라남도"),
        company=eligibility_engine.CompanyFacts(location_region="전남광주"),
    )


def _rule(results: list[Any], rule_id: str) -> Any:
    return next(r for r in results if r.rule_id == rule_id)


SW_1468 = {"name": "소프트웨어사업자(컴퓨터관련서비스사업)", "code": "1468", "allowed_industries": []}


def test_업종제한이_실제로_오면_코드로_판정한다() -> None:
    """7차까지는 값이 없어 전부 「공고문 확인」이었다. 8차부터 코드가 온다 (2026-09-22 §2-1)."""
    company = eligibility_engine.CompanyFacts(
        location_region="전남광주", registered_industry_codes=("1468",), registered_industry_names=("소프트웨어사업자",)
    )
    results = eligibility_engine.evaluate_notice_fields(
        {"item": {"bidNtceNo": "R1", "bidClseDt": "2026-09-30 10:00:00"}, "license_limits": [SW_1468]},
        as_of=BEFORE_DEADLINE,
        regions=("광주광역시",),
        company=company,
    )
    industry = _rule(results, "ELIG-INDUSTRY")
    assert industry.status == "PASS"
    assert "1468" in industry.reason


def test_등록_업종이_미입력이면_불가가_아니라_확인_필요다() -> None:
    """빈 칸은 「없다」가 아니라 「아직 안 적었다」다. 열리는 조건에 코드·이름을 적는다."""
    results = _fields(license_limits=[SW_1468])
    industry = _rule(results, "ELIG-INDUSTRY")
    assert industry.status == "CHECK"
    assert industry.unlock_condition == "소프트웨어사업자(컴퓨터관련서비스사업), 1468 등록 시 가능"
    assert industry.unlock_options == ["소프트웨어사업자(컴퓨터관련서비스사업), 1468 등록 시 가능"]


def test_업종이_맞지_않으면_불가이고_무엇을_등록하면_되는지_말한다() -> None:
    company = eligibility_engine.CompanyFacts(location_region="전남광주", registered_industry_codes=("1169",))
    # 44차 결정 4 — 업종이 없어 「불가」인 것은 공동수급 불허일 때만(허용 · 모름은 확인 필요 · 파트너형)
    results = eligibility_engine.evaluate_notice_fields(
        {"item": {"bidNtceNo": "R1", "bidClseDt": "2026-09-30 10:00:00", "cmmnSpldmdMethdNm": "(없음)공동수급불허"}, "license_limits": [SW_1468]},
        as_of=BEFORE_DEADLINE,
        regions=("광주광역시",),
        company=company,
    )
    industry = _rule(results, "ELIG-INDUSTRY")
    assert industry.status == "FAIL"
    assert "1468" in (industry.unlock_condition or "")


def test_네_종_중_하나면_낱개로도_셀_수_있게_남긴다() -> None:
    """아산시 공고가 그렇다 — 1426·1468·1469·1470 중 하나 (기준 답안 A-5)."""
    rows = [
        {"name": f"소프트웨어사업자({n})", "code": code, "allowed_industries": []}
        for code, n in (("1426", "패키지"), ("1468", "컴퓨터관련"), ("1469", "디지털콘텐츠"), ("1470", "데이터베이스"))
    ]
    results = _fields(license_limits=rows)
    industry = _rule(results, "ELIG-INDUSTRY")
    assert industry.status == "CHECK"
    assert len(industry.unlock_options) == 4
    assert any("1468" in option for option in industry.unlock_options)
    # 그중 하나만 등록해도 통과한다.
    passed = eligibility_engine.evaluate_notice_fields(
        {"item": {"bidNtceNo": "R1", "bidClseDt": "2026-09-30 10:00:00"}, "license_limits": rows},
        as_of=BEFORE_DEADLINE,
        regions=("광주광역시",),
        company=eligibility_engine.CompanyFacts(location_region="전남광주", registered_industry_codes=("1470",)),
    )
    assert _rule(passed, "ELIG-INDUSTRY").status == "PASS"


def test_받았는데_업종_제한_행이_없으면_가능이다() -> None:
    """「미확인」과 다른 사실이다. 한양사이버대·한남대가 이 경우다 (기준 답안 A-1·A-2)."""
    results = _fields(license_limits=[], allowed_regions=[])
    assert _rule(results, "ELIG-INDUSTRY").status == "PASS"
    assert _rule(results, "ELIG-REGION").status == "PASS"


def test_자격_정보를_아직_못_받았으면_확인_필요다() -> None:
    results = _fields(**{"item": {"bidNtceNo": "R1", "indstrytyLmtYn": "Y", "bidClseDt": "2026-09-30 10:00:00"}})
    industry = _rule(results, "ELIG-INDUSTRY")
    assert industry.status == "CHECK"
    assert "미수집" in industry.source


def test_참가가능지역이_오면_소재지로_판정한다() -> None:
    """가야대 공고가 경상남도다 — 광주 회사는 불가이고, 그 이유를 지역 이름으로 말한다."""
    blocked = _fields(allowed_regions=["경상남도"])
    region = _rule(blocked, "ELIG-REGION")
    assert region.status == "FAIL"
    assert "경상남도" in region.reason
    assert region.unlock_options == ["경상남도 소재 시 가능"]

    allowed = _fields(allowed_regions=["광주광역시", "전라남도"])
    assert _rule(allowed, "ELIG-REGION").status == "PASS"
