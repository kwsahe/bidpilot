"""참가자격 조항마다 담당자 확인 (20차 §4-C · ISSUE-139).

담당자 말(2026-09-23): 「자격요건 같은 경우는 안 맞으면 입찰 신청 자체를 못하니까 더 강조되면서
보여줘야 함. **하나하나씩 체크 및 확인**할 수 있는 기능도 필요하고.」

규칙은 조항 원문과 회사 사실이 둘 다 있을 때만 가능·불가를 낸다 — 그래서 대부분 「확인 필요」다.
회사가 그 조항을 실제로 확인했으면 그 사실을 여기에 남긴다. 판정(`eligibility_engine`)은 이 기록을
**회사 쪽 사실(`CompanyFacts.clause_reviews`)로** 읽는다 — 목록 게이트와 상세 판정이 같은 함수로
같은 기록을 보므로 두 화면이 어긋나지 않는다.

- 상태: `met`(충족) · `unmet`(미충족) · `pending`(보류). **충족·미충족은 근거 메모가 있어야 저장된다** —
  빈 메모로 「충족」을 남기면 근거 없는 가능이 된다(CLAUDE.md §11).
- `clause_hash`: 확인할 때 조항 원문의 해시. 조항 파일을 다시 뽑아 원문이 바뀌면 그 확인은 `stale` 로
  읽히고 판정에 쓰이지 않는다(화면이 「조항이 바뀌었습니다 — 다시 확인」을 붙인다).
- 저장: `analyses/<공고>/qualification_review.json`(조직 범위). 공개 시연 범위는
  `data/public/reviews/<공고>.qualification_review.json`(gitignore).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Literal

from app.core import storage
from app.core.paths import DATA_ROOT
from app.schemas.organization import AnalysisContext
from app.services import analysis_store
from app.services.finding_resolution_service import fnv1a32
from app.services.qualification_clause_service import clause_body

logger = logging.getLogger(__name__)

ReviewState = Literal["met", "unmet", "pending"]
STATES: Final[tuple[str, ...]] = ("met", "unmet", "pending")
FILE_NAME: Final[str] = "qualification_review.json"
PUBLIC_DIR: Path = DATA_ROOT / "public" / "reviews"

#: `CompanyFacts.clause_reviews` 한 칸 — (공고 id, 조항 id, 상태, 메모, 확인한 사람, 확인 시각 ISO, 조항 해시).
ReviewFact = tuple[str, str, str, str, str, str, str]


class ReviewNoteRequiredError(ValueError):
    """충족·미충족을 메모 없이 저장하려 했다."""


def clause_hash(text: str) -> str:
    """조항 원문의 해시 — 빈칸 차이와 머리 글머리·번호(「나.」「– 」)는 같은 조항으로 본다.

    같은 조항이 RFP 요구사항(REQ-030 「나. …」)에서 공고문 조항(QC-02 「…」)으로 옮겨 가도 확인이 이어진다.
    """
    return fnv1a32(re.sub(r"\s+", " ", clause_body(text)).strip())


def review_path(procurement_id: str, context: AnalysisContext | None) -> Path:
    safe = storage.safe_id(procurement_id, what="공고 id")
    return analysis_store.resolve_path(
        context, safe, public_path=PUBLIC_DIR / f"{safe}.{FILE_NAME}", file_name=FILE_NAME
    )


def _read(path: Path, context: AnalysisContext | None) -> dict[str, Any]:
    payload = storage.read_json(path, default=None)
    if not isinstance(payload, dict):
        return {}
    try:
        analysis_store.assert_owner(payload, context)
    except analysis_store.ForeignResultError:
        return {}
    return payload


def load(procurement_id: str, context: AnalysisContext | None) -> dict[str, dict[str, Any]]:
    """`{조항 id: {state, note, decided_by, decided_at, clause_hash}}`. 없으면 빈 dict."""
    return dict(_read(review_path(procurement_id, context), context).get("reviews") or {})


def save(
    procurement_id: str,
    clause_id: str,
    *,
    state: str,
    note: str | None,
    decided_by: str,
    clause_text: str,
    context: AnalysisContext | None,
    recorded_by: str | None = None,
    check_version: bool = False,
    expected_decided_at: datetime | None = None,
) -> dict[str, Any]:
    """조항 하나의 확인을 저장하고 그 칸을 돌려준다.

    `check_version` 이면 화면이 읽은 확인 시각(`expected_decided_at` · 없던 칸이면 None)과 지금 저장된 것이 다를 때
    `StaleWriteError`(43차 M25 — 두 사람이 같은 조항을 확인하면 나중 것이 앞 것을 말없이 덮었다)."""
    if state not in STATES:
        raise ValueError(f"알 수 없는 확인 상태입니다: {state}")
    memo = (note or "").strip()
    if state in ("met", "unmet") and not memo:
        raise ReviewNoteRequiredError(
            "「충족」·「미충족」은 근거 메모가 있어야 저장됩니다 — 무엇을 보고 확인했는지 한 줄 적으세요."
        )
    path = review_path(procurement_id, context)
    entry = {
        "state": state,
        "note": memo or None,
        "decided_by": decided_by.strip(),
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "clause_hash": clause_hash(clause_text),
        # 본문의 `decided_by` 는 사람이 적은 이름이고, 이것은 서명된 신원이다(인증이 켜졌을 때만).
        "recorded_by": recorded_by,
    }
    with storage.locked(path):
        payload = _read(path, context) or {"procurement_id": procurement_id, "reviews": {}}
        reviews = payload.setdefault("reviews", {})
        old = reviews.get(clause_id)
        if check_version:
            # 화면이 본 확인은 판정과 같은 규칙으로 찾는다 — 원문 해시가 같은 확인 중 가장 최근(번호가 밀려 다른 열쇠에 있어도 ·
            # 43차 마지막 검토: 지금 번호의 칸만 보면 늘 「먼저 바꿨습니다」가 떠 「미충족」을 고칠 수 없었다)
            same = [e for e in reviews.values() if isinstance(e, dict) and e.get("clause_hash") == entry["clause_hash"] and e.get("decided_at")]
            latest = max(same, key=lambda e: str(e["decided_at"]), default=None)
            stored_at = datetime.fromisoformat(latest["decided_at"]) if latest else None
            storage.ensure_unchanged(stored_at, expected_decided_at, stored_by=latest.get("decided_by") if latest else None)
        if isinstance(old, dict) and old.get("clause_hash") and old.get("clause_hash") != entry["clause_hash"]:
            # 41차 R40-CLAUSE-B — 번호가 밀려 이 칸에 남아 있던 **다른 원문**의 확인은 지우지 않고 해시 열쇠로 옮긴다
            # (판정은 원문 해시로 그 원문 줄에 잇는다 · 옛 번호 줄을 저장하면 살아 있는 「미충족」이 지워졌다)
            reviews.setdefault(f"{clause_id}@{old['clause_hash']}", old)
        reviews[clause_id] = entry
        payload["procurement_id"] = procurement_id
        analysis_store.stamp(payload, context)
        storage.stamp(payload)
        storage.write_json_atomic(path, payload)
    return entry


def facts_for(organization_id: str, evidence_scope: str | None) -> tuple[ReviewFact, ...]:
    """회사 쪽 사실로 넣을 확인 기록 전부 — `eligibility_engine.company_facts_for` 가 부른다.

    공개 시연 범위는 공용 파일을, 그 밖(내부 · 범위 없음)은 조직의 분석 폴더를 읽는다.
    깨진 파일은 건너뛴다 — 확인 기록 하나 때문에 목록 전체가 죽으면 안 된다.
    """
    if evidence_scope == "public_demo":
        paths = sorted(PUBLIC_DIR.glob(f"*.{FILE_NAME}")) if PUBLIC_DIR.exists() else []
    else:
        paths = analysis_store.iter_private_results(organization_id, FILE_NAME)
    facts: list[ReviewFact] = []
    for path in paths:
        try:
            payload = storage.read_json(path, default=None)
        except Exception as exc:  # noqa: BLE001 — 한 파일 때문에 판정 전체를 멈추지 않는다
            logger.warning("조항 확인 기록을 읽지 못했습니다: %s (%s)", path.name, exc.__class__.__name__)
            continue
        if not isinstance(payload, dict) or not payload.get("procurement_id"):
            continue
        for clause_id, entry in sorted((payload.get("reviews") or {}).items()):
            if not isinstance(entry, dict) or entry.get("state") not in STATES:
                continue
            facts.append((
                str(payload["procurement_id"]), str(clause_id), str(entry["state"]),
                str(entry.get("note") or ""), str(entry.get("decided_by") or ""),
                str(entry.get("decided_at") or ""), str(entry.get("clause_hash") or ""),
            ))
    return tuple(facts)
