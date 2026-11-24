"""HWPX 서식 템플릿 PoC 테스트.

- 내장 서식으로 만든 HWPX가 ZIP·필수 멤버·XML 검증을 통과하고, 텍스트를 다시 뽑으면 넣은 값이 나온다.
- 자리표시자가 있는 (테스트에서 생성한) 서식의 {{key}} 치환과 미치환 보고.
- 한컴오피스에서 열리는지는 여기서 검증하지 않는다 (검증 불가 항목으로 보고서에 남긴다).
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.company import CompanyProfile
from app.schemas.procurement import ProcurementNotice
from app.schemas.requirement import PageInfo, Requirement, RfpParseResult
from app.services import document_extractor, hwpx_template_service as hts

client = TestClient(app)


@pytest.fixture(autouse=True)
def export_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "exports"
    monkeypatch.setattr(hts, "EXPORT_DIR", path)
    monkeypatch.setattr(hts, "TEMPLATE_DIR", tmp_path / "templates")
    monkeypatch.setattr(hts, "REGISTRY_FILE", tmp_path / "templates" / "registry.json")
    return path


PROFILE = CompanyProfile(name="주식회사 샘플에듀", address="광주광역시 북구 가상로 77", phone="062-000-0000", business_domains=["생성형 AI 교육"], preferred_regions=["광주광역시"])
NOTICE = ProcurementNotice(id="g2b-T-000", notice_no="R26BK00000001", title="생성형 AI 활용 교육 용역", agency="가천대학교", published_at=datetime(2026, 9, 1, tzinfo=timezone.utc))


def parse_result() -> RfpParseResult:
    req = Requirement(
        id="g2b-T-000:REQ-001",
        procurement_id="g2b-T-000",
        requirement_id="REQ-001",
        category="과업내용",
        requirement_type="mandatory",
        title="교육과정 기획",
        content="주말을 이용한 40시간 내외의 교육 과정 기획",
        page=2,
        source_text="◦ 주말을 이용한 40시간 내외의 교육 과정 기획",
        item_type="TASK",
        display_code="TSK-001",
    )
    return RfpParseResult(procurement_id="g2b-T-000", source="g2b_attachment", document="제안요청서.hwp", page_count=3, pages=[PageInfo(page=1, char_count=10)], empty_pages=[], count=1, requirements=[req], generated_at=datetime.now(timezone.utc))


def test_builtin_templates_listed_as_beta() -> None:
    templates = hts.list_templates()
    assert {t.id for t in templates} >= {"bid_application", "company_overview", "performance_table", "staffing_table", "requirement_matrix"}
    assert all(t.status == "beta" for t in templates)


def test_render_bid_application_validates_and_reextracts(export_dir: Path) -> None:
    result = hts.render("bid_application", "g2b-T-000", profile=PROFILE, notice=NOTICE, parse_result=None, manual={"representative": "홍길동"})
    assert result.status == "beta"
    assert result.validation.zip_ok and result.validation.required_members_ok and result.validation.xml_ok and result.validation.mimetype_ok
    assert result.verification.fields_checked >= 5
    assert result.verification.missing_fields == []
    assert result.verified is True
    assert result.values["corporate_number"] == ""  # 없는 값은 지어내지 않는다
    path = export_dir / "g2b-T-000" / "bid_application.hwpx"
    assert path.exists() and (export_dir / "g2b-T-000" / "bid_application.report.json").exists()
    assert document_extractor.detect_format(path) == "hwpx"
    text = "\n".join(p.text for p in document_extractor.extract_hwpx(path))
    assert "주식회사 샘플에듀" in text and "R26BK00000001" in text and "홍길동" in text
    with zipfile.ZipFile(path) as zf:
        first = zf.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED


def test_render_requirement_matrix_uses_parsed_items() -> None:
    result = hts.render("requirement_matrix", "g2b-T-000", profile=PROFILE, notice=NOTICE, parse_result=parse_result())
    path = hts.export_path("g2b-T-000", result.file_name)
    text = "\n".join(p.text for p in document_extractor.extract_hwpx(path))
    assert "TSK-001" in text and "40시간" in text
    with pytest.raises(hts.TemplateRenderError):
        hts.render("requirement_matrix", "g2b-T-000", profile=PROFILE, notice=NOTICE, parse_result=None)


def test_missing_required_value_is_error() -> None:
    with pytest.raises(hts.TemplateRenderError):
        hts.render("bid_application", "g2b-T-000", profile=PROFILE, notice=None, parse_result=None)


def test_placeholder_replacement_reports_unresolved() -> None:
    doc = hts._Doc(title="{{title}}", paragraphs=["상호: {{company_name}}", "대표자: {{representative}}"])
    template = hts.build_minimal_hwpx(doc)
    rendered, unresolved = hts.replace_placeholders(template, {"title": "입찰참가신청서", "company_name": "샘플에듀 <합성>"})
    assert unresolved == ["representative"]
    report = hts.validate_hwpx(rendered)
    assert report.zip_ok and report.xml_ok
    with zipfile.ZipFile(io.BytesIO(rendered)) as zf:
        section = zf.read("Contents/section0.xml").decode("utf-8")
    assert "샘플에듀 &lt;합성&gt;" in section and "{{representative}}" in section


def test_validate_rejects_garbage() -> None:
    report = hts.validate_hwpx(b"not a zip")
    assert report.zip_ok is False and report.required_members_ok is False


def test_templates_api_render_for_fixture(tmp_path: Path) -> None:
    client.post("/api/rfp/parse", json={"procurement_id": "synthetic-rfp-0001"})
    listing = client.get("/api/templates").json()
    assert listing["status"] == "beta" and listing["count"] >= 5

    response = client.post("/api/templates/render", json={"template_id": "requirement_matrix", "procurement_id": "synthetic-rfp-0001"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "beta" and body["sha256"]
    download = client.get(body["download_path"])
    assert download.status_code == 200
    assert download.content[:2] == b"PK"
    assert client.get("/api/templates/requirement_matrix/report/synthetic-rfp-0001").status_code == 200
    assert client.post("/api/templates/render", json={"template_id": "nope", "procurement_id": "synthetic-rfp-0001"}).status_code == 404
    assert client.get("/api/exports/synthetic-rfp-0001/../x.hwpx").status_code in (404, 422)


def test_서식_안내문에_영어_머리와_파일_경로가_없다() -> None:
    """DTL-23 — 안내문이 「Beta ·」로 시작하고 「(data/company/performance_ledger.json)」가 화면에 나왔다."""
    for template in hts.BUILTIN_TEMPLATES.values():
        assert "beta" not in template.note.lower() and "data/" not in template.note and ".json" not in template.note, template.id
