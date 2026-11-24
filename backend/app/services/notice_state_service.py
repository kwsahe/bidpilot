"""공고 하나의 **분석 상태** — 흩어져 있던 판정을 한 곳에 모은다 (0920.md §4-B-3 · ISSUE-076).

## 왜 필요한가

결정·검토·조건·발견 항목은 대시보드 훅만 읽고 있었다. 그래서 같은 공고가 화면마다 다른
상태로 보였다.

- 대시보드 띠는 「내 결정 대기 **5**」, 사업기회의 「검토 중」 탭은 **0건**.
  정의가 아예 달랐다 — 띠는 「파싱된 공고 + 결정 미정」, 탭은 「결정·검토·발견 처리 **파일이
  있는** 공고」.
- 사업기회 행은 요구사항 55건·조치·제출 전 점검 47건이 이미 있는 공고에도 「입찰 분석 시작」
  이라고 적었다. 분석 여부를 모르기 때문이다.
- 레이더는 결정을 몰라서 「참여 안 함」으로 정한 공고가 한복판에 남았다.

여기서 한 벌만 판정하고, 띠·탭·목록 행·레이더가 **그것만** 쓴다.

## 「검토 중」의 정의

**분석을 시작했고 결정이 안 난 공고 + 사람이 손댄 흔적이 있는 공고.** 두 정의를 합쳤다 —
어느 쪽만 쓰면 다른 화면에서 빠지는 공고가 생긴다.

## 비싸지 않게 만든다

요구사항 수를 세려면 파싱 결과 파일을 열어야 하는데, 통합 목록은 공고가 100건이 넘는다.
전부 열면 목록이 몇 초씩 걸린다. 그래서 **먼저 싼 것부터 본다** — 파일이 «있는지»만 보고,
흔적이 하나도 없으면 거기서 끝낸다. 실제로 손댄 공고는 몇 건뿐이라 비용이 그 몇 건에만 붙는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core import storage
from app.schemas.organization import AnalysisContext
from app.services import (
    analysis_store,
    auditor_service,
    critical_condition_service,
    decision_service,
    finding_resolution_service,
    review_service,
    rfp_parser,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NoticeState:
    """한 공고의 분석 상태. **모르는 것은 None 이다** — 0 으로 단정하지 않는다."""

    procurement_id: str
    #: 요구사항을 뽑아 둔 적이 있는가.
    parsed: bool = False
    #: 뽑아 둔 요구사항 수. 파싱 전이면 None.
    requirement_count: int | None = None
    #: 그중 「확인 필요」(status == "check"). 화면 배지의 두 번째 숫자가 이것이다.
    check_count: int | None = None
    #: 담당자가 확인·정정한 항목 수 (review_status). **위와 다른 값이다** —
    #: 「확인 필요」는 기계가 못 정한 것이고, 이것은 사람이 손본 것이다.
    confirmed_count: int | None = None
    #: 저장된 참여 결정. **파일이 없으면 None** — 「미정(UNREVIEWED)」과 구분한다.
    decision: str | None = None
    #: 저장된 담당자 최종 검토. 없으면 None.
    review: str | None = None
    #: 미해결 발견 항목 수.
    open_findings: int = 0
    #: 참가를 막는 조건 수. **조건을 탐지한 적이 없으면 None** — 0 이 아니다.
    blocking_conditions: int | None = None
    #: 사람이 마지막으로 손댄 시각.
    last_activity_at: datetime | None = None

    @property
    def touched(self) -> bool:
        """사람이 판단을 남긴 적이 있는가 (결정·검토·발견 처리 중 하나라도)."""
        return self.decision is not None or self.review is not None or self.last_activity_at is not None

    @property
    def awaiting_decision(self) -> bool:
        """「검토 중」에 오를 공고인가 — 분석을 시작했고 결정이 안 난 것.

        결정 파일이 있어도 값이 「미정」이면 여전히 결정이 안 난 것이다.
        """
        undecided = self.decision in (None, "UNREVIEWED")
        return undecided and (self.parsed or self.touched)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parsed": self.parsed,
            "requirement_count": self.requirement_count,
            "check_count": self.check_count,
            "confirmed_count": self.confirmed_count,
            "decision": self.decision,
            "review": self.review,
            "open_findings": self.open_findings,
            "blocking_conditions": self.blocking_conditions,
            "last_activity_at": self.last_activity_at.isoformat() if self.last_activity_at else None,
        }


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _newest(*moments: datetime | None) -> datetime | None:
    stamps = [m for m in (_aware(x) for x in moments) if m is not None]
    return max(stamps) if stamps else None


#: 파일이 안 바뀌었으면 다시 세지 않는다 — (경로, 수정 시각, 크기) → 개수 셋.
#:
#: 요구사항 파일은 원문까지 들고 있어 한 건이 수백 KB 다. 통합 목록은 파싱된 공고를 전부
#: 훑으므로, 목록을 한 번 그릴 때마다 수 MB 를 다시 읽고 있었다. 내용이 같으면 읽지 않는다.
_COUNT_CACHE: dict[tuple[str, int, int], tuple[int | None, int | None, int | None]] = {}
_COUNT_CACHE_MAX = 256


def _requirement_counts(procurement_id: str) -> tuple[int | None, int | None, int | None]:
    """(요구사항 수, 확인 필요 수, 담당자 확인 수). 못 읽으면 전부 None.

    `rfp_parser.load_generated` 를 쓰지 않는다 — 그쪽은 정정 덧입히기와 유형 재분류까지 해서
    한 건에 20ms 넘게 걸린다. 여기서 필요한 것은 개수 셋뿐이다.
    """
    try:
        path = rfp_parser.generated_path(procurement_id)
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        hit = _COUNT_CACHE.get(key)
        if hit is not None:
            return hit
        payload = storage.read_json(path, default=None)
    except Exception as exc:  # noqa: BLE001 — 한 공고가 못 읽혀도 목록은 그려야 한다
        logger.debug("요구사항 파일을 읽지 못했습니다 (%s): %s", procurement_id, exc.__class__.__name__)
        return None, None, None
    if not isinstance(payload, dict):
        return None, None, None
    items = payload.get("requirements")
    if not isinstance(items, list):
        return None, None, None
    rows = [row for row in items if isinstance(row, dict)]
    counts = (
        len(rows),
        sum(1 for row in rows if row.get("status") == "check"),
        sum(1 for row in rows if row.get("review_status") in ("confirmed", "corrected")),
    )
    if len(_COUNT_CACHE) >= _COUNT_CACHE_MAX:
        _COUNT_CACHE.clear()
    _COUNT_CACHE[key] = counts
    return counts


def _read_decision(procurement_id: str, context: AnalysisContext | None) -> tuple[str | None, datetime | None]:
    """저장된 참여 결정. **파일이 없으면 None** — `load_decision` 은 없어도 「미정」을 지어낸다."""
    try:
        if not decision_service.decision_path(procurement_id, context).exists():
            return None, None
        decision = decision_service.load_decision(procurement_id, context)
        return decision.status, _aware(decision.decided_at)
    except Exception as exc:  # noqa: BLE001
        logger.debug("결정을 읽지 못했습니다 (%s): %s", procurement_id, exc.__class__.__name__)
        return None, None


def _read_review(procurement_id: str, context: AnalysisContext | None) -> tuple[str | None, datetime | None]:
    try:
        review = review_service.load_decision(procurement_id, context)
    except Exception:  # noqa: BLE001 — 없는 것이 정상이다
        return None, None
    return review.status, _aware(review.decided_at)


def _read_findings(procurement_id: str, context: AnalysisContext | None, *, parsed: bool = False) -> tuple[int, datetime | None]:
    """안 고친 발견 수 · 마지막 처리 시각.

    45차 M6 — 예전에는 사람이 「다시 열기」를 누른 처리 기록만 셌다(「검토 중」 탭 1건 · 대시보드 「안 고친 문제 61」).
    요구사항을 뽑은 공고는 **가장 최근 점검 결과의 발견 중 해결 처리하지 않은 것**을 센다 — 대시보드 7단계와 같은 수.
    """
    try:
        resolutions = finding_resolution_service.load_resolutions(procurement_id, context).resolutions
    except Exception as exc:  # noqa: BLE001
        logger.debug("발견 항목 처리를 읽지 못했습니다 (%s): %s", procurement_id, exc.__class__.__name__)
        resolutions = []
    newest = max((_aware(r.decided_at) for r in resolutions if r.decided_at), default=None)
    run = None
    # 회사 폴더(공고마다 작은 폴더)일 때만 — 공용 폴더(가상 예시 · 공개 배포)는 모든 공고의 결과가 섞여 있어 공고마다 수백 개를 읽게 된다(45차 마지막 검토)
    if parsed and context is not None and context.is_private:
        try:
            run = auditor_service.latest_stored_run(procurement_id, context)
        except Exception as exc:  # noqa: BLE001
            logger.debug("최근 점검 결과를 읽지 못했습니다 (%s): %s", procurement_id, exc.__class__.__name__)
    if run is None:
        return sum(1 for r in resolutions if r.status == "open"), newest
    stored = {r.key for r in resolutions}
    resolved = {r.key for r in resolutions if r.status == "resolved"}
    return sum(1 for f in run.findings if finding_resolution_service.shown_key(f, stored) not in resolved), newest


def _read_blocking(procurement_id: str, context: AnalysisContext | None) -> int | None:
    """참가를 막는 조건 수. 탐지한 적이 없으면 None — 「막는 것이 없다」와 구분한다."""
    try:
        gate = critical_condition_service.gate_for(procurement_id, context)
    except Exception as exc:  # noqa: BLE001
        logger.debug("조건 게이트를 읽지 못했습니다 (%s): %s", procurement_id, exc.__class__.__name__)
        return None
    return None if gate is None else len(gate.blocker_ids)


def state_of(procurement_id: str, context: AnalysisContext | None = None) -> NoticeState:
    """공고 하나의 분석 상태. 흔적이 없으면 싼 값으로 끝낸다."""
    try:
        parsed = rfp_parser.generated_path(procurement_id).exists()
    except Exception:  # noqa: BLE001 — 허용되지 않는 id 형태
        parsed = False

    decision, decided_at = _read_decision(procurement_id, context)
    review, reviewed_at = _read_review(procurement_id, context)
    open_findings, resolved_at = _read_findings(procurement_id, context, parsed=parsed)
    last_activity_at = _newest(decided_at, reviewed_at, resolved_at)

    # 흔적이 하나도 없으면 여기서 끝낸다 — 목록 100건에 파일을 다 열지 않기 위해서다.
    if not parsed and decision is None and review is None and open_findings == 0 and last_activity_at is None:
        return NoticeState(procurement_id=procurement_id)

    requirement_count, check_count, confirmed_count = (
        _requirement_counts(procurement_id) if parsed else (None, None, None)
    )
    return NoticeState(
        procurement_id=procurement_id,
        parsed=parsed,
        requirement_count=requirement_count,
        check_count=check_count,
        confirmed_count=confirmed_count,
        decision=decision,
        review=review,
        open_findings=open_findings,
        blocking_conditions=_read_blocking(procurement_id, context),
        last_activity_at=last_activity_at,
    )


def touched_ids(context: AnalysisContext | None) -> set[str]:
    """사람이 손댄 흔적이 있는 공고 id.

    조직 폴더와 공개 폴더 양쪽을 본다 — 조직 구조로 옮기기 전에 저장된 결과가 공개 폴더에
    남아 있다(가천대 피지컬의 발견 처리 기록이 그렇다).
    """
    ids: set[str] = set()
    files = (
        ("decision.json", decision_service.DECISION_DIR, ".decision.json"),
        ("review.json", review_service.REVIEW_DIR, ".review.json"),
        ("findings.json", review_service.REVIEW_DIR, ".findings.json"),
    )
    if analysis_store.is_private(context) and context is not None:
        for file_name, _directory, _suffix in files:
            for path in analysis_store.iter_private_results(context.organization_id, file_name):
                ids.add(path.parent.name)
    for _file_name, directory, suffix in files:
        if not directory.exists():
            continue
        for path in directory.glob(f"*{suffix}"):
            ids.add(path.name[: -len(suffix)])
    return ids


def parsed_ids() -> set[str]:
    """요구사항을 뽑아 둔 공고 id. 「분석을 시작했다」의 정의다."""
    directory = rfp_parser.GENERATED_DIR
    if not directory.exists():
        return set()
    return {path.name[: -len(".requirements.json")] for path in directory.glob("*.requirements.json")}


def review_queue_ids(context: AnalysisContext | None) -> set[str]:
    """「검토 중」에 오를 후보 id — 분석을 시작했거나 사람이 손댄 공고.

    **띠와 탭이 같은 집합을 보게 하는 단 하나의 자리다** (ISSUE-076-a).
    가상 예시 공고(`synthetic-`)는 연습 기록이라 세지 않는다(45차 M15 — 「검토 중」에 개발용 번호로 섞였다).
    """
    return {pid for pid in parsed_ids() | touched_ids(context) if not pid.startswith("synthetic-")}
