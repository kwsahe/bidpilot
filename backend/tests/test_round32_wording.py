"""32차 §3-E — 글(R31-16~24 · 어려운 글 · 뜻 틀린 곳)과 저장된 결과의 옛 글을 읽을 때 바꾸는 함수."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.schemas.business_opportunity import SupportRequirementItem
from app.services import auditor_service, eligibility_engine, opportunity_priority, proposal_service
from app.services import plan_draft_service as pds
from app.services import support_application_service as sas
from app.services import wording
from app.services.support_kinds import SupportKindResult


# --------------------------------------------------------------------------
# 번호 풀이 — 프론트 clauseRefText 와 같은 규칙
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "want"), [
    ("REQ-014", "14번 요구사항"), ("REQ-001", "1번 요구사항"), ("RFP-QC-20", "20번 조항"), ("QC-03", "3번 조항"), ("X-9", "X-9"),
])
def test_요구사항_조항_번호를_사람_말로(raw: str, want: str) -> None:
    assert wording.requirement_label(raw) == want


def test_제안요청서_쪽과_번호() -> None:
    assert wording.rfp_ref(17, "REQ-014") == "제안요청서 17쪽 · 14번 요구사항"
    assert wording.rfp_ref(None, "REQ-014") == "제안요청서 14번 요구사항"


# --------------------------------------------------------------------------
# §3-E-2 저장된 결과의 옛 글 — 읽어서 내보낼 때만 바꾼다
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("old", "new"), [
    # 점검 권고(1707959 저장본 꼴)
    ("RFP p.9 REQ-015 요구사항 '만족도 조사'에 대응하는 문장이 초안에 없습니다.",
     "제안요청서 9쪽 · 15번 요구사항 '만족도 조사'에 대응하는 문장이 초안에 없습니다."),
    ("RFP p.4 REQ-021 조건은 원문만으로 충족을 확정할 수 없어 CHECK 상태입니다. 초안이 충족을 단정하고 있으니",
     "제안요청서 4쪽 · 21번 요구사항은 원문만으로 충족을 확정할 수 없어 「확인 필요」로 남아 있습니다. 초안이 충족을 단정하고 있으니"),
    ("제안요청서 17쪽 (REQ-014) 요구사항에 부분적으로만 대응합니다.", "제안요청서 17쪽 · 14번 요구사항에 부분적으로만 대응합니다."),
    # 제안서 꼬리 — 쪽은 p.N 그대로(「3쪽」은 점검 숫자 검사가 근거 없는 숫자로 읽는다)
    ("교육을 20회 운영합니다. (RFP p.3 요구사항 준수)", "교육을 20회 운영합니다. (제안요청서 p.3 요구사항 준수)"),
    # R31-16 「(합성)」 · 후보 근거의 0~1 소수
    ("확인 필요. (후보 근거: 「AI 심화 커리큘럼(합성)」 p.2, 유사도 0.42 — 미채택)", "확인 필요. (후보 근거: 「AI 심화 커리큘럼(가상 예시)」 p.2 — 미채택)"),
    # 사업계획서 초안 경고(126482 저장본 25곳)
    ("공고 인용 밖 내용 — AI 제안", pds.FLAG_NOTICE_EXTRA),
    ("회사 근거 밖 내용 — AI 제안", pds.FLAG_COMPANY_EXTRA),
    ("공고 근거 확인 필요 — 인용한 공고 문장을 찾지 못했다", pds.FLAG_NOTICE_NOT_FOUND),
    ("공고 근거 확인 필요 — 3억원", f"{pds.FLAG_NOTICE_VALUES}: 3억원 — 확인하세요"),
    ("공고 문장 복사 — 문장의 70% 이상이 공고 한 대목과 겹친다", f"{pds.FLAG_COPY}(문장의 70% 이상이 공고 한 대목과 겹친다)"),
    ("금칙어 — 보장, 최고", f"{pds.FLAG_BANNED}: 보장, 최고"),
    # R31-22 그림 공고문 메모
    ("공고문이 이미지입니다 — 요약문으로 판정합니다", "공고문이 그림 파일이라 글을 읽지 못해, 기업마당 요약만 보고 판정했습니다"),
])
def test_옛_글을_새_말로(old: str, new: str) -> None:
    assert wording.modernize_text(old) == new


def test_모르는_글과_키는_그대로_두고_사본을_돌려준다() -> None:
    saved = {"REQ-014": "교육은 총 20회 이상 운영한다.", "flags": ["공고 인용 밖 내용 — AI 제안"], "requirement_id": "REQ-014"}
    out = wording.modernize(saved)
    assert out["REQ-014"] == "교육은 총 20회 이상 운영한다." and out["requirement_id"] == "REQ-014"
    assert out["flags"] == [pds.FLAG_NOTICE_EXTRA]
    assert saved["flags"] == ["공고 인용 밖 내용 — AI 제안"]  # 원본(저장 파일 내용)은 그대로


def test_새로_만드는_초안_경고도_같은_말이다() -> None:
    """옛 경고 → 새 말 표의 오른쪽이 지금 코드가 만드는 경고와 같다 — 두 판이 갈리지 않는다."""
    assert wording.modernize_text(pds.FLAG_NOTICE_EXTRA) == pds.FLAG_NOTICE_EXTRA
    assert pds.FLAG_NOTICE_NOT_FOUND in pds.GROUNDING_FLAGS and pds.FLAG_NOTICE_EXTRA not in pds.GROUNDING_FLAGS


# --------------------------------------------------------------------------
# R31-24 · 어려운 글 #18 — 점검 권고 · 꼬리 정규식(R31-23)
# --------------------------------------------------------------------------


def test_점검_권고는_내부_번호_대신_N번_요구사항() -> None:
    req = SimpleNamespace(page=17, requirement_id="REQ-014", title="만족도 조사", content="만족도 조사 실시", source_text="교육 종료 후 만족도 조사 실시")
    text = auditor_service._missing_recommendation(req, None)  # type: ignore[arg-type]
    assert text.startswith("제안요청서 17쪽 · 14번 요구사항 '만족도 조사'에") and "REQ-" not in text and "요구사항 요구사항" not in text


@pytest.mark.parametrize("tail", [
    "(RFP p.3 요구사항 준수)", "(RFP 요구사항 준수)", "(제안요청서 p.17 요구사항)", "(제안요청서 요구사항)", "(제안요청서 p.3 요구사항 준수)",
    '(근거: 「자료」 p.1 "회사 문단")',
])
def test_꼬리_정규식은_옛_꼴과_새_꼴을_모두_걷는다(tail: str) -> None:
    assert proposal_service.TRAILING_NOTE_RE.sub("", f"교육을 운영합니다. {tail}") == "교육을 운영합니다."


# --------------------------------------------------------------------------
# 나라장터 판정 글 — 계약 · 낙찰 방식 · 근거 금액 · 실적 조항 번호 · 사업 규모
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("award", "rate", "want"), [
    ("협상에의한계약-협상에 의한 낙찰자 결정", "80", "제안서 평가로 뽑음(기술 80 : 가격 20)"),
    ("적격심사제-시설분야용역 적격심사 추정가격 5억원 미만", "", "적격심사(수행 능력 · 가격 함께 심사)로 뽑음"),
    ("최저가낙찰제-최저가낙찰자", "", "가장 낮은 가격으로 뽑음"),
    ("처음 보는 방식", "", "처음 보는 방식"),  # 모르는 값은 지어내지 않는다
])
def test_낙찰_방식을_풀어_쓴다(award: str, rate: str, want: str) -> None:
    assert eligibility_engine._award_text(award, rate) == want


def test_공동수급_칸을_풀어_쓴다() -> None:
    assert eligibility_engine._joint_text("(없음)공동수급불허") == "다른 회사와 함께 참가할 수 없음(공동수급 불허)"
    assert eligibility_engine._joint_text("(전자)공동이행") == "다른 회사와 함께 참가할 수 있음(공동이행)"


def test_근거_줄_금액은_원_단위_글() -> None:
    line = eligibility_engine._fields(("asignBdgtAmt", "30000000"), ("presmptPrce", "27272727"))
    assert "30000000" not in line and "3,000만" in line


# --------------------------------------------------------------------------
# 기업마당 글 — R31-17 · R31-18 · 뜻 틀린 곳 · 신청 전 점검 한 줄
# --------------------------------------------------------------------------


def test_R31_17_모른다고_하고_직접_맡는_사업이_아니라고_단정하지_않는다() -> None:
    unknown = opportunity_priority._not_ours_reason(SupportKindResult(kinds=["unclassified"], basis="x"))
    assert "알 수 없어" in unknown and "아니라" not in unknown
    summary = opportunity_priority._not_ours_reason(
        SupportKindResult(kinds=["ai_education"], basis="AI 교육(「AI 교육」) — 요약에만", declared=False)
    )
    assert "직접 맡기 어려운" not in summary
    other = opportunity_priority._not_ours_reason(SupportKindResult(kinds=["robotics", "low_relevance"], basis="Physical AI·로봇(「로봇」)"))
    assert "보여" in other  # 단정하지 않는다


def _program(**fields):
    base = {"attachments": [], "apply_period_kind": "fixed", "apply_period_text": "2026. 9. 15. ~ 10. 6.", "title": "시험", "id": "bizinfo-T"}
    return SimpleNamespace(**(base | fields))


def test_뜻_틀린_곳_신청_마감은_신청_대상_아님과_다르다() -> None:
    from tests.test_support_application_v2 import program as real_program  # SupportProgram 을 그대로 만든다

    requirements = SimpleNamespace(of=lambda kind: [])
    closed = sas.company_meaning_line(real_program(), requirements, indirect=None, gate="FAIL", closed=True)
    blocked = sas.company_meaning_line(real_program(), requirements, indirect=None, gate="FAIL")
    ok = sas.company_meaning_line(real_program(), requirements, indirect=None, gate="PASS")
    assert closed is not None and closed.startswith("신청 종료")  # 33차 R32-09 — 화면 말 「신청 종료」 · 마감 두 번 안 씀
    assert "마감" not in closed
    assert blocked is not None and blocked.startswith("신청 대상 아님")
    assert ok is not None and ok.startswith("직접 신청") and "신청 주체" not in ok


def test_신청_전_점검_못_찾은_항목은_한_줄_찾지_않는_칸은_뺀다() -> None:
    items = {
        "eligibility": [
            SupportRequirementItem(key="org_type", label="조직 형태", value=None, status="unknown"),
            SupportRequirementItem(key="employees", label="고용 인원", value=None, status="unknown"),
            SupportRequirementItem(key="clause_role", label="회사가 맡을 자리", value=None, status="unknown"),  # 조항 항목 키 꼴
        ],
        "benefit": [
            SupportRequirementItem(key="scale", label="지원 규모", value=None, status="unknown"),
            SupportRequirementItem(key="self_burden", label="자부담", value=None, status="unknown"),
        ],
    }
    checks = sas.pre_submit_checks(items, _program(), document_read=True)
    missing = [c for c in checks if "못 찾은 항목" in c]
    assert missing == ["공고문에서 못 찾은 항목: 조직 형태 · 고용 인원 — 원문에서 확인하세요"]
    assert not any("찾지 못함" in c for c in checks)


def test_R31_20_창업_연차를_채우는_회사에_맞지_않는다고_하지_않는다() -> None:
    from tests.test_round32_rules import target

    result = target("창업 3년 이내 기업, 창업 7년 이내 기업 또는 사회적기업으로 진입하고자 하는 기업")  # 2021년 설립 → 5년 · 진입 꼴은 불가 갈래
    assert result.status == "CHECK" and "맞지 않습니다" not in result.reason and "창업 7년 이내 조건에는 맞습니다" in result.reason, result.reason


def test_R31_20_상한을_넘으면_그대로_맞지_않는다() -> None:
    from tests.test_round32_rules import target

    result = target("창업 3년 이내 기업 또는 사회적기업으로 진입하고자 하는 기업")
    assert result.status == "CHECK" and "창업 연차 조건은 맞지 않습니다" in result.reason, result.reason


def test_소재_가능_문장은_맞는다고_말한다() -> None:
    text = sas._location_pass_reason("광주광역시", "전남광주", "북구")
    # 43차 BIZ-16 — 뒤집힌 논리 「(「광주광역시」는 전남광주에 듭니다)」 대신 회사 주소가 옛 광주라서 맞는다
    assert text.endswith("회사 주소(북구)가 옛 광주광역시 지역이라 맞습니다.") and "요구하고 회사 소재는" not in text



@pytest.mark.parametrize(("switch_on", "want"), [(False, "AI 의미 매칭은 꺼 두었습니다"), (True, "AI 의미 매칭을 쓸 수 없었습니다")])
def test_뜻_틀린_곳_꺼_둔_AI_비교를_쓸_수_없었다고_하지_않는다(monkeypatch: pytest.MonkeyPatch, switch_on: bool, want: str) -> None:
    from app.services import bizinfo_service, semantic_matcher
    from tests.test_semantic_fit_wiring import make_program

    monkeypatch.setattr(semantic_matcher, "embed_cached", lambda _texts: None)
    monkeypatch.setattr(semantic_matcher, "semantic_fit_enabled", lambda: switch_on)
    fit = bizinfo_service.support_fit(make_program(), today=date(2026, 10, 7))
    assert want in fit.note


# --------------------------------------------------------------------------
# 마지막 검토 1 — 화면이 보낸 「새 말」 초안은 저장 원문으로 점검한다(해시 · 저장 열쇠 · 막음 · 승인 대조가 이어지게)
# --------------------------------------------------------------------------


def _section(*texts: str):
    from app.schemas.proposal import ProposalSection, ProposalSentence

    return ProposalSection(
        id="P", title="t",
        sentences=[ProposalSentence(id=f"S-{i}", text=t, grounding_type="RFP_GROUNDED") for i, t in enumerate(texts)],
    )


def test_새_말로_바꾼_저장_초안은_저장_원문으로_점검한다(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import auditor as auditor_api

    raw = ["교육을 20회 운영합니다. (RFP p.3 요구사항 준수)", "만족도 조사를 합니다."]
    monkeypatch.setattr(proposal_service, "load_section", lambda *_a, **_kw: _section(*raw))
    shown = "\n".join(wording.modernize_text(t) for t in raw)  # 화면이 받은 글 그대로 보낸다
    assert shown != "\n".join(raw)
    assert auditor_api._stored_text_for("p", shown, None) == "\n".join(raw)  # type: ignore[arg-type]
    pasted = "다른 사람이 붙여넣은 초안입니다."
    assert auditor_api._stored_text_for("p", pasted, None) == pasted  # type: ignore[arg-type]
