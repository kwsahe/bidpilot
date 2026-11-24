"""38차 §3-F — recheck30 결함(백엔드).

PRACTICAL-01 출처마다 자르기 · PRACTICAL-04 「… 접수 불가」 · PRACTICAL-05 수행기관도 광주 · 전남 · RULES-06 활동 지역 정식 이름 ·
RULES-01 · 03 컨소시엄 필수 꼴 · 역할 조항 중복 · RULES-04 경기 광주시 갈래 단서 · RULES-02 전담부서 미포함 창 기준점 ·
BRIEF-01 가상 예시 기업마당 · BRIEF-02 계산 방식 · 기간 · BRIEF-03 다시 들어옴 · 갈래 바뀜 · BRIEF-04 같은 저장본 · BRIEF-08 시연 고정 공고.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.schemas.business_opportunity import (
    NextRoute,
    OpportunitySummary,
    SupportClause,
    SupportProgram,
    SupportRequirements,
    UnifiedOpportunity,
    UnifiedOpportunityListResponse,
)
from app.services import opportunity_brief_service as brief
from app.services import opportunity_service, practical_priority as practical
from app.services import support_application_service as sas
from app.services import support_requirement_extractor as extractor

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
FETCHED = datetime(2026, 10, 15, 0, 35, tzinfo=timezone.utc)


def item(n: int, *, source: str = "g2b", left: int = 20, age: int = 3, agency: str = "서울 기관", executing: str | None = None,
         methods: list[str] | None = None, gate: str = "CHECK", group: str | None = None, recruit: str | None = None,
         pinned: bool = False, closed: bool = False) -> UnifiedOpportunity:
    return UnifiedOpportunity(
        id=f"{source}-T{n:03d}", source_type=source, opportunity_type="procurement" if source == "g2b" else "support_program",
        title=f"시험 {n}", agency=agency, executing_agency=executing, deadline=NOW + timedelta(days=left),
        published_at=NOW - timedelta(days=age), organization_id="org-sample", company_priority_score=60, priority_rank=n,
        source_rank=n, priority_label="검토", eligibility_gate=gate, gate_reason="-", confidence="medium", score_components=[],
        next_route=NextRoute(kind="procurement_analysis", path="/", label="열기"), source="cached", fit_type="A1",
        recruit_kind=recruit or (practical.RECRUIT_BID if source == "g2b" else practical.RECRUIT_BENEFIT),
        submission_methods=methods or (["전자입찰"] if source == "g2b" else ["미상"]), practical_group=group, pinned=pinned, closed=closed,
    )


# --------------------------------------------------------------------------
# PRACTICAL-01 — 출처마다 자르기
# --------------------------------------------------------------------------


def test_실무순이어도_limit_은_출처마다_자른다(monkeypatch) -> None:
    from app.schemas.organization import AnalysisContext

    g2b = [item(i, left=5) for i in range(1, 6)]  # 긴급(T6) — 실무순에서 기업마당 T1 뒤
    biz = [item(100 + i, source="bizinfo", left=30, age=1) for i in range(1, 11)]  # T1

    async def procurements(**_kwargs):
        return [x.model_copy() for x in g2b], "cached", None, None

    async def support(**_kwargs):
        return [x.model_copy() for x in biz], "cached", None, True, FETCHED

    monkeypatch.setattr(opportunity_service, "_collect_procurements", procurements)
    monkeypatch.setattr(opportunity_service, "_collect_support", support)
    monkeypatch.setattr(opportunity_service, "ranking_method_of", lambda _org: "practical")
    context = AnalysisContext(organization_id="org-sample", evidence_scope="internal")
    practical_list = asyncio.run(opportunity_service.list_opportunities(context=context, source="all", limit=3, now=NOW, include_blocked=True))
    score_list = asyncio.run(opportunity_service.list_opportunities(context=context, source="all", limit=3, sort="priority", now=NOW, include_blocked=True))
    count = lambda listing, s: sum(1 for i in listing.items if i.source_type == s)  # noqa: E731
    assert count(practical_list, "g2b") == count(score_list, "g2b") == 3
    assert count(practical_list, "bizinfo") == 3 and practical_list.returned_count == 6
    assert practical_list.total_count == 15  # 분모는 자르기 전


# --------------------------------------------------------------------------
# PRACTICAL-04 · 05
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("이메일 접수 불가, 온라인 접수만", [practical.METHOD_ONLINE]),
        ("방문·우편 접수 불가", [practical.METHOD_UNKNOWN]),
        ("이메일(abc@example.kr)로 제출", [practical.METHOD_EMAIL]),
        ("우편 접수는 받지 않으며 이메일로 제출", [practical.METHOD_EMAIL]),
        ("방문 접수(불가피한 경우 우편)", [practical.METHOD_VISIT, practical.METHOD_POST]),
    ],
)
def test_접수_불가_부정은_그_방식이_아니다(text: str, want: list[str]) -> None:
    assert practical.bizinfo_methods(text, None) == want


def test_기업마당_수행기관이_광주전남이면_기관_자체() -> None:
    home = item(1, source="bizinfo", agency="중소벤처기업부", executing="광주정보문화산업진흥원", methods=[practical.METHOD_VISIT])
    away = item(2, source="bizinfo", agency="중소벤처기업부", executing="서울산업진흥원", methods=[practical.METHOD_VISIT])
    rows = [away, home]
    opportunity_service._apply_practical(rows, organization_id="org-sample", now=NOW)
    assert home.practical_order < away.practical_order  # 같은 등급 · 같은 유형 — 접수방식 자리만 다르다(1 < 2)


# --------------------------------------------------------------------------
# RULES-06 · 01 · 03 · 04 · 02
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "want"), [("부산광역시", "부산"), ("서울특별시", "서울"), ("경기도", "경기"), ("광주광역시", "전남광주"), ("전라남도", "전남광주"), ("부산", "부산")])
def test_활동_지역_정식_이름을_태그_이름으로(name: str, want: str) -> None:
    assert sas._region_aliases(name) == (want,)


@pytest.mark.parametrize(
    ("line", "required"),
    [
        ("국제 컨소시엄(일본 필수 포함)을 구성하여 신청", True),
        ("컨소시엄을 구성한 기업만 신청 가능", True),
        ("국내 기업 2개사 이상이 컨소시엄 구성하여 참여하는 것이 필수", True),
        ("컨소시엄 참여 필수", True),
        ("컨소시엄 구성 가능", False),
        ("컨소시엄을 구성하여 신청할 수 있음", False),
        ("컨소시엄연구개발과제의 경우 참여기관별 적용", False),
    ],
)
def test_컨소시엄_필수_꼴(line: str, required: bool) -> None:
    assert extractor.consortium_required(line) is required


def test_역할_조항_중복_거르기가_필수_줄을_남긴다() -> None:
    text = "\n".join([
        "1. 사업 개요",
        "○ 지원 내용: 컨소시엄 단위 과제를 지원합니다",
        "2. 신청 자격",
        "○ 신청 대상: 국내 중소기업",
        "○ 컨소시엄을 구성한 기업만 신청 가능",
    ])
    requirements = extractor.extract_from_text("PBLN_TEST01", text)
    roles = [c for c in requirements.of("role") if c.detail.get("role") == "consortium"]
    assert any(c.detail.get("required") for c in roles)
    company = SimpleNamespace(joint_bid_available=None)
    gap = sas._consortium_gap(requirements, company)
    assert gap is not None and gap.status == "CHECK" and "컨소시엄을 구성한 기업만" in gap.source


def _program(**extra) -> SupportProgram:
    return SupportProgram(id="bizinfo-PBLN_TEST02", title="시험 사업", agency="경기도", executing_agency="경기도경제과학진흥원", **extra)


def test_경기_광주시_대체에도_이전_갈래_단서는_남는다() -> None:
    clause = SupportClause(
        kind="location", label="소재: 광주시(광역시 줄임말)", source_text="광주시 소재 기업 또는 광주시로 이전 예정인 기업", page=1, section=None,
        detail={"region": "전남광주", "alias": "광주시", "site": "소재", "metro_short": True, "ambiguous": "경기 광주시", "relocation": True},
    )
    requirements = SupportRequirements(program_id="PBLN_TEST02", document_read=True, clauses=[clause])
    company = SimpleNamespace(location_region="전남광주", location_city=None)
    result = sas._biz_location(requirements, _program(), company)
    assert result.status == "CHECK"  # 예전: detail 을 통째로 바꿔 이전 갈래가 사라지고 불가


def test_전담부서_미포함은_개요_상자의_같은_줄이_아니라_본문_줄_근처에서_찾는다() -> None:
    overview = "○ 기업부설연구소를 보유한 기업"
    text = "\n".join([
        "□ 사업 개요",
        overview,
        "○ 지원 규모: 과제당 1억원",
        "○ 지원 기간: 12개월",
        "○ 지원 방식: 출연",
        "○ 신청 방법: 온라인",
        "○ 문의: 담당 부서",
        "○ 기타: 공고문 참조",
        "□ 신청 자격",
        overview,
        "※ 연구개발전담부서 인정서만 보유한 기업은 미포함",
    ])
    requirements = extractor.extract_from_text("PBLN_TEST03", text)
    labs = [c for c in requirements.of("prerequisite") if c.detail.get("requirement") == "research_department"]
    assert labs and labs[0].detail.get("lab_only") is True


# --------------------------------------------------------------------------
# BRIEF-01 · 02 · 03 · 04 · 08
# --------------------------------------------------------------------------


def _listing(items, *, method="practical", days=30, fetched=None, bizinfo_status="cached", org="org-sample"):
    return UnifiedOpportunityListResponse(
        organization_id=org, organization_name="주식회사 샘플에듀", total_count=len(items),
        g2b_count=sum(1 for i in items if i.source_type == "g2b"), bizinfo_count=sum(1 for i in items if i.source_type == "bizinfo"),
        returned_count=len(items), closed_count=0, source_status={"g2b": "cached", "bizinfo": bizinfo_status}, source_errors={}, fetched_at=FETCHED,
        source_fetched_at=fetched if fetched is not None else {"g2b": FETCHED, "bizinfo": FETCHED},
        summary=OpportunitySummary(open_total=len(items), open_g2b=0, open_bizinfo=0, priority=0, closed=0, closed_pinned=0, days=days, new_days=3),
        sort=method, ranking_method=method, field_mapping_verified=True, note="시험", items=items,
    )


def _ranked(items):
    practical.annotate(items, now=NOW, ceiling_krw=200_000_000)
    practical.order(items, now=NOW, home_of=lambda i: False)
    for n, i in enumerate(items, start=1):
        i.priority_rank = n
    return items


@pytest.fixture()
def briefs(tmp_path, monkeypatch):
    monkeypatch.setattr(brief, "briefs_dir", lambda _org: tmp_path / "briefs")


def test_기업마당이_가상_예시면_경고하고_순위표를_남기지_않는다(briefs) -> None:
    body, snapshot = brief.build_markdown(_listing(_ranked([item(1)]), bizinfo_status="sample"), now=NOW, previous=None)
    assert "기업마당은 받아 둔 목록이 없어 가상 예시로 대신했습니다" in body
    assert brief.save_snapshot("org-sample", snapshot, now=NOW) is None


def test_계산_방식이_바뀌면_오름_내림을_내지_않는다(briefs) -> None:
    items = _ranked([item(i, left=20 + i) for i in range(1, 8)])
    _, first = brief.build_markdown(_listing(items, method="score"), now=NOW, previous=None)
    for i in items:  # 순서를 뒤집어도
        i.practical_order = 100 - i.practical_order
    body, _ = brief.build_markdown(_listing(items, method="practical"), now=NOW + timedelta(hours=1), previous=first)
    assert "계산 방식이 바뀌어 순위 비교는 하지 않음 — 새로 · 탈락만" in body
    assert "계단 이상 오른 것" not in body and "계단 이상 내린 것" not in body
    later = _ranked([item(i, left=20 + i) for i in range(1, 9)])  # 새로 하나 — 표 꼴에서도 오름 · 내림 칸이 그 말
    body, _ = brief.build_markdown(_listing(later, method="practical"), now=NOW + timedelta(hours=2), previous=first)
    assert body.count("계산 방식이 바뀌어 순위 비교는 하지 않음 — 새로 · 탈락만") == 2 and "새로 들어온 것 1건" in body


def test_다시_들어옴과_갈래_바뀜(briefs) -> None:
    before = _ranked([item(1), item(2, gate="FAIL"), item(3, source="bizinfo", recruit=practical.RECRUIT_BENEFIT)])
    _, first = brief.build_markdown(_listing(before), now=NOW, previous=None)
    after = _ranked([item(1), item(2), item(3, source="bizinfo", recruit=practical.RECRUIT_OPERATOR)])
    body, _ = brief.build_markdown(_listing(after), now=NOW + timedelta(hours=1), previous=first)
    row = next(r for r in body.splitlines() if "다시 들어옴(제외 · 비추천이던 것)" in r)
    assert "다시 들어옴(제외 · 비추천이던 것) 1건" in row and "갈래 바뀜(매출 ↔ 지원금) 1건" in row


def test_같은_저장본은_두_출처가_모두_같을_때만(briefs) -> None:
    items = _ranked([item(1)])
    _, first = brief.build_markdown(_listing(items), now=NOW, previous=None)
    newer = {"g2b": FETCHED, "bizinfo": FETCHED + timedelta(hours=2)}  # 기업마당만 새로 받음
    body, _ = brief.build_markdown(_listing(items, fetched=newer), now=NOW + timedelta(hours=3), previous=first)
    assert "같은 저장본" not in body
    body_same, _ = brief.build_markdown(_listing(items), now=NOW + timedelta(hours=3), previous=first)
    assert "두 브리핑 모두 같은 저장본입니다" in body_same


def test_실제_회사_브리핑에서는_시연_고정_공고를_뺀다(briefs, monkeypatch) -> None:
    from app.services import organization_service

    pinned = item(9, pinned=True, closed=True, gate="FAIL", left=-30)
    rows = _ranked([item(1), pinned])
    monkeypatch.setattr(organization_service, "get_organization", lambda _org: SimpleNamespace(data_class="real"))
    body, snapshot = brief.build_markdown(_listing(rows), now=NOW, previous=None)
    assert "시험 9" not in body and "g2b-T009" not in snapshot["rows"]
    sheet, _ = brief.sheet_rows(_listing(rows), now=NOW)
    assert all(r[3] != "시험 9" for r in sheet)
    monkeypatch.setattr(organization_service, "get_organization", lambda _org: SimpleNamespace(data_class="synthetic"))
    body, _ = brief.build_markdown(_listing(rows), now=NOW, previous=None)
    assert "시험 9" in body  # 가상 예시 · 시험 회사는 그대로(시연용)
