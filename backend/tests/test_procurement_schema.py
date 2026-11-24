"""ProcurementNotice 스키마 계약 테스트.

합성 공고 더미(sample_procurement.json)는 실데이터 전환과 함께 삭제했다.
스키마 검증은 저장해 둔 **실제 나라장터 응답**으로 한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.procurement import ProcurementNotice
from app.services import g2b_mapper


def test_real_api_items_validate_against_schema(raw_items: list[dict[str, Any]]) -> None:
    notices = [ProcurementNotice.model_validate(n.model_dump()) for n in g2b_mapper.map_notices(raw_items)]

    assert len(notices) >= 1
    for notice in notices:
        assert notice.notice_no
        assert notice.title
        assert isinstance(notice.published_at, datetime)
        assert notice.raw_data["source"] == "g2b"


def test_notice_is_json_serialisable(raw_items: list[dict[str, Any]]) -> None:
    notice = g2b_mapper.map_notices(raw_items)[0]
    payload = notice.model_dump(mode="json")

    assert isinstance(payload["published_at"], str)
    assert ProcurementNotice.model_validate(payload).id == notice.id


def test_optional_fields_default_to_none_and_empty_raw_data() -> None:
    notice = ProcurementNotice(
        id="g2b-X-000",
        notice_no="X-000",
        title="제목",
        agency="기관",
        published_at=datetime(2026, 9, 3),
    )
    assert notice.deadline_at is None
    assert notice.budget is None
    assert notice.region is None
    assert notice.source_url is None
    assert notice.raw_data == {}


def test_schema_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        ProcurementNotice.model_validate({"id": "x", "title": "no notice_no"})
