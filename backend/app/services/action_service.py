"""공고별 Action Checklist 저장·자동 씨앗 서비스.

- Critical Condition 보고서에서 행동이 필요한 조건(BLOCKER/ACTION/CHECK)마다 항목을 하나씩 만든다.
  같은 조건(source_condition_id)으로는 두 번 만들지 않는다 (재탐지해도 중복 없음).
- 완료(done)는 사람만 표시한다. 시스템이 완료로 바꾸지 않는다.
- 저장은 data/public/actions/<id>.actions.json (원자적 쓰기).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core import requester, storage
from app.core.paths import DATA_ROOT
from app.schemas.organization import AnalysisContext
from app.services import analysis_store
from app.schemas.action import (
    ActionChecklist,
    ActionCounts,
    ActionCreateRequest,
    ActionItem,
    ActionUpdateRequest,
)
from app.schemas.critical_condition import CriticalConditionReport
from app.services.finding_resolution_service import fnv1a32

ACTION_DIR = DATA_ROOT / "public" / "actions"
_KST = timezone(timedelta(hours=9))

_PRIORITY_BY_STATUS = {"BLOCKER": "urgent", "ACTION": "high", "CHECK": "normal"}
_TITLE_BY_TYPE = {
    "briefing_attendance": "제안요청 설명회 참석 등록·참석",
    "pre_registration": "사전등록 완료",
    "region_restriction": "지역제한 충족 여부 확인 (사업자등록증 소재지)",
    "industry_license": "업종·면허 등록 여부 확인 및 증빙 준비",
    "direct_production": "직접생산확인증명서 준비",
    "sme_certificate": "중소기업확인서 발급·유효기간 확인",
    "performance_record": "유사 수행실적 증빙(계약서·완료확인서) 준비",
    "staffing": "투입 인력 자격·경력 증빙 준비",
    "bid_bond": "입찰보증금 납부 방법·기한 확인",
    "onsite_submission": "방문·우편 제출 일정과 담당자 지정",
    "copies": "제출 부수대로 인쇄·제본 준비",
    "file_format": "제출 파일 형식(PDF/HWP/USB) 준비",
    "presentation": "제안 발표·시연 준비",
    "security_pledge": "보안서약서 서명·제출",
    "separate_procedure": "별도 절차(사전심사 등) 신청",
    "attendance_certificate": "참석확인서 수령·보관",
    "mandatory_form": "지정 서식으로 서류 작성",
    "deadline_passed": "마감 경과 — 참여 불가 여부 확인",
    "eligibility_fail": "자격 규칙 「불가」 사유 확인",
}

# 조건 하나가 «할 일 하나»로 끝나지 않는 것들.
#
# 「제안요청 설명회 참석 등록·참석」 한 줄만 남기면, 담당자는 그 한 줄에 체크하고
# 사전 신청기한을 놓친다 — 설명회는 참석 자체보다 «언제까지 신청하는가»에서 떨어진다.
# 그래서 놓치는 자리가 여럿인 조건만 골라 실제로 해야 하는 순서대로 쪼갠다.
# 여기 없는 조건은 지금처럼 _TITLE_BY_TYPE 한 줄로 남는다 — 일부러 늘리지 않는다.
_STEPS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "briefing_attendance": (
        "현장설명(제안요청 설명회) 참석이 «필수»인지 원문에서 확인",
        "설명회 일시와 장소 확인",
        "사전 신청기한 확인 — 기한을 넘기면 참석해도 인정되지 않는다",
        "참석확인서 등 증빙 수령 방법 확인",
    ),
    "pre_registration": (
        "입찰 참가 등록기한 확인",
        "나라장터 전자입찰 이용자 등록 상태 확인",
        "등록에 필요한 서류(사업자등록증·인증서 등) 준비",
    ),
    "industry_license": (
        "공고가 요구하는 업종코드·면허 확인",
        "회사 보유 등록·신고 현황과 대조",
        "증빙서류(등록증·신고필증) 유효기간 확인",
    ),
    "region_restriction": (
        "제한 대상 지역과 판단 기준(본사·지사 소재지 등) 확인",
        "사업자등록증 소재지가 그 기준을 만족하는지 확인",
        "만족하지 않으면 지점·사업장 등 예외 자격이 있는지 확인",
    ),
    "performance_record": (
        "요구하는 실적의 기간·금액·건수 기준 확인",
        "해당 실적의 계약서·완료확인서 확보",
        "증빙이 불충분하면 충족으로 확정하지 말 것",
    ),
    "presentation": (
        "발표·제안설명회 실시 여부와 일시 확인",
        "발표 시간·자료 형식·제출기한 확인",
        "발표자 지정과 리허설 일정 확보",
    ),
    "bid_bond": (
        "입찰보증금 요구 여부와 요율 확인",
        "납부 방법(보증서·현금)과 기한 확인",
        "보증서 발급 소요일을 역산해 일정 확보",
    ),
    "mandatory_form": (
        "공고 첨부의 지정 서식 원본 내려받기",
        "지정 서식으로 작성 — 자체 양식은 형식 요건 탈락 사유가 될 수 있다",
        "서명·날인이 필요한 서식 확인",
    ),
}


class ActionNotFoundError(LookupError):
    """없는 action id."""


def checklist_path(procurement_id: str, context: "AnalysisContext | None" = None) -> Path:
    safe = storage.safe_id(procurement_id, what='공고 id')
    return analysis_store.resolve_path(context, safe, public_path=ACTION_DIR / f"{safe}.actions.json", file_name="actions.json")


def _now() -> datetime:
    """저장 도장과 「기한 지남」 판정이 같은 시계를 본다 (ISSUE-133 · prompt_07 §4-A).

    `counts_of` 가 `due_at < moment` 로 기한 지난 할 일을 세고, 그 수가 화면의
    「기한 지남 N」 배지와 「기한 지난 체크리스트 N건」 경고가 된다 — 공고 마감 판정이
    앞당겨진 시계를 볼 때 이쪽만 실제 시계에 남으면 한 화면이 두 날짜를 말한다.
    """
    return storage.utc_now()


def _load_items(procurement_id: str, context: "AnalysisContext | None" = None) -> list[ActionItem]:
    payload = storage.read_json(checklist_path(procurement_id, context), default=None)
    if not isinstance(payload, dict):
        return []
    analysis_store.assert_owner(payload, context)
    return [ActionItem.model_validate(item) for item in payload.get("items", [])]


def _save_items(procurement_id: str, items: list[ActionItem], context: "AnalysisContext | None" = None) -> ActionChecklist:
    payload: dict[str, Any] = {
        "procurement_id": procurement_id,
        "items": [item.model_dump(mode="json") for item in items],
    }
    analysis_store.stamp(payload, context)
    storage.stamp(payload)
    storage.write_json_atomic(checklist_path(procurement_id, context), payload)
    return build_checklist(procurement_id, items, updated_at=_now(), context=context)


def counts_of(items: list[ActionItem], now: datetime | None = None) -> ActionCounts:
    moment = now or _now()

    def count(status: str) -> int:
        return sum(1 for i in items if i.status == status)

    overdue = sum(
        1
        for i in items
        if i.due_at is not None and i.status in ("todo", "doing", "blocked") and storage.ensure_aware(i.due_at) < moment
    )
    return ActionCounts(
        total=len(items),
        todo=count("todo"),
        doing=count("doing"),
        done=count("done"),
        blocked=count("blocked"),
        na=count("na"),
        overdue=overdue,
    )


def build_checklist(
    procurement_id: str, items: list[ActionItem], *, updated_at: datetime | None = None, context: "AnalysisContext | None" = None
) -> ActionChecklist:
    order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    status_order = {"blocked": 0, "todo": 1, "doing": 2, "done": 3, "na": 4}
    ordered = sorted(items, key=lambda i: (status_order[i.status], order[i.priority], i.due_at or datetime.max.replace(tzinfo=timezone.utc)))
    return ActionChecklist(
        procurement_id=procurement_id,
        items=ordered,
        counts=counts_of(items),
        updated_at=updated_at,
        organization_id=context.organization_id if context else None,
        evidence_scope=context.evidence_scope if context else None,
    )


def load_checklist(procurement_id: str, context: "AnalysisContext | None" = None) -> ActionChecklist:
    return build_checklist(procurement_id, _load_items(procurement_id, context), context=context)


def seed_from_report(report: CriticalConditionReport, *, context: "AnalysisContext | None" = None) -> ActionChecklist:
    """행동이 필요한 조건마다 항목을 만든다. 이미 있는 조건은 건너뛴다 (멱등).

    읽기부터 쓰기까지 잠근다 — 멱등성은 «이미 있는 조건»을 읽어서 판정하는데, 그 사이에
    다른 쪽이 같은 항목을 넣으면 둘 다 「없다」고 보고 두 번 넣는다 (ISSUE-032).
    """
    with storage.locked(checklist_path(report.procurement_id, context)):
        return _seed_from_report_locked(report, context)


def _seed_from_report_locked(report: CriticalConditionReport, context: "AnalysisContext | None") -> ActionChecklist:
    items = _load_items(report.procurement_id, context)
    existing = {item.source_condition_id for item in items if item.source_condition_id}
    # 이미 목록에 있는 제목. 같은 제목이 두 번 보이면 담당자는 「같은 걸 두 번 하라고?」로
    # 읽고 체크리스트 전체를 의심한다 (ISSUE-015). 제목이 겹치면 어느 항목에서 나온
    # 할 일인지 뒤에 붙여 구분한다 — 지우지 않는다. 요구사항이 둘이면 준비할 증빙도 둘이다.
    titles_seen = {item.title for item in items}
    now = _now()
    added = _seed_schedule(report.procurement_id, items, now)
    for condition in report.conditions:
        if condition.status not in _PRIORITY_BY_STATUS or condition.id in existing:
            continue
        note = f"근거: {condition.content}" + (f" (p.{condition.source_page})" if condition.source_page else "")
        steps = _STEPS_BY_TYPE.get(condition.condition_type)
        if steps:
            # 여러 줄로 쪼갠 조건. 첫 줄의 id 는 예전과 같은 식으로 만든다 — 이미 저장된
            # 체크리스트가 그 id 를 들고 있어서, 식을 바꾸면 같은 항목이 하나 더 생긴다.
            titles = list(steps)
            # 43차 E2E-14 — 같은 갈래 조건(실적 증빙 하나를 여러 면에서 본 8개)은 할 일 **한 벌**이다. 세 줄을 8번 되풀이하지 않고
            # 이미 있는 한 벌의 메모에 관련 요구사항 번호만 덧붙인다(멱등 — 번호가 이미 있으면 그대로).
            same = [item for item in items if item.title == steps[0] and item.origin == "auto"]
            if same:
                if condition.requirement_id:
                    for item in items:
                        if item.title in steps and item.origin == "auto" and condition.requirement_id not in (item.note or ""):
                            item.note = _with_related(item.note, condition.requirement_id)
                            item.updated_at = now
                            added += 1
                continue
        else:
            titles = [_TITLE_BY_TYPE.get(condition.condition_type, f"{condition.title} 확인")]
        for index, title in enumerate(titles):
            if title in titles_seen and condition.requirement_id:
                title = f"{title} — {condition.requirement_id}"
            titles_seen.add(title)
            seed = f"{report.procurement_id}:{condition.id}" if index == 0 else f"{report.procurement_id}:{condition.id}:{index}"
            items.append(
                ActionItem(
                    id=f"ACT-{fnv1a32(seed)}",
                    procurement_id=report.procurement_id,
                    title=title,
                    status="todo",
                    priority=_PRIORITY_BY_STATUS[condition.status],  # type: ignore[arg-type]
                    due_at=condition.due_at,
                    source_condition_id=condition.id,
                    requirement_id=condition.requirement_id,
                    note=note,
                    origin="auto",
                    # 조건 탐지를 «누른» 사람 (S12). 항목 자체는 규칙이 만들었지만,
                    # 그 규칙을 돌린 것은 사람이다.
                    recorded_by=requester.current_recorded_by(),
                    created_at=now,
                    updated_at=now,
                )
            )
            added += 1
    if added == 0:
        return build_checklist(report.procurement_id, items, context=context)
    return _save_items(report.procurement_id, items, context)


def _with_related(note: str | None, requirement_id: str) -> str:
    """메모 끝 「관련 요구사항: REQ-a · REQ-b」에 번호 하나를 더한다(같은 갈래 조건을 한 벌로 묶은 할 일 · 43차 E2E-14)."""
    text = note or ""
    marker = " · 관련 요구사항: "
    if marker in text:
        head, tail = text.split(marker, 1)
        return f"{head}{marker}{tail} · {requirement_id}"
    return f"{text}{marker}{requirement_id}"


def _seed_schedule(procurement_id: str, items: list[ActionItem], now: datetime) -> int:
    """공고문 일정표(43차 결정 1 · H6) — 참가신청 · 입찰등록 · 제출 마감 · (필수) 현장설명을 **기한이 붙은** 할 일로, 단계별 제출서류를
    그 단계의 기한으로 넣는다(가천대: 「10/30 10:00 참가신청 — ebiz4u」 · 「현장설명 준비서류: 인감증명서 …」). 이미 있으면 그대로(멱등)."""
    from app.services import notice_schedule, qualification_clause_service

    payload = qualification_clause_service.load(procurement_id) if procurement_id.startswith("g2b-") else None
    schedule = (payload or {}).get("schedule") if isinstance(payload, dict) else None
    if not schedule:
        return 0
    have = {item.id for item in items}
    stage_of_kind = {"application": "참가신청", "briefing": "현장설명", "registration": "입찰등록", "submission": "입찰등록"}
    due_of_stage: dict[str, datetime] = {}
    added = 0
    for entry in schedule.get("items") or []:
        kind = str(entry.get("kind") or "")
        if kind not in notice_schedule.KIND_LABEL:
            continue
        at = datetime.fromisoformat(str(entry["at"]))
        due_of_stage.setdefault(stage_of_kind.get(kind, kind), at)
        required = kind == "briefing" and schedule.get("briefing_required")
        # 44차 M3 — 날짜만 있던 줄은 23:59 를 적지 않는다: 「참가신청 마감 10/30(시각 원문 확인)」
        when = f"{at.astimezone(_KST):%m/%d %H:%M}" if entry.get("time_known") else f"{at.astimezone(_KST):%m/%d}(시각 원문 확인)"
        title = f"{notice_schedule.KIND_LABEL[kind]} {when}" + (" — 필수(불참 시 참가 불가)" if required else "")
        action_id = f"ACT-{fnv1a32(f'{procurement_id}:SCHED:{kind}:{at.isoformat()}')}"
        if action_id in have:
            continue
        items.append(ActionItem(
            id=action_id, procurement_id=procurement_id, title=title, status="todo",
            priority="urgent" if kind in ("application", "registration") or required else "high",  # type: ignore[arg-type]
            due_at=at, note=f"근거: 공고문 p.{entry.get('page') or '?'} 「{str(entry.get('text') or '')[:100]}」",
            origin="auto", recorded_by=requester.current_recorded_by(), created_at=now, updated_at=now,
        ))
        have.add(action_id)
        added += 1
    for doc in schedule.get("documents") or []:
        stage = str(doc.get("stage") or "")
        names = [str(n) for n in doc.get("items") or []]
        if not names:
            continue
        action_id = f"ACT-{fnv1a32(f'{procurement_id}:SCHED-DOCS:{stage}')}"
        if action_id in have:
            continue
        key = [n for n in names if any(k in n for k in notice_schedule.KEY_DOCS)]
        items.append(ActionItem(
            id=action_id, procurement_id=procurement_id, title=f"{stage} 제출서류 준비 — {' · '.join((key or names)[:4])}"[:120],
            status="todo", priority="high", due_at=due_of_stage.get(stage),  # type: ignore[arg-type]
            note=f"근거: 공고문 p.{doc.get('page') or '?'} 「{stage}」 서류 {len(names)}가지: " + " / ".join(names)[:400],
            origin="auto", recorded_by=requester.current_recorded_by(), created_at=now, updated_at=now,
        ))
        have.add(action_id)
        added += 1
    return added


def create_action(procurement_id: str, request: ActionCreateRequest, *, context: "AnalysisContext | None" = None) -> ActionItem:
    with storage.locked(checklist_path(procurement_id, context)):
        return _create_action_locked(procurement_id, request, context)


def _create_action_locked(procurement_id: str, request: ActionCreateRequest, context: "AnalysisContext | None") -> ActionItem:
    items = _load_items(procurement_id, context)
    now = _now()
    seq = len(items) + 1
    item = ActionItem(
        id=f"ACT-{fnv1a32(f'{procurement_id}:manual:{seq}:{now.isoformat()}')}",
        procurement_id=procurement_id,
        title=request.title,
        priority=request.priority,
        due_at=request.due_at,
        owner=request.owner,
        source_condition_id=request.source_condition_id,
        requirement_id=request.requirement_id,
        note=request.note,
        origin="manual",
        # 본문의 `owner` 는 담당자가 적는 이름이고, 이것은 서명된 신원이다 (S12).
        recorded_by=requester.current_recorded_by(),
        created_at=now,
        updated_at=now,
    )
    items.append(item)
    _save_items(procurement_id, items, context)
    return item


def update_action(procurement_id: str, action_id: str, request: ActionUpdateRequest, *, context: "AnalysisContext | None" = None) -> ActionItem:
    with storage.locked(checklist_path(procurement_id, context)):
        return _update_action_locked(procurement_id, action_id, request, context)


def _update_action_locked(procurement_id: str, action_id: str, request: ActionUpdateRequest, context: "AnalysisContext | None") -> ActionItem:
    items = _load_items(procurement_id, context)
    for index, item in enumerate(items):
        if item.id != action_id:
            continue
        data = item.model_dump()
        for key in ("title", "status", "priority", "owner", "evidence", "note"):
            value = getattr(request, key)
            if value is not None:
                data[key] = value
        if request.clear_due_at:
            data["due_at"] = None
        elif request.due_at is not None:
            data["due_at"] = request.due_at
        now = _now()
        data["updated_at"] = now
        if request.status == "done" and item.status != "done":
            data["completed_at"] = now
        elif request.status is not None and request.status != "done":
            data["completed_at"] = None
        # 마지막으로 «바꾼» 사람으로 갱신한다 (S12). 만든 사람이 아니라 지금 누른 사람이다.
        data["recorded_by"] = requester.current_recorded_by()
        updated = ActionItem.model_validate(data)
        items[index] = updated
        _save_items(procurement_id, items, context)
        return updated
    raise ActionNotFoundError(action_id)


def delete_action(procurement_id: str, action_id: str, *, context: "AnalysisContext | None" = None) -> None:
    with storage.locked(checklist_path(procurement_id, context)):
        _delete_action_locked(procurement_id, action_id, context)


def _delete_action_locked(procurement_id: str, action_id: str, context: "AnalysisContext | None") -> None:
    items = _load_items(procurement_id, context)
    remaining = [item for item in items if item.id != action_id]
    if len(remaining) == len(items):
        raise ActionNotFoundError(action_id)
    # «context 를 안 넘겨서» 삭제만 공개 폴더에 기록되던 자리다 (생성·수정 경로는 넘기고 있었다).
    # 컨텍스트가 없으면 analysis_store.resolve_path 가 data/public/actions/ 를 타므로,
    # 사내(internal) 분석에서 항목을 지우면 조직 폴더 파일은 그대로 남고 지운 결과만 공개 폴더에 새로 생겼다
    # → 담당자가 「해당 없음」으로 지운 항목이 새로고침하면 되살아난다.
    _save_items(procurement_id, remaining, context)
