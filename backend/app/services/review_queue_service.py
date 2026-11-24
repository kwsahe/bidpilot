"""「검토 중」 — 내가 손댄 공고가 어디까지 갔는가 (0919.md §4-B-3).

## 왜 필요한가

목록 화면은 **새로 들어온 것**을 보여준다. 그런데 담당자가 실제로 잃어버리는 것은
「며칠 전에 열어서 뭔가 하다 만 공고」다. 지금은 그것을 찾으려면 공고 id 를 기억하거나
목록을 처음부터 훑어야 한다. 손댄 흔적이 있는 것만 모아 **최근 활동 순**으로 세운다.

## 「손댄 흔적」의 정의

셋 중 하나라도 저장돼 있으면 이 줄에 오른다.

- **참여 결정**(`decision.json`) — 참여·보류·참여 안 함
- **최종 검토**(`review.json`) — 승인·보류·반려
- **발견 항목 처리**(`findings.json`) — 해결·재오픈

요구사항을 파싱한 것만으로는 오르지 않는다. 파싱은 「기계가 한 일」이고 이 줄은
**사람이 판단을 남긴 것**을 모으는 자리이기 때문이다.

## 무엇을 하지 않는가

**네트워크를 부르지 않는다.** 공고 제목·마감일은 이미 받아 둔 목록(`cached_only`)에서만
가져온다. 이 줄이 실호출을 하면 화면을 열 때마다 목록이 바뀐다 (ISSUE-062).

목록에서 내려간 공고(30일 창을 벗어났거나 후보에서 빠진 것)는 **빼지 않는다.** 검토 중인
일은 공고가 목록에 남아 있는지와 상관없이 끝내야 하는 일이다. 대신 제목을 지어내지
않는다 — 캐시에 없으면 제안요청서 파일 이름을, 그것도 없으면 공고 id 를 그대로 쓰고
`notice_known=False` 로 「목록에서 내려갔다」를 말한다.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from app.schemas.organization import AnalysisContext
from app.services import (
    analysis_store,
    decision_service,
    finding_resolution_service,
    home_agencies,
    notice_state_service,
    notice_version_service,
    procurement_service,
    review_service,
    rfp_parser,
)

logger = logging.getLogger(__name__)

#: 한 번에 돌려줄 최대 건수. 검토 중인 일이 이보다 많으면 화면이 아니라 일이 문제다.
MAX_ROWS = 100

#: 「손댄 흔적」으로 볼 파일. (종류, 조직 폴더 안 이름, 공개 경로 접미사)
SIGNAL_FILES: tuple[tuple[str, str, str], ...] = (
    ("decision", "decision.json", ".decision.json"),
    ("review", "review.json", ".review.json"),
    ("resolution", "findings.json", ".findings.json"),
)

#: 화면에 그대로 쓰는 말. 영문 상태값을 화면에 내보내지 않는다.
DECISION_LABELS = {"GO": "참여", "HOLD": "보류", "NO_GO": "참여 안 함", "UNREVIEWED": "미정"}
REVIEW_LABELS = {"pending": "검토 대기", "on_hold": "다시 검토", "rejected": "반려", "approved": "승인"}
SIGNAL_LABELS = {"decision": "참여 결정", "review": "최종 검토", "resolution": "발견 항목 처리"}


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def real_deadline(notice: Any) -> datetime | None:
    """실제 마감 — 입찰 마감 · 참가자격 등록 마감 · 공고문 일정표 마감 중 가장 이른 것(43차 결정 1).

    (2.0.6) 대시보드 띠(`daily_digest_service`)에 있던 함수를 여기로 옮겼다 — 탭은 입찰 마감만 봐서, 등록마감이 지난 입찰이
    띠에서는 「지남」 · 탭에서는 「살아 있는 공고 · D-3」이었다. 띠와 탭이 이 함수 하나를 쓴다.
    """
    from app.services import g2b_mapper

    raw = notice.raw_data if isinstance(notice.raw_data, dict) else {}
    stamps = [_aware(notice.deadline_at)]
    for key in ("qualification_deadline", "schedule_deadline"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            parsed = g2b_mapper.parse_datetime(value)
            if parsed is None:
                try:
                    parsed = datetime.fromisoformat(value.strip())
                except ValueError:
                    parsed = None
            stamps.append(_aware(parsed))
    real = [d for d in stamps if d is not None]
    return min(real) if real else None


def wide_listing() -> tuple[dict[str, Any], set[str]]:
    """넓은 저장본(관련 낮음 포함)의 입찰 id → 공고 · 시연 고정 공고 id. **네트워크를 부르지 않는다.**

    (2.0.6 links-2) 대시보드로 열 수 있는가 = 넓은 캐시에 있는가. 27차 LNK-R1 은 좁은 목록으로 갈랐다 — 그때는 대시보드가 관련 낮음을
    못 찾아 데모로 떨어졌지만, 2.0.5 부터 대시보드가 관련 낮음까지 한 번 더 찾는다. 대시보드 띠 「참여 미정」도 이 범위로 센다(2.0.6).
    """
    cached = procurement_service.cached_only(include_low=True)
    views = cached.notices if cached else []
    # 시연용 고정 공고(가천대 해커톤 등 · 마감) — 「살아 있는 공고」에 세지 않는다(45차 M15 · 열면 「예시 공고(마감)」)
    return {view.notice.id: view.notice for view in views}, {view.notice.id for view in views if view.pinned}


def queue_place(
    procurement_id: str,
    *,
    by_id: dict[str, Any],
    pinned_ids: set[str],
    others: dict[str, dict[str, Any]],
    moment: datetime,
) -> tuple[str, datetime | None]:
    """(살아 있음 live · 마감 지남 closed · 목록에서 내려감 gone, 판단에 쓴 마감) — 「검토 중」 탭과 대시보드 띠 「참여 미정」이 함께 쓴다.

    (2.0.6) 띠는 좁은 목록 · 실제 마감, 탭은 넓은 목록 · 입찰 마감으로 갈라, 띠를 눌러 간 탭에서 같은 공고가 다른 칸에 섰다.
    입찰은 실제 마감(`real_deadline`), 지원사업 · 직접 넣은 공고는 `other_notices` 의 마감이다. 목록에 있는데 마감을 모르면(상시 · 미상) 살아 있다.
    """
    other = others.get(procurement_id)
    if other is not None:
        listed, deadline = other["listed"], other["deadline"]
    else:
        notice = by_id.get(procurement_id)
        listed, deadline = notice is not None, real_deadline(notice) if notice is not None else None
    if not listed:
        return "gone", deadline
    if procurement_id in pinned_ids or (deadline is not None and deadline < moment):
        return "closed", deadline
    # (2.0.6 마지막 검토) 입찰에 마감이 아무 데도 없으면 개찰이 지난 공고는 끝난 것이다 — 통합 목록 `closed` 와 같은 규칙(opportunity_service).
    # 개찰일을 마감으로 보이지는 않는다(D-day 를 지어내지 않음 · 마감은 None 그대로).
    if other is None and deadline is None:
        from app.services import g2b_mapper

        notice = by_id.get(procurement_id)
        raw = notice.raw_data if notice is not None and isinstance(notice.raw_data, dict) else {}
        opening = _aware(g2b_mapper.parse_datetime(str(raw.get("opening_at") or "")))
        if opening is not None and opening < moment:
            return "closed", None
    return "live", deadline


def _candidate_ids(context: AnalysisContext | None) -> set[str]:
    """손댄 흔적이 있는 공고 id. 조직 폴더와 공개 폴더 양쪽을 본다(레거시 결과 포함)."""
    ids: set[str] = set()

    if analysis_store.is_private(context) and context is not None:
        for _kind, file_name, _suffix in SIGNAL_FILES:
            for path in analysis_store.iter_private_results(context.organization_id, file_name):
                ids.add(path.parent.name)

    # 공개 경로에 남은 레거시 결과. 조직 구조로 옮기기 전에 저장된 것들이다.
    for _kind, _file_name, suffix in SIGNAL_FILES:
        directory = decision_service.DECISION_DIR if suffix == ".decision.json" else review_service.REVIEW_DIR
        if not directory.exists():
            continue
        for path in directory.glob(f"*{suffix}"):
            ids.add(path.name[: -len(suffix)])

    return ids


def _signal(kind: str, procurement_id: str, context: AnalysisContext | None) -> dict[str, Any] | None:
    """한 종류의 흔적을 읽는다. 읽지 못하면 없는 것으로 본다 — 줄 하나가 화면을 막지 않는다."""
    try:
        if kind == "decision":
            decision = decision_service.load_decision(procurement_id, context)
            # 결정 파일이 없어도 `load_decision` 은 「미정」을 만들어 돌려준다. 파일이 실제로
            # 있는지는 경로로 확인해야 한다 — 그러지 않으면 모든 공고가 이 줄에 오른다.
            if not decision_service.decision_path(procurement_id, context).exists():
                return None
            return {
                "kind": kind,
                "at": _aware(decision.decided_at),
                "who": decision.recorded_by or decision.decided_by,
                "status": decision.status,
                "label": DECISION_LABELS.get(decision.status, decision.status),
            }
        if kind == "review":
            if not review_service.review_path(procurement_id, context).exists():
                return None
            review = review_service.load_decision(procurement_id, context)
            return {
                "kind": kind,
                "at": _aware(review.decided_at),
                "who": review.reviewer,
                "status": review.status,
                "label": REVIEW_LABELS.get(review.status, review.status),
            }
        resolutions = finding_resolution_service.load_resolutions(procurement_id, context).resolutions
        if not resolutions:
            return None
        newest = max(resolutions, key=lambda item: _aware(item.decided_at) or datetime.min.replace(tzinfo=timezone.utc))
        unresolved = [item for item in resolutions if item.status == "open"]
        return {
            "kind": "resolution",
            "at": _aware(newest.decided_at),
            "who": newest.recorded_by or newest.reviewer,
            "status": "open" if unresolved else "resolved",
            "label": f"미해결 {len(unresolved)}건" if unresolved else f"{len(resolutions)}건 해결",
            "open_count": len(unresolved),
        }
    except Exception as exc:  # noqa: BLE001 — 한 공고가 못 읽혀도 나머지는 보여준다
        logger.debug("검토 흔적을 읽지 못했습니다 (%s/%s): %s", procurement_id, kind, exc.__class__.__name__)
        return None


def _next_step(signals: dict[str, dict[str, Any]], *, parsed: bool) -> str:
    """「다음 할 일」 한 줄. 저장된 것만 보고 정한다 — 무거운 분석을 다시 돌리지 않는다.

    순서는 대시보드 「지금 할 일」과 같은 생각이다: **막는 것이 먼저**, 그다음 사람의 판단.
    """
    decision = signals.get("decision")
    review = signals.get("review")
    if decision is not None and decision["status"] in ("NO_GO", "HOLD"):
        # 참여하지 않기로 했거나 미뤄 둔 건은 더 시킬 일이 없다. **파싱 · 점검 발견보다 먼저 본다** —
        # 참여하지 않기로 한 공고에 「제안요청서 파싱」 · 「점검에서 고칠 것 n건」을 시키면 목록이 끝나지 않는 일로 찬다(45차 마지막 검토).
        return "없음 — " + DECISION_LABELS[decision["status"]]
    resolution = signals.get("resolution")
    if resolution and resolution.get("open_count"):
        return f"점검에서 고칠 것 {resolution['open_count']}건 처리"
    if not parsed:
        # 요구사항이 없으면 참여 여부도 제대로 정할 수 없다. 그것이 먼저다.
        return "제안요청서에서 요구사항 뽑기"
    if decision is None or decision["status"] == "UNREVIEWED":
        return "참여 여부 결정"
    if review is None or review["status"] == "pending":
        return "담당자 최종 검토"
    if review["status"] == "on_hold":
        return "수정 권고 반영 후 다시 검토"
    if review["status"] == "rejected":
        return "반려 사유 반영 후 재검토"
    return "없음 — 승인 완료"


def _with_open_findings(signals: dict[str, dict[str, Any]], open_findings: int) -> dict[str, dict[str, Any]]:
    """다음 할 일에 쓸 발견 수를 `state.open_findings` 로 맞춘 사본(신호 자체 · 「손댄 흔적」 판단은 그대로)."""
    out = dict(signals)
    if open_findings:
        out["resolution"] = {**signals.get("resolution", {}), "open_count": open_findings}
    elif "resolution" in out:
        out["resolution"] = {**out["resolution"], "open_count": 0}
    return out


def next_step_of_state(state: Any) -> str:
    """목록 항목의 분석 상태(`AnalysisState`)로 같은 「다음 할 일」을 고른다 — 오늘 브리핑 「오늘 실제 행동」(37차 §3-H).

    새 문장을 만들지 않는다 — 검토 목록과 같은 `_next_step` 이다. 흔적이 없으면(분석 전) 「제안요청서에서 요구사항 뽑기」.
    """
    if state is None:
        return _next_step({}, parsed=False)
    signals: dict[str, dict[str, Any]] = {}
    if getattr(state, "open_findings", 0):
        signals["resolution"] = {"open_count": state.open_findings}
    if getattr(state, "decision", None):
        signals["decision"] = {"status": state.decision}
    if getattr(state, "review", None):
        signals["review"] = {"status": state.review}
    return _next_step(signals, parsed=bool(getattr(state, "parsed", False)))


def _test_record(procurement_id: str, document: str | None) -> bool:
    """가상 예시 · 시험 기록(45차 M15) — 「검토 중」에 「synthetic-rfp-0001」 · 「제안요청서: synthetic_ai_training_rfp.pdf」가 섞였다."""
    return procurement_id.startswith("synthetic-") or bool(document and document.startswith("synthetic_"))


def _fallback_title(procurement_id: str) -> tuple[str, str | None]:
    """캐시에 없는 공고의 표시 이름. **지어내지 않는다.**"""
    stored = notice_version_service.latest_title(procurement_id)
    if stored:
        return stored, None
    try:
        document = rfp_parser.load_generated(procurement_id).document
    except Exception:  # noqa: BLE001 — 파싱 결과가 없으면 id 만 보여준다
        return procurement_id, None
    if isinstance(document, str) and document.strip():
        return procurement_id, document.strip()
    return procurement_id, None


def other_notices(ids: Iterable[str], *, context: AnalysisContext | None) -> dict[str, dict[str, Any]]:
    """지원사업(`bizinfo-`) · 직접 넣은 공고(`manual-`)의 제목 · 기관 · 마감 · 갈 곳 · 결정 낱말. 입찰 id 는 넣지 않는다.

    (2.0.6 links-1) 두 갈래도 같은 결정 파일을 쓴다(44차 M4) — 여기서 입찰로 다뤄 id 글자 제목 · 「목록에서 내려감」 ·
    입찰 정리표 단추가 나왔다. 지우지 않고 갈래를 나눈다: 결정 낱말은 그 화면과 같은 벌(`decision_service.SUPPORT_LABELS`),
    누르면 그 화면(지원사업 신청 분석 · 직접 넣기 탭)으로 간다. 대시보드 띠(`daily_digest_service`)도 마감을 여기서 읽는다.
    """
    from app.services import manual_notice_service, opportunity_service, support_application_service

    wanted = [pid for pid in ids if pid.startswith(decision_service.SUPPORT_PREFIXES)]
    programs = support_application_service.cached_programs({pid for pid in wanted if pid.startswith("bizinfo-")})
    out: dict[str, dict[str, Any]] = {}
    for pid in wanted:
        if pid.startswith("bizinfo-"):
            program = programs.get(pid)
            listed = program is not None
            if program is None and context is not None:
                # 목록에서 빠진 사업도 저장된 분석이 있으면 남겨 둔 사본으로 지원사업 화면이 연다(33차 §3-A-6)
                program = support_application_service.archived_program(pid, context.organization_id)
            out[pid] = {
                "kind": "support",
                "title": program.title if program else None,
                "agency": program.agency if program else None,
                "deadline": opportunity_service._deadline_of_program(program) if program else None,
                "listed": listed,
                "open_path": f"/support/{pid}" if program else None,
                "route_label": "지원사업 신청 분석 열기",
                "labels": decision_service.SUPPORT_LABELS,
            }
            continue
        notice = None
        if context is not None:
            try:
                notice = manual_notice_service.get(context.organization_id, pid)
            except Exception:  # noqa: BLE001 — 지웠거나 못 읽은 공고는 id 만 보인다(지어내지 않는다)
                notice = None
        # (2.0.6) 참가신청 · 등록 마감이 더 이르면 그쪽(43차 Q20) — 직접 넣기 · 「전체」 탭 행의 실제 마감과 같은 쌍
        stamps = [_aware(d) for d in (notice.deadline, notice.apply_deadline) if d is not None] if notice else []
        out[pid] = {
            "kind": "manual",
            "title": notice.title if notice else None,
            "agency": notice.agency if notice else None,
            "deadline": min(stamps) if stamps else None,
            "listed": notice is not None,
            "open_path": f"/opportunities?tab=manual&manual={pid}" if notice else None,
            "route_label": "직접 넣은 공고 보기",
            # 직접 넣기 탭의 결정 칸과 같은 벌 — 수혜(지원금)면 신청 낱말, 입찰 · 수행이면 참여 낱말(ManualConfirm)
            "labels": decision_service.SUPPORT_LABELS if notice is not None and notice.recruit == "benefit" else decision_service.BID_LABELS,
        }
    return out


def _other_next_step(status: str | None, other: dict[str, Any]) -> str:
    """지원사업 · 직접 넣은 공고의 「다음 할 일」 — 그 화면의 결정 칸 기준(정리표 · 요구사항 뽑기는 입찰에만)."""
    labels = other["labels"]
    support = labels is decision_service.SUPPORT_LABELS
    # (2.0.6) 지원금 「검토 중」(HOLD)도 「없음 — 검토 중」 — 띠 「참여 미정」(`awaiting_decision`)은 HOLD 를 결정된 것으로 세는데
    # 탭만 「신청 여부 결정」이라 해, 탭이 정할 일이라 한 사업이 띠 숫자 · 「참여 미정만」 거르기에서 빠졌다(입찰 HOLD 와 같은 꼴).
    if status in ("NO_GO", "HOLD"):
        return "없음 — " + labels[status]
    if status == "GO":
        return other["route_label"]
    return "신청 여부 결정" if support else "참여 여부 결정"


def build(
    *,
    context: AnalysisContext | None = None,
    mine: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """검토 중인 공고를 최근 활동 순으로. **네트워크를 부르지 않는다.**

    `mine` 이 있으면 그 계정이 남긴 것을 앞으로 올린다(거르지는 않는다 — 동료가 손댄 건을
    숨기면 「아무도 안 보고 있는 건」이 생긴다).
    """
    moment = now or datetime.now(timezone.utc)
    # (2.0.6 links-2) 넓은 캐시(관련 낮음 포함) — 좁은 목록으로 두면 살아 있는 비추천 입찰이 「목록에서 내려감」으로 적혔다
    by_id, pinned_ids = wide_listing()

    rows: list[dict[str, Any]] = []
    # 후보 집합은 **띠와 같은 곳**에서 온다 (0920 §4-B-3 · ISSUE-076-a).
    # 예전에는 여기서 「파일이 있는 공고」만 모으고 띠는 「파싱된 공고」를 셌다 —
    # 정의가 달라 같은 순간 띠 5건 · 탭 0건이었다.
    queue_ids = notice_state_service.review_queue_ids(context)
    others = other_notices(queue_ids, context=context)
    for procurement_id in queue_ids:
        state = notice_state_service.state_of(procurement_id, context)
        signals = {}
        for kind, _file_name, _suffix in SIGNAL_FILES:
            found = _signal(kind, procurement_id, context)
            if found is not None:
                signals[kind] = found
        # 「분석을 시작했고 결정이 안 난 공고」도 올린다 — 사람이 아직 아무것도 저장하지
        # 않았어도 그것이 바로 담당자가 잊어버리는 자리다.
        if not signals and not state.awaiting_decision:
            continue

        stamps = [signal["at"] for signal in signals.values() if signal["at"] is not None]
        last_at = max(stamps) if stamps else None
        last_kind = None
        if last_at is not None:
            last_kind = next(kind for kind, signal in signals.items() if signal["at"] == last_at)

        other = others.get(procurement_id)
        if other is not None:
            title, document = other["title"] or procurement_id, None
            agency, known = other["agency"], other["title"] is not None
        else:
            notice = by_id.get(procurement_id)
            title, document = (notice.title, None) if notice else _fallback_title(procurement_id)
            # 10-31 독립 검토 — 다른 화면처럼 조달청 대행은 「수요기관(조달청 대행)」(저장값은 지역 판정용 그대로)
            agency = home_agencies.display_agency(notice.agency, (notice.raw_data or {}).get("demand_institution")) if notice else None
            known = notice is not None
        # (2.0.6) D-day · 살아 있음/지남은 띠와 같은 함수 · 같은 마감(입찰은 실제 마감)
        place, deadline = queue_place(procurement_id, by_id=by_id, pinned_ids=pinned_ids, others=others, moment=moment)
        if _test_record(procurement_id, document):
            continue
        decision_status = signals["decision"]["status"] if "decision" in signals else None
        rows.append(
            {
                "procurement_id": procurement_id,
                # (2.0.6 links-1) 입찰(bid) · 지원사업(support) · 직접 넣은 공고(manual) — 화면은 갈 곳 · 정리표 단추를 이것으로 가른다
                "kind": other["kind"] if other else "bid",
                # 누르면 갈 곳(지원사업 · 직접 넣은 공고만 · 입찰은 화면이 대시보드 주소를 만든다)
                "open_path": other["open_path"] if other else None,
                "title": title,
                "agency": agency,
                # 목록에서 내려간 공고인가. 화면은 이것을 그대로 적는다 — 제목 대신 id 가
                # 보이는 이유를 말해 주지 않으면 고장으로 읽힌다.
                "notice_known": known,
                # 받아 둔 캐시에는 있다(제목을 안다) — 옛 응답과의 호환(2.0.6 부터 notice_known 과 같다)
                "in_cache": known,
                "document": document,
                "deadline_at": deadline.isoformat() if deadline else None,
                "days_left": (deadline - moment).days if deadline else None,
                "last_activity_at": last_at.isoformat() if last_at else None,
                # (2.0.6) 지원금 결정은 「신청 결정」 — 같은 줄의 결정 낱말(신청 · 검토 중)과 맞춘다(「참여 결정」이 함께 보였다)
                "last_activity_kind": (
                    "신청 결정" if last_kind == "decision" and other and other["labels"] is decision_service.SUPPORT_LABELS
                    else SIGNAL_LABELS.get(last_kind or "", None)
                ),
                "recorded_by": next(
                    (signals[kind]["who"] for kind in ("review", "decision", "resolution") if signals.get(kind) and signals[kind]["who"]),
                    None,
                ),
                # (2.0.6) 결정 전은 입찰 줄과 같은 「미정」 — 그 화면 낱말(「결정 전」)에 화면이 앞말 「결정」을 붙여 「결정 결정 전」이 됐다
                "decision_label": (
                    None if decision_status is None
                    else signals["decision"]["label"] if not other or decision_status == "UNREVIEWED"
                    else other["labels"].get(decision_status, decision_status)
                ),
                "review_label": signals["review"]["label"] if "review" in signals else None,
                # 45차 M6 · 마지막 검토 — 발견 수는 머리 칩 · 대시보드 7단계와 같은 값(`state.open_findings`)
                "resolution_label": (
                    f"미해결 {state.open_findings}건" if state.open_findings
                    else signals["resolution"]["label"] if "resolution" in signals else None
                ),
                "next_step": (
                    _other_next_step(decision_status, other) if other
                    else _next_step(_with_open_findings(signals, state.open_findings), parsed=state.parsed)
                ),
                # 43차 N4 — 살아 있음 · 마감 지남 · 목록에서 내려감(18건 중 살아 있는 것은 1건이었다)
                "queue_state": place,
                # 목록 행·레이더가 쓰는 것과 **같은 분석 상태**를 함께 싣는다.
                "analysis_state": state.to_dict(),
            }
        )

    # 최근 활동 순으로 세운 뒤, 내 것을 앞으로 끌어올린다. 파이썬 정렬은 안정적이라
    # 두 번 부르면 「내 것 먼저, 그 안에서 최근 순」이 된다. ISO 문자열은 사전순 = 시간순이고,
    # 활동 시각이 없는 줄은 빈 문자열이라 내림차순에서 맨 뒤로 간다.
    #
    # 시각이 같을 때 **공고 id 로 한 번 더 가른다.** 같은 초에 저장된 건이 여러 개면 순서가
    # 집합 순회 순서를 따라가 새로고침할 때마다 목록이 뒤바뀌었다(내 테스트가 세 번에 한 번
    # 실패해서 드러났다). 같은 화면을 두 번 열면 같은 순서여야 한다.
    rows.sort(key=lambda row: (row["last_activity_at"] or "", row["procurement_id"]), reverse=True)
    if mine:
        rows.sort(key=lambda row: 0 if row["recorded_by"] == mine else 1)
    # 43차 N4 — 살아 있는 것 먼저 · 마감 지남 · 목록에서 내려감(그 안은 위 순서 그대로)
    order = {"live": 0, "closed": 1, "gone": 2}
    rows.sort(key=lambda row: order[row["queue_state"]])

    return {
        "as_of": moment.isoformat(),
        "mine": mine,
        "counts": {state: sum(1 for row in rows if row["queue_state"] == state) for state in order},
        "total": len(rows),
        "truncated": len(rows) > MAX_ROWS,
        "items": rows[:MAX_ROWS],
    }
