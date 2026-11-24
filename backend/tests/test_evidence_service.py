"""요구사항 ↔ 회사 근거 매칭 테스트.

핵심 계약 (CLAUDE.md 11)
    - 유사도가 높다고 자동으로 '충족'이 아니다. 채택(selected)과 후보(candidate)를 구분한다.
    - 모호한 요구사항(status=check)은 **점수가 아무리 높아도 자동 채택하지 않는다**.
    - 인덱스나 임베딩 키가 없으면 빈 결과를 정직하게 돌려준다. 지어내지 않는다.
    - 근거 범위(evidence_scope)에 맞는 인덱스만 쓴다. 합성·실제 자료를 조용히 합치지 않는다.

네트워크를 쓰지 않는다 — explicit_test 범위로 인덱스와 임베딩을 주입해 검증한다.
"""

from __future__ import annotations

import math

import pytest

from app.schemas.organization import AnalysisContext
from app.schemas.requirement import Requirement
from app.services import evidence_service as es

# 1과 0으로만 만든 직교 벡터 — 코사인 값을 손으로 계산할 수 있다.
VEC_A = [1.0, 0.0, 0.0]
VEC_B = [0.0, 1.0, 0.0]

TEST_CTX = AnalysisContext(organization_id="org-test", evidence_scope="explicit_test")


def make_requirement(req_id: str = "REQ-001", status: str = "unmatched") -> Requirement:
    return Requirement(
        id=f"test:{req_id}",
        procurement_id="test",
        requirement_id=req_id,
        category="과업내용",
        requirement_type="mandatory",
        title="생성형 AI 교육 과정 운영",
        content="생성형 AI 활용 교육 과정을 기획하고 운영한다",
        page=1,
        source_text="생성형 AI 활용 교육 과정을 기획하고 운영한다",
        status=status,  # type: ignore[arg-type]
    )


def make_chunk(evidence_id: str, embedding: list[float]) -> es.EvidenceChunk:
    return es.EvidenceChunk(
        evidence_id=evidence_id,
        document_name="회사소개서(합성)",
        doc_type="회사소개",
        page=1,
        source_text="생성형 AI 활용 실무교육을 주력 사업으로 수행합니다",
        embedding=embedding,
    )


@pytest.fixture
def stub_index(monkeypatch: pytest.MonkeyPatch):
    """임베딩을 주입한다 (네트워크·파일 없이). chunk 는 explicit_test 범위로 직접 넘긴다."""

    def install(chunks: list[es.EvidenceChunk], vectors: dict[str, list[float]]):
        monkeypatch.setattr(es.llm_client, "is_configured", lambda: True)
        monkeypatch.setattr(es, "embed_requirements", lambda reqs: vectors)
        return lambda reqs: es.match_requirements(reqs, context=TEST_CTX, chunks=chunks)

    return install


# --------------------------------------------------------------------------
# 코사인
# --------------------------------------------------------------------------


def test_같은_방향_벡터는_1이다() -> None:
    assert es.cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_직교_벡터는_0이다() -> None:
    assert es.cosine(VEC_A, VEC_B) == pytest.approx(0.0)


def test_영벡터는_0으로_처리한다() -> None:
    """0으로 나누지 않는다."""
    assert es.cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_길이가_다르면_오류를_낸다() -> None:
    """차원이 어긋난 인덱스를 조용히 넘기지 않는다."""
    with pytest.raises(ValueError):
        es.cosine([1.0, 0.0], [1.0, 0.0, 0.0])


# --------------------------------------------------------------------------
# 채택 / 후보 구분
# --------------------------------------------------------------------------


def test_임계값이_고정되어_있다() -> None:
    assert es.SELECT_THRESHOLD == 0.60
    assert es.CANDIDATE_THRESHOLD == 0.50
    assert es.CANDIDATE_THRESHOLD < es.SELECT_THRESHOLD


def test_유사도가_높으면_채택한다(stub_index) -> None:
    req = make_requirement()
    match = stub_index([make_chunk("EV-01", VEC_A)], {"REQ-001": VEC_A})

    result = match([req])

    assert result.available
    assert len(result.matches) == 1
    assert result.matches[0].selected is True
    assert result.scope_info is not None and result.scope_info.evidence_scope == "explicit_test"


def test_후보_기준에_못_미치면_채택하지_않는다(stub_index) -> None:
    # VEC_A와의 코사인이 1/sqrt(1+y^2) 이므로 y=1.52 -> 약 0.55 (채택 0.60 미만, 후보 0.50 이상)
    mixed = [1.0, 1.52, 0.0]
    norm = math.sqrt(sum(x * x for x in mixed))
    score = 1.0 / norm  # VEC_A와의 코사인
    assert es.CANDIDATE_THRESHOLD <= score < es.SELECT_THRESHOLD

    match = stub_index([make_chunk("EV-01", mixed)], {"REQ-001": VEC_A})
    result = match([make_requirement()])

    assert len(result.matches) == 1
    assert result.matches[0].selected is False
    assert "채택 기준" in (result.matches[0].note or "")


def test_후보_기준_미만은_아예_붙이지_않는다(stub_index) -> None:
    """0.50 미만에서는 무관한 문서가 섞이기 시작한다."""
    match = stub_index([make_chunk("EV-01", VEC_B)], {"REQ-001": VEC_A})
    result = match([make_requirement()])
    assert result.matches == []


# --------------------------------------------------------------------------
# 모호한 요구사항은 자동 채택 금지 (CLAUDE.md 11)
# --------------------------------------------------------------------------


def test_check_상태는_점수가_높아도_채택하지_않는다(stub_index) -> None:
    match = stub_index([make_chunk("EV-01", VEC_A)], {"REQ-001": VEC_A})

    result = match([make_requirement(status="check")])

    item = result.matches[0]
    assert item.similarity_score == pytest.approx(1.0)
    assert item.selected is False, "모호한 요구사항을 자동 충족 처리하면 안 된다"
    assert "사람 검토" in (item.note or "")


# --------------------------------------------------------------------------
# 사용 불가 상황 — 지어내지 않는다
# --------------------------------------------------------------------------


def test_인덱스가_없으면_빈_결과와_이유를_돌려준다() -> None:
    result = es.match_requirements([make_requirement()], context=TEST_CTX, chunks=[])
    assert result.available is False
    assert result.matches == []
    assert "인덱스" in (result.reason or "") or "회사자료" in (result.reason or "")


def test_임베딩_키가_없으면_건너뛴다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(es.llm_client, "is_configured", lambda: False)
    result = es.match_requirements([make_requirement()], context=TEST_CTX, chunks=[make_chunk("EV-01", VEC_A)])
    assert result.available is False
    # 문구는 「임베딩 키」에서 「AI 검색 설정」으로 바뀌었다 (사업담당자 용어).
    # 뜻은 같다 — 설정이 없어서 건너뛴다는 것. 낱말이 아니라 그 뜻을 본다.
    # 43차 결정 3 — 「AI 검색 설정이 없어」 대신 「회사 근거 연결(AI 검색)은 꺼 두었습니다 — 원장 후보에서 고르세요」
    assert "회사 근거 연결(AI 검색)은 꺼 두었습니다" in (result.reason or "")
    assert "원장 후보" in (result.reason or "")


def test_임베딩_호출이_실패해도_죽지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(es.llm_client, "is_configured", lambda: True)

    def boom(_reqs):
        raise es.llm_client.LLMUnavailableError("네트워크 오류")

    monkeypatch.setattr(es, "embed_requirements", boom)
    result = es.match_requirements([make_requirement()], context=TEST_CTX, chunks=[make_chunk("EV-01", VEC_A)])
    assert result.available is False
    assert "실패" in (result.reason or "")


def test_explicit_test_범위는_chunk를_넘겨야_한다() -> None:
    with pytest.raises(es.ScopeError):
        es.match_requirements([make_requirement()], context=TEST_CTX)


def test_운영_범위에는_chunk를_직접_넘길_수_없다() -> None:
    """internal/public_demo 는 인덱스 파일만 쓴다 — 테스트 chunk 를 운영 경로에 끼워 넣지 못한다."""
    with pytest.raises(es.ScopeError):
        es.match_requirements([make_requirement()], context=AnalysisContext(organization_id="org-test", evidence_scope="internal"), chunks=[make_chunk("EV-01", VEC_A)])


# --------------------------------------------------------------------------
# 출력 형태
# --------------------------------------------------------------------------


def test_상위_K개만_붙인다(stub_index) -> None:
    chunks = [make_chunk(f"EV-{i:02d}", VEC_A) for i in range(6)]
    match = stub_index(chunks, {"REQ-001": VEC_A})
    result = match([make_requirement()])
    assert len(result.matches) == es.TOP_K


def test_모든_증빙에_synthetic_표기가_붙는다(stub_index) -> None:
    """공개 데모에는 합성 자료만 쓴다 (CLAUDE.md 21)."""
    match = stub_index([make_chunk("EV-01", VEC_A)], {"REQ-001": VEC_A})
    payload = match([make_requirement()]).to_dict()
    assert all(link["synthetic"] for link in payload["links"])
    assert all(doc["synthetic"] for doc in payload["documents"])
    assert payload["scope"]["synthetic_evidence_used"] is True and payload["scope"]["real_evidence_used"] is False


def test_출력에_원문과_문서명이_남는다(stub_index) -> None:
    """근거 없이 점수만 보여주지 않는다."""
    match = stub_index([make_chunk("EV-01", VEC_A)], {"REQ-001": VEC_A})
    item = match([make_requirement()]).matches[0]
    assert item.document_name
    assert item.source_text.strip()
    assert item.page == 1


# --------------------------------------------------------------------------
# 자료 출처 표기 (합성 / 비식별한 실제 자료)
# --------------------------------------------------------------------------


def test_문서의_synthetic_값을_그대로_전달한다(stub_index) -> None:
    """하드코딩하면 실제 자료에 '합성' 배지가 붙어 화면이 거짓말을 한다."""
    chunk = make_chunk("EV-01", VEC_A)
    chunk.synthetic = False
    chunk.anonymized = True
    match = stub_index([chunk], {"REQ-001": VEC_A})

    payload = match([make_requirement()]).to_dict()

    assert payload["links"][0]["synthetic"] is False
    assert payload["links"][0]["anonymized"] is True
    assert payload["documents"][0]["synthetic"] is False


def test_합성과_실제_자료가_섞여도_각각_표기된다(stub_index) -> None:
    synthetic = make_chunk("EV-01", VEC_A)
    real = make_chunk("EV-02", VEC_A)
    real.synthetic = False
    real.anonymized = True
    match = stub_index([synthetic, real], {"REQ-001": VEC_A})

    result = match([make_requirement()])
    flags = {link["evidence_id"]: link["synthetic"] for link in result.to_dict()["links"]}

    assert flags["EV-01"] is True
    assert flags["EV-02"] is False
    assert result.scope_info is not None
    assert result.scope_info.synthetic_evidence_used is True and result.scope_info.real_evidence_used is True
