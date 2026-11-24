"""40차 §3-C — 주제 확인(담당자 결정 1 · D23): 교육 · 컨설팅인데 공고명에 회사 사업 주제가 없으면 본업 덩어리 안에서 뒤로.

숨기지도 접지도 않는다 · 판정 · 점수는 그대로 · 꼬리표는 `practical_priority.tags_of` 한 함수(사업기회 행 · 브리핑 판단 칸 · 엑셀 · 표).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.business_opportunity import NextRoute, UnifiedOpportunity
from app.services import opportunity_brief_service as brief
from app.services import opportunity_export_service as exporter
from app.services import practical_priority as p
from app.services import prespec_service

NOW = datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc)
CEILING = 200_000_000


def _item(n: int, title: str, *, typ: str = "A1", source: str = "g2b", recruit: str | None = None, left: int = 20, age: int = 3,
          opportunity_type: str = "procurement", budget: int | None = 50_000_000) -> UnifiedOpportunity:
    return UnifiedOpportunity(
        id=f"{source}-{n:03d}", source_type=source, opportunity_type=opportunity_type, title=title, agency="서울 시험 기관",
        organization_id="org-sample", priority_rank=n, priority_label="검토", eligibility_gate="CHECK", confidence="medium",
        score_components=[], company_priority_score=60, next_route=NextRoute(kind="support_application", path="/", label="열기"),
        source="cached", deadline=NOW + timedelta(days=left), published_at=NOW - timedelta(days=age), recruit_kind=recruit,
        fit_type=typ, submission_methods=["전자입찰"], budget=budget,
    )


@pytest.mark.parametrize(
    ("title", "typ", "expected"),
    [
        ("2026년 국제조세 위탁교육", "A1", p.TOPIC_TAG),  # 주제 없는 교육 운영
        ("현장 중심 시뮬레이션 교육 운영", "A1", p.TOPIC_TAG),
        ("2026 직업훈련 교육훈련 과정 운영", "A1", p.TOPIC_TAG),  # 실무 문서 §2.3 일반 직업훈련 · 교육훈련
        ("중장기 발전계획 재정립 전략 수립 컨설팅", "B1", p.TOPIC_TAG),
        ("생성형 AI 활용 실무교육 운영", "A1", None),
        ("공무원 디지털 역량강화 교육", "A1", None),
        ("빅데이터 분석 실무 과정 운영", "A1", None),
        ("ESG 경영 컨설팅", "B1", None),
        ("기업 AX 전략 수립 컨설팅", "B1", None),
        ("SW 코딩 캠프 운영", "A1", None),
        ("디지털미디어고 교사 연수", "A1", p.TOPIC_TAG),  # 학교 이름 속 「디지털」은 주제가 아니다
        ("OO데이터진흥원 신규 직원 교육", "A1", p.TOPIC_TAG),
        ("세무 교육과정 온라인 콘텐츠 개발", "A2", None),  # A2 는 주제와 상관없이 맞음(실무 문서 §2.3-8)
        ("행정 시스템 개발", "C", None),
        ("2027년 공공기관 사이버교육 운영 위탁", "A1", None),  # 이러닝 갈래
        ("대학 SDGs 아카데미 운영", "A1", None),  # ESG 갈래
        ("공유대학 공동교육과정 개편", "A1", None),  # 교육과정 개편은 주제와 상관없이 맞음
        ("대학특화과정 교과목 컨설팅", "B1", None),
        ("신규 직원 역량강화 교육 운영", "A1", p.TOPIC_TAG),  # 일반 직무 교육은 주제 확인
        ("교육 정책 기초 연구", "B2", None),  # 본업 덩어리 밖 — 대상 아님
    ],
)
def test_주제_맞음_주제_확인(title: str, typ: str, expected: str | None) -> None:
    assert p.topic_of(_item(1, title, typ=typ)) == expected


def test_대상은_나라장터_입찰_사전규격_직접_넣은_입찰만() -> None:
    assert p.topic_of(_item(1, "세무 교육 운영", opportunity_type="pre_spec")) == p.TOPIC_TAG
    assert p.topic_of(_item(2, "세무 교육 운영", source="manual", recruit=p.RECRUIT_BID)) == p.TOPIC_TAG
    assert p.topic_of(_item(3, "세무 교육 운영", source="manual", recruit=p.RECRUIT_OPERATOR)) is None
    assert p.topic_of(_item(4, "세무 교육 운영", source="bizinfo", recruit=p.RECRUIT_BENEFIT, typ="수혜")) is None
    assert p.topic_of(_item(5, "세무 교육 운영 수행기관 모집", source="bizinfo", recruit=p.RECRUIT_OPERATOR)) is None


def _arrange(items: list[UnifiedOpportunity]) -> list[str]:
    p.annotate(items, now=NOW, ceiling_krw=CEILING)
    return [i.id for i in p.order(items, now=NOW, home_of=lambda _i: False)]


def test_본업_덩어리_안에서_주제_맞음_뒤로_그_안은_지금_순서() -> None:
    off_t1 = _item(1, "2026년 세무조사 위탁교육", left=30, age=2)  # 주제 확인 · T1(가장 먼저 볼 등급)
    on_t6 = _item(2, "AI 활용 실무교육", left=5, age=20)  # 주제 맞음 · T6
    on_t1 = _item(3, "생성형 AI 교육 운영", left=30, age=2)  # 주제 맞음 · T1
    side = _item(4, "교육 실태 기초 연구", typ="B2", left=30, age=2)  # 연구 덩어리
    assert _arrange([off_t1, side, on_t6, on_t1]) == [on_t1.id, on_t6.id, off_t1.id, side.id]
    assert off_t1.topic_note == p.TOPIC_TAG and off_t1.practical_block == p.BLOCK_CORE  # 숨기지 않고 본업 칸
    assert off_t1.practical_group == "신규+여유"  # 칸 · 판정 · 점수는 그대로
    assert side.topic_note is None


def test_대형_덩어리는_주제_꼬리표를_달지_않는다() -> None:
    large = _item(1, "세무 교육 운영", budget=900_000_000)
    p.annotate([large], now=NOW, ceiling_krw=CEILING)
    assert large.practical_block == p.BLOCK_LARGE and large.topic_note is None


def test_꼬리표는_한_함수로_브리핑_엑셀_표가_같은_값() -> None:
    item = _item(1, "2026년 세무조사 위탁교육", budget=300_000_000)
    p.annotate([item], now=NOW, ceiling_krw=CEILING)
    assert p.tags_of(item) == [item.scale_tag, p.TOPIC_TAG]
    assert brief.verdict_of(item).endswith(f"{item.scale_tag} · {p.TOPIC_TAG}")
    row = exporter._row(item)
    assert " · ".join(p.tags_of(item)) in row


def test_선제준비_보임은_주제_맞음_먼저() -> None:
    on = _item(1, "AI 교육 운영", opportunity_type="pre_spec", age=5)
    off = _item(2, "세무 교육 운영", opportunity_type="pre_spec", age=1)  # 더 새 것이지만 주제 확인
    for it in (on, off):
        it.opinion_deadline = NOW + timedelta(days=3)
    p.annotate([on, off], now=NOW, ceiling_krw=CEILING)
    section = prespec_service.section([off, on], now=NOW)
    assert [i.id for i in section.items] == [on.id, off.id]
