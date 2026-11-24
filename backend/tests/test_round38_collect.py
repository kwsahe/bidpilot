"""38차 §3-A — 나라장터 수집 넓히기 · 분류 합격선 (prompt_28 · 규칙 판 57).

시험 자료는 recheck30 부록 `docs/reports/2026-11-03_coverage/sweep_candidates.csv`(10-14 웹 탐색 79건)다.
「없음 — 나라장터에 있으나 제목에 AI 낱말이 없어 안 받음」 26건 중 샘플에듀 본업(A1 교육운영 · A2 과정개발 · B1 컨설팅 ·
ESG · AX)은 새 낱말로 **수집되고**(나라장터 공고명 검색은 부분 일치 · 띄어쓰기 무시) 분류가 **후보**여야 한다.
비추천 예시는 옛 저장본(Git 이력)의 실제 제목이다.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.schemas.procurement import ProcurementNotice
from app.services import opportunity_filter as f
from app.services import procurement_service as ps

REPO = Path(__file__).resolve().parents[2]
SWEEP = REPO / "docs" / "reports" / "2026-11-03_coverage" / "sweep_candidates.csv"
KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 15, 9, 0, tzinfo=KST)


def notice(title: str, *, published: datetime | None = None, deadline: datetime | None = None, no: str = "R26BK00000001") -> ProcurementNotice:
    return ProcurementNotice(
        id=f"g2b-{no}-000", notice_no=f"{no}-000", title=title, agency="시험 기관",
        published_at=published or datetime(2026, 10, 1, tzinfo=KST), deadline_at=deadline, raw_data={},
    )


def collected_by(title: str) -> list[str]:
    """나라장터 공고명 검색과 같은 규칙 — 부분 일치 · 띄어쓰기 무시(L1 실측: 「역량강화」 = 「역량 강화」)."""
    squashed = title.replace(" ", "").lower()
    return [k for k in f.COLLECT_KEYWORDS if k.replace(" ", "").lower() in squashed]


def _sweep_rows() -> list[dict[str, str]]:
    if not SWEEP.exists():  # 사내 탐색 자료(docs/)는 저장소에 없다 — 있는 복제본에서만 잰다
        return []
    rows = list(csv.DictReader(SWEEP.open(encoding="utf-8-sig")))
    return [r for r in rows if r["BidPilot"].startswith("없음") and "AI 낱말" in r["BidPilot"]]


def _is_core(row: dict[str, str]) -> bool:
    kind = row["유형(탐색 추정)"]
    return kind.startswith(("A1", "A2", "B1")) or "ESG" in row["공고"] or "AX" in row["공고"]


@pytest.mark.skipif(not SWEEP.exists(), reason="사내 탐색 자료(docs/) 없음")
def test_시험_자료는_26건이다() -> None:
    assert len(_sweep_rows()) == 26


@pytest.mark.parametrize("row", [r for r in _sweep_rows() if _is_core(r)], ids=lambda r: r["공고"][:24])
def test_본업_26건은_수집되고_후보다(row: dict[str, str]) -> None:
    title = row["공고"]
    assert collected_by(title), f"수집 낱말에 안 걸림: {title}"
    match = f.classify(notice(title))
    assert match.is_candidate, f"{title} → {match.tier} · {match.low_reason}"


@pytest.mark.parametrize(
    "title",
    [
        "(긴급) 2026학년도 금곡고등학교 2학년 수학여행 위탁용역",
        "2026학년도 광영여자고등학교 2학년 소규모테마형 교육여행 위탁용역",
        "2026학년도 2학년 제주도 현장체험학습(수학여행) 위탁용역",
        "2026년 AI·디지털 기반 교육혁신 국외연수 대행 용역",  # AI 가 있어도 여행 용역
        "2026년 AI디지털기반 수업혁신 역량강화 교원 해외연수 위탁용역",
        "2026년 SW미래채움 우수 강사 국외 역량강화교육 운영",
        "2026년도 지방공무원 공무국외연수 위탁용역",
        "2026년 코레일유통(주) 폭력예방 대면교육 대행 용역",
        "2026년 대전광역시교육청 학교폭력 감수성 진단 검사 용역",
        "2026년 용인교육지원청 교육시설과 전기‧통신‧소방공사 하자검사 용역 소액수의 견적 제출",
        "2026학년도 2학기 경산중학교 수학여행 차량 임차용역 소액수의 견적제출 안내공고",
        "2026. 역사문화교육연계 무안반도 역사문화 체험 차량 임차 용역",
        "2026년 재외동포 교육콘텐츠 해외배송",
    ],
)
def test_본업이_아닌_교육_여행_시설은_비추천과_사유(title: str) -> None:
    match = f.classify(notice(title))
    assert match.tier == "low" and not match.is_candidate, title
    assert match.low_reason and "본업이 아닌" in match.low_reason, match.low_reason


def test_AI동행_데모데이_기획_운영은_후보다() -> None:
    # recheck30 — 받았지만 「기획 · 운영」이 업무 낱말에 없어 관련 낮음으로 숨었다(1757066 · 2억).
    assert f.classify(notice("2026년 AI동행 데모데이 기획·운영 및 성과 확산")).is_candidate


@pytest.mark.parametrize(
    ("title", "ai"),
    [
        ("KAIST CTxAI 콘텐츠 마이크로디그리 과정 운영", "AI"),  # 소문자 뒤 대문자 마디
        ("G밸리 M.AX 인재육성 아카데미 교육 운영", "AX"),
        ("공무원 챗GPT 활용 교육", "챗GPT"),
    ],
)
def test_AX_GPT_합성어_마디도_AI_낱말이다(title: str, ai: str) -> None:
    match = f.classify(notice(title))
    assert ai in match.matched_ai and match.is_candidate


@pytest.mark.parametrize("title", ["MAIN 시스템 유지관리 용역", "TAX 정보 시스템", "MAX 장비 구매", "domain 관리"])
def test_대문자_뒤나_소문자_낱말은_AI_AX_가_아니다(title: str) -> None:
    match = f.classify(notice(title))
    assert not {"AI", "AX"} & set(match.matched_ai), title


def test_교육청_기관명의_교육은_본업이_아니다() -> None:
    match = f.classify(notice("2026년 서울특별시교육청 청사 냉난방기 유지관리 용역"))
    assert not match.is_candidate


def test_넓힌_수집_낱말로_받은_본업_아닌_공고도_사유와_남는다() -> None:
    match = f.classify(notice("디지털 트윈 플랫폼 구축"))
    assert match.tier == "low" and "디지털" in (match.low_reason or "")


# --------------------------------------------------------------------------
# §3-A-4 — 열린 공고는 게시 30일이 지나도 남긴다 (1726242)
# --------------------------------------------------------------------------


def _view(n: ProcurementNotice) -> ps.NoticeView:
    return ps.NoticeView(notice=n, match=f.classify(n))


def _cached(*views: ps.NoticeView) -> ps.ProcurementResult:
    return ps.ProcurementResult(source="cached", notices=list(views), fetched_at=NOW, total_fetched=len(views))


def test_창_밖으로_밀린_열린_공고는_이어_붙인다() -> None:
    old_open = notice("연암공대 AI 교육 운영", published=NOW - timedelta(days=34), deadline=NOW + timedelta(days=7), no="R26BK01726242")
    out = ps.carry_open_notices([], _cached(_view(old_open)), now=NOW, days=30)
    assert [v.notice.id for v in out] == [old_open.id]


@pytest.mark.parametrize(
    "case",
    [
        dict(published=-34, deadline=-1),   # 이미 마감
        dict(published=-34, deadline=None),  # 마감일 모름
        dict(published=-10, deadline=7),    # 창 안인데 이번에 안 옴 — 취소 · 삭제일 수 있음
    ],
)
def test_마감됐거나_창_안에서_빠진_공고는_붙이지_않는다(case: dict) -> None:
    deadline = None if case["deadline"] is None else NOW + timedelta(days=case["deadline"])
    stale = notice("AI 교육 운영", published=NOW + timedelta(days=case["published"]), deadline=deadline)
    assert ps.carry_open_notices([], _cached(_view(stale)), now=NOW, days=30) == []


def test_새_차수가_왔으면_옛_차수를_붙이지_않는다() -> None:
    old = notice("AI 교육 운영", published=NOW - timedelta(days=34), deadline=NOW + timedelta(days=7), no="R26BK01726242")
    new = old.model_copy(update={"id": "g2b-R26BK01726242-001", "notice_no": "R26BK01726242-001"})
    out = ps.carry_open_notices([_view(new)], _cached(_view(old)), now=NOW, days=30)
    assert [v.notice.id for v in out] == [new.id]


# --------------------------------------------------------------------------
# §3-G 후속 — 넓힌 수집 실제 1회(L2)에서 본 거짓 본업(규칙 판 61)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "candidate"),
    [
        ("수성구 농악 전수교육관 건립 용역사업 집행계획(설계공모)", False),  # L2 사본에서 샘플에듀 실무순 1위로 올라왔던 것
        ("(긴급)국립목포대학교 GSP 교육·연구·산학협력 공간 재조성을 위한 설계용역(제안공모)", False),
        ("2027~2028년 교육광장 발간 용역", False),
        ("AI 교육센터 인테리어 공사", False),  # AI 낱말이 있어도 공사 · 인테리어
        ("교육과정 설계 컨설팅", True),  # 본업 「설계」는 막지 않는다
        ("AI 교육과정 설계 및 운영", True),
        ("중장기 ESG 경영전략 수립 및 ESG 경영보고서 발간 용역", True),  # recheck30 본업 — 다른 본업 낱말이 있으면 「발간」이 있어도 본업
        ("교재 발간 및 교육 운영", True),  # 일 낱말이 함께 있으면 펴내는 일만이 아니다
    ],
)
def test_건축_설계_펴내기는_교육_낱말이_있어도_본업이_아니다(title: str, candidate: bool) -> None:
    match = f.classify(notice(title))
    assert match.is_candidate is candidate, (title, match.low_reason)
    if not candidate:
        assert match.low_reason and "본업이 아닌" in match.low_reason


def test_건립은_AI_낱말이_있으면_본업에서_빼지_않는다() -> None:
    # 같은 저장본에서 「한-우 법센터 건립사업 PMC」(사업담당자 GPT 「파트너형」)가 「건립」 하나로 후보에서 빠졌다 — 그래서 AI 낱말이 없을 때만
    title = "우즈베키스탄 AI 기반 법률서비스 환경 구축 및 한-우 법센터 건립사업 PMC 용역"
    assert f.noncore_of(title, ai=True) is None
    assert "건립" in (f.noncore_of("수성구 농악 전수교육관 건립 용역사업", ai=False) or "")
