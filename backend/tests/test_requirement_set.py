"""요구사항 집합의 신원 — 안정 ID · 버전 · 대응 범위 · 심각도 정책.

여기서 지키는 계약은 하나로 요약된다.

    요구사항을 더 잘 추출했다는 이유로 기존 제안서가 갑자기 결함투성이로 보이면 안 된다.

그러려면 (1) 번호가 밀려도 연결이 끊기지 않아야 하고, (2) 초안이 어느 집합 기준인지
기록돼야 하며, (3) 미반영이라고 전부 같은 무게로 경고하면 안 된다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.requirement import Requirement
from app.services import analysis_state, auditor_service, item_classifier, requirement_set, rfp_parser


def req(
    requirement_id: str,
    content: str,
    *,
    item_type: str = "REQUIREMENT",
    criticality: str = "normal",
    requirement_type: str = "mandatory",
    response_scope: str | None = None,
    action_required: bool = False,
) -> dict[str, Any]:
    return {
        "id": f"pid:{requirement_id}",
        "procurement_id": "pid",
        "requirement_id": requirement_id,
        "category": "기타",
        "requirement_type": requirement_type,
        "title": content[:40],
        "content": content,
        "source_text": content,
        "status": "unmatched",
        "item_type": item_type,
        "criticality": criticality,
        "action_required": action_required,
        "response_scope": response_scope,
    }


# ---------------------------------------------------------------------------
# 안정 ID — 번호가 밀려도 같은 요구사항은 같은 신원
# ---------------------------------------------------------------------------


def test_요구사항이_중간에_끼어도_뒤_항목의_안정_ID가_그대로다():
    """지시서 핵심 — 「요구사항 중간 삽입 후 stable ID 유지」.

    이것이 깨지면 저장된 제안서가 다른 요구사항을 가리킨다(실측 19문장 중 5문장).
    """
    before = [req("REQ-001", "교육과정을 기획한다"), req("REQ-002", "보안성 검사를 받는다")]
    after = [
        req("REQ-001", "교육과정을 기획한다"),
        req("REQ-002", "새로 발견된 중간 요구사항"),  # ← 여기가 끼었다
        req("REQ-003", "보안성 검사를 받는다"),  # 번호가 밀렸다
    ]
    requirement_set.assign_identity(before, procurement_id="pid", document="doc.hwp")
    requirement_set.assign_identity(after, procurement_id="pid", document="doc.hwp")

    보안_이전 = next(r for r in before if "보안성" in r["content"])
    보안_이후 = next(r for r in after if "보안성" in r["content"])

    assert 보안_이전["requirement_id"] != 보안_이후["requirement_id"], "번호는 실제로 밀렸다"
    assert 보안_이전["stable_id"] == 보안_이후["stable_id"], "그래도 신원은 같아야 한다"


def test_display_code가_바뀌어도_연결이_깨지지_않는다():
    """화면 표시 코드(TSK-001)는 항목 유형을 따라 바뀐다. 저장 연결은 그것을 쓰지 않는다."""
    item = req("REQ-005", "교육을 운영한다", item_type="REQUIREMENT")
    requirement_set.assign_identity([item], procurement_id="pid", document="doc.hwp")
    before_stable = item["stable_id"]

    # 사람이 유형을 「과업」으로 정정하면 display_code 가 TSK-005 로 바뀐다.
    item["item_type"] = "TASK"
    item["display_code"] = item_classifier.display_code("TASK", "REQ-005")
    requirement_set.assign_identity([item], procurement_id="pid", document="doc.hwp")

    assert item["display_code"] == "TSK-005"
    assert item["stable_id"] == before_stable


def test_글머리표가_붙었다_떨어져도_같은_항목이다():
    """추출 규칙이 바뀌면 「○ 」가 붙었다 떨어졌다 한다. 그것으로 신원이 바뀌면 안 된다."""
    a = requirement_set.stable_requirement_id(procurement_id="p", document="d", source_text="○ 교육 운영")
    b = requirement_set.stable_requirement_id(procurement_id="p", document="d", source_text="교육 운영")
    assert a == b


def test_다른_요구사항은_다른_신원을_받는다():
    a = requirement_set.stable_requirement_id(procurement_id="p", document="d", source_text="20회 이상 운영")
    b = requirement_set.stable_requirement_id(procurement_id="p", document="d", source_text="30회 이상 운영")
    assert a != b, "수치가 다르면 다른 요구사항이다"


def test_같은_문장이_두_번_나오면_각각_다른_신원이다():
    items = [req("REQ-001", "제출서류를 확인한다"), req("REQ-002", "제출서류를 확인한다")]
    requirement_set.assign_identity(items, procurement_id="pid", document="doc.hwp")
    assert items[0]["stable_id"] != items[1]["stable_id"], "뭉뚱그리면 한쪽이 영영 미탐이 된다"


def test_첨부_파일명이_달라져도_같은_원문이면_같은_신원이다():
    """2026-09-14 사고의 회귀 테스트.

    같은 첨부를 다시 내려받으면서 파일명 앞의 `1_` 하나가 사라졌다(실측:
    `1_2. 제안요청서(피지컬 AI).hwp` → `2. 제안요청서(피지컬 AI).hwp`).
    그것만으로 56건 전체의 안정 ID 가 갈렸고, 저장된 제안서 19문장이 전부
    지금 요구사항을 못 찾게 됐다(0/19). 파일명은 전달 방식이지 신원이 아니다.
    """
    a = requirement_set.stable_requirement_id(
        procurement_id="pid", document="1_2. 제안요청서(피지컬 AI).hwp", source_text="교육은 총 20회 이상 운영한다"
    )
    b = requirement_set.stable_requirement_id(
        procurement_id="pid", document="2. 제안요청서(피지컬 AI).hwp", source_text="교육은 총 20회 이상 운영한다"
    )
    c = requirement_set.stable_requirement_id(procurement_id="pid", source_text="교육은 총 20회 이상 운영한다")
    assert a == b == c

    # 다른 공고의 같은 문장까지 뭉뚱그리지는 않는다.
    assert a != requirement_set.stable_requirement_id(
        procurement_id="다른공고", source_text="교육은 총 20회 이상 운영한다"
    )


def test_첨부_파일명이_달라져도_집합_해시가_같다():
    """파일명이 안정 ID 를 통해 집합 해시까지 흔들고 있었다 — 그러면 「요구사항이
    바뀌었다」는 거짓 신호가 뜨고 제안서가 이유 없이 «이전 기준»으로 밀린다."""
    first = [req("REQ-001", "가"), req("REQ-002", "나")]
    second = [req("REQ-001", "가"), req("REQ-002", "나")]
    requirement_set.assign_identity(first, procurement_id="pid", document="1_제안요청서.hwp")
    requirement_set.assign_identity(second, procurement_id="pid", document="제안요청서.hwp")
    assert requirement_set.set_hash(first) == requirement_set.set_hash(second)


def test_옛_규칙으로_찍힌_신원은_다시_계산할_수_있다():
    """마이그레이션이 쓰는 길. 파생값이므로 다시 계산하는 것은 추측이 아니다.

    `recompute=False`(기본)일 때는 한 번 정해진 신원을 그대로 둔다 — 저장된 제안서가
    그것을 가리키고 있어서, 대응표 없이 함부로 갈아 끼우면 연결이 끊긴다.
    """
    items = [req("REQ-001", "교육을 운영한다")]
    items[0]["stable_id"] = "SR-옛날값"

    requirement_set.assign_identity(items, procurement_id="pid", document="d.hwp")
    assert items[0]["stable_id"] == "SR-옛날값", "기본값은 이미 정해진 신원을 지키는 것이다"

    changed = requirement_set.assign_identity(items, procurement_id="pid", document="d.hwp", recompute=True)
    assert changed >= 1
    assert items[0]["stable_id"] == requirement_set.stable_requirement_id(
        procurement_id="pid", source_text="교육을 운영한다"
    )


# ---------------------------------------------------------------------------
# 집합 해시와 버전
# ---------------------------------------------------------------------------


def test_순서만_바뀐_집합은_같은_해시다():
    items = [req("REQ-001", "가"), req("REQ-002", "나")]
    requirement_set.assign_identity(items, procurement_id="pid", document="d")
    assert requirement_set.set_hash(items) == requirement_set.set_hash(list(reversed(items)))


def test_항목이_늘면_해시가_달라진다():
    items = [req("REQ-001", "가")]
    requirement_set.assign_identity(items, procurement_id="pid", document="d")
    before = requirement_set.set_hash(items)
    items.append(req("REQ-002", "나"))
    requirement_set.assign_identity(items, procurement_id="pid", document="d")
    assert requirement_set.set_hash(items) != before


def test_같은_내용으로_다시_찍어도_판_번호가_오르지_않는다():
    """마이그레이션 멱등성 — 여러 번 돌려도 판이 쌓이지 않아야 한다."""
    payload = {"procurement_id": "pid", "requirements": [req("REQ-001", "가")]}
    requirement_set.assign_identity(payload["requirements"], procurement_id="pid", document="d")
    first = requirement_set.describe(payload)
    second = requirement_set.describe(payload, previous=first.to_dict())
    third = requirement_set.describe(payload, previous=second.to_dict())
    assert first.requirement_set_version == second.requirement_set_version == third.requirement_set_version == 1
    assert first.requirement_set_id == third.requirement_set_id


def test_내용이_바뀌면_판_번호가_오른다():
    payload = {"procurement_id": "pid", "requirements": [req("REQ-001", "가")]}
    requirement_set.assign_identity(payload["requirements"], procurement_id="pid", document="d")
    first = requirement_set.describe(payload)

    payload["requirements"].append(req("REQ-002", "나"))
    requirement_set.assign_identity(payload["requirements"], procurement_id="pid", document="d")
    second = requirement_set.describe(payload, previous=first.to_dict())
    assert second.requirement_set_version == 2


# ---------------------------------------------------------------------------
# 제안서가 어느 집합 기준인가
# ---------------------------------------------------------------------------


def test_해시가_같으면_제안서가_최신이다():
    assert (
        requirement_set.proposal_basis(
            proposal_set_hash="abc", proposal_mandatory_total=10, current_set_hash="abc", current_mandatory_count=10
        )
        == "current"
    )


def test_해시가_다르면_제안서가_이전_기준이다():
    assert (
        requirement_set.proposal_basis(
            proposal_set_hash="abc", proposal_mandatory_total=10, current_set_hash="xyz", current_mandatory_count=20
        )
        == "stale_requirements"
    )


def test_해시가_없어도_필수_건수가_다르면_이전_기준으로_본다():
    """옛 저장본에는 집합 기록이 없다. 32건 기준을 55건 집합과 견주는 것을 그냥 지나치면 안 된다."""
    assert (
        requirement_set.proposal_basis(
            proposal_set_hash=None, proposal_mandatory_total=32, current_set_hash="xyz", current_mandatory_count=55
        )
        == "stale_requirements"
    )


def test_근거가_없으면_최신이라고_단정하지_않는다():
    """CLAUDE.md 11 — 없는 근거를 만들지 않는다."""
    assert (
        requirement_set.proposal_basis(
            proposal_set_hash=None, proposal_mandatory_total=10, current_set_hash="xyz", current_mandatory_count=10
        )
        == "unknown_basis"
    )


# ---------------------------------------------------------------------------
# 대응 범위
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "item_type, content, expected",
    [
        ("TASK", "교육과정을 기획한다", "PROPOSAL_BODY"),
        ("ELIGIBILITY", "업종코드 1234 를 보유해야 한다", "ELIGIBILITY_DOCUMENT"),
        ("SUBMISSION", "제안서는 HWP 로 15부 제출한다", "SUBMISSION_CHECKLIST"),
        ("REQUIREMENT", "성과품의 소유권은 발주처에 귀속된다", "CONTRACT_COMPLIANCE"),
        ("REQUIREMENT", "가격제안서를 별도 봉투에 넣어 제출한다", "PRICE_PROPOSAL"),
        ("SCHEDULE", "현장설명회에 반드시 참석하여야 한다", "INTERNAL_ACTION"),
        ("REFERENCE", "본 사업의 배경은 다음과 같다", "REFERENCE_ONLY"),
    ],
)
def test_대응_범위를_유형과_본문에서_정한다(item_type: str, content: str, expected: str):
    assert item_classifier.response_scope_of(item_type, "mandatory", content, content) == expected


def test_해당_없음은_규칙으로_만들지_않는다():
    """원문만 보고 「우리 사업에 해당 없음」을 단정할 수 없다. 사람이 정정으로만 넣는다."""
    scopes = {
        item_classifier.response_scope_of(t, "mandatory", "아무 문장", "아무 문장")
        for t in item_classifier.ITEM_TYPES
    }
    assert "NOT_APPLICABLE" not in scopes


# ---------------------------------------------------------------------------
# 심각도 — 미반영이라고 전부 HIGH 가 아니다
# ---------------------------------------------------------------------------


def _requirement(**kwargs: Any) -> Requirement:
    base = dict(
        id="pid:REQ-001",
        procurement_id="pid",
        requirement_id="REQ-001",
        category="기타",
        requirement_type="mandatory",
        title="제목",
        content="내용",
        source_text="내용",
    )
    base.update(kwargs)
    return Requirement(**base)


def test_계약_준수사항_미기재를_HIGH로_처리하지_않는다():
    """실측 — 「성과품 납품 후 자문 요청에 성실히 응하여야」가 제안서 누락 HIGH 였다.

    제안서 본문에 다시 적을 것이 아니라 계약하면 지키는 조항이다.
    """
    item = _requirement(
        content="용역수행자는 성과품 납품 후 1년 내 자문 요청에 성실히 응하여야 한다",
        response_scope="CONTRACT_COMPLIANCE",
    )
    assert auditor_service.missing_severity(item) == "low"


def test_참가를_막는_조건_누락은_CRITICAL이다():
    item = _requirement(
        content="입찰공고일 기준 다음 각 호의 자격을 모두 갖춘 자이어야 한다",
        criticality="blocker",
        response_scope="ELIGIBILITY_DOCUMENT",
    )
    assert auditor_service.missing_severity(item) == "critical"


def test_평가배점_항목_누락은_HIGH다():
    item = _requirement(content="유사 실적 3건 이상", item_type="EVALUATION", response_scope="PROPOSAL_BODY")
    assert auditor_service.missing_severity(item) == "high"


def test_수치_의무가_걸린_본문_항목_누락은_HIGH다():
    item = _requirement(
        content="만족도 조사를 실시하고 응답률 80% 이상을 확보해야 한다",
        response_scope="PROPOSAL_BODY",
    )
    assert auditor_service.missing_severity(item) == "high"


def test_보완_가능한_본문_부족은_MEDIUM이다():
    item = _requirement(content="전담 운영 매니저를 배정한다", response_scope="PROPOSAL_BODY")
    assert auditor_service.missing_severity(item) == "medium"


def test_참고_항목은_결함이_아니다():
    item = _requirement(content="본 사업의 배경", item_type="REFERENCE", response_scope="REFERENCE_ONLY")
    assert auditor_service.missing_severity(item) == "info"


def test_LLM이_대응있다고_한_것은_확인_요청이지_결함이_아니다():
    item = _requirement(content="유사 실적 3건 이상", item_type="EVALUATION", response_scope="PROPOSAL_BODY")
    assert auditor_service.partial_severity(item, llm_says_covered=True) == "low"
    # 다만 참가를 막는 조건은 LLM 판단만 믿고 넘길 수 없다.
    blocker = _requirement(criticality="blocker", response_scope="ELIGIBILITY_DOCUMENT")
    assert auditor_service.partial_severity(blocker, llm_says_covered=True) == "medium"


def test_같은_원인의_발견을_묶는_키가_있다():
    item = _requirement(response_scope="SUBMISSION_CHECKLIST")
    key, label = auditor_service.group_of("missing_requirement", item)
    assert key == "scope:SUBMISSION_CHECKLIST"
    assert "제출" in label


# ---------------------------------------------------------------------------
# 변경 영향 — «제안서가 실제로 본 판»과 견주는가
# ---------------------------------------------------------------------------


class _FakeSection:
    """proposal_service.load_section 이 돌려주는 것 중 여기서 쓰는 두 필드만."""

    def __init__(self, *, requirement_set_hash: str | None = None, mandatory_total: int | None = None) -> None:
        self.requirement_set_hash = requirement_set_hash
        self.mandatory_total = mandatory_total
        self.covered_requirement_ids: list[str] = []


def _version(set_hash: str, mandatory: int) -> dict[str, Any]:
    return {
        "requirement_set_hash": set_hash,
        "requirements": [req(f"REQ-{i:03d}", f"요구사항 {i}") for i in range(1, mandatory + 1)],
    }


def test_제안서_해시가_가리키는_판을_찾아_견준다(monkeypatch: pytest.MonkeyPatch):
    versions = [_version("aaa", 2), _version("bbb", 3)]
    monkeypatch.setattr(analysis_state.rfp_parser, "list_versions", lambda pid: versions)
    found, reason = analysis_state.proposal_basis_version(
        "pid", _FakeSection(requirement_set_hash="aaa"), current_hash="ccc"
    )
    assert found is versions[0]
    assert reason == ""


def test_기준_판을_못_찾으면_아무_판이나_견주지_않는다(monkeypatch: pytest.MonkeyPatch):
    """실측 — 준비 상태는 「필수 32 → 54」라 하고 변경 영향은 「새로 발견 0건」이라 했다.

    뒤엣것은 «직전 판(56건) ↔ 현재(55건)» 비교였다. 제안서가 본 32건짜리 판은
    보존돼 있지 않다. 그럴 때는 못 찾았다고 말해야 한다.
    """
    monkeypatch.setattr(analysis_state.rfp_parser, "list_versions", lambda pid: [_version("aaa", 55), _version("bbb", 54)])
    found, reason = analysis_state.proposal_basis_version(
        "pid", _FakeSection(mandatory_total=32), current_hash="ccc"
    )
    assert found is None
    assert "32" in reason


def test_필수_건수가_같은_판이_둘이면_고르지_않는다(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(analysis_state.rfp_parser, "list_versions", lambda pid: [_version("aaa", 32), _version("bbb", 32)])
    found, reason = analysis_state.proposal_basis_version(
        "pid", _FakeSection(mandatory_total=32), current_hash="ccc"
    )
    assert found is None
    assert "가릴 수 없" in reason


def test_필수_건수로_판이_하나만_짚이면_그것을_쓴다(monkeypatch: pytest.MonkeyPatch):
    versions = [_version("aaa", 32), _version("bbb", 54)]
    monkeypatch.setattr(analysis_state.rfp_parser, "list_versions", lambda pid: versions)
    found, reason = analysis_state.proposal_basis_version(
        "pid", _FakeSection(mandatory_total=32), current_hash="ccc"
    )
    assert found is versions[0]
    assert reason == ""


def test_초안이_없으면_기준_판도_없다():
    found, reason = analysis_state.proposal_basis_version("pid", None, current_hash="ccc")
    assert found is None
    assert "초안" in reason


# ---------------------------------------------------------------------------
# 실제 공고 — 분모와 상태
# ---------------------------------------------------------------------------

REAL_ID = "g2b-R26BK01707959-000"


def _has_real_notice() -> bool:
    return rfp_parser.generated_path(REAL_ID).exists()


real_only = pytest.mark.skipif(not _has_real_notice(), reason="실공고 저장본이 없는 환경")


@real_only
def test_전체_필수_선택_분모가_일치한다():
    """재분석 결과 — 「전체 55건·필수 54건·조건 1건 분모 일치」.

    서식 하단의 단독 확인 문구 1건을 요구사항에서 제외한 최신 기준이다.
    """
    parsed = rfp_parser.load_generated(REAL_ID)
    assert parsed.count == parsed.mandatory_count + parsed.optional_or_conditional_count
    assert parsed.mandatory_count == 54
    assert parsed.optional_or_conditional_count == 1
    assert parsed.count == 55


@real_only
def test_이전_기준_초안은_최신으로_표시되지_않는다():
    readiness = analysis_state.audit_readiness(REAL_ID)
    assert readiness.basis == "stale_requirements"
    assert readiness.ready is False
    assert "필수 요구사항" in readiness.message
    assert "32건" in readiness.message and "54건" in readiness.message
    keys = {a["key"] for a in readiness.actions}
    assert {"view_changes", "compare", "regenerate", "keep"} <= keys


@real_only
def test_이전_기준_초안으로_일반_감사를_돌리면_막힌다():
    from app.services import proposal_service

    client = TestClient(app)
    section = proposal_service.load_section(REAL_ID)
    text = "\n".join(s.text for s in section.sentences)

    blocked = client.post(
        "/api/auditor/run",
        json={"procurement_id": REAL_ID, "proposal_text": text, "use_llm": False},
    )
    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["code"] == "STALE_REQUIREMENTS"

    # 일부러 견주는 것은 막지 않는다 — 대신 결과에 모드가 남는다.
    allowed = client.post(
        "/api/auditor/run",
        json={
            "procurement_id": REAL_ID,
            "proposal_text": text,
            "use_llm": False,
            "mode": "change_impact",
        },
    )
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["mode"] == "change_impact"
    assert body["stale_requirements"] is True


@real_only
def test_새로_붙여넣은_초안은_막히지_않는다():
    """Auditor 는 초안을 붙여넣어서도 돌린다. 저장본이 낡았다고 그 경로를 막으면 안 된다."""
    client = TestClient(app)
    response = client.post(
        "/api/auditor/run",
        json={
            "procurement_id": REAL_ID,
            "proposal_text": "교육과정을 기획하고 운영하겠습니다. 전담 매니저를 배정하겠습니다.",
            "use_llm": False,
        },
    )
    assert response.status_code == 200


@real_only
def test_미반영이_전부_HIGH가_아니다():
    from app.services import proposal_service

    section = proposal_service.load_section(REAL_ID)
    text = "\n".join(s.text for s in section.sentences)
    run = auditor_service.run_audit(REAL_ID, text, use_llm=False, mode="change_impact")

    severities = {f.severity for f in run.findings}
    assert "critical" in severities, "참가를 막는 조건은 먼저 보여야 한다"
    high = sum(1 for f in run.findings if f.severity == "high")
    assert high < len(run.findings), "전부 high 이면 우선순위가 없는 것과 같다"
    assert all(f.group_key for f in run.findings), "묶음 없이 REQ 번호만 늘어놓지 않는다"


@real_only
def test_구버전_제안서의_번호_불일치를_최신_근거처럼_취급하지_않는다():
    """재분석 뒤에도 기존 초안은 보존하되 최신 기준으로 가장하지 않는다.

    2026-09-14 — 여기서 원래 「어긋난 문장이 하나는 있어야 한다」고 못 박고 있었다.
    그때 실제로 어긋나 있었기 때문인데, 그 어긋남의 정체는 «요구사항이 바뀐 것»이
    아니라 첨부 파일명이 `1_2. 제안요청서…hwp` → `2. 제안요청서…hwp` 로 바뀌면서
    안정 ID 가 전부 갈린 사고였다(19문장 0/19). 사고를 계약으로 굳혀 놓은 셈이라
    바로잡는다 — **연결이 끊긴 것과 기준이 낡은 것은 다른 문제다.**

    - 연결(문장 → 요구사항)은 이어져 있어야 한다.
    - 그래도 이 초안은 필수 32건 기준이므로 «최신»이 아니다. 그 판정은 연결이
      깨졌는지가 아니라 «어느 집합을 보고 만들었는가»에서 나와야 한다.
    """
    from app.services import proposal_service

    parsed = rfp_parser.load_generated(REAL_ID)
    by_id = {r.requirement_id: r for r in parsed.requirements}
    section = proposal_service.load_section(REAL_ID)

    mismatched: list[str] = []
    linked = 0
    for sentence in section.sentences:
        if not sentence.requirement_id or not sentence.stable_requirement_id:
            continue
        linked += 1
        target = by_id.get(sentence.requirement_id)
        if target is None or target.stable_id != sentence.stable_requirement_id:
            mismatched.append(sentence.id)

    assert linked, "REQ 번호와 안정 ID 를 함께 가진 문장이 있어야 이 테스트가 뜻이 있다"
    assert not mismatched, f"문장이 가리키는 요구사항과 안정 ID 가 어긋난다: {mismatched}"

    # 연결이 성해도 «최신»은 아니다 — 기준 집합이 다르다.
    readiness = analysis_state.audit_readiness(REAL_ID)
    assert readiness.basis == "stale_requirements"
    assert readiness.ready is False


@real_only
def test_이전_요구사항_판이_보존된다():
    versions = rfp_parser.list_versions(REAL_ID)
    assert versions, "덮어쓰기 전 판이 남아야 한다"
    assert all(v.get("requirement_set_hash") for v in versions)


@real_only
def test_실제_구성이_달라진_이전_판은_변경비교에_사용한다():
    """허위 요구사항 제거로 구성이 달라졌으므로 이전 판과 변경점을 보여준다."""
    versions = rfp_parser.list_versions(REAL_ID)
    assert versions, "보존된 판이 있어야 이 테스트가 뜻이 있다"

    previous = rfp_parser.previous_version(REAL_ID)
    assert previous is not None

    stored = rfp_parser.load_generated(REAL_ID)
    archived_ids = {r.get("stable_id") for r in previous.get("requirements", [])}
    current_ids = {r.stable_id for r in stored.requirements}
    assert archived_ids != current_ids, "보존된 판과 현재 판의 요구사항 구성이 달라야 한다"

    impact = analysis_state.change_impact(REAL_ID)
    assert impact["available"] is True


@real_only
def test_제안서_대비_변화는_기준_판을_찾았을_때만_그렇게_말한다():
    """이 공고의 초안은 필수 32건 기준인데 보존된 판은 55·54건뿐이다.

    그래도 판 대 판 비교는 낼 수 있다. 다만 그것을 「제안서 대비 변화」로 읽으면
    「필수 32 → 54」와 「새로 발견 0건」이 한 화면에서 서로를 부정한다. 무엇과
    견줬는지(compared_to)와 «제안서 기준 비교는 불가»를 함께 내려보내야 한다.
    """
    impact = analysis_state.change_impact(REAL_ID)
    assert impact["compared_to"] == "latest_previous_version"
    assert impact["proposal_comparison"]["available"] is False
    assert "32" in impact["proposal_comparison"]["reason"]
    # 견준 판의 필수 건수를 숨기지 않는다 — 준비 상태 문구의 32건과 다른 값이다.
    assert impact["previous"]["mandatory_count"] != impact["proposal_comparison"]["mandatory_total"]


@real_only
def test_저장된_초안이_지금_요구사항을_가리킨다():
    """첨부 파일명이 바뀌며 끊겼던 연결(19문장 0/19)의 회귀 테스트."""
    from app.services import proposal_service

    parsed = rfp_parser.load_generated(REAL_ID)
    stable_ids = {r.stable_id for r in parsed.requirements if r.stable_id}
    section = proposal_service.load_section(REAL_ID)

    with_id = [s for s in section.sentences if s.stable_requirement_id]
    assert with_id, "안정 ID 를 가진 문장이 있어야 한다"
    orphans = [s.id for s in with_id if s.stable_requirement_id not in stable_ids]
    assert not orphans, f"지금 요구사항에 없는 안정 ID 를 가리킨다: {orphans}"
