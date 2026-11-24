"""개발 수행역량 API.

- GET /api/capability/{procurement_id}   이 공고를 우리 개발진이 수행할 수 있는지 판정한다

판정은 **읽기 전용**이다. 저장하지 않고, GO/NO-GO 나 자격판정을 바꾸지 않는다.
매번 다시 계산해도 되는 규칙 판정이라 분석 결과를 파일로 남기지 않는다 —
회사 역량자료가 바뀌면 다음 조회에서 바로 반영되는 편이 낫다.

파싱된 요구사항이 있으면 그 본문까지 읽는다. 없으면 공고명·요약만 보고 판정하며,
그 사실을 `used_requirements=False` 로 응답에 남긴다 — 제목만으로 분야를 단정하지 않기 위해서다.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from pydantic import Field as PydField

from app.api import deps
from app.core import requester, storage
from app.schemas.capability import CapabilityReport
from app.schemas.delivery_capacity import COMPANY_CHECK_LABELS, CompanyCheck, DeliveryCapacity, DeliveryCapacityUpdate
from app.services import (
    audit_log_service,
    capability_service,
    delivery_capacity_service,
    procurement_service,
    rfp_parser,
)

router = APIRouter(tags=["capability"])


def _check_id(procurement_id: str) -> str:
    try:
        return storage.safe_id(procurement_id, what="공고 id")
    except storage.InvalidIdError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def _requirement_text(procurement_id: str) -> tuple[str, str]:
    """파싱된 요구사항 본문과 그 출처. 아직 파싱 전이면 ("", "")."""
    try:
        parsed = rfp_parser.load_generated(procurement_id)
    except Exception:  # noqa: BLE001 — 파싱 전·픽스처 없음 모두 «원문 없음»으로 다룬다
        return "", ""
    chunks: list[str] = []
    for req in parsed.requirements:
        chunks.append(req.content or "")
        if req.source_text and req.source_text != req.content:
            chunks.append(req.source_text)
    text = "\n".join(c for c in chunks if c.strip())
    where = f"{parsed.document} (파싱된 요구사항 {len(parsed.requirements)}건)" if text else ""
    return text, where


# 고정 경로를 **먼저** 등록한다. `/{procurement_id}` 를 앞에 두면 "profile" 이 공고 id 로 잡힌다.
@router.get("/api/capability/profile", response_model=DeliveryCapacity)
def get_capacity(organization_id: str | None = Query(default=None)) -> DeliveryCapacity:
    """회사 개발역량 자료. 없으면 `source="absent"` 로 빈 자료를 돌려준다."""
    context = deps.context_or_400(organization_id, None)
    return delivery_capacity_service.load(context.organization_id)


@router.put("/api/capability/profile", response_model=DeliveryCapacity)
def put_capacity(
    body: DeliveryCapacityUpdate, organization_id: str | None = Query(default=None)
) -> DeliveryCapacity:
    """회사 개발역량 자료를 저장한다. 담당자가 적는 자료이며 시스템이 채우지 않는다.

    공개 데모 배포에서는 쓰기를 막는다 (ISSUE-026). 다른 쓰기 경로에는 이 검사가 있었는데
    여기만 빠져 있었다 — 공개 링크에서 누구나 회사 수행역량 자료를 바꿀 수 있었다.
    """
    deps.require_writable()
    context = deps.context_or_400(organization_id, None)
    before = delivery_capacity_service.load(context.organization_id)
    saved = delivery_capacity_service.save(context.organization_id, body)
    # 순서 방식 · 단독 상한 · AI 보조는 사업기회 순서 전체를 바꾼다 — 활동 기록에 전후 값을 남긴다(43차 Q28 · 값만 · 메모 없음).
    changed = {
        key: f"{getattr(before, key)} → {getattr(saved, key)}"
        for key in ("ranking_method", "budget_ceiling_krw", "ai_fit_assist")
        if getattr(before, key) != getattr(saved, key)
    }
    if changed:
        who = requester.current()
        audit_log_service.append(
            user=who.user if who is not None else body.updated_by,
            role=who.role if who is not None else "local",
            method="PUT",
            path="/api/capability/profile",
            organization_id=context.organization_id,
            status=200,
            event={"kind": "capacity_setting", **changed},
        )
    return saved


class LeftBlankUpdate(BaseModel):
    """「안 적음(그대로 둠)」 칸 열쇠 전부(41차 D31) — 빈 목록이면 모두 되돌린다."""

    keys: list[str] = PydField(default_factory=list, max_length=20)
    updated_by: str = PydField(min_length=1, max_length=60)
    expected_updated_at: datetime | None = None


@router.put("/api/capability/left-blank", response_model=DeliveryCapacity)
def put_left_blank(body: LeftBlankUpdate, organization_id: str | None = Query(default=None)) -> DeliveryCapacity:
    """빈 회사 칸을 「안 적음(그대로 둠)」으로 고른다(41차 D31). 판정은 바뀌지 않는다 — 빈칸 안내에서만 빠진다. 회사 값은 쓰지 않는다."""
    from app.services import company_blank_fields

    deps.require_writable()
    context = deps.context_or_400(organization_id, None)
    unknown = [k for k in body.keys if k not in company_blank_fields.FIELD_KEYS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"알 수 없는 칸입니다: {', '.join(unknown)}")
    if "expected_updated_at" in body.model_fields_set:
        delivery_capacity_service.ensure_fresh(context.organization_id, body.expected_updated_at)
    return delivery_capacity_service.set_left_blank(context.organization_id, body.keys, updated_by=body.updated_by)


class CompanyChecksUpdate(BaseModel):
    """회사 단위 확인(43차 결정 2) — 열쇠마다 확인일 · 유효기간 · 확인한 사람, 또는 None(지움)."""

    checks: dict[str, CompanyCheck | None] = PydField(default_factory=dict)
    updated_by: str = PydField(min_length=1, max_length=60)
    expected_updated_at: datetime | None = None


@router.put("/api/capability/company-checks", response_model=DeliveryCapacity)
def put_company_checks(body: CompanyChecksUpdate, organization_id: str | None = Query(default=None)) -> DeliveryCapacity:
    """나라장터 등록 · 부정당 제재 없음 · 체납 없음을 회사 단위로 한 번 확인한다(43차 결정 2). 프로그램은 값을 고르지 않는다."""
    deps.require_writable()
    context = deps.context_or_400(organization_id, None)
    unknown = [k for k in body.checks if k not in COMPANY_CHECK_LABELS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"알 수 없는 확인 칸입니다: {', '.join(unknown)}")
    for key, check in body.checks.items():
        if check is not None and check.valid_until < check.confirmed_on:
            raise HTTPException(status_code=400, detail=f"{COMPANY_CHECK_LABELS[key]} — 유효기간이 확인일보다 앞입니다.")
    if "expected_updated_at" in body.model_fields_set:
        delivery_capacity_service.ensure_fresh(context.organization_id, body.expected_updated_at)
    payload = {k: (v.model_dump(mode="json") if v is not None else None) for k, v in body.checks.items()}
    return delivery_capacity_service.set_company_checks(context.organization_id, payload, updated_by=body.updated_by)


@router.get("/api/capability/blank-fields")
async def get_blank_fields(
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> dict:
    """비어 있어서 판정이 멈춘 회사자료 칸과 그 칸 때문에 「확인 필요」로 남은 공고 수 (38차 §3-C-7). 읽기 전용."""
    from app.services import company_blank_fields

    context = deps.context_or_400(organization_id, evidence_scope)
    return await company_blank_fields.build(context)


@router.get("/api/capability/{procurement_id}", response_model=CapabilityReport)
async def get_capability(
    procurement_id: str,
    organization_id: str | None = Query(default=None),
    evidence_scope: str | None = Query(default=None),
) -> CapabilityReport:
    procurement_id = _check_id(procurement_id)
    context = deps.context_or_400(organization_id, evidence_scope, procurement_id=procurement_id)
    try:
        view = await procurement_service.get_notice(procurement_id)
    except procurement_service.NoNoticeDataError as exc:
        raise HTTPException(status_code=503, detail=f"나라장터 조회 실패, 캐시도 없음: {exc}")
    if view is None:
        raise HTTPException(status_code=404, detail="현재 후보 목록에 없는 공고입니다")

    text, where = _requirement_text(procurement_id)
    return capability_service.evaluate(
        view.notice,
        organization_id=context.organization_id,
        requirement_text=text,
        requirement_where=where or "과업 원문",
    )
