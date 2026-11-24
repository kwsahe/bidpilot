"""참가자격 조항마다 담당자 확인 (20차 §4-C · ISSUE-139 · ISSUE-140).

담당자 말: 「자격요건 … 하나하나씩 체크 및 확인할 수 있는 기능도 필요하고.」
「안 맞으면 입찰 신청 자체를 못 하니까」 — 자격 종합이 불가면 「참여」를 저장하지 않는다.

재는 것:
1. 충족 → 그 줄이 가능(HUMAN)이 되고 근거에 「담당자 확인 {이름} {시각}: {메모}」. 미충족 → 불가(HUMAN).
2. 충족·미충족은 메모가 있어야 저장된다(빈 메모 422). 보류는 메모 없이 된다.
3. 확인한 뒤 조항 원문이 바뀌면 `stale` — 판정은 규칙으로 돌아간다.
4. 목록과 상세가 같은 확인을 본다(회사 쪽 사실 한 곳에서 읽는다).
5. 자격 종합이 불가면 「참여」 422(조항 원문 앞 60자), 보류는 된다.
6. 활동 기록에 누가·어느 조항·무엇으로 — 메모 본문은 남기지 않는다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.procurement import ProcurementNotice
from app.services import action_service, audit_log_service, critical_condition_service as ccs, decision_service
from app.services import eligibility_engine as ee
from app.services import procurement_service, qualification_clause_service as qc
from app.services import qualification_review_service as qr
from app.services.opportunity_filter import CandidateMatch

client = TestClient(app)
SYNTHETIC = "synthetic-rfp-0001"
KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 1, 9, 0, tzinfo=KST)
NOTICE_ID = "g2b-R26QUAL0000002-000"


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ccs, "CONDITION_DIR", tmp_path / "conditions")
    monkeypatch.setattr(action_service, "ACTION_DIR", tmp_path / "actions")
    monkeypatch.setattr(decision_service, "DECISION_DIR", tmp_path / "decisions")
    monkeypatch.setattr(qc, "CLAUSE_DIR", tmp_path / "qualification_clauses")
    qc._MEMO.clear()
    client.post("/api/rfp/parse", json={"procurement_id": SYNTHETIC})
    yield
    qc._MEMO.clear()


def put_review(clause_id: str, state: str, note: str | None, *, pid: str = SYNTHETIC):
    return client.put(
        f"/api/eligibility/{pid}/review/{clause_id}",
        json={"state": state, "note": note, "decided_by": "김담당"},
    )


def row(report: dict, rule_id: str) -> dict:
    return next(r for r in report["results"] if r["rule_id"] == rule_id)


# ---------------------------------------------------------------------------
# 1) API 왕복
# ---------------------------------------------------------------------------


def test_충족을_저장하면_그_줄이_담당자_확인_가능이_된다() -> None:
    before = client.get(f"/api/eligibility/{SYNTHETIC}").json()
    assert row(before, "QUAL-STAFF-REQ-011")["status"] == "CHECK"

    response = put_review("REQ-011", "met", "총괄책임자 경력증명서 확인(12년)")
    assert response.status_code == 200, response.text
    staff = row(response.json(), "QUAL-STAFF-REQ-011")
    assert staff["status"] == "PASS" and staff["method"] == "HUMAN"
    assert staff["review_state"] == "met" and staff["reviewed_by"] == "김담당"
    assert staff["source"].startswith("담당자 확인 김담당 ") and "총괄책임자 경력증명서 확인(12년) / 제안요청서 4쪽" in staff["source"]
    assert response.json()["review"]["met"] == 1

    # GET 도 같은 판정 — 판정 메모가 회사 사실(확인 기록)을 따라간다.
    again = client.get(f"/api/eligibility/{SYNTHETIC}").json()
    assert row(again, "QUAL-STAFF-REQ-011")["status"] == "PASS"
    listed = client.get(f"/api/eligibility/{SYNTHETIC}/review").json()
    assert [(r["clause_id"], r["state"], r["stale"]) for r in listed["reviews"]] == [("REQ-011", "met", False)]


def test_충족_미충족은_메모_없이_저장되지_않는다() -> None:
    for state in ("met", "unmet"):
        response = put_review("REQ-011", state, "   ")
        assert response.status_code == 422
        assert "근거 메모" in response.json()["detail"]
    assert put_review("REQ-011", "pending", None).status_code == 200
    assert client.get(f"/api/eligibility/{SYNTHETIC}/review").json()["reviews"][0]["state"] == "pending"


def test_없는_조항은_404() -> None:
    assert put_review("QC-99", "met", "확인").status_code == 404


def test_미충족이면_불가이고_참여는_422_보류는_된다() -> None:
    response = put_review("REQ-011", "unmet", "경력 10년 이상 책임자가 없다")
    assert response.status_code == 200
    assert response.json()["verdict"] == "FAIL"
    assert row(response.json(), "QUAL-STAFF-REQ-011")["method"] == "HUMAN"

    go = client.put(f"/api/decision/{SYNTHETIC}", json={"status": "GO", "reasons": ["적합"], "decided_by": "김담당"})
    assert go.status_code == 422
    detail = go.json()["detail"]
    assert "참가자격이 「불가」" in detail and "인력 조항: 총괄책임자" in detail
    hold = client.put(f"/api/decision/{SYNTHETIC}", json={"status": "HOLD", "reasons": ["인력 확보 중"], "decided_by": "김담당"})
    assert hold.status_code == 200, hold.text


def test_활동_기록에는_조항과_상태만_남고_메모는_없다() -> None:
    put_review("REQ-011", "met", "비밀스러운 메모 문장")
    lines = [json.loads(line) for line in audit_log_service.AUDIT_LOG_FILE.read_text(encoding="utf-8").splitlines()]
    events = [line["event"] for line in lines if line.get("event", {}).get("kind") == "clause_review"]
    assert events == [{"kind": "clause_review", "procurement_id": SYNTHETIC, "clause_id": "REQ-011", "state": "met"}]
    assert "비밀스러운" not in audit_log_service.AUDIT_LOG_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 2) 판정 합치기 — stale · 두 화면
# ---------------------------------------------------------------------------


def _raw() -> dict:
    return {"source": "g2b", "item": {
        "bidNtceNo": "R26QUAL0000002", "cntrctCnclsMthdNm": "일반경쟁", "bidQlfctRgstDt": "2026-09-20 18:00",
        "bidClseDt": "2026-09-21 10:00:00", "indstrytyLmtYn": "N", "bidPrtcptLmtYn": "N",
        "cmmnSpldmdCorpRgnLmtYn": "N", "jntcontrctDutyRgnNm1": "", "rgnLmtBidLocplcJdgmBssNm": "",
        "asignBdgtAmt": "55000000",
    }}


def _save(text: str) -> None:
    qc.save({
        "notice_id": NOTICE_ID, "document": {"name": "입찰공고문.pdf", "index": 0, "format": "pdf", "hash": "x"},
        "status": "ok", "page_is_approximate": False,
        "section": {"heading": "3. 입찰참가자격", "page_from": 2, "page_to": 2},
        "clauses": [{"id": "QC-01", "text": text, "page": 2, "kind": "disqualification"}],
        "second_source": None, "note": None,
    })


def _fact(text: str, state: str = "met") -> tuple[str, ...]:
    return (NOTICE_ID, "QC-01", state, "나라장터 등록증 확인", "김담당", "2026-09-23T01:00:00+00:00", qr.clause_hash(text))


def test_원문이_바뀌면_stale_이고_규칙_판정으로_돌아간다() -> None:
    _save("부정당업자에 해당하지 아니한 자")
    facts = ee.CompanyFacts(clause_reviews=(_fact("부정당업자에 해당하지 아니한 자"),))
    rules = ee.evaluate_notice_fields(_raw(), as_of=NOW, company=facts, notice_id=NOTICE_ID)
    met = next(r for r in rules if r.rule_id == "QUAL-DISQUAL-QC-01")
    assert (met.status, met.method, met.review_state) == ("PASS", "HUMAN", "met")
    assert met.source.startswith("담당자 확인 김담당 2026-09-23 10:00: 나라장터 등록증 확인 / 입찰공고문 2쪽")

    _save("부정당업자로 지정되지 아니하고 조세 체납이 없는 자")  # 조항 파일을 다시 뽑았다
    rules = ee.evaluate_notice_fields(_raw(), as_of=NOW, company=facts, notice_id=NOTICE_ID)
    stale = next(r for r in rules if r.rule_id == "QUAL-DISQUAL-QC-01")
    assert (stale.status, stale.method, stale.review_state) == ("CHECK", "RULE", "stale")


def test_목록과_상세가_같은_확인을_본다() -> None:
    _save("부정당업자에 해당하지 아니한 자")
    facts = ee.CompanyFacts(clause_reviews=(_fact("부정당업자에 해당하지 아니한 자", "unmet"),))
    listed = ee.evaluate_notice_fields(_raw(), as_of=NOW, company=facts, notice_id=NOTICE_ID)
    notice = ProcurementNotice(
        id=NOTICE_ID, notice_no="R26QUAL0000002-000", title="AI 교육", agency="기관",
        published_at=datetime(2026, 8, 20, tzinfo=KST), raw_data=_raw(),
    )
    view = procurement_service.NoticeView(notice=notice, match=CandidateMatch(tier="high", matched_ai=["AI"], matched_work=["교육"]))
    report = ee.evaluate_from_sources(NOTICE_ID, notice=view, parse_result=None, as_of=NOW, use_llm=False, company=facts)
    pick = lambda rows: {r.clause_id: (r.status, r.method) for r in rows if r.clause_id}  # noqa: E731
    assert pick(listed) == pick(report.results) == {"QC-01": ("FAIL", "HUMAN")}
    assert ee.overall_verdict(listed) == report.verdict == "FAIL"
    assert report.review.unmet == 1


def test_조항_id_가_바뀌어도_같은_원문이면_확인이_이어진다() -> None:
    """RFP 요구사항 줄(REQ-030 「나. …」)에 「미충족」을 남긴 뒤 조항 파일이 와서 그 줄이 공고문 조항 QC-01 로 합쳐졌다.

    id 로만 찾으면 그 확인이 조용히 사라져 종합이 불가 → 확인 필요로 풀리고 「참여」가 저장된다(20차 검수).
    """
    text = "부정당업자에 해당하지 아니한 자"
    _save(text)
    old = (NOTICE_ID, "REQ-030", "unmet", "제재 이력 조회 결과 해당", "김담당", "2026-09-23T01:00:00+00:00", qr.clause_hash("나. " + text))
    rules = ee.evaluate_notice_fields(_raw(), as_of=NOW, company=ee.CompanyFacts(clause_reviews=(old,)), notice_id=NOTICE_ID)
    carried = next(r for r in rules if r.rule_id == "QUAL-DISQUAL-QC-01")
    assert (carried.status, carried.method, carried.review_state) == ("FAIL", "HUMAN", "unmet")
    assert ee.overall_verdict(rules) == "FAIL"


def test_공고가_목록에_없을_때_보이는_RFP_줄도_확인을_저장한다() -> None:
    """상세는 공고가 없으면 조항 파일 없이 RFP 요구사항으로 줄을 만든다 — 그 줄(REQ-011)이 저장에서 404 가 나면 안 된다."""
    staff = next(r for r in client.get(f"/api/eligibility/{SYNTHETIC}").json()["results"] if r["rule_id"] == "QUAL-STAFF-REQ-011")
    qc.save({
        "notice_id": SYNTHETIC, "document": {"name": "입찰공고문.pdf", "index": 0, "format": "pdf", "hash": "x"},
        "status": "ok", "page_is_approximate": False, "section": {"heading": "3. 입찰참가자격", "page_from": 1, "page_to": 1},
        "clauses": [{"id": "QC-01", "text": staff["clause_text"], "page": 1, "kind": "staff"}], "second_source": None, "note": None,
    })
    assert {"QC-01", "REQ-011"} <= set(ee.clause_texts(SYNTHETIC))
    response = put_review("REQ-011", "met", "총괄책임자 경력증명서 확인")
    assert response.status_code == 200, response.text
    assert row(response.json(), "QUAL-STAFF-REQ-011")["method"] == "HUMAN"


def test_미충족_확인은_참가_차단_조건이_된다() -> None:
    """조건 탐지도 목록·상세와 같은 회사 사실(담당자 확인 포함)을 본다 — 「미충족」 조항이 참가 차단 조건이 된다."""
    assert put_review("REQ-011", "unmet", "경력 10년 이상 책임자가 없다").status_code == 200
    report = client.post("/api/conditions/detect", json={"procurement_id": SYNTHETIC}).json()
    blockers = [c for c in report["conditions"] if c.get("extraction_method") == "HUMAN"]
    assert blockers and "인력 조항" in blockers[0]["title"]


def test_다른_공고의_확인은_섞이지_않는다() -> None:
    _save("부정당업자에 해당하지 아니한 자")
    other = ("g2b-R26OTHER000001-000",) + _fact("부정당업자에 해당하지 아니한 자")[1:]
    rules = ee.evaluate_notice_fields(_raw(), as_of=NOW, company=ee.CompanyFacts(clause_reviews=(other,)), notice_id=NOTICE_ID)
    assert next(r for r in rules if r.rule_id == "QUAL-DISQUAL-QC-01").review_state is None


# ---------------------------------------------------------------------------
# 3) 앞에 세운다 — 목록 「불가」 첫 사유 · 조항 문서 링크 (20차 §4-D-4 · §4-E-2)
# ---------------------------------------------------------------------------


def _view(raw: dict) -> procurement_service.NoticeView:
    notice = ProcurementNotice(
        id=NOTICE_ID, notice_no="R26QUAL0000002-000", title="AI 교육", agency="기관",
        published_at=datetime(2026, 8, 20, tzinfo=KST), raw_data=raw,
    )
    return procurement_service.NoticeView(notice=notice, match=CandidateMatch(tier="high", matched_ai=["AI"], matched_work=["교육"]))


def test_목록_불가_첫_사유는_조항_원문이다() -> None:
    from app.services import opportunity_priority as priority
    from app.services import organization_service

    text = "입찰공고일 전일부터 입찰서 제출일까지 법인등기부상 본점 소재지를 서울특별시에 둔 업체로서 그 기간 동안 유지할 것"
    qc.save({
        "notice_id": NOTICE_ID, "document": {"name": "입찰공고문.pdf", "index": 0, "format": "pdf", "hash": "x"},
        "status": "ok", "page_is_approximate": False, "section": {"heading": "3. 입찰참가자격", "page_from": 1, "page_to": 1},
        "clauses": [{"id": "QC-01", "text": text, "page": 1, "kind": "region"}], "second_source": None, "note": None,
    })
    view = _view(_raw())
    rules = ee.evaluate_notice_fields(_raw(), as_of=NOW, company=ee.CompanyFacts(location_region="전남광주"), notice_id=NOTICE_ID)
    gate, reason = priority.procurement_eligibility_gate(
        view.notice, view.match, profile=organization_service.load_profile("org-sample"), now=NOW, results=rules
    )
    assert gate == "FAIL"
    # 43차 Q13 — 판정 문장 먼저, 원문은 뒤(어느 지역인지가 잘리지 않게)
    assert reason.startswith("지역 조항: 조항은 서울 소재를 요구") and "원문 「입찰공고일 전일부터" in reason and "…" in reason


def test_조항_문서_링크는_나라장터_원본만_싣는다() -> None:
    raw = {**_raw(), "attachments": [
        {"name": "입찰공고문.pdf", "url": "https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?a=1"},
        {"name": "제안요청서.hwp", "url": "http://example.com/rfp.hwp"},
    ]}
    qc.save({
        "notice_id": NOTICE_ID, "document": {"name": "입찰공고문.pdf", "index": 0, "format": "pdf", "hash": "x"},
        "status": "ok", "page_is_approximate": False, "section": {"heading": "3. 입찰참가자격", "page_from": 1, "page_to": 1},
        "clauses": [{"id": "QC-01", "text": "부정당업자에 해당하지 아니한 자", "page": 1, "kind": "disqualification"}],
        "second_source": {"document": {"name": "제안요청서.hwp", "index": 1, "format": "hwp"}, "page_is_approximate": True,
                          "section": None, "clauses": [{"id": "QC-01", "text": "청산 절차 중이 아닌 업체", "page": 3, "kind": "disqualification"}]},
        "note": None,
    })
    report = ee.evaluate_from_sources(NOTICE_ID, notice=_view(raw), parse_result=None, as_of=NOW, use_llm=False)
    assert [(d.source_document, d.name, d.url) for d in report.clause_documents] == [
        ("입찰공고문", "입찰공고문.pdf", "https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?a=1"),
        ("제안요청서", "제안요청서.hwp", None),
    ]


def test_같은_조항을_두_사람이_확인하면_나중_것이_409() -> None:
    """43차 M25 — 화면이 읽은 확인 시각을 보내면, 그사이 남이 확인한 조항을 말없이 덮지 않는다."""
    url = f"/api/eligibility/{SYNTHETIC}/review/REQ-011"
    first = client.put(url, json={"state": "met", "note": "경력증명서 확인", "decided_by": "대표", "expected_decided_at": None})
    assert first.status_code == 200, first.text
    stale = client.put(url, json={"state": "unmet", "note": "경력 부족", "decided_by": "김담당", "expected_decided_at": None})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_write" and "대표 님이" in stale.json()["detail"]["message"]
    seen = client.get(f"/api/eligibility/{SYNTHETIC}/review").json()["reviews"][0]
    assert seen["state"] == "met"
    again = client.put(url, json={"state": "unmet", "note": "경력 부족", "decided_by": "김담당", "expected_decided_at": seen["decided_at"]})
    assert again.status_code == 200


def test_번호가_밀린_조항의_확인도_원문_해시로_버전을_맞춘다() -> None:
    """43차 마지막 검토 — 화면은 원문 해시로 이은 확인의 시각을 보내는데 서버가 지금 번호의 칸만 봐 늘 409 였다."""
    url = f"/api/eligibility/{SYNTHETIC}/review/REQ-011"
    first = client.put(url, json={"state": "met", "note": "경력증명서 확인", "decided_by": "대표", "expected_decided_at": None})
    assert first.status_code == 200
    path = qr.review_path(SYNTHETIC, None)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["reviews"] = {"REQ-099": payload["reviews"]["REQ-011"]}  # 다시 뽑기로 번호가 밀린 것처럼 — 같은 원문 해시가 다른 열쇠에
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    seen = payload["reviews"]["REQ-099"]["decided_at"]
    again = client.put(url, json={"state": "unmet", "note": "경력 부족", "decided_by": "김담당", "expected_decided_at": seen})
    assert again.status_code == 200, again.text
