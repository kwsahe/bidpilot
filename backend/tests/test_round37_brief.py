"""37차 §3-H — 「오늘 브리핑」 마크다운 · 엑셀 「브리핑」 시트.

약속 넷.

1. 첫 브리핑은 「비교할 지난 브리핑 없음」, 같은 저장본으로 두 번째는 「변화 없음」과 두 시각을 적는다.
2. 머리 열셋이 정해진 순서로 나온다 · 모으지 않는 것(사전규격 · 발주계획)은 「아직 모으지 않음」으로 적는다.
3. 「파트너형」은 공동수급이 허용될 때만이다(공동수급 불가인데 파트너로 보완한다고 가정하지 않는다).
4. 엑셀은 시트 일곱 — 마지막이 「브리핑」이다.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest
from openpyxl import load_workbook

from app.schemas.business_opportunity import (
    NextRoute,
    OpportunitySummary,
    UnifiedOpportunity,
    UnifiedOpportunityListResponse,
)
from app.services import export_store
from app.services import opportunity_brief_service as brief
from app.services import opportunity_workbook as workbook

NOW = datetime(2026, 10, 14, 3, 0, tzinfo=timezone.utc)
FETCHED = datetime(2026, 10, 14, 0, 10, tzinfo=timezone.utc)

HEADINGS = (
    "# 오늘 브리핑 — 주식회사 샘플에듀",
    "## 지난 브리핑 대비 달라진 것",
    "# 오늘 핵심 결론",
    "# 신규 · 준비여유 최우선 후보",
    "# 직접도전 후보",
    "# 기관 자체접수 / PMS / 이메일형 후보",
    "# 나라장터 후보",
    "# 🔵 선제준비 — 사전규격 · 본공고 예정",
    "# 📥 GPT · 사람이 찾은 확인 전 후보 0건",  # 38차 §3-E-5
    "# 🚨 긴급 · 마감 임박",
    "# 🤝 대형 · 파트너형 후보",  # 38차 §3-B-5 — 긴급 칸 뒤 · 제외 칸 앞
    "# ❌ 제외 · 비추천",
    "# 광주 · 전남 / 대학 시장 신호",
    "# 오늘 전수조사 전체 후보풀",
    "# 오늘 실제 행동 우선순위",
)


def item(index: int, *, source: str = "g2b", gate: str = "PASS", group: str = "직접도전", **extra) -> UnifiedOpportunity:
    prefix = "g2b-" if source == "g2b" else "bizinfo-"
    fields = dict(
        id=f"{prefix}T{index:03d}",
        source_type=source,
        opportunity_type="procurement" if source == "g2b" else "support_program",
        title=f"시험 사업 {index}",
        agency="시험 기관",
        deadline=NOW + timedelta(days=20),
        published_at=NOW - timedelta(days=2),
        detail_url=f"https://example.invalid/{index}",
        organization_id="org-sample",
        company_priority_score=70,
        priority_rank=index,
        source_rank=index,
        priority_label="우선 검토",
        eligibility_gate=gate,
        gate_reason="시험 사유",
        confidence="medium",
        score_components=[],
        next_route=NextRoute(kind="support_application", path="/", label="신청 분석 열기"),
        source="cached",
        practical_group=group,
        practical_order=index,
    )
    fields.update(extra)
    return UnifiedOpportunity(**fields)


def listing(items: list[UnifiedOpportunity]) -> UnifiedOpportunityListResponse:
    return UnifiedOpportunityListResponse(
        organization_id="org-sample",
        organization_name="주식회사 샘플에듀",
        total_count=len(items),
        g2b_count=sum(1 for i in items if i.source_type == "g2b"),
        bizinfo_count=sum(1 for i in items if i.source_type == "bizinfo"),
        returned_count=len(items),
        closed_count=0,
        source_status={},
        source_errors={},
        fetched_at=FETCHED,
        # 38차 BRIEF-04 — 「같은 저장본」은 두 출처 받은 때가 모두 같을 때만이라 둘 다 적는다
        source_fetched_at={"g2b": FETCHED, "bizinfo": FETCHED},
        summary=OpportunitySummary(
            open_total=len(items), open_g2b=0, open_bizinfo=0, priority=0, closed=0, closed_pinned=0, days=30, new_days=3,
        ),
        sort="practical",
        ranking_method="practical",
        field_mapping_verified=True,
        note="시험",
        items=items,
    )


SAMPLE = [
    item(1),
    item(2, gate="CHECK", group="조건부"),
    item(3, source="bizinfo", group="신규+여유"),
    item(4, gate="FAIL", group="제외", gate_reason="지역 불가 — 시험"),
]


@pytest.fixture()
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(brief, "briefs_dir", lambda organization_id: tmp_path / "briefs")
    return tmp_path / "briefs"


def test_첫_브리핑은_비교할_지난_브리핑이_없다고_적는다(folder) -> None:
    body, snapshot = brief.build_markdown(listing(SAMPLE), now=NOW, previous=brief.latest_snapshot("org-sample"))
    assert "비교할 지난 브리핑 없음" in body
    assert snapshot["rows"]["g2b-T001"]["rank"] == 1


def test_같은_저장본으로_두_번째는_변화_없음과_두_시각을_적는다(folder) -> None:
    data = listing(SAMPLE)
    _, first = brief.build_markdown(data, now=NOW, previous=None)
    brief.save_snapshot("org-sample", first, now=NOW)
    body, _ = brief.build_markdown(data, now=NOW + timedelta(minutes=5), previous=brief.latest_snapshot("org-sample"))
    line = next(row for row in body.splitlines() if "변화 없음" in row)
    assert "지난 브리핑(2026-10-14 12:00 만듦)" in line
    assert "그때 목록 받은 때 2026-10-14 09:10" in line
    assert "같은 저장본" in line


def test_새로_들어온_것과_탈락한_것을_가른다(folder) -> None:
    _, first = brief.build_markdown(listing(SAMPLE[:2]), now=NOW, previous=None)
    later = [SAMPLE[0], item(2, gate="FAIL", group="제외"), item(5)]
    body, _ = brief.build_markdown(listing(later), now=NOW, previous=first)
    assert "새로 들어온 것 1건" in body
    assert "마감 · 탈락(불가 · 관련 낮음) 1건" in body


def test_마감돼_목록에서_빠진_공고는_지난_순위표의_제목으로_적는다(folder) -> None:
    # 마감 공고는 이번 목록(마감 뺌)에 아예 없다 — 전에는 제목 대신 공고 id 가 찍혔다(37차 마지막 검토)
    _, first = brief.build_markdown(listing([SAMPLE[0], item(7, title="곧 마감할 사업")]), now=NOW, previous=None)
    body, _ = brief.build_markdown(listing([SAMPLE[0]]), now=NOW, previous=first)
    line = next(row for row in body.splitlines() if "마감 · 탈락" in row)
    assert "곧 마감할 사업" in line and "g2b-T007" not in line


def test_머리_열셋이_정해진_순서로_나온다(folder) -> None:
    body, _ = brief.build_markdown(listing(SAMPLE), now=NOW, previous=None)
    heads = [row for row in body.splitlines() if row.startswith("# ") or row.startswith("## 지난")]
    assert tuple(heads) == HEADINGS


def test_모으지_않는_것은_아직_모으지_않음으로_적는다(folder) -> None:
    body, _ = brief.build_markdown(listing(SAMPLE), now=NOW, previous=None)
    # 38차 §3-D — 선제준비 칸은 사전규격 · 발주계획으로 채운다. 「아직 모으지 않음」은 기관 자체공고 칸에만 남는다.
    section = body.split("# 🔵 선제준비")[1].split("# 🚨")[0]
    assert brief.NOT_COLLECTED not in section and "사전규격 0건" in section
    assert brief.NOT_COLLECTED in body.split("# 기관 자체접수")[1].split("# 나라장터 후보")[0]
    assert brief.SOURCE_LINE in body


def test_제외는_사유와_함께_적는다(folder) -> None:
    body, _ = brief.build_markdown(listing(SAMPLE), now=NOW, previous=None)
    section = body.split("# ❌ 제외 · 비추천")[1].split("# 광주")[0]
    assert "지역 불가 — 시험" in section


def test_메모_속_항목은_사본으로_나간다(monkeypatch) -> None:
    # 정렬 · 순위가 메모 속 객체를 고치면 한 요청 안의 두 번째 목록이 첫 목록의 「순」을 덮어쓴다(엑셀 「브리핑」 시트 · 37차 마지막 검토)
    import asyncio

    from app.services import eligibility_engine, opportunity_service

    kept = item(9, source="bizinfo", group="일반 접수 중")
    kept.track_ranks["support"] = 3
    monkeypatch.setattr(opportunity_service, "_support_memo_key", lambda **_: ("r37-test",))
    monkeypatch.setattr(eligibility_engine, "company_facts_for", lambda _org: None)
    monkeypatch.setitem(opportunity_service._SUPPORT_MEMO, ("r37-test",), ([kept], "cached", None, True, None))
    got, *_rest = asyncio.run(opportunity_service._collect_support(organization_id="org-sample", profile=None, now=NOW, refresh=False, count=1))
    assert got[0] is not kept and got[0].id == kept.id
    got[0].source_rank = 99
    got[0].track_ranks["support"] = 1
    assert kept.source_rank == 9 and kept.track_ranks == {"support": 3}


@pytest.mark.parametrize(
    ("award_line", "expected"),
    [
        ("제한경쟁 · 다른 회사와 함께 참가할 수 있음(공동수급 허용)", "단독으로는 큼 · 파트너형"),
        ("제한경쟁 · 다른 회사와 함께 참가할 수 없음(공동수급 불허)", "단독으로는 큼 · 공동수급 불허"),
        (None, "단독으로는 큼 · 공동수급 확인 필요"),
    ],
)
def test_파트너형은_공동수급이_허용될_때만이다(award_line: str | None, expected: str) -> None:
    # 38차 D14 · DOCS-01 — 판단 낱말은 사업기회 행 꼬리표와 같은 함수(`practical.partner_tag`)의 값이다.
    from app.services import practical_priority as practical

    big = item(1, budget=500_000_000, fit_type="C", award_line=award_line)
    big.partner_tag = practical.partner_tag(big, 200_000_000)
    assert brief.verdict_of(big) == expected
    small = item(2, budget=100_000_000, fit_type="C", award_line=award_line)
    small.partner_tag = practical.partner_tag(small, 200_000_000)
    assert small.partner_tag is None and brief.verdict_of(small) == "적극도전"


def test_순위표는_최근_것만_남기고_깨진_것은_건너뛴다(folder) -> None:
    _, snapshot = brief.build_markdown(listing(SAMPLE), now=NOW, previous=None)
    for day in range(export_store.MAX_FILES + 3):  # 43차 Q27 — 하루 한 번만 남긴다(날마다 하나)
        brief.save_snapshot("org-sample", snapshot, now=NOW + timedelta(days=day))
    files = sorted(folder.glob("brief_*.json"))
    assert len(files) == export_store.MAX_FILES
    files[-1].write_text("{깨짐", encoding="utf-8")
    assert brief.latest_snapshot("org-sample") is not None


def test_엑셀은_시트_일곱이고_마지막이_브리핑이다() -> None:
    data = listing(SAMPLE)
    body = workbook.build(data, gaps=None, rules=None, now=NOW, brief=brief.sheet_rows(data, now=NOW))
    book = load_workbook(io.BytesIO(body))
    assert book.sheetnames == list(workbook.SHEET_NAMES)
    assert book.sheetnames[-1] == "브리핑"
    sheet = book["브리핑"]
    assert tuple(cell.value for cell in sheet[1]) == brief.SHEET_COLUMNS
    titles = [row[3] for row in sheet.iter_rows(min_row=2, values_only=True)]
    assert titles[:2] == ["시험 사업 1", "시험 사업 2"]  # 매출 먼저 · 회사 방식 순서
    assert any(str(row[0]).startswith(brief.SOURCE_LINE) for row in sheet.iter_rows(min_row=2, values_only=True))
