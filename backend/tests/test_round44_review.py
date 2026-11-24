"""44차 §4 마지막 변경 검토에서 확인된 결함(실무 렌즈 · 반박 검증 뒤 남은 것). 호출 없음.

- 마감 읽기(추출기 판 10): 「시작 · 개시 및 마감: A ~ B」의 끝 · 「부터 N일간 · N일 이내」는 기간 · 표 머리줄 칸은 갈래 낱말로 ·
  평가 · 개찰 날짜에 칸 이름을 붙이지 않음 · 「24:00까지」는 그날 끝.
- 「입찰참가자격을 등록한 자」도 회사 단위 확인(등록)이 통과시킨다.
- 업종 없음 · 파트너형에는 「규모 큼(본업에 남김)」을 붙이지 않는다.
- 「AI 보조 쉼 — Claude 로그인 필요」는 로그인 실패일 때만.
- 직접 넣은 입찰 · 수행 공고가 「불가」면 「참여」를 받지 않는다(수혜는 사람이 정함).
- 공고문을 읽는 동안 들어온 「원문 확인함」을 덮지 않는다.
- 협약 기간 「~ 12. 10.」(끝에 연도 생략)를 2012년으로 읽지 않는다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.schemas.business_opportunity import UnifiedOpportunity
from app.schemas.decision import DecisionRequest
from app.schemas.manual_notice import ManualNoticeInput
from app.schemas.organization import AnalysisContext
from app.services import auto_collect, decision_service, eligibility_engine, manual_notice_service, notice_schedule, plan_form_service
from app.services import practical_priority as practical
from app.services import qualification_clause_service as qc

KST = timezone(timedelta(hours=9))
PUBLISHED = datetime(2026, 9, 28, tzinfo=KST)
ORG = get_settings().default_organization_id
CTX = AnalysisContext(organization_id=ORG, evidence_scope="internal")


def _items(lines: list[tuple[int, str]]) -> list[tuple[str, str]]:
    out = notice_schedule.extract(lines, year_hint=2026, not_before=PUBLISHED)
    return [(i["kind"], i["at"][:16]) for i in out["items"]]


@pytest.mark.parametrize(("lines", "want"), [
    ([(1, "참가신청서 접수 시작 및 마감: 2026. 10. 20.(화) 09:00 ~ 2026. 10. 24.(토) 18:00")], [("application", "2026-10-24T18:00")]),
    ([(1, "입찰서 제출 개시 및 마감일시 : 2026. 11. 12.(목) 10:00 ~ 2026. 11. 17.(화) 10:00")], [("submission", "2026-11-17T10:00")]),
    ([(1, "□ 참가신청서 접수기간(개시~마감): 2026. 10. 26.(월) 09:00 ~ 2026. 10. 28.(수) 18:00")], [("application", "2026-10-28T18:00")]),
    # 시작일시 줄은 그대로 버린다(R36-J-01)
    ([(1, "○ 제출 시작일시: 2026/11/12(목) 10:00"), (1, "○ 제출 마감일시: 2026/11/17(화) 10:00")], [("submission", "2026-11-17T10:00")]),
])
def test_시작_및_마감_범위는_끝_날짜가_마감(lines, want) -> None:
    assert _items(lines) == want


@pytest.mark.parametrize("line", [
    "가. 접수기간 : 2026. 10. 26.(월)부터 5일간(09:00~18:00)",
    "제출기한: 2026. 10. 20.(화) ~ 7일 이내",
    "제안서 접수기간 : 2026. 10. 13.(화)부터 15일간",
])
def test_부터_N일간_N일_이내는_기간이라_마감을_지어내지_않는다(line: str) -> None:
    assert _items([(1, line)]) == []


def test_날만_적힌_범위_끝은_그대로_읽는다() -> None:
    assert _items([(1, "제안서 접수기간 : 2026. 10. 13.(화)부터 15일(목)까지")]) == [("submission", "2026-10-15T23:59")]


@pytest.mark.parametrize(("label", "row", "want"), [
    ("제안서 제출마감", "2026. 10. 30.(금) 10:00 / 평가 2026. 11. 3.(화) 14:00", [("submission", "2026-10-30T10:00")]),
    ("입찰 마감일시", "2026. 10. 30.(금) 10:00 (개찰: 2026. 10. 30.(금) 11:00)", [("submission", "2026-10-30T10:00")]),
    ("입찰서 제출 마감일시", "2026. 10. 30.(금) 10:00 (개찰: 2026. 10. 30.(금) 11:00)", [("submission", "2026-10-30T10:00")]),
    ("참가신청 마감 현장설명 입찰등록 마감", "2026. 10. 30.(금) 2026. 11. 2.(월) 2026. 11. 10.(화)",
     [("application", "2026-10-30T23:59"), ("briefing", "2026-11-02T23:59"), ("registration", "2026-11-10T23:59")]),
])
def test_표_머리줄_칸은_갈래_낱말로_나누고_평가_개찰에는_칸_이름을_붙이지_않는다(label: str, row: str, want) -> None:
    assert _items([(1, label), (1, row)]) == want


def test_요일_괄호_짧은_낱말을_넘는_범위와_기간_이름표() -> None:
    # 함평(1758810) — 머리말 아래 「공고기간 : A (화요일) ∼ B」는 마감이 아니다(칸 짝짓기는 날짜로 시작하는 표 행만)
    assert _items([(2, "4. 입찰참가 등록 및 제안서 제출 : 서면 제출"),
                   (2, "가. 공고기간 : 2026. 10. 6. (화요일) ∼ 2026. 10. 26. (월요일) [21일간]")]) == []
    # 고려대(1764242) — 「4. 제안서 제출 및 접수 / 가. 기 간 : 10. 15.(목) 공고 시 ~ 10. 26.(월) 17:00」의 끝이 제출 마감
    assert _items([(4, "4. 제안서 제출 및 접수"), (4, "가. 기    간 : 2026. 10. 15.(목) 공고 시 ~ 10. 26.(월) 17:00"),
                   (4, "나. 접    수 : 이메일 또는 우편 제출")]) == [("submission", "2026-10-26T17:00")]
    # 사업 기간은 머리말이 「제출」이어도 마감이 아니다
    assert _items([(4, "4. 제안서 제출"), (4, "가. 사업 기간 : 2026. 11. 1.(일) ~ 2026. 12. 20.(일)")]) == []


def test_24시까지는_그날_끝() -> None:
    assert _items([(1, "참가신청서 이메일 제출: 2026. 10. 28.(수) 24:00까지")]) == [("application", "2026-10-28T23:59")]


def test_추출기_판은_10() -> None:
    assert qc.EXTRACTOR_VERSION == 10


def test_입찰참가자격을_등록한_자도_회사_단위_확인으로_통과() -> None:
    company = eligibility_engine.CompanyFacts(
        location_region="전남광주", from_real_company=True,
        company_checks=tuple((k, "2026-10-20", "2027-10-19", "대표") for k in eligibility_engine.REGISTRATION_CHECK_KEYS),
    )
    for text in ("국가종합전자조달시스템 입찰참가자격 등록규정에 따라 나라장터(G2B)에 입찰참가자격을 등록한 자",
                 "조달청에 입찰참가자격 등록을 필한 자"):
        clause = eligibility_engine._Clause(id="QC-01", kind="disqualification", text=text, page=1, origin="입찰공고문", approx=False)
        assert eligibility_engine._judge_disqualification(clause, company, date(2026, 10, 24)).status == "PASS", text
    hard = eligibility_engine._Clause(id="QC-02", kind="disqualification", text="입찰참가자격을 등록한 자로서 부도 · 회생 절차 중이 아닌 자",
                                      page=1, origin="입찰공고문", approx=False)
    assert eligibility_engine._judge_disqualification(hard, company, date(2026, 10, 24)).status == "CHECK"


def _item(**kw) -> UnifiedOpportunity:
    base = dict(id="g2b-R26BK00000001-000", source_type="g2b", title="AI 활용 교육 운영", organization="광주광역시",
                budget=300_000_000, fit_type="A1")
    base.update(kw)
    return UnifiedOpportunity.model_construct(**base)


def test_업종_없음_파트너형에는_규모_큼을_붙이지_않는다() -> None:
    ceiling = 200_000_000
    assert practical.scale_tag(_item(), ceiling) is not None
    assert practical.scale_tag(_item(industry_partner="allowed"), ceiling) is None


@pytest.mark.parametrize(("reason", "resting"), [
    ("LLMUnavailableError: Claude CLI 가 아직 로그인되어 있지 않습니다 — 서버에서 claude 를 한 번 실행해 로그인하세요", True),
    ("LLMUnavailableError: Claude 로그인이 끝났습니다 — 관리자에게 Claude 다시 로그인을 부탁하세요", True),
    ("LLMUnavailableError: Claude CLI 가 240초 안에 답하지 않았습니다", False),
    ("LLMUnavailableError: Claude CLI 실패(exit 1) — 알 수 없는 오류", False),
])
def test_AI_보조_쉼은_로그인_실패일_때만(reason: str, resting: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    monkeypatch.setenv("COLLECT_SCHEDULER", "cron")
    monkeypatch.setattr(auto_collect, "task_state", lambda: "Ready")
    at = datetime(2026, 10, 24, 7, 31, tzinfo=KST)
    auto_collect.LOG_FILE.write_text(json.dumps({"시각": at.astimezone(timezone.utc).isoformat(), "실행": True, "결과": [
        {"출처": "나라장터", "결과": "g2b"}, {"출처": "기업마당", "결과": "bizinfo"},
        {"출처": "AI 적합도", "결과": None, "실패_이유": reason}]}, ensure_ascii=False) + "\n", encoding="utf-8")
    state = auto_collect.collect_state(datetime(2026, 10, 24, 10, tzinfo=KST))
    assert state["text"].endswith(auto_collect.AI_RESTING_NOTE) is resting


def _manual(**kw) -> ManualNoticeInput:
    base = dict(url="https://www.univ.ac.kr/notice/r44-review", title="AI 교육 운영 위탁", agency="시험대학",
                deadline=datetime(2026, 10, 1, 16, 0, tzinfo=KST), recruit="bid", methods=["이메일"])
    base.update(kw)
    return ManualNoticeInput(**base)


def test_직접_넣은_입찰이_불가면_참여를_받지_않는다_수혜는_사람이_정함() -> None:
    bid = manual_notice_service.create(ORG, _manual()).notice  # 마감 10/1 — 지남(불가)
    assert manual_notice_service.gate_now(ORG, bid.id) == "FAIL"
    with pytest.raises(decision_service.DecisionIneligibleError):
        decision_service.save_decision(bid.id, DecisionRequest(status="GO", reasons=["참여"], decided_by="김담당"), context=CTX)
    assert decision_service.save_decision(bid.id, DecisionRequest(status="NO_GO", reasons=["마감 지남"], decided_by="김담당"), context=CTX).status == "NO_GO"
    benefit = manual_notice_service.create(ORG, _manual(url="https://www.univ.ac.kr/notice/r44-review-b", recruit="benefit")).notice
    assert decision_service.save_decision(benefit.id, DecisionRequest(status="GO", reasons=["신청"], decided_by="김담당"), context=CTX).status == "GO"


def test_공고문을_읽는_동안_들어온_원문_확인함을_덮지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    notice = manual_notice_service.create(ORG, _manual(url="https://www.univ.ac.kr/notice/r44-review-c",
                                                       deadline=datetime(2026, 12, 30, 16, 0, tzinfo=KST))).notice

    def slow_extract(_path, *, file_name):  # 읽는 동안 다른 사람이 「원문 확인함 — 가능으로」를 누른다
        manual_notice_service.set_human_pass(ORG, notice.id, by="김담당", reason="원문 확인", gate_now="CHECK")
        return {"status": "ok", "format": "pdf", "clauses": [], "file": file_name}

    monkeypatch.setattr(qc, "extract_clauses", slow_extract)
    saved = manual_notice_service.attach_document(ORG, notice.id, file_name="공고문.pdf", payload=b"%PDF-1.4 test")
    assert saved.document is not None and saved.human_pass is not None and saved.human_pass.by == "김담당"


@pytest.mark.parametrize(("text", "end"), [
    ("사업기간 : 2026. 9. 1. ~ 12. 10.", "2026-12"),
    ("지원기간: 2026.10.15.~12.12.", "2026-12"),
    ("사업기간 : 2026. 11. 1. ~ 2. 28.", "2027-02"),
    ("사업기간 : 2026. 11. 1. ~ 2027. 3. 31.", "2027-03"),
    ("수행기간: 2026. 11. ~ '27. 2.", "2027-02"),
])
def test_협약_기간_끝에_연도가_없으면_시작_연도(text: str, end: str) -> None:
    assert plan_form_service._agreement_period(text)["end"] == end
