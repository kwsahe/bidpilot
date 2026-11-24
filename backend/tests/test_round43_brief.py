"""43차 §2-D — 브리핑 · 숫자 · 엑셀(BRIEF-01 · Q27 · M9 · N11)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.services import opportunity_brief_service as brief
from tests.test_round37_brief import NOW, SAMPLE, listing


@pytest.fixture()
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(brief, "briefs_dir", lambda organization_id: tmp_path / "briefs")
    return tmp_path / "briefs"


def test_같은_날_두_번째_브리핑은_기준을_새로_남기지_않는다(folder) -> None:
    _, snapshot = brief.build_markdown(listing(SAMPLE), now=NOW, previous=None)
    assert brief.save_snapshot("org-sample", snapshot, now=NOW) is not None
    assert brief.save_snapshot("org-sample", snapshot, now=NOW + timedelta(hours=3)) is None
    assert brief.save_snapshot("org-sample", snapshot, now=NOW + timedelta(days=1)) is not None


def test_규칙_판이_다르면_순위_비교를_하지_않는다(folder) -> None:
    _, snapshot = brief.build_markdown(listing(SAMPLE), now=NOW, previous=None)
    old = {**snapshot, "rules_version": 1}
    diff = brief.changes(old, snapshot)
    assert diff["not_comparable"] == "규칙 판" and diff["up"] == [] and diff["down"] == []


def test_계정마다_자기_기준과_견준다(folder) -> None:
    _, snapshot = brief.build_markdown(listing(SAMPLE), now=NOW, previous=None)
    brief._save_snapshot("org-sample", {**snapshot, "account": "hajin"}, now=NOW)
    brief._save_snapshot("org-sample", {**snapshot, "account": "ceo"}, now=NOW + timedelta(hours=1))
    assert brief.latest_snapshot("org-sample", account="hajin")["account"] == "hajin"
    assert brief.latest_snapshot("org-sample", account="new")["account"] == "ceo"  # 없으면 회사 최신


def test_비추천_사유_묶음_이름() -> None:
    assert brief._low_bundle("본업이 아닌 일 — 공고명의 「국외연수」(여행 · 국외연수)") == "여행 · 국외연수"
    assert brief._low_bundle(None).startswith("관련 낮음")
