"""34차 §3-D — 사업 규모 · 회사자료 카드(R33-S1 · S6). 네트워크 0."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.core import org_storage
from app.schemas.delivery_capacity import DeliveryCapacityUpdate
from app.services import delivery_capacity_service, eligibility_engine
from tests.test_round33_budget import AS_OF, CEILING, raw


def _budget_rule(joint_partner: bool | None):
    rules = eligibility_engine.evaluate_notice_fields(
        raw(joint="(전자)공동이행"),
        as_of=AS_OF,
        company=eligibility_engine.CompanyFacts(budget_ceiling_krw=CEILING, joint_bid_available=joint_partner),
    )
    return next(r for r in rules if r.rule_id == "ELIG-BUDGET")


def test_R33_S1_파트너_있음이면_열리는_조건_없이_나눠_맡을지만() -> None:
    rule = _budget_rule(True)
    assert rule.status == "CHECK" and rule.check_side == "company"
    assert rule.unlock_condition is None  # 갖춘 것을 「갖추면 가능」으로 다시 약속하지 않는다
    assert rule.reason.endswith("함께 참가할 회사를 확보해 두었습니다 — 나눠 맡을지 정하세요.")
    # 모름 · 없음은 그대로 열쇠
    assert _budget_rule(None).unlock_condition == "공동수급 파트너 확보 시"
    assert _budget_rule(False).unlock_condition == "공동수급 파트너 확보 시"


def test_R33_S6_화면_저장이_파일의_손_메모_칸을_남긴다(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "delivery_capacity.json"
    path.write_text(json.dumps({"budget_ceiling_krw": 100, "_note": "담당자 손 메모", "_old": 1}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(org_storage, "storage_for", lambda org: SimpleNamespace(delivery_capacity_file=path))
    delivery_capacity_service.save("org-sample", DeliveryCapacityUpdate(budget_ceiling_krw=200_000_000, updated_by="시험"))
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["budget_ceiling_krw"] == 200_000_000
    assert saved["_note"] == "담당자 손 메모" and saved["_old"] == 1
    # 깨진 파일이어도 저장은 된다(옮길 메모가 없을 뿐)
    path.write_text("{ 깨짐", encoding="utf-8")
    delivery_capacity_service.save("org-sample", DeliveryCapacityUpdate(budget_ceiling_krw=1, updated_by="시험"))
    assert json.loads(path.read_text(encoding="utf-8"))["budget_ceiling_krw"] == 1
