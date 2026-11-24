"""34차 §3-A — 새 데이터(10-08)에서 틀린 판정. 원문 문장은 공개 공고 글을 짧게 옮긴 회귀 상수다(recheck26 §2)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.services import bizinfo_document_store as store
from app.services import eligibility_engine as ee
from app.services import support_application_service as sas
from app.services import support_requirement_extractor as extractor
from tests.test_support_application_v2 import DOMAINS, SAMPLEEDU, TODAY, program, verdict

KST = timezone(timedelta(hours=9))


def requirements(text: str):
    return extractor.extract_from_text("P", store.join_pages([text]))


# --------------------------------------------------------------------------
# 1) R33-D4 — 여럿을 나열한 대상 목록 · 「다만 … 사회적기업」 예외 줄(122145)
# --------------------------------------------------------------------------

T_122145 = (
    "□ 지원 대상\n"
    "ㅇ 고용보험 피보험자 10인 이상* 기업, 공공기관, 지방공기업, 비영리단\n"
    "체, 비영리법인 등\n"
    "* 일경험 사업 참여 신청 직전 월말 기준. 다만, 고용보험 피보험자수 10인 미만의 기업\n"
    "이라도 다음의 기업은 참여 가능\n"
    "①｢벤처기업육성에 관한 특별조치법｣에 따른 벤처기업\n"
    "③｢사회적기업 육성법｣에 따른 사회적기업"
)


def test_122145_나열_목록에_기업이_있으면_비영리만_대상이_아니다() -> None:
    req = requirements(T_122145)
    org = sas._biz_org_type(req, SAMPLEEDU)
    assert org is not None and org.status == "PASS", org
    head = sas._biz_headcount(req, SAMPLEEDU)
    assert head is not None and head.status == "PASS", head  # 「10인 미만이라도 … 사회적기업」 예외
    assert not [c for c in req.of("headcount") if c.detail.get("comparator") == "미만"]


def test_사회연대경제_형태만_나열한_목록은_여전히_불가() -> None:
    venture = ee.CompanyFacts(certifications=("벤처기업",), location_region="전남광주")
    req = requirements("□ 지원대상\n지원대상 : 행안부형 마을기업, 전남형 예비마을기업 및 협동조합, 고용 10인 미만 사회연대경제 관련 비영리법인･단체 등")
    org = sas._biz_org_type(req, venture)
    assert org is not None and org.status == "FAIL"


# --------------------------------------------------------------------------
# 2) 표 · 트랙 · 대상 제품 목록의 한 줄(126672 · 119692)
# --------------------------------------------------------------------------


def test_126672_대상_제품_표의_한_줄은_전체_필수가_아니다() -> None:
    req = requirements(
        "2. 신청 대상\n□ 신청 대상제품\n연번 신청 대상제품 관련부처\n"
        "1 국가연구개발사업 완료판정 과제의 기술이 적용된 제품 전 부처\n"
        "2 특허 및 실용신안을 사업화한 제품 지식재산처\n"
        "□ 일정\n출원중인 특허, 발급전인 인증, 완료판정 전인 기술개발제품 등"
    )
    rule = sas._biz_prerequisite(req, SAMPLEEDU, DOMAINS)
    assert rule is not None and rule.status == "CHECK", rule
    assert "여러 갈래" in rule.reason


def test_119692_트랙_표의_선정_요건은_다른_트랙이_있으면_확인_필요() -> None:
    row = ("구 분세부요건비고[트랙 1]다음 요건 중 하나 이상 충족➀ ‘26년 2월 이 후 중동지역 국가로 물류 발송 기업"
           "[트랙 2]‘26년도 일반 수출바우처 1차 선정기업으로 최근 1년 중동지역 직수출 실적 보유 기업")
    req = requirements(f"○ 신청자격\n{row}\n‘26년도 일반 수출바우처 1차 선정기업으로 최근 1년 중동지역 직수출 실적 보유 기업")
    rule = sas._biz_prerequisite(req, SAMPLEEDU, DOMAINS)
    assert rule is not None and rule.status == "CHECK", rule


def test_자격_절_밖이어도_진짜_완료판정_요건은_읽는다() -> None:
    """125978 「최종평가 결과 완료판정(60점 이상) 과제에 한하여 신청 가능」 — 그대로 불가(회사는 선행 과제 없음 확인)."""
    req = requirements("□ (지원방법) PoC 단계 생략\n* 접수 마감일 기준, 스마트제조혁신R&D 최종평가 결과 완료판정(60점 이상)\n과제에 한하여 신청 가능")
    rule = sas._biz_prerequisite(req, SAMPLEEDU, DOMAINS)
    assert rule is not None and rule.status == "FAIL"


# --------------------------------------------------------------------------
# 3) 소재 요건의 갈래 · 역할 · 우대 · 이전
# --------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    # 120334 — 주관(경북 제조기업)과 참여(전국 소재)
    "○ 지원대상\n경상북도 소재 퍼스널케어(헬스, 뷰티케어)분야 제조기업과 전국소재 디자인/ICT/서비스 및 유통 등 분야별 지원 기업(기관)의 컨소시엄",
    # 126827 — 프로그램별 도내/외
    "❍ (지원대상) 미래모빌리티 관련 부품·제품 및 기술보유 기업\n도내기업 강원특별자치도 내 본사 또는 공장이 소재한 미래모빌리티 관련 기업\n"
    "사업화 지원 패키지 전동화 부품 관련 도내/외 기업",
    # 122910 — 괄호 안 「… 우대」는 요건이 아니다
    "가. 지원대상 : 미래차부품 관련 기업 (부산광역시 내 사업장 또는 연구소를 보유한 기업 우대)",
    # 127034 — 그 지역으로 이전을 희망하는 기업도 대상
    "□ 지원대상\n◦ 대전광역시로 주거·사무·제조 공간 이전을 희망하거나 이전을 완료한 기업\n이전 주소 (본사/지점/연구소/공장) 대전광역시",
])
def test_소재_갈래_우대_이전은_불가가_아니다(text: str) -> None:
    rule = sas._biz_location(requirements(text), program(), SAMPLEEDU)
    assert rule.status == "CHECK", rule


def test_소재_요건이_분명하면_여전히_불가() -> None:
    rule = sas._biz_location(requirements("○ 신청자격\n② 경상남도 내에 사업장(본사, 연구소, 공장, 지사 등)을 보유한 기업으로"), program(), SAMPLEEDU)
    assert rule.status == "FAIL"


# --------------------------------------------------------------------------
# 4 · 5) 나라장터 — R33-D1 지역 별칭 · R33-D2 자격 미확인 · R33-D3 실적 조항
# --------------------------------------------------------------------------

NOW = datetime(2026, 10, 8, 10, 0, tzinfo=KST)
GWANGJU = ee.CompanyFacts(location_region="전남광주")


def region_rule(allowed):
    raw = {"source": "g2b", "item": {"bidNtceNo": "R26TEST", "rgnLmtBidLocplcJdgmBssNm": ""}}
    if allowed is not ...:
        raw["allowed_regions"] = allowed
    rules = ee.evaluate_notice_fields(raw, as_of=NOW, company=GWANGJU)
    return next(r for r in rules if r.rule_id == "ELIG-REGION")


def test_1761269_경기도_광주시는_우리_광주가_아니다() -> None:
    rule = region_rule(["경기도 수원시", "경기도 성남시 분당구", "경기도 광주시", "경기도 하남시"])
    assert rule.status == "FAIL", rule.reason
    assert ee._region_names("경기도 광주시") == ["경기"]


@pytest.mark.parametrize(("allowed", "status"), [
    (["광주광역시"], "CHECK"),       # 43차 H2 — 옛 광주 · 옛 전남 중 어느 쪽인지 회사 주소를 모르면 확정 안 함
    (["전라남도"], "CHECK"),
    (["광주광역시", "전라남도"], "PASS"),  # 둘 다 열림 = 통합 전체
    (["전라남도 나주시"], "CHECK"),  # 우리 도 안의 시 · 군만 — 회사 시 · 군을 모르면 확정 안 함
    ([], "PASS"),                    # 받았는데 제한 없음
    (..., "CHECK"),                  # 받아 본 적 없음 — R33-D2
])
def test_참가가능지역_판정(allowed, status: str) -> None:
    assert region_rule(allowed).status == status


def test_지역제한_판단기준_칸도_도_이름_뒤_시는_그_도() -> None:
    raw = {"source": "g2b", "item": {"bidNtceNo": "R26TEST", "rgnLmtBidLocplcJdgmBssNm": "경기도 광주시"}}
    rules = ee.evaluate_notice_fields(raw, as_of=NOW, company=GWANGJU, regions=("광주광역시", "전라남도"))
    assert next(r for r in rules if r.rule_id == "ELIG-REGION").status == "FAIL"


def test_R33_D3_입찰공고문에_실적_조항이_있으면_필드_줄을_가능으로_확정하지_않는다(tmp_path, monkeypatch) -> None:
    from app.services import qualification_clause_service as qc
    from tests.test_qualification_rules import NOTICE_ID, raw, save_clauses

    # 조항 파일은 tmp 로 — 저장소의 실제 조항 폴더(키트에도 실림)에 쓰지 않는다(34차 마지막 검토)
    monkeypatch.setattr(qc, "CLAUSE_DIR", tmp_path / "qualification_clauses")
    qc._MEMO.clear()
    save_clauses(("track_record", "최근 3년 이내 AI 교육 용역 수행 실적 1건 이상"))
    rules = ee.evaluate_notice_fields(raw(), as_of=datetime(2026, 9, 1, 9, 0, tzinfo=KST), company=ee.CompanyFacts(), notice_id=NOTICE_ID)
    track = next(r for r in rules if r.rule_id == "ELIG-TRACK-RECORD")
    assert track.status == "CHECK" and "실적 참가자격 조항" in track.reason
    qc._MEMO.clear()


def test_마지막_검토_실적_조항_줄이_모두_가능이면_필드_줄은_그대로() -> None:
    track_pass = ee.EligibilityResult(rule_id="QUAL-TRACK-QC-01", label="실적", status="PASS", method="HUMAN", source="s", reason="r")
    field = ee.EligibilityResult(rule_id="ELIG-TRACK-RECORD", label="실적 · 참가 제한", status="PASS", method="RULE", source="s", reason="없음")
    import unittest.mock as mock

    with mock.patch.object(ee, "_collect_field_rules", return_value=[field]), mock.patch.object(ee, "_qualification_rows", return_value=[track_pass]):
        rows = ee._collect_notice_rules({}, datetime(2026, 9, 1, tzinfo=KST), None, notice_id="g2b-X")
    assert next(r for r in rows if r.rule_id == "ELIG-TRACK-RECORD").status == "PASS"
    with mock.patch.object(ee, "_collect_field_rules", return_value=[field]), mock.patch.object(
        ee, "_qualification_rows", return_value=[track_pass.model_copy(update={"status": "CHECK"})]
    ):
        rows = ee._collect_notice_rules({}, datetime(2026, 9, 1, tzinfo=KST), None, notice_id="g2b-X")
    assert next(r for r in rows if r.rule_id == "ELIG-TRACK-RECORD").status == "CHECK"


def test_마지막_검토_기술_보유_앞말과_광주전남() -> None:
    from app.services import support_application_service as sas
    from app.services import support_requirement_extractor as extractor

    def field(sentence: str) -> str | None:
        m = next((m for m in sas._SKILL_HELD_RE.finditer(sentence) if m.group(1) not in sas._NOT_A_SKILL_FIELD), None)
        return m.group(1) if m else None

    assert field("디지털헬스케어 관련 기술을 보유한 기업 및 의료기관") == "디지털헬스케어"
    assert field("사업 관련 분야의 제품 또는 기술을 보유한 기업") is None
    assert field("우수 아이디어와 구현 기술을 보유한 서울시 소재 기업") is None
    assert field("만 60세 이상의 숙련기술보유자") is None
    assert field("블록체인 기술 보유 및 해외 진출 역량") == "블록체인"
    assert extractor.names_gwangju("광주·전남 지역 내 본사 또는 주사업장 소재 기업")
    assert not extractor.names_gwangju("경기도 광주시 소재 기업")
    assert not extractor.names_gwangju("전남 지역 내 본사를 둔 기업")


def test_마지막_검토_광주전남_소재가_맞아도_관련_기업_분야가_없으면_가능이_아니다() -> None:
    from types import SimpleNamespace

    from app.services import support_application_service as sas

    line = "광주ㆍ전남 지역 내 본사 또는 주사업장 소재 기반 에이지테크 관련 기업"
    program = SimpleNamespace(requirement_sentences=(line,))
    result = sas._biz_target_industry(program, ("AI 교육", "생성형 AI 교육"))
    assert result is not None and result.status == "CHECK" and "에이지테크" in result.reason
    assert sas._biz_target_industry(SimpleNamespace(requirement_sentences=("AI 관련 기업",)), ("AI 교육",)) is None


# --------------------------------------------------------------------------
# 6) 거짓 가능 — 기술 보유(126841) · 요약 경로 「전남 소재」(117149 · 125805)
# --------------------------------------------------------------------------


def test_126841_블록체인_기술_보유_요건은_공고문_경로에서도_본다() -> None:
    p = program(requirement_sentences=["블록체인 기술 보유 및 해외 진출 역량이 있는 블록체인 중소기업 또는 스타트업(업력 10년 이내)"])
    rule = sas._biz_target_industry(p, DOMAINS)
    assert rule is not None and rule.status == "CHECK" and "블록체인" in rule.reason


@pytest.mark.parametrize(("title", "line"), [
    ("[전남] 2026년 중소기업 육성자금(사회적경제 경영안정자금)", "도내 사회적 경제기업(사회적기업, 마을기업, 협동조합, 자활기업)"),
    ("[전남광주] 2026년 사회연대경제 서비스체험 페어", "전남 소재 사회연대경제기업 및 신규 창업팀"),
])
def test_요약_경로의_전남_소재도_통합_해석_확인(title: str, line: str) -> None:
    p = program(title, requirement_sentences=[line], region_tags=["전남광주"])
    rule = sas._biz_region(p, SAMPLEEDU)
    assert rule.status == "CHECK" and "통합" in rule.reason


def test_광주_대상_요약은_그대로_가능() -> None:
    p = program("[광주] 2026년 AI 기업 지원", requirement_sentences=["광주광역시 소재 중소기업"], region_tags=["전남광주"])
    assert sas._biz_region(p, SAMPLEEDU).status == "PASS"


# --------------------------------------------------------------------------
# 7) 「소상공인만 대상」은 대상이 소상공인 하나일 때만
# --------------------------------------------------------------------------


@pytest.mark.parametrize("line", [
    "지원대상 : 농식품 데이터를 활용하여 신규 비즈니스 창출을 추진하고자 하는 중견(초기)·중소기업, 소상공인",
    "신청자격 : 글로벌시장 진출을 희망하는 중소기업 및 소상공인",
    "근로기준법 제2조, 소상공인기본법 시행령 제3조 제3항 및 제4항 참고",
])
def test_소상공인이_나열되거나_법_이름이면_소상공인만_대상이_아니다(line: str) -> None:
    req = requirements(f"○ 신청자격\n{line}")
    assert sas._biz_small_business(req, program(target="중소기업"), SAMPLEEDU, date(2026, 10, 8)) is None


def test_소상공인_하나만_대상이면_인원으로_본다() -> None:
    req = requirements("○ 신청자격\n신청대상 : 사업자등록을 한 소상공인")
    rule = sas._biz_small_business(req, program(target="중소기업"), SAMPLEEDU, date(2026, 10, 8))
    assert rule is not None and rule.status == "CHECK"


# --------------------------------------------------------------------------
# 8) R33-01 · 02 — 선행 선정 절차 꼴(검수 표본 10줄)
# --------------------------------------------------------------------------

PROCEDURE_LINES = [
    "ㅇ (결과통보) 선정기업에 한하여 선정심사일로부터 5일 이내 개별 통보",
    "최종 선정된 기관에 한하여 제출 선정기관 협약전",
    "선정평가가 완료된 후 선정기업에 한하여 개별 통보",
    "최종 선정된 기업에 한하여 협약을 체결한 후 사업비를 지급",
    "선정된 기업에 한해서 추후 원본 제출을 요청할 수 있음",
]
REQUIREMENT_LINES = [
    "강진군 밀키트 사업 선정업소로 (식육)즉석판매제조가공업 영업 신고 및 사업자등록 되어 있는 업소",
    "1단계 사업 협약이 완료된 선정기업에 한하여 지원",
    "2025년 바우처 사업 수행이 종료된 선정기업에 한하여 신청",
    "1차 사업 협약이 체결된 선정기업에 한하여 지원",
    "2025년 예비창업패키지에 선정된 기업으로서 신청 가능",
]


def prior_keys(line: str) -> list:
    return [c.detail.get("requirement") for c in requirements(f"○ 신청자격\n{line}").of("prerequisite")]


@pytest.mark.parametrize("line", PROCEDURE_LINES)
def test_선정_뒤_절차_문장은_선행_선정_요건이_아니다(line: str) -> None:
    assert "prior_selection" not in prior_keys(line)


@pytest.mark.parametrize("line", REQUIREMENT_LINES)
def test_진짜_선행_선정_요건은_그대로_요건(line: str) -> None:
    assert "prior_selection" in prior_keys(line)


def test_가능_판정_한_벌_122145_는_샘플에듀에게_가능() -> None:
    label, _reason = verdict(T_122145)
    assert label in ("가능", "확인 필요")
