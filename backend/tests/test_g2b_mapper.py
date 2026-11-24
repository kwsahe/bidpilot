"""g2b_mapper: 나라장터 실제 응답 item -> ProcurementNotice 매핑 테스트.

입력은 저장해 둔 **실제 API 응답**(data/public/sample_procurements/g2b_raw_response_sample.json)이다.
필드명을 추정하지 않고 실제 응답에 있는 이름만 검증한다 (CLAUDE.md 25-4, 25-5).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import g2b_mapper
from app.services.g2b_mapper import KST

MINIMAL_ITEM = {
    "bidNtceNo": "R26BK09999999",
    "bidNtceOrd": "001",
    "bidNtceNm": "테스트 공고",
    "bidNtceDt": "2026-08-20 01:14:56",
    "ntceInsttNm": "테스트기관",
}


def test_maps_every_real_item_without_crashing(raw_items: list[dict[str, Any]]) -> None:
    notices = g2b_mapper.map_notices(raw_items)
    assert len(notices) == len(raw_items)
    for notice in notices:
        assert notice.id.startswith("g2b-")
        assert notice.title
        assert notice.agency
        assert notice.published_at is not None


def test_notice_no_is_bid_no_with_order(raw_items: list[dict[str, Any]]) -> None:
    item = raw_items[0]
    notice = g2b_mapper.map_notice(item)
    assert notice is not None
    assert notice.notice_no == f"{item['bidNtceNo']}-{item['bidNtceOrd']}"
    assert notice.id == f"g2b-{item['bidNtceNo']}-{item['bidNtceOrd']}"


def test_datetimes_are_parsed_as_kst(raw_items: list[dict[str, Any]]) -> None:
    notice = g2b_mapper.map_notice(raw_items[0])
    assert notice is not None
    assert notice.published_at.utcoffset() == timedelta(hours=9)
    assert notice.deadline_at is not None
    assert notice.deadline_at.utcoffset() == timedelta(hours=9)
    # 마감(또는 개찰)은 공고게시일 이후여야 한다.
    assert notice.deadline_at >= notice.published_at


def test_parse_datetime_formats() -> None:
    assert g2b_mapper.parse_datetime("2026-08-20 01:14:56") == datetime(
        2026, 8, 20, 1, 14, 56, tzinfo=KST
    )
    assert g2b_mapper.parse_datetime("2026-08-30 18:00") is not None
    assert g2b_mapper.parse_datetime("2026-08-30") is not None
    assert g2b_mapper.parse_datetime("") is None
    assert g2b_mapper.parse_datetime(None) is None
    assert g2b_mapper.parse_datetime("20260830") is None


def test_opening_datetime_is_not_the_deadline() -> None:
    """43차 H1 — 입찰 마감이 비면 마감은 None 이다. 개찰일시는 제출 마감이 아니라 `opening_at` 에만 둔다(옛 저장본도 `normalized`)."""
    item = {**MINIMAL_ITEM, "bidClseDt": "", "opengDt": "2026-08-31 11:00:00"}
    notice = g2b_mapper.map_notice(item)
    assert notice is not None
    assert notice.deadline_at is None
    assert notice.raw_data["opening_at"] == "2026-08-31 11:00:00"
    old = notice.model_copy(update={"deadline_at": g2b_mapper.parse_datetime("2026-08-31 11:00:00")})
    assert g2b_mapper.normalized(old).deadline_at is None
    kept = g2b_mapper.map_notice({**MINIMAL_ITEM, "bidClseDt": "2026-08-30 10:00:00", "opengDt": "2026-08-31 11:00:00"})
    assert kept is not None and g2b_mapper.normalized(kept).deadline_at == kept.deadline_at

    no_deadline = g2b_mapper.map_notice({**MINIMAL_ITEM, "bidClseDt": "", "opengDt": ""})
    assert no_deadline is not None
    assert no_deadline.deadline_at is None


def test_budget_comes_from_assigned_budget_amount(raw_items: list[dict[str, Any]]) -> None:
    item = next(i for i in raw_items if i.get("asignBdgtAmt"))
    notice = g2b_mapper.map_notice(item)
    assert notice is not None
    assert notice.budget == int(item["asignBdgtAmt"])


def test_parse_amount_treats_zero_and_blank_as_none() -> None:
    assert g2b_mapper.parse_amount("425000000") == 425000000
    assert g2b_mapper.parse_amount("425,000,000") == 425000000
    assert g2b_mapper.parse_amount("0") is None
    assert g2b_mapper.parse_amount("") is None
    assert g2b_mapper.parse_amount(None) is None


def test_budget_is_none_when_both_amount_fields_are_empty() -> None:
    notice = g2b_mapper.map_notice({**MINIMAL_ITEM, "asignBdgtAmt": "0", "presmptPrce": ""})
    assert notice is not None
    assert notice.budget is None


def test_attachments_are_extracted_with_names(raw_items: list[dict[str, Any]]) -> None:
    item = next(i for i in raw_items if i.get("ntceSpecDocUrl1"))
    notice = g2b_mapper.map_notice(item)
    assert notice is not None
    attachments = notice.raw_data["attachments"]

    expected = sum(
        1
        for index in range(1, g2b_mapper.ATTACHMENT_SLOTS + 1)
        if str(item.get(f"ntceSpecDocUrl{index}") or "").strip()
    )
    assert len(attachments) == expected >= 1
    for attachment in attachments:
        assert attachment["url"].startswith("http")
        assert attachment["name"]


def test_attachment_name_falls_back_when_file_name_missing() -> None:
    item = {**MINIMAL_ITEM, "ntceSpecDocUrl2": "https://www.g2b.go.kr/x", "ntceSpecFileNm2": ""}
    attachments = g2b_mapper.extract_attachments(item)
    assert attachments == [{"name": "첨부2", "url": "https://www.g2b.go.kr/x"}]


def test_items_missing_required_fields_are_skipped_not_raised() -> None:
    broken = [
        {**MINIMAL_ITEM, "bidNtceNo": ""},  # 공고번호 없음
        {**MINIMAL_ITEM, "bidNtceNm": "   "},  # 공고명 없음
        {**MINIMAL_ITEM, "bidNtceDt": "", "rgstDt": ""},  # 게시일 없음
        {},  # 완전히 빈 item
    ]
    for item in broken:
        assert g2b_mapper.map_notice(item) is None

    mixed = [*broken, MINIMAL_ITEM]
    assert len(g2b_mapper.map_notices(mixed)) == 1


def test_registration_datetime_is_used_when_notice_datetime_is_blank() -> None:
    item = {**MINIMAL_ITEM, "bidNtceDt": "", "rgstDt": "2026-08-19 09:00:00"}
    notice = g2b_mapper.map_notice(item)
    assert notice is not None
    assert notice.published_at.day == 19


def test_raw_data_keeps_original_item_and_source(raw_items: list[dict[str, Any]]) -> None:
    notice = g2b_mapper.map_notice(raw_items[0])
    assert notice is not None
    assert notice.raw_data["source"] == "g2b"
    assert notice.raw_data["operation"] == "getBidPblancListInfoServcPPSSrch"
    assert notice.raw_data["item"] == raw_items[0]


# ---------------------------------------------------------------------------
# 지역: 「판단기준 이름」을 「지역 이름」으로 읽던 오독
# ---------------------------------------------------------------------------
#
# 캐시된 실응답 76건에서 rgnLmtBidLocplcJdgmBssNm 값을 세어 보니 세 가지뿐이었다.
#   52건 '본사또는참여지사소재지' · 23건 '' · 1건 '본사소재지'
# 지역 이름은 한 건도 없었고, 대상 지역 필드(jntcontrctDutyRgnNm1)는 76건 전부 비어 있었다.
# 그런데 이 값이 region 으로 들어가 「회사 활동 지역과 다르다」는 이유로 참가자격이 FAIL 이
# 됐다. 대상 지역을 모르는데 참가 불가로 단정한 것이고, 들어갈 수 있는 공고를 버리는 판정이다.


def test_실응답에_들어오는_판단기준_값은_지역_이름이_아니다() -> None:
    for basis in ("본사또는참여지사소재지", "본사소재지"):
        assert g2b_mapper.contains_region_name(basis) is False
        assert g2b_mapper.region_name(basis) is None


def test_지역제한_판단기준은_region_으로_들어가지_않는다() -> None:
    notice = g2b_mapper.map_notice({**MINIMAL_ITEM, "rgnLmtBidLocplcJdgmBssNm": "본사또는참여지사소재지"})
    assert notice is not None
    assert notice.region is None  # 판단기준 이름은 지역이 아니다
    # 버리지는 않는다 — 판단기준이 붙어 있었다는 사실은 남겨야 CHECK 사유를 쓸 수 있다.
    assert notice.raw_data["region_limit_basis"] == "본사또는참여지사소재지"
    assert notice.raw_data["region_limit_area"] is None


def test_지역_이름이_실제로_적혀_있으면_지역으로_쓴다() -> None:
    notice = g2b_mapper.map_notice({**MINIMAL_ITEM, "rgnLmtBidLocplcJdgmBssNm": "광주광역시"})
    assert notice is not None
    assert notice.region == "광주광역시"
    assert notice.raw_data["region_limit_area"] == "광주광역시"


def test_지역의무공동도급_대상지역은_지역_이름이라_그대로_쓴다() -> None:
    notice = g2b_mapper.map_notice(
        {**MINIMAL_ITEM, "rgnLmtBidLocplcJdgmBssNm": "본사또는참여지사소재지", "jntcontrctDutyRgnNm1": "전라남도"}
    )
    assert notice is not None
    assert notice.region == "전라남도"


def test_판단기준은_저장해_둔_공고에서도_원본_item_으로_찾을_수_있다() -> None:
    """캐시로 되살린 공고에는 새로 넣은 편의 키가 없다 — 원본 item 을 먼저 봐야 한다."""
    cached_like = {"source": "g2b", "item": {"rgnLmtBidLocplcJdgmBssNm": "본사또는참여지사소재지"}}
    assert g2b_mapper.region_limit_basis(cached_like) == "본사또는참여지사소재지"
    assert g2b_mapper.region_limit_basis({"item": {}}) is None
    assert g2b_mapper.region_limit_basis({}) is None


def test_kst_is_utc_plus_nine() -> None:
    assert KST == timezone(timedelta(hours=9))
