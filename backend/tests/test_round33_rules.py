"""33차 §3-F — 판정 남은 것(recheck25 R32-02 · 03 · 05 …)."""

from __future__ import annotations

import dataclasses
from datetime import date

from app.services import support_application_service as sas
from tests.test_round32_rules import SAMPLEEDU, target

LINE_122863 = (
    "공고일 기준 1인 (예비)창업기업 또는 7년 이내 창업자, 창의성을 갖춘 창업ㆍ벤처기업 또는 창업 예정인 자로서 "
    "제조 분야의 AX(AI Transformation) 관련 서비스를 개발하려는 자"
)


def test_R32_02_또는_뒤_공통_꼬리는_모든_갈래에_걸린다() -> None:
    branches = sas._target_branches(LINE_122863)
    assert len(branches) == 3
    assert all("제조 분야" in b for b in branches)
    venture = dataclasses.replace(SAMPLEEDU, certifications=("벤처기업",))
    result = target(LINE_122863, venture)
    assert result.status == "CHECK", result.reason  # 예전: 「벤처기업」 갈래만 보고 거짓 가능
    assert "업종 · 분야" in result.reason
    assert LINE_122863[:40] in result.reason  # 인용은 원문 그대로(붙인 갈래가 아니라 대상 줄)


def test_R32_02_꼬리가_없으면_갈래는_그대로() -> None:
    assert sas._target_branches("사회적기업 또는 만 39세 이하 청년 창업자") == ["사회적기업", "만 39세 이하 청년 창업자"]


def test_R32_03_설립_연도만_있으면_경계_해는_확인_필요() -> None:
    founded = dataclasses.replace(SAMPLEEDU, certifications=(), founded_year=2021)
    edge = target("창업 5년 이내 기업", founded)  # 2026 - 2021 = 5 — 설립 월에 따라 다름
    assert edge.status == "CHECK" and "설립 월에 따라" in edge.reason
    inside = target("창업 7년 이내 기업", founded)
    assert inside.status == "PASS", inside.reason
    over = target("창업 4년 이내 기업", founded)
    assert over.status == "FAIL", over.reason


def test_R32_05_진입_꼴에_되려도_든다() -> None:
    assert sas._ASPIRING_RE.search("사회적기업이 되려는 기업")


def test_R32_04_진짜_선행_선정_요건은_절차_낱말이_있어도_요건() -> None:
    from app.services import bizinfo_document_store as store
    from app.services import support_requirement_extractor as extractor

    def keys(line: str) -> list:
        text = store.join_pages([f"○ 신청자격\n{line}"])
        return [c.detail.get("requirement") for c in extractor.extract_from_text("P", text).of("prerequisite")]

    # 예전: 「협약」 낱말 하나로 절차 문장이라 여겨 버렸다
    assert "prior_selection" in keys("1단계 사업 협약이 완료된 선정기업에 한하여 지원")
    assert "prior_selection" in keys("2025년 바우처 사업 수행이 종료된 선정기업에 한하여 신청")
    # 선정 뒤 절차 문장은 여전히 요건이 아니다(R31-01)
    assert "prior_selection" not in keys("ㅇ (결과통보) 선정기업에 한하여 선정심사일로부터 5일 이내 개별 통보")


def test_R32_07_공동수급_지역_가능_사유에_회사_사실을_지어내지_않는다() -> None:
    from datetime import datetime, timedelta, timezone

    from app.services import eligibility_engine

    rules = eligibility_engine.evaluate_notice_fields(
        {"source": "g2b", "item": {"bidNtceNo": "R26TEST", "cmmnSpldmdCorpRgnLmtYn": "N"}},
        as_of=datetime(2026, 8, 25, tzinfo=timezone(timedelta(hours=9))),
    )
    row = next(r for r in rules if r.rule_id == "ELIG-CONSORTIUM-REGION")
    assert row.status == "PASS" and "혼자" not in row.reason


def test_R32_08_종합_사유는_공고문_쪽과_회사_쪽을_나눈다() -> None:
    from app.schemas.eligibility import EligibilityResult
    from app.services import opportunity_priority as priority
    from app.services import organization_service
    from app.services.opportunity_filter import classify
    from tests.test_unified_opportunities import ALPHA, NOW, make_notice, make_organizations

    make_organizations()

    def r(label: str, side: str) -> EligibilityResult:
        return EligibilityResult(rule_id=f"X-{label}", label=label, status="CHECK", method="RULE", source="s", reason="r", check_side=side)

    notice = make_notice("g2b-SIDE-000", "생성형 AI 활용 실무교육 운영")
    results = [r("공고문 참가자격 부분", "notice"), r("사업 규모", "company"), r("업종", "company")]
    gate, reason = priority.procurement_eligibility_gate(
        notice, classify(notice), profile=organization_service.load_profile(ALPHA), now=NOW, results=results
    )
    assert gate == "CHECK"
    assert "공고문에서 볼 것: 공고문 참가자격 부분" in reason
    assert "회사자료에 적거나 직접 확인할 것: 사업 규모 · 업종" in reason


def test_R32_10_조직_형태_사유는_사실대로() -> None:
    result = target("광주 소재 중소기업(비영리 법인 제외)", category="사회적기업")
    assert result.status == "CHECK", result.reason
    assert "찾습니다" not in result.reason and "적혀 있습니다" in result.reason


def test_마지막_검토_경계_해라도_다른_갈래가_맞으면_가능() -> None:
    venture = dataclasses.replace(SAMPLEEDU, certifications=("벤처기업",), founded_year=2023)
    result = target("창업 3년 이내 기업 또는 벤처기업", venture)
    assert result.status == "PASS", result.reason


def test_마지막_검토_선정_뒤_절차_문장은_요건이_아니다() -> None:
    from app.services import bizinfo_document_store as store
    from app.services import support_requirement_extractor as extractor

    def keys(line: str) -> list:
        text = store.join_pages([f"○ 신청자격\n{line}"])
        return [c.detail.get("requirement") for c in extractor.extract_from_text("P", text).of("prerequisite")]

    assert "prior_selection" not in keys("선정된 기업에 한해서 추후 원본 제출을 요청할 수 있음")
    assert "prior_selection" not in keys("최종 선정된 기업에 한하여 협약을 체결한 후 사업비를 지급")
    assert "prior_selection" in keys("1차 사업 협약이 체결된 선정기업에 한하여 지원")
