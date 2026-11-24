"""43차 §2-H — 여러 사람이 한 회사 기록을 같이 쓸 때(M25 · TEAM-05 · Q28). 호출 없음.

- 처음 읽은 시각을 보내면 그사이 다른 사람이 저장했을 때 409 「… 님이 MM/DD HH:MM에 먼저 바꿨습니다」(회사 값 · 안 적음 · 회사 단위 확인 ·
  직접 넣기 · 오늘 열어 볼 곳 · 조항 확인). 보내지 않는 옛 화면 · 키트는 검사하지 않는다.
- 「열기」는 연 사람을 함께 적는다. 순서 방식 · 단독 상한 · AI 보조를 바꾸면 활동 기록에 전후 값이 남는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core import storage
from app.core.config import get_settings
from app.main import app
from app.schemas.delivery_capacity import DeliveryCapacityUpdate
from app.schemas.manual_notice import ManualNoticeInput, WatchSiteInput
from app.services import delivery_capacity_service, manual_notice_service, procurement_service
from app.services import qualification_clause_service as qc
from app.services import watchlist_service as watch

ORG = get_settings().default_organization_id
KST = timezone(timedelta(hours=9))


@pytest.fixture(autouse=True)
def _private_clauses(tmp_path, monkeypatch):
    monkeypatch.setattr(qc, "PRIVATE_CLAUSE_DIR", tmp_path / "qualification_clauses")
    monkeypatch.setattr(procurement_service, "load_cache", lambda: None)


def test_회사_값을_그사이_남이_바꿨으면_409() -> None:
    first = delivery_capacity_service.save(ORG, DeliveryCapacityUpdate(updated_by="대표", budget_ceiling_krw=300_000_000))
    opened_at = first.updated_at  # 김담당이 폼을 연 때
    delivery_capacity_service.save(ORG, DeliveryCapacityUpdate(updated_by="대표", budget_ceiling_krw=300_000_000, proposal_lead_days=5))
    with pytest.raises(storage.StaleWriteError) as caught:
        delivery_capacity_service.save(ORG, DeliveryCapacityUpdate(updated_by="김담당", budget_ceiling_krw=200_000_000, expected_updated_at=opened_at))
    assert caught.value.by == "대표" and "먼저 바꿨습니다" in str(caught.value)
    assert delivery_capacity_service.load(ORG).budget_ceiling_krw == 300_000_000  # 앞 저장이 남는다
    # 다시 불러온 시각이면 통과 · 보내지 않는 옛 화면은 검사하지 않는다
    fresh = delivery_capacity_service.load(ORG).updated_at
    delivery_capacity_service.save(ORG, DeliveryCapacityUpdate(updated_by="김담당", budget_ceiling_krw=300_000_000, expected_updated_at=fresh))
    delivery_capacity_service.save(ORG, DeliveryCapacityUpdate(updated_by="키트", budget_ceiling_krw=300_000_000))


def test_API_409는_화면이_알아보는_꼴이고_안_적음_회사_확인도_막는다() -> None:
    client = TestClient(app)
    base = f"?organization_id={ORG}"
    saved = client.put(f"/api/capability/profile{base}", json={"updated_by": "대표", "proposal_lead_days": 4}).json()
    stale = "2026-01-01T00:00:00Z"
    res = client.put(f"/api/capability/profile{base}", json={"updated_by": "김담당", "proposal_lead_days": 4, "expected_updated_at": stale})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "stale_write"
    assert "대표 님이" in res.json()["detail"]["message"]
    assert client.put(f"/api/capability/left-blank{base}", json={"keys": [], "updated_by": "김담당", "expected_updated_at": stale}).status_code == 409
    assert client.put(f"/api/capability/company-checks{base}", json={"checks": {}, "updated_by": "김담당", "expected_updated_at": stale}).status_code == 409
    ok = client.put(f"/api/capability/left-blank{base}", json={"keys": [], "updated_by": "김담당", "expected_updated_at": saved["updated_at"]})
    assert ok.status_code == 200


def test_순서_방식_상한_AI_보조_바꾸면_활동_기록에_전후_값(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import audit_log_service

    lines: list[dict] = []
    monkeypatch.setattr(audit_log_service, "append", lambda **kw: lines.append(kw) or True)
    client = TestClient(app)
    base = f"?organization_id={ORG}"
    client.put(f"/api/capability/profile{base}", json={"updated_by": "대표", "budget_ceiling_krw": 200_000_000, "ranking_method": "score"})
    lines.clear()
    client.put(f"/api/capability/profile{base}", json={"updated_by": "대표", "budget_ceiling_krw": 300_000_000, "ranking_method": "practical"})
    events = [kw["event"] for kw in lines if kw.get("event")]
    assert events == [{"kind": "capacity_setting", "ranking_method": "score → practical", "budget_ceiling_krw": "200000000 → 300000000"}]
    lines.clear()
    client.put(f"/api/capability/profile{base}", json={"updated_by": "대표", "budget_ceiling_krw": 300_000_000, "proposal_lead_days": 6})
    assert not [kw for kw in lines if kw.get("event")]  # 그 밖의 칸은 줄을 더하지 않는다


def _manual() -> ManualNoticeInput:
    return ManualNoticeInput(
        url="https://www.kosac.re.kr/menus/274/bns/PBANC_00000000000999", title="AI 교육 운영 수행기관 모집", agency="한국과학창의재단",
        deadline=datetime(2026, 11, 30, 16, 0, tzinfo=KST), recruit="operator", methods=["PMS/기관시스템"],
    )


def test_직접_넣기_옛_폼이_남의_마감_고침을_되돌리지_않는다() -> None:
    notice = manual_notice_service.create(ORG, _manual(), created_by="김담당").notice
    opened_at = notice.updated_at
    moved = _manual().model_copy(update={"deadline": datetime(2026, 11, 20, 16, 0, tzinfo=KST)})
    manual_notice_service.update(ORG, notice.id, moved, updated_by="대표", expected_updated_at=opened_at, now=opened_at + timedelta(minutes=5))
    with pytest.raises(storage.StaleWriteError) as caught:
        manual_notice_service.update(ORG, notice.id, _manual(), updated_by="김담당", expected_updated_at=opened_at)
    assert caught.value.by == "대표"
    assert manual_notice_service.get(ORG, notice.id).deadline.astimezone(KST).day == 20


def test_열어_볼_곳_옛_목록으로_저장하면_409_열기는_연_사람을_적는다() -> None:
    base = [WatchSiteInput(id=s.id, name=s.name, url=s.url, layer=s.layer, memo=s.memo) for s in watch.load(ORG)]
    added = base + [WatchSiteInput(name="대표가 더한 게시판", url="https://www.nipa.kr/home/2-2")]
    watch.replace(ORG, added, base=base, saved_by="대표")
    with pytest.raises(storage.StaleWriteError) as caught:
        watch.replace(ORG, base[:3], base=base, saved_by="김담당")  # 옛 목록으로 저장 — 대표가 더한 곳이 지워질 뻔했다
    assert caught.value.by == "대표"
    assert any(s.name == "대표가 더한 게시판" for s in watch.load(ORG))
    site = next(s for s in watch.load(ORG) if s.url)
    assert watch.mark_opened(ORG, site.id, by="김담당").last_opened_by == "김담당"
    assert next(s for s in watch.load(ORG) if s.id == site.id).last_opened_by == "김담당"


def test_저장_응답의_시각은_파일에_찍힌_시각과_같다() -> None:
    """43차 — 응답 시각(모델을 만든 순간)과 파일 시각(`stamp`)이 달라 화면이 받은 시각으로 다음 저장을 하면 409 였다(서버 시계 · +7일 시험)."""
    saved = delivery_capacity_service.save(ORG, DeliveryCapacityUpdate(updated_by="대표", proposal_lead_days=4))
    assert saved.updated_at == delivery_capacity_service.load(ORG).updated_at
    delivery_capacity_service.save(ORG, DeliveryCapacityUpdate(updated_by="대표", proposal_lead_days=5, expected_updated_at=saved.updated_at))
