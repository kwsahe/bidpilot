"""개발 수행역량 회사자료 읽기·쓰기.

파일이 없으면 **비어 있는 자료**(`source="absent"`)를 돌려준다. 기본값을 지어내지 않는다 —
「적혀 있지 않다」와 「없다」는 다른 말이고, 이 구분이 무너지면 판정이 거짓말을 하기 시작한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core import org_storage, storage
from app.schemas.delivery_capacity import (
    DELIVERY_CAPACITY_SCHEMA_VERSION,
    DeliveryCapacity,
    DeliveryCapacityUpdate,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load(organization_id: str) -> DeliveryCapacity:
    """조직의 개발 수행역량. 파일이 없거나 깨졌으면 `source="absent"`."""
    store = org_storage.storage_for(org_storage.validate_organization_id(organization_id))
    try:
        payload = storage.read_json(store.delivery_capacity_file, default=None)
    except storage.CorruptJsonError:
        payload = None
    if not isinstance(payload, dict):
        return DeliveryCapacity(organization_id=organization_id, source="absent")

    data = dict(payload)
    data["organization_id"] = organization_id
    data["source"] = "file"
    try:
        return DeliveryCapacity.model_validate(data)
    except ValueError:
        # 사람이 손으로 고치다 형식을 깨뜨릴 수 있다. 그때도 «없는 것»으로 다루고
        # 판정을 멈춘다 — 반쯤 읽은 회사자료로 수행 가능 여부를 말하지 않는다.
        return DeliveryCapacity(organization_id=organization_id, source="absent")


def ensure_fresh(organization_id: str, expected: datetime | None) -> None:
    """처음 읽은 뒤 다른 사람이 먼저 저장했으면 `StaleWriteError`(43차 M25 — 나중 저장이 말없이 되돌리지 않게)."""
    current = load(organization_id)
    storage.ensure_unchanged(current.updated_at, expected, stored_by=current.updated_by)


def save(organization_id: str, update: DeliveryCapacityUpdate) -> DeliveryCapacity:
    org_id = org_storage.validate_organization_id(organization_id)
    if "expected_updated_at" in update.model_fields_set:
        ensure_fresh(org_id, update.expected_updated_at)
    fields = update.model_dump(exclude={"expected_updated_at"})
    if fields.get("ranking_method") is None:
        # 순서 방식을 비워 보냈으면 저장된 값을 둔다 — 이 칸을 모르는 화면이 저장해도 회사가 고른 방식이 남는다(37차 §3-A).
        fields["ranking_method"] = load(org_id).ranking_method
    if fields.get("ai_fit_assist") is None:
        # AI 적합도 보조 설정(40차)도 같다 — 비워 보내면 저장된 값(없으면 꺼짐)을 둔다.
        fields["ai_fit_assist"] = load(org_id).ai_fit_assist
    if fields.get("left_blank") is None:
        # 「안 적음」 칸(41차 D31)도 같다 — 입찰 자격 자료 저장이 지우지 않는다.
        fields["left_blank"] = load(org_id).left_blank
    for keep in ("company_checks", "direct_production_items", "digital_products"):
        if fields.get(keep) is None:
            # 회사 단위 확인 · 직접생산 품명(43차)도 같다 — 이 칸을 모르는 화면 · 키트가 저장해도 지우지 않는다.
            fields[keep] = getattr(load(org_id), keep)
    capacity = DeliveryCapacity.model_validate(
        {
            **fields,
            "organization_id": org_id,
            "updated_at": _now(),
            "source": "file",
        }
    )
    payload = capacity.model_dump(mode="json")
    path = org_storage.storage_for(org_id).delivery_capacity_file
    # 사람이 파일에 손으로 적은 `_` 칸(`_note` 등)은 모델 밖이라 화면 저장이 지웠다(34차 R33-S6). 그대로 옮긴다.
    try:
        previous = storage.read_json(path, default=None)
    except storage.CorruptJsonError:
        previous = None
    if isinstance(previous, dict):
        payload.update({k: v for k, v in previous.items() if k.startswith("_") and k not in payload})
    storage.stamp(payload, schema_version=DELIVERY_CAPACITY_SCHEMA_VERSION)
    storage.write_json_atomic(path, payload)
    # 43차 — 파일에 찍힌 시각(`stamp`)을 돌려준다. 모델을 만든 순간과 달라(서버 시계는 마이크로초까지 다르다) 화면이 받은 시각으로
    # 다음 저장을 하면 버전 확인(M25)이 「먼저 바꿨습니다」로 막았다(+7일 시험에서 드러남).
    capacity = capacity.model_copy(update={"updated_at": datetime.fromisoformat(payload["updated_at"])})
    # 목록이 들고 있던 지원사업 판정은 이 값들로 잰 것이다 — 바뀌었으니 버린다 (0922 §4-D-3).
    # 늦게 들여온다: 모듈 맨 위에서 부르면 import 고리가 생긴다.
    from app.services import opportunity_service

    opportunity_service.clear_support_memo()
    return capacity


def set_company_checks(organization_id: str, checks: dict[str, Any], *, updated_by: str) -> DeliveryCapacity:
    """회사 단위 확인 칸만 바꾼다(43차 결정 2) — 값이 None 인 열쇠는 지운다. 열쇠는 부르는 쪽이 검사한다."""
    current = load(organization_id)
    merged = {k: v.model_dump(mode="json") for k, v in current.company_checks.items()}
    for key, value in checks.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    update = DeliveryCapacityUpdate.model_validate({
        **current.model_dump(include=set(DeliveryCapacityUpdate.model_fields) - {"updated_by", "company_checks"}),
        "updated_by": updated_by,
        "company_checks": merged,
    })
    return save(organization_id, update)


def set_left_blank(organization_id: str, keys: list[str], *, updated_by: str) -> DeliveryCapacity:
    """「안 적음(그대로 둠)」 칸만 바꾼다(41차 D31) — 다른 칸은 저장된 값 그대로. 열쇠는 부르는 쪽이 검사한다."""
    current = load(organization_id)
    update = DeliveryCapacityUpdate.model_validate({
        **current.model_dump(include=set(DeliveryCapacityUpdate.model_fields) - {"updated_by", "left_blank"}),
        "updated_by": updated_by,
        "left_blank": list(dict.fromkeys(keys)),
    })
    return save(organization_id, update)
