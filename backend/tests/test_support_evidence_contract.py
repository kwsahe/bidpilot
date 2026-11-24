"""지원사업 회사근거 매칭의 `condition` 계약 — 프런트 3D 가 여기에 기대고 있다.

`_match_evidence` 가 돌려주는 각 근거의 `condition` 은 **항목 단위 매핑이 아니다.**
`_evidence_requirements` 가 공고 원문에서 뽑아 만든 **검색 앵커 세 개의 이름**일 뿐이다:

    사업 개요   ← program.summary      (bsnsSumryCn)
    지원 분야   ← 분류 대·중 + 제목    (pldirSportRealmLclasCodeNm·…MlsfcCodeNm)
    지원 대상   ← program.target + 제목 (trgetNm)

즉 `condition` 은 「신청자격 4묶음 중 어느 항목에 이 근거가 붙는가」가 **아니다.**
`eligibility_items` 의 `target`·`company_type`·`region`·`business_age`·`excluded` 나
`condition_items` 의 `method`·`scale`·`self_burden`·`preferred` 에는 근거가 붙지 않는다 —
애초에 그 항목들로 검색하지 않기 때문이다.

이 사실을 여기서 못 박는 이유는 화면 쪽 사고 하나 때문이다. 3D 그래프가 근거 노드를
「신청자격 묶음 아래」로 매달면, 화면은 「신청자격을 항목별로 검증했다」고 말하게 되는데
실제로 백엔드가 한 일은 **세 덩어리 텍스트로 한 번 검색한 것**이다. 그래서 그래프는
근거를 항목이 아니라 **「회사자료 검색 기준」 묶음** 하나에 매단다.

**이 테스트의 뜻:** 나중에 백엔드가 진짜 항목 단위 매핑을 주기 시작하면
(예: `condition` 에 "업력 조건"·"제외 대상"이 실려 오면) **이 테스트가 먼저 깨진다.**
그러면 프런트가 「검색 기준 묶음」을 「항목별 근거」로 바꿔야 한다는 것을 그 시점에 알 수 있다.
테스트가 깨지면 지우지 말고 화면 구조를 함께 고쳐라.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.schemas.business_opportunity import SupportAttachment, SupportProgram
from app.schemas.organization import AnalysisContext
from app.services import evidence_service, support_application_service as svc

# 화면이 근거를 매달 수 있는 앵커 — 이 셋 말고는 없다.
EVIDENCE_ANCHORS = {"사업 개요", "지원 분야", "지원 대상"}


def _program(**overrides) -> SupportProgram:
    """세 앵커가 모두 서는 완전한 공고. 원문에 있는 필드만 채운다."""
    base = dict(
        id="bizinfo-TEST-0001",
        title="중소기업 생성형 AI 활용 실무교육 지원",
        agency="테스트진흥원",
        summary="재직자를 대상으로 생성형 AI 활용 실무교육을 운영하는 비용을 지원합니다.",
        apply_start=date(2026, 9, 1),
        apply_end=date(2026, 10, 31),
        apply_period_text="2026-09-01 ~ 2026-10-31",
        apply_period_kind="dated",
        category="인력",
        subcategory="교육",
        hashtags=["광주", "중소기업"],
        target="중소기업, 소상공인",
        apply_method="온라인 신청서 제출 후 사업계획서 및 증빙 서류 첨부",
        attachments=[SupportAttachment(name="신청서식.hwp", url="https://example.invalid/f", kind="form")],
    )
    base.update(overrides)
    return SupportProgram(**base)


def _items(program: SupportProgram):
    """실제 호출부(`analyze`)와 같은 순서로 넘긴다: conditions + eligibility."""
    return svc.condition_items(program) + svc.eligibility_items(program)


@pytest.fixture
def echo_matcher(monkeypatch):
    """`evidence_service.match_requirements` 를 요구사항마다 근거 1건씩 되돌려주는 가짜로 바꾼다.

    임베딩 키·회사 색인 없이도 **`requirement_id → condition` 라벨 변환**만 따로 볼 수 있다.
    반환하는 근거 내용은 검사 대상이 아니다 (여기서 회사자료를 지어내지 않는다).
    """

    def fake(requirements, *, context, chunks=None):
        matches = [
            evidence_service.EvidenceMatch(
                requirement_id=r.requirement_id,
                evidence_id=f"chunk-{i}",
                document_name="합성 회사소개서",
                doc_type="company_profile",
                page=1,
                source_text="(가짜 매처가 넣은 자리표시 텍스트)",
                similarity_score=0.5,
                selected=i == 0,
            )
            for i, r in enumerate(requirements)
        ]
        return evidence_service.EvidenceResult(
            available=True,
            matches=matches,
            scope_info=evidence_service.scope_info_of(context, [], matches),
        )

    monkeypatch.setattr(evidence_service, "match_requirements", fake)
    return fake


CONTEXT = AnalysisContext(organization_id="org-sample", evidence_scope="public_demo")


# ---------------------------------------------------------------------------
# 앵커 이름 고정
# ---------------------------------------------------------------------------


def test_검색_앵커는_정확히_세_개다():
    """`_evidence_requirements` 가 만드는 항목의 title 이 곧 `condition` 이 된다."""
    program = _program()
    requirements = svc._evidence_requirements(program, _items(program))
    assert [r.title for r in requirements] == ["사업 개요", "지원 분야", "지원 대상"]


def test_condition_은_앵커_세_개_안에서만_나온다(echo_matcher):
    program = _program()
    matches, scope = svc._match_evidence(program, _items(program), context=CONTEXT)

    assert matches, "앵커가 셋 다 서는 공고인데 근거가 하나도 없다"
    conditions = {m["condition"] for m in matches}
    assert conditions <= EVIDENCE_ANCHORS, f"모르는 condition 이 생겼다: {conditions - EVIDENCE_ANCHORS}"
    assert conditions == EVIDENCE_ANCHORS, "완전한 공고에서는 세 앵커가 모두 나와야 한다"
    assert scope is not None


def test_condition_에_항목_라벨이_실려_오지_않는다(echo_matcher):
    """신청자격·조건 «항목»의 라벨은 `condition` 이 될 수 없다.

    이것이 깨졌다면 백엔드가 항목 단위 매핑을 시작한 것이다 — 좋은 일이지만,
    그때는 화면이 근거를 「회사자료 검색 기준」이 아니라 항목 아래로 옮겨야 한다.
    """
    program = _program()
    items = _items(program)
    matches, _ = svc._match_evidence(program, items, context=CONTEXT)

    conditions = {m["condition"] for m in matches}
    item_labels = {i.label for i in items} - EVIDENCE_ANCHORS
    assert conditions & item_labels == set(), (
        f"항목 라벨이 condition 으로 올라왔다: {sorted(conditions & item_labels)}. "
        "백엔드가 항목 단위 매핑을 주기 시작했다면 프런트 그래프도 함께 고쳐야 한다."
    )


def test_condition_은_REQ_번호로_새지_않는다(echo_matcher):
    """`label_of.get(...)` 의 기본값은 requirement_id 다. 화면에 「REQ-001」이 뜨면 안 된다."""
    program = _program()
    matches, _ = svc._match_evidence(program, _items(program), context=CONTEXT)
    assert not any(m["condition"].startswith("REQ-") for m in matches)


# ---------------------------------------------------------------------------
# 원문이 비면 앵커도 준다 — 없는 값을 만들지 않는다
# ---------------------------------------------------------------------------


def test_개요가_없으면_사업_개요_앵커도_없다(echo_matcher):
    program = _program(summary=None)
    matches, _ = svc._match_evidence(program, _items(program), context=CONTEXT)
    conditions = {m["condition"] for m in matches}
    assert "사업 개요" not in conditions
    assert conditions <= EVIDENCE_ANCHORS


def test_분류도_대상도_개요도_없으면_검색_자체를_안_한다(echo_matcher):
    """앵커가 하나도 없으면 `([], None)`. 빈 텍스트로 억지 검색을 돌리지 않는다."""
    program = _program(summary=None, category=None, subcategory=None, target=None)
    matches, scope = svc._match_evidence(program, _items(program), context=CONTEXT)
    assert matches == []
    assert scope is None


def test_매칭이_불가하면_근거는_비지만_범위는_남는다(monkeypatch):
    """임베딩 키가 없거나 색인이 비었을 때. 근거를 지어내지 않고, 왜 비었는지는 남긴다."""
    reason = "승인·색인된 회사자료가 없습니다."

    def unavailable(requirements, *, context, chunks=None):
        return evidence_service.EvidenceResult(
            available=False,
            reason=reason,
            scope_info=evidence_service.scope_info_of(context, [], [], note=reason),
        )

    monkeypatch.setattr(evidence_service, "match_requirements", unavailable)
    program = _program()
    matches, scope = svc._match_evidence(program, _items(program), context=CONTEXT)
    assert matches == []
    assert scope is not None and scope["note"] == reason
