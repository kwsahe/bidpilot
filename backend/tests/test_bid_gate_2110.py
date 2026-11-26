"""2.11.0 D · E — 작성 도구 낱말 · 제목 조각 · 확정 전 인력 경력 · 평가본 실적 사업명 · 작성 지시문 · 사전규격뿐 · 참가 자격(게이트 판 5).

시험 자료는 가상 값뿐이다. AI 는 가짜로 — 네트워크 · CLI 를 부르지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.services import attachment_service, bid_proposal_service as bid, bid_quality_gate as gate, eligibility_engine, plan_export_service
from tests.test_bid_quality_gate import COMPANY, ORG, PID, _codes, _fake_writer, _quality, _source, _store, api  # noqa: F401 — api 는 준비물

PARAMS = {"organization_id": ORG, "evidence_scope": "internal"}


def _s(text: str, **extra: Any) -> dict[str, Any]:
    return {"text": text, "type": "AI_SUGGESTION", **extra}


# --- T7a 작성 도구 낱말 ---------------------------------------------------------------------------------------


def test_본문_표_칸에_원문_낱말이_남으면_보통이고_대조_인용은_잡지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_writer(monkeypatch, units={
        "M1-1": [_s("- 일정: 6~7개월차(원문 6-7월)에 운영합니다."), _s("- 발주기관이 정한 원문 기준을 따릅니다.")],
        "M1-2": [_s("- 연구원이 원문과 대조해 검수합니다.")]})
    draft = bid.generate(source=_source(), company=COMPANY)
    found = [f for f in _quality(draft)["findings"] if f["code"] == "TOOL_WORD"]
    assert len(found) == 1 and found[0]["severity"] == "MINOR" and found[0]["axis"] == "auto" and found[0]["count"] == 2
    assert found[0]["action"] and "제안요청서" in found[0]["action"]
    # 인용 원문에 「원문」이 든 제안요청서 문장은 옮긴 말이라 잡지 않는다
    quoted = {"text": "- 당사는 원문 보관 기준을 지키겠습니다.", "type": "RFP_GROUNDED", "source": "기록물은 원문 그대로 보관한다."}
    assert gate.tool_words({"sections": [], "form": {}, "tables": []}, [("s", quoted)]) == []
    assert gate.tool_words({"sections": [], "form": {}, "tables": []}, [("s", {**quoted, "type": "AI_SUGGESTION"})])
    # AI 표 칸(과업별 대응)도 본다 — ⚠ 검토 표식은 떼고
    view = {"sections": [], "form": {}, "tables": [{"key": "scope", "by": "llm", "title": "과업별 대응",
                                                   "rows": [["가. 운영", "운영합니다", "원문 산출물 ⚠ 확인"]]}]}
    assert gate.tool_words(view, []) == [("과업별 대응 표", "원문 산출물")]
    # 공고 글에 같은 덩어리가 있으면(기록물 원문 과업) 뺀다
    view["title"] = "원문 산출물 디지털화 용역"
    assert gate.tool_words(view, []) == []


# --- T7b 제목 조각 ---------------------------------------------------------------------------------------------


def test_소항목_제목_조각_낱말이_본문에_없으면_보통() -> None:
    items = {"a": "기대효과 및 비전", "b": "제안의 특징 및 장점", "c": "업무보고 및 검토계획", "d": "가" * 22 + " 및 비전", "e": "기대효과 및 비전"}
    bodies = {"a": "- 기대효과: 교육 만족도를 높입니다.", "b": "- 당사는 차별화된 방법을 씁니다.", "c": "- 착수 보고와 결과 검토를 합니다.",
              "d": "- 기대효과를 냅니다.", "e": "- 기대효과를 냅니다."}
    view = {"form": {"sections": [{"items": [{"key": k, "plain": v} for k, v in items.items()]}]}, "tables": [],
            "sections": [{"key": k, "section": f"소항목 {k}", "by": "rules" if k == "e" else "llm", "sentences": [_s(bodies[k])]}
                         for k in items]}
    assert gate.title_gaps(view) == [("소항목 a", "비전")]
    # 괄호 안의 「·」는 나누지 않는다
    paren = {"form": {"sections": [{"items": [{"key": "p", "plain": "추진 일정(주차별 · 월별)"}]}]}, "tables": [],
             "sections": [{"key": "p", "section": "추진 일정", "by": "llm", "sentences": [_s("- W1~W4 에 운영합니다.")]}]}
    assert gate.title_gaps(paren) == []
    # 딸린 표 칸에 있으면 있음으로
    view["tables"] = [{"key": "t1", "rows": [["비전", "교육으로 지역 인재를 키운다"]]}]
    view["sections"][0]["tables"] = ["t1"]
    assert gate.title_gaps(view) == []


# --- T7c 확정 전 인력 경력 ---------------------------------------------------------------------------------------


def test_외부_위촉_인력의_지난_경력을_단정하면_인력_약속() -> None:
    caught = ["- 외부 위촉 코치는 스타트업 컨설팅을 수행해 온 전문가입니다.", "- 경력이 풍부한 현장 강사가 맡습니다.", "- 대기업 출신 전문가를 둡니다."]
    passed = ["- 코치는 컨설팅 경력이 있는 전문가를 선정 기준으로 위촉합니다.", "- 당사가 운영해 온 프로그램을 전문가와 함께 고칩니다.",
              "- 교체 시 동등 이상 경력자로 바꿉니다.", "- 강사 후보는 경력이 있는 전문가로 둡니다."]
    assert all(gate.past_career(_s(t)) for t in caught)
    assert not any(gate.past_career(_s(t)) for t in passed)
    quoted = {"text": "- 현장에서 활동해 온 전문가를 둡니다.", "type": "RFP_GROUNDED", "source": "현장에서 활동해 온 전문가를 둘 것"}
    assert not gate.past_career(quoted)


def test_인력_표를_채워도_위촉_문장의_지난_경력은_잡는다(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_bid_quality_gate import _filled

    line = "- 외부 위촉 코치는 스타트업 컨설팅을 수행해 온 전문가입니다."
    _fake_writer(monkeypatch, units={"M3-4": [_s(line)], "M3-5": [_s("- 당사가 운영해 온 프로그램을 전문가와 함께 고칩니다.")]})
    quality = _quality(_filled(bid.generate(source=_source(), company=COMPANY)))
    assert quality["staffing_unconfirmed"] is False
    found = [f for f in quality["findings"] if f["code"] == "STAFFING_PROMISE"]
    assert len(found) == 1 and found[0]["axis"] == "evidence" and found[0]["count"] == 1 and "지난 경력" in found[0]["title"]


# --- T7d · D4 평가본 실적 사업명 ----------------------------------------------------------------------------------


def test_식별_낱말에_수행_실적_사업명을_더하고_짧은_제목과_인증_행은_뺀다() -> None:
    rows = [{"agency": "가나대학교 산학협력단", "title": "2024 가나대학교 재학생 AI 실무 교육 운영", "field": "대학·교육기관"},
            {"agency": "가나시청", "title": "AI 교육", "field": "공공·지자체"},
            {"agency": "가상인증원", "title": "가상 품질경영시스템 인증 취득", "field": "인증·지정"}]
    words = gate.identity_words({}, rows)
    titles = [w for k, w in words if k == "실적 사업명"]
    assert titles == ["2024 가나대학교 재학생 AI 실무 교육 운영", "2024 대학 재학생 AI 실무 교육 운영"]
    found = gate.identity_findings([("Ⅲ. 수행 실적", "당사는 2024 대학 재학생 AI 실무 교육 운영을 수행했습니다.")], words)
    assert [(f["severity"], f["detail"].split(" — ")[0]) for f in found] == [("MAJOR", "실적 사업명 1")]
    assert "재학생" not in found[0]["detail"]  # 값은 싣지 않는다(D7)
    # 이번 공고 제목과 같은 사업명은 뺀다(연속 사업)
    assert not [w for k, w in gate.identity_words({}, rows, exclude=rows[0]["title"]) if w == rows[0]["title"]]


def test_평가본은_일반현황_주요_실적_줄을_뺀다() -> None:
    general = {"kind": "fields", "section": "일반현황", "fields": [
        {"label": "주요 실적", "value": "2024 가나대학교 재학생 AI 실무 교육 운영", "filled_by": "company"},
        {"label": "주요 사업내용", "value": "AI 활용 교육", "filled_by": "company"}],
        "sentences": [{"text": "주요 실적: 2024 가나대학교 재학생 AI 실무 교육 운영"}, {"text": "주요 사업내용: AI 활용 교육"}]}
    out, _cover = plan_export_service.blind_copy({"sections": [general]}, {})
    assert [f["label"] for f in out["sections"][0]["fields"]] == ["주요 사업내용"]
    assert [s["text"] for s in out["sections"][0]["sentences"]] == ["주요 사업내용: AI 활용 교육"]


def test_AI_에_보내는_평가본_실적_가림은_식별_검사와_같은_함수() -> None:
    row = {"id": "ledger:1", "title": "2024 가나대학교 재학생 교육(제2024-0001-00001호)", "agency": "가나대학교 산학협력단", "field": "대학·교육기관"}
    sent = bid.llm_payload({"ledger": [row], "agency_names": ["가나대학교"]}, blind=True)["performance"][0]
    assert sent["title"] == bid.blind_text(row["title"], ["가나대학교"]) == "2024 대학 재학생 교육"


# --- T8 작성 지시문 · 완료형 거르기 -------------------------------------------------------------------------------


def test_지시문_원문_낱말_완료형_위촉_경력_의무_문구_실적명_예시안_하도급() -> None:
    prompt = bid.SYSTEM_PROMPT
    for phrase in ("「원문」이라는 낱말을 쓰지 않습니다", "끝낸 일처럼", "선정 기준", "주체(누가) · 수단 · 주기", "title 을 줄이거나 바꾸지 않습니다",
                   "사업명(title)을 쓰지 않고", "「(안)」을 붙입니다", "사전 승인을 받은 뒤에만", "A 와 B 를 각각"):
        assert phrase in prompt, phrase
    # 지시문이 자료를 「원문」이라 부르는 곳은 경계 표식 줄과 금지 줄뿐
    assert [line for line in prompt.splitlines() if "원문" in line and "<<<원문" not in line and "「원문」이라는" not in line] == []
    for word in ("비전", "코치", "동국대"):  # 평가 예문의 사업 고유 낱말은 박지 않는다
        assert word not in prompt


def test_받아_첨부했다는_완료형은_본문에서_빼고_붙임_제출은_남긴다() -> None:
    done, plan = _s("- 사업자등록증을 받아 첨부했습니다."), _s("- 사업자등록증은 붙임으로 제출합니다.")
    kept, moved = bid.bid_filter([done, plan], [], "s", sources=[])
    assert [s["text"] for s in kept] == [plan["text"]] and moved == 1


# --- T9 사전규격 규격서뿐 ---------------------------------------------------------------------------------------


def test_사전규격_규격서뿐인_초안을_찾고_받아_둔_첨부를_가른다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(attachment_service, "CACHE_DIR", tmp_path / "real_rfp")
    spec = "사전규격 규격서 1(R26BD00000001)"
    draft = {"sources": [spec], "rfp_document": spec, "papers": []}
    attachments = ["공고서.hwpx", "공고서.pdf", spec]
    assert bid.source_gap(draft, PID, attachments) == {"missing": ["공고서.hwpx"], "received": [], "unread": []}  # 형식 둘은 하나
    path = attachment_service.cache_path(PID, 0, "공고서.hwpx")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PK hwpx")
    assert bid.source_gap(draft, PID, attachments) == {"missing": [], "received": ["공고서.hwpx"], "unread": []}
    # 쓸 때 이미 받아 두었는데 읽은 원문에 없음 — 글을 못 뽑은 파일(다시 써도 읽지 못한다 · 2.11.0 검토)
    later = {**draft, "executed_at": "2999-01-01T00:00:00+00:00"}
    assert bid.source_gap(later, PID, attachments) == {"missing": [], "received": [], "unread": ["공고서.hwpx"]}
    [line] = gate._source_gap_findings(bid.source_gap(later, PID, attachments))
    assert line["axis"] == "fact" and "읽지 못함" in line["detail"] and "그림 PDF" in line["action"]
    assert bid.source_gap({**draft, "sources": [spec, "공고서.hwpx"]}, PID, attachments) is None  # 본공고 첨부도 읽음
    assert bid.source_gap(draft, PID, None) is None and bid.source_gap(draft, PID, [spec]) is None  # 첨부를 모름 · 규격서뿐
    assert bid.source_gap({"rfp_document": spec, "papers": []}, PID, attachments) is None  # 읽은 원문 목록이 없는 옛 초안은 보지 않는다
    path.write_bytes(b"<html><head><title>\xec\xa0\x90\xea\xb2\x80</title></head></html>")  # 안내 화면은 받지 않은 것으로
    assert bid.source_gap(draft, PID, attachments)["missing"] == ["공고서.hwpx"]
    # 받은 것 · 안 받은 것이 섞이면 둘 다 적는다
    assert "아직 안 받음 「공고서.hwpx」" in gate._source_gap_findings({"missing": ["공고서.hwpx"], "received": ["과업지시서.hwp"]})[0]["detail"]


def test_API_사전규격뿐이면_중요_사실_확인이고_받아_두면_다시_쓰라고(api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_bid_quality_gate import _filled

    monkeypatch.setattr(attachment_service, "CACHE_DIR", tmp_path / "real_rfp")
    _fake_writer(monkeypatch)
    _store(_filled(bid.generate(source=_source(), company=COMPANY)))
    monkeypatch.setattr(gate, "stored_notice", lambda pid: {"notice_no": None, "title": None, "agency": None, "url": None,
                                                           "attachments": ["공고서.hwpx"]})
    quality = api.get(f"/api/proposal/{PID}/plan-draft", params=PARAMS).json()["quality"]
    found = [f for f in quality["findings"] if f["code"] == "SOURCE_PRESPEC_ONLY"]
    assert [(f["severity"], f["axis"]) for f in found] == [("MAJOR", "fact")]
    assert quality["status"] != "BLOCKED" and quality["generation"]["status"] != "FAIL"
    path = attachment_service.cache_path(PID, 0, "공고서.hwpx")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PK hwpx")
    quality = api.get(f"/api/proposal/{PID}/plan-draft", params=PARAMS).json()["quality"]
    found = [f for f in quality["findings"] if f["code"] == "SOURCE_PRESPEC_ONLY"]
    assert [(f["severity"], f["axis"]) for f in found] == [("MAJOR", "auto")] and "다시 쓰" in found[0]["action"]
    assert quality["generation"]["status"] == "REVIEW"


# --- T10 참가 자격 -----------------------------------------------------------------------------------------------


def _row(status: str, label: str, *, side: str | None = None, clause: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(status=status, label=label, clause_text=clause, reason=f"{label} 사유", check_side=side)


def test_참가_자격_불가는_중요_사실_확인이고_확인_필요_판정_못함은_참고() -> None:
    fail = SimpleNamespace(results=[_row("FAIL", "업종", clause="소프트웨어사업자 등록"), _row("CHECK", "실적", side="company"), _row("PASS", "지역")])
    [line] = gate.eligibility_findings(fail)
    assert (line["code"], line["severity"], line["axis"], line["count"]) == ("ELIGIBILITY", "MAJOR", "fact", 1)
    assert "업종: 소프트웨어사업자 등록" in line["detail"] and line["action"]
    [line] = gate.eligibility_findings(SimpleNamespace(results=[_row("CHECK", "실적", side="company"), _row("CHECK", "인력", side="notice")]))
    assert line["severity"] == "INFO" and "확인 필요 2줄(회사 쪽 1)" in line["detail"] and "실적" in line["detail"]
    assert gate.eligibility_findings(SimpleNamespace(results=[_row("PASS", "지역")])) == []
    assert gate.eligibility_findings(None) == []
    assert gate.eligibility_findings(gate.ELIGIBILITY_ERROR)[0]["severity"] == "INFO"


def test_API_참가_자격_불가여도_승인할_수_있고_엔진_예외는_차단이_아니다(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_bid_quality_gate import _filled

    _fake_writer(monkeypatch)
    _store(_filled(bid.generate(source=_source(), company=COMPANY)))
    report = SimpleNamespace(results=[_row("FAIL", "업종", clause="소프트웨어사업자 등록")])
    monkeypatch.setattr(eligibility_engine, "offline_report", lambda pid, context: report)
    quality = api.get(f"/api/proposal/{PID}/plan-draft", params=PARAMS).json()["quality"]
    assert "ELIGIBILITY" in _codes(quality, "MAJOR") and quality["status"] != "BLOCKED" and "GATE_ERROR" not in _codes(quality)
    monkeypatch.setattr(eligibility_engine, "offline_report", lambda pid, context: (_ for _ in ()).throw(RuntimeError("시험")))
    quality = api.get(f"/api/proposal/{PID}/plan-draft", params=PARAMS).json()["quality"]
    assert "GATE_ERROR" not in _codes(quality) and "ELIGIBILITY" in _codes(quality, "INFO")


def test_직접_넣은_공고는_참가_자격_판정을_부르지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(eligibility_engine, "offline_report", lambda pid, context: calls.append(pid))
    assert bid._eligibility("manual-abc", None) is None and calls == []  # type: ignore[arg-type]
    bid._eligibility(PID, None)  # type: ignore[arg-type]
    assert calls == [PID]
