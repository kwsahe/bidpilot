"""문서 항목 유형 분류기 테스트 (app/services/item_classifier.py).

실제 제안요청서(가천대 생성형 AI 교육 등)에서 관찰한 문장 형태를 손으로 옮긴 픽스처만 쓴다.
네트워크·LLM 없음. 유형마다 최소 1건씩 잡는지, 저장 id는 바뀌지 않는지, 날짜는
명시된 경우에만 채우는지를 확인한다.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.services import item_classifier as ic

# --------------------------------------------------------------------------
# 유형별 분류
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("category", "content", "expected"),
    [
        ("과업내용", "주말(토요일, 일요일)을 이용한 40시간 내외의 교육 과정 기획", "TASK"),
        ("과업내용", "교육 종료 후 만족도 조사를 실시하여야 한다.", "TASK"),
        ("기타", "교육생 1인당 실습 계정을 제공하여야 한다.", "REQUIREMENT"),
        ("인력", "총괄책임자는 관련 분야 경력 5년 이상이어야 한다.", "REQUIREMENT"),
        ("입찰참가자격", "입찰참가자격: 소프트웨어사업자 신고를 마친 자", "ELIGIBILITY"),
        ("기타", "본 입찰은 광주광역시에 본점 소재지를 둔 중소기업만 참가할 수 있다.", "ELIGIBILITY"),
        ("제출서류", "제안서는 원본 1부, 사본 5부와 USB 1개를 제출하여야 한다.", "SUBMISSION"),
        ("기타", "제출서류: 입찰참가신청서, 사업자등록증 사본, 제안서(PDF 파일 포함)", "SUBMISSION"),
        ("일정", "제안서 제출 마감: 2026. 9. 26.(금) 15:00까지", "SCHEDULE"),
        ("과업내용", "제안요청 설명회에 반드시 참석하여야 하며 미참석 시 입찰에 참여할 수 없다.", "SCHEDULE"),
        ("평가", "기술평가 80점, 가격평가 20점으로 합산하여 협상적격자를 선정한다.", "EVALUATION"),
        ("기타", "제안서 평가 시 지역업체 참여에 가점을 부여한다.", "EVALUATION"),
        ("기타", "계약 체결 시 입찰금액의 5%에 해당하는 계약보증금을 납부하여야 한다.", "SPECIAL_CONDITION"),
        ("보안", "수행 인력은 착수 전 보안서약서를 제출하여야 한다.", "SPECIAL_CONDITION"),
        ("제출서류", "공동수급체 구성은 허용하지 않는다.", "SPECIAL_CONDITION"),
        ("사업개요", "본 사업은 재학생의 생성형 AI 활용 역량을 높이기 위한 것이다.", "REFERENCE"),
        ("기타", "가천대학교 부트캠프 사업 소개 자료는 별첨을 참고한다.", "REFERENCE"),
    ],
)
def test_classify_item_type(category: str, content: str, expected: str) -> None:
    assert ic.classify_item_type(category, content) == expected


def test_category_precedence_keeps_extractor_type_for_specific_sections() -> None:
    # 평가 절의 "가점" 문장은 특이사항 패턴이 없으므로 평가로 남는다.
    assert ic.classify_item_type("평가", "지역업체 참여 시 가점 2점", "") == "EVALUATION"
    # 자격 절은 본문이 무엇이든 자격이다 (특이사항 표현이 없는 한).
    assert ic.classify_item_type("입찰참가자격", "국가종합전자조달시스템 이용자 등록을 마친 자", "") == "ELIGIBILITY"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        # 끝이 「제출 · 첨부」인 증빙 · 재무 서류 줄은 제출 항목이다 (외부 점검 P1-05-2 · 3).
        ("최근 2년 표준재무제표 첨부", "SUBMISSION"),
        ("수행실적 증빙서류(원본 1부 必, 나머지 사본으로 제출)", "SUBMISSION"),
        ("사본 : 용역계약서 및 세금계산서(계약금액과 동일해야 함) 함께 제출", "SUBMISSION"),
        # 평가 규칙 문장은 평가기준 그대로다.
        ("국세청 발행 표준재무제표 자료 기준", "EVALUATION"),
        ("기재된 내용을 토대로 평가하되, 증빙서류가 제출된 경우에 한해 해당실적을 인정한다", "EVALUATION"),
    ],
)
def test_evaluation_document_submission_lines(content: str, expected: str) -> None:
    assert ic.classify_item_type("평가", content) == expected


def test_evaluation_evidence_submission_is_high_not_blocker() -> None:
    fields = ic.classify_fields(
        category="평가",
        requirement_type="mandatory",
        content="수행실적 증빙서류(원본 1부 必, 나머지 사본으로 제출)",
    )
    assert fields["item_type"] == "SUBMISSION"
    assert fields["response_scope"] == "SUBMISSION_CHECKLIST"
    # 「원본 1부」가 제출 차단 규칙에 걸리지만, 평가 증빙은 참가를 막지 않는다.
    assert fields["criticality"] == "high"
    # 제출 절에서 온 같은 꼴은 차단 그대로다.
    assert ic.classify_fields(category="제출서류", requirement_type="mandatory", content="제안서 원본 1부 제출")[
        "criticality"
    ] == "blocker"


def test_human_confirmation_keeps_evaluation_evidence_high(monkeypatch: pytest.MonkeyPatch) -> None:
    """사람이 확인만 해도 중대성을 다시 센다(correction_service) — 그때 「참가 차단」으로 되돌아가지 않는다."""
    from types import SimpleNamespace

    from app.services import correction_service as cs

    monkeypatch.setattr(cs, "latest_by_requirement", lambda _pid: {"EVL-001": SimpleNamespace(changes={}, review_status="confirmed")})
    payload = {
        "requirements": [
            {
                "requirement_id": "EVL-001",
                "category": "평가",
                "requirement_type": "mandatory",
                "item_type": "SUBMISSION",
                "content": "수행실적 증빙서류(원본 1부 必, 나머지 사본으로 제출)",
                "source_text": "",
            }
        ]
    }
    assert cs.apply_to_payload("g2b-TEST-000", payload) == 1
    assert payload["requirements"][0]["criticality"] == "high"
    # 사람이 유형을 「자격」으로 바꾼 평가 줄은 차단 그대로(평가에서 온 «제출» 줄만 낮춘다)
    assert ic.criticality_of("ELIGIBILITY", "mandatory", "광주광역시 소재 업체로 제한", category="평가") == "blocker"


# --------------------------------------------------------------------------
# 중대성 · 행동 필요
# --------------------------------------------------------------------------


def test_blocker_for_region_restriction() -> None:
    text = "광주광역시에 본점 소재지를 둔 업체만 참가할 수 있다."
    assert ic.criticality_of("ELIGIBILITY", "mandatory", text) == "blocker"
    assert ic.action_required_of("ELIGIBILITY", "mandatory") is True


def test_blocker_for_mandatory_briefing() -> None:
    text = "제안요청 설명회에 반드시 참석하여야 하며 미참석 시 입찰 참여가 제한된다."
    assert ic.criticality_of("SCHEDULE", "mandatory", text) == "blocker"


def test_high_for_plain_submission() -> None:
    assert ic.criticality_of("SUBMISSION", "mandatory", "제안서를 제출한다.") == "high"


def test_normal_for_task_and_low_for_optional_or_reference() -> None:
    assert ic.criticality_of("TASK", "mandatory", "교육과정 기획") == "normal"
    assert ic.criticality_of("TASK", "optional", "가능하면 교재를 제공") == "low"
    assert ic.criticality_of("REFERENCE", "mandatory", "사업 배경") == "low"
    assert ic.action_required_of("TASK", "mandatory") is False


# --------------------------------------------------------------------------
# 날짜는 명시된 경우에만
# --------------------------------------------------------------------------


def test_due_at_from_explicit_deadline() -> None:
    due = ic.due_at_of("SCHEDULE", "제안서 제출 마감: 2026. 9. 26.(금) 15:00까지")
    assert due == datetime(2026, 9, 26, 15, 0, tzinfo=ic.KST)


def test_due_at_korean_date_format() -> None:
    due = ic.due_at_of("SCHEDULE", "제안요청 설명회 일시: 2026년 9월 12일 14시")
    assert due == datetime(2026, 9, 12, 14, 0, tzinfo=ic.KST)


def test_due_at_period_takes_end_date() -> None:
    due = ic.due_at_of("SCHEDULE", "접수 기간: 2026.09.01 ~ 2026.09.30")
    assert due == datetime(2026, 9, 30, 0, 0, tzinfo=ic.KST)


def test_due_at_none_without_explicit_date_or_for_task() -> None:
    assert ic.due_at_of("SCHEDULE", "제안서 제출 마감은 공고문에 따른다.") is None
    assert ic.due_at_of("TASK", "2026. 9. 26. 까지 교육 완료") is None


# --------------------------------------------------------------------------
# 표시 코드 · 페이로드 보강 (저장 id는 그대로)
# --------------------------------------------------------------------------


def test_display_code_keeps_number() -> None:
    assert ic.display_code("TASK", "REQ-003") == "TSK-003"
    assert ic.display_code("SPECIAL_CONDITION", "REQ-120") == "SPC-120"
    assert ic.display_code("REQUIREMENT", "REQ-001") == "REQ-001"


def test_enrich_payload_fills_only_missing_fields() -> None:
    payload = {
        "requirement_id": "REQ-007",
        "category": "일정",
        "requirement_type": "mandatory",
        "content": "제안서 제출 마감: 2026. 9. 26. 15:00까지",
        "source_text": "○ 제안서 제출 마감: 2026. 9. 26. 15:00까지",
    }
    assert ic.enrich_payload(payload, page_is_approximate=True) is True
    assert payload["requirement_id"] == "REQ-007"
    assert payload["item_type"] == "SCHEDULE"
    assert payload["display_code"] == "SCH-007"
    assert payload["page_is_approximate"] is True
    assert payload["review_status"] == "unreviewed"
    assert payload["due_at"].startswith("2026-09-26T15:00:00")
    # 두 번째 호출은 아무것도 바꾸지 않는다 (사람이 고친 값을 덮지 않는다).
    payload["item_type"] = "TASK"
    assert ic.enrich_payload(payload) is False
    assert payload["item_type"] == "TASK"


def test_item_counts_has_all_types() -> None:
    counts = ic.item_counts([{"item_type": "TASK"}, {"item_type": "TASK"}, {"item_type": "SCHEDULE"}, {}])
    assert counts["TASK"] == 2
    assert counts["SCHEDULE"] == 1
    assert counts["REQUIREMENT"] == 1
    assert set(counts) == set(ic.ITEM_TYPES)
