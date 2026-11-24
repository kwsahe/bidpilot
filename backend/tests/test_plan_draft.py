"""사업계획서 초안 — 양식 뼈대 · 절마다 작성 · 규칙 검증 · 절 단위 실패 (25차 · prompt_15 §4-C).

LLM 은 부르지 않는다 — `llm_client.complete_structured` 를 대역으로 바꾼다. 입력 양식은 126482 원문 발췌
(`test_plan_form.FULL` — 행 번호 주석은 그 파일에 있다)로 만든다. `data/private` 는 읽지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import llm_client, plan_completeness_service, plan_draft_service, plan_form_service, plan_validation, support_plan_service, support_requirement_extractor
from app.services.plan_draft_service import (
    BudgetRowOut,
    PlanSectionOut,
    PlanSentenceOut,
    PlanTablesOut,
    ScheduleRowOut,
)
from app.services.plan_form_service import HUMAN_INPUT
from tests.test_plan_form import FULL

PROGRAM = SimpleNamespace(id="PBLN_000000000126482", title="민관협력 오픈이노베이션 지원")

COMPANY = {
    "profile": {
        "name": "주식회사 시험",
        "business_domains": ["AI SaaS·소프트웨어 개발", "AI·AX 교육 및 인력양성"],
        "certifications": ["데이터 공급기업"],
        "founded_year": 2021,
        "preferred_regions": ["광주광역시"],
        "address": "광주광역시 북구 첨단과기로 123",
        "phone": "062-000-1234",
        "employee_count": 17,
    },
    "capacity": {
        "skills": [{"name": "AI 에이전트 개발", "level": "proven", "note": "내부 메모 — 보내지 않음", "source": "구술"}],
        "credentials": [{"name": "데이터바우처 공급기업", "held": True, "note": "비공개 메모"}, {"name": "소프트웨어사업자", "held": None}],
        "business_items": ["빅데이터 전략 및 컨설팅업"],
        "developer_count": 2,
        "team_note": "팀 메모 — 보내지 않음",
        "budget_ceiling_krw": 200_000_000,
    },
    "ledger": [
        {"seq": 7, "year": 2025, "field": "AI 교육", "title": "공공데이터 활용 AI 교육 과정 운영", "agency": "광주정보문화산업진흥원",
         "summary": "공공데이터 분석 실습 교육", "amount_thousand_krw": 48000, "external_use": "가능",
         "evidence_note": "계약서 사본 — 비공개", "warnings": ["금액 확인"], "exclusion_reason": None},
        {"seq": 9, "year": 2024, "field": "개발", "title": "내부 전용 과제", "agency": "비공개 기관", "summary": "외부 사용 불가",
         "amount_thousand_krw": 99000, "external_use": "불가", "evidence_note": "", "warnings": [], "exclusion_reason": "비공개"},
    ],
}
FACTS = ["창업 연차: 「창업 7년 이내」 요건이고 회사는 2021년 설립(5년차)이다."]


@pytest.fixture()
def form() -> dict:
    return plan_form_service.extract_form("bizinfo-PBLN_000000000126482", FULL)


@pytest.fixture()
def requirements():
    return support_requirement_extractor.extract_from_text("PBLN_000000000126482", FULL)


def run(form: dict, requirements, **overrides):
    kwargs = dict(
        program=PROGRAM, form=form, requirements=requirements, company=COMPANY, facts=FACTS, matches=[],
        notice_text=FULL, annex=None, company_name="주식회사 시험",
    )
    kwargs.update(overrides)
    return plan_draft_service.generate(**kwargs)


def ai_on(monkeypatch: pytest.MonkeyPatch, replies) -> list[str]:
    """AI 문을 열고 `complete_structured` 를 대역으로. replies(호출 목적) → 결과 또는 예외."""
    purposes: list[str] = []
    monkeypatch.setattr(plan_draft_service, "llm_ready", lambda: (True, None))

    def _fake(**kwargs):
        purposes.append(kwargs["purpose"])
        result = replies(kwargs["purpose"], len(purposes))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(llm_client, "complete_structured", _fake)
    return purposes


def select_task(form: dict, no: int = 3) -> dict:
    return {**form, "selected_task": next(t for t in form["tasks"] if t["no"] == no)}


# ---------------------------------------------------------------------------
# 1) AI 꺼짐 — 규칙 초안(공고 양식 뼈대)
# ---------------------------------------------------------------------------


def test_AI_꺼짐이면_양식_뼈대의_규칙_초안_소항목_8_표_5(form: dict, requirements) -> None:
    draft = run(form, requirements)
    assert draft["generated_by"] == "rules"
    assert draft["llm_note"].startswith(plan_draft_service.AI_OFF_NOTE)
    items = [s for s in draft["sections"] if s["kind"] == "item" and not s["optional"]]
    assert len(items) == 8 and len(draft["tables"]) == 5
    assert [s["section"] for s in draft["sections"]][:2] == ["일반 현황", "공공데이터 활용 계획"]
    assert draft["ai_sentence_count"] == 0
    # 과제를 안 골랐으면 과제명은 「(담당자 선택)」이고 빈칸 목록 맨 위에 「과제를 먼저 고르세요」.
    general = draft["sections"][0]
    assert next(f for f in general["fields"] if f["label"] == "과제명")["value"] == plan_form_service.TASK_PENDING
    assert draft["blanks"][0]["why"] == plan_draft_service.TASK_FIRST


def test_사람만_채우는_칸은_채우지_않는다(form: dict, requirements) -> None:
    draft = run(select_task(form), requirements)
    for section in draft["sections"]:
        for field in section.get("fields") or []:
            if field["human_only"]:
                assert field["value"] == HUMAN_INPUT, field
    staff = next(t for t in draft["tables"] if t["key"] == "staff")
    assert all(cell == HUMAN_INPUT for row in staff["rows"] for cell in row)
    text = json.dumps(draft, ensure_ascii=False)
    assert "062-000-1234" not in text and "첨단과기로" not in text


def test_규칙_초안은_겨냥_평가_항목과_공고_요구를_단다(form: dict, requirements) -> None:
    draft = run(select_task(form), requirements)
    budget = next(s for s in draft["sections"] if s["section"] == "집행 계획")
    assert budget["eval_targets"] == ["실현 가능성 및 구체성"]
    assert any(s.get("notice_quote") and "1억원" in s["text"] for s in budget["sentences"])
    solve = next(s for s in draft["sections"] if s["section"] == "과제 해결방안")
    assert any("강남서초교육지원청" in s["text"] for s in solve["sentences"])


# ---------------------------------------------------------------------------
# 2) 허용 목록 직렬화 — 보내지 않는 것 0
# ---------------------------------------------------------------------------


def test_밖으로_보내는_본문에_금지_필드가_없다(form: dict, requirements) -> None:
    form = select_task(form)
    units = plan_draft_service.form_units(form)
    routed = plan_draft_service.route_clauses(units, requirements)
    matches = [{"id": "doc-1", "document_name": "회사소개서.pdf", "text": "채택 본문 — 비공개 단락", "selected": True}]
    for unit in units:
        bundle = plan_draft_service.build_bundle(
            unit, form=form, clauses=routed[unit["key"]], company=COMPANY, facts=FACTS, matches=matches, annex=None
        )
        bundle["clause_reviews"] = ["조항 확인 메모 — 보내지 않음"]
        payload = json.dumps(plan_draft_service.llm_payload(bundle), ensure_ascii=False)
        for secret in ("062-000-1234", "첨단과기로", "17", "48000", "99000", "계약서 사본", "금액 확인", "비공개",
                       "developer_count", "팀 메모", "200000000", "내부 메모", "비공개 메모", "조항 확인 메모", "채택 본문", "주식회사 시험"):
            assert secret not in payload, (unit["title"], secret)
        assert "내부 전용 과제" not in payload  # 외부 사용 「불가」 행


# ---------------------------------------------------------------------------
# 3) AI 작성 + 규칙 검증
# ---------------------------------------------------------------------------


def _good(purpose: str, n: int) -> PlanSectionOut:
    if purpose == "plan_draft:review":
        return plan_draft_service.PlanReviewOut()
    return PlanSectionOut(sentences=[
        PlanSentenceOut(text="우리 회사는 공공데이터를 가공해 학교 에너지 사용을 모니터링하는 모델을 만듭니다.", type="AI_SUGGESTION"),
        PlanSentenceOut(text="2025년 공공데이터 활용 AI 교육 과정을 운영했습니다.", type="COMPANY_EVIDENCE_GROUNDED", source_ids=["ledger:7"]),
    ])


def test_AI_초안은_절마다_쓰고_공고_요구_줄을_남긴다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    purposes = ai_on(monkeypatch, _good)
    draft = run(select_task(form), requirements)
    writes = [p for p in purposes if p != "plan_draft:review"]
    assert len(writes) == 8 and "plan_draft:review" in purposes
    assert draft["generated_by"] == "llm" and draft["llm_note"] is None
    assert draft["attempts"]["logical_calls"] <= draft["attempts"]["max_logical_calls"] == 11  # 절 8 + 채점 1 + 고쳐 쓰기 2(30차)
    budget = next(s for s in draft["sections"] if s["section"] == "집행 계획")
    assert any(s.get("notice_quote") for s in budget["sentences"])
    company = [s for sec in draft["sections"] for s in sec["sentences"] if s.get("ai") and s["type"] == plan_draft_service.COMPANY]
    assert company and all(not s["flags"] for s in company)


def test_근거_없는_회사_주장은_AI_제안으로_내린다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    def _bad(purpose: str, n: int):
        if purpose == "plan_draft:review":
            return plan_draft_service.PlanReviewOut()
        return PlanSectionOut(sentences=[
            PlanSentenceOut(text="2019년 한국도로공사 과제를 수행했습니다.", type="COMPANY_EVIDENCE_GROUNDED", source_ids=["ledger:7"]),
            PlanSentenceOut(text="근거 없는 주장입니다.", type="COMPANY_EVIDENCE_GROUNDED", source_ids=["ledger:404"]),
        ])

    ai_on(monkeypatch, _bad)
    draft = run(select_task(form), requirements)
    ai = [s for sec in draft["sections"] for s in sec["sentences"] if s.get("ai")]
    assert ai and all(s["type"] == plan_draft_service.SUGGESTION for s in ai)
    assert all(any(f.startswith(plan_draft_service.GROUNDING_FLAGS) for f in s["flags"]) for s in ai)
    assert draft["validation"]["demoted"] == len(ai)


def test_예시_값_사람_칸_금칙어_복사를_잡는다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    copied = "공공기관 제안 과제 해결을 위한 공공데이터 활용 방안 및 요구 기술에 대한 이해도"  # 평가지표 원문

    def _reply(purpose: str, n: int):
        if purpose == "plan_draft:review":
            return plan_draft_service.PlanReviewOut()
        return PlanSectionOut(sentences=[
            PlanSentenceOut(text="재료비로 3,448,000원을 씁니다.", type="AI_SUGGESTION"),
            PlanSentenceOut(text="문의는 연락처 010-1234-5678 로 합니다.", type="AI_SUGGESTION"),
            PlanSentenceOut(text="국내 유일의 기술로 선정 확률을 높입니다.", type="AI_SUGGESTION"),
            PlanSentenceOut(text=copied + "를 높이겠습니다.", type="AI_SUGGESTION"),
        ])

    ai_on(monkeypatch, _reply)
    draft = run(select_task(form), requirements)
    first = next(s for s in draft["sections"] if s["by"] == "llm")
    texts = [s for s in first["sentences"] if s.get("ai")]
    assert "3,448,000" not in texts[0]["text"] and HUMAN_INPUT in texts[0]["text"]
    assert "010-1234-5678" not in texts[1]["text"]
    assert any(f.startswith(plan_draft_service.FLAG_BANNED) for f in texts[2]["flags"])
    assert any(f.startswith(plan_draft_service.FLAG_COPY) for f in texts[3]["flags"])
    # 규칙 초안의 「공고 요구」 인용 줄은 복사로 세지 않는다.
    assert not any(s.get("notice_quote") and s.get("flags") for sec in draft["sections"] for s in sec["sentences"])
    assert draft["validation"]["examples"] >= 1 and draft["validation"]["human"] >= 1


def test_사업비_표_원_단위_예시_값_상한_일정_범위(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    def _reply(purpose: str, n: int):
        if purpose == "plan_draft:review":
            return plan_draft_service.PlanReviewOut()
        return PlanSectionOut(
            sentences=[PlanSentenceOut(text="사업비는 항목별로 나눕니다.", type="AI_SUGGESTION")],
            tables=PlanTablesOut(
                budget=[BudgetRowOut(item="외주용역비", basis="데이터 가공", amount_krw=3_448_000),
                        BudgetRowOut(item="재료비", basis="데이터 구매", amount_krw=60_000_000),
                        BudgetRowOut(item="회식비", basis="-", amount_krw=50_000_000)],
                schedule=[ScheduleRowOut(task="산출물 협의", period="’26.12월 ~ ’27.3월", detail="기능 구현"),
                          ScheduleRowOut(task="확산", period="’27.5월", detail="사업화")],
            ),
        )

    ai_on(monkeypatch, _reply)
    draft = run(select_task(form), requirements)
    budget = next(t for t in draft["tables"] if t["key"] == "budget")
    assert budget["rows"][0][2] == HUMAN_INPUT  # 예시 금액 3,448,000 은 근거가 아니다
    check = draft["validation"]["budget"]
    assert check["cap_krw"] == 100_000_000  # 「1억원」 = 100,000,000원
    assert check["total_krw"] == 110_000_000 and check["over_cap"] is True
    assert check["items_outside"] == ["회식비"]
    schedule = next(t for t in draft["tables"] if t["key"] == "schedule")
    assert "협약 기간 밖" not in schedule["rows"][0][1]  # ’27.3월 은 협약 기간 안
    assert "협약 기간 밖" in schedule["rows"][1][1]


def test_고른_과제의_기관을_말해도_회사_근거는_내리지_않는다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """시험 실행(9-28)에서 「…교육지원청 담당자 대상 교육」이 근거 없음으로 5번 내려갔다 — 기관은 고른 과제의 것이다."""
    def _reply(purpose: str, n: int):
        if purpose == "plan_draft:review":
            return plan_draft_service.PlanReviewOut()
        return PlanSectionOut(sentences=[
            PlanSentenceOut(text="2025년 공공데이터 활용 AI 교육 과정 운영 경험으로 강동송파교육지원청 담당자 대상 교육을 운영합니다.",
                            type="COMPANY_EVIDENCE_GROUNDED", source_ids=["ledger:7"]),
            PlanSentenceOut(text="2025년 한국도로공사 교육 과정을 운영했습니다.", type="COMPANY_EVIDENCE_GROUNDED", source_ids=["ledger:7"]),
        ])

    ai_on(monkeypatch, _reply)
    draft = run(select_task(form, 4), requirements)
    team = next(sec for sec in draft["sections"] if sec["section"] == "기업(팀) 역량")  # 실적은 역량 절에만 싣는다
    ai = [s for s in team["sentences"] if s.get("ai")]
    agency = [s for s in ai if "강동송파교육지원청" in s["text"]]
    other = [s for s in ai if "한국도로공사" in s["text"]]
    assert agency and all(s["type"] == plan_draft_service.COMPANY and not s["flags"] for s in agency)
    assert other and all(s["type"] == plan_draft_service.SUGGESTION and "한국도로공사" in s["flags"][0] for s in other)
    # 실적이 실리지 않은 절에서 실적을 가리키면 근거가 없다(여덟 절이 같은 실적을 되풀이하지 않게).
    solve = next(sec for sec in draft["sections"] if sec["section"] == "과제 해결방안")
    assert all(s["type"] == plan_draft_service.SUGGESTION and s["flags"][0] == plan_draft_service.FLAG_NO_COMPANY_SOURCE
               for s in solve["sentences"] if s.get("ai"))


def test_사업비_합계_줄은_비목이_아니고_항목_합과_견준다(form: dict) -> None:
    rows = [["인건비", "", "30,000,000"], ["외주용역비", "", "20,000,000"], ["합계", "", "50,000,000"]]
    check = plan_draft_service.budget_check(rows, form)
    assert check["total_krw"] == 50_000_000 and check["items_outside"] == [] and not check["total_mismatch"] and not check["over_cap"]
    check = plan_draft_service.budget_check(rows[:2] + [["합계", "", "60,000,000"]], form)
    assert check["total_mismatch"] and check["total_krw"] == 50_000_000
    check = plan_draft_service.budget_check([["인건비", "", "(담당자 입력)"], ["합계", "과제별 최대 1억원 이내", "(담당자 입력)"]], form)
    assert check["items_outside"] == [] and not check["total_mismatch"] and not check["over_cap"]
    check = plan_draft_service.budget_check([["인건비", "", "(담당자 입력)"], ["합계", "", "120,000,000"]], form)
    assert check["over_cap"]  # 항목 금액이 비어도 합계 줄이 상한을 넘으면 알린다


def test_세번째_절이_실패하면_그_절만_규칙_내용_사유(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    def _reply(purpose: str, n: int):
        # 절을 동시에 쓰므로 「세 번째 호출」이 아니라 세 번째 절의 목적으로 가른다.
        if purpose == "plan_draft:기술 등 경쟁력":
            return llm_client.LLMUnavailableError("AI 검색 요청이 한도를 넘었습니다.")
        return _good(purpose, n)

    ai_on(monkeypatch, _reply)
    draft = run(select_task(form), requirements)
    items = [s for s in draft["sections"] if s["kind"] == "item" and not s["optional"]]
    assert items[0]["by"] == "llm" and items[1]["by"] == "llm"
    assert items[2]["by"] == "rules" and "한도" in items[2]["llm_error"]
    assert any("AI 작성 실패" in s["text"] for s in items[2]["sentences"])
    assert "실패 절 1개" in draft["llm_note"]


def test_과제를_안_고르면_AI_를_부르지_않는다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    purposes = ai_on(monkeypatch, _good)
    draft = run(form, requirements)
    assert purposes == [] and draft["generated_by"] == "rules"
    assert plan_draft_service.TASK_FIRST in draft["llm_note"]


def test_시간_상한을_넘으면_남은_절은_규칙(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    ticks = iter([0.0] + [0.0] * 3 + [999.0] * 200)
    ai_on(monkeypatch, _good)
    draft = run(select_task(form), requirements, clock=lambda: next(ticks))
    reasons = [s["llm_error"] for s in draft["sections"] if s["llm_error"]]
    assert reasons and all("시간 상한" in r for r in reasons)


# ---------------------------------------------------------------------------
# 4) 반영 셈 · AI 초안 유지
# ---------------------------------------------------------------------------


def test_AI_가_조항을_다시_써도_미반영_수가_규칙_초안과_같다(form: dict, requirements) -> None:
    rule = run(select_task(form), requirements)
    rewritten = json.loads(json.dumps(rule, ensure_ascii=False))
    for section in rewritten["sections"]:
        for sentence in section["sentences"]:
            if sentence.get("notice_quote"):
                sentence["text"] = "공고가 요구하는 조건을 우리 말로 다시 적었습니다."
                sentence["source"] = None  # 원문 대조로는 못 찾는다 — id 로 센다
    before = support_plan_service.uncovered_quotes(rule, requirements)
    after = support_plan_service.uncovered_quotes(rewritten, requirements)
    assert after == before


def test_AI_초안을_규칙_초안으로_덮지_않는다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(support_plan_service, "draft_dir", lambda _ctx, _pid: tmp_path)
    context = SimpleNamespace(organization_id="org-test-alpha", evidence_scope="internal")
    llm_draft = {"generated_by": "llm", "executed_at": "2026-10-01T00:00:00+00:00", "provider": "xai", "sections": [{"section": "a", "sentences": []}]}
    support_plan_service.save(llm_draft, context=context, program_id="P")
    rules_draft = {"generated_by": "rules", "executed_at": "2026-10-02T00:00:00+00:00", "sections": [{"section": "b", "sentences": []}]}

    shown, kept = support_plan_service.save_draft(rules_draft, context=context, program_id="P")
    assert kept is True and shown["generated_by"] == "llm"
    assert support_plan_service.load(context=context, program_id="P")["generated_by"] == "llm"
    assert any(p.name.startswith("rules-") for p in (tmp_path / support_plan_service.VERSIONS_DIR).iterdir())

    shown, kept = support_plan_service.save_draft(rules_draft, context=context, program_id="P", force_rules=True)
    assert kept is False and support_plan_service.load(context=context, program_id="P")["generated_by"] == "rules"


# ---------------------------------------------------------------------------
# 5) 만드는 동안에도 /health 가 답한다
# ---------------------------------------------------------------------------


def test_생성_중에도_health_가_1초_안에_답한다(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from app.api import insights
    from app.main import app
    from app.services import bizinfo_document_store, support_application_service

    async def _build(*_a, **_kw):
        return {"draft_outline": [], "evidence_matches": []}

    async def _find(*_a, **_kw):
        return PROGRAM, None, "sample"

    def _slow(**_kw):
        time.sleep(2.0)
        return {"generated_by": "rules", "sections": [], "executed_at": "2026-10-01T00:00:00+00:00"}

    monkeypatch.setattr(support_application_service, "build", _build)
    monkeypatch.setattr(support_application_service, "find_program", _find)
    monkeypatch.setattr(plan_form_service, "form_for", lambda *_a, **_kw: plan_form_service.standard_form("P", "공고문 텍스트 없음"))
    monkeypatch.setattr(plan_form_service, "save_form", lambda *_a, **_kw: None)
    monkeypatch.setattr(plan_form_service, "annex_excerpt", lambda *_a, **_kw: None)
    monkeypatch.setattr(support_requirement_extractor, "load", lambda *_a, **_kw: None)
    monkeypatch.setattr(bizinfo_document_store, "load_text", lambda *_a, **_kw: None)
    monkeypatch.setattr(plan_draft_service, "company_sources", lambda *_a, **_kw: {})
    monkeypatch.setattr(plan_draft_service, "generate", _slow)
    monkeypatch.setattr(support_plan_service, "save_draft", lambda draft, **_kw: (draft, False))
    monkeypatch.setattr(insights, "_plan_form_view", lambda _ctx, _pid, form: form)

    async def scenario() -> float:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 느린 요청을 보낸 때부터 잰다 — 루프가 막히면 sleep 자체가 늦게 깨서, 그 뒤부터 재면 막힘이 안 보인다(26차).
            started = time.monotonic()
            post = asyncio.create_task(client.post("/api/support-programs/bizinfo-P/plan-draft?organization_id=org-sample", json={}))
            await asyncio.sleep(0.3)
            health = await client.request("GET", "/health")  # conftest 가 AsyncClient.get 만 막는다 — ASGI 전송은 네트워크가 아니다
            elapsed = time.monotonic() - started
            assert health.status_code == 200
            response = await post
            assert response.status_code == 200, response.text
            return elapsed

    assert asyncio.run(scenario()) < 1.5  # 막히면 2초 뒤


def test_없는_과제_번호는_400(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import support_application_service

    async def _build(*_a, **_kw):
        return {"draft_outline": [], "evidence_matches": []}

    async def _find(*_a, **_kw):
        return PROGRAM, None, "sample"

    monkeypatch.setattr(support_application_service, "build", _build)
    monkeypatch.setattr(support_application_service, "find_program", _find)
    monkeypatch.setattr(plan_form_service, "build_form", lambda _pid: plan_form_service.extract_form("P", FULL))
    monkeypatch.setattr(plan_form_service, "load_saved", lambda *_a, **_kw: {})
    response = TestClient(app).post("/api/support-programs/bizinfo-P/plan-draft?organization_id=org-sample", json={"task_no": 99})
    assert response.status_code == 400 and "99" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 6) 완성도 점검표 (§4-D)
# ---------------------------------------------------------------------------


def test_점검표_규칙_초안(form: dict, requirements) -> None:
    from app.services import plan_completeness_service

    chosen = select_task(form)
    draft = run(chosen, requirements)
    check = plan_completeness_service.plan_completeness(draft, chosen, company_region="광주광역시")
    assert check["form"]["items_total"] == 8 and check["form"]["tables_present"] == check["form"]["tables_total"] == 5
    assert check["evaluation"]["covered"] == check["evaluation"]["total"] == 4
    assert check["evaluation"]["bonus"][0]["applies"] is True
    assert check["kind"]["label"] == "기본 초안(AI 미사용 · 공고 양식 목차)" and check["kind"]["failed_sections"] == 0
    assert check["length"]["recommended"] == 7 * 1500
    assert check["blanks"]["count"] > 0 and "대표자" in check["blanks"]["fields"]
    assert check["summary"].startswith("양식 ") and check["summary"].endswith("기본 초안")
    assert plan_completeness_service.plan_completeness(draft, chosen, company_region="서울특별시")["evaluation"]["bonus"][0]["applies"] is False


def test_점검표_AI_초안_복사_비율과_근거_불일치(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    from app.services import plan_completeness_service

    copied = "공공기관 제안 과제 해결을 위한 공공데이터 활용 방안 및 요구 기술에 대한 이해도"

    def _reply(purpose: str, n: int):
        if purpose == "plan_draft:review":
            return plan_draft_service.PlanReviewOut()
        return PlanSectionOut(sentences=[
            PlanSentenceOut(text=copied + "를 높입니다.", type="AI_SUGGESTION"),
            PlanSentenceOut(text="2019년 실적이 있습니다.", type="COMPANY_EVIDENCE_GROUNDED", source_ids=["ledger:7"]),
        ])

    ai_on(monkeypatch, _reply)
    chosen = select_task(form)
    draft = run(chosen, requirements)
    check = plan_completeness_service.plan_completeness(draft, chosen)
    assert check["copy"]["percent"] == 50 and check["copy"]["tone"] == "warn"
    assert check["numbers"]["mismatches"] == 8
    assert check["form"]["items_filled"] == 8
    assert check["evaluation"]["bonus"][0]["applies"] is None  # 소재지를 모르면 판정하지 않는다
    assert check["summary"].endswith("AI 초안")


def test_예전_초안은_양식_기준으로_세지_않는다(form: dict) -> None:
    from app.services import plan_completeness_service

    legacy = {"generated_by": "rules", "sections": [{"section": "사업 개요·추진 배경", "sentences": []}]}
    assert plan_completeness_service.plan_completeness(legacy, form)["legacy"] is True


# ---------------------------------------------------------------------------
# 7) 9-28 시험 실행(공개 자료 · Claude CLI) 검수에서 나온 것
# ---------------------------------------------------------------------------


def test_사람_수_매출이_든_규칙_사실은_밖으로_보내지_않는다(form: dict, requirements) -> None:
    """PRIV-1 — 「고용 인원: … 회사는 17인이다」가 fact 로 그대로 나갈 수 있었다."""
    from app.services.support_application_service import COMPANY_FACT_WORDS

    assert {f"{COMPANY_FACT_WORDS[k]}:" for k in ("BIZ-HEADCOUNT", "BIZ-SMALL-BUSINESS", "BIZ-REVENUE")} == set(plan_draft_service.PRIVATE_FACT_PREFIXES)
    form = select_task(form)
    facts = FACTS + ["고용 인원: 「5인 이상」 요건이고 회사는 17인이다.", "매출: 회사 매출 30억원으로 요건 안이다."]
    unit = next(u for u in plan_draft_service.form_units(form) if u["title"] == "기업(팀) 역량")
    bundle = plan_draft_service.build_bundle(unit, form=form, clauses=[], company=COMPANY, facts=facts, matches=[], annex=None)
    payload = json.dumps(plan_draft_service.llm_payload(bundle), ensure_ascii=False)
    assert "창업 연차" in payload and "17인" not in payload and "30억원" not in payload


def test_17인_규모도_사람_칸으로_지운다() -> None:
    """PRIV-2 — 「인」으로 쓴 인원은 걸리지 않았다."""
    from app.services import plan_validation

    for text in ("당사는 상시근로자 17인 규모로 운영합니다.", "당사는 17인 규모의 기업입니다.", "회사는 12명의 전문 인력으로"):
        cleaned, removed = plan_validation.strip_human_fields(text)
        assert "17" not in cleaned and "12" not in cleaned and removed == ["매출액·고용인원"], (text, cleaned)


def _one_unit_reply(section: str, out: PlanSectionOut):
    def _reply(purpose: str, n: int):
        if purpose == "plan_draft:review":
            return plan_draft_service.PlanReviewOut()
        return out if purpose == f"plan_draft:{section}" else PlanSectionOut()
    return _reply


def test_AI_가_채운_표_칸도_사람_칸_금칙어_복사_예시를_본다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """PRIV-3 · OC-4 · NUM-5 — 표 칸은 검사 없이 내려받기 파일로 나갔다."""
    copied = "공공기관 제안 과제 해결을 위한 공공데이터 활용 방안 및 요구 기술에 대한 이해도"
    out = PlanSectionOut(tables=PlanTablesOut(budget=[
        BudgetRowOut(item="인건비", basis="책임연구원 연락처 062-000-1234 월 3,448,000원"),
        BudgetRowOut(item="외주용역비", basis=copied),
        BudgetRowOut(item="지급수수료", basis="100% 보장되는 클라우드 이용료"),
    ]))
    ai_on(monkeypatch, _one_unit_reply("집행 계획", out))
    draft = run(select_task(form), requirements)
    rows = next(t for t in draft["tables"] if t["key"] == "budget")["rows"]
    assert "062-000-1234" not in rows[0][1] and "3,448,000" not in rows[0][1]
    assert rows[1][1].endswith(f"⚠ {plan_draft_service.CELL_MARK_COPY}") and f"⚠ {plan_draft_service.CELL_MARK_BANNED}" in rows[2][1]
    assert draft["validation"]["human"] >= 1 and draft["validation"]["copy"] >= 1 and draft["validation"]["banned"] >= 1
    assert any(b["field"] == "연락처" for b in draft["blanks"])


def test_회사_주장은_회사_조각으로만_공고_과제_id_로는_안_된다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """G6 · G7 — 과제 id 만 단 사업영역 주장이 회사 근거로 통과했고, 보유 자격은 id 가 없어 쓰지 못했다."""
    out = PlanSectionOut(sentences=[
        PlanSentenceOut(text="당사는 AI 교육을 주력으로 합니다.", type="COMPANY_EVIDENCE_GROUNDED", source_ids=["task:3"]),
        PlanSentenceOut(text="당사는 데이터바우처 공급기업으로 협약일부터 데이터를 라벨링처럼 가공합니다.",
                        type="COMPANY_EVIDENCE_GROUNDED", source_ids=["cap:cred:데이터바우처 공급기업"]),
        PlanSentenceOut(text="당사의 사업영역은 AI SaaS·소프트웨어 개발입니다.", type="COMPANY_EVIDENCE_GROUNDED", source_ids=["profile:domains"]),
    ])
    ai_on(monkeypatch, _one_unit_reply("기술 등 경쟁력", out))
    draft = run(select_task(form), requirements)
    section = next(s for s in draft["sections"] if s["section"] == "기술 등 경쟁력")
    ai = [s for s in section["sentences"] if s.get("ai")]

    def said(head: str) -> dict:
        return next(s for s in ai if s["text"].startswith(head))

    assert said("당사는 AI 교육")["type"] == plan_draft_service.SUGGESTION
    assert said("당사는 데이터바우처")["type"] == plan_draft_service.COMPANY and not said("당사는 데이터바우처")["flags"]
    assert said("당사의 사업영역")["type"] == plan_draft_service.COMPANY
    unit = next(u for u in plan_draft_service.form_units(form) if u["title"] == "기술 등 경쟁력")
    payload = plan_draft_service.llm_payload(plan_draft_service.build_bundle(
        unit, form=select_task(form), clauses=[], company=COMPANY, facts=FACTS, matches=[], annex=None))
    assert payload["company"]["credentials"] == [{"source_id": "cap:cred:데이터바우처 공급기업", "name": "데이터바우처 공급기업"}]
    assert payload["company"]["performance"][0]["client_agency"] == "광주정보문화산업진흥원"


def test_공고_근거_문장은_인용이_문장의_절반은_돼야_한다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """F2 · G5 — 과제 id 하나만 달면 우리 계획도 공고 근거(검은 글씨)로 나갔다."""
    task_title = "학교 에너지·탄소 통합관리 및 모니터링 시스템 개발"
    long_quote = "공공기관 제안 과제 해결을 위한 공공데이터 활용 방안 및 요구 기술에 대한 이해도"
    out = PlanSectionOut(sentences=[
        PlanSentenceOut(text=f"「{task_title}」 과제의 산출물은 에너지 DB 구축, AI 예측 모델, 현장 대시보드, 담당자 교육 네 가지이며 단계별로 수행합니다.",
                        type="RFP_GROUNDED", source=task_title, source_ids=["task:3"]),
        PlanSentenceOut(text="공고는 없는 조항을 요구합니다.", type="RFP_GROUNDED", source="공고에 없는 인용 문장입니다", source_ids=["task:3"]),
        PlanSentenceOut(text=f"평가 기준은 {long_quote}입니다.", type="RFP_GROUNDED", source=long_quote, source_ids=["eval:1"]),
        # 과제 기관명은 인용으로 센다 — 과제를 되풀이한 문장이 기관명 때문에 내려가지 않게(2차 검수 F1).
        PlanSentenceOut(text=f"서울특별시 강남서초교육지원청이 제시한 「{task_title}」이 목표입니다.", type="RFP_GROUNDED",
                        source=task_title, source_ids=["task:3"]),
        # 인용 두 개를 「 / 」로 이어 붙여도 조각마다 찾는다(2차 검수 F2).
        PlanSentenceOut(text=f"「{task_title}」 과제로 협약 기간 「협약일～’27.3월(5개월)」 안에 마칩니다.", type="RFP_GROUNDED",
                        source=f"{task_title} / 협약일～’27.3월(5개월)", source_ids=["task:3"]),
    ])
    ai_on(monkeypatch, _one_unit_reply("과제 해결방안", out))
    draft = run(select_task(form), requirements)
    ai = [s for s in next(s for s in draft["sections"] if s["section"] == "과제 해결방안")["sentences"] if s.get("ai")]
    assert ai[0]["type"] == plan_draft_service.SUGGESTION and ai[0]["flags"] == ["공고에 없는 내용입니다 — AI가 덧붙였으니 확인하세요"]
    assert ai[1]["type"] == plan_draft_service.SUGGESTION and ai[1]["flags"][0] == plan_draft_service.FLAG_NOTICE_NOT_FOUND
    # 평가 기준을 옮기기만 한 문장은 공고 요구가 아니다(2차 검수 G7) — 인용 자체는 복사로 세지 않는다.
    assert ai[2]["type"] == plan_draft_service.SUGGESTION and ai[2]["flags"] == ["평가 기준을 옮겨 적은 문장입니다 — AI가 덧붙였으니 확인하세요"]
    assert ai[3]["type"] == plan_draft_service.NOTICE and not ai[3]["flags"]
    assert ai[4]["type"] == plan_draft_service.NOTICE and not ai[4]["flags"]


def test_추진_계획을_먼저_쓰고_그_단계를_다른_절에_넘긴다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """NUM-3 · F3 — 절을 따로 쓰니 3단계 · 5단계가 섞였다."""
    prompts: dict[str, str] = {}
    order: list[str] = []
    monkeypatch.setattr(plan_draft_service, "llm_ready", lambda: (True, None))

    def _fake(**kwargs):
        order.append(kwargs["purpose"])
        prompts[kwargs["purpose"]] = kwargs["user"]
        if kwargs["purpose"] == "plan_draft:review":
            return plan_draft_service.PlanReviewOut()
        if kwargs["purpose"] == "plan_draft:추진 계획":
            return PlanSectionOut(tables=PlanTablesOut(schedule=[
                ScheduleRowOut(task="현황 진단", period="협약일 ~ 2026.12", detail="요구사항 정리"),
                ScheduleRowOut(task="시스템 개발", period="2027.1 ~ 2027.3", detail="구현"),
            ]))
        return PlanSectionOut()

    monkeypatch.setattr(llm_client, "complete_structured", _fake)
    run(select_task(form), requirements)
    assert order[0] == "plan_draft:추진 계획"
    assert "이미 정한 추진 단계" not in prompts["plan_draft:추진 계획"]
    assert "현황 진단(협약일 ~ 2026.12): 요구사항 정리 / 시스템 개발(2027.1 ~ 2027.3): 구현" in prompts["plan_draft:집행 계획"]
    assert "되풀이하지 않고" in prompts["plan_draft:집행 계획"]  # 단계를 다시 늘어놓지 않게


def test_고친_절은_빈칸과_셈을_바꾸고_못_고친_약점은_남긴다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """G12 · F6 — 버린 첫 판의 셈이 남고(내림 8 ≠ 실제 6) · 고치지 못한 약점은 사라졌다."""
    units = {u["title"]: u["key"] for u in plan_draft_service.form_units(form)}
    rewrites: list[str] = []

    def _reply(purpose: str, n: int):
        if purpose == "plan_draft:review":
            return plan_draft_service.PlanReviewOut(weaknesses=[
                plan_draft_service.ReviewWeakness(unit_key=units["사업화 방안"], eval_item="지속 가능성", weakness="수익 모델이 없다"),
                plan_draft_service.ReviewWeakness(unit_key=units["과제 해결방안"], eval_item="이해도", weakness="요구 분석이 얕다"),
                plan_draft_service.ReviewWeakness(unit_key=units["기업(팀) 역량"], eval_item="팀(기업) 구성", weakness="인력이 얕다"),
            ])
        if purpose == "plan_draft:과제 해결방안":
            rewrites.append(purpose)
            if len(rewrites) == 1:  # 첫 판 — 근거 없는 회사 주장 하나 · 빈칸 하나
                return PlanSectionOut(sentences=[PlanSentenceOut(text="2019년 실적이 있습니다.", type="COMPANY_EVIDENCE_GROUNDED", source_ids=["ledger:404"])],
                                      blanks=[plan_draft_service.PlanBlankOut(field="첫 판 빈칸", why="버려질 판")])
            return PlanSectionOut(sentences=[PlanSentenceOut(text="요구를 기능 단위로 나눕니다.", type="AI_SUGGESTION")],
                                  blanks=[plan_draft_service.PlanBlankOut(field="고친 판 빈칸", why="남는다")])
        return PlanSectionOut()

    ai_on(monkeypatch, _reply)
    draft = run(select_task(form), requirements)
    assert len(rewrites) == 2
    assert draft["validation"]["demoted"] == 0  # 버린 첫 판의 내림은 세지 않는다
    fields = [b["field"] for b in draft["blanks"]]
    assert "고친 판 빈칸" in fields and "첫 판 빈칸" not in fields
    # 30차 — 「하」 절 최대 2개 · 팀(기업) 구성 → 협업 과제 이해도 먼저: 사업화 방안은 메모로 남는다
    assert draft["review_notes"] == [{"section": "사업화 방안", "items": ["[지속 가능성] 수익 모델이 없다"]}]


def test_빈칸은_사람_표를_올리고_같은_칸을_합친다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """F9 · F10 — 인력 구성 · 정량적 성과 표가 목록에 없었고, 같은 칸을 절마다 되풀이했다."""
    def _reply(purpose: str, n: int):
        if purpose == "plan_draft:review":
            return plan_draft_service.PlanReviewOut()
        return PlanSectionOut(blanks=[plan_draft_service.PlanBlankOut(field="시범 학교 수(개교)", why="기관과 확인"),
                                      plan_draft_service.PlanBlankOut(field="과제소개서 요구사항", why="과제소개서를 받아야 한다")])

    ai_on(monkeypatch, _reply)
    draft = run(select_task(form), requirements)
    fields = [b["field"] for b in draft["blanks"]]
    assert fields.count("시범 학교 수(개교)") == 1 and fields.count("과제소개서 요구사항") == 1
    assert "과제소개서" not in fields  # 모델이 이미 올렸으면 규칙 빈칸을 겹쳐 넣지 않는다
    assert {"인력 구성", "수상 이력 등", "정량적 성과"} <= set(fields)  # 표 이름은 공고 양식 글 그대로(27차 D7)


def test_담당자_메모_문장은_본문이_아니라_빈칸으로(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """F8 — 「근거 자료로 확인되지 않습니다」가 본문(검은 글씨)으로 나갔다."""
    out = PlanSectionOut(sentences=[
        PlanSentenceOut(text="공간 DB 구축 실적은 현재 근거 자료로 확인되지 않습니다.", type="AI_SUGGESTION"),
        PlanSentenceOut(text="시범 학교에서 먼저 적용합니다.", type="AI_SUGGESTION"),
    ])
    ai_on(monkeypatch, _one_unit_reply("기업(팀) 역량", out))
    draft = run(select_task(form), requirements)
    team = next(s for s in draft["sections"] if s["section"] == "기업(팀) 역량")
    assert [s["text"] for s in team["sentences"] if s.get("ai")] == ["시범 학교에서 먼저 적용합니다."]
    assert any("근거 자료로 확인되지 않습니다" in b["why"] for b in draft["blanks"])


def test_제외_조항은_계획서_절에_싣지_않고_과제명은_공고_근거(form: dict, requirements) -> None:
    """F11 · G11 — 탈락 점수 · 신청 개수가 역량 절의 「공고 요구」로 붙었고, 과제명이 회사 프로필 출처로 표시됐다."""
    units = plan_draft_service.form_units(form)
    routed = plan_draft_service.route_clauses(units, requirements)
    assert all(c["kind"] != "exclusion" for clauses in routed.values() for c in clauses)
    draft = run(select_task(form), requirements)
    line = next(s for s in draft["sections"][0]["sentences"] if s["text"].startswith("과제명:"))
    assert line["type"] == plan_draft_service.NOTICE and line["source"] == "공고 과제 목록"


def test_사업비_합계_이름_변형과_금액_미입력_행(form: dict) -> None:
    """NUM-6 · NUM-1 — 「합계(원)」은 비목으로 · 금액이 비면 상한 검사를 한 것처럼 보였다."""
    check = plan_draft_service.budget_check([["인건비", "", "30,000,000"], ["합계(원)", "", "30,000,000"]], form)
    assert check["items_outside"] == [] and not check["total_mismatch"] and check["blank_rows"] == 0
    check = plan_draft_service.budget_check([["인건비", "", "(담당자 입력)"], ["여비", "", "1,000,000"]], form)
    assert check["blank_rows"] == 1



def test_회사_근거_문장은_근거_밖_글이_길면_AI_제안(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """2차 검수 G1~G3 · F8 — 사업영역 한 마디를 달고 나머지는 계획인 문장이 회사 근거(검은 글씨)로 나갔다."""
    out = PlanSectionOut(sentences=[
        PlanSentenceOut(text="당사는 AI SaaS·소프트웨어 개발 기업으로, 자사 SaaS 제품에 점검 기능을 모듈로 붙여 전국 학교에 구독형으로 판매하고 "
                             "유지보수 인력을 배치해 연간 계약으로 운영하겠습니다.",
                        type="COMPANY_EVIDENCE_GROUNDED", source_ids=["profile:domains"]),
        PlanSentenceOut(text="당사의 사업영역은 AI SaaS·소프트웨어 개발입니다.", type="COMPANY_EVIDENCE_GROUNDED", source_ids=["profile:domains"]),
    ])
    ai_on(monkeypatch, _one_unit_reply("기술 등 경쟁력", out))
    draft = run(select_task(form), requirements)
    ai = [s for s in next(s for s in draft["sections"] if s["section"] == "기술 등 경쟁력")["sentences"] if s.get("ai")]
    assert ai[0]["type"] == plan_draft_service.SUGGESTION and ai[0]["flags"] == ["회사 근거에 없는 내용입니다 — AI가 덧붙였으니 확인하세요"]
    assert ai[1]["type"] == plan_draft_service.COMPANY and not ai[1]["flags"]


def test_빈칸_합치기는_절_이름을_붙이고_메모는_합치지_않는다() -> None:
    """2차 검수 F3 — 기업 현황의 대표자가 일반 현황에 흡수돼 사라졌고, 담당자 메모는 첫 것만 남았다."""
    merged = plan_draft_service._merge_blanks([
        {"field": "대표자", "why": "사람만 채우는 칸", "section": "일반 현황"},
        {"field": "대표자", "why": "사람만 채우는 칸", "section": "기업 현황"},
        {"field": "담당자 확인", "why": "메모 하나", "section": "기업(팀) 역량"},
        {"field": "담당자 확인", "why": "메모 둘", "section": "기업(팀) 역량"},
        {"field": "연락처", "why": "담당자만 채우는 칸이라 AI가 쓴 값을 비웠습니다", "section": "추진 계획"},
        {"field": "연락처", "why": "사람만 채우는 칸", "section": "일반 현황"},
    ])
    assert merged[0] == {"field": "대표자", "why": "사람만 채우는 칸", "section": "일반 현황 · 기업 현황"}
    assert [b["why"] for b in merged if b["field"] == "담당자 확인"] == ["메모 하나", "메모 둘"]
    assert [b["section"] for b in merged if b["field"] == "연락처"] == ["추진 계획", "일반 현황"]


def test_못_고친_약점의_절_키는_제목으로(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """2차 검수 F4 — 「S2-9에서 …」는 담당자가 어느 절인지 모른다."""
    units = {u["title"]: u["key"] for u in plan_draft_service.form_units(form)}

    def _reply(purpose: str, n: int):
        if purpose == "plan_draft:review":
            return plan_draft_service.PlanReviewOut(weaknesses=[
                plan_draft_service.ReviewWeakness(unit_key=units["추진 계획"], eval_item="구체성", weakness="일정이 얕다"),
                plan_draft_service.ReviewWeakness(unit_key=units["기술 등 경쟁력"], eval_item="차별성", weakness="비교가 없다"),
                # 30차 — 고쳐 쓰기는 두 절까지라 셋째 약점은 메모로 남는다
                plan_draft_service.ReviewWeakness(unit_key=units["사업화 방안"], eval_item="지속 가능성",
                                                  weakness=f"{units['집행 계획']}에서 서버를 시범 기간에만 빌린다"),
            ])
        return PlanSectionOut()

    ai_on(monkeypatch, _reply)
    draft = run(select_task(form), requirements)
    assert draft["review_notes"] == [{"section": "사업화 방안", "items": ["[지속 가능성] 「집행 계획」에서 서버를 시범 기간에만 빌린다"]}]


def test_채택_회사자료는_evidence_id_로도_가리킨다(form: dict) -> None:
    """2차 검수 QUAL-1 — 실제 채택 자료에는 id 대신 evidence_id 가 있어 source_id 가 모두 「None」이었다."""
    unit = next(u for u in plan_draft_service.form_units(form) if u["title"] == "기업(팀) 역량")
    matches = [{"evidence_id": "ev-1", "document_name": "회사소개서.pdf", "text": "본문 — 보내지 않음", "selected": True}]
    bundle = plan_draft_service.build_bundle(unit, form=select_task(form), clauses=[], company=COMPANY, facts=FACTS, matches=matches, annex=None)
    payload = plan_draft_service.llm_payload(bundle)
    assert payload["company"]["documents"] == [{"source_id": "ev-1", "document_name": "회사소개서.pdf"}]
    assert plan_draft_service.source_texts(bundle)["ev-1"] == "회사소개서.pdf"
    assert "본문 — 보내지 않음" not in json.dumps(payload, ensure_ascii=False)


def test_회사_소개_조각은_역량_절에만(form: dict) -> None:
    """2차 검수 Q3 · 3차 시험 실행 — 같은 회사 소개 문장(설립 · 사업영역)이 여덟 절을 열었다."""
    units = {u["title"]: u for u in plan_draft_service.form_units(form)}

    def company_of(title: str) -> dict:
        bundle = plan_draft_service.build_bundle(units[title], form=select_task(form), clauses=[], company=COMPANY, facts=FACTS, matches=[], annex=None)
        return plan_draft_service.llm_payload(bundle)["company"]

    solve, team = company_of("과제 해결방안"), company_of("기업(팀) 역량")
    assert solve["business_domains"] is None and not solve["certifications"] and solve["founded_year"] is None and not solve["credentials"]
    # 활동 지역도 역량 절에만 — 27차 검수 D4: 표준 양식 초안에서 일곱 절의 회사 근거가 이 한 줄이었다(예전 기대: 모든 절).
    assert solve["activity_regions"] is None
    assert team["activity_regions"]["values"] == ["광주광역시"]
    assert team["business_domains"]["values"] and team["certifications"] and team["founded_year"]["value"] == 2021 and team["credentials"]


# ---------------------------------------------------------------------------
# 8) 26차 ISSUE-143 — 공고 근거 문장을 자기 인용과 대조한다
# ---------------------------------------------------------------------------


def _money_clause(form: dict, requirements) -> dict:
    units = plan_draft_service.form_units(form)
    routed = plan_draft_service.route_clauses(units, requirements)
    budget = next(u for u in units if u["title"] == "집행 계획")
    return next(c for c in routed[budget["key"]] if "1억원" in c["text"])


def test_공고_근거_문장의_숫자가_인용에_없으면_내린다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """검수자 재현 ① — 「과제별 최대 3억원 지원」이 1억원 조항을 인용한 채 공고 근거(검은 글씨)로 남았다."""
    clause = _money_clause(form, requirements)
    out = PlanSectionOut(sentences=[
        PlanSentenceOut(text=f"공고는 「{clause['text']}」에 따라 과제별 최대 3억원을 지원합니다.", type="RFP_GROUNDED",
                        source=clause["text"], source_ids=[clause["id"]]),
        # 통과해야 하는 것 — 인용이 문장에 그대로 있고 숫자가 같다.
        PlanSentenceOut(text=f"공고는 「{clause['text']}」을 제공합니다.", type="RFP_GROUNDED", source=clause["text"], source_ids=[clause["id"]]),
    ])
    ai_on(monkeypatch, _one_unit_reply("집행 계획", out))
    draft = run(select_task(form), requirements)
    ai = [s for s in next(s for s in draft["sections"] if s["section"] == "집행 계획")["sentences"] if s.get("ai")]
    assert ai[0]["type"] == plan_draft_service.SUGGESTION and ai[0]["flags"] == [f"{plan_draft_service.FLAG_NOTICE_VALUES}: 3억원 — 확인하세요"]
    assert ai[1]["type"] == plan_draft_service.NOTICE and not ai[1]["flags"]


def test_인용과_무관한_계획에_조항을_달아도_내린다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """검수자 재현 ② — 500개 학교 계획에 60점 조항을 인용해 달면 인용 길이만 세어 통과했다."""
    cutoff = "선정 규모와 관계없이 취득 점수가 60점 미만일 경우 선정 대상에서 제외"
    out = PlanSectionOut(sentences=[
        PlanSentenceOut(text="우리는 협약 기간 안에 서울 관내 500개 학교에 점검 시스템을 보급합니다.", type="RFP_GROUNDED",
                        source=cutoff, source_ids=["eval:1"]),
        # 숫자가 없어도 인용이 문장에 없으면 덮었다고 세지 않는다.
        PlanSentenceOut(text="우리는 학교 담당자와 함께 점검 방식을 새로 설계합니다.", type="RFP_GROUNDED", source=cutoff, source_ids=["eval:1"]),
    ])
    ai_on(monkeypatch, _one_unit_reply("과제 해결방안", out))
    draft = run(select_task(form), requirements)
    ai = [s for s in next(s for s in draft["sections"] if s["section"] == "과제 해결방안")["sentences"] if s.get("ai")]
    assert ai[0]["type"] == plan_draft_service.SUGGESTION and ai[0]["flags"] == [f"{plan_draft_service.FLAG_NOTICE_VALUES}: 500개 — 확인하세요"]
    assert ai[1]["type"] == plan_draft_service.SUGGESTION and ai[1]["flags"] == ["공고에 없는 내용입니다 — AI가 덧붙였으니 확인하세요"]


def test_회사_조각에서만_찾은_인용은_공고_근거가_아니다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """검수자 재현 ③ — ledger 제목을 인용으로 단 「500명」 문장이 공고 근거로 남았다(COMPANY 로 달면 내려갔다)."""
    title = "공공데이터 활용 AI 교육 과정 운영"
    out = PlanSectionOut(sentences=[
        PlanSentenceOut(text=f"「{title}」으로 500명을 교육했습니다.", type="RFP_GROUNDED", source=title, source_ids=["ledger:7"]),
        # 통과해야 하는 것 — 과제 기관명을 인용으로 단 문장.
        PlanSentenceOut(text="서울특별시 강남서초교육지원청이 제시한 「학교 에너지·탄소 통합관리 및 모니터링 시스템 개발」이 목표입니다.",
                        type="RFP_GROUNDED", source="학교 에너지·탄소 통합관리 및 모니터링 시스템 개발", source_ids=["task:3"]),
    ])
    ai_on(monkeypatch, _one_unit_reply("기업(팀) 역량", out))
    draft = run(select_task(form), requirements)
    ai = [s for s in next(s for s in draft["sections"] if s["section"] == "기업(팀) 역량")["sentences"] if s.get("ai")]
    assert ai[0]["type"] == plan_draft_service.SUGGESTION and ai[0]["flags"] == [plan_draft_service.FLAG_NOTICE_NOT_FOUND]
    assert ai[1]["type"] == plan_draft_service.NOTICE and not ai[1]["flags"]


def test_근거_없는_값의_표시는_사람이_쓰는_금액_모양() -> None:
    from app.services import plan_validation

    assert plan_validation.won_label(300_000_000) == "3억원"
    assert plan_validation.won_label(50_000_000) == "5,000만원"
    assert plan_validation.won_label(3_448_000) == "3,448,000원"


# ---------------------------------------------------------------------------
# 9) 26차 ISSUE-147 · 148 — 반영 셈과 과제 선택 저장
# ---------------------------------------------------------------------------


def test_제외_조항은_반영_셈에서_빠진다(form: dict, requirements) -> None:
    """ISSUE-147 — 초안이 싣지 않는 제외 조항이 「초안에 반영되지 않은 공고문 조항」으로 영원히 남았다(126482 는 6건)."""
    from app.services import support_application_service

    assert requirements.of("exclusion"), "픽스처 공고에 제외 조항이 있어야 이 검사가 뜻을 갖는다"
    draft = run(select_task(form, 4), requirements)
    uncovered = support_application_service._uncovered_from_draft(draft, requirements)
    assert uncovered == []
    program = SimpleNamespace(attachments=[], apply_period_kind="fixed", apply_period_text="2026. 9. 15. ~ 10. 6.")
    checks = support_application_service.pre_submit_checks({}, program, uncovered=uncovered, document_read=True)
    assert not any("반영되지 않은" in c for c in checks)


def _plan_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, requirements) -> Any:
    """POST /plan-draft 를 픽스처 공고 · 가상 회사 · tmp 저장소로 — 네트워크 · data/private 없이."""
    from fastapi.testclient import TestClient

    from app.api import insights
    from app.main import app
    from app.services import bizinfo_document_store, eligibility_engine, support_application_service

    async def _build(*_a, **_kw):
        return {"draft_outline": [], "evidence_matches": []}

    async def _find(*_a, **_kw):
        return PROGRAM, None, "sample"

    monkeypatch.setattr(support_application_service, "build", _build)
    monkeypatch.setattr(support_application_service, "find_program", _find)
    monkeypatch.setattr(plan_form_service, "build_form", lambda _pid: plan_form_service.extract_form("bizinfo-PBLN_000000000126482", FULL))
    monkeypatch.setattr(plan_form_service, "_form_path", lambda _ctx, _pid: tmp_path / "plan_form.json")
    monkeypatch.setattr(plan_form_service, "annex_excerpt", lambda *_a, **_kw: None)
    monkeypatch.setattr(support_plan_service, "draft_dir", lambda _ctx, _pid: tmp_path)
    monkeypatch.setattr(support_requirement_extractor, "load", lambda *_a, **_kw: requirements)
    monkeypatch.setattr(bizinfo_document_store, "load_text", lambda *_a, **_kw: FULL)
    monkeypatch.setattr(plan_draft_service, "company_sources", lambda *_a, **_kw: COMPANY)
    monkeypatch.setattr(eligibility_engine, "company_facts_for", lambda *_a, **_kw: eligibility_engine.CompanyFacts())
    monkeypatch.setattr(insights, "_plan_form_view", lambda _ctx, _pid, form: form)
    return TestClient(app)


def _seed_llm_draft_for_task(tmp_path: Path, form: dict, no: int) -> None:
    context = SimpleNamespace(organization_id="org-sample", evidence_scope="internal")  # 저장 자리는 tmp 로 바꿔 둠
    plan_form_service.save_form(context, "bizinfo-P", select_task(form, no))
    support_plan_service.save(
        {"generated_by": "llm", "provider": "claude_cli", "executed_at": "2026-09-28T10:00:00+00:00",
         "selected_task": select_task(form, no)["selected_task"], "sections": [{"section": "과제 해결방안", "sentences": []}]},
        context=context, program_id="bizinfo-P",
    )


def test_옛_AI_초안을_유지하면_과제_선택도_그대로(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, form: dict, requirements) -> None:
    """ISSUE-148 — 과제 선택을 먼저 저장해 「3번을 골랐습니다」 옆에 4번 과제의 AI 초안이 붙었다."""
    client = _plan_api(monkeypatch, tmp_path, requirements)
    _seed_llm_draft_for_task(tmp_path, form, 4)

    response = client.post("/api/support-programs/bizinfo-P/plan-draft?organization_id=org-sample", json={"task_no": 3})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kept_llm_draft"] is True and body["generated_by"] == "llm"
    assert body["kept_reason"] == "AI 꺼짐"
    assert body["form"]["selected_task"]["no"] == 4  # 유지한 AI 초안의 과제
    context = SimpleNamespace(organization_id="org-sample", evidence_scope="internal")
    assert plan_form_service.load_saved(context, "bizinfo-P")["selected_task"]["no"] == 4

    # 새 초안이 실제로 저장되면(규칙 초안으로 바꾸기) 그때 과제 선택도 저장한다.
    response = client.post("/api/support-programs/bizinfo-P/plan-draft?organization_id=org-sample", json={"task_no": 3, "force_rules": True})
    assert response.json()["kept_llm_draft"] is False and "kept_reason" not in response.json()
    assert plan_form_service.load_saved(context, "bizinfo-P")["selected_task"]["no"] == 3


def test_AI_를_켰는데_절이_전부_실패하면_사유가_응답에(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, form: dict, requirements) -> None:
    """ISSUE-148 — 한도 · 시간 초과로 절이 전부 실패해 규칙으로 떨어지면 옛 AI 초안만 보이고 이유가 사라졌다."""
    client = _plan_api(monkeypatch, tmp_path, requirements)
    _seed_llm_draft_for_task(tmp_path, form, 4)
    ai_on(monkeypatch, lambda purpose, n: llm_client.LLMUnavailableError("Claude 사용 한도에 걸렸습니다 — 몇 시간 뒤 다시 시도하세요"))

    body = client.post("/api/support-programs/bizinfo-P/plan-draft?organization_id=org-sample", json={"task_no": 4}).json()
    assert body["kept_llm_draft"] is True
    assert body["kept_reason"] == "AI 작성 실패: Claude 사용 한도에 걸렸습니다 — 몇 시간 뒤 다시 시도하세요"


# ---------------------------------------------------------------------------
# 10) 26차 ISSUE-152 — 초안 검증 잔여 일곱
# ---------------------------------------------------------------------------


def test_고친_판이_채운_사업비_표도_상한과_합계를_잰다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """① 첫 판 사업비 표가 비고 검토 뒤 고친 판이 채우면 by 가 「rules」로 남아 상한 · 합계 검사를 건너뛰었다."""
    units = {u["title"]: u["key"] for u in plan_draft_service.form_units(form)}
    seen: list[str] = []

    def _reply(purpose: str, n: int):
        if purpose == "plan_draft:review":
            return plan_draft_service.PlanReviewOut(weaknesses=[
                plan_draft_service.ReviewWeakness(unit_key=units["집행 계획"], eval_item="구체성", weakness="사업비가 비었다")])
        if purpose == "plan_draft:집행 계획":
            seen.append(purpose)
            if len(seen) == 2:
                return PlanSectionOut(tables=PlanTablesOut(budget=[
                    BudgetRowOut(item="인건비", basis="개발 인력", amount_krw=100_000_000),
                    BudgetRowOut(item="외주용역비", basis="데이터 가공", amount_krw=50_000_000),
                    BudgetRowOut(item="합계", basis="", amount_krw=120_000_000),
                ]))
        return PlanSectionOut()

    ai_on(monkeypatch, _reply)
    draft = run(select_task(form), requirements)
    budget = draft["validation"]["budget"]
    assert len(seen) == 2 and budget is not None
    assert budget["total_krw"] == 150_000_000 and budget["over_cap"] and budget["total_mismatch"]


def test_한국어_금액을_원_단위_한_값으로_읽는다() -> None:
    """② 「5천만원 · 1억 5천만원」을 숫자로 못 읽어 근거 대조 · 사업비 셈을 빠져나갔다."""
    from app.services import plan_validation

    keys = plan_validation.number_keys("5천만원 · 3백만원 · 2천만 원 · 1억 5천만원 · 1억 2,000만원")
    assert keys == {("won", 50_000_000.0), ("won", 3_000_000.0), ("won", 20_000_000.0), ("won", 150_000_000.0), ("won", 120_000_000.0)}
    assert plan_validation.won("1억 5천만원") == 150_000_000 and plan_validation.won("5천만원") == 50_000_000
    assert plan_validation.won("7,000,000") == 7_000_000 and plan_validation.won("1억원") == 100_000_000


def test_사람_칸은_실제로_지운_것이_있을_때만_적는다() -> None:
    """③ 「5천만원」을 못 지우는데도 「지웠다」고 적었다."""
    from app.services import plan_validation

    assert plan_validation.strip_human_fields("매출은 5천만원입니다") == ("매출은 (담당자 입력)입니다", ["매출액·고용인원"])
    assert plan_validation.strip_human_fields("2027년까지 매출 확대를 목표로 3단계로") == ("2027년까지 매출 확대를 목표로 3단계로", [])


def test_제어문자가_있어도_DOCX_를_만든다(form: dict, requirements) -> None:
    """④ XML 에 쓸 수 없는 제어문자(\\x0b)가 있으면 DOCX 가 500 이 됐다. python-docx 로 다시 열어 글이 남았는지 본다(28차 — HWPX 없앰)."""
    import io

    from docx import Document

    from app.services import plan_export_service

    chosen = select_task(form)
    draft = run(chosen, requirements)
    solve = next(s for s in draft["sections"] if s["section"] == "과제 해결방안")
    solve["sentences"].append({"text": "세로\x0b탭과\x01제어문자", "type": plan_draft_service.SUGGESTION, "ai": True, "flags": []})
    draft["tables"][0]["rows"] = [["가\x0c나"] * len(draft["tables"][0]["columns"])]
    docx = plan_export_service.build_docx(draft, chosen, title="초안")
    assert docx[:2] == b"PK"
    text = "\n".join(p.text for p in Document(io.BytesIO(docx)).paragraphs)
    assert "세로탭과제어문자" in text
    assert "\x0b" not in text and "\x01" not in text


def test_양식_자리표시는_빈칸으로_바꾸고_센다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """⑤ form_examples.raw(0000.00.00 · 000 …)를 아무도 읽지 않아 자리표시가 초안에 그대로 남았다."""
    assert "0000.00.00." in form["form_examples"]["raw"] and "000" in form["form_examples"]["raw"]  # 양식은 끝에 점이 있다
    out = PlanSectionOut(
        sentences=[PlanSentenceOut(text="개업일은 0000.00.00 이고 인력 000 명으로 1,000원 단위 예산을 씁니다.", type="AI_SUGGESTION")],
        tables=PlanTablesOut(schedule=[ScheduleRowOut(task="착수 0000.00.00", period="협약일 ~ 2026.12", detail="연락 062-000-1234")]),
    )
    ai_on(monkeypatch, _one_unit_reply("추진 계획", out))
    draft = run(select_task(form), requirements)
    section = next(s for s in draft["sections"] if s["section"] == "추진 계획")
    text = next(s["text"] for s in section["sentences"] if s.get("ai"))
    assert "0000.00.00" not in text and " 000 " not in text and "1,000원" in text
    schedule = next(t for t in draft["tables"] if t["key"] == "schedule")["rows"][0]
    assert schedule[0] == f"착수 {HUMAN_INPUT}" and "062-000-1234" not in schedule[2]  # 연락처는 사람 칸으로 지운다
    assert draft["validation"]["examples"] >= 3


def test_점검표는_규칙_사실_줄을_본문으로_세지_않는다(form: dict, requirements) -> None:
    """⑥ 규칙 사실 줄(창업 연차)을 본문으로 세어 규칙 초안이 「양식 2/8」로 나왔다."""
    from app.services import plan_completeness_service

    chosen = select_task(form, 4)
    draft = run(chosen, requirements)
    assert any(s.get("fact") for sec in draft["sections"] for s in sec["sentences"])
    with_body = sum(1 for sec in draft["sections"] if sec["kind"] == "item" and not sec["optional"]
                    and any(plan_completeness_service._content(s) for s in sec["sentences"]))
    check = plan_completeness_service.plan_completeness(draft, chosen)
    assert check["form"]["items_filled"] == with_body == 0


def test_남은_시간을_호출마다_넘기고_30초_미만이면_부르지_않는다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """⑦ 「한 벌 5분 상한」이 실제로는 「5분 뒤 새 호출 안 함」이었다 — 이미 나간 호출은 180초씩 더 돌았다."""
    timeouts: dict[str, float] = {}
    monkeypatch.setattr(plan_draft_service, "llm_ready", lambda: (True, None))

    def _fake(**kwargs):
        timeouts[kwargs["purpose"]] = kwargs["timeout"]
        return plan_draft_service.PlanReviewOut() if kwargs["purpose"] == "plan_draft:review" else PlanSectionOut()

    monkeypatch.setattr(llm_client, "complete_structured", _fake)
    # 시작 0초 · 추진 계획 100초(남은 상한 - 100초) · 나머지 절 상한 - 20초(남은 20초 → 부르지 않음) — 44차 M2 상한 270초
    limit = plan_draft_service.TIME_LIMIT_SECONDS
    ticks = iter([0.0, 100.0] + [limit - 20.0] * 200)
    draft = run(select_task(form), requirements, clock=lambda: next(ticks))
    assert timeouts == {"plan_draft:추진 계획": limit - 100.0}
    reasons = [s["llm_error"] for s in draft["sections"] if s["llm_error"]]
    assert len(reasons) == 7 and all("시간 상한" in r for r in reasons)


def test_두_자리_연도는_네_자리와_같은_해로_읽는다() -> None:
    """26차 §4-J 시험 — 「’27년 3월」 · 「2027년 3월」이 공고 「협약일～’27.3월」과 다르다며 「27년」 · 「2027년」으로 내려갔다(오탐)."""
    from app.services import plan_validation

    quote = ["협약일～’27.3월(5개월)"]
    assert plan_validation.unsupported_bits("협약 기간은 협약일부터 ’27년 3월까지 5개월입니다.", quote, orgs=False) == []
    assert plan_validation.unsupported_bits("협약기간은 협약일부터 2027년 3월까지 5개월로 끝냅니다.", quote, orgs=False) == []
    # 정말 다른 값은 그대로 잡는다.
    assert plan_validation.unsupported_bits("협약일부터 ’28년 3월까지 5개월입니다.", quote, orgs=False) == ["2028년"]
    assert plan_validation.unsupported_bits("협약일부터 2027년 3월까지 7개월입니다.", quote, orgs=False) == ["7개월"]


# ---------------------------------------------------------------------------
# 11) 26차 변경분 독립 검수에서 나온 것(DV-1~7 · 옛 뼈대 경로)
# ---------------------------------------------------------------------------


def test_공고_근거_대조는_월과_개수도_본다() -> None:
    """DV-1 — 「최종 보고 ’27.5월」 · 「학교 5곳」 · 「1억 5천」이 인용을 달고 검은 글씨로 나갔다."""
    from app.services import plan_validation

    period = ["협약일～’27.3월(5개월)"]
    money = ["자금 (과제별 최대 1억원) 및 후속 연계 지원"]
    assert plan_validation.unsupported_bits("「협약일～’27.3월(5개월)」, 최종 보고 ’27.5월", period, orgs=False) == ["5월"]
    assert plan_validation.unsupported_bits("「자금 (과제별 최대 1억원) 및 후속 연계 지원」, 학교 5곳에서 실증", money, orgs=False) == ["5곳"]
    assert plan_validation.unsupported_bits("과제별 최대 1억 5천 지원", ["과제별 최대 1억원"], orgs=False) == ["1억 5,000만원"]
    # 같은 값의 다른 모양 · 강조 따옴표는 그대로 통과(DV-6).
    assert plan_validation.unsupported_bits("협약 기간은 협약일부터 ’27년 3월까지 5개월입니다.", period, orgs=False) == []
    assert plan_validation.unsupported_bits("당사는 창업 ‘7년 이내’ 요건을 충족합니다", ["「창업 7년 이내」 요건"], orgs=False) == []
    assert plan_validation.unsupported_bits("업력 ‘10년 이상’ 기업", ["업력 10년 이상 기업"], orgs=False) == []
    assert plan_validation.unsupported_bits("만족도 ‘90.5점’ 달성", ["만족도 90.5점"], orgs=False) == []


def _notice_sentence(monkeypatch, form, requirements, section: str, sentence: PlanSentenceOut) -> dict:
    ai_on(monkeypatch, _one_unit_reply(section, PlanSectionOut(sentences=[sentence])))
    draft = run(select_task(form), requirements)
    return next(s for s in next(x for x in draft["sections"] if x["section"] == section)["sentences"] if s.get("ai")), draft


def test_같은_인용을_두_번_달아도_덮음은_한_번(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """DV-2 — 「조항 / 조항」 · 「조항 / 과제별 최대 1억원 / 1억원」으로 같은 글자를 두세 번 세어 계획 문장이 공고 근거로 남았다."""
    clause = _money_clause(form, requirements)
    text = f"「{clause['text']}」에 맞춰 우리는 AI 튜터 서비스를 새로 설계하고 운영합니다."
    for source in (clause["text"], f"{clause['text']} / {clause['text']}", f"{clause['text']} / 과제별 최대 1억원 / 1억원"):
        s, _ = _notice_sentence(monkeypatch, form, requirements, "집행 계획",
                                PlanSentenceOut(text=text, type="RFP_GROUNDED", source=source, source_ids=[clause["id"]]))
        assert s["type"] == plan_draft_service.SUGGESTION and s["flags"] == ["공고에 없는 내용입니다 — AI가 덧붙였으니 확인하세요"], source


def test_공고_자격_조항의_기준값은_사람_칸으로_지우지_않는다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """DV-3 — 「직전년도 매출액 5천만원 이상」을 인용한 문장에서 공고의 기준값이 「(담당자 입력)」이 되고 거짓 빈칸이 남았다."""
    from app.services import plan_validation

    quote = "직전년도 매출액 5천만원 이상 기업"
    assert plan_validation.strip_human_fields(f"공고 요구: 「{quote}」", keep=[quote]) == (f"공고 요구: 「{quote}」", [])
    # 지키지 않은 부분(회사 매출)은 여전히 지운다.
    assert plan_validation.strip_human_fields(f"「{quote}」이고 당사 매출은 3억원입니다.", keep=[quote]) == (
        f"「{quote}」이고 당사 매출은 {HUMAN_INPUT}입니다.", ["매출액·고용인원"])


def test_숫자로_내린_문장도_인용은_복사로_세지_않는다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """DV-4 — 숫자 대조로만 내린 문장이 「공고 문장 복사」로도 찍혀 복사 셈이 부풀었다."""
    cutoff = "선정 규모와 관계없이 취득 점수가 60점 미만일 경우 선정 대상에서 제외"
    s, draft = _notice_sentence(monkeypatch, form, requirements, "과제 해결방안",
                                PlanSentenceOut(text=f"「{cutoff}」되므로 70점을 넘깁니다.", type="RFP_GROUNDED", source=cutoff, source_ids=["task:3"]))
    assert s["flags"] == [f"{plan_draft_service.FLAG_NOTICE_VALUES}: 70점 — 확인하세요"] and draft["validation"]["copy"] == 0


def test_인용이_없고_기관명만_있으면_공고_근거가_아니다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """DV-5 — 과제 기관명 길이만으로 절반을 넘겨 인용 없는 계획 문장이 공고 근거로 남았다."""
    s, _ = _notice_sentence(monkeypatch, form, requirements, "과제 해결방안", PlanSentenceOut(
        text="서울특별시 강남서초교육지원청과 매주 협력합니다.", type="RFP_GROUNDED",
        source="학교 에너지·탄소 통합관리 및 모니터링 시스템 개발", source_ids=["task:3"]))
    assert s["type"] == plan_draft_service.SUGGESTION and s["flags"] == ["공고에 없는 내용입니다 — AI가 덧붙였으니 확인하세요"]


def test_금액을_지워도_뒤_공백은_남긴다() -> None:
    """DV-7 — 「매출 3억 규모로」가 「매출 (담당자 입력)규모로」로 붙었다."""
    from app.services import plan_validation

    assert plan_validation.strip_human_fields("매출 3억 규모로 성장") == (f"매출 {HUMAN_INPUT} 규모로 성장", ["매출액·고용인원"])
    assert plan_validation.number_keys("3억 원 · 3억원") == {("won", 300_000_000.0)}


def test_초안이_없을_때_뼈대_경로도_제외_조항을_세지_않는다(requirements) -> None:
    """검수 R26-D-OUTLINE-EXCL — 저장된 초안이 없으면 뼈대 경로가 여전히 제외 조항을 「반영 안 됨」으로 셌다."""
    from app.services import support_application_service

    assert requirements.of("exclusion")
    missing = support_application_service.uncovered_clauses([], requirements)
    excluded = {(c.source_text or "").strip() for c in requirements.of("exclusion")}
    assert missing and not (set(missing) & excluded)


# ---------------------------------------------------------------------------
# 12) 27차 — 26차 재검증 잔여(R26-01 · 02 · 06~10)
# ---------------------------------------------------------------------------


def test_날짜는_월과_일을_양쪽에서_대조한다() -> None:
    """R26-01 — 「10.8.(목)까지 접수」가 마감 「10.6.(화)」 인용 옆에서 검은 글씨로 남았고, 「10월 6일」 풀어 쓰기는 오탐이었다."""
    from app.services import plan_validation

    deadline = ["2026.9.15.(화) ~ 10.6.(화) 16:00까지"]
    assert plan_validation.unsupported_bits("「2026.9.15.(화) ~ 10.6.(화) 16:00까지」, 10.8.(목)까지 접수", deadline, orgs=False) == ["10월 8일"]
    assert plan_validation.unsupported_bits("10월 6일 16시까지 접수합니다", deadline, orgs=False) == []
    assert plan_validation.unsupported_bits("2026-10-08 접수", deadline, orgs=False) == ["10월 8일"]
    period = ["협약일～’27.3월(5개월)"]
    assert plan_validation.unsupported_bits("최종 보고는 ’27.5.31.까지", period, orgs=False) == ["5월 31일", "5월"]
    assert plan_validation.unsupported_bits("최종 보고는 2027.5.31.까지", period, orgs=False) == ["5월 31일", "5월"]
    # 소수 점수는 날짜가 아니다 — 범위 「4.2~4.5.」도(검수 C9)
    assert plan_validation.date_keys("만족도 90.5점 · 4.5점 척도") == set()
    assert plan_validation.unsupported_bits("목표 만족도는 4.2~4.5.", ["만족도 4.5점 이상"], orgs=False) == []
    # 날짜는 (월, 일) 짝 — 공고에 있는 월과 일을 따로 맞춰 만든 틀린 날짜 · 날짜 속 일을 빌린 기간은 통과하지 못한다(검수 C3 · C22)
    assert plan_validation.unsupported_bits("10.15.(목)까지 접수", ["접수기간 2026.9.15.(화) ~ 10.6.(화)"], orgs=False) == ["10월 15일"]
    assert plan_validation.unsupported_bits("「접수 마감 2026.10.30.(금)」, 결과 30일 내 통보", ["접수 마감 2026.10.30.(금)"], orgs=False) == ["30일"]


def test_짧은_인용_조각은_사람_칸_지우기를_막지_못한다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """R26-02 — 인용 조각 「1억원」이 「당사 매출액은 1억원입니다」의 매출 값을 지키고 있었다."""
    from app.services import plan_validation

    assert not plan_validation.meaningful_quote("1억원") and not plan_validation.meaningful_quote("/ 22개")
    assert plan_validation.meaningful_quote("교육지원청") and plan_validation.meaningful_quote("직전년도 매출액 5천만원 이상")
    s, draft = _notice_sentence(monkeypatch, form, requirements, "과제 해결방안",
                                PlanSentenceOut(text="당사 매출액은 1억원입니다.", type="RFP_GROUNDED", source="1억원", source_ids=["task:3"]))
    assert HUMAN_INPUT in s["text"] and "1억원" not in s["text"]
    assert s["type"] == plan_draft_service.SUGGESTION
    assert s["flags"][0] == plan_draft_service.FLAG_NOTICE_SHORT
    blanks = [b for b in draft["blanks"] if b["field"] == "매출액·고용인원"]
    assert blanks, draft["blanks"]
    # 긴 것부터 가린다 — 짧은 조각이 먼저 긴 인용 일부를 가리지 않는다
    long_quote = "직전년도 매출액 5천만원 이상 기업"
    assert plan_validation.strip_human_fields(f"「{long_quote}」", keep=["5천만원", long_quote]) == (f"「{long_quote}」", [])


def test_숫자만인_인용_조각은_숫자_대조를_통과시키지_않는다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """R26-06 — 「/ 22개」처럼 숫자만인 조각이 공고 어디든 있으면 숫자 대조를 통과했다."""
    s, _ = _notice_sentence(monkeypatch, form, requirements, "과제 해결방안",
                            PlanSentenceOut(text="평가 항목 22개를 모두 충족합니다.", type="RFP_GROUNDED", source="/ 22개", source_ids=["task:3"]))
    assert s["type"] == plan_draft_service.SUGGESTION


@pytest.mark.parametrize(
    ("text", "keys"),
    [
        # R26-07 — 대략 「여」 · 한국어 수 + 개수 단위 · 주 · 인 · 대
        ("학교 500여 곳", {("곳", 500.0)}),
        ("교원 5천 명 대상", {("명", 5000.0)}),
        ("2만여 명", {("명", 20000.0)}),
        ("8주 과정 · 3인 1조 · 노트북 10대", {("주", 8.0), ("명", 3.0), ("대", 10.0)}),
        # R26-08 — 개수 · 천원 · 시각은 금액 · 개수로 잘못 읽지 않는다
        ("1,000곳", {("곳", 1000.0)}),
        ("2만 건", {("건", 20000.0)}),
        ("1만 명", {("명", 10000.0)}),
        ("100,000천원", {("won", 100_000_000.0)}),
        ("16:00 종료", set()),
        # R26-10 — 금액 한 덩어리
        ("3천5백만원", {("won", 35_000_000.0)}),
        ("1억 3천4백만원", {("won", 134_000_000.0)}),
        ("1억 5천원", {("won", 100_005_000.0)}),
        ("1억 5천", {("won", 150_000_000.0)}),
    ],
)
def test_숫자_모양_표(text: str, keys: set) -> None:
    """R26-07 · 08 · 10 — 숫자 모양을 한 표로. 공고 근거 대조가 보는 열쇠(number_keys + 개수 · 날짜)."""
    from app.services import plan_validation

    got = {k for k in plan_validation.number_keys(text) | plan_validation._notice_extra_keys(text) if k[0] != "year"}
    assert got == keys


def test_두_자리_연도는_기간과_다른_열쇠다() -> None:
    """R26-09 — 「업력 10년」이 지어낸 「’10년」 연도를 통과시켰다(같은 열쇠)."""
    from app.services import plan_validation

    assert plan_validation.unsupported_bits("당사는 ’10년에 설립했습니다", ["업력 10년 이상"], orgs=False) == ["2010년"]
    assert plan_validation.unsupported_bits("’27년 3월까지", ["협약일～’27.3월(5개월)"], orgs=False) == []
    assert plan_validation.unsupported_bits("’27년 3월까지", ["2027년 3월"], orgs=False) == []
    # 여는 따옴표 강조는 기간으로 읽을 수 있다(26차 DV-6 그대로)
    assert plan_validation.unsupported_bits("업력 ‘10년 이상’ 기업", ["업력 10년 이상 기업"], orgs=False) == []


def test_유지_사유는_다시_열어도_남는다(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, form: dict, requirements) -> None:
    """R26-15 — 「AI 초안을 유지합니다 — 사유」 줄이 단계를 다시 열면(GET) 사라졌다."""
    client = _plan_api(monkeypatch, tmp_path, requirements)
    _seed_llm_draft_for_task(tmp_path, form, 4)
    client.post("/api/support-programs/bizinfo-P/plan-draft?organization_id=org-sample", json={"task_no": 3})
    body = client.get("/api/support-programs/bizinfo-P/plan-draft?organization_id=org-sample").json()
    assert body["kept_llm_draft"] is True and body["kept_reason"] == "AI 꺼짐"
    context = SimpleNamespace(organization_id="org-sample", evidence_scope="internal")
    assert plan_form_service.load_saved(context, "bizinfo-P")["selected_task"]["no"] == 4  # 과제 선택은 그대로
    # 새 초안이 저장되면 사유도 사라진다
    client.post("/api/support-programs/bizinfo-P/plan-draft?organization_id=org-sample", json={"task_no": 3, "force_rules": True})
    assert "kept_reason" not in client.get("/api/support-programs/bizinfo-P/plan-draft?organization_id=org-sample").json()


def test_같은_초안은_동시에_두_번_만들지_않는다(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, form: dict, requirements) -> None:
    """R26-05 — 쉬운 보기 두 단추 · 두 탭이 같은 초안을 동시에 두 번 만들었다(서버에 막기 없음)."""
    import asyncio
    import threading
    import time as _time

    import httpx

    from app.main import app

    _plan_api(monkeypatch, tmp_path, requirements)
    real = plan_draft_service.generate
    started = threading.Event()

    def slow(**kwargs):
        started.set()
        _time.sleep(1.0)
        return real(**kwargs)

    monkeypatch.setattr(plan_draft_service, "generate", slow)
    url = "/api/support-programs/bizinfo-P/plan-draft?organization_id=org-sample"

    async def scenario() -> tuple[int, int, str]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(client.request("POST", url, json={"task_no": 3}))
            while not started.is_set():
                await asyncio.sleep(0.02)
            second = await client.request("POST", url, json={"task_no": 3})
            done = await first
            return done.status_code, second.status_code, second.json().get("detail", "")

    first, second, detail = asyncio.run(scenario())
    assert first == 200 and second == 409
    assert "이미 만드는 중입니다" in detail


def test_27차_검수_숫자_모양_잔여() -> None:
    """27차 §3-B 독립 검수 C1 · C2 · C4 · C5 · C6 · C7 · C8 · C10 · C11 · C12 · C23 · C25."""
    from app.services import plan_validation

    ub = plan_validation.unsupported_bits
    # C2 · C23 — 다음 낱말의 첫 글자를 개수 단위로 읽지 않는다
    assert ub("지원금 1억 부가세 포함", ["지원금 1억(부가세 포함)"], orgs=False) == []
    assert ub("과제당 5천만 개발비 지원", ["과제당 5천만원 지원"], orgs=False) == []
    assert ub("3억 건물 신축", ["3억원 건물 신축"], orgs=False) == []
    # C1 · C24 — 사람 칸 지우기가 다음 낱말을 먹지 않는다
    assert plan_validation.strip_human_fields("매출액 10억원 회사로 성장")[0] == f"매출액 {HUMAN_INPUT} 회사로 성장"
    assert plan_validation.strip_human_fields("당사 매출액 3억원 부가세 별도")[0] == f"당사 매출액 {HUMAN_INPUT} 부가세 별도"
    assert plan_validation.strip_human_fields("직원 수 5천 명 이상")[0] == f"직원 수 {HUMAN_INPUT} 이상"
    # C4 — 쉼표 금액 뒤 「대비」 · 「인건비」도 금액으로 읽는다
    assert ub("총 50,000,000 대비 자부담", ["총 사업비 3,000,000원"], orgs=True) == ["5,000만원"]
    # C5 — 네 자리 연도는 같은 수의 기간이 있어도 연도다
    assert ub("당사는 2010년부터 10년간 교육 사업을 운영했습니다", ["교육 사업 운영 10년"], orgs=True) == ["2010년"]
    # C6 — 「1,2차」는 12 가 아니다
    assert ub("2차 평가", ["1,2차 평가를 거쳐 선정"], orgs=False) == []
    # C7 — 따옴표 없는 「27년 3월」도 2027년이다
    assert ub("2027년 3월까지", ["협약일~27년 3월"], orgs=False) == []
    # C10 — 「1대1」은 개수가 아니다
    assert ub("1대1 멘토링을 제공합니다", ["1:1 멘토링 제공"], orgs=False) == []
    # C11 — 한국어 수 + 시간 · 점
    assert ub("누적 1만 시간 교육을 운영했습니다", ["누적 교육 10,000시간"], orgs=True) == []
    assert ub("평가 점수 5천 점", ["평가 점수 3,000점"], orgs=False) == ["5,000점"]
    # C12 — 큰 개수는 지수 표기 없이
    assert ub("참여자 100만 명", ["참여자 10만 명"], orgs=False) == ["1,000,000명"]
    # C25 — 닫는 따옴표가 없는 「‘10년」은 연도다(강조 「‘10년 이상’」만 기간으로도 읽는다)
    assert ub("당사는 ‘10년에 설립했습니다", ["업력 10년 이상"], orgs=False) == ["2010년"]
    assert ub("업력 ‘10년 이상’ 기업", ["업력 10년 이상 기업"], orgs=False) == []
    # C8 — 「1억원 규모」 같은 짧은 조각은 회사 매출을 지켜 주지 못한다
    assert plan_validation.strip_human_fields("당사 매출액은 1억원 규모입니다.", keep=["1억원 규모"])[1] == ["매출액·고용인원"]


def test_긴_인용이_먼저_가려져야_인용_안_숫자가_남는다() -> None:
    """검수 C26 (2) — 짧은 조각을 먼저 가리면 긴 인용을 못 찾아 인용 안의 「상시근로자 5명」이 지워졌다(옛 순서)."""
    from app.services import plan_validation

    long_quote = "직전년도 매출액 5천만원 이상, 상시근로자 5명 이상 기업"
    short = "매출액 5천만원 이상"
    assert plan_validation.strip_human_fields(f"「{long_quote}」", keep=[short, long_quote]) == (f"「{long_quote}」", [])


def test_공고에_있는_짧은_조각이_숫자_대조를_통과시키지_않는다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """검수 C26 (1) — 긴 인용과 함께 공고 어딘가의 짧은 숫자 조각을 달면 그 숫자가 근거가 됐다(R26-06 의 길)."""
    cutoff = "선정 규모와 관계없이 취득 점수가 60점 미만일 경우 선정 대상에서 제외"
    s, _ = _notice_sentence(monkeypatch, form, requirements, "과제 해결방안",
                            PlanSentenceOut(text=f"「{cutoff}」되며 평가 항목 22개를 모두 충족합니다.", type="RFP_GROUNDED",
                                            source=f"{cutoff} / 22개", source_ids=["task:3"]))
    assert s["type"] == plan_draft_service.SUGGESTION
    assert s["flags"][0] == f"{plan_draft_service.FLAG_NOTICE_VALUES}: 22개 — 확인하세요"


# ---------------------------------------------------------------------------
# 27차 §3-C-8 — 저장한 샘플에듀 초안 검수에서 확정한 것(D1~D6)
# ---------------------------------------------------------------------------


def _money_only(*kinds: str) -> Any:
    clauses = [SimpleNamespace(detail={"kind": k}) for k in kinds]
    return SimpleNamespace(document_read=True, of=lambda kind: clauses if kind == "money" else [])


def test_무료_현물_지원이면_표준_양식에서_사업비_표와_집행_계획을_뺀다() -> None:
    """D1 · D3 — 무료 컨설팅 · 테스팅 공고에 창업 표준 양식을 씌우자 AI 가 인건비 · 외주용역비 표를 채웠다."""
    text = "광주 SW 품질 테스팅 지원(무료)\n신청방법: 진흥원 누리집 공고게시문 내 첨부서식 작성 후 제출"
    base = plan_form_service.extract_form("PBLN_000000000123852", text)
    assert base["source"] == "standard"
    free = plan_form_service.in_kind_form(base, _money_only("free"), text)
    assert [t["key"] for t in free["tables"]] == ["schedule", "staff"]
    assert all(i["key"] != "S3-3" for s in free["sections"] for i in s["items"])
    assert free["budget"]["mode"] == "in_kind"
    assert plan_form_service.IN_KIND_NOTE in free["notice"] and plan_form_service.ATTACHED_FORM_NOTE in free["notice"]
    # 받는 돈 조항이 하나라도 있으면(한도 · 비율) 무료만의 공고가 아니다 — 그대로 · 공고 양식도 그대로
    paid = plan_form_service.in_kind_form(base, _money_only("free", "cap"), text)
    assert [t["key"] for t in paid["tables"]] == ["schedule", "budget", "staff"] and "mode" not in paid["budget"]
    notice_form = plan_form_service.extract_form("PBLN_000000000126482", FULL)
    assert plan_form_service.in_kind_form(notice_form, _money_only("free")) is notice_form


def test_무료_현물_지원_공고의_사업비_문장은_표시하고_사업비_빈칸은_묻지_않는다() -> None:
    """D1 — 「정부지원금과 자부담을 합친 총액을 넣어 주세요」 빈칸 · 사업비 편성 문장이 검사 없이 나갔다."""
    text = "광주 SW 품질 테스팅 지원(무료)"
    form = plan_form_service.in_kind_form(plan_form_service.extract_form("PBLN_000000000123852", text), _money_only("free"), text)
    unit = next(u for u in plan_draft_service.form_units(form) if u["title"] == "사업화 전략")
    bundle = plan_draft_service.build_bundle(unit, form=form, clauses=[], company=COMPANY, facts=FACTS, matches=[], annex=None)
    out = PlanSectionOut(
        sentences=[
            PlanSentenceOut(text="사업비는 인건비와 외주용역비 위주로 편성합니다.", type="AI_SUGGESTION"),
            PlanSentenceOut(text="테스트 결과를 제품 개선에 반영합니다.", type="AI_SUGGESTION"),
        ],
        blanks=[plan_draft_service.PlanBlankOut(field="총 사업비", why="정부지원금과 자부담을 합친 총액을 넣어 주세요"),
                plan_draft_service.PlanBlankOut(field="시험 대상 제품명", why="담당자가 적는다")],
    )
    sentences, _rows, blanks, _counts = plan_draft_service.validate_unit(out, bundle, form=form, notice=plan_validation.NoticeIndex(text))
    assert plan_draft_service.FLAG_IN_KIND_BUDGET in sentences[0]["flags"]
    assert not sentences[1]["flags"]
    assert [b["field"] for b in blanks] == ["시험 대상 제품명"]


def test_본문_단계_수가_일정표_행_수와_다르면_AI_제안으로(form: dict) -> None:
    """D6 — 추진 계획 본문은 「3단계」인데 바로 아래 일정표는 5행이었다."""
    unit = next(u for u in plan_draft_service.form_units(form) if "schedule" in u.get("tables", []))
    bundle = plan_draft_service.build_bundle(unit, form=select_task(form), clauses=[], company=COMPANY, facts=FACTS, matches=[], annex=None)
    rows = [ScheduleRowOut(task=f"단계 {i}", period="협약일 ~ 2026.12", detail="내용") for i in range(1, 6)]

    def check(sentence: str) -> list[str]:
        out = PlanSectionOut(sentences=[PlanSentenceOut(text=sentence, type="AI_SUGGESTION")], tables=PlanTablesOut(schedule=rows))
        return plan_draft_service.validate_unit(out, bundle, form=form, notice=plan_validation.NoticeIndex(FULL))[0][0]["flags"]

    assert check("사업은 준비, 개발·실증, 사업화의 3단계로 나누어 추진합니다.") == ["본문은 3단계인데 일정표는 5줄입니다 — 맞추세요"]
    assert check("사업은 5단계로 나누어 추진합니다.") == []


def test_검토_요약에_그_절의_AI_표_행을_싣는다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """D5 — 검토에 문장만 보내 제자리에 있는 일정표를 「기간이 없다」고 적었다."""
    prompts: dict[str, str] = {}
    monkeypatch.setattr(plan_draft_service, "llm_ready", lambda: (True, None))

    def _fake(**kwargs):
        prompts[kwargs["purpose"]] = kwargs["user"]
        if kwargs["purpose"] == "plan_draft:review":
            return plan_draft_service.PlanReviewOut()
        if kwargs["purpose"] == "plan_draft:추진 계획":
            return PlanSectionOut(sentences=[PlanSentenceOut(text="단계별로 추진합니다.", type="AI_SUGGESTION")],
                                  tables=PlanTablesOut(schedule=[ScheduleRowOut(task="현황 진단", period="협약일 ~ 2026.12", detail="요구사항 정리")]))
        return PlanSectionOut()

    monkeypatch.setattr(llm_client, "complete_structured", _fake)
    run(select_task(form), requirements)
    # 2.7.0 — 검토 본문은 원문 경계 표식(`llm_client.fenced`) 안에 담는다 · 표식 줄을 떼고 JSON 을 읽는다
    fenced = prompts["plan_draft:review"].splitlines()
    assert fenced[0].startswith("<<<원문 시작") and fenced[-1].startswith("<<<원문 끝")
    review = json.loads("\n".join(fenced[1:-1]))
    plan = next(d for d in review["draft"] if d["title"] == "추진 계획")
    assert plan["tables"]["schedule"][0][0] == "현황 진단"


def test_점검표는_서로_다른_회사_근거_수를_따로_센다(form: dict) -> None:
    """D4 — 같은 회사 사실 한 줄이 일곱 절에서 되풀이돼 「회사 근거 11」로 부풀었다."""
    one = {"text": "당사의 주요 활동 지역은 광주광역시입니다.", "type": plan_draft_service.COMPANY, "source_ids": ["profile:regions"], "ai": True}
    draft = {"sections": [{"key": f"S{i}", "kind": "item", "section": f"절 {i}", "sentences": [dict(one)]} for i in range(3)], "tables": []}
    grounding = plan_completeness_service.plan_completeness(draft, form)["grounding"]
    assert grounding["company"] == 3 and grounding["company_sources"] == 1


def test_AI_없이_고르면_서버_AI_가_켜져도_부르지_않는다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """29차 R28-01 — 「규칙 초안 만들기(AI 없이)」 · 「규칙 초안으로 바꾸기」는 `no_ai` 로 AI 를 강제로 끈다."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_live", True)
    purposes = ai_on(monkeypatch, lambda purpose, n: _good(purpose, n))
    draft = run(select_task(form), requirements, no_ai=True)
    assert purposes == [] and draft["generated_by"] == "rules"
    assert plan_draft_service.NO_AI_REASON in (draft.get("llm_note") or "")
    # 라우트도 — no_ai 가 use_claude 보다 앞선다(사업계획서 작성 문 잠금도 잡지 않는다)
    from app.api.insights import PlanDraftRequest

    assert PlanDraftRequest(no_ai=True, use_claude=True).no_ai is True


def test_평가위원_채점은_하_절만_한_번_고치고_채점을_남긴다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """29차 §3-C — 검토 호출이 평가 항목별 상 · 중 · 하와 고칠 문장을 돌려주고, 「하」인 절만 고친다(호출 수는 그대로)."""
    units = {u["title"]: u["key"] for u in plan_draft_service.form_units(form)}
    written: list[str] = []

    def _reply(purpose: str, n: int):
        written.append(purpose)
        if purpose == "plan_draft:review":
            return plan_draft_service.PlanReviewOut(scores=[
                plan_draft_service.ReviewScore(eval_item="협업 과제 이해도", grade="하", reason="요구 분석이 얕다", unit_keys=[units["과제 해결방안"]],
                                               fixes=[plan_draft_service.ReviewFix(unit_key=units["과제 해결방안"], sentence="우리 회사는 모델을 만듭니다.", fix="데이터 항목을 밝힌다")]),
                plan_draft_service.ReviewScore(eval_item="지속 가능성", grade="상", reason="수익 모델이 있다", unit_keys=[units["사업화 방안"]]),
            ])
        return _good(purpose, n)

    ai_on(monkeypatch, _reply)
    draft = run(select_task(form), requirements)
    assert written.count("plan_draft:과제 해결방안") == 2 and written.count("plan_draft:사업화 방안") == 1  # 「상」은 고치지 않는다
    assert draft["attempts"]["logical_calls"] <= draft["attempts"]["max_logical_calls"]
    grades = {s["eval_item"]: s for s in draft["review_scores"]}
    assert grades["협업 과제 이해도"]["grade"] == "하" and grades["협업 과제 이해도"]["rewritten"] is True
    assert grades["협업 과제 이해도"]["sections"] == ["과제 해결방안"] and grades["협업 과제 이해도"]["fixes"][0]["fix"] == "데이터 항목을 밝힌다"
    assert grades["지속 가능성"]["rewritten"] is False


def test_쓰기_지시에_평가위원이_보는_것과_목표_분량과_개월차가_간다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """29차 §3-C — 절마다 평가 항목 · 세부 내용 · 탈락 점수 · 목표 분량(본문 7쪽 ÷ 절 수) · 협약 개월 안 개월차 지시."""
    prompts: dict[str, str] = {}
    monkeypatch.setattr(plan_draft_service, "llm_ready", lambda: (True, None))

    def _fake(**kwargs):
        prompts[kwargs["purpose"]] = kwargs["user"]
        return _good(kwargs["purpose"], len(prompts))

    monkeypatch.setattr(llm_client, "complete_structured", _fake)
    run(select_task(form), requirements)
    plan = prompts["plan_draft:추진 계획"]
    # 2.7.0 — 평가 세부 내용은 원문 경계 표식 안(머리줄 · 표식 · 항목 순)
    assert "평가위원이 보는 것(" in plan and "<<<원문 시작: 평가 항목>>>\n「실현 가능성 및 구체성」" in plan and "60점 미만" in plan
    assert "목표 분량: 본문 약 1,312자" in plan  # 7쪽 × 1,500자 ÷ 8절
    assert "협약 기간 5개월 안에서 「1~2개월차」" in plan
    assert "① 현황 → ② 문제 → ③ 해결 방안 → ④ 차별성 → ⑤ 기대 성과" in plan_draft_service.SYSTEM_PROMPT


def test_규칙_사업비_표는_허용_비목마다_산출_근거_한_줄_금액은_빈칸(form: dict) -> None:
    """29차 §3-C — 금액을 지어내지 않고, 산출 근거 칸에 무엇을 적을지 한 줄."""
    table = next(t for t in form["tables"] if t["key"] == "budget")
    items = form["budget"]["allowed_items"]
    rows = plan_draft_service.rule_table({**table, "cap_krw": 100_000_000}, items)["rows"]
    assert [r[0] for r in rows] == [*items, "합계"] and all(r[2] == HUMAN_INPUT for r in rows)
    assert all(r[1].startswith("산출:") for r in rows[:-1]) and rows[-1][1] == "공고 상한 100,000,000원 이하"
    assert plan_draft_service.budget_basis("인건비").startswith("산출: 인원 × 월 급여")


def test_품질_확인_규칙_자체_기재_역량_빈칸_표기_공고_줄_되풀이_평가자_말투(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """29차 §3-C 품질 확인 — Q3 자체 기재 역량을 「검증된」으로 쓰면 내린다 · Q6 빈칸 표기 하나 · Q7 약점 고백은 빈칸 · Q9 공고 줄 되풀이는 뺀다."""
    company = {**COMPANY, "capacity": {"skills": [{"name": "AI 에이전트 개발", "level": "proven"}]}}

    def _reply(purpose: str, n: int):
        if purpose == "plan_draft:review":
            return plan_draft_service.PlanReviewOut()
        if purpose == "plan_draft:기업(팀) 역량":
            return PlanSectionOut(sentences=[
                PlanSentenceOut(text="당사는 검증된 AI 에이전트 개발 역량을 보유합니다.", type="COMPANY_EVIDENCE_GROUNDED", source_ids=["skill:AI 에이전트 개발"]),
                PlanSentenceOut(text="해당 실적만으로 전문성을 입증할 수는 없습니다.", type="AI_SUGGESTION"),
                PlanSentenceOut(text="목표 정합률은 「(담당자 입력)」입니다.", type="AI_SUGGESTION"),
            ])
        return PlanSectionOut()

    ai_on(monkeypatch, _reply)
    draft = run(select_task(form), requirements, company=company)
    team = next(s for s in draft["sections"] if s["section"] == "기업(팀) 역량")
    ai = {s["text"]: s for s in team["sentences"] if s.get("ai")}
    verified = ai["당사는 검증된 AI 에이전트 개발 역량을 보유합니다."]
    assert verified["type"] == plan_draft_service.SUGGESTION and plan_draft_service.FLAG_SELF_CLAIM in verified["flags"]
    assert "해당 실적만으로 전문성을 입증할 수는 없습니다." not in ai  # 본문이 아니라 담당자 확인
    assert any(b["field"] == "담당자 확인" and "입증" in b["why"] for b in draft["blanks"])
    assert "목표 정합률은 (담당자 입력)입니다." in ai
    quotes = [{"text": "공고 요구: 「자금(과제별 최대 1억원) 및 후속 연계 지원」", "source": "자금(과제별 최대 1억원) 및 후속 연계 지원", "notice_quote": True}]
    echo = [{"text": "자금(과제별 최대 1억원) 및 후속 연계 지원", "type": plan_draft_service.NOTICE}, {"text": "당사는 데이터를 정리합니다.", "type": plan_draft_service.SUGGESTION}]
    assert [s["text"] for s in plan_draft_service.drop_quote_echo(echo, quotes)] == ["당사는 데이터를 정리합니다."]


# ---------------------------------------------------------------------------
# 30차 §3-B — 내부 말 막기 · 기관 현황 한 줄 · 근거 고르기 · 과제소개서 지시 (Codex 실측 C-02~04)
# ---------------------------------------------------------------------------


def test_30차_본문의_작성_사정은_내려_담당자_확인으로(form: dict) -> None:
    unit = next(u for u in plan_draft_service.form_units(form) if u["title"] == "과제 해결방안")
    bundle = plan_draft_service.build_bundle(unit, form=select_task(form), clauses=[], company=COMPANY, facts=FACTS, matches=[], annex=None)
    out = PlanSectionOut(sentences=[
        PlanSentenceOut(text="과제소개서 발췌만으로 확인할 수 없으므로 데이터 범위는 단정하지 않습니다.", type="AI_SUGGESTION"),
        PlanSentenceOut(text="유사한 개발 이력은 해당없음이다.", type="AI_SUGGESTION"),
        PlanSentenceOut(text="학교 에너지 데이터를 모아 이상 사용을 알립니다.", type="AI_SUGGESTION"),
    ])
    sentences, _rows, blanks, counts = plan_draft_service.validate_unit(out, bundle, form=form, notice=plan_validation.NoticeIndex(FULL))
    assert [s["text"] for s in sentences] == ["학교 에너지 데이터를 모아 이상 사용을 알립니다."]
    assert counts["internal"] == 2
    assert [b["field"] for b in blanks] == ["담당자 확인", "담당자 확인"]


def test_30차_기관_현황_줄은_첫_절에_한_번_과제소개서가_있으면_없음() -> None:
    line = {"text": f"기관 현황 · 문제: {HUMAN_INPUT}", "ai": True}
    body = {"text": "데이터를 모읍니다.", "ai": True}

    def sections():
        return [{"sentences": [dict(line), dict(body)]}, {"sentences": [dict(line)]}, {"sentences": [dict(body), dict(line)]}]

    kept = sections()
    assert plan_draft_service._keep_one_agency_status(kept, has_annex=False) == 2
    assert [len(s["sentences"]) for s in kept] == [2, 0, 1]
    none = sections()
    assert plan_draft_service._keep_one_agency_status(none, has_annex=True) == 3
    assert not any(HUMAN_INPUT in x["text"] for s in none for x in s["sentences"])


def test_30차_역량_절_근거는_과제와_겹치는_원장_행부터_지정_행도(form: dict) -> None:
    """C-04 — 소항목 제목 낱말로만 매겨 「데이터 분석 활용 지원사업」이 밀렸고, 지정 · 저작권 행은 역량 절에 실리지 않았다."""
    def row(seq, year, field, title, summary):
        return {"seq": seq, "year": year, "field": field, "title": title, "agency": "기관", "summary": summary, "external_use": "가능"}

    noise = [row(s, 2025, "AI 교육", f"생성형 AI 강사 파견 {s}", "기업 역량 강화 교육") for s in (1, 2, 3)]
    analysis = row(45, 2022, "기업·재직자·컨설팅", "가상기업 데이터 분석 활용 지원사업", "급식 데이터 분석")
    voucher = row(44, 2023, "지정", "데이터바우처 공급기업 선정", "데이터 가공 공급기업")
    company = {**COMPANY, "ledger": [*noise, analysis], "ledger_all": [*noise, analysis, voucher]}
    task = {"no": 17, "title": "학교 급식 데이터 분석 파이프라인", "agency": "교육청"}
    unit = next(u for u in plan_draft_service.form_units(form) if u["title"] == "기업(팀) 역량")
    bundle = plan_draft_service.build_bundle(unit, form={**form, "selected_task": task}, clauses=[], company=company, facts=FACTS,
                                             matches=[], annex="공공데이터 가공 · 급식 데이터 분석")
    ids = [r["id"] for r in bundle["ledger"]]
    assert ids[:2] == ["ledger:45", "ledger:44"] and len(ids) == 3
    # 보내는 칸은 그대로(금액 · 메모 없음)
    payload = plan_draft_service.llm_payload(bundle)
    assert "amount_thousand_krw" not in json.dumps(payload, ensure_ascii=False)


def test_30차_과제소개서가_있으면_그_글로_쓰라고_없으면_첫_절에만(form: dict) -> None:
    units = plan_draft_service.form_units(form)
    unit = next(u for u in units if u["title"] == "과제 해결방안")
    selected = select_task(form)
    with_annex = plan_draft_service.build_bundle(unit, form=selected, clauses=[], company=COMPANY, facts=FACTS, matches=[], annex="◦ (개요) 급식 데이터")
    assert "과제소개서 발췌(task.annex_excerpt)가 있습니다" in plan_draft_service._unit_prompt(with_annex)
    bare = plan_draft_service.build_bundle(unit, form=selected, clauses=[], company=COMPANY, facts=FACTS, matches=[], annex=None)
    assert "그 줄을 두지 않습니다" in plan_draft_service._unit_prompt(bare)
    assert "이 소항목에만" in plan_draft_service._unit_prompt({**bare, "first_unit": True})


def test_30차_점검표_분량_줄에_문장_평균_최장_가운뎃점(form: dict, requirements) -> None:
    draft = run(select_task(form), requirements)
    section = next(s for s in draft["sections"] if s["section"] == "과제 해결방안")
    section["sentences"] = [{"text": "가" * 40, "type": "AI_SUGGESTION"}, {"text": "나·다·라" + "마" * 125, "type": "AI_SUGGESTION"}]
    length = plan_completeness_service.plan_completeness(draft, form)["length"]
    assert length["sentence_max"] >= 130 and length["over_120"] >= 1 and length["dots"] >= 2 and length["sentence_avg"]


def test_35차_단계_이름표는_가장_큰_번호만_일정표와_견준다(form: dict) -> None:
    """Claude 초안(123852) — 「○ 1단계 준비 · ○ 2단계 개발 …」 넷이 「본문은 1단계인데 일정표는 5줄」처럼 하나씩 잘못 표시됐다."""
    unit = next(u for u in plan_draft_service.form_units(form) if "schedule" in u.get("tables", []))
    bundle = plan_draft_service.build_bundle(unit, form=select_task(form), clauses=[], company=COMPANY, facts=FACTS, matches=[], annex=None)
    labelled = ["○ 1단계 준비: 고객 요구를 정리합니다.", "○ 2단계 개발: 기능을 고도화합니다.", "그 뒤 결과를 정리합니다."]

    def flags(rows: int) -> list[list[str]]:
        schedule = [ScheduleRowOut(task=f"단계 {i}", period="1~2개월차", detail="내용") for i in range(1, rows + 1)]
        out = PlanSectionOut(sentences=[PlanSentenceOut(text=t, type="AI_SUGGESTION") for t in labelled], tables=PlanTablesOut(schedule=schedule))
        return [s["flags"] for s in plan_draft_service.validate_unit(out, bundle, form=form, notice=plan_validation.NoticeIndex(FULL))[0]]

    assert flags(5) == [[], ["본문은 2단계인데 일정표는 5줄입니다 — 맞추세요"], []]
    assert flags(2) == [[], [], []]


def test_35차_무료_현물_공고의_검토_권고에서_사업비_말은_뺀다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """Claude 초안(123852 · 무료 컨설팅 · 테스팅) 검토 메모가 「단계별 소요 예산(정부지원금 · 자부담)을 표로 덧붙인다」고 권했다."""
    units = {u["title"]: u["key"] for u in plan_draft_service.form_units(form)}
    fix = plan_draft_service.ReviewFix

    def _reply(purpose: str, n: int):
        if purpose == "plan_draft:review":
            # 「하」 고쳐 쓰기는 두 절까지 · 팀 구성 → 이해도 먼저 — 사업화 방안의 고침은 메모로 남는다
            return plan_draft_service.PlanReviewOut(scores=[
                plan_draft_service.ReviewScore(eval_item="지속 가능성", grade="하", reason="일정이 비었다", unit_keys=[units["사업화 방안"]], fixes=[
                    fix(unit_key=units["사업화 방안"], sentence="단계별로 실행합니다.", fix="단계별 소요 예산(정부지원금·자부담)을 표로 덧붙입니다"),
                    fix(unit_key=units["사업화 방안"], sentence="단계별로 실행합니다.", fix="일정표 기간 칸을 채웁니다"),
                ]),
                plan_draft_service.ReviewScore(eval_item="협업 과제 이해도", grade="하", reason="얕다", unit_keys=[units["과제 해결방안"]],
                                               fixes=[fix(unit_key=units["과제 해결방안"], sentence="모델을 만듭니다.", fix="데이터 항목을 밝힌다")]),
                plan_draft_service.ReviewScore(eval_item="팀(기업) 구성", grade="하", reason="얕다", unit_keys=[units["기업(팀) 역량"]],
                                               fixes=[fix(unit_key=units["기업(팀) 역량"], sentence="인력이 있습니다.", fix="역할을 밝힌다")]),
            ])
        return _good(purpose, n)

    ai_on(monkeypatch, _reply)
    free = {**select_task(form), "budget": {**(form.get("budget") or {}), "mode": "in_kind"}}
    draft = run(free, requirements)
    fixes = [f["fix"] for s in draft["review_scores"] for f in s["fixes"]]
    notes = [i for n in draft["review_notes"] for i in n["items"]]
    assert "단계별 소요 예산(정부지원금·자부담)을 표로 덧붙입니다" not in fixes and "일정표 기간 칸을 채웁니다" in fixes
    assert notes and not any("자부담" in i for i in notes) and any("일정표 기간" in i for i in notes)
    paid = run(select_task(form), requirements)  # 사업비가 있는 공고는 그대로
    assert any("정부지원금" in f["fix"] for s in paid["review_scores"] for f in s["fixes"])


def test_36차_읽을_때도_단계_이름표는_큰_번호만_현물_공고는_예산_권고를_뺀다() -> None:
    """PLAN-01 — 10-12 Claude 초안(123852)은 f6dc939 전에 만들어져 1~4단계 줄마다 틀린 표시 · 「예산표를 덧붙이라」 권고가 저장돼 있다."""
    flag = lambda n: f"본문은 {n}단계인데 일정표는 5줄입니다 — 맞추세요"  # noqa: E731
    saved = {
        "sections": [{"key": "S3-2", "by": "llm", "sentences": [
            {"text": "○ 1단계 준비: 정리합니다.", "flags": [flag(1)]},
            {"text": "○ 2단계 개발: 고도화합니다.", "flags": [flag(2)]},
            {"text": "○ 4단계 사업화: 연결합니다.", "flags": [flag(4)]},
            {"text": "그 뒤 점검합니다.", "flags": ["다른 표시"]},
        ]}],
        "review_notes": [{"section": "추진 계획", "items": ["[성장전략] 단계별 소요 예산(정부지원금·자부담)을 표로 덧붙입니다", "[성장전략] 일정표 기간을 채웁니다"]}],
        "review_scores": [{"eval_item": "성장전략", "fixes": [{"fix": "자금 소요 계획을 표로 덧붙입니다"}, {"fix": "일정표 기간을 채웁니다"}]}],
    }
    free = plan_draft_service.read_view(saved, {"budget": {"mode": "in_kind"}})
    assert [s["flags"] for s in free["sections"][0]["sentences"]] == [[], [], [flag(4)], ["다른 표시"]]
    assert free["review_notes"][0]["items"] == ["[성장전략] 일정표 기간을 채웁니다"]
    assert [f["fix"] for f in free["review_scores"][0]["fixes"]] == ["일정표 기간을 채웁니다"]
    paid = plan_draft_service.read_view(saved, {"budget": {"mode": "cash"}})
    assert len(paid["review_notes"][0]["items"]) == 2 and len(paid["review_scores"][0]["fixes"]) == 2  # 사업비가 있는 공고는 그대로
    assert saved["sections"][0]["sentences"][0]["flags"] == [flag(1)]  # 저장본은 그대로


def test_36차_현물_공고는_채점_지시에_예산표_금지_고쳐_쓰기에도_예산_권고를_넘기지_않는다(monkeypatch: pytest.MonkeyPatch, form: dict, requirements) -> None:
    """PLAN-03 — 거르기가 화면에만 걸리고 고쳐 쓰기 지시에는 그대로 갔다."""
    units = {u["title"]: u["key"] for u in plan_draft_service.form_units(form)}
    systems: dict[str, str] = {}
    users: list[str] = []
    monkeypatch.setattr(plan_draft_service, "llm_ready", lambda: (True, None))

    def _fake(**kwargs):
        systems[kwargs["purpose"]] = kwargs["system"]
        users.append(kwargs["user"])
        if kwargs["purpose"] == "plan_draft:review":
            return plan_draft_service.PlanReviewOut(scores=[plan_draft_service.ReviewScore(
                eval_item="지속 가능성", grade="하", reason="일정이 비었다", unit_keys=[units["사업화 방안"]],
                fixes=[plan_draft_service.ReviewFix(unit_key=units["사업화 방안"], sentence="단계별로 실행합니다.", fix="단계별 예산표를 덧붙입니다"),
                       plan_draft_service.ReviewFix(unit_key=units["사업화 방안"], sentence="단계별로 실행합니다.", fix="일정표 기간 칸을 채웁니다")])])
        return _good(kwargs["purpose"], len(users))

    monkeypatch.setattr(llm_client, "complete_structured", _fake)
    free = {**select_task(form), "budget": {**(form.get("budget") or {}), "mode": "in_kind"}}
    run(free, requirements)
    assert plan_draft_service.IN_KIND_REVIEW_RULE in systems["plan_draft:review"]
    rewrite = users[-1]  # 마지막 호출이 「하」 절 고쳐 쓰기
    assert "일정표 기간 칸을 채웁니다" in rewrite and "예산표" not in rewrite


def test_36차_예산_자금_낱말은_검토_권고에만_초안_문장은_옛_낱말() -> None:
    """마지막 검토 PD-1 — 넓힌 낱말이 초안 만들기에도 쓰여 무료(현물) 공고의 「투자금 유치 실적」 · 「예산군」 문장이 AI 제안으로 내려갔다."""
    for text in ("투자금 유치 실적을 적습니다", "예산군 소재 기업과 협력합니다", "운영 예산 절감 효과를 냅니다"):
        assert not plan_draft_service._BUDGET_TALK_RE.search(text)
    assert plan_draft_service._BUDGET_TALK_RE.search("자부담 비율을 적습니다")
    assert plan_draft_service._BUDGET_ADVICE_RE.search("예산표를 덧붙이세요") and plan_draft_service._BUDGET_ADVICE_RE.search("자금 소요 계획을 적으세요")
