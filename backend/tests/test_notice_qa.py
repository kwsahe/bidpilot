"""공고문에 질문하기 (판 2.4.0 · `notice_qa_service`).

- 원문은 받아 둔 파일만(분석에 쓴 문서 · 입찰공고문 · 기업마당 쪽 표식).
- 답 문장은 인용이 원문에 있어야 · 다른 쪽에 있으면 쪽을 고침 · 숫자가 인용에 없으면 뺌 · 모두 빠지면 not_found + 낱말 줄.
- AI 꺼짐 · 공용 데모 · 하루 30 → 낱말 찾기. 보낸 글은 원문 쪽 글(연락처 가림) + 질문뿐.
- 잘못된 id 404 · 질문 길이 422 · 열람자 POST 403 · 동시 질문 409.

진짜 CLI 는 부르지 않는다 — `complete_structured` 를 가짜로 바꿔 끼운다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.core import identity, inflight, org_storage, storage
from app.core.config import get_settings
from app.main import app
from app.schemas.organization import AnalysisContext
from app.services import (
    attachment_service,
    bizinfo_document_store,
    document_extractor,
    llm_client,
    notice_qa_service as qa,
    procurement_service,
    rfp_parser,
    user_service,
)

PID = "g2b-R26BK09999991-000"
ORG = "org-sample"
CTX = AnalysisContext(organization_id=ORG, evidence_scope="internal")
SECRET = "bidpilot-notice-qa-token-240"
client = TestClient(app)

NOTICE_PAGES = ["입찰 참가자격: 소프트웨어사업자 신고 업체\n담당 홍길동 062-123-4567 hong@example.go.kr", "제출서류: 제안서 10부, 가격제안서 1부"]
RFP_PAGES = ["사업 개요", "교육은 총 20회 이상 운영한다.\n교육 종료 후 만족도 조사를 실시한다.", "사업 기간은 계약일로부터 6개월이다."]


def _doc(name: str, pages: list[str], fmt: str) -> document_extractor.ExtractedDocument:
    return document_extractor.ExtractedDocument(
        file_name=name, doc_format=fmt, pages=[document_extractor.DocumentPage(page=i, text=t) for i, t in enumerate(pages, start=1)]  # type: ignore[arg-type]
    )


@pytest.fixture()
def bid_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """입찰 공고 하나 — 받아 둔 입찰공고문(0번) · 제안요청서(1번)와 공고 저장본의 첨부 목록. 추출은 가짜."""
    cache = tmp_path / "real_rfp"
    monkeypatch.setattr(attachment_service, "CACHE_DIR", cache)
    folder = cache / attachment_service.sanitize_dir_name(PID)
    folder.mkdir(parents=True)
    (folder / "0_입찰공고문.hwp").write_bytes(b"x")
    (folder / "1_제안요청서.pdf").write_bytes(b"%PDF-")
    notice = SimpleNamespace(id=PID, raw_data={"attachments": [{"name": "입찰공고문.hwp", "url": "u0"}, {"name": "제안요청서.pdf", "url": "u1"}]})
    monkeypatch.setattr(procurement_service, "load_cache", lambda **_: SimpleNamespace(notices=[SimpleNamespace(notice=notice)]))

    def fake_extract(path: Path, *, file_name: str | None = None, **_: Any) -> document_extractor.ExtractedDocument:
        if "제안요청서" in str(file_name):
            return _doc(str(file_name), RFP_PAGES, "pdf")
        return _doc(str(file_name), NOTICE_PAGES, "hwp")

    monkeypatch.setattr(document_extractor, "extract_document", fake_extract)
    return folder


def _analysed(monkeypatch: pytest.MonkeyPatch, *, role: str = "rfp", document: str = "제안요청서.pdf") -> None:
    parsed = SimpleNamespace(document=document, document_role=role, page_is_approximate=True)
    monkeypatch.setattr(rfp_parser, "load_generated", lambda pid: parsed if pid == PID else (_ for _ in ()).throw(rfp_parser.RfpNotParsedError(pid)))


def _not_analysed(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(pid: str) -> Any:
        raise rfp_parser.RfpNotParsedError(pid)

    monkeypatch.setattr(rfp_parser, "load_generated", missing)


def _ai_on(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """AI 문을 켜고 보낸 글을 모은다 — 답은 각 시험이 `answer` 로 정한다."""
    monkeypatch.setattr(get_settings(), "plan_writer_cli", True)
    monkeypatch.setattr(llm_client, "claude_cli_path", lambda: r"C:\fake\claude.exe")
    calls: list[dict[str, Any]] = []
    return calls


def _answer(monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]], payload: dict[str, Any] | Exception) -> None:
    def fake(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if isinstance(payload, Exception):
            raise payload
        return kwargs["schema"].model_validate(payload)

    monkeypatch.setattr(llm_client, "complete_structured", fake)


# ---------------------------------------------------------------------------
# 원문 찾기
# ---------------------------------------------------------------------------


def test_분석한_공고는_입찰공고문과_제안요청서를_함께_읽는다(bid_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _analysed(monkeypatch)
    sources = qa.load_sources(CTX, PID)
    assert [(s.name, s.role, len(s.pages), s.page_is_approximate) for s in sources] == [
        ("입찰공고문", "notice", 2, True), ("제안요청서", "rfp", 3, True)]
    assert qa.state(CTX, PID)["warning"] is None
    # 옛 분석은 문서 이름에 캐시 번호까지 적었다 — 그래도 찾는다
    _analysed(monkeypatch, document="1_제안요청서.pdf")
    assert [s.role for s in qa.load_sources(CTX, PID)] == ["notice", "rfp"]


def test_분석_전이면_입찰공고문만_읽고_경고한다(bid_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _not_analysed(monkeypatch)
    state = qa.state(CTX, PID)
    assert state["available"] is True
    assert state["documents"] == [{"name": "입찰공고문", "role": "notice", "pages": 2, "page_is_approximate": True}]
    assert state["warning"] == qa.NOTICE_ONLY_WARNING
    # 공고문을 분석했으면 같은 문서를 두 번 읽지 않는다
    _analysed(monkeypatch, role="notice", document="입찰공고문.hwp")
    assert [s.role for s in qa.load_sources(CTX, PID)] == ["notice"]


def test_받아_둔_원문이_없으면_빈_목록(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(attachment_service, "CACHE_DIR", tmp_path / "real_rfp")
    _not_analysed(monkeypatch)
    assert qa.load_sources(CTX, PID) == []
    result = qa.ask(CTX, PID, "제출서류는?")
    assert result["status"] == "no_source" and result["lines"] == []


def test_기업마당은_쪽_표식으로_나누고_한글_원본이면_근사_쪽(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bizinfo_document_store, "DOCS_DIR", tmp_path / "bizinfo_docs")
    (tmp_path / "bizinfo_docs").mkdir()
    body = bizinfo_document_store.join_pages(["지원 대상: 광주 소재 중소기업", "신청 기간: 11월 30일까지"])
    # Windows 에서 저장하면 줄바꿈이 \r\n 이다 — 그래도 쪽이 둘로 나뉘어야 한다
    (tmp_path / "bizinfo_docs" / "PBLN_000000000000001.txt").write_bytes(body.replace("\n", "\r\n").encode("utf-8"))
    record = bizinfo_document_store.DocumentRecord(program_id="PBLN_000000000000001", status="text", suffix="hwp", pages=2)
    monkeypatch.setattr(bizinfo_document_store, "load_index", lambda: bizinfo_document_store.DocumentIndex(records={record.program_id: record}))
    sources = qa.load_sources(CTX, "bizinfo-PBLN_000000000000001")
    assert [(s.name, s.role, [p for p, _ in s.pages], s.page_is_approximate) for s in sources] == [("공고문", "support", [1, 2], True)]
    assert sources[0].pages[1][1].startswith("신청 기간")


# ---------------------------------------------------------------------------
# 검증
# ---------------------------------------------------------------------------


def _sources() -> list[qa.Source]:
    return [qa.Source("입찰공고문", "notice", [(1, NOTICE_PAGES[0]), (2, NOTICE_PAGES[1])], False),
            qa.Source("제안요청서", "rfp", [(i, t) for i, t in enumerate(RFP_PAGES, start=1)], True)]


def _line(text: str, doc: int, page: int, quote: str) -> dict[str, Any]:
    return {"text": text, "citations": [{"doc": doc, "page": page, "quote": quote}]}


def test_인용이_원문에_없으면_문장을_뺀다() -> None:
    answer = qa.NoticeAnswerOut.model_validate({"found": True, "lines": [
        _line("만족도 조사를 실시합니다.", 2, 2, "교육 종료 후 만족도 조사를 실시한다"),
        _line("현장 실습을 합니다.", 2, 2, "현장 실습을 반드시 포함한다"),  # 원문에 없는 인용
    ]})
    lines, dropped = qa.verify(answer, _sources())
    assert [l["text"] for l in lines] == ["만족도 조사를 실시합니다."] and dropped == 1
    # 화면 인용은 원문 그 자리(끝 마침표까지)
    assert lines[0]["citations"][0] == {"document": "제안요청서", "page": 2, "page_is_approximate": True, "quote": "교육 종료 후 만족도 조사를 실시한다."}


def test_다른_쪽에_있으면_쪽을_고친다() -> None:
    answer = qa.NoticeAnswerOut.model_validate({"found": True, "lines": [_line("사업 기간은 6개월입니다.", 2, 1, "사업 기간은 계약일로부터 6개월이다.")]})
    lines, dropped = qa.verify(answer, _sources())
    assert dropped == 0 and lines[0]["citations"][0]["page"] == 3


def test_문장_숫자가_인용에_없으면_뺀다() -> None:
    answer = qa.NoticeAnswerOut.model_validate({"found": True, "lines": [_line("교육은 총 30회 이상입니다.", 2, 2, "교육은 총 20회 이상 운영한다.")]})
    assert qa.verify(answer, _sources()) == ([], 1)


def _one(text: str) -> list[qa.Source]:
    return [qa.Source("입찰공고문", "notice", [(1, text)], False)]


@pytest.mark.parametrize(("source", "text", "quote"), [
    ("총 사업비는 3.5억원(부가세 포함)이다.", "총 사업비는 35억원입니다.", "총 사업비는 35억원(부가세 포함)이다."),
    ("사업 기간은 2~3개월이다.", "사업 기간은 23개월입니다.", "사업 기간은 23개월이다."),
    ("제출 마감: 1. 13.(화) 18:00까지", "제출 마감은 11월 3일입니다.", "제출 마감: 11. 3.(화) 18:00까지"),
])
def test_숫자_사이_문장부호는_지우지_않는다(source: str, text: str, quote: str) -> None:
    """11-04 검토 — 압축이 숫자 사이 점 · 물결을 지워 「3.5억」 원문이 「35억」 인용을 받아 주었다."""
    answer = qa.NoticeAnswerOut.model_validate({"found": True, "lines": [_line(text, 1, 1, quote)]})
    assert qa.verify(answer, _one(source)) == ([], 1)


def test_시각_단위_없는_숫자도_인용과_견준다() -> None:
    """11-04 검토 — 단위 낱말 검사는 10:00 · 단위 없는 배점을 숫자로 보지 않았다."""
    source = _one("제안서 제출 마감: 2026. 11. 10.(화) 10:00까지\n기술평가 배점 90점, 가격평가 배점 10점")
    deadline = "제안서 제출 마감: 2026. 11. 10.(화) 10:00까지"
    answer = qa.NoticeAnswerOut.model_validate({"found": True, "lines": [
        _line("제출 마감 시각은 18:00입니다.", 1, 1, deadline),
        _line("기술평가 배점은 80입니다.", 1, 1, "기술평가 배점 90점"),
        _line("제안서는 11월 10일 10:00까지 냅니다.", 1, 1, deadline),
    ]})
    lines, dropped = qa.verify(answer, source)
    assert dropped == 2 and [line["text"] for line in lines] == ["제안서는 11월 10일 10:00까지 냅니다."]


def test_짧은_낱말_인용은_근거가_아니다() -> None:
    """11-04 검토 — 「공동수급」 한 낱말로 뜻이 반대인 문장(「허용됩니다」)이 근거를 달고 남았다."""
    answer = qa.NoticeAnswerOut.model_validate({"found": True, "lines": [_line("공동수급이 허용됩니다.", 1, 1, "공동수급")]})
    assert qa.verify(answer, _one("공동수급은 허용하지 않는다.")) == ([], 1)


def test_화면_인용은_원문_글자_그대로() -> None:
    """모델이 낫표를 빼고 적어도 화면에는 원문 그 자리의 글을 보인다."""
    answer = qa.NoticeAnswerOut.model_validate({"found": True, "lines": [
        _line("교육이 끝나면 만족도 조사를 합니다.", 1, 1, "교육 종료 후 만족도 조사를 실시한다")]})
    lines, _dropped = qa.verify(answer, _one("○ 교육 종료 후 「만족도 조사」를 실시한다."))
    assert lines[0]["citations"][0]["quote"] == "교육 종료 후 「만족도 조사」를 실시한다."
    # 끝 문장부호가 압축에서 빠져도 인용이 「(10」에서 끊기지 않는다(11-04 실제 질문)
    answer = qa.NoticeAnswerOut.model_validate({"found": True, "lines": [
        _line("기술 90%, 가격 10%입니다.", 1, 1, "기술능력평가(90%) + 가격평가(10%)")]})
    lines, _dropped = qa.verify(answer, _one("종합평가 점수(100%) = 기술능력평가(90%) + 가격평가(10%) 로 한다"))
    assert lines[0]["citations"][0]["quote"] == "기술능력평가(90%) + 가격평가(10%)"
    # 끝 문장부호 뒤 여는 괄호(다음 글의 시작)는 붙이지 않는다(11-06 실제 질문 「…없습니다.(」)
    answer = qa.NoticeAnswerOut.model_validate({"found": True, "lines": [
        _line("따로 서류를 낼 필요가 없습니다.", 1, 1, "별도의 서류를 제출할 필요가 없습니다")]})
    lines, _dropped = qa.verify(answer, _one("확인이 가능한 입찰참가자격은 별도의 서류를 제출할 필요가 없습니다.(조달청 고시)"))
    assert lines[0]["citations"][0]["quote"] == "별도의 서류를 제출할 필요가 없습니다."


@pytest.mark.parametrize(("error", "note"), [
    (llm_client.LLMValidationError("스키마 검증 3회 실패: 1 validation error for NoticeAnswerOut\nlines.0.citations"),
     "AI 답의 모양이 맞지 않았습니다 — " + qa.SEARCH_TAIL),
    (llm_client.LLMUnavailableError("Claude 사용 한도에 걸렸습니다 — 몇 시간 뒤 다시 시도하세요 (You've hit your limit)"),
     "Claude 사용 한도에 걸렸습니다 — 몇 시간 뒤 다시 시도하세요 — " + qa.SEARCH_TAIL),
    (llm_client.LLMUnavailableError("Claude CLI 실패(exit 1) — unexpected token"), "AI(Claude)를 부르지 못했습니다 — " + qa.SEARCH_TAIL),
    (PermissionError("[WinError 32] 다른 프로세스가 파일을 사용 중"), "AI 답을 받는 중 시스템 오류(PermissionError) — " + qa.SEARCH_TAIL),
])
def test_AI_실패_글은_한국어_한_줄로_낱말_찾기(error: Exception, note: str, bid_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """11-04 검토 — 스키마 원문(영어 여러 줄) · CLI 영어 출력을 화면에 싣지 않는다 · OSError 도 500 이 아니라 낱말 찾기."""
    _analysed(monkeypatch)
    calls = _ai_on(monkeypatch)
    _answer(monkeypatch, calls, error)
    result = qa.ask(CTX, PID, "제출서류는?")
    assert result["status"] == "search_only" and result["note"] == note and result["used_today"] == 1


def test_모두_빠지면_찾지_못함과_낱말_줄(bid_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _analysed(monkeypatch)
    calls = _ai_on(monkeypatch)
    _answer(monkeypatch, calls, {"found": True, "lines": [_line("교육은 40회입니다.", 2, 2, "교육은 총 20회 이상 운영한다.")]})
    result = qa.ask(CTX, PID, "교육은 몇 회 운영하나요?")
    assert result["status"] == "not_found" and result["dropped"] == 1 and result["lines"] == []
    assert result["note"] == "공고문에서 답을 찾지 못했습니다"
    assert result["matches"] and result["matches"][0] == {"document": "제안요청서", "page": 2, "page_is_approximate": True,
                                                         "text": "교육은 총 20회 이상 운영한다."}


def test_AI_답은_검증한_문장만_쪽_인용과_함께(bid_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _analysed(monkeypatch)
    calls = _ai_on(monkeypatch)
    _answer(monkeypatch, calls, {"found": True, "lines": [_line("교육은 20회 이상 운영합니다.", 2, 2, "교육은 총 20회 이상 운영한다.")]})
    result = qa.ask(CTX, PID, "교육은 몇 회 운영하나요?")
    assert result["status"] == "answered" and result["dropped"] == 0
    assert result["lines"][0]["citations"][0]["document"] == "제안요청서"
    assert (result["pages_sent"], result["pages_total"], result["used_today"]) == (5, 5, 1)
    assert calls[0]["plan_writer"] is True and calls[0]["writer"] == "claude" and calls[0]["purpose"] == "notice_qa"


# ---------------------------------------------------------------------------
# 낱말 찾기로 내려가는 길
# ---------------------------------------------------------------------------


def test_AI_꺼짐이면_낱말_찾기만(bid_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _analysed(monkeypatch)
    calls: list[dict[str, Any]] = []
    _answer(monkeypatch, calls, {"found": False})
    state = qa.state(CTX, PID)
    assert state["ai_ready"] is False and state["ai_note"] == qa.AI_OFF_NOTE
    result = qa.ask(CTX, PID, "제출서류는 무엇인가요?")
    assert result["status"] == "search_only" and calls == []
    assert result["note"].startswith(qa.AI_OFF_NOTE)
    assert result["matches"][0]["text"] == "제출서류: 제안서 10부, 가격제안서 1부"
    assert qa.used_today(ORG) == 0  # 낱말 찾기는 세지 않는다


def test_공용_데모_모드면_AI_를_부르지_않는다(bid_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _analysed(monkeypatch)
    calls = _ai_on(monkeypatch)
    _answer(monkeypatch, calls, {"found": False})
    monkeypatch.setattr(get_settings(), "public_demo_mode", True)
    result = qa.ask(CTX, PID, "제출서류는?")
    assert result["status"] == "search_only" and calls == [] and qa.DEMO_NOTE in result["note"]


def test_하루_30번을_넘으면_낱말_찾기와_안내(bid_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _analysed(monkeypatch)
    calls = _ai_on(monkeypatch)
    _answer(monkeypatch, calls, {"found": False})
    path = org_storage.storage_for(ORG).root / qa.COUNT_FILE
    storage.write_json_atomic(path, {"day": storage.kst_today().isoformat(), "count": qa.DAILY_LIMIT})
    result = qa.ask(CTX, PID, "제출서류는?")
    assert result["status"] == "search_only" and result["note"] == qa.LIMIT_NOTE and calls == []
    assert result["used_today"] == qa.DAILY_LIMIT
    # 어제 기록은 오늘 0 으로
    storage.write_json_atomic(path, {"day": "2000-01-01", "count": 99})
    assert qa.used_today(ORG) == 0


def test_AI_가_실패해도_한_번으로_세고_낱말_찾기(bid_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _analysed(monkeypatch)
    calls = _ai_on(monkeypatch)
    _answer(monkeypatch, calls, llm_client.LLMUnavailableError("Claude 사용 한도에 걸렸습니다"))
    result = qa.ask(CTX, PID, "제출서류는?")
    assert result["status"] == "search_only" and "Claude 사용 한도" in result["note"]
    assert result["used_today"] == 1 and len(calls) == 1


def test_보낸_글은_원문_쪽_글과_질문뿐_연락처는_가림(bid_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _analysed(monkeypatch)
    calls = _ai_on(monkeypatch)
    _answer(monkeypatch, calls, {"found": False})
    root = org_storage.storage_for(ORG).root
    root.mkdir(parents=True, exist_ok=True)
    (root / "profile.json").write_text(json.dumps({"company_name": "비밀회사값-프로필", "revenue": "매출-비밀-777"}, ensure_ascii=False), encoding="utf-8")
    (root / "ledger.json").write_text(json.dumps([{"title": "원장-비밀-실적"}], ensure_ascii=False), encoding="utf-8")
    qa.ask(CTX, PID, "참가자격은?")
    sent = calls[0]["user"] + calls[0]["system"]
    for secret in ("비밀회사값-프로필", "매출-비밀-777", "원장-비밀-실적", "062-123-4567", "hong@example.go.kr"):
        assert secret not in sent, secret
    # 허용 목록 — 문서 머리 + 쪽 글(가림) + 질문 말고는 없다
    masked = [procurement_service.mask_contact_text(t) for t in NOTICE_PAGES]
    expected = "\n\n".join([f"[문서 1 · 입찰공고문 · 쪽 {i}]\n{t}" for i, t in enumerate(masked, start=1)]
                           + [f"[문서 2 · 제안요청서 · 쪽 {i}]\n{t}" for i, t in enumerate(RFP_PAGES, start=1)])
    assert calls[0]["user"] == f"{expected}\n\n질문: 참가자격은?"


def test_보낼_쪽은_4만자를_넘으면_질문과_맞는_쪽부터_쪽_순서로() -> None:
    filler = "가" * 30_000
    sources = [qa.Source("제안요청서", "rfp", [(1, filler), (2, "만족도 조사 실시"), (3, filler)], False)]
    picked, total = qa.pick_pages(sources, "만족도 조사")
    assert total == 3 and [p for _d, p, _t in picked] == [1, 2]


# ---------------------------------------------------------------------------
# API — id · 길이 · 권한 · 동시 질문
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["etc-passwd", "bizinfo-a.b", "manual-zzz", "manual-0123456789ab", "g2b-..-1"])
def test_잘못된_id_는_404(bad: str) -> None:
    assert client.get(f"/api/notice-qa/{bad}").status_code == 404
    assert client.post(f"/api/notice-qa/{bad}", json={"question": "제출서류는?"}).status_code == 404


@pytest.mark.parametrize("question", ["가", "  가  ", "질" * 301])
def test_질문_길이가_맞지_않으면_422(question: str) -> None:
    assert client.post(f"/api/notice-qa/{PID}", json={"question": question}).status_code == 422


def test_같은_공고_동시_질문은_409(bid_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _analysed(monkeypatch)
    with inflight.hold("notice_qa", ORG, PID):
        response = client.post(f"/api/notice-qa/{PID}", json={"question": "제출서류는?"})
    assert response.status_code == 409 and "답하는 중" in response.json()["detail"]
    # 끝나면 다시 묻는다(공백은 정리)
    ok = client.post(f"/api/notice-qa/{PID}", json={"question": "  제출서류는   무엇인가요?  "})
    assert ok.status_code == 200 and ok.json()["status"] == "search_only"


@pytest.fixture()
def signed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(get_settings(), "api_token", SECRET)
    monkeypatch.setattr(user_service, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.delenv("DEMO_USER", raising=False)
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    auth_api.reset_login_throttle()
    user_service.clear_snapshot_cache()
    user_service.add_user("staff1", "old-password-1", role="viewer", display_name="직원 하나")
    user_service.add_user("editor1", "old-password-2", role="editor", display_name="편집 하나")
    user_service.clear_snapshot_cache()
    yield
    user_service.clear_snapshot_cache()


def _headers(user: str, role: str) -> dict[str, str]:
    return {"X-API-Token": SECRET, "X-User": user, "X-User-Role": role, "X-User-Signature": identity.signature_for(user, role, SECRET)}


def test_열람자는_원문_상태만_보고_질문은_403(signed: None, bid_files: Path, monkeypatch: pytest.MonkeyPatch, audit_log_file: Path) -> None:
    _analysed(monkeypatch)
    viewer = _headers("staff1", "viewer")
    assert client.get(f"/api/notice-qa/{PID}", headers=viewer).status_code == 200
    assert client.post(f"/api/notice-qa/{PID}", json={"question": "제출서류는?"}, headers=viewer).status_code == 403
    editor = client.post(f"/api/notice-qa/{PID}", json={"question": "제출서류는?"}, headers=_headers("editor1", "editor"))
    assert editor.status_code == 200, editor.text
    # 쓰기 요청은 활동 기록에 한 줄씩(본문 · 질문은 남기지 않음)
    logged = [json.loads(line) for line in audit_log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    asks = [row for row in logged if row.get("path") == f"/api/notice-qa/{PID}"]
    assert [row.get("status") for row in asks] == [403, 200]
    assert "제출서류" not in audit_log_file.read_text(encoding="utf-8")
