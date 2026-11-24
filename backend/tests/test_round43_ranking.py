"""43차 §2-C — 분류 · 순서 · 점수(결정 4 · Q1 · Q2 · M3 · M4 · M6 · Q5 · Q7 · Q8 · Q9 · Q12)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.procurement import ProcurementNotice
from app.services import home_agencies, opportunity_filter as f, opportunity_priority as priority
from app.services import practical_priority as practical, prespec_service, work_kinds


def _notice(title: str, klass: str | None = None) -> ProcurementNotice:
    return ProcurementNotice(id="g2b-T-000", notice_no="T", title=title, agency="기관", published_at=datetime.now(timezone.utc),
                             raw_data={"procurement_class": klass} if klass else {})


def test_결정4_제목이_갈래를_말하면_조달분류_연구조사로_그_밖에_묶지_않는다():
    n = _notice("[혁신]특성화 기반 교양·전공 교육과정 혁신 및 대학혁신 프로그램 운영 체계 구축 연구 용역", "학술연구서비스")
    out = work_kinds.of_notice(n)
    assert "other" not in out["tracks"] and "education" in out["tracks"]


def test_Q1_가명정보_개인정보는_주제_낱말():
    assert "가명정보" in practical.TOPIC_TERMS and "개인정보" in practical.TOPIC_TERMS


def test_Q2_이러닝_교육_임차_운영은_A1():
    assert practical._title_type("2027년 경기도자영업아카데미 소상공인 이러닝 교육 임차·운영 용역")[0] == "A1"
    assert practical._title_type("행사용 차량 임차 용역")[0] == "D"


def test_M3_컨설팅_낱말이_있어도_제작은_D():
    assert practical._title_type("UL인증 컨설팅 반영 50kW급 DAB DC-DC 컨버터 모듈 설계 및 제작 용역")[0] == "D"


def test_M3_수행기관_모집_유형은_제목에서만():
    typ, basis = practical.bizinfo_type("초격차 스타트업 1000+ 프로젝트 실증ㆍ구매 주관기관 모집", "역량 강화 지원", practical.RECRUIT_OPERATOR)
    assert typ == "D" and "미분류" in basis


def test_M3_이름_속_교육_누리집_공공건축_스키는_비추천():
    ai = lambda t: bool(f.matched_keywords(f.strip_dept_labels(t), f.AI_KEYWORDS))  # noqa: E731
    for title in ("2027년 법교육 누리집 및 SNS 채널 운영", "피지컬AI 실증단지 구축사업 공공건축 기획용역", "외국인 스키 강습"):
        assert f.noncore_of(title, ai=ai(title)), title
    assert "교육" not in f.core_title("2027부산 다자녀 교육지원포인트 사업 콜센터 운영")


def test_M6_Q7_수요기관_기준_광주_전남():
    assert priority.home_ground("조달청", "한국인터넷진흥원") == "한국인터넷진흥원"
    assert priority.home_ground("조달청 광주지방조달청", "충남대학교 산학협력단") is None
    assert priority.home_ground("남부대학교", None) == "남부대학교"
    assert not home_agencies.is_home("신안산대학교") and not home_agencies.is_home("경기도 광주시")
    assert home_agencies.display_agency("조달청", "국토교통부 국토교통인재개발원") == "국토교통부 국토교통인재개발원(조달청 대행)"


def test_발주계획_열쇠는_연도_띄어쓰기를_뺀다():
    assert prespec_service.title_key("2027년 인천형 AX ISP 수립") == prespec_service.title_key("인천형 AX ISP수립(사전규격)")


def test_Q8_호남권은_우리_지역():
    from app.services import support_application_service as sas
    from app.schemas.business_opportunity import SupportProgram

    program = SupportProgram(id="P", title="호남권 AX랩 지능형농업 경진대회", agency="과학기술정보통신부", executing_agency="광주테크노파크", region_tags=["전북", "광주", "전남"])
    assert sas._honam(program) and not sas._other_region(program, [])


def test_나라장터_목록_응답의_기관도_조달청_대행_표시값(notice_cache_file) -> None:
    """10-31 최종 점검 B2 — /api/procurements 는 「조달청」, 통합 목록은 「수요기관(조달청 대행)」이라 사업기회 행 · 입찰 분석 머리와
    레이더 · 제안서 작성이 같은 공고를 다른 기관으로 보였다. 응답만 바꾸고 저장된 원래 값(지역 판정용)은 그대로다."""
    from app.services import procurement_service

    n = ProcurementNotice(id="g2b-T-000", notice_no="T", title="AI 교육 운영", agency="조달청", published_at=datetime.now(timezone.utc),
                          raw_data={"demand_institution": "한국인터넷진흥원"})
    view = procurement_service.NoticeView(notice=n, match=f.classify(n))
    assert view.to_dict()["agency"] == "한국인터넷진흥원(조달청 대행)"
    assert view.notice.agency == "조달청"


def test_제안서_워드_머리도_조달청_대행_표시값(monkeypatch) -> None:
    """11-01 — 화면은 「대법원 사법연수원(조달청 대행)」인데 제안서 워드 머리만 「조달청 서울지방조달청」이었다."""
    import asyncio

    from app.services import procurement_service, proposal_export

    n = ProcurementNotice(id="g2b-T-000", notice_no="T", title="이러닝 콘텐츠 제작", agency="조달청 서울지방조달청",
                          published_at=datetime.now(timezone.utc), raw_data={"demand_institution": "대법원 사법연수원"})

    async def get_notice(_id):
        return procurement_service.NoticeView(notice=n, match=f.classify(n))

    monkeypatch.setattr(procurement_service, "get_notice", get_notice)
    assert asyncio.run(proposal_export._notice_line("g2b-T-000")) == "이러닝 콘텐츠 제작  (대법원 사법연수원(조달청 대행))"
