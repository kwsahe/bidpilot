"""기업마당 지원사업 · 발주기관 인사이트 · 공고 변경 감지 · 정정/Gold 테스트 (네트워크 없음)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import storage
from app.core.config import get_settings
from app.main import app
from app.schemas.procurement import ProcurementNotice
from app.services import (
    agency_insight_service,
    bizinfo_client,
    bizinfo_service,
    correction_service,
    notice_version_service as nvs,
    procurement_service,
    rfp_parser,
)

client = TestClient(app)
FIXTURE_ID = "synthetic-rfp-0001"


# --------------------------------------------------------------------------
# 기업마당
# --------------------------------------------------------------------------


def test_bizinfo_mapper_follows_documented_fields() -> None:
    program = bizinfo_service.map_program(
        {
            "pblancId": "P1",
            "pblancNm": "생성형 AI 교육 바우처",
            "jrsdInsttNm": "광주광역시",
            "reqstBeginEndDe": "20260901 ~ 20260930",
            "hashtags": "AI,교육",
            "trgetNm": "중소기업",
            "creatPnttm": "2026-08-25 09:00:00",
        }
    )
    assert program is not None
    assert program.id == "bizinfo-P1"
    assert program.apply_start == date(2026, 9, 1) and program.apply_end == date(2026, 9, 30)
    assert program.hashtags == ["AI", "교육"]
    assert program.created_at is not None and program.created_at.tzinfo is not None
    assert bizinfo_service.map_program({"pblancNm": "id 없음"}) is None


def test_support_fit_is_rule_based_and_separate_from_recommendation() -> None:
    program = bizinfo_service.map_program(
        {"pblancId": "P2", "pblancNm": "광주 중소기업 생성형 AI 교육 바우처", "jrsdInsttNm": "광주광역시", "reqstBeginEndDe": "20260901 ~ 20261231", "trgetNm": "중소기업", "hashtags": "AI,교육"}
    )
    fit = bizinfo_service.support_fit(program, today=date(2026, 9, 7))
    assert fit.method == "keyword_rule"
    assert fit.label == "적합"
    assert {c.key for c in fit.components} == {"domain", "target", "region", "period"}
    assert "추천등급" in fit.note

    expired = bizinfo_service.map_program({"pblancId": "P3", "pblancNm": "부산 물류 장비 지원", "jrsdInsttNm": "부산광역시", "reqstBeginEndDe": "20260101 ~ 20260131"})
    assert bizinfo_service.support_fit(expired, today=date(2026, 9, 7)).label == "낮음"


@pytest.mark.anyio
async def test_list_programs_falls_back_to_sample_without_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bizinfo_service, "CACHE_FILE", tmp_path / "bizinfo_cache.json")
    monkeypatch.setattr(bizinfo_client, "is_configured", lambda: False)
    listing = await bizinfo_service.list_programs()
    assert listing.source == "sample"
    assert listing.bizinfo_api_configured is False
    # field_mapping_verified 는 "필드 매핑을 실응답으로 확인했는가"이지 "이 데이터가 실제인가"가 아니다.
    # 실응답 확인이 끝났으므로 합성 샘플로 떨어져도 True 다 — 데이터가 합성이라는 사실은 source/error 가 말한다.
    assert listing.field_mapping_verified is True
    assert listing.count == 5
    assert all(view.kind == "support" for view in listing.items)
    assert listing.error and "가상 예시 목록" in listing.error


def test_support_programs_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bizinfo_service, "CACHE_FILE", tmp_path / "bizinfo_cache.json")
    monkeypatch.setattr(bizinfo_client, "is_configured", lambda: False)
    response = client.get("/api/support-programs")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "sample"
    assert body["items"][0]["support_fit"]["method"] == "keyword_rule"


def test_business_opportunities_keeps_kinds_apart(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bizinfo_service, "CACHE_FILE", tmp_path / "bizinfo_cache.json")
    monkeypatch.setattr(bizinfo_client, "is_configured", lambda: False)

    async def no_procurements(**_kwargs):
        raise procurement_service.NoNoticeDataError("테스트: 나라장터 없음")

    monkeypatch.setattr(procurement_service, "list_ai_candidates", no_procurements)
    # 마감 사업까지 포함해 조회한다 (오늘 날짜에 따라 건수가 흔들리지 않게).
    # 「불가」도 함께 받는다 — 여기서 재는 것은 «두 출처가 섞이지 않는가»이고,
    # 자격으로 거르면 셀 것이 사라진다 (0921 §4-C-2).
    response = client.get(
        "/api/business-opportunities", params={"include_closed": True, "include_blocked": True}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["organization_id"] == get_settings().default_organization_id
    assert body["source_status"]["bizinfo"] == "sample"
    assert body["source_errors"]["g2b"] and "나라장터" in body["source_errors"]["g2b"]
    assert body["g2b_count"] == 0 and body["bizinfo_count"] == 5
    for item in body["items"]:
        assert item["source_type"] == "bizinfo" and item["opportunity_type"] == "support_program"
        # 원본 점수는 섞이지 않는다 — 지원사업에는 지원 적합도만 붙고 조달 추천등급은 오지 않는다.
        assert item["source_specific_score"]["kind"] == "support_fit"
        assert "grade" not in item["source_specific_score"]
        assert item["next_route"]["kind"] == "support_application"
        # 지원 규모는 목록 API 에 없다 — 0원으로 표시하지 않는다.
        assert item["budget"] is None


# --------------------------------------------------------------------------
# 발주기관 인사이트
# --------------------------------------------------------------------------


def _notice(nid: str, agency: str, title: str, budget: int | None = None) -> ProcurementNotice:
    return ProcurementNotice(
        id=nid,
        notice_no=nid,
        title=title,
        agency=agency,
        published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        deadline_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
        budget=budget,
        region="광주광역시",
        raw_data={"attachments": [{"name": "제안요청서.hwp", "url": "https://www.g2b.go.kr/x"}]},
    )


def test_agency_insight_computed_from_cached_notices() -> None:
    from app.services.opportunity_filter import classify

    notices = [
        _notice("g2b-A-000", "가천대학교", "생성형 AI 활용 교육 운영", 50_000_000),
        _notice("g2b-B-000", "가천대학교", "AI 부트캠프 강사 지원", None),
        _notice("g2b-C-000", "광주광역시", "디지털 전환 컨설팅", 30_000_000),
    ]
    views = [procurement_service.NoticeView(notice=n, match=classify(n)) for n in notices]
    result = procurement_service.ProcurementResult(source="cached", notices=views, fetched_at=datetime.now(timezone.utc), total_fetched=3)
    listing = agency_insight_service.build_from_result(result, window_days=14)
    assert listing.agencies[0].agency == "가천대학교"
    assert listing.agencies[0].notice_count == 2
    assert listing.agencies[0].budget_known_count == 1 and listing.agencies[0].budget_avg == 50_000_000
    assert "AI" in listing.agencies[0].top_keywords
    assert "관측치" in listing.note


# --------------------------------------------------------------------------
# 공고 변경 감지
# --------------------------------------------------------------------------


def test_notice_versions_only_grow_on_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nvs, "VERSION_DIR", tmp_path / "versions")
    first = _notice("g2b-V-000", "가천대학교", "생성형 AI 교육", 50_000_000)
    nvs.record(first)
    nvs.record(first)
    assert len(nvs.load_history("g2b-V-000").versions) == 1

    changed = first.model_copy(update={"deadline_at": datetime(2026, 10, 5, tzinfo=timezone.utc), "budget": 55_000_000})
    history = nvs.record(changed)
    assert len(history.versions) == 2
    assert len(history.changes) == 1
    fields = {c.field for c in history.changes[0].changes}
    assert fields == {"deadline_at", "budget"}
    assert history.changes[0].changes[0].label in ("마감일", "예산")


def test_save_cache_records_versions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.opportunity_filter import classify

    monkeypatch.setattr(nvs, "VERSION_DIR", tmp_path / "versions")
    notice = _notice("g2b-W-000", "광주광역시", "AI 교육")
    procurement_service.save_cache([procurement_service.NoticeView(notice=notice, match=classify(notice))], 1, datetime.now(timezone.utc))
    assert len(nvs.load_history("g2b-W-000").versions) == 1
    response = client.get("/api/procurements/g2b-W-000/changes")
    assert response.status_code == 200 and response.json()["version_count"] == 1


# --------------------------------------------------------------------------
# 정정 기록 · Gold 내보내기
# --------------------------------------------------------------------------


@pytest.fixture()
def corrections_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "corrections"
    monkeypatch.setattr(correction_service, "CORRECTION_DIR", path)
    client.post("/api/rfp/parse", json={"procurement_id": FIXTURE_ID})
    return path


def test_correction_overlays_on_read_and_keeps_history(corrections_dir: Path) -> None:
    before = rfp_parser.load_generated(FIXTURE_ID)
    target = before.requirements[0]
    assert target.extraction_method == "RULE"

    response = client.put(
        f"/api/rfp/{FIXTURE_ID}/items/{target.requirement_id}",
        json={"reviewer": "김담당", "review_status": "corrected", "item_type": "SCHEDULE", "page": target.page, "note": "일정 항목으로 정정"},
    )
    assert response.status_code == 200, response.text
    item = response.json()["item"]
    assert item["item_type"] == "SCHEDULE"
    assert item["display_code"].startswith("SCH-")
    assert item["extraction_method"] == "HUMAN" and item["review_status"] == "corrected"
    assert item["requirement_id"] == target.requirement_id  # 저장 id는 그대로

    again = rfp_parser.load_generated(FIXTURE_ID)
    assert next(r for r in again.requirements if r.requirement_id == target.requirement_id).item_type == "SCHEDULE"
    # 원본 파일은 바뀌지 않았다.
    raw = storage.read_json(rfp_parser.generated_path(FIXTURE_ID))
    assert next(r for r in raw["requirements"] if r["requirement_id"] == target.requirement_id).get("extraction_method") == "RULE"

    history = client.get(f"/api/rfp/{FIXTURE_ID}/corrections").json()
    assert len(history["corrections"]) == 1 and history["corrections"][0]["reviewer"] == "김담당"


def test_gold_export_requires_confirmed_items(corrections_dir: Path) -> None:
    assert client.get(f"/api/exports/gold/{FIXTURE_ID}").status_code == 422
    parsed = rfp_parser.load_generated(FIXTURE_ID)
    first, second = parsed.requirements[0], parsed.requirements[1]
    client.put(f"/api/rfp/{FIXTURE_ID}/items/{first.requirement_id}", json={"reviewer": "김담당", "review_status": "confirmed"})
    client.put(f"/api/rfp/{FIXTURE_ID}/items/{second.requirement_id}", json={"reviewer": "김담당", "review_status": "rejected"})
    gold = client.get(f"/api/exports/gold/{FIXTURE_ID}")
    assert gold.status_code == 200
    body = gold.json()
    assert body["confirmed_count"] == 1 and body["rejected_count"] == 1
    assert body["requirements"][0]["requirement_id"] == first.requirement_id
    assert body["requirements"][0]["source_text"] == first.source_text
    assert "평가 전용" in body["_note"]
    # 45차 M20 — 화면 내려받기는 한국어 머리 표 파일(엑셀이 바로 여는 BOM)
    table = client.get(f"/api/exports/gold/{FIXTURE_ID}?format=csv")
    assert table.status_code == 200 and table.headers["content-type"].startswith("text/csv")
    text = table.content.decode("utf-8")
    assert text.startswith("\ufeff항목 코드,유형,필수 여부,내용,쪽,원문,담당자 확인,확인한 사람")
    assert "확정(그대로 맞음)" in text and "김담당" in text


def test_correction_unknown_item_is_404(corrections_dir: Path) -> None:
    assert client.put(f"/api/rfp/{FIXTURE_ID}/items/REQ-999", json={"reviewer": "k", "review_status": "confirmed"}).status_code == 404
