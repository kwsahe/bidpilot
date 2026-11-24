"""41차 2-D — 「안 적음」(D31) · 선제준비 꼬리표(브리핑 · 엑셀 · FRONT-R40-02 · TOPIC-01) · AI 풀이 한 줄(AIFIT-06) · 실무순 풀이(TOPIC-10) ·
tags_of 대형(REGRESS-08) · 로그 없이 예약 작업만(REGRESS-05) · 예약 작업 상태 한 번만(REGRESS-03) · 탐침 import 순서(REGRESS-01). 호출 없음."""

from __future__ import annotations

import ast
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.schemas.business_opportunity import NextRoute, PrepareSection, UnifiedOpportunity
from app.services import auto_collect, company_blank_fields, delivery_capacity_service
from app.services import opportunity_brief_service as brief
from app.services import practical_priority as p

ORG = get_settings().default_organization_id
NOW = datetime(2026, 10, 21, 3, 0, tzinfo=timezone.utc)


def _item(n: int, title: str, *, gate: str = "CHECK", unlock: list[str] | None = None, pre: bool = False, typ: str = "A1") -> UnifiedOpportunity:
    item = UnifiedOpportunity(
        id=(f"g2bpre-R26BD{n:08d}" if pre else f"g2b-R26BK{n:08d}-000"), source_type="g2b",
        opportunity_type="pre_spec" if pre else "procurement", title=title, agency="서울 시험 기관", organization_id=ORG,
        priority_rank=n, priority_label="검토", eligibility_gate=gate, confidence="medium", score_components=[], company_priority_score=60,
        next_route=NextRoute(kind="support_application", path="/", label="열기"), source="cached",
        deadline=None if pre else NOW + timedelta(days=20), published_at=NOW - timedelta(days=2), fit_type=typ, budget=50_000_000,
        unlock_conditions=unlock or [],
    )
    if pre:
        item.opinion_deadline = NOW + timedelta(days=3)
    return item


# --------------------------------------------------------------------------
# D31 — 「안 적음(그대로 둠)」
# --------------------------------------------------------------------------


def test_안_적음_칸은_빈칸_안내에서_빠지고_판정은_그대로() -> None:
    from app.services import eligibility_engine

    items = [_item(1, "공동수급 교육 운영", unlock=["공동수급 파트너가 있으면 가능"]), _item(2, "매출 요건 교육", unlock=["매출 10억 이상이면 가능"])]
    company = eligibility_engine.CompanyFacts()
    before = {f.key: f for f in company_blank_fields.count_fields(items, company)}
    assert len(before["joint_bid_partner"].ids) == 1 and len(before["revenue"].ids) == 1
    after = {f.key: f for f in company_blank_fields.count_fields(items, company, frozenset({"joint_bid_partner"}))}
    assert after["joint_bid_partner"].left_blank and after["joint_bid_partner"].ids == []  # 안내에서 빠짐
    assert after["joint_bid_partner"].to_dict()["left_blank"] is True and after["joint_bid_partner"].blank  # 값은 여전히 비어 있음
    assert len(after["revenue"].ids) == 1  # 다른 칸은 그대로
    assert [i.eligibility_gate for i in items] == ["CHECK", "CHECK"]  # 판정은 손대지 않는다


def test_안_적음_저장은_그_칸만_바꾸고_입찰_자격_자료_저장이_지우지_않는다() -> None:
    client = TestClient(app)
    bad = client.put(f"/api/capability/left-blank?organization_id={ORG}", json={"keys": ["없는칸"], "updated_by": "시험"})
    assert bad.status_code == 400
    ok = client.put(f"/api/capability/left-blank?organization_id={ORG}", json={"keys": ["joint_bid_partner", "revenue"], "updated_by": "시험"})
    assert ok.status_code == 200 and ok.json()["left_blank"] == ["joint_bid_partner", "revenue"]
    capacity = delivery_capacity_service.load(ORG)
    assert capacity.left_blank == ["joint_bid_partner", "revenue"]
    assert capacity.joint_bid_partner is None and capacity.revenue_krw_last_year is None  # 회사 값은 쓰지 않는다
    # 입찰 자격 자료 화면 저장(이 칸을 모름)이 「안 적음」을 지우지 않는다
    body = {"updated_by": "시험", "proposal_lead_days": 4}
    assert client.put(f"/api/capability/profile?organization_id={ORG}", json=body).status_code == 200
    assert delivery_capacity_service.load(ORG).left_blank == ["joint_bid_partner", "revenue"]
    assert client.put(f"/api/capability/left-blank?organization_id={ORG}", json={"keys": [], "updated_by": "시험"}).json()["left_blank"] == []


def test_브리핑_등록_업종_권유도_안_적음이면_빠진다(monkeypatch: pytest.MonkeyPatch) -> None:
    items = [_item(1, "교육 운영", unlock=["1468 등록 시 가능"])]
    listing = SimpleNamespace(items=items, organization_id=ORG)
    assert "등록 업종" in brief._direct_note(listing)
    monkeypatch.setattr(company_blank_fields, "left_blank_of", lambda _org: frozenset({"registered_industries"}))
    assert "등록 업종」이 비어" not in brief._direct_note(listing)


# --------------------------------------------------------------------------
# 선제준비 꼬리표 · AI 풀이 · 실무순 풀이 · tags_of 대형
# --------------------------------------------------------------------------


def test_선제준비_판단_칸에_꼬리표() -> None:
    pre = _item(1, "세무 교육 운영", pre=True)
    p.annotate([pre], now=NOW, ceiling_krw=200_000_000)
    assert pre.topic_note == p.TOPIC_TAG
    assert brief.verdict_of(pre) == f"선제준비 · {p.TOPIC_TAG}"


def test_AI_꼬리표가_선제준비에만_있어도_풀이_한_줄() -> None:
    pre = _item(1, "AI 행사 운영", pre=True)
    pre.ai_fit_note = "AI: 본업 아닐 수 있음 · 행사 대행"
    listing = SimpleNamespace(items=[_item(2, "AI 교육 운영")], prepare=PrepareSection(items=[pre]))
    assert brief.ai_note_line(listing)


def test_대형_꼬리표도_tags_of_에_들고_판단_칸에는_한_번만() -> None:
    big = _item(1, "AI 플랫폼 구축", typ="C")
    big.budget = 900_000_000
    p.annotate([big], now=NOW, ceiling_krw=200_000_000)
    assert big.partner_tag and big.partner_tag in p.tags_of(big)
    assert brief.verdict_of(big).count(big.partner_tag) == 1
    # 42차 BACK-R41-01 — 브리핑 TOP 판단 칸도 한 번만(긴급 머리가 붙어도)
    assert brief._top_verdict(big).count(big.partner_tag) == 1
    big.time_tier = "T6"
    assert brief._top_verdict(big).count(big.partner_tag) == 1


def test_실무순_풀이에_주제_자리() -> None:
    source = (Path(brief.__file__)).read_text(encoding="utf-8")
    assert "본업 안에서 주제 맞음 먼저" in source


# --------------------------------------------------------------------------
# 받은 때 한 줄 — 로그 없이 예약 작업만 · 상태 조회 한 번만
# --------------------------------------------------------------------------


def test_로그가_없어도_예약_작업이_있으면_키트가_아니다(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not auto_collect.LOG_FILE.exists()
    monkeypatch.setattr(auto_collect, "task_state", lambda: "Ready")
    assert auto_collect.collect_state(NOW)["kind"] == "missed"
    monkeypatch.setattr(auto_collect, "task_state", lambda: "Disabled")
    assert auto_collect.collect_state(NOW)["kind"] == "off"
    monkeypatch.setattr(auto_collect, "task_state", lambda: "NONE")
    assert auto_collect.collect_state(NOW)["kind"] == "none"


def test_예약_작업_상태는_동시에_와도_한_번만_묻는다() -> None:
    import importlib.util

    # conftest 가 가짜 task_state 를 끼워 두었으니 같은 파일을 따로 읽은 사본으로 잰다(파일 · 로그는 건드리지 않는 함수만 부름)
    spec = importlib.util.spec_from_file_location("auto_collect_copy_r41", auto_collect.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    calls: list[int] = []

    def slow() -> str:
        calls.append(1)
        time.sleep(0.2)
        module._TASK_MEMO.update(at=time.monotonic(), state="Ready")
        return "Ready"

    module._ask_task_state = slow
    threads = [threading.Thread(target=module.task_state) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1


# --------------------------------------------------------------------------
# REGRESS-01 — 탐침은 앱을 맨 위에서 들여오지 않는다
# --------------------------------------------------------------------------


def test_탐침은_맨_위에서_앱을_들여오지_않는다() -> None:
    path = Path(__file__).resolve().parents[2] / "scripts" / "probe_ai_fit.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert not any(isinstance(n, ast.ImportFrom) and (n.module or "").startswith("app") for n in top)


def test_다른_폴더의_예약_작업은_이_설치의_작업이_아니다(monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 PC 의 키트가 본 저장소의 작업(작업 폴더가 다른 곳)을 제 것으로 읽어 「오늘 목록을 아직 받지 않았습니다」를 띄웠다(41차 키트)."""
    import importlib.util
    import subprocess as sp
    import sys as _sys

    spec = importlib.util.spec_from_file_location("auto_collect_copy_r41b", auto_collect.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    monkeypatch.setattr(_sys, "platform", "win32")

    def answer(text: str):
        return lambda *a, **k: sp.CompletedProcess(a, 0, stdout=text, stderr="")

    monkeypatch.setattr(module.subprocess, "run", answer(r"Ready|C:\somewhere\else"))
    assert module._ask_task_state() == "NONE"
    monkeypatch.setattr(module.subprocess, "run", answer(f"Disabled|{module._REPO_ROOT}"))
    assert module._ask_task_state() == "Disabled"
    monkeypatch.setattr(module.subprocess, "run", answer("NONE"))
    assert module._ask_task_state() == "NONE"
