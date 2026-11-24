"""39차 §3-A — 분류 정밀도(D19 · recheck31 P1 · P4~P7 · P9 · COLLECT-01 · 02 · 04 · 05 · 07 · 08 · 09).

숨기지 않고 사유와 함께 접는다(D15). 기준 답안 시험은 `test_precision_gold.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.schemas.procurement import ProcurementNotice
from app.services import opportunity_filter as f


def _notice(title: str, *, klass: str | None = None, agency: str = "기관", description: str | None = None) -> ProcurementNotice:
    raw = {"procurement_class": klass} if klass else {}
    return ProcurementNotice(
        id="g2b-R26BK00000001-000", notice_no="R26BK00000001-000", title=title, agency=agency,
        published_at=datetime(2026, 10, 1, tzinfo=timezone.utc), description=description, raw_data=raw,
    )


@pytest.mark.parametrize(
    ("title", "klass"),
    [
        ("외국인 유학생 조기적응 및 역량강화 프로그램[경주]", "국내여행서비스"),
        ("2027 차세대 보안리더양성 글로벌 역량강화 프로그램 운영", "국내여행서비스"),
        ("설화고등학교 국외 AI FESTA 및 체험학습", "국외여행서비스"),
        ("AI·빅데이터 기반 학교 리더십 전략과정 직무연수 3기 연수시설 임차 용역", "숙박서비스"),
        ("단기해외교육봉사 항공권 발권 및 부대업무 대행", "항공여객운송서비스"),
        ("2027년 사법부 온라인 교육과정", "화상외국어교육서비스"),
    ],
)
def test_조달분류_부정_신호는_AI_낱말이_있어도_사유와_함께_접는다(title: str, klass: str) -> None:
    match = f.classify(_notice(title, klass=klass))
    assert not match.is_candidate
    assert match.low_reason == f"조달분류 「{klass}」 — 본업 아님(여행 · 숙박 · 운송 · 지역개발 · 어학)"


@pytest.mark.parametrize(
    "title",
    [
        "EBS 방송 및 교육 인터넷서비스 통합 운영 사업",
        "2027년 광주교육정보시스템 유지관리 및 보안관제 용역",
        "2027~2028년도 부산교육망센터 통합 유지관리",
        "2026년도 첨단분야 혁신융합대학 COSS/HUSS허브 (허브LMS) 교육 플랫폼 및 클라우드 유지보수·운영지원",
        "2027~2028년 통합교육포털 「강동 미래온」 유지보수 용역",
    ],
)
def test_정보시스템_유지관리는_본업이_아니다(title: str) -> None:
    match = f.classify(_notice(title))
    assert not match.is_candidate and "정보시스템 유지관리 · 운영" in (match.low_reason or "")


def test_조달분류_유지관리도_본업이_아니다_공고명_AI_면_후보로_둔다() -> None:
    plain = f.classify(_notice("2027년 교육 행정 지원 용역", klass="정보시스템유지관리서비스"))
    assert not plain.is_candidate and plain.low_reason.startswith("조달분류 「정보시스템유지관리서비스」")
    with_ai = f.classify(_notice("AI 수사자료 표준화 시스템 유지관리", klass="정보시스템유지관리서비스"))
    assert with_ai.is_candidate  # 유형은 D(연구 · 감리 · 구매 덩어리) — practical_priority


@pytest.mark.parametrize(
    "title",
    ["경제금융교육 통합 홈페이지 구축", "(긴급)2026년 소상공인연합회 소상공인교육원(소상공인 디지털교육센터) 홈페이지 리뉴얼 및 고도화",
     "경기교육 지방공무원 인사관리 플랫폼 구축"],
)
def test_교육이_이름_안에만_있는_웹_시스템_구축은_본업이_아니다(title: str) -> None:
    match = f.classify(_notice(title))
    assert not match.is_candidate and "이름 안에만" in (match.low_reason or "")


def test_LMS_구축과_교육_운영이_함께면_본업이다() -> None:
    assert f.classify(_notice("대학 LMS 구축 및 교육 운영 용역")).is_candidate


@pytest.mark.parametrize(
    "title",
    [
        "부안면 기초생활거점 조성사업 지역역량강화용역(협상에 의한 계약)",
        "횡성군 서원면 기초생활거점조성사업 지역역량강화 용역",
        "양양군 목재문화체험장 교육프로그램 운영 용역",
        "함평 엑스포공원 에듀테인먼트파크 조성사업 생태교육 프로그램 역량강화 용역",
        "2027-2028년 KOTRA 전화외국어 교육과정 운영 위탁",
        "울진 중학생 영어캠프 위탁 운영",
        "AX혁신센터 공간 설계 및 기자재 구입·설치 용역",
        "첨단 AI 기반 디지털의료기기 신속제품화 지원사업(AX-Sprint 300) - 식약처 허가를 위한 개발 문서 및 GMP 컨설팅 용역",
        "정보보호 및 개인정보보호 관리체계 인증(ISMS-P) 컨설팅 용역",
    ],
)
def test_농촌_체험_어학_공간_인허가는_본업이_아니다(title: str) -> None:
    match = f.classify(_notice(title))
    assert not match.is_candidate and match.low_reason


@pytest.mark.parametrize(
    "title",
    [
        "27년 AI 위협탐지 대응 실무인력 양성",
        "2027학년도 DSC공유대학(대전형공유대학) 온라인 콘텐츠 개발 용역",
        "(앵커) 재난안전분야 온라인 교육컨텐츠(K-MOOC) 개발",
        "INU 소셜 AI 임팩트 챌린지(아이디어톤&해커톤) 운영 용역",
        "생성형 AI 활용 특강 운영",
        "2026 청소년 디지털 역량강화 교육 운영",
        "국민건강보험공단 신규직원 디지털 역량강화 교육",
        "서울시설공단 직원 디지털 역량강화 교육",
        "경기도자영업아카데미 이러닝 임차 및 교육 운영",
    ],
)
def test_숨은_본업과_낱말_경계(title: str) -> None:
    match = f.classify(_notice(title))
    assert match.is_candidate, match.low_reason


@pytest.mark.parametrize(
    "title",
    ["관저동 먹자골목 콘텐츠 개발 용역 사업", "지역 콘텐츠 IP 활성화 프로그램 운영", "2026년 청소년 글로벌역량 강화사업 성과공유회"],
)
def test_콘텐츠_개발_프로그램_운영_낱말만으로는_본업이_아니다(title: str) -> None:
    assert not f.classify(_notice(title)).is_candidate


def test_AI_운영_용역은_조달분류가_교육일_때만_후보다() -> None:
    title = "2026년 글로컬대학 AI 에이전트 기반 「CWNU DNA+ AI 커리어 패스포트」운영 용역"
    assert f.classify(_notice(title, klass="취업지원교육서비스")).is_candidate
    assert not f.classify(_notice(title, klass="기타사업지원서비스")).is_candidate


def test_청소_보험_시설_낱말은_그_자체로는_여전히_접는다() -> None:
    for title in ("교육관 청소 용역", "교육 시설 보험 가입", "연수원 시설 관리 위탁"):
        assert not f.classify(_notice(title)).is_candidate, title


def test_AI_경로는_제목에서만_본다_조달분류_기관명은_근거가_아니다() -> None:
    match = f.classify(_notice("○○ 업무 지원 용역", description="교육서비스 > 정보화교육서비스", agency="한국AI진흥원"))
    assert not match.is_candidate
    infra = f.classify(_notice("대학 AI 인프라 기반 구축", description="SW 및 시스템 개발 > 정보시스템개발서비스"))
    assert not infra.is_candidate


def test_앞_괄호는_부서_이름_꼴만_지운다() -> None:
    assert f.strip_dept_labels("[정보화/중앙/헬스케어인공지능연구과] 임상연구관리시스템 유지관리") == "임상연구관리시스템 유지관리"
    assert f.strip_dept_labels("(AI)활용 시범사업") == "(AI)활용 시범사업"
    assert f.strip_dept_labels("[AI앵커]AWS 공인자격증 교육") == "[AI앵커]AWS 공인자격증 교육"


def test_띄어쓰기를_무시한다_전략수립() -> None:
    spaced = f.classify(_notice("OO시 지역산업 육성 전략 수립 연구용역"))
    joined = f.classify(_notice("OO시 지역산업 육성 전략수립 연구용역"))
    assert spaced.tier == joined.tier != "none"
