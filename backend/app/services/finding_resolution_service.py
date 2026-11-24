"""Auditor 발견 항목의 담당자 해결 처리 저장/조회.

- 저장은 공고당 JSON 파일 1개 (`data/public/reviews/<procurement_id>.findings.json`).
- 키는 `resolution_key()`로 만든 안정 키다. 프론트엔드(`lib/cosmos/graph.ts`의
  `findingResolutionKey`)와 **같은 규칙**을 써야 하므로 바꾸면 양쪽을 같이 바꾼다.
- Auditor 검사 결과 파일은 절대 수정하지 않는다 (탐지 기록과 사람의 판단을 분리한다).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.core import storage
from app.schemas.audit import AuditFinding
from app.schemas.finding_resolution import (
    FindingResolution,
    FindingResolutionList,
    FindingResolutionRequest,
)
from app.services import review_service, wording

if TYPE_CHECKING:  # pragma: no cover
    from app.schemas.organization import AnalysisContext

RESOLUTION_DIR = review_service.REVIEW_DIR

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


class InvalidProcurementIdError(ValueError):
    """저장 경로로 쓸 수 없는 id."""


# ---------------------------------------------------------------------------
# 안정 키
# ---------------------------------------------------------------------------


def fnv1a32(text: str) -> str:
    """FNV-1a 32bit 해시의 8자리 hex. 프론트엔드 구현과 동일해야 한다."""
    value = 0x811C9DC5
    for byte in text.encode("utf-8"):
        value ^= byte
        value = (value * 0x01000193) & 0xFFFFFFFF
    return f"{value:08x}"


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def resolution_key(finding: AuditFinding) -> str:
    """검사마다 바뀌는 AF-id 대신, 같은 문제를 가리키는 안정 키.

    우선순위: 요구사항 id → 증빙 id → 초안 문장 텍스트 fingerprint → 초안 전체.
    """
    if finding.requirement_id:
        return f"{finding.finding_type}:req:{finding.requirement_id}"
    if finding.evidence_id:
        return f"{finding.finding_type}:ev:{finding.evidence_id}"
    if finding.proposal_text:
        return f"{finding.finding_type}:text:{fnv1a32(_normalize_text(finding.proposal_text))}"
    return f"{finding.finding_type}:draft:all"


def stored_keys(procurement_id: str, context: "AnalysisContext | None" = None) -> set[str]:
    """이 공고에 저장된 처리 기록의 키. 못 읽으면 빈 집합(응답을 막지 않는다)."""
    try:
        return {item.key for item in load_resolutions(procurement_id, context).resolutions}
    except Exception:  # noqa: BLE001 — 키 잇기는 부가 기능이다
        return set()


def shown_key(finding: AuditFinding, stored: set[str]) -> str:
    """응답에 실을 처리 키 — 새 말로 바꾸기 **전** 원문 키(33차 R32-12).

    32차 동안은 화면이 새 말 글로 키를 만들어 저장했다. 원문 키 기록이 없고 그 **별칭**(새 말 글의 키) 기록만
    있으면 별칭으로 잇는다 — 33차에 32차의 「해결」이 떨어졌다(34차 R33-08).
    """
    key = resolution_key(finding)
    if key in stored:
        return key
    alias = resolution_key(wording.modernize_model(finding))
    return alias if alias in stored else key


# ---------------------------------------------------------------------------
# 저장 / 조회
# ---------------------------------------------------------------------------


def resolution_path(procurement_id: str, context: "AnalysisContext | None" = None) -> Path:
    if not _SAFE_ID_RE.match(procurement_id):
        raise InvalidProcurementIdError(f"허용되지 않는 공고 id입니다: {procurement_id}")
    from app.services import analysis_store

    return analysis_store.resolve_path(
        context, procurement_id, public_path=RESOLUTION_DIR / f"{procurement_id}.findings.json", file_name="findings.json"
    )


def _read(
    procurement_id: str, context: "AnalysisContext | None" = None
) -> tuple[dict[str, FindingResolution], bool]:
    """저장된 처리 기록. `(기록, 공개 레거시로 읽었는가)`.

    **읽기는 공개 레거시 파일도 본다** (0920 §4-B-3 · ISSUE-076-b).
    조직 구조로 옮기기 전에 저장된 결과가 `data/public/reviews/` 에 남아 있는데, 읽기 경로가
    조직 폴더만 보고 있었다. 그래서 가천대 피지컬의 발견 처리 기록이 「검토 중」 탭에서
    통째로 빠졌다 — 결정·검토는 이미 이 규칙을 쓰고 있었고 여기만 달랐다.

    **쓰기는 바꾸지 않는다.** 쓰기까지 공개 파일을 가리키면 다른 회사가 공용 데모 결과를
    덮어쓰는 길이 열리고, 공개 데모 쓰기 금지(`guard_public_demo_write`)도 우회된다.
    """
    if not _SAFE_ID_RE.match(procurement_id):
        raise InvalidProcurementIdError(f"허용되지 않는 공고 id입니다: {procurement_id}")
    from app.services import analysis_store

    # 직접 json.loads 하면 깨진 파일이 그대로 500 으로 올라가고, 격리도 한국어 안내도
    # 없다. 저장소의 단일 읽기 경로를 쓴다 — 거기서 격리하고 CorruptJsonError 를 던지며
    # 전역 핸들러가 409 + 「기록이 사라진 것은 아닙니다」로 답한다 (ISSUE-023).
    try:
        raw, legacy = analysis_store.load_json(
            context,
            procurement_id,
            public_path=RESOLUTION_DIR / f"{procurement_id}.findings.json",
            file_name="findings.json",
        )
    except analysis_store.ForeignResultError:
        # 다른 회사의 결과다. 예전처럼 «없는 것»으로 본다 — 여기서 막는 것이 회사 격리다.
        return {}, False
    if not isinstance(raw, dict):
        return {}, False
    items = raw.get("resolutions", [])
    result: dict[str, FindingResolution] = {}
    for item in items:
        parsed = FindingResolution.model_validate(item)
        result[parsed.key] = parsed
    return result, legacy


def _write(procurement_id: str, items: dict[str, FindingResolution], context: "AnalysisContext | None" = None) -> None:
    path = resolution_path(procurement_id, context)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "procurement_id": procurement_id,
        "resolutions": [item.model_dump(mode="json") for item in items.values()],
        "organization_id": context.organization_id if context else None,
        "evidence_scope": context.evidence_scope if context else None,
    }
    storage.write_json_atomic(path, payload)


def load_resolutions(procurement_id: str, context: "AnalysisContext | None" = None) -> FindingResolutionList:
    items, legacy = _read(procurement_id, context)
    return FindingResolutionList(
        procurement_id=procurement_id,
        resolutions=list(items.values()),
        # 공개 레거시로 읽었으면 그렇게 말한다 — 결정·검토가 이미 쓰는 표시와 같다.
        organization_id=None if legacy else (context.organization_id if context else None),
        evidence_scope="public_demo" if legacy else (context.evidence_scope if context else None),
        legacy_result=legacy,
    )


def save_resolution(
    procurement_id: str,
    request: FindingResolutionRequest,
    *,
    context: "AnalysisContext | None" = None,
    recorded_by: str | None = None,
) -> FindingResolution:
    """해결(resolved) 또는 재오픈(open) 기록을 남긴다. 같은 키는 덮어쓴다.

    같은 키는 덮어써도 되지만 **다른 키는 덮어쓰면 안 된다.** 두 사람이 서로 다른 발견을
    동시에 해결 처리하면, 잠그지 않을 경우 둘 다 옛 목록을 읽고 자기 것만 더해 써서
    먼저 누른 쪽의 기록이 사라진다 (ISSUE-032).
    """
    with storage.locked(resolution_path(procurement_id, context)):
        return _save_resolution_locked(procurement_id, request, context, recorded_by)


def _save_resolution_locked(
    procurement_id: str,
    request: FindingResolutionRequest,
    context: "AnalysisContext | None",
    recorded_by: str | None = None,
) -> FindingResolution:
    # 저장할 때도 공개 레거시를 «읽어» 이어 쓴다. 다만 **쓰는 곳은 조직 폴더**다 —
    # 처음 손대는 순간 레거시 기록이 조직 폴더로 옮겨 오는 셈이고, 공개 파일은 그대로 둔다.
    items, _legacy = _read(procurement_id, context)
    resolution = FindingResolution(
        procurement_id=procurement_id,
        key=request.key,
        status=request.status,
        finding_type=request.finding_type,
        requirement_id=request.requirement_id,
        finding_id=request.finding_id,
        audit_run_id=request.audit_run_id,
        reviewer=request.reviewer,
        note=request.note,
        # 본문의 `reviewer` 는 클라이언트의 주장이고, 이것은 서명된 신원에서 온 사실이다 (S12).
        recorded_by=recorded_by,
        decided_at=datetime.now(timezone.utc),
    )
    items[request.key] = resolution
    _write(procurement_id, items, context)
    return resolution
