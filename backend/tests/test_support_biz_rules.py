"""기업마당 자격 규칙 BIZ-* (0921.md §4-B).

## 무엇이 틀렸나

지원사업 자격은 **점수 성분**으로만 판정했다 — 「지역 점수가 0이고 사유에 '밖으로 보임'이
들어 있으면 불가」. 근거가 화면에 남지 않고, 대상 요건(업력·인증·인원)은 아예 보지 않았다.
1,605건을 그렇게 두면 담당자가 무엇을 신청할 수 있는지 알 수 없다.

## 여기서 지키는 약속 넷

1. **나라장터와 같은 결과 모양**(`EligibilityResult`)을 쓴다. 화면이 두 출처를 한 벌의
   어휘(「가능 · 확인 필요 · 불가」)로 그린다.
2. **대상 요건은 원문 그대로 인용한다.** 요약문의 「☞」 문장을 근거(`source`)에 싣고
   가공하지 않는다.
3. **모르는 것은 「확인 필요」다.** 지역 표시가 없으면 「전국 사업」으로 단정하지 않는다.
4. **소재지가 비었으면 회사가 적은 활동 지역으로 본다.** 지어내는 것이 아니라 이미 적어 둔
   값을 읽는 것이다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.services import bizinfo_service, eligibility_engine, support_application_service

TODAY = date(2026, 9, 17)
SAMPLEEDU = eligibility_engine.CompanyFacts(
    location_region="전남광주",
    certifications=("사회적기업", "데이터바우처 공급기업"),
    founded_year=2021,
    employee_count=None,
    activity_regions=("광주광역시", "전라남도"),
)


def program(**fields: Any):
    base = {"pblancId": "P1", "pblancNm": "시험 사업", "jrsdInsttNm": "시험기관"}
    return bizinfo_service.map_program(base | fields)


def rule(results: list[Any], rule_id: str) -> Any:
    for entry in results:
        if entry.rule_id == rule_id:
            return entry
    raise AssertionError(f"{rule_id} 규칙이 없다: {[r.rule_id for r in results]}")


def judge(prog, company=SAMPLEEDU) -> list[Any]:
    return support_application_service.biz_rules(prog, company=company, today=TODAY)


# ---------------------------------------------------------------------------
# BIZ-REGION
# ---------------------------------------------------------------------------


def test_대상_지역에_들면_가능이고_근거를_적는다() -> None:
    result = rule(judge(program(hashtags="#전남광주,#AI")), "BIZ-REGION")
    assert result.status == "PASS"
    assert "전남광주" in result.source and "전남광주" in result.reason


def test_옛_이름_해시태그도_같은_지역으로_읽는다() -> None:
    """통합 전 「광주」·「전남」 태그가 아직 섞여 있다 — 같은 곳을 다른 이름이라고 읽으면 버린다."""
    assert rule(judge(program(hashtags="#광주")), "BIZ-REGION").status == "PASS"
    assert rule(judge(program(hashtags="#전남")), "BIZ-REGION").status == "PASS"


def test_다른_지역이면_불가이고_양쪽을_함께_적는다() -> None:
    result = rule(judge(program(hashtags="#부산,#제조")), "BIZ-REGION")
    assert result.status == "FAIL"
    assert "부산" in result.reason and "전남광주" in result.reason


def test_지역_표시가_없으면_전국이_아니라_확인_필요다() -> None:
    result = rule(judge(program(hashtags="#AI,#교육")), "BIZ-REGION")
    assert result.status == "CHECK"
    assert "전국" in result.reason


def test_소재지가_비면_활동_지역으로_본다() -> None:
    """지어내는 것이 아니라 회사가 이미 적어 둔 값을 읽는 것이다."""
    company = eligibility_engine.CompanyFacts(activity_regions=("광주광역시", "전라남도"))
    result = rule(judge(program(hashtags="#부산"), company), "BIZ-REGION")
    assert result.status == "FAIL"
    assert "활동 지역" in result.reason


def test_소재지도_활동_지역도_없으면_확인_필요다() -> None:
    result = rule(judge(program(hashtags="#부산"), eligibility_engine.CompanyFacts()), "BIZ-REGION")
    assert result.status == "CHECK"
    assert result.unlock_condition and "소재지" in result.unlock_condition


# ---------------------------------------------------------------------------
# BIZ-TARGET — 「☞」 문장을 근거로
# ---------------------------------------------------------------------------


def test_인증을_보유하면_가능이고_인증_이름을_적는다() -> None:
    result = rule(
        judge(program(bsnsSumryCn="<p>☞ 전라남도 소재 (예비)사회적기업</p>", hashtags="#전남광주")), "BIZ-TARGET"
    )
    assert result.status == "PASS"
    assert "사회적기업" in result.reason
    # 근거는 원문 문장 그대로다.
    assert "☞" not in result.source and "(예비)사회적기업" in result.source


def test_창업_7년_이내는_설립연도로_센다() -> None:
    result = rule(judge(program(bsnsSumryCn="<p>☞ 창업 7년 이내 창업기업</p>")), "BIZ-TARGET")
    assert result.status == "PASS"
    assert "2021" in result.reason


def test_업력_요건을_넘기면_불가다() -> None:
    old = eligibility_engine.CompanyFacts(founded_year=2010, location_region="전남광주")
    result = rule(judge(program(bsnsSumryCn="<p>☞ 창업 7년 이내</p>"), old), "BIZ-TARGET")
    assert result.status == "FAIL"
    assert "2010" in result.reason


def test_인원_요건인데_상시_근로자_수가_없으면_확인_필요다() -> None:
    result = rule(judge(program(bsnsSumryCn="<p>☞ 피보험자 5인 이상 기업</p>")), "BIZ-TARGET")
    assert result.status == "CHECK"
    assert result.unlock_condition and "상시 근로자" in result.unlock_condition


def test_대상_문장이_없으면_확정하지_않는다() -> None:
    result = rule(judge(program(trgetNm="중소기업")), "BIZ-TARGET")
    assert result.status == "CHECK"
    assert "중소기업" in result.source


# ---------------------------------------------------------------------------
# BIZ-PERIOD · BIZ-ROLE
# ---------------------------------------------------------------------------


def test_상시_예산_소진은_가능이다() -> None:
    result = rule(judge(program(reqstBeginEndDe="예산 소진시까지")), "BIZ-PERIOD")
    assert result.status == "PASS"


def test_접수가_끝났으면_불가다() -> None:
    result = rule(judge(program(reqstBeginEndDe="20260801 ~ 20260810")), "BIZ-PERIOD")
    assert result.status == "FAIL"


def test_회사가_맡을_역할을_요약문에서_찾는다() -> None:
    result = rule(
        judge(program(bsnsSumryCn="<p>공급기업(AI Agent 역량 보유)과 수요기업 컨소시엄 필수</p>")), "BIZ-ROLE"
    )
    assert result.status == "PASS"
    assert "공급기업" in result.reason and "수요기업" in result.reason


def test_역할_낱말이_없으면_규칙을_내지_않는다() -> None:
    results = judge(program(bsnsSumryCn="<p>지원 내용을 안내합니다</p>"))
    assert all(r.rule_id != "BIZ-ROLE" for r in results)


def test_판정은_세_가지뿐이다() -> None:
    """화면 어휘를 한 벌로 유지한다 — 나라장터와 같은 값만 쓴다."""
    results = judge(program(hashtags="#전남광주", bsnsSumryCn="<p>☞ 사회적기업</p>", reqstBeginEndDe="상시"))
    assert {r.status for r in results} <= {"PASS", "CHECK", "FAIL"}
    assert all(r.method == "RULE" for r in results)
    assert all(r.source and r.reason for r in results), "근거 없는 판정은 만들지 않는다"


# ---------------------------------------------------------------------------
# 30차 §3-E — 「가능」은 대상 요건이 모두 회사 사실로 가려졌을 때만 (담당자 결정 · recheck22 §5 일곱 건)
# ---------------------------------------------------------------------------

SEVEN_CASES = [
    # (공고, 제목, 요약문 대상 줄, 기대, 사유에 들 말)
    ("126791", "2026년 제2차 고용노동부 예비사회적기업 지정 계획 공고", "(예비)사회적기업으로 진입하고자 하는 일반 기업", "FAIL", "아닌 기업을 찾습니다"),
    ("126516", "2026년 2차 통일형 예비사회적기업 지정계획 공고", "「사회적기업 육성법」제8조 및 같은 법 시행령 제8조에 따른 조직 형태를 갖춘 기업", "CHECK", "지정 · 인증을 주는 공고"),
    ("126779", "2026년 대전 웰컴 스테이 지원사업 참가기업 모집 공고",
     "2026년 내(1~12월) 대전광역시로 주거ㆍ사무ㆍ제조 공간 이전을 희망하거나 이전을 완료한 매출ㆍ고용ㆍ투자 등 일정 성장단계에 진입한 창업 7년 이내 기업", "CHECK", "지역 이전"),
    ("119834", "[광주] 2026년 벤처기업육성자금 지원계획 공고", "광주 지역소재 법상 벤처기업, 창업 7년 이내 광(光) 관련기업", "CHECK", "업종 · 분야"),
    ("119567", "2026년 농식품 크라우드펀딩 지원사업 공고", "창업 7년 이내 농식품 기업 또는 예비창업자", "CHECK", "업종 · 분야"),
    ("126314", "2026년 산림분야 오픈이노베이션 참여기업 모집 공고",
     "수요과제 모집분야에 해당하는 기술을 보유한 창업 7년 이내 기업 (※ 신사업 분야의 경우 창업 10년 이내 기업)", "CHECK", "업종 · 분야"),
    ("126731", "Plug in : Tokyo #15 참여 스타트업 모집 공고", "일본 진출을 희망하는 전국 소재 모집공고일 기준 창업 7년 이내 스타트업", "CHECK", "진출"),
]


@pytest.mark.parametrize(("pid", "title", "line", "expect", "word"), SEVEN_CASES, ids=[c[0] for c in SEVEN_CASES])
def test_30차_한_조항만_맞은_가능은_확인_필요_진입하려는_공고는_불가(pid: str, title: str, line: str, expect: str, word: str) -> None:
    prog = program(pblancId=pid, pblancNm=title, bsnsSumryCn=f"<p>☞ {line}</p><p>☞ 사회적기업 재정지원사업 참여 지원</p>",
                   trgetNm="사회적기업" if "사회적기업" in title else "창업벤처")
    result = rule(judge(prog), "BIZ-TARGET")
    assert result.status == expect and word in result.reason, result.reason
    if expect == "CHECK":
        assert "「" in result.reason  # 원문 인용(또는 이유)이 사유에 든다


@pytest.mark.parametrize("line", [
    "전국의 예비창업자(개인ㆍ팀) 또는 창업 10년 미만 기업(개인ㆍ법인)",  # 맞은 갈래(창업 10년 미만 기업)에 남은 조건 없음
    "(예비)사회적기업",
    "도내 사회적 경제기업(사회적기업, 마을기업, 협동조합, 자활기업)",
])
def test_30차_맞은_갈래에_남은_조건이_없으면_그대로_가능(line: str) -> None:
    result = rule(judge(program(bsnsSumryCn=f"<p>☞ {line}</p>", trgetNm="사회적기업", hashtags="#전남광주")), "BIZ-TARGET")
    assert result.status == "PASS", result.reason


@pytest.mark.parametrize(("line", "expect"), [
    ("사회적기업 또는 사회적기업으로 전환하려는 협동조합", "CHECK"),  # 갈래 하나만 진입 · 전환 — 불가로 숨기지 않는다
    ("사회적기업, (예비)사회적기업으로 진입하고자 하는 일반 기업", "CHECK"),
    ("창업 7년 이내 기업으로, 대전광역시로 본사 이전을 완료한 기업", "CHECK"),  # 쉼표는 「그리고」 — 뒤 조건을 버리지 않는다
    ("창업 3년 이내 기업 또는 사회적기업", "PASS"),  # 창업 연차 갈래가 안 맞아도 다른 갈래(사회적기업)로
    ("창업 3년 이내 기업", "FAIL"),
])
def test_30차_마지막_검토_갈래_판정(line: str, expect: str) -> None:
    result = rule(judge(program(bsnsSumryCn=f"<p>☞ {line}</p>", trgetNm="사회적기업", hashtags="#전남광주")), "BIZ-TARGET")
    assert result.status == expect, result.reason


def test_30차_법령_이름과_지원내용_줄의_낱말로는_인증을_맞추지_않는다() -> None:
    prog = program(bsnsSumryCn="<p>☞ 「사회적기업 육성법」에 따른 조직 형태를 갖춘 기업</p><p>☞ 사회적기업 재정지원사업 참여</p>", trgetNm="중소기업")
    assert rule(judge(prog), "BIZ-TARGET").status == "CHECK"

# ---------------------------------------------------------------------------
# 31차 §3-A — 거짓 불가 · 거짓 가능 바로잡기 (recheck23 R30-01~06)
# ---------------------------------------------------------------------------


def _target(line: str, company=SAMPLEEDU, *, category: str = "중소기업", title: str = "시험 사업") -> Any:
    return rule(judge(program(pblancNm=title, bsnsSumryCn=f"<p>☞ {line}</p>", trgetNm=category, hashtags="#전남광주"), company), "BIZ-TARGET")


@pytest.mark.parametrize(("line", "expect"), [
    ("사회적기업으로 인증받은 기업", "PASS"),  # 이미 그 지위 — 「진입하려는」이 아니다
    ("사회적기업으로 인증된 기업", "PASS"),
    ("데이터바우처 공급기업으로 지정된 기업", "PASS"),
    ("사회적기업으로 진입하고자 하는 기업 또는 데이터바우처 공급기업", "PASS"),  # 회사 인증 둘 — 맞는 갈래 하나로 충분
    ("(예비)사회적기업으로 진입하고자 하는 일반 기업", "FAIL"),  # 모든 갈래가 진입 — 분명한 불가
])
def test_31차_R30_01_진입_구절은_진입하려는_꼴로만_읽는다(line: str, expect: str) -> None:
    result = _target(line)
    assert result.status == expect, result.reason


def test_31차_R30_01_회사_인증_하나만_있고_다른_갈래가_남으면_불가가_아니다() -> None:
    only_social = eligibility_engine.CompanyFacts(location_region="전남광주", certifications=("사회적기업",), founded_year=2021)
    result = _target("사회적기업으로 진입하고자 하는 기업 또는 데이터바우처 공급기업", only_social)
    assert result.status == "CHECK", result.reason


def test_31차_R30_02_창업_연차_갈래를_버리면_분류_이름을_다시_붙이지_않는다() -> None:
    result = _target("창업 3년 이내 기업 또는 예비창업자", category="사회적기업")
    assert result.status != "PASS", result.reason


@pytest.mark.parametrize(("line", "founded", "expect"), [
    ("수요과제 모집분야에 해당하는 기술을 보유한 창업 7년 이내 기업 (※ 신사업 분야의 경우 창업 10년 이내 기업)", 2017, "CHECK"),  # 126314 꼴 · 9년
    ("창업 7년 이내 기업 혹은 지역 특화 기업", 2010, "CHECK"),
    ("창업 3년 이내이거나 매출 10억 미만 기업", 2010, "CHECK"),
    ("창업 7년 이내 기업, 사회적협동조합", 2010, "CHECK"),
    ("창업 7년 이내 기업", 2010, "FAIL"),  # 상한도 넘고 대안도 없다
    ("창업 7년 이내 기업(단순 유통, 판매업 제외)", 2010, "FAIL"),  # 괄호 안 쉼표는 대안이 아니다
])
def test_31차_R30_03_창업_연차_불가는_가장_큰_상한도_넘고_대안이_없을_때만(line: str, founded: int, expect: str) -> None:
    old = eligibility_engine.CompanyFacts(location_region="전남광주", founded_year=founded)
    result = _target(line, old)
    assert result.status == expect, result.reason


@pytest.mark.parametrize("line", [
    "경영현안 해결 의지가 높은 김포시 소재 사회적경제기업",  # 120608 꼴
    "하남시 소재 사회적경제기업",  # 119332 꼴
    "광주광역시 북구에 소재한 사회적기업",
    "담양군 소재 사회적기업",
])
def test_31차_R30_04_시_군_구_소재는_확인_필요(line: str) -> None:
    result = _target(line, category="사회적기업")
    assert result.status == "CHECK" and "세부 지역" in result.reason, result.reason


@pytest.mark.parametrize("line", ["광주광역시 소재 사회적기업", "서울시 소재 사회적기업", "광주ㆍ전남통합특별시 소재 사회적기업"])
def test_31차_R30_04_광역_특별시_단위는_세부_지역으로_보지_않는다(line: str) -> None:
    result = _target(line, category="사회적기업")
    assert "세부 지역" not in result.reason, result.reason


@pytest.mark.parametrize("line", [
    "사회적기업으로 진입하고자 하는 데이터바우처 공급기업",  # 같은 갈래가 회사가 이미 가진 지위로 진입하려는 기업을 찾는다
    "사회적기업으로 전환하려는 데이터바우처 공급기업",
])
def test_31차_마지막_검토_같은_갈래의_진입_구절이면_다른_인증이_맞아도_가능이_아니다(line: str) -> None:
    result = _target(line)
    assert result.status == "CHECK", result.reason
    assert "사회적기업" in result.reason


@pytest.mark.parametrize("line", [
    "담양군에 본사를 둔 사회적기업",
    "나주시 내에 소재한 사회적기업",
    "부여군에 본부(지부)를 두고 있는 사회적기업",  # 126613 꼴
])
def test_31차_마지막_검토_본사를_둔_시_군_구도_세부_지역(line: str) -> None:
    result = _target(line, category="사회적기업")
    assert result.status == "CHECK" and "세부 지역" in result.reason, result.reason


def test_31차_마지막_검토_대구는_광역시라_세부_지역이_아니다() -> None:
    assert "세부 지역" not in _target("대구 소재 사회적기업", category="사회적기업").reason


def test_31차_R30_05_구_안의_또는에서_뒤_조건을_버리지_않는다() -> None:
    result = _target("사회적기업으로 본사 또는 공장이 북구 관내에 있는 기업")
    assert result.status == "CHECK" and "세부 지역" in result.reason, result.reason
    assert "「사회적기업으로 본사" in result.reason  # 인용은 맞은 갈래 원문


def test_31차_R30_06_판정_메모_열쇠에_규칙_판이_든다(monkeypatch) -> None:
    from app.services import opportunity_service

    before = opportunity_service._inputs_stamp()
    assert before.startswith(f"r{support_application_service.RULES_VERSION}-")
    monkeypatch.setattr(support_application_service, "RULES_VERSION", support_application_service.RULES_VERSION + 1)
    assert opportunity_service._inputs_stamp() != before


def test_31차_R30_06_프로필_저장도_판정_메모를_비운다(monkeypatch) -> None:
    from app.schemas.organization import OrganizationProfileUpdate
    from app.services import opportunity_service, organization_service

    called: list[bool] = []
    monkeypatch.setattr(opportunity_service, "clear_support_memo", lambda: called.append(True))
    monkeypatch.setattr(organization_service.storage, "write_json_atomic", lambda *a, **k: None)
    monkeypatch.setattr(organization_service, "get_organization", lambda oid: type("O", (), {"organization_id": oid})())
    organization_service.save_profile("org-test-alpha", OrganizationProfileUpdate(name="가상 회사", updated_by="테스트"))
    assert called == [True]
