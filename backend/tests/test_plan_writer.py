"""사업계획서 작성 페이지 전용 문 — 단추를 누를 때만 Claude CLI (28차 §3-D · prompt_18).

- 서버 전체 AI(`llm_live`)가 꺼져 있어도 `plan_writer=True` 호출만 CLI 로 간다. 나머지(제안서 6단계 · Auditor · 자격 보강)는 그대로 막힌다.
- 문이 꺼져 있으면(`plan_writer_cli` 거짓) CLI 0 · 한 줄 사유.
- 입찰 제안서 CLI 경로는 **사람이 채택한 근거 문장만** 보낸다.
- 다른 공고를 만드는 중이면 409 · 상태 API 는 꺼져 있을 때 프로세스를 띄우지 않는다 · 저장본 목록은 메타만.

CLI 는 부르지 않는다 — `subprocess.run` 을 가짜로 바꿔 끼운다.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core import inflight
from app.core.config import get_settings
from app.main import app
from app.schemas.organization import AnalysisContext
from app.services import llm_client, proposal_service, support_plan_service

FAKE_EXE = r"C:\fake\claude.exe"
FAKE_CODEX = r"C:\fake\codex.exe"
client = TestClient(app)


class _Answer(BaseModel):
    ok: bool = True


@pytest.fixture()
def cli_calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """가짜 CLI — 받은 stdin(보낸 본문)을 모은다. 누계 기록은 임시 파일로."""
    calls: list[str] = []
    monkeypatch.setattr(llm_client, "USAGE_LOG", tmp_path / "llm_usage.jsonl")
    monkeypatch.setattr(llm_client, "claude_cli_path", lambda: FAKE_EXE)

    def fake_run(args, **kwargs):
        calls.append(kwargs.get("input") or "")
        body = {"type": "result", "is_error": False, "result": "", "structured_output": {"ok": True}, "usage": {}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(body), stderr="")

    monkeypatch.setattr(llm_client.subprocess, "run", fake_run)
    return calls


def writer(monkeypatch: pytest.MonkeyPatch, *, on: bool, live: bool = False) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "plan_writer_cli", on)
    monkeypatch.setattr(settings, "llm_live", live)
    monkeypatch.setattr(settings, "llm_provider", "openai")  # 서버 공급자가 무엇이든 문은 claude_cli 로 고정


def test_writer_on_only_plan_writer_calls_reach_cli(monkeypatch: pytest.MonkeyPatch, cli_calls: list[str]) -> None:
    writer(monkeypatch, on=True, live=False)
    answer = llm_client.complete_structured(system="s", user="본문", schema=_Answer, plan_writer=True)
    assert answer.ok is True
    assert cli_calls == ["본문"]
    # 같은 서버에서 plan_writer 를 넘기지 않는 호출(제안서 6단계 · Auditor · 자격 보강)은 막힌다
    with pytest.raises(llm_client.LLMUnavailableError, match="AI 초안이 꺼져"):
        llm_client.complete_structured(system="s", user="u", schema=_Answer)
    assert len(cli_calls) == 1


def test_writer_off_no_cli_and_one_line_reason(monkeypatch: pytest.MonkeyPatch, cli_calls: list[str]) -> None:
    writer(monkeypatch, on=False, live=False)
    with pytest.raises(llm_client.LLMUnavailableError) as exc:
        llm_client.complete_structured(system="s", user="u", schema=_Answer, plan_writer=True)
    assert str(exc.value) == llm_client.PLAN_WRITER_OFF_REASON
    assert cli_calls == []


def test_status_off_spawns_no_process(monkeypatch: pytest.MonkeyPatch) -> None:
    writer(monkeypatch, on=False)

    def boom(*args, **kwargs):
        raise AssertionError("꺼져 있는데 프로세스를 띄웠다")

    monkeypatch.setattr(llm_client.subprocess, "run", boom)
    body = client.get("/api/plan-writer/status").json()
    assert body["enabled"] is False and body["cli"] is False and body["logged_in"] is False
    assert body["off_reason"] == llm_client.PLAN_WRITER_OFF_REASON
    assert client.get("/health").json()["plan_writer_cli"] is False


def test_status_on_reads_login_once(monkeypatch: pytest.MonkeyPatch) -> None:
    writer(monkeypatch, on=True)
    monkeypatch.setattr(llm_client, "claude_cli_path", lambda: FAKE_EXE)
    seen: list[list[str]] = []

    def fake_run(args, **kwargs):
        seen.append(list(args))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max"}), stderr="")

    monkeypatch.setattr(llm_client.subprocess, "run", fake_run)
    body = client.get("/api/plan-writer/status").json()
    assert body == {**body, "enabled": True, "cli": True, "logged_in": True, "auth_method": "claude.ai", "subscription_type": "max",
                    "training_reminder": True}
    assert seen == [[FAKE_EXE, "auth", "status"]]  # 모델을 부르지 않는다


def test_proposal_cli_payload_carries_only_adopted_evidence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """입찰 제안서 CLI 경로 — 채택(selected)한 근거 문장만 간다. 채택 안 한 후보 문장은 본문에 없다."""
    from app.schemas.proposal import EvidenceCandidate
    from app.services import rfp_parser

    writer(monkeypatch, on=True)
    sent: list[str] = []

    def fake_complete(**kwargs):
        sent.append(kwargs["user"])
        assert kwargs.get("plan_writer") is True
        raise llm_client.LLMUnavailableError("가짜 — 규칙 초안 유지")

    monkeypatch.setattr(llm_client, "complete_structured", fake_complete)
    monkeypatch.setattr(llm_client, "claude_cli_path", lambda: FAKE_EXE)
    monkeypatch.setattr(proposal_service, "store_document", lambda document, context=None: document)
    parsed = rfp_parser.load_generated("synthetic-rfp-0001")
    first, second = parsed.requirements[0], parsed.requirements[1]
    links = [
        EvidenceCandidate(requirement_id=first.requirement_id, evidence_id="EV-A", document_name="채택문서", page=1,
                          source_text="채택한 근거 문장 가나다", similarity_score=0.9, selected=True),
        EvidenceCandidate(requirement_id=second.requirement_id, evidence_id="EV-B", document_name="후보문서", page=2,
                          source_text="채택 안 한 후보 문장 라마바", similarity_score=0.8, selected=False),
    ]
    proposal_service.generate_document("synthetic-rfp-0001", evidence_links=links, plan_writer=True)
    body = "\n".join(sent)
    assert sent, "CLI 경로가 불리지 않았다"
    assert "채택 안 한 후보 문장 라마바" not in body and "후보문서" not in body
    assert "채택한 근거 문장 가나다" in body


def test_other_notice_running_is_409(monkeypatch: pytest.MonkeyPatch) -> None:
    writer(monkeypatch, on=True)
    with inflight.hold("plan_writer"):
        response = client.post("/api/proposal/generate/full", json={"procurement_id": "synthetic-rfp-0001", "use_claude": True})
    assert response.status_code == 409
    assert response.json()["detail"] == inflight.PLAN_WRITER_BUSY
    assert inflight.running("plan_writer") is False


def test_plan_drafts_list_is_meta_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.core import org_storage

    analyses = tmp_path / "analyses"
    folder = analyses / "bizinfo-PBLN_1"
    (folder / support_plan_service.VERSIONS_DIR).mkdir(parents=True)
    secret = "회사 실적 본문 — 목록에 나오면 안 된다"
    (folder / "plan_draft.json").write_text(json.dumps({
        "form_title": "사업계획서", "generated_by": "llm", "provider": "claude_cli", "model": "claude-opus-5-5",
        "executed_at": "2026-09-29T02:22:00+00:00", "elapsed_seconds": 198.3, "ai_sentence_count": 76,
        "blanks": [{"field": "매출", "why": secret}], "sections": [{"sentences": [{"text": secret}]}],
    }, ensure_ascii=False), encoding="utf-8")
    (folder / support_plan_service.VERSIONS_DIR / "2026-09-28T13-13-05.155389+00-00.json").write_text(
        json.dumps({"generated_by": "rules", "sections": [{"sentences": [{"text": secret}]}]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(org_storage, "storage_for", lambda org: SimpleNamespace(analyses_dir=analyses, analysis_dir=lambda pid: analyses / pid))
    context = AnalysisContext(organization_id="org-test-alpha", evidence_scope="internal")
    items = support_plan_service.list_saved(context)
    assert items[0]["id"] == "bizinfo-PBLN_1" and items[0]["versions"] == 1 and items[0]["blanks"] == 1
    assert secret not in json.dumps(items, ensure_ascii=False)
    assert "sections" not in items[0]
    versions = support_plan_service.list_versions(context, "bizinfo-PBLN_1")
    assert secret not in json.dumps(versions, ensure_ascii=False)
    # 폴더에 없는 이름(경로 이동)은 읽지 않는다
    assert support_plan_service.load_version(context, "bizinfo-PBLN_1", "../plan_draft") is None


def test_only_two_services_pass_plan_writer() -> None:
    """`plan_writer=` 를 넘기는 곳은 사업계획서 · 입찰 제안서 서비스(와 그 라우트)뿐 — 소스 검사.
    11-03 — 입찰 제안서 초안(제안요청서 목차대로 · `bid_proposal_service`)이 더해졌다.
    2.4.0 — 공고문에 질문하기(`notice_qa_service` · 원문 쪽 글 + 질문만 보냄)가 더해졌다."""
    root = Path(__file__).resolve().parents[1] / "app"
    allowed = {"services/plan_draft_service.py", "services/proposal_service.py", "services/bid_proposal_service.py", "services/llm_client.py",
               "services/notice_qa_service.py", "api/insights.py", "api/proposal.py"}
    passing = {p.relative_to(root).as_posix() for p in root.rglob("*.py") if "plan_writer=" in p.read_text(encoding="utf-8")}
    assert passing <= allowed, passing - allowed
    for name in ("services/auditor_service.py", "services/eligibility_engine.py"):
        assert "plan_writer" not in (root / name).read_text(encoding="utf-8"), name
    # 대시보드 6단계(부분 제안서) 요청은 use_claude 를 받지 않는다
    assert "use_claude" not in (root / "schemas" / "proposal.py").read_text(encoding="utf-8")


def test_other_company_on_public_demo_is_403_before_cli(monkeypatch: pytest.MonkeyPatch, cli_calls: list[str]) -> None:
    """28차 검수 R1-02 — 저장할 수 없는 곳(공용 데모 · 기본이 아닌 회사)이면 CLI 를 부르기 전에 거절한다."""
    from app.services import organization_service

    writer(monkeypatch, on=True)
    # 시험 환경의 회사 등록부와 상관없이 「기본이 아닌 회사 + 공용 데모」 문맥을 만든다
    monkeypatch.setattr(organization_service, "resolve_context", lambda *a, **k: AnalysisContext(organization_id="org-test-alpha", evidence_scope="public_demo"))
    response = client.post(
        "/api/proposal/generate/full",
        json={"procurement_id": "synthetic-rfp-0001", "use_claude": True, "organization_id": "org-test-alpha", "evidence_scope": "public_demo"},
    )
    assert response.status_code == 403, response.text
    assert cli_calls == []


def test_bid_cli_failure_is_reported_and_keeps_previous_ai_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    """28차 검수 R1-01 — Claude 가 모두 실패하면 사유를 돌려주고, 있던 AI 초안을 규칙 초안으로 덮지 않는다."""
    from app.schemas.proposal_document import ProposalDocument

    writer(monkeypatch, on=True)
    monkeypatch.setattr(llm_client, "claude_cli_path", lambda: FAKE_EXE)

    def failing(**kwargs):
        raise llm_client.LLMUnavailableError("Claude 사용 한도에 걸렸습니다")

    monkeypatch.setattr(llm_client, "complete_structured", failing)
    previous = ProposalDocument(id="PROPDOC-x", procurement_id="synthetic-rfp-0001", title="옛 AI 초안", generation_method="LLM")
    stored: list[ProposalDocument] = []
    monkeypatch.setattr(proposal_service, "load_document", lambda pid, context=None: previous)
    monkeypatch.setattr(proposal_service, "store_document", lambda document, context=None: stored.append(document) or document)
    result = proposal_service.generate_document("synthetic-rfp-0001", plan_writer=True)
    assert stored == []  # 덮지 않았다
    assert result.kept_llm_draft is True and result.title == "옛 AI 초안"
    assert result.llm_note and "사용 한도" in result.llm_note
    # 옛 AI 초안이 없으면 규칙 초안을 저장하되 실패 사유를 싣는다 — 회사 폴더(internal)일 때
    monkeypatch.setattr(proposal_service, "load_document", lambda pid, context=None: (_ for _ in ()).throw(proposal_service.ProposalNotGeneratedError(pid)))
    internal = AnalysisContext(organization_id="org-test-alpha", evidence_scope="internal")
    result = proposal_service.generate_document("synthetic-rfp-0001", plan_writer=True, context=internal)
    assert stored and result.generation_method == "RULE" and result.llm_note and "사용 한도" in result.llm_note
    # 합성 데모(공개 추적 파일)에는 저장하지 않고 이 화면에만 돌려준다 (29차 R28-07)
    stored.clear()
    result = proposal_service.generate_document("synthetic-rfp-0001", plan_writer=True)
    assert stored == [] and "저장하지 않았습니다" in (result.llm_note or "")


def test_bid_no_change_without_error_keeps_previous_ai_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    """29차 R28-05 — 실패 사유가 없어도 한 섹션도 AI 로 바뀌지 않았으면 있던 AI 초안을 덮지 않는다."""
    from app.schemas.proposal import GeneratedSectionDraft
    from app.schemas.proposal_document import ProposalDocument

    writer(monkeypatch, on=True)
    monkeypatch.setattr(llm_client, "codex_cli_path", lambda: FAKE_CODEX)
    seen: list[dict] = []

    def empty(**kwargs):  # 답은 왔는데 고친 문장이 없다
        seen.append(kwargs)
        return GeneratedSectionDraft(sentences=[])

    monkeypatch.setattr(llm_client, "complete_structured", empty)
    previous = ProposalDocument(id="PROPDOC-x", procurement_id="synthetic-rfp-0001", title="옛 AI 초안", generation_method="LLM")
    stored: list[ProposalDocument] = []
    monkeypatch.setattr(proposal_service, "load_document", lambda pid, context=None: previous)
    monkeypatch.setattr(proposal_service, "store_document", lambda document, context=None: stored.append(document) or document)
    internal = AnalysisContext(organization_id="org-test-alpha", evidence_scope="internal")
    result = proposal_service.generate_document("synthetic-rfp-0001", plan_writer=True, writer="codex", context=internal)
    assert stored == [] and result.kept_llm_draft is True and "바꾼 문장이 없습니다" in (result.llm_note or "")
    # 쓰는 이 · 한 벌 시간 상한이 호출마다 간다 (29차 §3-A · R28-06)
    assert seen and all(k["writer"] == "codex" and 0 < k["timeout"] <= proposal_service.PLAN_WRITER_TIME_LIMIT for k in seen)


def test_bid_deadline_passed_skips_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """29차 R28-06 — 한 벌 마감이 지나면 더 부르지 않고 사유를 남긴다."""
    writer(monkeypatch, on=True)
    monkeypatch.setattr(llm_client, "claude_cli_path", lambda: FAKE_EXE)
    monkeypatch.setattr(llm_client, "complete_structured", lambda **k: (_ for _ in ()).throw(AssertionError("마감 뒤에 불렀다")))
    errors: list[str] = []
    drafts = [SimpleNamespace()]  # 비어 있지 않은 목록이면 된다 — 부르기 전에 돌아선다
    assert proposal_service.refine_with_llm(drafts, plan_writer=True, errors=errors, deadline=0.0) is False
    assert errors and "시간 상한" in errors[0]


def test_이전_판_라우트_잘못된_id_는_400_목록은_시각_순(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """29차 R28-08 — 잘못된 공고 id 는 500 이 아니라 400 · 이전 판 목록은 만든 시각 최신 순(「rules-」 판이 늘 위가 아니다)."""
    from app.core import org_storage

    for path in ("/api/support-programs/bad id!/plan-draft/versions", "/api/support-programs/bad id!/plan-draft/versions/x"):
        response = client.get(f"{path}?organization_id=org-sample")
        assert response.status_code == 400, (path, response.text)
    analyses = tmp_path / "analyses"
    folder = analyses / "bizinfo-PBLN_1" / support_plan_service.VERSIONS_DIR
    folder.mkdir(parents=True)
    for name, at in (("rules-2026-09-27T01-00-00+00-00", "2026-09-27T01:00:00+00:00"), ("2026-09-29T01-00-00+00-00", "2026-09-29T01:00:00+00:00"),
                     ("2026-09-28T01-00-00+00-00", "2026-09-28T01:00:00+00:00")):
        (folder / f"{name}.json").write_text(json.dumps({"generated_by": "rules", "executed_at": at}), encoding="utf-8")
    monkeypatch.setattr(org_storage, "storage_for", lambda org: SimpleNamespace(analyses_dir=analyses, analysis_dir=lambda pid: analyses / pid))
    context = AnalysisContext(organization_id="org-test-alpha", evidence_scope="internal")
    names = [v["name"] for v in support_plan_service.list_versions(context, "bizinfo-PBLN_1")]
    assert names == ["2026-09-29T01-00-00+00-00", "2026-09-28T01-00-00+00-00", "rules-2026-09-27T01-00-00+00-00"]
