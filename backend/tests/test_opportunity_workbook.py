"""사업기회 **엑셀 출력** (0924.md §4-C · 담당자 지시 2).

생성한 파일을 **openpyxl 로 다시 열어** 잰다 — 코드가 만들었다는 것으로는 부족하다.
시트 일곱 · 머리글 · 행 수 · 하이퍼링크 · 날짜 셀이 실제로 그 모양인지 확인한다.

여기서 지키는 약속 둘.

1. **파일이 화면과 같은 말을 한다.** 판정은 워크북이 새로 만들지 않고 목록이 준 값을 쓴다.
2. **「이번 주 할 일」 시트는 화면과 같은 규칙**이다 — 입찰 4 + 지원사업 4 (0924 §4-B-3).
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
from app.services import opportunity_workbook as workbook

NOW = datetime(2026, 9, 18, 3, 0, tzinfo=timezone.utc)


def opportunity(
    index: int,
    *,
    source: str = "bizinfo",
    days: int | None = 3,
    gate: str = "PASS",
    participation: str | None = None,
    tracks: list[str] | None = None,
    category: str = "기술",
) -> UnifiedOpportunity:
    prefix = "g2b-" if source == "g2b" else "bizinfo-"
    return UnifiedOpportunity(
        id=f"{prefix}TEST{index:03d}",
        source_type=source,  # type: ignore[arg-type]
        opportunity_type="procurement" if source == "g2b" else "support_program",
        title=f"시험 사업 {index}",
        agency="시험 기관",
        deadline=None if days is None else NOW + timedelta(days=days),
        detail_url=f"https://example.invalid/{index}",
        organization_id="org-sample",
        company_priority_score=70,
        priority_rank=index,
        source_rank=index,
        priority_label="우선 검토",
        eligibility_gate=gate,  # type: ignore[arg-type]
        gate_reason="시험 사유",
        confidence="medium",
        score_components=[],
        next_route=NextRoute(kind="support_application", path="/", label="열기"),
        source="cached",
        category=category,
        work_tracks=tracks or ([] if source == "bizinfo" else ["development"]),  # type: ignore[arg-type]
        participation=participation,
        company_meaning="직접 신청 · 무료 · 자부담 없음 · 9-30 마감",
        document_read=True,
        clause_quotes=["지원대상 : 광주광역시 본사소재 기업"],
    )


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
        fetched_at=NOW,
        summary=OpportunitySummary(
            open_total=len(items),
            open_g2b=0,
            open_bizinfo=len(items),
            priority=0,
            closed=0,
            closed_pinned=0,
            days=30,
            new_days=3,
        ),
        sort="priority",
        field_mapping_verified=True,
        note="시험",
        items=items,
    )


def open_book(body: bytes):
    return load_workbook(io.BytesIO(body))


def test_시트가_일곱이고_이름이_정해져_있다() -> None:
    book = open_book(workbook.build(listing([opportunity(1)]), now=NOW))
    assert book.sheetnames == list(workbook.SHEET_NAMES)


def test_기업마당_시트는_기준_답안과_같은_머리글이다() -> None:
    """검수자가 손으로 만든 `bizinfo_candidates.csv` 와 같은 이름·같은 순서다."""
    book = open_book(workbook.build(listing([opportunity(1)]), now=NOW))
    header = [cell.value for cell in book["기업마당"][1]]
    assert tuple(header) == workbook.BIZINFO_COLUMNS


def test_출처마다_자기_시트에만_들어간다() -> None:
    items = [opportunity(1, source="g2b"), opportunity(2), opportunity(3)]
    book = open_book(workbook.build(listing(items), now=NOW))
    assert book["사업기회"].max_row - 1 == 3
    assert book["나라장터"].max_row - 1 == 1
    assert book["기업마당"].max_row - 1 == 2


def test_링크는_하이퍼링크고_마감은_날짜_셀이다() -> None:
    """글자로 적으면 엑셀에서 누르지도 정렬하지도 못한다."""
    book = open_book(workbook.build(listing([opportunity(1)]), now=NOW))
    sheet = book["기업마당"]
    link = sheet.cell(row=2, column=len(workbook.BIZINFO_COLUMNS))
    assert link.hyperlink is not None
    assert link.hyperlink.target == "https://example.invalid/1"
    deadline = sheet.cell(row=2, column=workbook.BIZINFO_COLUMNS.index("실제 마감") + 1)
    assert isinstance(deadline.value, datetime)


def test_머리글이_고정되고_열_너비가_잡힌다() -> None:
    book = open_book(workbook.build(listing([opportunity(1)]), now=NOW))
    for name in workbook.SHEET_NAMES:
        assert book[name].freeze_panes == "A2", name
    assert book["기업마당"].column_dimensions["D"].width >= workbook.MIN_COLUMN_WIDTH


def test_이번_주_할_일은_입찰_넷과_지원사업_넷이다() -> None:
    """마감 순으로만 채우면 한쪽이 여덟 자리를 다 가져간다 (0924 §4-B-3)."""
    items = [opportunity(i, source="g2b", days=i) for i in range(1, 8)]
    items += [opportunity(100 + i, days=i) for i in range(1, 8)]
    picked = workbook.this_week(items, now=NOW)
    assert len(picked) == workbook.PER_SOURCE_ROWS * 2
    assert sum(1 for i in picked if i.source_type == "g2b") == workbook.PER_SOURCE_ROWS
    assert sum(1 for i in picked if i.source_type == "bizinfo") == workbook.PER_SOURCE_ROWS


def test_한쪽이_모자라면_남은_자리를_다른_쪽이_쓴다() -> None:
    """빈칸을 만들지 않는다."""
    items = [opportunity(i, source="g2b", days=i) for i in range(1, 8)]
    items += [opportunity(101, days=2)]
    picked = workbook.this_week(items, now=NOW)
    assert len(picked) == workbook.PER_SOURCE_ROWS * 2
    assert sum(1 for i in picked if i.source_type == "bizinfo") == 1


def test_마감_지난_것과_불가는_이번_주에_없다() -> None:
    items = [
        opportunity(1, source="g2b", days=-1),
        opportunity(2, source="g2b", gate="FAIL"),
        opportunity(3, source="g2b", days=30),
        opportunity(4, source="g2b", days=2),
    ]
    picked = workbook.this_week(items, now=NOW)
    assert [i.id for i in picked] == ["g2b-TEST004"]


def test_간접_참여는_판정_칸에_그대로_적는다() -> None:
    """「불가」로 닫지 않는다 — 들어가는 길이 파일에도 남아야 한다 (0924 §4-A-4)."""
    book = open_book(
        workbook.build(listing([opportunity(1, gate="CHECK", participation="간접(공급기업)")]), now=NOW)
    )
    sheet = book["기업마당"]
    verdict = sheet.cell(row=2, column=workbook.BIZINFO_COLUMNS.index("판정") + 1).value
    group = sheet.cell(row=2, column=1).value
    assert verdict == "간접(공급기업)"
    assert group == "간접"  # 43차 NUM-10 — 유형 A1~D 와 겹치는 글자 접두어 없음


def test_근거_칸에_공고문_원문이_들어간다() -> None:
    book = open_book(workbook.build(listing([opportunity(1)]), now=NOW))
    quote = book["기업마당"].cell(row=2, column=workbook.BIZINFO_COLUMNS.index("근거(공고문)") + 1).value
    assert quote == "지원대상 : 광주광역시 본사소재 기업"


def test_판정_칸에_영문_값이_없다() -> None:
    """화면과 같은 말을 쓴다 (규칙 11)."""
    items = [opportunity(1), opportunity(2, gate="CHECK"), opportunity(3, gate="FAIL")]
    book = open_book(workbook.build(listing(items), now=NOW))
    column = workbook.BIZINFO_COLUMNS.index("판정") + 1
    values = [book["기업마당"].cell(row=r, column=column).value for r in (2, 3, 4)]
    assert values == ["가능", "확인 필요", "불가"]


@pytest.mark.parametrize(
    "name, expected",
    [("주식회사 샘플에듀", "BidPilot_사업기회_주식회사샘플에듀_20260918.xlsx"), ("", "BidPilot_사업기회_회사_20260918.xlsx")],
)
def test_파일_이름_형식(name: str, expected: str) -> None:
    assert workbook.filename(name, today=NOW.date()) == expected


def test_갭_리포트_시트는_주어진_값을_그대로_적는다() -> None:
    """워크북이 갭을 다시 세지 않는다 — 두 곳에서 세면 화면과 파일이 갈린다."""
    gaps = {"gaps": [{"condition": "1468 등록 시 가능", "label": "업종·면허", "blocked": 3, "pending": 25,
                      "blocked_examples": ["g2b-A"], "pending_examples": []}]}
    book = open_book(workbook.build(listing([opportunity(1)]), gaps=gaps, now=NOW))
    row = [cell.value for cell in book["갭 리포트"][2]]
    assert row[:4] == ["1468 등록 시 가능", "업종·면허", 3, 25]


def test_엑셀이_받지_않는_제어_문자가_섞여도_워크북을_만든다() -> None:
    """33차 최신화 뒤 실측 — 기업마당 요약에 세로 탭(\x0b)이 섞여 워크북 전체가 500 이었다."""
    item = opportunity(1).model_copy(update={"company_meaning": "\x0b\x0b구독료 전액 지원", "title": "시험\x01 사업"})
    book = open_book(workbook.build(listing([item]), now=NOW))
    sheet = book["기업마당"]
    values = [cell.value for cell in sheet[2]]
    assert "시험 사업" in values
    assert not any(isinstance(v, str) and ("\x0b" in v or "\x01" in v) for v in values)
