"""40차 §3-F — 조항 · 근거 줄(CLAUSE-02 · 03 · 05 · 06 · 07 · 08 · 추출기 판 3). 호출 없음."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import eligibility_engine as ee
from app.services import qualification_clause_service as qc
from app.services import qualification_review_service as qr

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 1, 9, 0, tzinfo=KST)
NOTICE_ID = "g2b-R26QUAL0000040-000"


@pytest.fixture(autouse=True)
def clause_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qc, "CLAUSE_DIR", tmp_path / "qualification_clauses")
    monkeypatch.setattr(qc, "PRIVATE_CLAUSE_DIR", tmp_path / "private_clauses")
    qc._MEMO.clear()
    yield
    qc._MEMO.clear()


def _body(*lines: str) -> list[tuple[int, str]]:
    return [(3, line) for line in lines]


def _payload(*kinds_texts: tuple[str, str], version: int | None = None, status: str = "ok") -> dict:
    return {"notice_id": NOTICE_ID, "status": status, "page_is_approximate": False,
            "extractor_version": qc.EXTRACTOR_VERSION if version is None else version,
            "document": {"name": "입찰공고문.pdf", "index": 0, "format": "pdf", "hash": "x"},
            "section": {"heading": "3. 입찰참가자격", "page_from": 2, "page_to": 2}, "second_source": None, "note": None,
            "clauses": [{"id": f"QC-{n:02d}", "kind": kind, "text": text, "page": 2} for n, (kind, text) in enumerate(kinds_texts, start=1)]}


def _raw() -> dict:
    return {"source": "g2b", "item": {
        "bidNtceNo": "R26QUAL0000040", "cntrctCnclsMthdNm": "일반경쟁", "bidQlfctRgstDt": "2026-09-20 18:00",
        "bidClseDt": "2026-09-21 10:00:00", "indstrytyLmtYn": "N", "bidPrtcptLmtYn": "N",
        "cmmnSpldmdCorpRgnLmtYn": "N", "jntcontrctDutyRgnNm1": "", "rgnLmtBidLocplcJdgmBssNm": "", "asignBdgtAmt": "55000000",
    }}


# --------------------------------------------------------------------------
# CLAUSE-05 — 여는 말 · 절 머리글 거르기
# --------------------------------------------------------------------------


@pytest.mark.parametrize("intro", [
    "입찰참가자격 공지사항",
    "2. 입찰참가자격",
    "다음 중 어느 하나에 해당하는 자는 입찰참가자격이 없음",
    "(모든 조건을 충족해야 참가 가능함)",
    "아래의 참가자격을 모두 갖춘 자이어야 함.",
    "<다음 각 호의 요건을 모두 갖춘 업체>",
    "입찰에 참가하고자 하는 자는 다음 요건을 모두 충족하여야 한다.",
    "아래 자격을 모두 갖춘 자",
])
def test_여는_말과_머리글_낱말은_조항이_아니다(intro: str) -> None:
    clauses = qc.split_clauses(_body(f"○ {intro}", "○ 최근 3년 이내 유사 사업 실적 1건 이상 보유한 자"))
    assert [c["text"] for c in clauses] == ["최근 3년 이내 유사 사업 실적 1건 이상 보유한 자"]


@pytest.mark.parametrize("clause", [
    "다음 업종 중 하나를 등록한 자: 소프트웨어사업자(1468)",
    "다음 요건을 모두 갖춘 소프트웨어사업자",  # 업종 이름이 있으면 거르지 않는다
    "(공동수급 불허)",
    "제안서는 제출기한 내에 직접 방문하여 제출하여야 함",
    "중소기업기본법에 따른 중소기업으로서 확인서를 소지한 자",
    "입찰참가자는 다음 요건을 모두 갖춘 중소기업이어야 함",
    "참가자격: 아래를 모두 갖춘 소상공인",
    "중소기업으로서 다음 중 어느 하나에 해당하면 참가할 수 없음",
])
def test_짧아도_요건이_있는_줄은_남긴다(clause: str) -> None:
    """40차 마지막 검토 — 업종 이름이 없어도 기업 유형 · 결격처럼 요건이 든 짧은 줄은 여는 말 꼴이어도 남긴다."""
    assert [c["text"] for c in qc.split_clauses(_body(f"○ {clause}"))] == [clause]


def test_절_머리글과_같은_줄은_뺀다() -> None:
    # 쪽 머리에 되풀이된 머리글(1717796 「2. 입찰참가자격」 꼴) — 여는 말 꼴이 아니어도 머리글과 같으면 뺀다(로마 숫자 · 번호 · 띄어쓰기 무시)
    body = _body("□ 입찰참가자격 및 제출 서류", "○ 「소프트웨어 진흥법」에 따른 소프트웨어사업자(1468)로 등록한 자")
    clauses = qc.split_clauses(body, heading="Ⅲ. 입찰참가자격 및 제출서류")
    assert len(clauses) == 1 and clauses[0]["text"].startswith("「소프트웨어 진흥법」에")
    assert len(qc.split_clauses(body)) == 2


# --------------------------------------------------------------------------
# CLAUSE-02 — 코드 없는 업종 이름 · 단정하지 않는 근거 줄
# --------------------------------------------------------------------------


def test_코드_없는_업종_이름도_업종_조항이다() -> None:
    assert qc.classify("국제공인교정기관 및 교육서비스업으로 입찰참가자격을 등록한 사업자") == "industry"


def test_판정_조항이_없을_때_믿기_어려우면_원문_확인() -> None:
    plain = (("disqualification", "부정당업자 제재 등 결격사유가 없는 자"), ("other", "세부 입찰일정은 나라장터 공고 화면을 따릅니다"))
    assert qc.evidence_line(_payload(*plain)) == (qc.NO_DECISION_CLAUSE, 2)
    # 공고 필드가 업종 · 지역을 요구한다
    assert qc.evidence_line(_payload(*plain), field_requires=True) == (qc.NO_DECISION_UNSURE, 2)
    # 기타뿐 · 하나뿐 · 옛 추출기 판
    assert qc.evidence_line(_payload(("other", "참가자격 및 평가내용"), ("other", "제안서 제출 완료 후 가격입찰서 제출")))[0] == qc.NO_DECISION_UNSURE
    assert qc.evidence_line(_payload(("disqualification", "부정당업자 제재 등 결격사유가 없는 자")))[0] == qc.NO_DECISION_UNSURE
    assert qc.evidence_line(_payload(*plain, version=2))[0] == qc.NO_DECISION_UNSURE
    assert qc.NO_DECISION_UNSURE == "공고문 읽음 · 업종 · 지역 제한 조항을 못 찾음 — 원문 확인"
    # P1-02 4장 — 「결정 조항 없음」은 조항 n개가 있다는 상세와 반대로 읽혔다: 없는 것은 업종 · 지역 제한 조항이다
    assert qc.NO_DECISION_CLAUSE.startswith("공고문 읽음 · 업종 · 지역 제한 조항 없음") and "결정 조항 없음" not in qc.NO_DECISION_CLAUSE


def test_공고_필드가_요건을_말하는지() -> None:
    rule = lambda rid, status, source="": SimpleNamespace(rule_id=rid, status=status, source=source)  # noqa: E731
    assert qc.field_requires([rule("ELIG-INDUSTRY", "PASS", "나라장터 기본정보 — 요구 업종: 1468 소프트웨어사업자")]) is True
    assert qc.field_requires([rule("ELIG-INDUSTRY", "FAIL")]) is True
    assert qc.field_requires([rule("ELIG-INDUSTRY", "CHECK", "면허제한 자격 정보 미수집")]) is True
    assert qc.field_requires([rule("ELIG-REGION", "CHECK")]) is True
    assert qc.field_requires([rule("ELIG-INDUSTRY", "PASS", "나라장터 기본정보 — 요구 업종 없음"), rule("ELIG-REGION", "PASS"),
                              rule("ELIG-DEADLINE", "FAIL")]) is False


# --------------------------------------------------------------------------
# CLAUSE-08 — 못 받은 결과로 읽은 파일을 덮지 않는다
# --------------------------------------------------------------------------


@pytest.mark.parametrize("private", [True, False])
def test_못_받은_결과는_읽은_파일을_덮지_않는다(private: bool) -> None:
    qc.save(_payload(("industry", "소프트웨어사업자(1468)로 등록한 자")), private=private)
    qc.save({**_payload(status="not_fetched"), "note": "입찰공고문을 아직 내려받지 않았습니다"}, private=private)
    qc.save({**_payload(status="error"), "note": "여는 중 실패"}, private=private)
    assert qc.load(NOTICE_ID)["status"] == "ok"
    # 읽은 결과끼리는 새것으로 · 못 받은 것끼리도 새것으로
    qc.save(_payload(("industry", "엔지니어링사업자로 등록한 자")), private=private)
    assert qc.load(NOTICE_ID)["clauses"][0]["text"] == "엔지니어링사업자로 등록한 자"


def test_못_받은_파일은_다시_못_받아도_새로_쓴다() -> None:
    qc.save({**_payload(status="not_fetched"), "note": "첫 실패"}, private=True)
    qc.save({**_payload(status="error"), "note": "둘째 실패"}, private=True)
    assert qc.load(NOTICE_ID)["note"] == "둘째 실패"


# --------------------------------------------------------------------------
# CLAUSE-06 — 원문 해시가 맞는 확인이 먼저
# --------------------------------------------------------------------------


def test_다시_뽑아_번호가_밀려도_원문이_같은_확인을_잇는다() -> None:
    old_b = "부정당업자로 입찰참가자격 제한을 받고 있지 아니한 자"
    old_c = "조세 체납 사실이 없는 자"
    new_a = "국가를 당사자로 하는 계약에 관한 법률 시행령 제12조의 자격을 갖춘 자"
    # 판 1 때 확인: QC-03 = B(미충족) · QC-04 = C(충족). 판 3 은 앞에 A 가 끼어 B 가 QC-04 · C 가 QC-05 가 됐다.
    reviews = (
        (NOTICE_ID, "QC-03", "unmet", "제재 이력 있음", "김담당", "2026-09-23T01:00:00+00:00", qr.clause_hash(old_b)),
        (NOTICE_ID, "QC-04", "met", "완납 증명", "김담당", "2026-09-23T01:00:00+00:00", qr.clause_hash(old_c)),
    )
    qc.save(_payload(("disqualification", "입찰 공고일 현재 등록된 자"), ("disqualification", "결격 없는 자"),
                     ("disqualification", new_a), ("disqualification", old_b), ("disqualification", old_c)))
    rules = ee.evaluate_notice_fields(_raw(), as_of=NOW, company=ee.CompanyFacts(clause_reviews=reviews), notice_id=NOTICE_ID)
    by = {r.clause_id: (r.status, r.method, r.review_state) for r in rules if r.clause_id}
    assert by["QC-04"] == ("FAIL", "HUMAN", "unmet")  # 예전에는 id 로 C 의 확인을 집어 stale
    assert by["QC-05"] == ("PASS", "HUMAN", "met")
    assert by["QC-03"][2] is None  # 그 번호의 옛 확인(B)은 지금 QC-04 에 붙었다 — 41차 R40-CLAUSE-B 유령 「다시 확인」 줄 없음
    assert ee.overall_verdict(rules) == "FAIL"


# --------------------------------------------------------------------------
# CLAUSE-07 — 같은 절의 「단, … 예외 … 허용」
# --------------------------------------------------------------------------

SMALL_ONLY = "3.3. 「중소기업기본법」 제2조에 따른 소기업 또는 「소상공인 보호 및 지원에 관한 법률」에 따른 소상공인으로서 중소기업(소상공인)확인서를 소지한 자"
EXCEPTION = "단, 이 입찰은 중소기업자 우선조달계약 예외를 적용하여 중소기업이 아닌 법인·기관·단체(비영리법인 포함) 등의 입찰참가를 허용함"


def _mid() -> ee.CompanyFacts:
    return ee.CompanyFacts(sme_held=True, sme_grade="중기업", sme_valid_until=date(2027, 3, 31))


def test_소기업_전용_조항은_중기업에_불가() -> None:
    qc.save(_payload(("company_type", SMALL_ONLY)))
    rules = ee.evaluate_notice_fields(_raw(), as_of=NOW, company=_mid(), notice_id=NOTICE_ID)
    assert next(r for r in rules if r.clause_id == "QC-01").status == "FAIL"


def test_같은_절에_예외_허용_조항이_있으면_확인_필요로_낮춘다() -> None:
    qc.save(_payload(("company_type", SMALL_ONLY), ("other", EXCEPTION)))
    rules = ee.evaluate_notice_fields(_raw(), as_of=NOW, company=_mid(), notice_id=NOTICE_ID)
    row = next(r for r in rules if r.clause_id == "QC-01")
    assert row.status == "CHECK" and row.check_side == "notice" and "(QC-02)" in row.reason
    assert qc.classify(EXCEPTION) == "other"
    assert "FAIL" not in {r.status for r in rules if r.clause_id}


def test_판단_같은_낱말의_단은_예외_표시가_아니다() -> None:
    assert ee._TYPE_EXCEPTION.search(EXCEPTION)
    assert not ee._TYPE_EXCEPTION.search("발주기관 판단, 예외 없이 입찰참가를 허용하지 않음 — 소기업만")


# --------------------------------------------------------------------------
# CLAUSE-03 — 다시 뽑기는 내려받기와 따로
# --------------------------------------------------------------------------


def test_다시_뽑기는_비추천도_넣고_상한은_다시_뽑은_것만_센다(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.services import attachment_service
    from tests.test_round38_strength import _load_collect_daily

    daily = _load_collect_daily()
    stored = {
        "g2b-A": {"status": "ok", "extractor_version": 2},           # 비추천 — 넣는다
        "g2b-B": {"status": "ok", "extractor_version": 2},           # 마감 — 뺀다
        "g2b-C": {"status": "not_fetched", "extractor_version": 2},  # 받다 실패 — 내려받기 몫
        "g2b-D": {"status": "ok", "extractor_version": qc.EXTRACTOR_VERSION},  # 이미 새 판
        "g2b-E": {"status": "no_section"},                            # 판 없음(0) — 넣는다
        "g2b-F": {"status": "ok", "extractor_version": 1},
        "g2b-G": {"status": "ok", "extractor_version": 1},           # 첨부 캐시 없음 — 못 뽑음(세지 않음)
    }
    monkeypatch.setattr(qc, "load", lambda nid: stored.get(nid))
    monkeypatch.setattr(attachment_service, "pick_notice_document", lambda atts: 0)
    monkeypatch.setattr(attachment_service, "cached_attachment", lambda nid, i, name: None if nid == "g2b-G" else tmp_path / "x.pdf")
    saved: list[str] = []
    monkeypatch.setattr(qc, "build_payload", lambda nid, atts, **_kw: {"notice_id": nid, "status": "ok"})
    monkeypatch.setattr(qc, "save", lambda payload, private=False: saved.append(payload["notice_id"]) or tmp_path)
    items = [SimpleNamespace(id=nid, closed=(nid == "g2b-B"), relevance_note=("관련 낮음" if nid == "g2b-A" else None))
             for nid in ("g2b-A", "g2b-B", "g2b-C", "g2b-D", "g2b-G", "g2b-E", "g2b-F")]
    raw = {item.id: SimpleNamespace(id=item.id, raw_data={"attachments": [{"name": "공고문.pdf"}]}) for item in items}
    assert daily.reextract_stale(items, raw) == 3 and saved == ["g2b-A", "g2b-E", "g2b-F"]
    saved.clear()
    assert daily.reextract_stale(items, raw, limit=2) == 2 and saved == ["g2b-A", "g2b-E"]


def test_추출기_판은_4_이상() -> None:
    assert qc.EXTRACTOR_VERSION >= 4  # 41차 판 5 — test_round41_clauses



def test_Git_밖이_비어도_공개_폴더의_읽은_파일은_가리지_않는다() -> None:
    """40차 마지막 검토 — 공개 폴더가 「읽음」인데 다시 뽑다 실패하면 Git 밖에 「못 받음」이 써져 먼저 읽혔다."""
    qc.save(_payload(("industry", "소프트웨어사업자(1468)로 등록한 자")))  # 공개 폴더
    qc.save({**_payload(status="error"), "note": "압축 검사"}, private=True)
    assert not qc.clause_path(NOTICE_ID, private=True).exists()
    assert qc.load(NOTICE_ID)["status"] == "ok"


def test_다시_뽑다_실패한_것은_쓰지도_세지도_않는다(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.services import attachment_service
    from tests.test_round38_strength import _load_collect_daily

    daily = _load_collect_daily()
    monkeypatch.setattr(qc, "load", lambda nid: {"status": "ok", "extractor_version": 1})
    monkeypatch.setattr(attachment_service, "pick_notice_document", lambda atts: 0)
    monkeypatch.setattr(attachment_service, "cached_attachment", lambda nid, i, name: tmp_path / "x.pdf")
    monkeypatch.setattr(qc, "build_payload", lambda nid, atts, **_kw: {"notice_id": nid, "status": "error" if nid == "g2b-BAD" else "ok"})
    saved: list[str] = []
    monkeypatch.setattr(qc, "save", lambda payload, private=False: saved.append(payload["notice_id"]) or tmp_path)
    items = [SimpleNamespace(id=nid, closed=False, relevance_note=None) for nid in ("g2b-BAD", "g2b-OK")]
    raw = {item.id: SimpleNamespace(id=item.id, raw_data={"attachments": [{"name": "공고문.pdf"}]}) for item in items}
    assert daily.reextract_stale(items, raw, limit=1) == 1 and saved == ["g2b-OK"]
