"""40차 §3-D — AI 적합도 보조(담당자 결정 2 · D24). **호출 없음** — 가짜 CLI(`ask`)로만 시험한다.

보낸 글 허용 목록(공고명 · 조달분류 요약 · 기관 · 예산 · 관심 분야 · 판정 정의) · 하루 1회 · 120건 · 시간 초과 → 규칙만 ·
같은 공고는 다시 묻지 않음 · 판정 · 점수 그대로 · `ai_fit_assist` 꺼지면 아무것도 안 함.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.schemas.business_opportunity import NextRoute, UnifiedOpportunity
from app.schemas.delivery_capacity import DeliveryCapacityUpdate
from app.services import ai_fit_service as ai
from app.services import delivery_capacity_service
from app.services import practical_priority as p

NOW = datetime(2026, 10, 21, 0, 30, tzinfo=timezone.utc)  # 09:30 KST
ORG = get_settings().default_organization_id
CEILING = 200_000_000


def _item(n: int, title: str, *, left: int = 20, pre: bool = False, typ: str = "A1", budget: int | None = 50_000_000) -> UnifiedOpportunity:
    item = UnifiedOpportunity(
        id=(f"g2bpre-R26BD{n:08d}" if pre else f"g2b-R26BK{n:08d}-000"), source_type="g2b",
        opportunity_type="pre_spec" if pre else "procurement", title=title, agency="서울 시험 기관", organization_id=ORG,
        priority_rank=n, priority_label="검토", eligibility_gate="CHECK", confidence="medium", score_components=[],
        company_priority_score=60, next_route=NextRoute(kind="support_application", path="/", label="열기"), source="cached",
        deadline=None if pre else NOW + timedelta(days=left), published_at=NOW - timedelta(days=3), fit_type=typ,
        submission_methods=["전자입찰"], budget=budget,
    )
    if pre:
        item.opinion_deadline = NOW + timedelta(days=left)
    return item


def _listing(items: list[UnifiedOpportunity]):
    p.annotate(items, now=NOW, ceiling_krw=CEILING)
    bids = [i for i in items if i.opportunity_type != "pre_spec"]
    pre = [i for i in items if i.opportunity_type == "pre_spec"]
    return SimpleNamespace(items=bids, prepare=SimpleNamespace(items=pre))


def _raw(_id: str) -> dict:
    return {"item": {"pubPrcrmntLrgClsfcNm": "교육 및 전문직종/기술서비스", "pubPrcrmntMidClsfcNm": "교육서비스", "pubPrcrmntClsfcNm": "기타교육서비스"}}


def _pre_raw(_id: str) -> dict:
    return {"bsnsDivNm": "일반용역"}


@pytest.fixture()
def assist_on():
    """시험 저장소(사본)의 회사 설정에 `ai_fit_assist` 만 켠다 — 회사 값은 건드리지 않는다."""
    from app.core import org_storage, storage

    path = org_storage.storage_for(ORG).delivery_capacity_file
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = storage.read_json(path, default=None) or {}
    storage.write_json_atomic(path, {**payload, "ai_fit_assist": True})
    assert ai.enabled(ORG)
    yield


def test_설정을_비워_저장하면_켜_둔_값이_남는다(assist_on) -> None:
    current = delivery_capacity_service.load(ORG)
    fields = current.model_dump(exclude={"organization_id", "updated_at", "source", "ai_fit_assist", "updated_by"})
    delivery_capacity_service.save(ORG, DeliveryCapacityUpdate(**fields, updated_by="시험"))  # 이 칸을 모르는 화면이 저장해도
    assert delivery_capacity_service.load(ORG).ai_fit_assist is True


class FakeAsk:
    def __init__(self, labels: dict[str, tuple[str, str]] | None = None, error: Exception | None = None) -> None:
        self.labels = labels or {}
        self.error = error
        self.calls: list[list[str]] = []
        self.timeouts: list[float] = []

    def __call__(self, bodies, *, timeout=None):
        self.calls.append(list(bodies))
        self.timeouts.append(timeout)
        if self.error:
            raise self.error
        out = {}
        for n, body in enumerate(bodies, start=1):
            title = body.split(" | ")[0]
            label, reason = self.labels.get(title, ("core", "본업"))
            out[n] = ai.AiFitItem(n=n, label=label, reason=reason)
        return out


def test_꺼져_있으면_묻지도_꼬리표도_달지_않는다() -> None:
    items = [_item(1, "세무 교육 운영")]
    fake = FakeAsk()
    line = ai.run_daily(ORG, _listing(items), now=NOW, raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    assert line["건너뜀"].startswith("AI 적합도 꺼짐") and fake.calls == []
    assert ai.apply_notes(items, ORG) == 0 and items[0].ai_fit_note is None


def test_보낸_글은_허용_목록뿐(assist_on) -> None:
    items = [_item(1, "생성형 AI 실무 교육 운영"), _item(2, "AI 교육 콘텐츠 개발", pre=True, typ="A2")]
    fake = FakeAsk()
    ai.run_daily(ORG, _listing(items), now=NOW, raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    (bodies,) = fake.calls
    line_re = re.compile(r"^[^|]+ \| 분류: [^|]+ \| 기관: [^|]+ \| 예산: (?:\d+\.\d{2}억|미공개)$")
    assert all(line_re.match(b) for b in bodies), bodies
    # 회사 값 · 회사자료 · 실적 낱말이 없다(소재 · 매출 · 업종 코드 · 사업자번호 · 인원). 판정 정의 · 관심 분야는 고정 글(`SYSTEM`)이다.
    for word in ("전남광주", "매출", "사업자등록", "상시 근로자", "등록 업종", "수행실적", "1468"):
        assert word not in ai.SYSTEM + "\n" + ai.user_text(bodies), word
    assert "샘플에듀" not in ai.user_text(bodies)  # 공고 글에는 회사 이름도 없다(판정 정의 글의 「샘플에듀 일 아님」은 39차 정의 그대로)
    assert ai.SYSTEM.startswith("너는 공공조달 공고를 분류하는 검토자다") and all(t in ai.SYSTEM for t in ai.INTERESTS)
    assert "분류: 사전규격 · 일반용역" in bodies[1] or "분류: 사전규격 · 일반용역" in bodies[0]


def test_하루_1회_상한(assist_on) -> None:
    items = [_item(1, "세무 교육 운영")]
    fake = FakeAsk()
    ai.run_daily(ORG, _listing(items), now=NOW, raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    more = [_item(2, "새 공고 교육 운영")]
    second = ai.run_daily(ORG, _listing(more), now=NOW + timedelta(hours=3), raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    assert len(fake.calls) == 1 and second["건너뜀"] == "오늘 이미 물음(하루 1회)"
    tomorrow = ai.run_daily(ORG, _listing(more), now=NOW + timedelta(days=1), raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    assert len(fake.calls) == 2 and tomorrow["물은_수"] == 1


def test_한_번에_120건_마감_가까운_것부터(assist_on) -> None:
    items = [_item(n, f"AI 교육 운영 {n}", left=200 - n) for n in range(1, 131)]  # 번호가 클수록 마감이 가깝다
    fake = FakeAsk()
    line = ai.run_daily(ORG, _listing(items), now=NOW, raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    (bodies,) = fake.calls
    assert len(bodies) == ai.MAX_ITEMS == 120 and line["물은_수"] == 120
    assert bodies[0].startswith("AI 교육 운영 130")  # 가장 가까운 마감
    assert not any(b.startswith("AI 교육 운영 1 |") for b in bodies)  # 가장 먼 것은 다음 날
    assert fake.timeouts == [ai.TIME_LIMIT_SECONDS]


def test_시간_초과면_규칙만_받기는_성공(assist_on) -> None:
    from app.services import llm_client

    items = [_item(1, "세무 교육 운영")]
    fake = FakeAsk(error=llm_client.LLMUnavailableError("Claude CLI 가 240초 안에 답하지 않았습니다"))
    line = ai.run_daily(ORG, _listing(items), now=NOW, raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    assert line["호출_수"] == 1 and "240초" in line["실패_이유"]
    assert ai.load(ORG)["entries"] == {}
    assert ai.apply_notes(items, ORG) == 0 and items[0].ai_fit_note is None


def test_같은_공고는_다시_묻지_않고_공고명이_바뀌면_묻는다(assist_on) -> None:
    items = [_item(1, "세무 교육 운영")]
    fake = FakeAsk()
    ai.run_daily(ORG, _listing(items), now=NOW, raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    again = ai.run_daily(ORG, _listing([_item(1, "세무 교육 운영")]), now=NOW + timedelta(days=1), raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    assert again["건너뜀"] == "새로 물을 공고 없음" and len(fake.calls) == 1
    changed = ai.run_daily(ORG, _listing([_item(1, "세무 교육 운영(재공고)")]), now=NOW + timedelta(days=2), raw_of=_raw,
                           pre_raw_of=_pre_raw, ask=fake)
    assert changed["물은_수"] == 1 and len(fake.calls) == 2


def test_아님만_꼬리표_판정_점수_그대로_주제_확인_자리(assist_on) -> None:
    off = _item(1, "AI 행정 교육 운영", left=30)  # 주제 맞음이지만 AI 가 아님
    on = _item(2, "생성형 AI 실무 교육", left=5)
    fake = FakeAsk({"AI 행정 교육 운영": ("not_ours", "행정 업무 교육으로 본업과 거리 있음"), "생성형 AI 실무 교육": ("adjacent", "인접")})
    ai.run_daily(ORG, _listing([off, on]), now=NOW, raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    items = [_item(1, "AI 행정 교육 운영", left=30), _item(2, "생성형 AI 실무 교육", left=5)]
    p.annotate(items, now=NOW, ceiling_krw=CEILING)
    before = [(i.eligibility_gate, i.company_priority_score, i.practical_group, i.practical_block) for i in items]
    assert ai.apply_notes(items, ORG) == 1
    assert items[0].ai_fit_note == "AI: 본업 아닐 수 있음 · 행정 업무 교육으로 본업과 거리 있음" and items[1].ai_fit_note is None
    assert [(i.eligibility_gate, i.company_priority_score, i.practical_group, i.practical_block) for i in items] == before
    ordered = p.order(items, now=NOW, home_of=lambda _i: False)
    assert [i.id for i in ordered] == [items[1].id, items[0].id]  # 「주제 확인」과 같은 자리(뒤)
    assert p.tags_of(items[0]) == [items[0].ai_fit_note]


def test_CLI_는_한_번만_부른다(monkeypatch) -> None:
    from app.services import llm_client

    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return ai.AiFitAnswer(items=[ai.AiFitItem(n=1, label="core", reason="본업")])

    monkeypatch.setattr(llm_client, "claude_cli_path", lambda: "claude")
    monkeypatch.setattr(llm_client, "claude_cli_auth_status", lambda: {"loggedIn": True})  # 42차 로그인 확인
    monkeypatch.setattr(llm_client, "_complete_via_cli", fake)
    got = ai.ask_cli(["세무 교육 | 분류: 분류 없음 | 기관: 기관 | 예산: 미공개"])
    assert seen["attempts"] == 1 and seen["retry_token_race"] is False and seen["timeout"] == ai.TIME_LIMIT_SECONDS
    assert seen["system"] == ai.SYSTEM and got[1].label == "core"


def test_CLI_가_없으면_실패로_규칙만(monkeypatch) -> None:
    from app.services import llm_client

    monkeypatch.setattr(llm_client, "claude_cli_path", lambda: None)
    with pytest.raises(llm_client.LLMUnavailableError):
        ai.ask_cli(["x | 분류: 분류 없음 | 기관: 기관 | 예산: 미공개"])


def test_저장소는_Git_밖_회사_폴더(assist_on) -> None:
    from app.core import org_storage

    path = ai.store_path(ORG)
    assert path.parent == org_storage.storage_for(ORG).root and path.name == "ai_fit.json"  # 실제 PC 에서는 data/private/organizations/<org>/


def test_매일_받기_단계는_켠_회사가_없으면_건너뜀(monkeypatch) -> None:
    import asyncio
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("collect_daily_r40", Path(__file__).resolve().parents[2] / "scripts" / "collect_daily.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    row = asyncio.run(module._collect_ai_fit(NOW))
    assert row["출처"] == "AI 적합도" and "켠 회사가 없습니다" in row["건너뜀"]


@pytest.mark.parametrize(("company_line", "expected"), [
    ({"물은_수": 0, "아님_수": 0, "호출_수": 0, "실패_이유": "LLMUnavailableError: Claude CLI 가 아직 로그인되어 있지 않습니다"}, "묻지 못함"),
    ({"물은_수": 0, "아님_수": 0, "호출_수": 0, "실패_이유": None}, "새로 물을 것 없음"),
    ({"물은_수": 120, "아님_수": 0, "호출_수": 1, "실패_이유": "시간 초과"}, "물음"),
])
def test_매일_받기_단계_결과_낱말은_부르지_못한_날을_가린다(monkeypatch, company_line, expected) -> None:
    import asyncio
    import importlib.util
    from pathlib import Path

    from app.services import opportunity_service, organization_service

    spec = importlib.util.spec_from_file_location("collect_daily_r40b", Path(__file__).resolve().parents[2] / "scripts" / "collect_daily.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    async def listing(**_kwargs):
        return SimpleNamespace(items=[])

    monkeypatch.setattr(organization_service, "list_organizations", lambda include_inactive=False: [SimpleNamespace(organization_id=ORG)])
    monkeypatch.setattr(ai, "enabled", lambda _org: True)
    monkeypatch.setattr(opportunity_service, "list_opportunities", listing)
    monkeypatch.setattr(ai, "run_daily", lambda org, _listing, **_kw: {"회사": org, **company_line})
    row = asyncio.run(module._collect_ai_fit(NOW))
    assert row["결과"] == expected and row["실패_이유"] == company_line["실패_이유"]


def test_픽스처는_L2_결과_그대로_회사_값이_없다() -> None:
    from pathlib import Path

    for day in ("1016", "1019"):
        data = json.loads((Path(__file__).parent / "fixtures" / f"ai_fit_{day}.json").read_text(encoding="utf-8"))
        assert data["entries"] and data["prompt_version"] == ai.PROMPT_VERSION
        for entry in data["entries"].values():
            assert entry["label"] in ("core", "adjacent", "not_ours")
            assert re.match(r"^[^|]+ \| 분류: [^|]+ \| 기관: [^|]+ \| 예산: ", entry["sent"])
            assert ai.body_hash(entry["sent"]) == entry["hash"]


def test_브리핑_엑셀에_AI_판단_참고용_한_줄은_AI_꼬리표가_있을_때만() -> None:
    from app.services import opportunity_brief_service as brief

    items = [_item(1, "AI 행정 교육 운영", left=30), _item(2, "생성형 AI 실무 교육", left=5)]
    assert brief.ai_note_line(SimpleNamespace(items=items)) is None  # 키트 · 꺼 둔 회사
    items[0].ai_fit_note = "AI: 본업 아닐 수 있음 · 행정 업무 교육"
    line = brief.ai_note_line(SimpleNamespace(items=items))
    assert line and ai.REFERENCE_NOTE in line and "판정 · 점수" in line



def test_연락처_꼴이_섞인_공고만_빼고_묻는다(assist_on) -> None:
    """40차 마지막 검토 — 한 건 때문에 날마다 단계 전체가 건너뛰어졌다."""
    items = [_item(1, "AI 교육 운영 문의 010-1234-5678"), _item(2, "생성형 AI 실무 교육")]
    fake = FakeAsk()
    line = ai.run_daily(ORG, _listing(items), now=NOW, raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    (bodies,) = fake.calls
    assert line["물은_수"] == 1 and len(bodies) == 1 and bodies[0].startswith("생성형 AI 실무 교육")
    only_leak = ai.run_daily(ORG, _listing([_item(3, "교육 담당 a@b.kr")]), now=NOW + timedelta(days=1), raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    assert only_leak["건너뜀"].startswith("보낼 글에 연락처 꼴이 있어 묻지 않음") and len(fake.calls) == 1


def test_선제준비_보임에도_AI_꼬리표를_단다(assist_on) -> None:
    """40차 마지막 검토 — 선제준비도 묻는 대상인데 꼬리표를 달지 않았다(목록이 `apply_notes` 를 선제준비에도 부른다)."""
    import inspect

    from app.services import opportunity_service

    pre = _item(7, "AI 행정 업무 교육", pre=True)
    fake = FakeAsk({"AI 행정 업무 교육": ("not_ours", "행정 업무 교육")})
    ai.run_daily(ORG, _listing([pre]), now=NOW, raw_of=_raw, pre_raw_of=_pre_raw, ask=fake)
    again = _item(7, "AI 행정 업무 교육", pre=True)
    p.annotate([again], now=NOW, ceiling_krw=CEILING)
    assert ai.apply_notes([again], ORG) == 1 and again.ai_fit_note.startswith("AI: 본업 아닐 수 있음")
    assert "ai_fit_service.apply_notes(pre_items, organization_id)" in inspect.getsource(opportunity_service.list_opportunities)
