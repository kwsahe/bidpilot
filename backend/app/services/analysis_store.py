"""공고 분석 결과의 저장 위치 규칙 — 하나의 분석은 하나의 회사(+근거 범위)에 고정된다.

- `public_demo` 범위: 기존 공개 위치(`data/public/...`, 합성 근거만)에 그대로 둔다. 각 서비스의 디렉터리 상수를 쓴다.
- `internal` 범위: `data/private/organizations/{organization_id}/analyses/{procurement_id}/{kind}.json`.
  실제 회사 근거가 인용된 결과는 공개 폴더에 절대 쓰지 않는다.
- 읽기 대체(legacy): 기본 조직(`org-sample`)의 internal 결과가 아직 없으면 예전 공개 파일을 **레거시**로 돌려준다.
  그 결과는 `organization_id=None`, `evidence_scope=public_demo`, `legacy_result=True` 로 표시된다 —
  다른 회사의 결과처럼 재사용되지 않고, 화면에서 "합성 데모자료(레거시)"로 구분된다.
- 저장 payload 에는 항상 organization_id / evidence_scope 를 찍는다. 다른 조직의 결과를 읽으려 하면 거부한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core import org_storage, storage
from app.schemas.organization import AnalysisContext

# 핵심 서비스가 컨텍스트를 받지 못했을 때(레거시 테스트 진입점)의 위치: 공개 합성 위치. 실제 회사를 고르지 않는다.
LEGACY_PUBLIC_CONTEXT = AnalysisContext(organization_id=org_storage.DEFAULT_ORGANIZATION_ID, evidence_scope="public_demo")


class ForeignResultError(PermissionError):
    """다른 조직의 결과 파일을 현재 조직 컨텍스트로 읽으려 했다."""


class PublicDemoReadOnlyError(PermissionError):
    """기본 조직이 아닌 회사가 공용 데모 결과에 쓰려 했다."""


def guard_public_demo_write(context: AnalysisContext | None) -> None:
    """공용 데모 결과는 **기본 조직만** 쓸 수 있다.

    `public_demo` 범위의 결과(제안서·조치·결정·검토)는 회사 구분 없이 `data/public/…` 한
    파일에 저장된다. 그래서 어떤 조직 id 로든 쓰기를 보내면 **발표용 데모 화면이 바뀐다.**
    실측: `org-test-alpha` 로 데모 제안서를 재생성하자 샘플에듀 대시보드의 발견 항목이
    2건에서 9건으로 바뀌었다.

    저장 위치를 회사별로 쪼개면 기존 데모 파일의 경로가 달라진다 — 발표를 앞두고 바꿀
    일이 아니다. 대신 **쓰기를 기본 조직으로 한정**하고 나머지는 읽기 전용으로 둔다.
    화면은 이 결과에 「공용 데모 결과(모든 회사 공통)」를 붙인다.
    """
    if context is None:
        return
    if context.evidence_scope != "public_demo":
        return
    if context.organization_id == org_storage.DEFAULT_ORGANIZATION_ID:
        return
    raise PublicDemoReadOnlyError(
        "공용 데모 결과는 모든 회사가 함께 보는 자료라 다른 회사에서는 수정할 수 없습니다. "
        "회사 자료로 분석하려면 실제 공고를 선택하세요."
    )


def is_private(context: AnalysisContext | None) -> bool:
    return context is not None and context.is_private


def private_dir(context: AnalysisContext, procurement_id: str) -> Path:
    return org_storage.storage_for(context.organization_id).analysis_dir(procurement_id)


def resolve_path(context: AnalysisContext | None, procurement_id: str, *, public_path: Path, file_name: str) -> Path:
    """쓰기·읽기 경로. public_demo(또는 컨텍스트 없음)는 공개 경로, internal 은 조직 분석 폴더."""
    if not is_private(context):
        return public_path
    assert context is not None
    return private_dir(context, procurement_id) / file_name


def read_with_fallback(
    context: AnalysisContext | None, procurement_id: str, *, public_path: Path, file_name: str
) -> tuple[Path | None, bool]:
    """(찾은 경로, 레거시 대체 여부). 기본 조직의 internal 결과가 없으면 공개 레거시 파일로 대체한다."""
    target = resolve_path(context, procurement_id, public_path=public_path, file_name=file_name)
    if target.exists():
        return target, False
    if is_private(context) and context is not None and context.organization_id == org_storage.DEFAULT_ORGANIZATION_ID and public_path.exists():
        return public_path, True
    return None, False


def stamp(payload: dict[str, Any], context: AnalysisContext | None, *, legacy: bool = False) -> dict[str, Any]:
    """결과 payload 에 회사·근거 범위를 찍는다. 레거시 대체 결과는 organization_id=None 으로 남긴다.

    **모든 저장이 이 함수를 거친다.** 그래서 공용 데모 쓰기 차단도 여기 둔다 —
    서비스마다 따로 막으면 새 저장 경로가 생길 때마다 빠진다.
    """
    guard_public_demo_write(context)
    if legacy or context is None:
        payload["organization_id"] = None
        payload["evidence_scope"] = "public_demo"
        payload["legacy_result"] = bool(legacy)
        return payload
    payload["organization_id"] = context.organization_id
    payload["evidence_scope"] = context.evidence_scope
    payload["legacy_result"] = False
    return payload


def assert_owner(payload: dict[str, Any], context: AnalysisContext | None) -> None:
    """저장된 결과의 organization_id 가 현재 컨텍스트와 다르면 읽지 않는다 (누출 차단).

    공개 데모(public_demo) 결과는 합성 자료만 담고 공개 경로에 공유되므로 조직 간 읽기를 막지 않는다.
    대신 범위 표시가 없는 예전 공개 결과에는 evidence_scope=public_demo 를 붙여 화면이 「범위 미표시」로 남지 않게 한다.
    """
    if context is None:
        return
    if not is_private(context):
        payload.setdefault("organization_id", None)
        payload.setdefault("evidence_scope", "public_demo")
        payload.setdefault("legacy_result", False)
        return
    owner = payload.get("organization_id")
    if owner not in (None, context.organization_id):
        raise ForeignResultError("다른 조직의 분석 결과입니다")


def load_json(
    context: AnalysisContext | None, procurement_id: str, *, public_path: Path, file_name: str
) -> tuple[dict[str, Any] | None, bool]:
    """결과 JSON 을 읽는다. 없으면 (None, False). 레거시 대체면 두 번째 값이 True."""
    path, legacy = read_with_fallback(context, procurement_id, public_path=public_path, file_name=file_name)
    if path is None:
        return None, False
    payload = storage.read_json(path, default=None)
    if not isinstance(payload, dict):
        return None, False
    if not legacy:
        assert_owner(payload, context)
    return payload, legacy


def write_json(
    context: AnalysisContext | None, procurement_id: str, payload: dict[str, Any], *, public_path: Path, file_name: str
) -> Path:
    target = resolve_path(context, procurement_id, public_path=public_path, file_name=file_name)
    stamp(payload, context)
    return storage.write_json_atomic(target, payload)


def iter_private_results(organization_id: str, file_name: str) -> list[Path]:
    """조직의 모든 공고 분석 폴더에서 같은 이름의 결과 파일을 모은다 (인용 역추적용)."""
    root = org_storage.storage_for(organization_id).analyses_dir
    if not root.exists():
        return []
    return sorted(p for p in root.glob(f"*/{file_name}") if p.is_file())
