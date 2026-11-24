"""40차 §3-B — 분류 묶음(G1 · G3 · G5~G8 · CLASSIFY-04 · 05 · 07 · 08 · 10 · RANK-02 · D26).

**묶음 단위로 고친다**(§2 — 기준 답안 공고의 제목 조각을 그대로 박지 않는다). 그래서 여기 제목은 묶음마다 꾸민 예다.
숨기지 않고 사유와 함께 접는다(D15). 기준 답안 시험은 `test_precision_gold.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.schemas.procurement import ProcurementNotice
from app.services import opportunity_filter as f
from app.services import practical_priority as p


def _notice(title: str, *, klass: str | None = None) -> ProcurementNotice:
    raw = {"procurement_class": klass} if klass else {}
    return ProcurementNotice(
        id="g2b-R26BK00000001-000", notice_no="R26BK00000001-000", title=title, agency="기관",
        published_at=datetime(2026, 10, 1, tzinfo=timezone.utc), raw_data=raw,
    )


def _type(title: str) -> str:
    found = p._title_type(title)
    return found[0] if found else "-"


# --------------------------------------------------------------------------
# G1 — 이름 · 사업명 속 「교육」 · AI 아닌 시스템 구축
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "2026 광역시교육역사관 상설전시실 개편 연출 용역",  # 전시관 이름
        "산업안전교육센터 고도화 사업",  # 센터 이름 + 고도화
        "직무 역량기반 교육과정 시스템 고도화",  # 시스템 이름 속 「교육과정」
        "OO재단 교육사업 플랫폼 서비스 개발 지원 용역",  # 서비스 개발
    ],
)
def test_이름_속_교육과_AI_아닌_시스템_구축은_후보가_아니다(title: str) -> None:
    match = f.classify(_notice(title))
    assert not match.is_candidate, (title, match)
    assert match.low_reason


def test_서비스는_바로_뒤에_개발_동사가_올_때만_시스템_구축() -> None:
    match = f.classify(_notice("민간 고용서비스 종사자 교육 개편방안 연구 용역"))
    assert "웹 · 시스템 구축" not in (match.low_reason or "")
    assert _type("동영상 강의 영상 제작 사업") == "A2"
    assert f.online_edu_content("직종훈련 제약품질 온라인콘텐츠 대여")


def test_시스템과_함께여도_교육_운영이_있으면_후보다() -> None:
    assert f.classify(_notice("교육과정 운영 및 LMS 구축 용역")).is_candidate
    assert f.classify(_notice("교육관리 시스템 운영자 역량강화 교육")).is_candidate  # 「교육관리」는 이름 조각이 아니다


@pytest.mark.parametrize(
    ("title", "typ"),
    [
        ("창업 교육 수료생 실태조사", "B2"),
        ("2026학년도 교육 만족도 및 요구도 조사 용역", "B2"),
        ("평생교육 수요조사 용역", "B2"),
        ("OO산업 기반구축 사업 수요조사 및 추진전략 수립 용역", "B1"),  # 전략 수립이 함께면 컨설팅
        ("피지컬 AI 활용 고도화 방안 마련 용역", "B2"),
    ],
)
def test_조사_방안_마련은_연구다(title: str, typ: str) -> None:
    assert _type(title) == typ


# --------------------------------------------------------------------------
# G3 — 행사 · 공연 · 전시 · 홍보 대행
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "klass"),
    [
        ("2026년 OO군 공직자 역량강화 워크숍 위탁용역", "기타행사기획및대행서비스"),
        ("2026 국제 교류의 밤 행사 기획 운영 용역", "국제행사기획및대행서비스"),  # 프로그램 · 교육 운영 낱말 없는 행사
        ("교양 콘서트 온라인 콘텐츠 제작 용역", "공연기획및대행서비스"),
        ("AI·SW 학생 동아리 한마당", "축제기획및대행서비스"),
    ],
)
def test_행사_분류는_교육_운영_낱말이_없으면_접는다(title: str, klass: str) -> None:
    match = f.classify(_notice(title, klass=klass))
    assert not match.is_candidate
    assert "행사 · 공연 · 전시 · 홍보 대행" in (match.low_reason or "")


@pytest.mark.parametrize(
    ("title", "klass"),
    [
        ("2026년도 신규 직원 역량강화 교육 운영 용역", "기타행사기획및대행서비스"),
        ("AI 부트캠프 취업 컨설팅 및 교육 프로그램 운영 용역", "기타행사기획및대행서비스"),
        ("AI 역량 강화 학교 관리자 퍼실리테이션 워크숍 기획·운영", "회의기획및대행서비스"),
        ("2026 하이테크 리더스 포럼: AI 마스터 과정 3기 운영", "기타행사기획및대행서비스"),
        ("2026 소셜 AI 임팩트 챌린지(아이디어톤&해커톤) 운영 용역", "기타행사기획및대행서비스"),
        ("2026년 AI 창업 경진대회 용역", "기타행사기획및대행서비스"),
    ],
)
def test_행사_분류여도_교육_운영이면_후보다(title: str, klass: str) -> None:
    assert f.classify(_notice(title, klass=klass)).is_candidate


@pytest.mark.parametrize("title", ["OO아카데미 통합성과대회", "직업상담사 사례 발표회 및 역량강화 워크숍", "디지털 역량 워크숍 개최 용역"])
def test_성과대회_발표회_워크숍_개최는_본업이_아니다(title: str) -> None:
    match = f.classify(_notice(title))
    assert not match.is_candidate and "본업이 아닌 교육 · 일" in (match.low_reason or "")


# --------------------------------------------------------------------------
# G5 · G4 · RANK-02 — 기획연구 · 컨설팅 · PMC
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "typ"),
    [
        ("AI 기반 바이오 실증체계 구축사업 기획연구", "B2"),
        ("피지컬 AI 자동화 기술 개발 기획 연구", "B2"),
        ("AI 확산 신규 과제 발굴·기획 연구", "B1"),
        ("AX 인프라 연계 실증 기획용역", "B1"),
        ("OO기관 정보시스템 개선방안 연구", "B2"),
        ("기술컨설팅 고도화를 위한 개선방안 연구", "B1"),  # 컨설팅이 함께면 B1(주제는 §3-C 「주제 확인」이 본다)
        ("사업관리체계 고도화를 위한 AX ISP 수립", "B1"),
        ("OO국 직업훈련원 ODA 사업관리 용역", "D"),
        ("해외 교육 지원 사업 PMC 용역", "D"),
    ],
)
def test_기획연구_컨설팅_PMC_유형(title: str, typ: str) -> None:
    assert _type(title) == typ


# --------------------------------------------------------------------------
# G6 — 하드웨어 · 데이터 구축 · 의료 AI
# --------------------------------------------------------------------------


def test_AI_보드_생산은_장비다() -> None:
    match = f.classify(_notice("엣지 AI 제어보드 개발 및 생산 용역"))
    assert not match.is_candidate and "장비 · 서버" in (match.low_reason or "")


@pytest.mark.parametrize(
    ("title", "typ"),
    [
        ("인공지능 학습용 데이터 구축을 위한 영상 데이터 수집·가공 용역", "D"),
        ("AI READY DATA 가공 솔루션 구축 용역(데이터 가공·정제 · 현장 영상 수집)", "D"),
        ("호흡기 영상 인공지능 학습 데이터셋 구축 및 품질 관리", "D"),
        ("응급실 AI 기반 임상의사결정지원시스템(AI-CDSS) 개발", "D"),
        ("AI 학습데이터 구축 실무 교육 운영", "A1"),  # 교육 낱말이 있으면 데이터 꼴로 보지 않는다
        ("염색 공정 AI 모델 및 제조데이터 수집 컨설팅 용역", "B1"),  # 컨설팅이 함께면
    ],
)
def test_데이터_구축과_의료_AI는_D(title: str, typ: str) -> None:
    assert _type(title) == typ


# --------------------------------------------------------------------------
# G7 · G8 · CLASSIFY-04 · 07 · 08 · 10
# --------------------------------------------------------------------------


def test_AI_홍보_마케팅은_교육_낱말이_없으면_접는다() -> None:
    match = f.classify(_notice("지역 브랜드의 AI 활용 콘텐츠 제작 및 홍보"))
    assert not match.is_candidate and "홍보 · 마케팅 · 축제" in (match.low_reason or "")
    assert f.classify(_notice("공공기관 AI 홍보 마케팅 실무 교육")).is_candidate


def test_맨_온라인_콘텐츠는_교육_낱말과_함께일_때만_본업() -> None:
    assert f.core_terms_of("관광지 홍보 온라인 콘텐츠 제작") == []
    assert "온라인 콘텐츠" in f.core_terms_of("교양 교과목 온라인 콘텐츠 개발")
    assert f.online_edu_content("재난 분야 K-MOOC 개발")
    assert not f.online_edu_content("공연 온라인 콘텐츠 제작")


def test_면제_낱말_뒤의_본업_아님_낱말도_찾는다() -> None:
    # 「임차」는 교육 운영과 함께면 면제지만 뒤의 「체험장」까지 덮지 않는다
    match = f.classify(_notice("목공 교육 운영 및 시설 임차 체험장 관리"))
    assert not match.is_candidate and "「체험장」" in (match.low_reason or "") or "「시설」" in (match.low_reason or "")


def test_외국어는_기관_이름이면_접지_않는다() -> None:
    assert f.classify(_notice("OO외국어대학교 디지털 역량강화 교육 운영")).is_candidate
    assert f.classify(_notice("국제외국어고등학교 AX 컨설팅")).is_candidate
    assert not f.classify(_notice("외국어 교육 운영 용역")).is_candidate


@pytest.mark.parametrize(
    ("title", "klass", "candidate"),
    [
        ("AI 에이전트 기반 커리어 패스포트 운영", "취업지원교육서비스", True),
        ("AI 학습 코칭 프로그램 운영", "기타교육서비스", True),
        ("AI 문해력 서비스 운영", "정보화교육서비스", False),  # 정보화교육은 예외 밖
        ("AI 혁신 허브 운영", "기타교육서비스", False),  # 허브 · 센터 · 관 운영은 시설 운영
        ("AI 데이터센터 위탁운영", "기타교육서비스", False),
    ],
)
def test_AI_운영_조달분류_예외는_교육_운영_분류만(title: str, klass: str, candidate: bool) -> None:
    assert f.classify(_notice(title, klass=klass)).is_candidate is candidate


# --------------------------------------------------------------------------
# D26 — 사전규격 갈래 · 교수설계 · 해커톤 · 연구 수식어 · 대체 유형
# --------------------------------------------------------------------------


def test_교수설계는_설계_용역으로_접지_않는다() -> None:
    assert f.classify(_notice("직업교육센터 디지털트윈 기반 모듈형 교육 콘텐츠 기획 및 설계 용역")).is_candidate
    assert f.classify(_notice("AI 교육과정 설계 용역")).is_candidate
    assert not f.classify(_notice("교육관 신축 건축 설계 용역")).is_candidate


@pytest.mark.parametrize(
    ("title", "typ"),
    [
        ("AI 기반 초광역 리빙랩 해커톤 운영 용역", "A1"),
        ("로봇 OS 특강 및 챌린지 운영", "A1"),
        ("해양과학기술원 연구·행정 지원 AI Agent 개발 및 적용", "C"),
        ("한국전자통신연구원 AI 실무 교육", "A1"),  # 기관 이름 속 「연구」는 유형 근거가 아니다
        ("연구자 대상 생성형 AI 활용 교육", "A1"),
    ],
)
def test_해커톤_특강과_연구_수식어(title: str, typ: str) -> None:
    assert _type(title) == typ


def test_사전규격_대체_유형은_갈래_미분류_D_가_아니다() -> None:
    edu = f.classify(_notice("2026학년도 AI·DX 혁신역량 성장지원(재학생) 프로그램 용역"))
    assert p.type_of_kinds([], "2026학년도 AI·DX 혁신역량 성장지원(재학생) 프로그램 용역", fallback=p.prespec_fallback(edu, "2026학년도 AI·DX 혁신역량 성장지원(재학생) 프로그램 용역"))[0] == "A1"
    ax = f.classify(_notice("광역권 금속 기업 AX 기술지원 용역"))
    assert p.type_of_kinds([], "광역권 금속 기업 AX 기술지원 용역", fallback=p.prespec_fallback(ax, "광역권 금속 기업 AX 기술지원 용역"))[0] == "B1"
    none = f.classify(_notice("청사 경비 용역"))
    assert p.prespec_fallback(none) is None
    assert p.type_of_kinds([], "청사 경비 용역", fallback=None) == ("D", "갈래 미분류")


def test_본업_아님_사유_괄호는_낱말_묶음에_맞다() -> None:
    edcf = f.classify(_notice("EDCF 지원 AI 교육 정책 자문"))
    assert "공적개발원조" in (edcf.low_reason or "") and "여행" not in (edcf.low_reason or "")
    trip = f.classify(_notice("AI 교육 국외연수 대행"))
    assert "여행 · 국외연수" in (trip.low_reason or "")
