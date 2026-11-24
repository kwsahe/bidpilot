"""조직(회사) 등록부·프로필 서비스.

- 등록부: data/private/organizations/registry.json (조직 목록). 조직별 파일은 org_storage 가 경로를 정한다.
- 기본 조직 `org-sample`은 등록부에 없으면 만든다 (표시명·등급은 제품 원칙에서 정한 값이며 추정이 아니다).
- 프로필: 조직 폴더 profile.json → (기본 조직만) 레거시 data/company/company_profile.json → 합성 기본값.
  합성 기본값에는 `source=default_synthetic`, `data_class=synthetic` 이 붙는다. 실제 값을 지어내지 않는다.
- 분석 컨텍스트 해석(`resolve_context`)은 **호환 계층**이다. 핵심 서비스는 항상 명시된 컨텍스트를 받는다.
- 인증은 아직 없다 (로컬 관리자 모드). 생성·수정·승인자 필드는 남겨 두어 나중에 사용자 권한을 붙일 수 있게 한다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core import org_storage, storage
from app.core import auth
from app.core.config import get_settings
from app.schemas.organization import (
    API_EVIDENCE_SCOPES,
    AnalysisContext,
    Organization,
    OrganizationCreateRequest,
    OrganizationListResponse,
    OrganizationProfile,
    OrganizationProfileUpdate,
    OrganizationSummary,
    OrganizationUpdateRequest,
    PlanGeneralInfo,
    PlanGeneralUpdate,
)
from app.services import company_service, llm_client

logger = logging.getLogger(__name__)

DEFAULT_ORGANIZATION_ID = org_storage.DEFAULT_ORGANIZATION_ID

# 기본 조직 — 샘플에듀 실제자료의 소유 조직. 값은 제품 원칙(브리프)에서 정한 것이다.
DEFAULT_ORGANIZATION: dict[str, Any] = {
    "organization_id": DEFAULT_ORGANIZATION_ID,
    # 이름은 설정에서(30차 §3-G 키트 — 첫 실행이 받은 회사 이름). 기본값은 그대로 「주식회사 샘플에듀」.
    "display_name": get_settings().default_organization_name or DEFAULT_ORGANIZATION_ID,
    "legal_name": None,
    "status": "active",
    "data_class": "real",
    "approved_for_public": False,
}

# 합성 프로필 기본값 (CLAUDE.md 6장). 파일이 없을 때만 쓰며 화면에 "합성 기본값"으로 표시된다.
DEFAULT_SYNTHETIC_PROFILE: dict[str, Any] = {
    "name": "샘플에듀",
    "business_domains": [
        "AI 활용 교육",
        "생성형 AI 교육",
        "ChatGPT / Copilot 활용 교육",
        "업무자동화 교육",
        "디지털 역량 교육",
        "AI 컨설팅",
        "ESG 교육 및 컨설팅",
    ],
    "target_clients": ["공공기관", "대학", "기업", "교육기관"],
    "preferred_regions": ["광주광역시", "전라남도", "전국"],
    "certifications": [],
    "data_class": "synthetic",
    "approved_for_public": True,
}

# 프로필 공개 응답에서 기본 제외하는 항목 (사업자등록번호·개인 연락처 등은 스키마에 아예 없다).
PROFILE_PRIVATE_KEYS: tuple[str, ...] = ("business_registration_number", "corporate_number", "representative_phone", "representative_email",
                                          # 사업계획서 일반현황(대표자 · 사업자등록번호 · 매출 …) — 전용 API 로만 읽는다 (29차 §3-B)
                                          "plan_general")


class OrganizationNotFoundError(LookupError):
    """등록되지 않은 organization_id."""


class OrganizationExistsError(ValueError):
    """이미 있는 organization_id."""


class OrganizationInactiveError(ValueError):
    """비활성 조직으로는 분석·등록을 시작할 수 없다."""


class PublicDemoWriteError(PermissionError):
    """공개 배포(읽기 전용 데모) 모드에서는 회사 생성·자료 업로드·승인을 막는다."""


class InvalidEvidenceScopeError(ValueError):
    """운영 API에서 고를 수 없는 근거 범위 (explicit_test 등)."""


class OrganizationRegistryUnavailableError(RuntimeError):
    """조직 등록부 JSON 이 깨져 읽지 못했다 (원본은 storage 가 `.corrupt-*` 로 격리).

    여기서 빈 목록으로 뭉개면 `ensure_default_organization` 이 기본 조직만 다시 만들어
    「등록해 둔 회사들이 사라지고 샘플에듀 하나만 남은」 화면이 된다. 사실을 그대로 올려 보낸다.
    """

    def __init__(self, quarantined: Path | None) -> None:
        self.quarantined = quarantined
        where = f" (원본 보관: {quarantined.name})" if quarantined else ""
        super().__init__(f"조직 등록부를 읽지 못했습니다{where}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# 등록부
# --------------------------------------------------------------------------


def registry_quarantine_files() -> list[Path]:
    """등록부가 깨져 격리된 파일 목록 (`registry.json.corrupt-*`).

    깨진 파일은 첫 읽기에서 격리되므로 예외는 한 번만 난다 — 그 다음부터는 「파일 없음 = 빈 등록부」다.
    사실이 남는 곳은 이 격리 파일뿐이라, 조용한 「회사 없음」과 구분하려면 여기를 봐야 한다.
    """
    parent = org_storage.registry_file().parent
    if not parent.exists():
        return []
    return sorted(parent.glob(f"{org_storage.REGISTRY_FILE_NAME}.corrupt-*"))


def _read_registry() -> list[Organization]:
    try:
        payload = storage.read_json(org_storage.registry_file(), default=None)
    except storage.CorruptJsonError as exc:
        # 로그에는 파일명만 남긴다 (등록부 내용·회사명은 남기지 않는다).
        logger.error("조직 등록부를 읽지 못했습니다 (격리=%s)", exc.quarantined.name if exc.quarantined else "격리 실패")
        raise OrganizationRegistryUnavailableError(exc.quarantined) from exc
    if not isinstance(payload, dict):
        return []
    return [Organization.model_validate(item) for item in payload.get("organizations", [])]


def _write_registry(organizations: list[Organization]) -> None:
    payload: dict[str, Any] = {
        "_note": "조직(회사) 등록부. 내부 전용 — Git에 올리지 않는다. 회사별 자료는 같은 폴더의 {organization_id}/ 아래.",
        "organizations": [o.model_dump(mode="json") for o in organizations],
    }
    storage.stamp(payload, schema_version=1)
    storage.write_json_atomic(org_storage.registry_file(), payload)


def ensure_default_organization() -> Organization:
    """기본 조직 등록부 항목이 없으면 만든다 (멱등). 레거시 폴더가 있으면 migrated_from_legacy 표시는 마이그레이션 스크립트가 찍는다."""
    organizations = _read_registry()
    for org in organizations:
        if org.organization_id == DEFAULT_ORGANIZATION_ID:
            return org
    if not organizations and not org_storage.registry_file().exists():
        quarantined = registry_quarantine_files()
        if quarantined:
            # 깨진 등록부가 격리된 뒤 다시 부르면 「빈 등록부」로 보여 기본 조직만 되살아난다.
            # 담당자 화면에서는 등록해 둔 회사들이 조용히 사라진 것처럼 보이므로 사실을 남긴다.
            logger.error(
                "조직 등록부가 손상되어 격리됐습니다 (%s). 기본 조직만 다시 만듭니다 — 나머지 회사 항목은 격리 파일에 있습니다.",
                ", ".join(p.name for p in quarantined),
            )
    now = _now()
    org = Organization(**DEFAULT_ORGANIZATION, created_at=now, updated_at=now, created_by="system", updated_by="system")
    organizations.append(org)
    _write_registry(organizations)
    return org


def list_organizations(*, include_inactive: bool = True) -> list[Organization]:
    ensure_default_organization()
    organizations = _read_registry()
    if not include_inactive:
        organizations = [o for o in organizations if o.status == "active"]
    return sorted(organizations, key=lambda o: (o.organization_id != DEFAULT_ORGANIZATION_ID, o.created_at))


def get_organization(organization_id: str) -> Organization:
    org_id = org_storage.validate_organization_id(organization_id)
    ensure_default_organization()
    for org in _read_registry():
        if org.organization_id == org_id:
            return org
    raise OrganizationNotFoundError(org_id)


def require_active(organization_id: str) -> Organization:
    org = get_organization(organization_id)
    if org.status != "active":
        raise OrganizationInactiveError(org.organization_id)
    return org


def create_organization(request: OrganizationCreateRequest) -> Organization:
    ensure_default_organization()
    organizations = _read_registry()
    taken = {o.organization_id for o in organizations}
    if request.organization_id:
        org_id = org_storage.validate_organization_id(request.organization_id)
        if org_id in taken:
            raise OrganizationExistsError(org_id)
    else:
        org_id = org_storage.suggest_organization_id(request.display_name, taken=taken)
    now = _now()
    org = Organization(
        organization_id=org_id,
        display_name=request.display_name.strip(),
        legal_name=(request.legal_name or "").strip() or None,
        status="active",
        data_class=request.data_class,
        approved_for_public=request.approved_for_public,
        created_at=now,
        created_by=request.created_by,
        updated_at=now,
        updated_by=request.created_by,
        note=request.note,
    )
    organizations.append(org)
    _write_registry(organizations)
    # 저장공간을 미리 만든다 (빈 폴더). 파일은 실제로 쓸 때 만든다.
    org_storage.storage_for(org_id).root.mkdir(parents=True, exist_ok=True)
    return org


def update_organization(organization_id: str, request: OrganizationUpdateRequest) -> Organization:
    org_id = org_storage.validate_organization_id(organization_id)
    organizations = _read_registry()
    for index, org in enumerate(organizations):
        if org.organization_id != org_id:
            continue
        updates: dict[str, Any] = {"updated_at": _now(), "updated_by": request.updated_by}
        if request.display_name is not None:
            updates["display_name"] = request.display_name.strip()
        if request.legal_name is not None:
            updates["legal_name"] = request.legal_name.strip() or None
        if request.data_class is not None:
            updates["data_class"] = request.data_class
        if request.approved_for_public is not None:
            updates["approved_for_public"] = request.approved_for_public
        if request.note is not None:
            updates["note"] = request.note
        organizations[index] = org.model_copy(update=updates)
        _write_registry(organizations)
        return organizations[index]
    raise OrganizationNotFoundError(org_id)


def set_status(organization_id: str, status: str, *, updated_by: str) -> Organization:
    org_id = org_storage.validate_organization_id(organization_id)
    organizations = _read_registry()
    for index, org in enumerate(organizations):
        if org.organization_id == org_id:
            organizations[index] = org.model_copy(update={"status": status, "updated_at": _now(), "updated_by": updated_by})
            _write_registry(organizations)
            return organizations[index]
    raise OrganizationNotFoundError(org_id)


def mark_migrated(organization_id: str, *, updated_by: str) -> Organization:
    org_id = org_storage.validate_organization_id(organization_id)
    organizations = _read_registry()
    for index, org in enumerate(organizations):
        if org.organization_id == org_id:
            organizations[index] = org.model_copy(update={"migrated_from_legacy": True, "updated_at": _now(), "updated_by": updated_by})
            _write_registry(organizations)
            return organizations[index]
    raise OrganizationNotFoundError(org_id)


# --------------------------------------------------------------------------
# 프로필
# --------------------------------------------------------------------------


def _strip_private(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k not in PROFILE_PRIVATE_KEYS}


def load_profile(organization_id: str) -> OrganizationProfile:
    org = get_organization(organization_id)
    store = org_storage.storage_for(org.organization_id)
    own = store.profile_file
    payload = storage.read_json(own, default=None)
    source = "file"
    if not isinstance(payload, dict):
        legacy = store.legacy_path("profile")
        if legacy is not None and legacy.exists():
            payload = storage.read_json(legacy, default=None)
            source = "legacy_file"
    if isinstance(payload, dict):
        data = _strip_private(dict(payload))
        data["organization_id"] = org.organization_id
        data["source"] = source
        data.setdefault("name", org.display_name)
        return OrganizationProfile.model_validate(data)

    base = dict(DEFAULT_SYNTHETIC_PROFILE)
    if get_settings().neutral_company_defaults:
        # 키트(범용 설치) — 샘플에듀 사업영역 · 고객 · 지역을 남의 회사에 넣지 않는다(30차 §3-G). 비어 있으면 「회사 정보 필요」.
        base.update(business_domains=[], target_clients=[], preferred_regions=[])
    base["organization_id"] = org.organization_id
    base["name"] = org.display_name
    # 기본 조직만 공개 사업자 정보(company_identity.json: 상호·주소·전화)를 덧입힌다. 개인정보 필드는 없다.
    identity_path = store.legacy_path("identity")
    identity = storage.read_json(identity_path, default=None) if identity_path is not None else None
    if isinstance(identity, dict):
        base["name"] = str(identity.get("name") or base["name"])
        base["address"] = identity.get("address")
        base["phone"] = identity.get("phone")
    base["source"] = "default_synthetic"
    return OrganizationProfile.model_validate(base)


def save_profile(organization_id: str, update: OrganizationProfileUpdate) -> OrganizationProfile:
    org = get_organization(organization_id)
    if "expected_updated_at" in update.model_fields_set:
        # 44차 TEAM-R36-01 — 처음 읽은 뒤 다른 사람이 먼저 저장했으면 막는다(활동 지역 · 인증을 말없이 되돌리지 않게)
        current = load_profile(org.organization_id)
        storage.ensure_unchanged(current.updated_at, update.expected_updated_at, stored_by=current.updated_by)
    profile = OrganizationProfile.model_validate(
        {**update.model_dump(exclude={"expected_updated_at"}), "organization_id": org.organization_id, "updated_at": _now(), "source": "file"}
    )
    payload = profile.model_dump(mode="json")
    path = org_storage.storage_for(org.organization_id).profile_file
    previous = storage.read_json(path, default=None)
    if isinstance(previous, dict) and isinstance(previous.get("plan_general"), dict):
        payload["plan_general"] = previous["plan_general"]  # 프로필 저장이 일반현황을 지우지 않게 (29차 §3-B)
    else:
        alone = storage.read_json(_plan_general_file(org.organization_id), default=None)
        if isinstance(alone, dict):
            payload["plan_general"] = alone  # 30차 R29-01 — 따로 둔 일반현황을 프로필 파일로
    storage.stamp(payload, schema_version=1)
    storage.write_json_atomic(path, payload)
    # 파일에 찍힌 시각을 돌려준다 — 화면이 이 시각으로 다음 저장의 버전 확인을 한다(43차 c55f998 과 같은 함정)
    profile = profile.model_copy(update={"updated_at": datetime.fromisoformat(payload["updated_at"])})
    # 사업영역 · 인증 · 설립 연도는 지원사업 판정 · 점수의 입력이다 — 옛 판정 메모를 버린다(31차 R30-06). 늦게 들여온다(import 고리).
    from app.services import opportunity_service

    opportunity_service.clear_support_memo()
    return profile


def _plan_general_file(organization_id: str):
    """프로필 파일이 없는 회사의 일반현황 — `plan_general.json`(30차 R29-01). 합성 기본 프로필을 파일로 굳히지 않는다."""
    return org_storage.storage_for(organization_id).profile_file.with_name("plan_general.json")


def load_plan_general(organization_id: str) -> PlanGeneralInfo:
    """사업계획서 일반현황 (29차 §3-B). `profile.json` 의 칸 → 없으면 `plan_general.json` → 없으면 빈 값(지어내지 않는다)."""
    org = get_organization(organization_id)
    payload = storage.read_json(org_storage.storage_for(org.organization_id).profile_file, default=None)
    raw = payload.get("plan_general") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        raw = storage.read_json(_plan_general_file(org.organization_id), default=None)
    try:
        return PlanGeneralInfo.model_validate(raw) if isinstance(raw, dict) else PlanGeneralInfo()
    except ValueError:
        logger.warning("일반현황을 읽지 못했습니다(형식) — 빈 값으로 봅니다 (organization_id=%s)", org.organization_id)
        return PlanGeneralInfo()


def save_plan_general(organization_id: str, update: PlanGeneralUpdate) -> PlanGeneralInfo:
    """일반현황을 `profile.json` 의 `plan_general` 에 저장한다. 프로필이 아직 파일이 아니면 `plan_general.json` 에만 —
    합성 기본 프로필을 「저장된 프로필」로 굳히지 않는다(30차 R29-01 · 「저장 필요」 경고 · 판정 · 점수가 그대로)."""
    org = get_organization(organization_id)
    if "expected_updated_at" in update.model_fields_set:
        # 44차 TEAM-R36-01 — 처음 읽은 뒤 다른 사람이 일반현황을 먼저 저장했으면 막는다
        current = load_plan_general(org.organization_id)
        storage.ensure_unchanged(current.updated_at, update.expected_updated_at, stored_by=current.updated_by)
    data = update.model_dump(exclude={"expected_updated_at"})
    for key in ("representative", "business_number", "business_type", "business_item"):
        data[key] = data[key] or None
    info = PlanGeneralInfo.model_validate({**data, "updated_at": _now()})
    path = org_storage.storage_for(org.organization_id).profile_file
    payload = storage.read_json(path, default=None)
    if not isinstance(payload, dict):
        storage.write_json_atomic(_plan_general_file(org.organization_id), info.model_dump(mode="json"))
    else:
        # 프로필의 저장 시각(`updated_at`)은 그대로 둔다 — 일반현황 저장이 프로필 버전을 바꾸면 프로필 카드의 다음 저장이
        # 「먼저 바꿨습니다」로 막혔다(44차 TEAM-R36-01 · 두 카드는 버전을 따로 본다)
        payload["plan_general"] = info.model_dump(mode="json")
        payload["schema_version"] = 1
        storage.write_json_atomic(path, payload)
    # 개업일은 창업 연차 경계 해 판정의 입력이다(43차 COMPANY-07) — 옛 지원사업 판정 메모를 버린다. 늦게 들여온다(import 고리).
    from app.services import opportunity_service

    opportunity_service.clear_support_memo()
    return info


def preferred_regions(organization_id: str) -> tuple[str, ...]:
    """자격 판정(지역 규칙)에 쓰는 조직의 활동 지역. 프로필에 없으면 빈 튜플 — 지어내지 않는다."""
    return tuple(load_profile(organization_id).preferred_regions)


# --------------------------------------------------------------------------
# 요약 (목록·선택기)
# --------------------------------------------------------------------------


def _document_registry_note(organization_id: str) -> str | None:
    """자료 등록부를 못 읽은 흔적이 있으면 그 사실. 없으면 None.

    깨진 등록부는 첫 읽기에서 `.corrupt-*` 로 격리되고, 그 다음 읽기부터는 「파일 없음 = 빈 등록부」가
    된다. 그래서 화면에는 오류가 아니라 「등록된 회사자료가 없습니다」로만 보였다 — 담당자 눈에는
    올려 둔 자료가 통째로 증발한 것과 구분되지 않는다. 근거 매칭 사유(`evidence_service._empty_pool_reason`)
    가 쓰는 것과 같은 흔적을 회사 요약에도 실어, 「없다」와 「못 읽었다」를 화면에서 가를 수 있게 한다.
    """
    try:
        quarantined = company_service.registry_quarantine_files(organization_id)
    except Exception as exc:  # noqa: BLE001 — 사유 문구를 만들다 목록 조회를 죽이지 않는다
        logger.error("격리 파일 확인에 실패했습니다 (organization_id=%s): %s", organization_id, type(exc).__name__)
        return None
    if not quarantined:
        return None
    return (
        f"회사자료 등록부를 읽지 못했습니다 — JSON 이 깨져 격리됐습니다 ({quarantined[-1].name})."
        " 자료가 없는 것이 아니라 읽기에 실패한 것입니다. 관리자 확인이 필요합니다."
    )


def summarize(org: Organization) -> OrganizationSummary:
    profile = load_profile(org.organization_id)
    listing = company_service.list_documents(org.organization_id)
    company_index = listing.index.company_index
    # 「승인」이 두 벌로 세어지고 있었다. 백엔드의 정의는 여기 한 줄이다:
    #   approved_document_count = 승인됐고 아직 색인 전(approved) + 색인까지 끝난 것(indexed)
    # 반면 DocumentListResponse.counts 는 상태별 원자료라 counts["approved"] 가 「색인 전」만 센다.
    # 화면(frontend/src/app/company/page.tsx)이 한쪽에서는 summary.approved_document_count,
    # 다른 쪽에서는 counts.approved 를 똑같이 「승인 N건」이라 적어서 같은 페이지에 두 숫자가 떴다.
    # 이 값의 뜻은 바꾸지 않고(기존 계약), 라벨을 갈라 쓸 수 있게 조각을 함께 내려보낸다.
    indexed = sum(1 for d in listing.documents if d.status == "indexed")
    approved_not_indexed = sum(1 for d in listing.documents if d.status == "approved")
    approved = indexed + approved_not_indexed
    # 「승인」과 「실제로 근거로 쓰이는 것」도 같은 수가 아니다 — 비활성 처리했거나
    # 유효기간이 지난 문서는 승인 상태로 남아 있어도 매칭에서 빠진다 (company_service.is_active).
    active_evidence = sum(1 for d in listing.documents if company_service.is_active(d))
    last = max((d.uploaded_at for d in listing.documents), default=None)
    if profile.updated_at and (last is None or profile.updated_at > last):
        last = profile.updated_at
    if org.updated_at and (last is None or org.updated_at > last):
        last = org.updated_at
    return OrganizationSummary(
        organization=org,
        profile_source=profile.source,
        document_count=len(listing.documents),
        approved_document_count=approved,
        indexed_document_count=indexed,
        approved_not_indexed_document_count=approved_not_indexed,
        active_evidence_document_count=active_evidence,
        document_registry_note=_document_registry_note(org.organization_id),
        pending_index_documents=listing.index.pending_documents,
        index_chunk_count=int(company_index.get("chunk_count") or 0),
        index_built_at=company_index.get("built_at"),
        embedding_available=listing.index.embedding_available,
        last_updated_at=last,
        usable_in_public_demo=bool(org.approved_for_public and org.data_class != "real"),
    )


def list_summaries() -> OrganizationListResponse:
    settings = get_settings()
    return OrganizationListResponse(
        organizations=[summarize(org) for org in list_organizations()],
        default_organization_id=settings.default_organization_id,
        # 「인증 없이 로컬에서 돈다」는 뜻이다 — 공개 데모가 아니라는 것만으로는 부족하다.
        # API_TOKEN 이 걸린 사내 배포는 인증이 있는 것이므로 로컬 관리자 모드가 아니다.
        # (이 값이 넓게 잡혀 있어서 실배포 화면에 「로컬 관리자 모드」 배지가 떴다.)
        local_admin_mode=not settings.public_demo_mode and not auth.token_required(),
        public_demo_mode=settings.public_demo_mode,
    )


# --------------------------------------------------------------------------
# 분석 컨텍스트 (호환 계층)
# --------------------------------------------------------------------------


def resolve_context(
    organization_id: str | None,
    evidence_scope: str | None,
    *,
    procurement_id: str | None = None,
) -> AnalysisContext:
    """API 파라미터 → AnalysisContext.

    - organization_id 가 없으면 설정의 기본 조직(`org-sample`)을 쓴다 — **호환 계층에서만** 허용되는 암묵 기본값.
    - evidence_scope 가 없으면: 공개 배포 모드는 public_demo, 합성 데모 공고(`synthetic-*`)는 public_demo, 그 밖에는 internal.
    - explicit_test 는 운영 API에서 고를 수 없다.
    - 비활성 조직은 거부한다.
    """
    settings = get_settings()
    org_id = org_storage.validate_organization_id(organization_id or settings.default_organization_id)
    require_active(org_id)
    if evidence_scope is None:
        if settings.public_demo_mode or (procurement_id or "").startswith("synthetic-"):
            scope = "public_demo"
        else:
            scope = "internal"
    else:
        if evidence_scope not in API_EVIDENCE_SCOPES:
            raise InvalidEvidenceScopeError("고를 수 없는 근거 범위입니다 — 공개 데모 또는 사내 범위만 고를 수 있습니다")
        scope = evidence_scope
    if settings.public_demo_mode and scope != "public_demo":
        # 공개 배포본은 실제 회사자료를 절대 검색하지 않는다.
        raise InvalidEvidenceScopeError("공개 배포 모드에서는 공개 데모 범위만 쓸 수 있습니다")
    return AnalysisContext(organization_id=org_id, evidence_scope=scope)  # type: ignore[arg-type]


def require_writable() -> None:
    """공개 배포 모드에서는 회사 생성·자료 업로드·승인·색인을 막는다."""
    if get_settings().public_demo_mode:
        raise PublicDemoWriteError("공개 배포(읽기 전용 데모) 모드에서는 회사자료를 등록·승인할 수 없습니다")


def is_local_admin_mode() -> bool:
    return not get_settings().public_demo_mode
