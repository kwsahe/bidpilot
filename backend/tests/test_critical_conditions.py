"""Critical Condition 탐지·게이트·사람의 해결 처리 테스트.

네트워크·LLM 없음. 실제 입찰공고문·제안요청서에서 관찰한 문장을 손으로 옮긴 픽스처만 쓴다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.critical_condition import ConditionUpdateRequest
from app.schemas.eligibility import EligibilityCounts, EligibilityReport, EligibilityResult
from app.schemas.requirement import PageInfo, Requirement, RfpParseResult
from app.services import action_service, critical_condition_service as ccs, decision_service
from app.schemas.action import ActionCreateRequest, ActionUpdateRequest
from app.schemas.decision import DecisionRequest

PID = "g2b-TEST0001-000"


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ccs, "CONDITION_DIR", tmp_path / "conditions")
    monkeypatch.setattr(action_service, "ACTION_DIR", tmp_path / "actions")
    monkeypatch.setattr(decision_service, "DECISION_DIR", tmp_path / "decisions")


def req(seq: int, category: str, content: str, page: int = 3) -> Requirement:
    rid = f"REQ-{seq:03d}"
    return Requirement(
        id=f"{PID}:{rid}",
        procurement_id=PID,
        requirement_id=rid,
        category=category,
        requirement_type="mandatory",
        title=content[:20],
        content=content,
        page=page,
        source_text=f"○ {content}",
    )


def _license_rule():
    return next(r for r in ccs.RULES if r.condition_type == "industry_license")


def _license_condition(source_text: str):
    """업종·면허 규칙 하나만 떼어 판정한다 (탐지 파이프라인 전체를 돌리지 않는다)."""
    clause = "소프트웨어사업자 신고확인서를 제출하여야 한다."
    requirement = Requirement(
        id=f"{PID}:REQ-001",
        procurement_id=PID,
        requirement_id="REQ-001",
        category="자격",
        requirement_type="mandatory",
        title=clause[:20],
        content=clause,
        page=3,
        source_text=source_text,
    )
    return ccs._from_requirement(requirement, _license_rule())


def test_far_away_uncertain_word_does_not_weaken_a_blocker() -> None:
    """수천 자 떨어진 「필요시」가 업종·면허 BLOCKER 를 끌어내리지 않는다.

    파싱된 요구사항 한 건의 source_text 는 1만 자를 넘기도 한다(요구사항 정의서 표가
    통째로 들어온다). 전문에서 확신도 표현을 찾으면 상관없는 조항 한 마디가
    참가 자체를 막는 조건을 CHECK 로 바꿔 놓는다.
    """
    clause = "소프트웨어사업자 신고확인서를 제출하여야 한다."
    far = clause + " 기타 안내 문구." * 400 + " 제출서류는 필요시 추가로 요청할 수 있다."
    assert len(far) > 2000
    assert _license_condition(far).status == "BLOCKER"


def test_nearby_uncertain_word_still_weakens_a_blocker() -> None:
    """같은 문장 옆의 「필요시」는 여전히 확신을 낮춘다 — 창을 좁히되 규칙을 없애지는 않는다."""
    clause = "소프트웨어사업자 신고확인서를 제출하여야 한다."
    assert _license_condition(clause + " 이 서류는 필요시 제출한다.").status == "CHECK"
    assert _license_condition(clause).status == "BLOCKER"


def parse_result(*requirements: Requirement) -> RfpParseResult:
    return RfpParseResult(
        procurement_id=PID,
        source="g2b_attachment",
        document="제안요청서.hwp",
        doc_format="hwp",
        page_is_approximate=True,
        page_count=5,
        pages=[PageInfo(page=i, char_count=100) for i in range(1, 6)],
        empty_pages=[],
        count=len(requirements),
        candidate_count=len(requirements),
        requirements=list(requirements),
        generated_at=datetime.now(timezone.utc),
    )


# --------------------------------------------------------------------------
# 탐지
# --------------------------------------------------------------------------


def test_large_firm_exclusion_is_not_license_requirement() -> None:
    """11-01 사법연수원 공고 — 「대기업 및 중견기업 소프트웨어 사업자는 본 입찰에 참여할 수 없으며」가 업종·면허 BLOCKER 였다.
    대기업 참여 제한이지 업종 요건이 아니다(대기업 제한 조항은 참가자격 판정이 따로 본다). 같은 글에 등록 요건이 있으면 그대로 BLOCKER."""
    exclusion = (
        "2-2. 본 사업은 사업금액이 20억원 미만인 사업으로서,「중소 소프트웨어사업자의 사업 참여 지원에 관한 지침」에 의거 "
        "대기업 및 중견기업 소프트웨어 사업자는 본 입찰에 참여할 수 없으며, 「소프트웨어진흥법」제48조 제4항을 따른다."
    )
    found = ccs.detect_from_requirements([req(1, "입찰참가자격", exclusion)])
    assert not [c for c in found if c.condition_type == "industry_license"]

    both = "소프트웨어사업자(컴퓨터관련서비스사업, 업종코드 1468)로 등록한 자. 대기업 및 중견기업 소프트웨어 사업자는 참여할 수 없다."
    found = ccs.detect_from_requirements([req(2, "입찰참가자격", both)])
    license_rows = [c for c in found if c.condition_type == "industry_license"]
    assert license_rows and license_rows[0].status == "BLOCKER"

    # 독립 검토 — 가려야 하는 꼴(괄호가 「」 안 · 괄호 속 마침표)과 남겨야 하는 꼴(중소 소프트웨어사업자만 · 법률 이름 속 업종)
    hidden = [
        "「중소 소프트웨어사업자의 사업 참여 지원에 관한 지침(과학기술정보통신부 고시)」에 따라 대기업 및 중견기업 소프트웨어 사업자는 참여할 수 없다.",
        "대기업(매출 1.5조 이상) 및 중견기업 소프트웨어 사업자의 입찰 참여를 제한함",
    ]
    for index, text in enumerate(hidden, start=10):
        found = ccs.detect_from_requirements([req(index, "입찰참가자격", text)])
        assert not [c for c in found if c.condition_type == "industry_license"], text
    kept = [
        "대기업·중견기업을 제외한 중소 소프트웨어사업자만 참여 가능하며, 그 외 업체는 참여할 수 없음",
        "「정보통신공사업법」 제14조에 의한 정보통신공사업 등록을 필한 업체",
        "「소프트웨어 진흥법」에 따른 소프트웨어사업자로 신고한 자",
    ]
    for index, text in enumerate(kept, start=20):
        found = ccs.detect_from_requirements([req(index, "입찰참가자격", text)])
        assert [c for c in found if c.condition_type == "industry_license"], text


@pytest.mark.parametrize(
    ("content", "expected_type", "expected_status"),
    [
        ("제안요청 설명회에 반드시 참석하여야 하며 미참석 업체는 입찰에 참여할 수 없다.", "briefing_attendance", "BLOCKER"),
        ("설명회 참석을 희망하는 업체는 사전 등록하여야 한다.", "pre_registration", "ACTION"),
        ("광주광역시에 본점 소재지를 둔 업체만 참가할 수 있다.", "region_restriction", "BLOCKER"),
        ("소프트웨어사업자 신고를 마친 자", "industry_license", "BLOCKER"),
        ("직접생산확인증명서를 보유한 업체", "direct_production", "BLOCKER"),
        ("중소기업확인서를 제출하여야 한다.", "sme_certificate", "ACTION"),
        ("최근 3년 이내 유사 용역 수행실적이 1건 이상 있어야 한다.", "performance_record", "CHECK"),
        ("사업책임자는 관련 분야 경력 5년 이상의 자격을 갖추어야 한다.", "staffing", "CHECK"),
        ("공동수급체 구성은 허용하지 않는다.", "joint_venture", "INFO"),
        ("과업의 일부를 하도급할 수 없다.", "subcontract", "INFO"),
        ("입찰보증금은 입찰금액의 5% 이상을 납부하여야 한다.", "bid_bond", "ACTION"),
        ("제안서는 산학협력단 302호에 방문 제출한다.", "onsite_submission", "ACTION"),
        ("제안서 원본 1부, 사본 5부를 제출한다.", "copies", "ACTION"),
        ("제안서 파일은 PDF 파일로 USB에 담아 제출한다.", "file_format", "ACTION"),
        ("기술제안서와 가격제안서는 분리하여 별도 봉투에 밀봉한다.", "separate_price_tech", "INFO"),
        ("제안 발표는 업체당 20분으로 한다.", "presentation", "ACTION"),
        ("수행 인력은 착수 전 보안서약서를 제출한다.", "security_pledge", "ACTION"),
        ("입찰 참여 전 별도 절차로 사전 적격심사를 신청하여야 한다.", "separate_procedure", "ACTION"),
        ("설명회 참석확인서를 제안서에 첨부한다.", "attendance_certificate", "ACTION"),
        ("모든 서류는 별첨 서식에 따라 작성하여 제출한다.", "mandatory_form", "ACTION"),
    ],
)
def test_detects_each_condition_type(content: str, expected_type: str, expected_status: str) -> None:
    found = ccs.detect_from_requirements([req(1, "기타", content)])
    types = {c.condition_type: c for c in found}
    assert expected_type in types, [c.condition_type for c in found]
    condition = types[expected_type]
    assert condition.status == expected_status
    assert condition.detected_status == expected_status
    assert condition.requirement_id == "REQ-001"
    assert condition.source_text.startswith("○ ")
    assert condition.source_page == 3


def test_uncertain_wording_becomes_check_not_blocker() -> None:
    found = ccs.detect_from_requirements([req(1, "일정", "설명회 참석은 권장하며 불참 시 불이익은 없다.")])
    briefing = [c for c in found if c.condition_type == "briefing_attendance"]
    assert briefing and briefing[0].status == "CHECK"


def test_no_condition_for_plain_task() -> None:
    assert ccs.detect_from_requirements([req(1, "과업내용", "주말을 이용한 40시간 내외의 교육 과정 기획")]) == []


def test_condition_id_is_stable_across_redetection() -> None:
    a = ccs.detect_from_requirements([req(1, "기타", "제안요청 설명회에 반드시 참석하여야 한다.")])
    b = ccs.detect_from_requirements([req(1, "기타", "제안요청 설명회에 반드시 참석하여야 한다.")])
    assert a[0].id == b[0].id
    assert a[0].id.startswith("CC-")


def test_eligibility_fail_becomes_blocker() -> None:
    report = EligibilityReport(
        procurement_id=PID,
        verdict="FAIL",
        counts=EligibilityCounts(total=1, passed=0, check=0, failed=1),
        evaluated_at=datetime.now(timezone.utc),
        notice_available=True,
        requirements_available=False,
        llm_used=False,
        results=[
            EligibilityResult(
                rule_id="ELIG-BID-DEADLINE",
                label="입찰 마감",
                status="FAIL",
                method="RULE",
                source="bidClseDt=2026-08-01 10:00",
                reason="입찰 마감이 지났다.",
            )
        ],
    )
    found = ccs.detect_from_eligibility(PID, report)
    assert len(found) == 1
    assert found[0].condition_type == "deadline_passed"
    assert found[0].status == "BLOCKER"
    assert found[0].source_field == "bidClseDt=2026-08-01 10:00"


# --------------------------------------------------------------------------
# 게이트 · 사람의 해결 처리
# --------------------------------------------------------------------------


def _report():
    return ccs.build_report(
        PID,
        parse_result=parse_result(
            req(1, "기타", "제안요청 설명회에 반드시 참석하여야 하며 미참석 업체는 입찰에 참여할 수 없다."),
            req(2, "제출서류", "제안서 원본 1부, 사본 5부를 제출한다."),
            req(3, "과업내용", "교육과정 기획"),
        ),
        eligibility=None,
        notice_available=False,
    )


def test_gate_blocks_when_blocker_unresolved() -> None:
    report = _report()
    assert report.counts.blocker == 1
    assert report.gate.can_go is False
    # 사유는 «왜 막혔는지»를 담당자 말로 말해야 한다. 예전에는 영문 상태값(BLOCKER)이 그대로 실려
    # 화면에 「미해결 BLOCKER 1건 … CLEARED … GO」처럼 떴다. 글자 하나를 찾는 대신 뜻을 검사한다.
    assert "참가를 막는 조건 1건" in report.gate.reason
    assert "설명회 필참" in report.gate.reason, "무엇 때문에 막혔는지 이름이 있어야 한다"
    assert "저장할 수 없습니다" in report.gate.reason
    assert report.gate.blocker_ids


def test_system_never_clears_and_human_clear_persists() -> None:
    report = ccs.save_report(_report())
    assert all(c.status != "CLEARED" for c in report.conditions)
    blocker = next(c for c in report.conditions if c.status == "BLOCKER")

    updated = ccs.update_condition(
        PID, blocker.id, ConditionUpdateRequest(status="CLEARED", reviewer="김담당", note="9/12 설명회 참석 완료")
    )
    cleared = next(c for c in updated.conditions if c.id == blocker.id)
    assert cleared.status == "CLEARED"
    assert cleared.detected_status == "BLOCKER"  # 규칙 판정은 그대로 남는다
    assert cleared.resolved_by == "김담당"
    assert cleared.extraction_method == "HUMAN"
    assert updated.gate.can_go is True

    # 재탐지해도 사람의 기록이 덧입혀진다.
    again = ccs.build_report(PID, parse_result=_report_parse(), eligibility=None, notice_available=False)
    assert next(c for c in again.conditions if c.id == blocker.id).status == "CLEARED"


def _report_parse():
    return parse_result(
        req(1, "기타", "제안요청 설명회에 반드시 참석하여야 하며 미참석 업체는 입찰에 참여할 수 없다."),
        req(2, "제출서류", "제안서 원본 1부, 사본 5부를 제출한다."),
    )


def test_update_unknown_condition_raises() -> None:
    ccs.save_report(_report())
    with pytest.raises(ccs.ConditionNotFoundError):
        ccs.update_condition(PID, "CC-deadbeef", ConditionUpdateRequest(status="CLEARED", reviewer="x"))


def test_load_before_detect_raises() -> None:
    with pytest.raises(ccs.ConditionReportNotFoundError):
        ccs.load_report(PID)


def test_unread_requirements_stay_unknown_after_reload() -> None:
    """P1-02 — 처음 열 때만 「아직 모름」이고 두 번째(load_report)부터 「차단 조건 없음」으로 돌아갔다."""
    ccs.save_report(ccs.build_report(PID, parse_result=None, eligibility=None, notice_available=True))
    reloaded = ccs.load_report(PID)
    assert reloaded.gate.can_go is True
    assert reloaded.gate.reason.startswith("아직 모름")
    # 요구사항을 읽은 보고서는 다시 읽어도 「확인된 참가 차단 조건이 없습니다」
    ccs.save_report(ccs.build_report(PID, parse_result=parse_result(req(1, "과업내용", "교육과정 기획")), eligibility=None, notice_available=True))
    assert ccs.load_report(PID).gate.reason == "확인된 참가 차단 조건이 없습니다."


# --------------------------------------------------------------------------
# Action Checklist
# --------------------------------------------------------------------------


def test_seed_is_idempotent_and_human_marks_done() -> None:
    report = ccs.save_report(_report())
    first = action_service.seed_from_report(report)
    second = action_service.seed_from_report(report)
    # 멱등: 두 번 씨 뿌려도 같은 조건에 항목이 또 생기지 않는다. 이것이 이 테스트의 요지다.
    assert first.counts.total == second.counts.total
    # 행동이 필요한 조건(BLOCKER 설명회 · ACTION 제출부수)에만 항목이 붙는다 — 과업은 제외.
    actionable = {c.id for c in report.conditions if c.status in {"BLOCKER", "ACTION", "CHECK"}}
    assert {i.source_condition_id for i in first.items if i.source_condition_id} == actionable
    assert len(actionable) == 2
    # 설명회는 «참석»만 체크하면 사전 신청기한을 놓친다. 그래서 한 줄이 아니라 실제 순서대로 쪼갠다.
    briefing = next(c for c in report.conditions if c.condition_type == "briefing_attendance")
    steps = [i.title for i in first.items if i.source_condition_id == briefing.id]
    assert len(steps) > 1, "설명회 조건이 한 줄로 뭉뚱그려졌다"
    assert any("사전 신청기한" in t for t in steps)
    urgent = [i for i in first.items if i.priority == "urgent"]
    assert urgent and urgent[0].origin == "auto" and urgent[0].status == "todo"

    done = action_service.update_action(PID, urgent[0].id, ActionUpdateRequest(status="done", evidence="참석확인서 수령"))
    assert done.status == "done" and done.completed_at is not None
    assert action_service.load_checklist(PID).counts.done == 1


def test_manual_action_create_and_delete() -> None:
    item = action_service.create_action(PID, ActionCreateRequest(title="인감증명서 발급", priority="high"))
    assert action_service.load_checklist(PID).counts.total == 1
    action_service.delete_action(PID, item.id)
    assert action_service.load_checklist(PID).counts.total == 0
    with pytest.raises(action_service.ActionNotFoundError):
        action_service.delete_action(PID, item.id)


# --------------------------------------------------------------------------
# GO / HOLD / NO_GO
# --------------------------------------------------------------------------


def test_go_is_blocked_by_unresolved_blocker() -> None:
    ccs.save_report(_report())
    with pytest.raises(decision_service.DecisionBlockedError):
        decision_service.save_decision(PID, DecisionRequest(status="GO", reasons=["적합"], decided_by="김담당"))
    hold = decision_service.save_decision(PID, DecisionRequest(status="HOLD", reasons=["설명회 등록 후 재검토"], decided_by="김담당"))
    assert hold.status == "HOLD" and hold.gate is not None and hold.gate.can_go is False
    assert decision_service.load_decision(PID).status == "HOLD"


def test_go_allowed_after_human_clears_blocker() -> None:
    report = ccs.save_report(_report())
    blocker = next(c for c in report.conditions if c.status == "BLOCKER")
    # 28차 DTL-11 — 참가 차단 조건은 무엇을 확인했는지 메모가 있어야 풀린다(안전장치)
    ccs.update_condition(PID, blocker.id, ConditionUpdateRequest(status="CLEARED", reviewer="김담당", note="발주처에 확인 — 요건 충족"))
    go = decision_service.save_decision(PID, DecisionRequest(status="GO", reasons=["사업영역 적합"], decided_by="김담당"))
    assert go.status == "GO" and go.gate is not None and go.gate.can_go is True


def test_decision_requires_reason() -> None:
    """사유 없이 NO_GO 는 저장되지 않는다.

    공백만 있는 사유는 이제 **요청 스키마**가 먼저 거부한다(ISSUE-013). 서비스까지
    도달하지 않으므로 여기서는 두 관문을 각각 확인한다:
    빈 문자열은 422, 사유 목록 자체가 비면 서비스가 막는다.
    """
    with pytest.raises(ValidationError):
        DecisionRequest(status="NO_GO", reasons=["  "], decided_by="김담당")
    with pytest.raises(decision_service.DecisionReasonRequiredError):
        decision_service.save_decision(PID, DecisionRequest(status="NO_GO", reasons=[], decided_by="김담당"))


def test_unreviewed_default_when_nothing_saved() -> None:
    decision = decision_service.load_decision("g2b-NEVER-000")
    assert decision.status == "UNREVIEWED" and decision.decided_at is None


# --------------------------------------------------------------------------
# 조건 id 의 신원 · 저장본의 신선도
#
# 왜 필요한가: condition_id 를 REQ 번호로 만들면 요구사항을 다시 뽑을 때 번호가 밀려
# 사람이 CLEARED 로 표시한 기록이 엉뚱한 조건에 붙거나 사라진다. 그리고 저장된 보고서가
# 지금 요구사항 집합보다 낡았는지 알 길이 없어 옛 판정이 최신처럼 보인다.
# --------------------------------------------------------------------------


BRIEFING = "제안요청 설명회에 반드시 참석하여야 하며 미참석 업체는 입찰에 참여할 수 없다."


def req_stable(seq: int, content: str, stable_id: str | None) -> Requirement:
    """stable_id 를 가진 요구사항. seq(REQ 번호)만 밀어 재추출 상황을 만든다."""
    requirement = req(seq, "기타", content)
    requirement.stable_id = stable_id
    return requirement


def parse_result_with_hash(*requirements: Requirement, set_hash: str | None) -> RfpParseResult:
    result = parse_result(*requirements)
    result.requirement_set_hash = set_hash
    return result


def write_generated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, set_hash: str | None, procurement_id: str = PID
) -> None:
    """요구사항 파일을 흉내 낸다 — 신선도 대조 상대. 실제 파싱은 하지 않는다."""
    import json

    from app.services import rfp_parser

    generated = tmp_path / "generated"
    generated.mkdir(exist_ok=True)
    monkeypatch.setattr(rfp_parser, "GENERATED_DIR", generated)
    payload: dict[str, object] = {"procurement_id": procurement_id, "requirements": []}
    if set_hash is not None:
        payload["requirement_set_hash"] = set_hash
    (generated / f"{procurement_id}.requirements.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_condition_id_follows_stable_id_not_req_number() -> None:
    """REQ 번호가 밀려도 같은 요구사항이면 조건 id 가 같다."""
    before = ccs.detect_from_requirements([req_stable(1, BRIEFING, "SR-aaaa1111aaaa1111")])
    after = ccs.detect_from_requirements([req_stable(7, BRIEFING, "SR-aaaa1111aaaa1111")])
    assert before[0].id == after[0].id
    assert before[0].id_basis == "stable_id"
    # 옛 방식(REQ 번호)으로 만든 id 는 서로 달랐다 — 그래서 기록이 끊겼다.
    assert before[0].legacy_ids != after[0].legacy_ids
    assert before[0].legacy_ids and before[0].legacy_ids[0] != before[0].id


def test_condition_id_falls_back_to_req_number_for_old_data() -> None:
    """stable_id 가 없는 옛 요구사항은 지금처럼 REQ 번호로 떨어지고, 그 사실을 기록한다."""
    found = ccs.detect_from_requirements([req(1, "기타", BRIEFING)])
    assert found[0].id_basis == "requirement_id"
    assert found[0].legacy_ids == []  # 옛 방식과 결과가 같으므로 이행할 것이 없다


def test_human_cleared_survives_requirement_renumbering() -> None:
    """요구사항을 다시 뽑아 REQ 번호가 밀려도 사람이 남긴 CLEARED 는 유지된다."""
    first = ccs.save_report(
        ccs.build_report(
            PID,
            parse_result=parse_result_with_hash(req_stable(1, BRIEFING, "SR-bbbb2222bbbb2222"), set_hash="h1"),
            eligibility=None,
            notice_available=False,
        )
    )
    blocker = next(c for c in first.conditions if c.status == "BLOCKER")
    ccs.update_condition(PID, blocker.id, ConditionUpdateRequest(status="CLEARED", reviewer="김담당", note="참석 완료"))

    # 문서 앞쪽에 항목이 셋 끼어 REQ-001 → REQ-004 로 밀린 재추출.
    again = ccs.build_report(
        PID,
        parse_result=parse_result_with_hash(req_stable(4, BRIEFING, "SR-bbbb2222bbbb2222"), set_hash="h2"),
        eligibility=None,
        notice_available=False,
    )
    carried = next(c for c in again.conditions if c.condition_type == "briefing_attendance")
    assert carried.requirement_id == "REQ-004"
    assert carried.status == "CLEARED"
    assert carried.detected_status == "BLOCKER"
    assert carried.resolved_by == "김담당"
    assert again.gate.can_go is True


def test_override_left_under_old_req_number_id_is_not_lost() -> None:
    """stable_id 도입 이전에 남긴 기록(옛 id)을 새 id 로도 찾아낸다."""
    old = ccs.save_report(
        ccs.build_report(
            PID,
            parse_result=parse_result(req(1, "기타", BRIEFING)),  # stable_id 없음 = 옛 저장본
            eligibility=None,
            notice_available=False,
        )
    )
    old_blocker = next(c for c in old.conditions if c.status == "BLOCKER")
    ccs.update_condition(PID, old_blocker.id, ConditionUpdateRequest(status="CLEARED", reviewer="박담당", note="원문 확인"))  # 메모 필수(28차 DTL-11)

    # 같은 요구사항에 stable_id 가 채워진 뒤 다시 탐지 — id 가 바뀐다.
    migrated = ccs.save_report(
        ccs.build_report(
            PID,
            parse_result=parse_result(req_stable(1, BRIEFING, "SR-cccc3333cccc3333")),
            eligibility=None,
            notice_available=False,
        )
    )
    new_blocker = next(c for c in migrated.conditions if c.condition_type == "briefing_attendance")
    assert new_blocker.id != old_blocker.id
    assert old_blocker.id in new_blocker.legacy_ids
    assert new_blocker.status == "CLEARED"
    assert new_blocker.resolved_by == "박담당"
    # 옛 id 로 들어온 상태 변경도 지금 조건에 붙는다 (화면이 옛 id 를 들고 있을 수 있다).
    reverted = ccs.update_condition(PID, old_blocker.id, ConditionUpdateRequest(status="BLOCKER", reviewer="박담당"))
    assert next(c for c in reverted.conditions if c.id == new_blocker.id).status == "BLOCKER"


def test_report_is_stale_when_requirement_set_changed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """저장본 해시와 지금 요구사항 파일의 해시가 다르면 stale=True."""
    write_generated(monkeypatch, tmp_path, set_hash="6f2f76e5189d71b8")
    ccs.save_report(
        ccs.build_report(
            PID,
            parse_result=parse_result_with_hash(req(1, "기타", BRIEFING), set_hash="0000000000000000"),
            eligibility=None,
            notice_available=False,
        )
    )
    loaded = ccs.load_report(PID)
    assert loaded.freshness == "stale"
    assert loaded.stale is True
    assert loaded.stale_reason and "6f2f76e5189d71b8" in loaded.stale_reason
    assert loaded.requirement_set_hash == "0000000000000000"
    assert loaded.current_requirement_set_hash == "6f2f76e5189d71b8"
    # 낡았다고 조건을 감추지 않는다 — 감추면 BLOCKER 가 화면에서 사라진다.
    assert loaded.counts.blocker == 1
    assert loaded.gate.can_go is False


def test_report_is_current_when_hashes_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_generated(monkeypatch, tmp_path, set_hash="6f2f76e5189d71b8")
    ccs.save_report(
        ccs.build_report(
            PID,
            parse_result=parse_result_with_hash(req(1, "기타", BRIEFING), set_hash="6f2f76e5189d71b8"),
            eligibility=None,
            notice_available=False,
        )
    )
    loaded = ccs.load_report(PID)
    assert loaded.freshness == "current"
    assert loaded.stale is False
    assert loaded.stale_reason is None


def test_old_report_without_hash_is_never_assumed_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """해시 필드가 없는 옛 저장본은 «알 수 없음»이다. 최신이라고 단정하지 않는다."""
    write_generated(monkeypatch, tmp_path, set_hash="6f2f76e5189d71b8")
    ccs.save_report(
        ccs.build_report(
            PID,
            parse_result=parse_result(req(1, "기타", BRIEFING)),  # 집합 해시 없음
            eligibility=None,
            notice_available=False,
        )
    )
    # 저장 파일에서 신선도 필드를 통째로 지워 «필드 자체가 없던 시절»의 저장본을 만든다.
    store = ccs.storage.read_json(ccs.report_path(PID))
    for key in ("requirement_set_hash", "requirement_set_id", "freshness", "stale", "stale_reason"):
        store["report"].pop(key, None)
    ccs.storage.write_json_atomic(ccs.report_path(PID), store)

    loaded = ccs.load_report(PID)
    assert loaded.freshness == "unknown"
    assert loaded.stale is True
    assert loaded.stale_reason and "확인할 수 없습니다" in loaded.stale_reason


def test_freshness_unknown_when_requirement_file_is_gone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """대조할 요구사항 파일이 없으면 unknown — 저장본만 보고 최신이라 하지 않는다."""
    from app.services import rfp_parser

    monkeypatch.setattr(rfp_parser, "GENERATED_DIR", tmp_path / "empty")
    ccs.save_report(
        ccs.build_report(
            PID,
            parse_result=parse_result_with_hash(req(1, "기타", BRIEFING), set_hash="h9"),
            eligibility=None,
            notice_available=False,
        )
    )
    loaded = ccs.load_report(PID)
    assert loaded.freshness == "unknown"
    assert loaded.stale is True
    assert loaded.current_requirement_set_hash is None
