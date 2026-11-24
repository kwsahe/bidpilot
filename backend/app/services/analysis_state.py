"""분석 단계의 «준비 상태» — 지금 Auditor 를 돌려도 되는가.

## 왜 필요한가

요구사항 추출을 개선해 같은 공고의 요구사항이 32건 → 56건이 됐다. 그런데 저장된
제안서는 2026-09-04 에 «필수 32건» 기준으로 만든 것이고, Auditor 는 그것을 최신
56건 집합과 곧바로 비교했다. 그 결과 새로 발견된 요구사항 대부분이 한꺼번에
「미반영·높은 위험」으로 찍혔다.

그건 제안서의 결함이 아니라 **기준이 달라진 것**이다. 둘을 섞어 보여주면 담당자는
「지금 초안에서 고칠 것」과 「요구사항이 늘어난 것」을 구분할 수 없다.

## 무엇을 하는가

- 초안이 어느 요구사항 집합 기준인지 판정한다 (`requirement_set.proposal_basis`).
- 이전 집합 기준이면 일반 Auditor 실행을 막고, 무엇을 할 수 있는지 알려 준다.
- 사용자가 일부러 견주고 싶으면 `mode="change_impact"` 로 실행한다 —
  그 결과는 「변경 영향 분석」으로 따로 표시되고 일반 검사 결과와 섞이지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.schemas.organization import AnalysisContext
from app.services import proposal_service, requirement_set, rfp_parser

Blocker = Literal[
    "no_requirements",       # 요구사항을 아직 뽑지 않았다
    "no_proposal",           # 초안이 없다
    "stale_requirements",    # 초안이 이전 요구사항 집합 기준이다
    "unknown_basis",         # 기준 기록이 없어 최신인지 단정할 수 없다
    "document_changed",      # 초안을 만든 뒤 원문 문서가 바뀌었다
]

#: 실행을 막는 사유. 나머지는 경고만 하고 담당자가 보고 넘어갈 수 있다.
#:
#: `no_requirements` 는 여기 없다 — 요구사항이 없으면 run_audit 이 이미 404 를 내고,
#: 그것이 「없는 공고」에 대한 정확한 답이다. 409(충돌)로 바꾸면 원인을 흐린다.
#: `no_proposal` 도 없다 — Auditor 는 초안을 **붙여넣거나 업로드**해서도 돌린다.
#: 저장된 초안이 없다고 그 경로를 막으면 기존 기능이 사라진다.
HARD_BLOCKERS: frozenset[str] = frozenset({"stale_requirements"})


@dataclass
class AuditReadiness:
    """Auditor 를 지금 돌려도 되는가, 안 되면 무엇을 할 수 있는가."""

    ready: bool
    basis: str
    blockers: list[str] = field(default_factory=list)
    message: str = ""
    requirement_set_id: str | None = None
    requirement_set_hash: str | None = None
    requirement_set_version: int | None = None
    proposal_version: int | None = None
    requirement_count: int | None = None
    mandatory_count: int | None = None
    previous_mandatory_total: int | None = None
    #: **공고가 마지막으로 바뀐 시각** (0923 §3-3 · ISSUE-093).
    #:
    #: 저장된 결과(근거 연결·제출 전 점검·조건)가 이 시각보다 **앞서** 만들어졌으면
    #: 그것은 바뀌기 전의 공고를 보고 낸 답이다. 화면이 「다시 실행 필요」를 덧붙이는
    #: 근거가 이 값이다. 이력이 없으면 None — 「안 바뀌었다」가 아니라 「모른다」이므로
    #: 화면은 그때 아무 말도 덧붙이지 않는다.
    notice_changed_at: str | None = None
    #: 담당자가 고를 수 있는 다음 행동. 화면 버튼과 1:1 이다.
    actions: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "basis": self.basis,
            "blockers": self.blockers,
            "message": self.message,
            "requirement_set_id": self.requirement_set_id,
            "requirement_set_hash": self.requirement_set_hash,
            "requirement_set_version": self.requirement_set_version,
            "proposal_version": self.proposal_version,
            "requirement_count": self.requirement_count,
            "mandatory_count": self.mandatory_count,
            "previous_mandatory_total": self.previous_mandatory_total,
            "notice_changed_at": self.notice_changed_at,
            "actions": self.actions,
        }


#: 화면이 그릴 버튼. 지시서가 요구한 네 가지를 그대로 둔다.
_STALE_ACTIONS: list[dict[str, str]] = [
    {"key": "view_changes", "label": "변경된 요구사항 보기"},
    {"key": "compare", "label": "기존 제안서와 비교"},
    {"key": "regenerate", "label": "새 요구사항을 반영한 제안서 버전 만들기"},
    {"key": "keep", "label": "이전 제안서 유지"},
]


def notice_changed_at(procurement_id: str) -> str | None:
    """공고가 **마지막으로 바뀐** 시각 (0923 §3-3 · ISSUE-093).

    변경 기록(`notice_version_service`)이 있으면 그 마지막 변경 시각을, 변경이 한 번도
    없었으면 처음 관찰한 시각을 돌려준다. 이력 자체가 없으면 None 이다 — 「안 바뀌었다」가
    아니라 **「모른다」**이므로, 화면은 이 값이 없을 때 아무 말도 덧붙이지 않는다.
    """
    from app.services import notice_version_service

    try:
        history = notice_version_service.load_history(procurement_id)
    except Exception:  # noqa: BLE001 — 이력이 없어도 검사는 돌아가야 한다
        return None
    if history.changes:
        return max(c.observed_at for c in history.changes).isoformat()
    if history.versions:
        return max(v.observed_at for v in history.versions).isoformat()
    return None


def audit_readiness(procurement_id: str, *, context: AnalysisContext | None = None) -> AuditReadiness:
    """일반 Auditor 실행 전 점검."""
    changed_at = notice_changed_at(procurement_id)
    try:
        parsed = rfp_parser.load_generated(procurement_id)
    except Exception:  # noqa: BLE001 — 아직 파싱하지 않은 공고
        return AuditReadiness(
            ready=False,
            basis="no_proposal",
            blockers=["no_requirements"],
            message="요구사항을 먼저 추출해야 합니다.",
            notice_changed_at=changed_at,
            actions=[{"key": "parse", "label": "RFP 요구사항 정리 실행"}],
        )

    section = None
    try:
        section = proposal_service.load_section(procurement_id, context)
    except Exception:  # noqa: BLE001 — 초안 없음
        section = None

    basis = requirement_set.proposal_basis(
        proposal_set_hash=getattr(section, "requirement_set_hash", None),
        proposal_mandatory_total=getattr(section, "mandatory_total", None),
        current_set_hash=parsed.requirement_set_hash,
        current_mandatory_count=parsed.mandatory_count,
        has_proposal=section is not None,
    )

    readiness = AuditReadiness(
        ready=basis == "current",
        basis=basis,
        requirement_set_id=parsed.requirement_set_id,
        requirement_set_hash=parsed.requirement_set_hash,
        requirement_set_version=parsed.requirement_set_version,
        proposal_version=getattr(section, "proposal_version", None),
        requirement_count=parsed.count,
        mandatory_count=parsed.mandatory_count,
        previous_mandatory_total=getattr(section, "mandatory_total", None),
        notice_changed_at=changed_at,
    )

    if basis == "no_proposal":
        readiness.blockers = ["no_proposal"]
        readiness.message = requirement_set.basis_message("no_proposal")
        readiness.actions = [{"key": "generate", "label": "제안서 초안 만들기"}]
        return readiness

    if basis == "stale_requirements":
        readiness.blockers = ["stale_requirements"]
        readiness.message = requirement_set.basis_message(
            "stale_requirements",
            before=getattr(section, "mandatory_total", None),
            after=parsed.mandatory_count,
        )
        readiness.actions = list(_STALE_ACTIONS)
        return readiness

    if basis == "unknown_basis":
        # 막지는 않는다 — 기록이 없다고 검사를 못 하게 하면 옛 공고를 아예 못 본다.
        # 대신 최신이라고 말하지도 않는다.
        readiness.ready = True
        readiness.blockers = ["unknown_basis"]
        readiness.message = requirement_set.basis_message("unknown_basis")
        readiness.actions = [{"key": "regenerate", "label": "최신 요구사항으로 제안서 다시 만들기"}]
        return readiness

    readiness.message = requirement_set.basis_message("current")
    return readiness


def _mandatory_count(payload: dict[str, Any]) -> int:
    return sum(
        1
        for r in payload.get("requirements") or []
        if isinstance(r, dict) and str(r.get("requirement_type")) == "mandatory"
    )


def proposal_basis_version(
    procurement_id: str, section: Any, *, current_hash: str | None
) -> tuple[dict[str, Any] | None, str]:
    """제안서가 «실제로 본» 요구사항 판을 찾는다. (판, 사유) 를 돌려준다.

    왜 필요한가 — 실측(2026-09-14, g2b-R26BK01707959-000):

        준비 상태:   「필수 32건 → 54건으로 늘었다」   (제안서의 mandatory_total 기준)
        변경 영향:   「새로 발견 0건」                 (보존된 직전 판 v001 ↔ 현재 기준)

    한 화면에 서로 모순된 두 답이 떴다. 「직전 판」과 「제안서가 기준으로 삼은 판」이
    다른 것인데, 뒤엣것을 앞엣것으로 대신 답한 셈이다.

    찾는 순서는 근거의 세기 그대로다.

    1. 제안서에 `requirement_set_hash` 가 있으면 그 해시의 판 (제일 확실하다)
    2. 없으면 «필수 건수»가 정확히 하나만 들어맞는 판 — 둘 이상이면 고르지 않는다
    3. 그래도 없으면 None. **추측으로 아무 판이나 견주지 않는다.**
    """
    if section is None:
        return None, "제안서 초안이 없습니다."

    candidates = list(rfp_parser.list_versions(procurement_id))
    proposal_hash = str(getattr(section, "requirement_set_hash", None) or "")
    if proposal_hash:
        if proposal_hash == (current_hash or ""):
            return None, "제안서가 이미 최신 요구사항 집합 기준입니다."
        for payload in reversed(candidates):
            if str(payload.get("requirement_set_hash") or "") == proposal_hash:
                return payload, ""
        return None, f"제안서가 기준으로 삼은 요구사항 집합({proposal_hash})이 보존된 판에 없습니다."

    total = getattr(section, "mandatory_total", None)
    if not total:
        return None, "이 제안서가 어느 요구사항 집합을 기준으로 만들어졌는지 기록이 없습니다."
    matched = [p for p in candidates if _mandatory_count(p) == int(total)]
    if len(matched) == 1:
        return matched[0], ""
    if len(matched) > 1:
        return None, f"필수 {total}건인 보존 판이 {len(matched)}개라 어느 것이 기준인지 가릴 수 없습니다."
    return None, (
        f"제안서는 필수 {total}건 기준으로 만들어졌는데, 보존된 판 가운데 필수 {total}건인 것이 없습니다. "
        "이 초안과 현재 집합을 직접 견줄 근거가 없습니다."
    )


def change_impact(procurement_id: str, *, context: AnalysisContext | None = None) -> dict[str, Any]:
    """이전 집합 → 현재 집합의 변화를, 기존 초안이 이미 대응하는지와 함께 낸다.

    「24건 증가」 한 줄로 끝내지 않는다. 무엇이 늘었고 그중 새 문장이 필요한 것이
    몇 건인지까지 적는다 — 그래야 담당자가 다음에 할 일을 안다.

    견주는 상대는 «제안서가 실제로 본 판»을 먼저 찾는다(`proposal_basis_version`).
    못 찾으면 직전 판으로 견주되, 그 결과를 「제안서 대비 변화」로 읽으면 안 되므로
    `proposal_comparison.available=False` 와 사유를 함께 내려보낸다. 응답의
    `compared_to` 가 무엇과 견줬는지를 말한다.
    """
    parsed = rfp_parser.load_generated(procurement_id)
    current = [r.model_dump(mode="json") for r in parsed.requirements]

    section = None
    try:
        section = proposal_service.load_section(procurement_id, context)
    except Exception:  # noqa: BLE001
        section = None

    basis_payload, basis_reason = proposal_basis_version(
        procurement_id, section, current_hash=parsed.requirement_set_hash
    )
    previous_payload = basis_payload or rfp_parser.previous_version(procurement_id)
    compared_to = "proposal_basis" if basis_payload is not None else "latest_previous_version"
    proposal_comparison: dict[str, Any] = {
        "available": basis_payload is not None,
        "reason": basis_reason,
        "requirement_set_hash": getattr(section, "requirement_set_hash", None),
        "mandatory_total": getattr(section, "mandatory_total", None),
    }
    previous = list(previous_payload.get("requirements") or []) if previous_payload else []

    covered = set(getattr(section, "covered_requirement_ids", None) or [])

    if not previous:
        # 보존된 이전 판이 없다. 없는 것을 지어내지 않는다.
        return {
            "available": False,
            "reason": basis_reason
            or "보존된 이전 요구사항 집합이 없습니다. 이번 판부터 비교가 가능합니다.",
            "compared_to": None,
            "proposal_comparison": proposal_comparison,
            "current": {
                "requirement_set_id": parsed.requirement_set_id,
                "requirement_count": parsed.count,
                "mandatory_count": parsed.mandatory_count,
            },
            "previous_mandatory_total": getattr(section, "mandatory_total", None),
            "groups": [],
            "counts": {},
        }

    result = requirement_set.diff(previous, current)
    return {
        "available": True,
        "compared_to": compared_to,
        "proposal_comparison": proposal_comparison,
        "previous": {
            "requirement_set_id": previous_payload.get("requirement_set_id"),
            "requirement_set_version": previous_payload.get("requirement_set_version"),
            "requirement_count": len(previous),
            # 필수 건수를 함께 보낸다. 준비 상태 문구가 「필수 32건 → 54건」이라고 말하는데
            # 여기서 견준 판의 필수 건수가 몇인지 화면이 모르면 두 숫자가 어긋나도 알 수 없다.
            "mandatory_count": _mandatory_count(previous_payload),
            "generated_at": previous_payload.get("generated_at"),
        },
        "current": {
            "requirement_set_id": parsed.requirement_set_id,
            "requirement_set_version": parsed.requirement_set_version,
            "requirement_count": parsed.count,
            "mandatory_count": parsed.mandatory_count,
            "generated_at": parsed.generated_at.isoformat() if parsed.generated_at else None,
        },
        "counts": result.counts,
        "groups": requirement_set.added_summary(result, covered_stable_ids=covered),
        "entries": [e.to_dict() for e in result.entries if e.kind != "unchanged"],
        "uncertain": [e.to_dict() for e in result.by_kind("uncertain")],
    }
