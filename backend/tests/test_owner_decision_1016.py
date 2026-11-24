"""담당자 결정 2026-10-16 — 공고명에 AI 낱말 + 「구축 · 도입 · 시스템」이면 본업(개발) 후보.

37차까지는 「공고명에 AI 낱말만 있고 교육 · 컨설팅 · 개발 낱말이 없다」로 후보가 아니었다(38차 보고 (7) 7).
제목(기관 이름 조각을 뺀)에서만 본다 — 설명 · 기관명 · 분류명의 「시스템」 · AI 낱말로는 바뀌지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.schemas.procurement import ProcurementNotice
from app.services import opportunity_filter as f


def _notice(title: str, *, agency: str = "기관", description: str | None = None, raw: dict | None = None) -> ProcurementNotice:
    return ProcurementNotice(
        id="g2b-R26BK00000001-000", notice_no="R26BK00000001-000", title=title, agency=agency,
        published_at=datetime(2026, 10, 1, tzinfo=timezone.utc), description=description, raw_data=raw or {},
    )


@pytest.mark.parametrize(
    ("title", "word"),
    [
        ("온프레미스 기반 Multi-modal AI Agent 및 Graph RAG 시스템 구축", "구축"),
        ("나사렛대학교 AI 학사상담 챗봇 시스템 구축", "시스템"),
        ("기술평가 업무 지원을 위한 생성형 AI 구독 서비스 도입", "도입"),
        ("AI 수사자료 표준화 시스템 유지관리", "시스템"),
    ],
)
def test_제목의_AI_낱말과_구축_도입_시스템은_개발_후보(title: str, word: str) -> None:
    match = f.classify(_notice(title))
    assert match.is_candidate and match.tier == "high"
    assert word in match.matched_dev and match.low_reason is None


def test_AI_낱말이_기관명에만_있으면_그대로_후보_아님() -> None:
    match = f.classify(_notice("통합 행정 시스템 구축", agency="인공지능산업융합사업단"))
    assert not match.is_candidate


def test_구축_시스템이_설명에만_있으면_그대로_AI_낱말만() -> None:
    match = f.classify(_notice("AI 활용 현황 조사", description="정보 시스템 구축 이력 조사"))
    assert not match.is_candidate and "AI 낱말" in (match.low_reason or "")


@pytest.mark.parametrize(
    "title",
    [
        # 10-16 실제 자료에서 이 결정으로 끌려왔던 셋 — 부서 이름 속 AI · 행사 음향 장비 · 실습실 장비 설치
        "[정보화/중앙/헬스케어인공지능연구과] 2027년 임상연구관리시스템 유지관리 및 운영 지원",
        "AI 포럼 영상·음향 시스템 대행 용역 (2인이상 견적 수의계약)",
        "카자흐스탄 크즐오르다 대학교 인공지능 단과대학 내 VR 실습실 장비 설치사업 구축",
        "AI 융합센터 건립 설계용역",
    ],
)
def test_부서_이름_장비_시설은_후보가_아니다(title: str) -> None:
    assert not f.classify(_notice(title)).is_candidate


def test_시스템_낱말만_있는_SI_공고는_여전히_후보가_아니다() -> None:
    match = f.classify(_notice("상수도 관제시스템 구축"))
    assert not match.is_candidate


@pytest.mark.parametrize("title", ["AI GPU 서버 구축 용역", "AI 실습 장비 도입", "AI 학습용 GPU 서버 도입"])
def test_장비_서버_구축은_결정_밖이라_그대로_후보_아님(title: str) -> None:
    """CLAUDE.md §4-C 「AI GPU 서버 구축 → 낮은 적합도」 — 소프트웨어 · 서비스 구축만 개발 갈래다."""
    match = f.classify(_notice(title))
    assert not match.is_candidate
    assert "장비 · 서버" in (match.low_reason or "")
