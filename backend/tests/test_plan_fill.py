"""사업계획서 일반현황 자동 채움 — 회사자료 → 문서 칸 (29차 · prompt_19 §3-B).

- 회사 값이 있으면 문서 칸에 들어가고(출처 「회사자료」) **AI 에 보내는 본문에는 없다**.
- 회사자료에도 없는 칸만 「(담당자 입력)」 · 점검표는 「회사자료로 채움 n · 담당자 입력 남음 m」.
- AI 가 대표자 · 매출을 써도 지워지고, 칸은 회사 값으로 채워진다.
저장 경로는 conftest 가 tmp 로 돌린다.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import llm_client, plan_draft_service, plan_export_service, plan_fill_service, plan_form_service
from app.services.plan_draft_service import PlanSectionOut
from app.services.plan_form_service import HUMAN_INPUT
from tests.test_plan_draft import ai_on, form, requirements, run, select_task  # noqa: F401 — form · requirements 는 픽스처

client = TestClient(app)
ORG = "org-fill-test"
GENERAL = {
    "representative": "김가상", "business_number": "123-45-67890", "opened_on": "2016-03-02", "business_type": "서비스",
    "business_item": "교육 컨설팅", "revenue_by_year": [{"year": 2023, "value": 310000000}, {"year": 2024, "value": 420000000}],
    "employees_by_year": [{"year": 2024, "value": 12}], "staff": [{"role": "AI 교육 강사", "count": 4}, {"role": "개발", "count": 3}],
    "updated_by": "김담당",
}


@pytest.fixture(autouse=True)
def no_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "is_configured", lambda: False)


def make_org(general: dict | None = GENERAL) -> None:
    r = client.post("/api/organizations", json={"organization_id": ORG, "display_name": "가상교육", "data_class": "synthetic", "created_by": "김담당"})
    assert r.status_code == 201, r.text
    saved = client.put(f"/api/organizations/{ORG}/profile", json={
        "name": "주식회사 가상교육", "business_domains": ["AI 교육"], "address": "광주광역시 가상로 1", "phone": "062-000-0000",
        "data_class": "synthetic", "updated_by": "김담당"})
    assert saved.status_code == 200, saved.text
    if general:
        r = client.put(f"/api/organizations/{ORG}/plan-general", json=general)
        assert r.status_code == 200, r.text


def _fields_draft() -> dict:
    """일반 현황 칸 묶음 + 인력 구성 · 정량적 성과 표가 있는 규칙 초안(최소)."""
    labels = ["기업명", "대표자", "개업연월일", "사업장 소재지", "사업자등록번호", "연락처", "이메일", "업태/종목"]
    return {
        "generated_by": "rules",
        "sections": [{"key": "S0", "kind": "fields", "section": "일반 현황", "major_title": "일반 현황", "tables": ["staff", "performance"],
                      "fields": [{"label": l, "value": HUMAN_INPUT, "human_only": True, "source_ids": []} for l in labels],
                      "sentences": [{"text": f"{l}: {HUMAN_INPUT}", "type": None, "note": True} for l in labels]}],
        "tables": [
            {"key": "staff", "title": "인력 구성", "columns": ["연번", "성명", "직위", "담당업무", "보유 역량(경력 및 학력 등)", "구성 상태"],
             "rows": [[HUMAN_INPUT] * 6], "human_only": True, "by": "rules"},
            {"key": "performance", "title": "정량적 성과", "columns": ["구분", "2023년", "2024년", "2025년"],
             "rows": [["매출액(원)", HUMAN_INPUT, HUMAN_INPUT, HUMAN_INPUT], ["고용(명)", HUMAN_INPUT, HUMAN_INPUT, HUMAN_INPUT]],
             "human_only": True, "by": "rules"},
        ],
        "blanks": [{"field": l, "why": "사람만 채우는 칸"} for l in labels[1:]] + [
            {"field": "인력 구성", "why": "사람만 채우는 표"}, {"field": "정량적 성과", "why": "사람만 채우는 표"}],
    }


def test_회사_값은_칸에_들어가고_없는_칸만_담당자_입력() -> None:
    make_org()
    filled = plan_fill_service.fill_for(_fields_draft(), ORG, "internal")
    fields = {f["label"]: f for f in filled["sections"][0]["fields"]}
    assert fields["대표자"]["value"] == "김가상" and fields["대표자"]["source"] == "회사자료"
    assert fields["사업자등록번호"]["value"] == "123-45-67890"
    assert fields["개업연월일"]["value"] == "2016. 03. 02."
    assert fields["사업장 소재지"]["value"] == "광주광역시 가상로 1" and fields["연락처"]["value"] == "062-000-0000"
    assert fields["업태/종목"]["value"] == "서비스 / 교육 컨설팅"
    assert fields["이메일"]["value"] == HUMAN_INPUT  # 회사자료에도 없다
    # 칸 줄(문장)도 같은 값 · 회사 근거
    assert any(s["text"] == "대표자: 김가상" and s["type"] == "COMPANY_EVIDENCE_GROUNDED" for s in filled["sections"][0]["sentences"])
    # 표 — 인력 구성(성명 없이 직무 · 인원) · 정량적 성과(연도별)
    staff = next(t for t in filled["tables"] if t["key"] == "staff")
    # 30차 R29-10 — 인원은 직무 칸에 「(4명)」 · 「구성 상태」(채용 완료/예정)는 담당자 입력
    assert staff["rows"][0][3] == "AI 교육 강사(4명)" and staff["rows"][0][5] == HUMAN_INPUT and staff["rows"][0][1] == HUMAN_INPUT
    perf = next(t for t in filled["tables"] if t["key"] == "performance")
    assert perf["rows"][0][1:] == ["310,000,000", "420,000,000", HUMAN_INPUT] and perf["rows"][1][2] == "12"
    # 행 이름의 단위를 따른다 — 「매출액(억원)」 행에 원 값을 그대로 넣지 않는다
    assert plan_fill_service._money(310_000_000, "매출액(억원)") == "3.1" and plan_fill_service._money(420_000_000, "매출액(백만원)") == "420"
    # 셈 — 채운 칸은 빈칸 목록에서 빠진다 · 원본은 그대로
    fill = filled["company_fill"]
    assert "대표자" in fill["filled_fields"] and fill["filled_table_cells"] == 5  # 직무 2 + 매출 2 + 고용 1
    assert {b["field"] for b in filled["blanks"]} == {"이메일", "인력 구성", "정량적 성과"}
    assert fill["remaining"] == 3
    assert _fields_draft()["sections"][0]["fields"][1]["value"] == HUMAN_INPUT


def test_회사자료가_비면_채울_수_있는_칸을_센다() -> None:
    make_org(general=None)
    filled = plan_fill_service.fill_for(_fields_draft(), ORG, "internal")
    fill = filled["company_fill"]
    assert {"대표자", "사업자등록번호", "개업연월일", "업태/종목", "인력 구성", "정량적 성과"} <= set(fill["fillable_fields"])
    assert "이메일" not in fill["fillable_fields"]  # 대응표에 없는 칸은 회사자료로 채울 수 없다
    assert fill["filled"] == 3  # 기업명(프로필 이름) · 소재지 · 연락처


def test_점검표는_두_수로_나눠_센다() -> None:
    from app.services import plan_completeness_service

    make_org()
    form = plan_form_service.standard_form("PBLN_X", "공고문 텍스트 없음")
    checklist = plan_completeness_service.plan_completeness(plan_fill_service.fill_for(_fields_draft(), ORG, "internal"), form)
    assert "회사자료로 채움" in checklist["summary"] and "담당자가 채울 칸 3개" in checklist["summary"]
    assert checklist["company_fill"]["remaining"] == 3


def test_API_입력_검사_공개_응답에는_없다_프로필_저장이_지우지_않는다() -> None:
    make_org()
    bad = client.put(f"/api/organizations/{ORG}/plan-general", json={**GENERAL, "business_number": "1234567890"})
    assert bad.status_code == 422
    bad_year = client.put(f"/api/organizations/{ORG}/plan-general", json={**GENERAL, "revenue_by_year": [{"year": 1800, "value": 1}]})
    assert bad_year.status_code == 422
    profile = client.get(f"/api/organizations/{ORG}/profile").json()
    assert "plan_general" not in profile and "123-45-67890" not in json.dumps(profile, ensure_ascii=False)
    # 프로필을 다시 저장해도 일반현황은 남는다
    client.put(f"/api/organizations/{ORG}/profile", json={"name": "주식회사 가상교육", "data_class": "synthetic", "updated_by": "김담당"})
    general = client.get(f"/api/organizations/{ORG}/plan-general").json()
    assert general["business_number"] == "123-45-67890" and general["updated_at"]


def test_AI_본문에는_일반현황이_없고_AI_가_쓴_대표자_매출은_지워진다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    make_org()
    sent: list[str] = []

    def reply(purpose: str, n: int):
        if purpose == "plan_draft:review":
            return plan_draft_service.PlanReviewOut(weaknesses=[])
        return PlanSectionOut.model_validate({"sentences": [
            # 사람 칸 지우기는 「대표자: 이름」 모양을 본다(「대표자 역량」 같은 말을 지우지 않게 — 25차 규칙 그대로)
            {"text": "과제 책임은 대표자: 김가짜 가 맡습니다.", "type": "AI_SUGGESTION", "source": None, "source_ids": []},
            {"text": "당사 매출은 2024년 42억원입니다.", "type": "AI_SUGGESTION", "source": None, "source_ids": []}],
            "tables": {"schedule": [], "budget": []}, "blanks": []})

    ai_on(monkeypatch, reply)
    original = llm_client.complete_structured

    def spy(**kwargs):
        sent.append(kwargs["user"])
        return original(**kwargs)

    monkeypatch.setattr(llm_client, "complete_structured", spy)
    company = plan_draft_service.company_sources(ORG, "internal")
    draft = run(select_task(form), requirements, company=company, company_name="주식회사 가상교육")
    body = "\n".join(sent)
    assert sent and all(v not in body for v in ("김가상", "123-45-67890", "310000000", "420000000", "교육 컨설팅", "AI 교육 강사"))
    texts = [s["text"] for sec in draft["sections"] for s in sec["sentences"] if s.get("ai")]
    assert texts and not any("김가짜" in t or "42억" in t for t in texts)  # AI 가 쓴 사람 칸 값은 지운다(25차 규칙 그대로)
    # 문서를 조립할 때는 회사 값으로 채운다
    filled = plan_fill_service.fill_for(draft, ORG, "internal")
    general = next(s for s in filled["sections"] if s["kind"] == "fields")
    assert any(f["label"] == "대표자" and f["value"] == "김가상" for f in general["fields"])
    blocks = plan_export_service.plan_blocks(filled, form)
    assert ("text", "대표자: 김가상") in blocks


def test_30차_프로필_파일이_없는_회사는_일반현황만_따로_저장_합성_기본값을_채우지_않는다() -> None:
    """R29-01 — 일반현황을 먼저 저장하면 합성 기본 프로필(사업영역 · 지역)이 「저장된 프로필」로 굳었다."""
    from app.services import organization_service

    r = client.post("/api/organizations", json={"organization_id": "org-fresh", "display_name": "새 회사", "data_class": "synthetic", "created_by": "김담당"})
    assert r.status_code == 201, r.text
    assert client.put("/api/organizations/org-fresh/plan-general", json=GENERAL).status_code == 200
    assert organization_service.load_profile("org-fresh").source == "default_synthetic"  # 「저장 필요」 경고가 남는다
    assert organization_service.load_plan_general("org-fresh").representative == "김가상"
    values = plan_fill_service.company_values("org-fresh", "internal")
    assert values["business_domains"] is None and values["certifications"] is None and values["representative"] == "김가상"
    # 프로필을 저장하면 따로 둔 일반현황을 함께 옮긴다
    client.put("/api/organizations/org-fresh/profile", json={"name": "새 회사", "data_class": "synthetic", "updated_by": "김담당"})
    assert organization_service.load_profile("org-fresh").source == "file"
    assert organization_service.load_plan_general("org-fresh").business_number == "123-45-67890"


def test_30차_사내_범위가_아니거나_공개_배포면_일반현황을_채우지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """R29-02 — public_demo 범위에서도 대표자 · 사업자등록번호 · 매출이 응답 · DOCX 에 들어갔다."""
    from app.core.config import get_settings

    make_org()
    for scope in ("public_demo", None):
        draft = plan_fill_service.fill_for(_fields_draft(), ORG, scope)
        assert "company_fill" not in draft and "김가상" not in json.dumps(draft, ensure_ascii=False)
        assert plan_fill_service.company_values(ORG, scope)["representative"] is None
    monkeypatch.setattr(get_settings(), "public_demo_mode", True)
    assert "company_fill" not in plan_fill_service.fill_for(_fields_draft(), ORG, "internal")


def test_30차_인원_0명_줄은_채우지_않는다() -> None:
    table = {"columns": ["연번", "성명", "직위", "담당업무", "보유 역량(경력 및 학력 등)", "구성 상태"], "rows": [[HUMAN_INPUT] * 6]}
    filled, _left = plan_fill_service._fill_staff(table, [{"role": "개발", "count": 0}, {"role": "강사", "count": 2}])
    assert table["rows"] == [["1", HUMAN_INPUT, HUMAN_INPUT, "강사(2명)", HUMAN_INPUT, HUMAN_INPUT]] and filled == 1
