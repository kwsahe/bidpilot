"""10-31 최종 점검 W4 — /plan 저장본 목록: 서식 제목이 빈 지원사업 저장본은 같은 폴더 공고 사본(program.json)의 제목을 쓴다."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.schemas.organization import AnalysisContext
from app.services import support_plan_service


def test_saved_support_draft_without_form_title_uses_program_snapshot_title(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.core import org_storage

    analyses = tmp_path / "analyses"
    blank = analyses / "bizinfo-PBLN_000000000123852"
    titled = analyses / "bizinfo-PBLN_2"
    nothing = analyses / "bizinfo-PBLN_3"
    for folder in (blank, titled, nothing):
        folder.mkdir(parents=True)
    draft = {"form_title": None, "generated_by": "rules", "executed_at": "2026-10-01T00:00:00+00:00", "sections": [{"sentences": []}]}
    (blank / "plan_draft.json").write_text(json.dumps(draft), encoding="utf-8")
    (blank / "program.json").write_text(json.dumps({"id": blank.name, "title": "[전남광주] 디지털 품질관리 역량강화사업", "agency": "전남"}, ensure_ascii=False), encoding="utf-8")
    # 서식 제목이 있으면 그대로(사본이 있어도 덮지 않는다)
    (titled / "plan_draft.json").write_text(json.dumps({**draft, "form_title": "사업계획서 서식"}, ensure_ascii=False), encoding="utf-8")
    (titled / "program.json").write_text(json.dumps({"id": titled.name, "title": "다른 제목", "agency": "x"}, ensure_ascii=False), encoding="utf-8")
    # 사본도 없으면 지어내지 않는다(화면이 id 로 둔다)
    (nothing / "plan_draft.json").write_text(json.dumps(draft), encoding="utf-8")
    monkeypatch.setattr(org_storage, "storage_for", lambda org: SimpleNamespace(analyses_dir=analyses, analysis_dir=lambda pid: analyses / pid))

    items = {row["id"]: row for row in support_plan_service.list_saved(AnalysisContext(organization_id="org-test-alpha", evidence_scope="internal"))}
    assert items[blank.name]["title"] == "[전남광주] 디지털 품질관리 역량강화사업"
    assert items[titled.name]["title"] == "사업계획서 서식"
    assert items[nothing.name]["title"] is None


def test_saved_bid_drafts_are_the_new_bid_plan_files_not_the_old_full_drafts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """11-03 검토 — /plan 저장 목록이 옛 전체 초안(proposal_document.json)을 세서, 열면 「초안 없음」인 행이 고정됐다."""
    from app.core import org_storage

    analyses = tmp_path / "analyses"
    old, new = analyses / "g2b-R26BK00000001-000", analyses / "g2b-R26BK00000002-000"
    for folder in (old, new):
        folder.mkdir(parents=True)
    (old / "proposal_document.json").write_text(json.dumps({"sections": [{"sentences": []}], "generation_method": "LLM"}), encoding="utf-8")
    (new / "bid_plan_draft.json").write_text(json.dumps({
        "title": "제안서 공고", "generated_by": "llm", "model": "claude-opus-5-5", "executed_at": "2026-11-03T07:48:00+00:00",
        "sections": [{"sentences": []}], "blanks": [{"field": "참여인력 현황", "why": "사람만 채우는 표", "section": "4. 참여인력"}],
    }, ensure_ascii=False), encoding="utf-8")
    (new / "bid_plan_versions").mkdir()
    (new / "bid_plan_versions" / "2026-11-03T07-02-00.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(org_storage, "storage_for", lambda org: SimpleNamespace(analyses_dir=analyses, analysis_dir=lambda pid: analyses / pid))

    items = {row["id"]: row for row in support_plan_service.list_saved(AnalysisContext(organization_id="org-test-alpha", evidence_scope="internal"))}
    assert old.name not in items
    row = items[new.name]
    assert row["kind"] == "proposal" and row["generated_by"] == "llm" and row["model"] == "claude-opus-5-5"
    assert row["executed_at"] == "2026-11-03T07:48:00+00:00" and row["blanks"] == 1 and row["versions"] == 1
