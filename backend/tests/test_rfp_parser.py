import pytest
from pydantic import ValidationError

from app.schemas.requirement import Requirement
from app.services import rfp_parser

FIXTURE_ID = "synthetic-rfp-0001"


def test_fixture_pdf_extracts_six_pages() -> None:
    fixture = rfp_parser.get_fixture(FIXTURE_ID)
    pages = rfp_parser.extract_pages(fixture.path)
    assert len(pages) == 6
    assert all(page.strip() for page in pages), "빈 페이지가 있으면 안 된다"


def test_parse_fixture_extracts_grounded_requirements() -> None:
    result = rfp_parser.parse_fixture(FIXTURE_ID)

    assert result.page_count == 6
    assert result.empty_pages == []
    assert result.count >= 10
    assert result.count == len(result.requirements)

    ids = [r.requirement_id for r in result.requirements]
    assert ids == [f"REQ-{i:03d}" for i in range(1, len(ids) + 1)]

    for req in result.requirements:
        assert req.page is not None and 1 <= req.page <= 6
        assert req.source_text.strip()
        assert req.content.strip()
        assert req.status in {"matched", "partial", "unmatched", "check"}
        assert req.requirement_type in {"mandatory", "optional"}
        assert req.extraction_method == "RULE"


def test_parse_fixture_keeps_pages_in_reading_order() -> None:
    result = rfp_parser.parse_fixture(FIXTURE_ID)
    pages = [r.page for r in result.requirements]
    assert pages == sorted(pages)


def test_parse_fixture_marks_ambiguous_qualification_as_check() -> None:
    """모호한 자격·유사실적 조건은 자동 충족 처리하지 않고 check로 둔다."""
    result = rfp_parser.parse_fixture(FIXTURE_ID)
    by_title = {r.title: r for r in result.requirements}

    # PDF p.4: 총괄책임자 경력·유사사업 조건 → 사람 검토, 기본자격(사업자등록) → 명확한 조건
    assert by_title["총괄책임자"].status == "check"
    assert by_title["기본자격"].status == "unmatched"
    assert not any(r.status == "matched" for r in result.requirements)


def test_ambiguous_status_rules_on_plain_text() -> None:
    """태그와 무관하게 자격·인력 범주의 경력/유사 조건은 check, 그 외는 unmatched."""
    pages = [
        "책임자 [인력] 책임자는 관련 분야 경력 5년 이상이어야 한다.\n"
        "실적 [자격] 최근 3년 이내 유사사업 수행 실적이 있어야 한다.\n"
        "조건 [모호조건] 발주기관이 인정하는 수준이어야 한다.\n"
        "장소 [운영] 교육은 지정 교육장에서 운영해야 한다.\n"
    ]
    reqs = rfp_parser.extract_requirements("t", pages)
    assert {r.title: r.status for r in reqs} == {
        "책임자": "check",
        "실적": "check",
        "조건": "check",
        "장소": "unmatched",
    }


def test_bracketed_cross_reference_is_not_a_requirement_start() -> None:
    """'[별표 1]' 같은 참조 표기가 이어지는 줄에 있어도 문장을 쪼개지 않는다."""
    pages = [
        "파일형식 [제출] 계약상대자는 원본파일과 PDF 파일을 함께 제출하고, 파일명은\n"
        "붙임의 [별표 1] 명명규칙을 따라야 한다.\n"
    ]
    reqs = rfp_parser.extract_requirements("t", pages)
    assert len(reqs) == 1
    assert reqs[0].category == "제출"
    assert reqs[0].content == (
        "계약상대자는 원본파일과 PDF 파일을 함께 제출하고, 파일명은 붙임의 [별표 1] 명명규칙을 따라야 한다."
    )


def test_extract_requirements_from_plain_text_joins_wrapped_lines() -> None:
    pages = [
        "Page 1\n"
        "제목 [운영] 첫 줄은 여기서 끊기고\n"
        "다음 줄에서 끝나야 한다.\n"
        "설명문은 요구사항이 아니다.\n"
        "태그 없는 문장도 의무 표현이면 후보로 남겨야 한다.\n"
    ]
    reqs = rfp_parser.extract_requirements("test-id", pages)

    assert len(reqs) == 2
    first, second = reqs
    assert first.title == "제목"
    assert first.category == "운영"
    assert first.content == "첫 줄은 여기서 끊기고 다음 줄에서 끝나야 한다."
    assert first.source_text == "제목 [운영] 첫 줄은 여기서 끊기고\n다음 줄에서 끝나야 한다."
    assert first.page == 1
    assert first.status == "unmatched"
    assert second.status == "check"
    assert second.category == "기타"


def test_unknown_fixture_is_rejected() -> None:
    with pytest.raises(rfp_parser.RfpFixtureNotFoundError):
        rfp_parser.get_fixture("../../etc/passwd")


def test_requirement_schema_rejects_invalid_enums() -> None:
    base = {
        "id": "x:REQ-001",
        "procurement_id": "x",
        "requirement_id": "REQ-001",
        "category": "운영",
        "requirement_type": "mandatory",
        "title": "t",
        "content": "c",
        "page": 1,
        "source_text": "s",
    }
    with pytest.raises(ValidationError):
        Requirement.model_validate({**base, "status": "done"})
    with pytest.raises(ValidationError):
        Requirement.model_validate({**base, "requirement_type": "nice_to_have"})
    with pytest.raises(ValidationError):
        Requirement.model_validate({**base, "page": 0})


# ---------------------------------------------------------------------------
# 같은 결과면 파일을 다시 쓰지 않는다 (ISSUE-019 · TASK-018)
#
# 「다시 분석」은 거의 언제나 같은 결과를 낸다. 그런데 매번 `generated_at` 만 바뀐 파일을
# 덮어쓰고 이전 판을 versions/ 에 쌓았다. 추적 중인 파일이라 git 이 매번 변경으로 잡히고,
# 판 목록에는 내용이 같은 판이 늘어나 「무엇이 달라졌는지」를 볼 수 없게 된다.
# ---------------------------------------------------------------------------


def test_같은_결과면_파일과_판을_늘리지_않는다(tmp_path, monkeypatch) -> None:
    from datetime import datetime, timezone

    monkeypatch.setattr(rfp_parser, "GENERATED_DIR", tmp_path)

    def _result() -> rfp_parser.RfpParseResult:
        return rfp_parser.RfpParseResult(
            procurement_id="synthetic-rfp-0001",
            source="fixture",
            document="sample.pdf",
            pages=[],
            empty_pages=[],
            page_count=1,
            count=1,
            candidate_count=1,
            truncated=False,
            requirements=[
                Requirement(
                    id="synthetic-rfp-0001-REQ-001",
                    procurement_id="synthetic-rfp-0001",
                    requirement_id="REQ-001",
                    title="교육 운영 횟수",
                    category="과업내용",
                    requirement_type="mandatory",
                    content="교육은 총 20회 이상 실시한다.",
                    source_text="교육은 총 20회 이상 실시한다.",
                    page=17,
                )
            ],
            generated_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
        )

    rfp_parser.store_result(_result())
    path = rfp_parser.generated_path("synthetic-rfp-0001")
    first = path.read_text(encoding="utf-8")
    versions_after_first = len(rfp_parser.list_versions("synthetic-rfp-0001"))

    # 같은 내용을 «시각만 달리해» 다시 저장한다 — 실제 재분석이 하는 일이다.
    again = _result()
    again.generated_at = datetime(2026, 9, 17, tzinfo=timezone.utc)
    rfp_parser.store_result(again)

    assert path.read_text(encoding="utf-8") == first, "내용이 같은데 파일을 다시 썼다"
    assert len(rfp_parser.list_versions("synthetic-rfp-0001")) == versions_after_first

    # 내용이 실제로 바뀌면 그때는 쓴다.
    changed = _result()
    changed.requirements[0].content = "교육은 총 30회 이상 실시한다."
    rfp_parser.store_result(changed)
    assert "30회" in path.read_text(encoding="utf-8")
