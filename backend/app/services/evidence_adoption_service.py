"""원장 후보 채택 (45차 H5 — 43차 결정 3 의 빈 곳).

AI 검색(회사 근거 연결)을 꺼 둔 회사는 실적 원장에서 분야 낱말로 맞춘 **후보(미채택)** 만 받는다. 「사람이 고른 것만 초안에 쓴다」였는데
화면에 고를 단추가 없어 초안이 언제나 「확인 필요」였고, 정리표 · 대시보드는 그것을 「실패」로 보였다.

공고마다 채택을 남긴다(누가 적었나 · 서버가 본 사람 · 언제). 초안을 만들 때 채택한 후보만 근거로 쓴다(`proposal_service._resolve_links`).
후보는 규칙으로 다시 맞추므로(같은 원장 · 같은 요구사항이면 같은 번호) 채택은 `(요구사항 번호, 후보 번호)` 로 잇는다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core import storage
from app.core.paths import DATA_ROOT
from app.schemas.organization import AnalysisContext
from app.schemas.proposal import EvidenceCandidate
from app.services import analysis_store

FILE_NAME = "evidence_adoptions.json"
_PUBLIC_DIR = DATA_ROOT / "public" / "proposals"


class AdoptionError(ValueError):
    """채택을 받을 수 없다(가상 예시 공고 · 지금 후보에 없는 번호)."""


def _public_path(procurement_id: str):
    return _PUBLIC_DIR / f"{procurement_id}.evidence_adoptions.json"


def load(procurement_id: str, context: AnalysisContext | None) -> dict[tuple[str, str], dict[str, Any]]:
    """채택 `(요구사항 번호, 후보 번호) → {by, recorded_by, at}`. 없으면 빈 사전."""
    if context is None or not analysis_store.is_private(context):
        return {}
    payload, _legacy = analysis_store.load_json(context, procurement_id, public_path=_public_path(procurement_id), file_name=FILE_NAME)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for item in (payload or {}).get("items") or []:
        if isinstance(item, dict) and item.get("requirement_id") and item.get("evidence_id"):
            out[(str(item["requirement_id"]), str(item["evidence_id"]))] = item
    return out


def apply(procurement_id: str, context: AnalysisContext | None, links: list[EvidenceCandidate]) -> list[EvidenceCandidate]:
    """채택한 원장 후보를 「채택」으로 — 초안이 그 후보만 근거로 쓴다(`build_drafts` 는 selected 만 쓴다)."""
    adopted = load(procurement_id, context)
    if not adopted:
        return links
    return [
        link.model_copy(update={"selected": True}) if (link.requirement_id, link.evidence_id) in adopted else link
        for link in links
    ]


def ledger_view(procurement_id: str, context: AnalysisContext) -> dict[str, Any]:
    """정리표 · 대시보드가 보이는 원장 후보와 채택 — AI 검색이 켜져 있으면 후보 없이 `ai_search_off=False`."""
    from app.services import evidence_service, rfp_parser

    parsed = rfp_parser.load_generated(procurement_id)
    off = evidence_service.ai_search_off(context)  # 46차 H5 — 대시보드 · 정리표 · 지원사업과 같은 한 곳
    adopted = load(procurement_id, context)
    candidates = evidence_service.ledger_candidates(parsed.requirements, context) if off else []
    return {
        "procurement_id": procurement_id,
        "ai_search_off": off,
        "editable": analysis_store.is_private(context),
        "candidates": [
            {
                "requirement_id": c.requirement_id,
                "evidence_id": c.evidence_id,
                "document_name": c.document_name,
                "source_text": c.source_text,
                "adopted": adopted.get((c.requirement_id, c.evidence_id)),
            }
            for c in candidates
        ],
        "adopted_count": sum(1 for c in candidates if (c.requirement_id, c.evidence_id) in adopted),
    }


def set_adoption(
    procurement_id: str,
    context: AnalysisContext,
    *,
    requirement_id: str,
    evidence_id: str,
    adopted: bool,
    by: str,
    recorded_by: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """채택 · 채택 취소. 지금 원장 후보에 없는 번호는 받지 않는다. 반환은 `ledger_view` 와 같은 꼴(바로 화면을 고친다)."""
    if not analysis_store.is_private(context):
        raise AdoptionError("가상 예시(공용) 공고에서는 채택을 남기지 않습니다")
    view = ledger_view(procurement_id, context)
    if adopted and not any(c["requirement_id"] == requirement_id and c["evidence_id"] == evidence_id for c in view["candidates"]):
        raise AdoptionError("지금 원장 후보에 없는 실적입니다 — 화면을 다시 불러온 뒤 고르세요")
    current = load(procurement_id, context)
    key = (requirement_id, evidence_id)
    if adopted:
        current[key] = {
            "requirement_id": requirement_id,
            "evidence_id": evidence_id,
            "by": by,
            "recorded_by": recorded_by,
            "at": (now or storage.utc_now()).isoformat(),
        }
    else:
        current.pop(key, None)
    analysis_store.write_json(
        context, procurement_id, {"items": list(current.values())}, public_path=_public_path(procurement_id), file_name=FILE_NAME
    )
    return ledger_view(procurement_id, context)
