"""41차 2-C — 조항 · 근거 줄(R40-CLAUSE-A · B · C · D · E · 추출기 판 5). 호출 없음."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import eligibility_engine as ee
from app.services import qualification_clause_service as qc
from app.services import qualification_review_service as qr
from tests.test_round40_clauses import NOTICE_ID, _payload, _raw

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 1, 9, 0, tzinfo=KST)


@pytest.fixture(autouse=True)
def clause_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qc, "CLAUSE_DIR", tmp_path / "qualification_clauses")
    monkeypatch.setattr(qc, "PRIVATE_CLAUSE_DIR", tmp_path / "private_clauses")
    qc._MEMO.clear()
    yield
    qc._MEMO.clear()


def test_추출기_판은_7() -> None:
    assert qc.EXTRACTOR_VERSION == 10  # 10 = 44차 마지막 검토(기간 · 시작 및 마감 범위 · 칸 머리 · 24:00) · 9 = 44차 마감 읽기(R36-J-01 · J-02 · J-05) · 8 = 43차 마지막 검토(질의 기한) · 5 = 41차 2-C · 6 = 마지막 검토(지역 조항이 먼저) · 7 = 43차 공고문 일정표


# --------------------------------------------------------------------------
# R40-CLAUSE-C — 업종 코드 목록 줄에서 절이 끊기지 않고 · 코드 없는 업종 등록 문장은 업종 조항
# --------------------------------------------------------------------------

TABLE_NOTICE = [
    "바. 사전규격공개기간: 2026. 10. 03. ~ 2026. 10. 07.",
    "입찰참가자격",
    "가. 국가를 당사자로 하는 계약에 관한 법률 시행령 제12조에 의한 자격요건을 갖춘 업체",
    "나. 제안요청서에 의거 해당용역이 가능한 업체로, 기한 내 제안서를 제출한 업체",
    "다.「국가종합전자조달시스템 입찰참가자격등록규정」에 따라 제안서 제출 마감일까지",
    "나라장터(G2B)에 다음 업종 중 1개 이상으로 입찰참가자격을 등록한 업체",
    "1. 학술연구용역(업종코드 : 1169)",
    "2. 소프트웨어사업자(컴퓨터관련서비스사업)(업종코드 : 1468)",
    "라. 공동수급 및 하도급은 불허함",
    "입찰참가시",
    "제출서류(상세내용제안요청서참고)",
    "가. 입찰참가신청서, 입찰보증금 지급각서 각 1부",
    "낙찰자",
    "선정방법",
    "가. 제안서 평가는 기술능력평가(90%), 입찰가격평가(10%)의 합산점수로 평가함",
]


def test_업종_코드_목록_줄에서_절이_끊기지_않고_다음_절_머리에서_끝난다() -> None:
    lines = [(1, line) for line in TABLE_NOTICE]
    [(start, end, heading)] = qc.find_sections(lines)
    assert heading == "입찰참가자격"
    body = [text for _page, text in lines[start + 1:end]]
    assert "라. 공동수급 및 하도급은 불허함" in body  # 40차는 「1. 학술연구용역」에서 끊겨 빠졌다
    assert "입찰참가시" not in body and not any("제출서류" in t or "평가" in t for t in body)
    clauses = qc.split_clauses(lines[start + 1:end], heading)
    kinds = [qc.classify(c["text"]) for c in clauses]
    industry = next(c["text"] for c in clauses if qc.classify(c["text"]) == "industry")
    assert {"1169", "1468"} <= set(qc.industry_codes(industry))
    assert "consortium" in kinds


@pytest.mark.parametrize("text", [
    "나라장터(G2B)에 다음 업종 중 1개 이상으로 입찰참가자격을 등록한 업체",
    "아래 업종으로 입찰참가자격을 등록한 자",
])
def test_코드_없는_업종_등록_문장은_업종_조항이다(text: str) -> None:
    assert qc.classify(text) == "industry"


@pytest.mark.parametrize("text", [
    "공고일 현재 서울특별시에 본사를 두고 해당 업종으로 등록한 업체",
    "광주광역시에 소재하고 다음 업종 중 1개 이상으로 입찰참가자격을 등록한 업체",
])
def test_지역과_업종_등록이_한_문장이면_지역_조항이_먼저다(text: str) -> None:
    assert qc.classify(text) == "region"  # 마지막 검토 — 업종 조항으로 가면 다른 시 · 도 회사의 지역 「불가」가 사라졌다


def test_업종_등록_문장이라도_빼는_문장은_결격이다() -> None:
    assert qc.classify("다음 업종으로 등록한 자는 입찰에 참가할 수 없음") == "disqualification"


def test_코드_없는_업종_조항은_확인_필요이고_근거_줄을_단정하지_않는다() -> None:
    qc.save(_payload(("disqualification", "국가를 당사자로 하는 계약에 관한 법률 시행령 제12조의 자격을 갖춘 자"),
                     ("industry", "나라장터(G2B)에 다음 업종 중 1개 이상으로 입찰참가자격을 등록한 업체")), private=True)
    line, count = qc.evidence_line(qc.load(NOTICE_ID))
    assert line.startswith("근거: 공고문") and "다음 업종 중" in line and count == 2
    rules = ee.evaluate_notice_fields(_raw(), as_of=NOW, company=ee.CompanyFacts(), notice_id=NOTICE_ID)
    industry = next(r for r in rules if r.clause_id == "QC-02")
    assert industry.status == "CHECK" and industry.check_side == "company"


# --------------------------------------------------------------------------
# R40-CLAUSE-E — 여는 말 꼴
# --------------------------------------------------------------------------


@pytest.mark.parametrize("intro", [
    "입찰참가자격: 아래의 조건을 모두 만족하는 업체",
    "다음 각 호 중 어느 하나에 해당하는 자",
    "다음 각 호에 해당하는 업체이어야 합니다.",
    "본 제안 사업의 수행이 가능한 업체로서 다음 요건을 모두 갖춘 사업자이어야 한다.",
])
def test_여는_말_꼴_더함(intro: str) -> None:
    clauses = qc.split_clauses([(2, f"가. {intro}"), (2, "나. 소프트웨어사업자(업종코드 : 1468)로 등록한 자")])
    assert [c["text"] for c in clauses] == ["소프트웨어사업자(업종코드 : 1468)로 등록한 자"]


def test_요건이_든_긴_줄은_그대로_남긴다() -> None:
    text = "입찰참가자는 다음 요건을 모두 갖춘 중소기업으로서 중소기업확인서를 소지한 업체이어야 함"
    clauses = qc.split_clauses([(2, f"가. {text}")])
    assert [c["text"] for c in clauses] == [text]


# --------------------------------------------------------------------------
# R40-CLAUSE-A · B — 확인 기록: 가장 최근 · 유령 「다시 확인」 없음 · 옛 번호 저장이 살아 있는 확인을 지우지 않음
# --------------------------------------------------------------------------

B_TEXT = "부정당업자로 입찰참가자격 제한을 받고 있지 아니한 자"
C_TEXT = "조세 체납 사실이 없는 자"
D_TEXT = "국가를 당사자로 하는 계약에 관한 법률 시행령 제12조의 자격을 갖춘 자"


def _fact(clause_id: str, state: str, at: str, text: str) -> tuple:
    return (NOTICE_ID, clause_id, state, "메모", "김담당", at, qr.clause_hash(text))


def test_원문_해시가_같은_확인이_여럿이면_가장_최근() -> None:
    reviews = (_fact("QC-02", "met", "2026-09-01T00:00:00+00:00", B_TEXT),  # 9월 「충족」(옛 번호)
               _fact("QC-01", "unmet", "2026-10-01T00:00:00+00:00", B_TEXT))  # 10월 「미충족」(그때 번호)
    qc.save(_payload(("disqualification", D_TEXT), ("disqualification", B_TEXT)), private=True)  # 지금 B 는 QC-02
    rules = ee.evaluate_notice_fields(_raw(), as_of=NOW, company=ee.CompanyFacts(clause_reviews=reviews), notice_id=NOTICE_ID)
    by = {r.clause_id: (r.status, r.review_state) for r in rules if r.clause_id}
    assert by["QC-02"] == ("FAIL", "unmet")  # 40차는 id 가 맞는 옛 「충족」이 이겼다
    assert by["QC-01"][1] is None  # 그 번호의 옛 확인(B)은 지금 QC-02 에 붙었다 — 유령 「다시 확인」 줄을 만들지 않는다
    assert ee.overall_verdict(rules) == "FAIL"


def test_원문이_사라진_옛_번호_확인은_다시_확인으로_남는다() -> None:
    reviews = (_fact("QC-01", "met", "2026-09-01T00:00:00+00:00", "지금 공고문에 없는 옛 조항"),)
    qc.save(_payload(("disqualification", D_TEXT)), private=True)
    rules = ee.evaluate_notice_fields(_raw(), as_of=NOW, company=ee.CompanyFacts(clause_reviews=reviews), notice_id=NOTICE_ID)
    assert next(r for r in rules if r.clause_id == "QC-01").review_state == "stale"


def test_옛_번호_줄을_저장해도_다른_원문의_확인은_지워지지_않는다(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(qr, "review_path", lambda procurement_id, context: tmp_path / f"{procurement_id}.review.json")
    qr.save(NOTICE_ID, "QC-03", state="unmet", note="제재 이력", decided_by="김담당", clause_text=C_TEXT, context=None)
    # 번호가 밀려 QC-03 은 이제 다른 조항(D) — 그 줄을 「보류」(충족 · 미충족이 아닌 상태)로 저장
    qr.save(NOTICE_ID, "QC-03", state=next(s for s in qr.STATES if s not in ("met", "unmet")), note=None, decided_by="김담당", clause_text=D_TEXT, context=None)
    saved = qr.load(NOTICE_ID, None)
    assert saved["QC-03"]["clause_hash"] == qr.clause_hash(D_TEXT)
    moved = saved[f"QC-03@{qr.clause_hash(C_TEXT)}"]
    assert moved["state"] == "unmet"  # C 의 「미충족」은 해시 열쇠로 남아 판정이 원문으로 잇는다


# --------------------------------------------------------------------------
# R40-CLAUSE-D — 직접 넣은 공고문에도 추출기 판
# --------------------------------------------------------------------------


def test_직접_넣은_공고문_조항_파일에_추출기_판을_적는다(tmp_path: Path) -> None:
    from app.services import manual_notice_service as manual
    from tests.test_round38_manual import NOW as MNOW, ORG as MORG, _docx, _input

    notice = manual.create(MORG, _input(), now=MNOW).notice
    manual.attach_document(MORG, notice.id, file_name="공고문.docx", payload=_docx(tmp_path / "공고문.docx"), now=MNOW)
    stored = qc.load(notice.id)
    assert stored["extractor_version"] == qc.EXTRACTOR_VERSION  # 40차는 칸이 없어 늘 「옛 판」으로 읽혔다
    assert qc.evidence_line(stored)[0] != qc.NO_DECISION_UNSURE
