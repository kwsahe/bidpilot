"""41차 2-A — 분류 · 주제 · 사전규격 대체 유형(recheck33 CLASSIFY-R40-* · TOPIC-* · 홀드아웃 회귀 둘 · G2 · G3 · G4).

40차가 만든 회귀 둘은 **이름으로** 둔다(D34 — 다시 생기지 않게): 행사기획 분류 AI 교육(명지대 「AI를 활용한 창업 아카데미」 · 「공직자 미래역량강화
교육 위탁」)과 선제준비 행사 대행(CES 공동관 · 「AI+ 페스타」). 규칙은 묶음 단위로 고쳤다 — 그 밖의 제목은 묶음마다 꾸민 예다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.business_opportunity import NextRoute, UnifiedOpportunity
from app.schemas.procurement import ProcurementNotice
from app.services import opportunity_filter as f
from app.services import practical_priority as p
from app.services import prespec_service

NOW = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)
EVENT = "기타행사기획및대행서비스"


def _notice(title: str, *, klass: str | None = None) -> ProcurementNotice:
    return ProcurementNotice(
        id="g2b-R26BK00000001-000", notice_no="R26BK00000001-000", title=title, agency="기관",
        published_at=datetime(2026, 10, 1, tzinfo=timezone.utc), raw_data={"procurement_class": klass} if klass else {},
    )


def _type(title: str) -> str:
    found = p._title_type(title)
    return found[0] if found else "-"


def _item(n: int, title: str, *, typ: str = "A1", group_source: str = "g2b", opportunity_type: str = "procurement",
          relevance: str | None = None, age: int = 3) -> UnifiedOpportunity:
    return UnifiedOpportunity(
        id=f"{group_source}-{n:03d}", source_type=group_source, opportunity_type=opportunity_type, title=title, agency="서울 시험 기관",
        organization_id="org-sample", priority_rank=n, priority_label="검토", eligibility_gate="CHECK", confidence="medium",
        score_components=[], company_priority_score=60, next_route=NextRoute(kind="support_application", path="/", label="열기"),
        source="cached", deadline=NOW + timedelta(days=20), published_at=NOW - timedelta(days=age), fit_type=typ,
        submission_methods=["전자입찰"], budget=50_000_000, relevance_note=relevance, practical_candidate=relevance is None,
    )


# --------------------------------------------------------------------------
# 회귀 ① — 행사 · 홍보 조달분류의 AI 교육(CLASSIFY-R40-02)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "2026학년도 명지대학교 AI를 활용한 창업 아카데미 용역",  # 홀드아웃 회귀(1777550)
        "[입찰참가 자격확인]2026년 공직자 미래역량강화 교육 위탁 용역",  # 홀드아웃 회귀(1778173)
        "생성형 AI 실무 연수 위탁 용역",
        "공무원 대상 생성형 AI 활용 특강 운영",
        "AI 역량강화 워크숍 운영",
        "공무원 생성형 AI 교육 영상 콘텐츠 제작",
        "디지털 역량강화 과정 위탁 운영",
    ],
)
def test_회귀_행사_분류의_AI_교육은_접지_않는다(title: str) -> None:
    match = f.classify(_notice(title, klass=EVENT))
    assert match.is_candidate, (title, match.low_reason)


@pytest.mark.parametrize(
    "title",
    [
        "2026 OO 시민 축제 행사 대행",
        "2027년 OO무대예술아카데미 운영 용역",  # AI 낱말 없는 문화 아카데미는 행사 · 문화 일
        "2026년 OO 지역조직 역량 강화 워크숍 운영 대행 용역",
        "OO 성과 보고회 개최",
    ],
)
def test_행사_분류는_교육_일_꼴이_없으면_그대로_접는다(title: str) -> None:
    assert not f.classify(_notice(title, klass=EVENT)).is_candidate


# --------------------------------------------------------------------------
# 회귀 ② — 선제준비 행사 대행(CLASSIFY-R40-03 · D26 대체 유형)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "CES 2027 KOREA-M.AX ALLIANCE 공동관 조성·운영",  # 홀드아웃 회귀
        "CES2027 KOREA-M.AX Alliance 공동관 운영 용역",  # 홀드아웃 회귀
        "소상공인 AI+ 페스타 행사 기획·운영 대행 용역",  # 홀드아웃 회귀
        "2026 OO 교육 페스티벌 행사 용역",
        "AI 산업 박람회 참가 부스 운영",
        "아세안 공무원 통상 아카데미 참가자 초청 업무 대행",
    ],
)
def test_회귀_사전규격의_행사_전시_대행은_본업이_아니다(title: str) -> None:
    assert f.event_title_of(title), title


@pytest.mark.parametrize("title", [
    "AI 부스트캠프 운영", "AI 교육 프로그램 운영 대행", "생성형 AI 아카데미 운영",
    "AI 리터러시 교육 대행", "AX 전략 수립 컨설팅 대행", "ESG 경영 컨설팅 운영 대행",  # 마지막 검토 — 맨 「대행」으로 접지 않는다
])
def test_사전규격도_교육_일_꼴이면_행사로_보지_않는다(title: str) -> None:
    assert f.event_title_of(title) is None


def test_사전규격_대체_유형에_그_밖_A1_은_없다() -> None:
    title = "소상공인 AI+ 기획 운영 용역"
    match = f.classify(_notice(title))
    assert match.is_candidate
    assert p.prespec_fallback(match, title) is None  # 40차는 「그 밖 A1」
    assert p.type_of_kinds([], title, fallback=p.prespec_fallback(match, title)) == ("D", "갈래 미분류")
    lxp = "K-LXP 활용 교과에 대한 생성형 AI 지원 및 관리 용역"  # 학교 교과 일 — 40차에 A1 이었던 것을 잃지 않는다
    assert p.prespec_fallback(f.classify(_notice(lxp)), lxp)[0] == "A1"
    share = "AI 공유대학 운영"  # 마지막 검토 — 공유대학 · 이러닝 · 양성도 교육 일
    assert p.prespec_fallback(f.classify(_notice(share)), share)[0] == "A1"


def test_사전규격_행사_꼴은_사유와_함께_다른_사전규격으로_접힌다() -> None:
    from app.core.config import get_settings
    from app.services import company_service, delivery_capacity_service

    raw = {"bfSpecRgstNo": "R26BD99999901", "prdctClsfcNoNm": "소상공인 AI+ 페스타 행사 기획·운영 대행 용역", "orderInsttNm": "시험 기관",
           "rcptDt": "2026-10-19 10:00:00", "opninRgstClseDt": "2026-10-25 18:00:00", "asignBdgtAmt": "50000000"}
    prespec_service.PRESPEC_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    prespec_service.PRESPEC_CACHE_FILE.write_text(json.dumps({"items": [raw]}, ensure_ascii=False), encoding="utf-8")
    org = get_settings().default_organization_id
    [row] = prespec_service.build_items(notices=[], organization_id=org, profile=company_service.load_profile(org),
                                        capacity=delivery_capacity_service.load(org), now=NOW, main_items=[])
    assert row.relevance_note and "페스타" in row.relevance_note
    assert row.practical_candidate is False
    p.annotate([row], now=NOW, ceiling_krw=200_000_000)
    section = prespec_service.section([row], now=NOW)
    assert [i.id for i in section.others] == [row.id] and not section.items


# --------------------------------------------------------------------------
# 낱말 경계 · 사유 · 유형(CLASSIFY-R40-01 · 04 · 06 · 07 · 10 · 12 · G2)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    ["AI 기반 대시보드 구축", "생성형 AI 활용 경영정보 대시보드 개발", "AI 스토리보드 자동생성 솔루션 개발", "공공부문 생성형 AI 생산성 플랫폼 구축"],
)
def test_대시보드_생산성은_장비가_아니다(title: str) -> None:
    assert f.classify(_notice(title)).is_candidate


@pytest.mark.parametrize("title", ["엣지 AI 캐리어보드 개발 및 생산", "AI 온보드 컴퓨터 개발", "AI 전자 화이트보드 구매 설치"])
def test_보드_생산_장비는_그대로_장비(title: str) -> None:
    match = f.classify(_notice(title))
    assert not match.is_candidate, (title, match)


def test_교과서_수업료는_업무_낱말이_아니다() -> None:
    assert not f.classify(_notice("AI 디지털교과서 단말기 구매")).is_candidate
    assert "교과" not in f.classify(_notice("AI 디지털교과서 구독료 지원 사업")).matched_work
    assert "수업" in f.classify(_notice("AI 활용 수업 지원")).matched_work


@pytest.mark.parametrize("title", ["소상공인 AI 마케팅 아카데미 운영", "중소기업 AI 마케팅 컨설팅", "AI 기반 관광 마케팅 플랫폼 구축"])
def test_AI_홍보_마케팅_예외는_교육_컨설팅_구축까지(title: str) -> None:
    assert f.classify(_notice(title)).is_candidate


@pytest.mark.parametrize("title", ["AI 홍보관 구축 용역", "AI 체험 홍보관 구축"])
def test_AI_홍보관_구축은_시설이라_접는다(title: str) -> None:
    assert not f.classify(_notice(title)).is_candidate


def test_해외배송_사유는_배송() -> None:
    reason = f.classify(_notice("AI 교육 교재 해외배송 용역")).low_reason or ""
    assert "배송 · 운송" in reason and "여행" not in reason


@pytest.mark.parametrize(
    ("title", "typ"),
    [
        ("AI 기반 휴대용 보안진단체계 개발 실증", "C"),  # 맨 「진단」은 컨설팅이 아니다
        ("AI 기반 설비 고장 진단 모델 개발", "C"),
        ("공공기관 디지털 역량 진단 용역", "B1"),
        ("교육 실태조사 및 진단 연구", "B1"),  # 연구 · 조사 + 진단은 그대로 컨설팅
        ("의료 AI 해커톤 운영", "A1"),
        ("의료영상 AI 역량강화 워크숍", "A1"),
        ("AI Scribe 솔루션 도입 및 실증 운영 지원(만성질환관리)", "D"),  # G2 의료 AI
        ("AI 자막 Transcribe 시스템 구축", "C"),  # 낱말 속 scribe 는 의료가 아니다
        ("OO 교육 시스템 개인정보 영향평가", "D"),  # G2 영향평가는 감리성 업무
        ("2026 OO 대학 AI 드래프톤 운영 용역", "A1"),  # G4
    ],
)
def test_유형_진단_의료_교육_낱말(title: str, typ: str) -> None:
    assert _type(title) == typ


def test_드래프톤과_교육기관_콘텐츠_개발은_본업() -> None:
    assert f.classify(_notice("2026 OO 대학(원) AI 드래프톤 운영 용역")).is_candidate
    assert f.classify(_notice("OO대학교 2026학년도 전공 마이크로 콘텐츠 개발")).is_candidate
    assert f.classify(_notice("2026년 OO능력개발원 콘텐츠 개발 용역")).is_candidate
    assert not f.classify(_notice("OO 먹자골목 관광 콘텐츠 개발")).is_candidate  # 맨 「콘텐츠 개발」은 그대로 본업 아님


# --------------------------------------------------------------------------
# 주제 낱말(TOPIC-03 · 05 · 06 · 07 · G3) · 접힌 행(TOPIC-09) · 점수순 선제준비(TOPIC-02)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "typ"),
    [
        ("Ai 리터러시 교육 운영", "A1"),
        ("ai 활용 교육 운영", "A1"),
        ("RPA 업무 자동화 교육", "A1"),
        ("공무원 탄소 중립 실천 교육", "A1"),
        ("「AICC 도입방안 수립 컨설팅」", "B1"),
        ("AIDT 활용 교원 연수", "A1"),
        ("AIoT 실무 교육", "A1"),
        ("2026년 침해사고 수사과정 교육", "A1"),
        ("디지털 포렌식 실무 교육", "A1"),
        ("대학 모듈형 융합교육과정 도입 컨설팅 용역", "B1"),
    ],
)
def test_주제_낱말_대소문자_띄어쓰기_약어_교육과정_컨설팅(title: str, typ: str) -> None:
    item = _item(1, title, typ=typ)
    assert p.topic_of(item) is None, title


@pytest.mark.parametrize("title", ["MAIN 교육 운영", "OO고 교사 연수"])
def test_낱말_속_AI_와_학교_이름은_주제가_아니다(title: str) -> None:
    assert p.topic_of(_item(1, title)) == p.TOPIC_TAG


def test_비추천_행에는_주제_확인을_달지_않는다() -> None:
    folded = _item(1, "OO 전화외국어 교육과정 운영 위탁", relevance="본업이 아닌 교육 · 일 — 「외국어」")
    live = _item(2, "세무 교육 운영")
    p.annotate([folded, live], now=NOW, ceiling_krw=200_000_000)
    assert folded.practical_group == "비추천" and folded.topic_note is None and p.topic_rank(folded) == 0
    assert live.topic_note == p.TOPIC_TAG and p.topic_rank(live) == 1


def test_점수순_회사는_선제준비_순서를_주제로_바꾸지_않는다() -> None:
    on = _item(1, "AI 교육 운영", opportunity_type="pre_spec", age=5)
    off = _item(2, "세무 교육 운영", opportunity_type="pre_spec", age=1)  # 더 새 것 · 주제 확인
    for it in (on, off):
        it.opinion_deadline = NOW + timedelta(days=3)
    p.annotate([on, off], now=NOW, ceiling_krw=200_000_000)
    assert off.topic_note == p.TOPIC_TAG  # 꼬리표는 붙는다
    assert [i.id for i in prespec_service.section([on, off], now=NOW, by_topic=False).items] == [off.id, on.id]  # 등록일 새것 먼저
    assert [i.id for i in prespec_service.section([off, on], now=NOW).items] == [on.id, off.id]  # 실무순은 주제 맞음 먼저
