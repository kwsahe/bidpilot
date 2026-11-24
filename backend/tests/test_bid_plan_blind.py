"""11-06 갈래 B — 「이 양식으로 씁니다」 미리 보기 API · 평가본(회사명 없는 판) 내려받기.

회사 이름 · 대표자는 시험 회사 프로필 · 일반현황에서 읽는다(실제 회사 값을 박지 않는다). AI 는 가짜 · PDF 는 HTML 을 잡아 대조한다
(브라우저를 띄우지 않는다 — PDF 는 그 HTML 을 찍을 뿐이다).
"""

from __future__ import annotations

import html
import json
import re
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.organization import OrganizationCreateRequest, OrganizationProfileUpdate, PlanGeneralUpdate
from app.services import bid_proposal_service as bid
from app.services import bid_quality_gate as gate
from app.services import organization_service, plan_export_service, plan_pdf_service, procurement_service, proposal_service
from tests.test_bid_proposal_service import COMPANY, PID, RFP, _docx_text, _fake_writer, _hwpx_text, _Notice, _source

ORG = "org-blind-test"
#: 시험 회사 값 — 받침 있는 이름(「…21은」 → 「당사는」)을 일부러 고른다.
FULL_NAME, SHORT_NAME, CEO = "주식회사 가나다21", "가나다21", "홍길순"
BUSINESS_NO, ADDRESS, PHONE = "123-45-67890", "광주광역시 시험로 77", "062-111-2222"
#: 설립일 · 인증 이력 번호(2.10.0 D5 — 평가본에서 가린다)
OPENED, CERT_NO = date(2021, 4, 15), "제1234-56호"
PARAMS = {"organization_id": ORG, "evidence_scope": "internal"}
PREVIEW = {
    "procurement_id": PID, "outline_source": "rfp",
    "outline": [{"no": "Ⅰ", "title": "제안개요", "items": [{"no": "1", "title": "제안 목적"}]}],
    "outline_where": {"document": "제안요청서.hwpx", "page": 31, "head": "□ 제안서 목차 및 작성 방법"},
    "outline_rejected": [{"head": "목 차", "page": 1, "reason": "문서 앞 목차"}],
    "evaluation": {"items": [{"area": "사업 이해도", "name": "사업 목표 이해", "points": 10, "kind": "정성"}], "total": 100, "where": None},
    "format": {"page_limit": 50, "page_note": "본문 50쪽 이내", "blind": True, "blind_note": "업체명 표기 금지", "landscape": False,
               "ppt": False, "two_volume": False, "volumes": [], "notes": [], "where": None},
    "documents": [{"name": "제안요청서.hwpx", "role": "rfp", "pages": 40}],
    "warnings": [],
}


@pytest.fixture()
def api(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(proposal_service, "PROPOSALS_DIR", tmp_path / "public_proposals")
    organization_service.create_organization(OrganizationCreateRequest(display_name="시험 회사", organization_id=ORG, data_class="synthetic", created_by="k"))
    organization_service.save_profile(ORG, OrganizationProfileUpdate(
        name=FULL_NAME, address=ADDRESS, phone=PHONE, business_domains=["AI 활용 교육"], data_class="synthetic", updated_by="시험",
        certification_history=[f"2021.07 사회적기업 인증({CERT_NO})"]))
    organization_service.save_plan_general(ORG, PlanGeneralUpdate(representative=CEO, business_number=BUSINESS_NO, opened_on=OPENED,
                                                                  updated_by="시험"))

    async def fake_notice(notice_id: str, **_: Any) -> Any:
        return SimpleNamespace(notice=_Notice()) if notice_id == PID else None

    monkeypatch.setattr(procurement_service, "get_notice", fake_notice)
    monkeypatch.setattr(bid, "load_source", lambda pid, view: _source())
    # 본문에 회사 이름이 든 계획 문장 — 평가본에서 「당사」로 바뀌어야 한다
    _fake_writer(monkeypatch, units={"M1-1": [
        {"text": f"{SHORT_NAME}은 교육(수료)생 상담을 정기적으로 운영합니다.", "type": "AI_SUGGESTION"},
        {"text": f"{FULL_NAME}의 상담 일정은 월 1회입니다.", "type": "AI_SUGGESTION"},
    ]})
    original = bid.generate
    # 갈래 A(A-5)가 저장할 칸 — 아직 없어도 화면 응답에 실리는지 본다
    monkeypatch.setattr(bid, "generate", lambda **kw: {**original(**kw), "outline_where": PREVIEW["outline_where"],
                                                        "format": PREVIEW["format"], "outline_rejected": PREVIEW["outline_rejected"]})
    client = TestClient(app)
    assert client.post(f"/api/proposal/{PID}/plan-draft", json={**PARAMS, "writer": "claude"}).status_code == 200
    return client


def _export(api: TestClient, fmt: str, variant: str) -> Any:
    response = api.get(f"/api/proposal/{PID}/plan-draft/export", params={**PARAMS, "format": fmt, "variant": variant})
    assert response.status_code == 200, response.text
    return response


def _pdf_html(api: TestClient, monkeypatch: pytest.MonkeyPatch, variant: str) -> str:
    """PDF 길 — `build_pdf` 가 브라우저에 넘기는 HTML 을 잡는다(그 HTML 이 곧 PDF 글이다)."""
    seen: list[str] = []
    monkeypatch.setattr(plan_pdf_service, "pdf_status", lambda: {"browser": True, "word": False})
    monkeypatch.setattr(plan_pdf_service, "html_to_pdf", lambda page, **_: seen.append(page) or b"%PDF-fake")
    response = _export(api, "pdf", variant)
    assert response.content == b"%PDF-fake"
    return html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", "", seen[0], flags=re.S)))


IDENTITY = (SHORT_NAME, CEO, BUSINESS_NO, ADDRESS, PHONE, "2021. 04. 15.", CERT_NO)


def test_평가본은_세_형식_모두_회사_이름_대표자_식별_칸이_없고_제출용은_그대로(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    blind = {"DOCX": _docx_text(_export(api, "docx", "blind").content), "HWPX": _hwpx_text(_export(api, "hwpx", "blind").content),
             "PDF": _pdf_html(api, monkeypatch, "blind")}
    for fmt, text in blind.items():
        for value in IDENTITY:
            assert value not in text, (fmt, value)
        # 2.10.0 D6 — 표지 제안사 줄 · 일반현황 식별 칸은 자리표 대신 줄째 뺀다(설립일 · 연혁도 · D5)
        assert plan_export_service.BLIND_MARK not in text, fmt
        assert "전화번호" not in text and "설립년월일" not in text and "주요 연혁" not in text and "주요 사업내용" in text, fmt
        assert "당사는 교육(수료)생 상담을 정기적으로 운영합니다." in text and "당사의 상담 일정은 월 1회입니다." in text, fmt
        assert "한국인터넷진흥원" in text and "Ⅰ. 제안개요" in text, fmt  # 회사 정보 말고는 제출용과 같다
    submit = {"DOCX": _docx_text(_export(api, "docx", "submit").content), "HWPX": _hwpx_text(_export(api, "hwpx", "submit").content),
              "PDF": _pdf_html(api, monkeypatch, "submit")}
    for fmt, text in submit.items():
        assert FULL_NAME in text and CEO in text and plan_export_service.BLIND_MARK not in text, fmt
        assert "2021. 04. 15." in text and CERT_NO in text and "전화번호" in text, fmt


def test_평가본_파일_이름과_워드_문서_정보(api: TestClient) -> None:
    from docx import Document
    import io

    response = _export(api, "docx", "blind")
    assert "%ED%8F%89%EA%B0%80%EB%B3%B8" in response.headers["content-disposition"]  # 평가본
    props = Document(io.BytesIO(response.content)).core_properties
    assert props.author == "" and props.last_modified_by == "" and props.comments == ""


def test_평가본_이름_바꾸기는_조사를_맞추고_낱말_속_이름은_건드리지_않는다() -> None:
    draft = {"company_name": "가나다21", "sections": [{"kind": "item", "sentences": [
        {"text": "가나다21은 운영합니다. 가나다21이며 (주)가나다21과 함께 가나다21 주식회사의 일정 · 가나다21으로 보냅니다. 가나다21이 맡습니다."}]}]}
    out, cover = plan_export_service.blind_copy(draft, {"rows": [("발주기관", "기관"), ("제안사", "가나다21")]})
    assert out["sections"][0]["sentences"][0]["text"] == "당사는 운영합니다. 당사이며 당사와 함께 당사의 일정 · 당사로 보냅니다. 당사가 맡습니다."
    assert cover["rows"] == [("발주기관", "기관")]  # 2.10.0 D6 — 제안사 줄은 줄째 뺀다(예전 자리표 「(평가본 — 표기하지 않음)」)
    assert draft["sections"][0]["sentences"][0]["text"].startswith("가나다21은")  # 원본은 그대로


def test_평가본_긴_조사_띄어_쓴_이름_대표자_이름() -> None:
    """검토 11-06 — 「당사과의」 · 「당사이라는」 · 「당사으로서」 · 「당사 대표가」 · 띄어 쓴 이름이 남던 것."""
    draft = {"company_name": "가나다21", "sections": [
        {"kind": "item", "sentences": [{"text": "가나다21과의 협력 · 가나다21이라는 이름 · 가나다21으로서 · 가나다21이었다 · 가나다 21은 맡습니다."},
                                       {"text": "홍길순 대표가 직접 · 대표이사 홍길순은 · 홍길순이 맡습니다."}]},
        {"kind": "general", "fields": [{"label": "대표자", "value": "홍길순", "filled_by": "company"}]}]}
    out, _cover = plan_export_service.blind_copy(draft, {})
    first, second = (s["text"] for s in out["sections"][0]["sentences"])
    assert first == "당사와의 협력 · 당사라는 이름 · 당사로서 · 당사였다 · 당사는 맡습니다."
    assert second == "대표가 직접 · 대표는 · 대표가 맡습니다."


def test_평가본_짧은_조사_뒤에_붙은_조사도_맞춘다() -> None:
    """검토 11-06 #18 — 「당사이랑」 · 「당사과도」 · 「당사과는」 · 「당사으로는」이 남던 것."""
    draft = {"company_name": "샘플에듀", "sections": [{"kind": "item", "sentences": [
        {"text": "샘플에듀이랑 협력합니다. 샘플에듀과도 협약 · 샘플에듀과는 다릅니다 · 샘플에듀과만 · 샘플에듀으로도 · 샘플에듀으로만 · 한빛으로는 처음입니다."}]}]}
    out, _cover = plan_export_service.blind_copy(draft, {"rows": [("제안사", "한빛")]})
    assert out["sections"][0]["sentences"][0]["text"] == (
        "당사랑 협력합니다. 당사와도 협약 · 당사와는 다릅니다 · 당사와만 · 당사로도 · 당사로만 · 당사로는 처음입니다.")


def test_초안_응답에_양식_칸이_실린다(api: TestClient) -> None:
    got = api.get(f"/api/proposal/{PID}/plan-draft", params=PARAMS).json()
    assert got["outline_where"] == PREVIEW["outline_where"] and got["format"]["blind"] is True
    assert got["outline_rejected"] == PREVIEW["outline_rejected"] and "evaluation_total" in got


def test_양식_미리_보기_API(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bid, "outline_preview", lambda pid, view: {**PREVIEW, "procurement_id": pid}, raising=False)
    ok = api.get(f"/api/proposal/{PID}/plan-outline", params=PARAMS)
    assert ok.status_code == 200 and ok.json()["outline_where"]["page"] == 31
    # 공고 목록에 없는 공고도 받아 둔 원문으로 읽는다(검토 11-06 — 예전에는 404 「공고를 찾지 못했습니다」)
    other = api.get("/api/proposal/g2b-R26BK00000000-000/plan-outline", params=PARAMS)
    assert other.status_code == 200 and other.json()["procurement_id"] == "g2b-R26BK00000000-000"

    def raise_(exc: Exception) -> Any:
        def fn(pid: str, view: Any) -> Any:
            raise exc
        return fn

    monkeypatch.setattr(bid, "outline_preview", raise_(bid.NoRfpError("제안요청서가 없어 입찰공고문만 분석했습니다")), raising=False)
    no_rfp = api.get(f"/api/proposal/{PID}/plan-outline", params=PARAMS)
    assert no_rfp.status_code == 409 and "제안요청서" in no_rfp.json()["detail"]
    monkeypatch.setattr(bid, "outline_preview", raise_(bid.SourceMissingError("공고 분석을 먼저 하세요")), raising=False)
    assert api.get(f"/api/proposal/{PID}/plan-outline", params=PARAMS).status_code == 422


# ---------------------------------------------------------------------------
# 2.10.0 T6 — 평가본 가림 범위(D5) · 가린 자리(D6) · 실적 기관 유형(blind3) · 식별 낱말 검사(D7) · 평가본만 받는 공고(D8)
# ---------------------------------------------------------------------------

#: 동국대 작성요령 표 줄(11-13) — 원본 · 사본 구분 없는 평가본 규정
BLIND_LINE = "- 제안사를 식별할 수 있는 정보(업체명 등)는 포함하지 않음"
BLIND_RFP = RFP.replace("(PDF로 제출)", f"(PDF로 제출)\n{BLIND_LINE}", 1)
#: `plan_fill_service.company_values` 꼴의 시험 회사 값
VALUES = {"name": FULL_NAME, "representative": CEO, "phone": PHONE, "business_number": BUSINESS_NO, "address": ADDRESS,
          "website": "https://www.ganada21.kr/", "opened_on": "2021. 04. 15.", "history": f"2021.07 사회적기업 인증({CERT_NO}) / 2022.09 여성기업"}


def test_평가본은_설립일_연혁_칸과_본문_인증번호를_빼고_남는_칸이_없을_때만_자리표() -> None:
    """D5 · D6 — 식별 칸(설립일 · 주요 연혁 포함)은 줄째 빼고 본문의 회사 「제…호」 번호도 지운다. 원본은 그대로."""
    general = {"kind": "fields", "section": "일반현황", "fields": [
        {"label": "기관명", "value": FULL_NAME, "filled_by": "company"},
        {"label": "대표자", "value": CEO, "filled_by": "company"},
        {"label": "설립년월일", "value": "2021. 04. 15.", "filled_by": "company"},
        {"label": "주요 연혁", "value": f"2021.07 사회적기업 인증({CERT_NO})", "filled_by": "company"},
        {"label": "주요 사업내용", "value": "AI 활용 교육", "filled_by": "company"}],
        "sentences": [{"text": f"대표자: {CEO}"}, {"text": "주요 사업내용: AI 활용 교육"}]}
    body = {"kind": "item", "section": "추진 전략", "sentences": [
        {"text": f"당사는 사회적기업 인증({CERT_NO})을 받은 기관으로 운영합니다."},
        {"text": "법률 제12345호 · 고시 제2026-7호에 따라 운영합니다."}]}  # 회사 번호가 아닌 원문 번호는 그대로
    draft = {"company_name": FULL_NAME, "sections": [general, body]}
    out, cover = plan_export_service.blind_copy(draft, {"rows": [("발주기관", "기관"), ("제안사", FULL_NAME), ("제출일", "2026. 11. 13.")]})
    fields = out["sections"][0]["fields"]
    assert [f["label"] for f in fields] == ["주요 사업내용"]
    assert [s["text"] for s in out["sections"][0]["sentences"]] == ["주요 사업내용: AI 활용 교육"]
    assert [s["text"] for s in out["sections"][1]["sentences"]] == [
        "당사는 사회적기업 인증을 받은 기관으로 운영합니다.", "법률 제12345호 · 고시 제2026-7호에 따라 운영합니다."]
    assert cover["rows"] == [("발주기관", "기관"), ("제출일", "2026. 11. 13.")]
    assert len(draft["sections"][0]["fields"]) == 5  # 원본은 그대로
    # 남는 칸이 하나도 없으면 자리표(D6)
    only = {"sections": [{"kind": "fields", "fields": [{"label": "대표자", "value": CEO, "filled_by": "company"},
                                                        {"label": "전화번호", "value": PHONE, "filled_by": "company"}]}]}
    left = plan_export_service.blind_copy(only, {})[0]["sections"][0]["fields"]
    assert [f["value"] for f in left] == [plan_export_service.BLIND_MARK] * 2


def test_실적_기관은_이름_대신_기관_유형() -> None:
    kinds = {"OO대학교 산학협력단": "대학", "시험인공지능고등학교": "학교", "시험시청": "지자체", "광주광역시": "지자체", "북구청": "지자체",
             "㈜가나": "민간 기업", "주식회사 시험소프트": "민간 기업", "(사)시험인재개발원": "민간 단체", "한국시험기술협회": "민간 단체",
             "시험복지재단": "공공기관", "시험산업진흥원(ABC)": "공공기관", "한국시험인력공단": "공공기관", "광주광역시교육청": "공공기관",
             "고용노동부": "중앙행정기관", "조달청": "중앙행정기관", "관계기관": "기관", "Microsoft 관련 인증기관": "기관", "": "기관"}
    assert {name: bid.agency_kind(name) for name in kinds} == kinds
    # 식별 낱말로 쓸 이름 — 법인 꼴 · 괄호 · 「등」을 떼고 유형을 알 수 있는 조각만(일반 낱말 「관계기관」 · 「… 발급기관」은 아님)
    assert bid.agency_names("OO대학교 산학협력단") == ["OO대학교"]
    assert bid.agency_names("출원인 주식회사 가나다21") == ["가나다21"]
    assert bid.agency_names("사단법인 시험창업진흥협회") == ["시험창업진흥협회"]
    assert bid.agency_names("중소벤처기업부 등") == ["중소벤처기업부"]
    assert bid.agency_names("시험산업진흥원(ABC)") == ["시험산업진흥원"]
    assert bid.agency_names("관계기관") == [] and bid.agency_names("중소기업 확인 발급기관") == [] and bid.agency_names(None) == []


def test_평가본_공고는_AI_에_실적_기관_이름을_보내지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    pieces = {"profile": {}, "capacity": {}, "ledger": [{"id": "ledger:3", "title": "OO대학교 AI 실무 교육", "agency": "OO대학교",
                                                          "summary": "OO대학교 재학생 대상 AI 실무 교육 운영"}]}
    row = bid.llm_payload(pieces, blind=True)["performance"][0]
    assert row["agency"] == "대학" and row["title"] == "대학 AI 실무 교육" and "OO대학교" not in json.dumps(row, ensure_ascii=False)
    assert bid.llm_payload(pieces)["performance"][0]["agency"] == "OO대학교"  # 평가본 규정이 없으면 그대로
    # 다른 행 기관 이름이 제목에 든 실적 · 설립연도도 평가본 공고면 보내지 않는다(11-13 독립 검토)
    other = {"profile": {"founded_year": 2021}, "capacity": {}, "agency_names": ["시험대학교 인공지능사업단", "시험대학교"],
             "ledger": [{"id": "ledger:5", "title": "시험대학교 인공지능사업단 비교과 프로그램", "agency": "대학", "summary": "비교과 운영"}]}
    blind_payload = bid.llm_payload(other, blind=True)
    assert "시험대학교" not in json.dumps(blind_payload, ensure_ascii=False) and blind_payload["founded_year"]["value"] is None
    assert bid.llm_payload(other)["founded_year"]["value"] == 2021 and "시험대학교" in bid.llm_payload(other)["performance"][0]["title"]
    company = {"profile": {}, "capacity": {}, "ledger_all": [{"seq": 1, "title": "가", "agency": "시험대학교 산학협력단", "external_use": "가능"},
                                                             {"seq": 2, "title": "나", "agency": "가나다진흥원", "external_use": "불가"}]}
    assert set(bid.company_pieces(company, "AI 교육")["agency_names"]) >= {"시험대학교", "가나다진흥원"}  # 외부 사용 불가 행 기관도 식별 낱말
    # 원장 제목 · 요약 속 인증 · 등록 번호(「제…호」)도 감싼 괄호째 지운다(T6 검토 — AI 가 본문에 옮기면 평가본에 남는다)
    numbered = {**pieces, "ledger": [{"id": "ledger:4", "title": f"사회적기업 인증 {CERT_NO}", "agency": "고용노동부",
                                      "summary": f"사회적기업 인증({CERT_NO}) 취득 · 법률 제12345호 근거"}]}
    row = bid.llm_payload(numbered, blind=True)["performance"][0]
    assert row["title"] == "사회적기업 인증" and row["summary"] == "사회적기업 인증 취득 · 법률 제12345호 근거"
    assert CERT_NO in json.dumps(bid.llm_payload(numbered)["performance"][0], ensure_ascii=False)
    calls = _fake_writer(monkeypatch)
    draft = bid.generate(source=_source(BLIND_RFP), company=COMPANY)
    assert draft["format"]["blind"] and draft["format"]["blind_only"]
    sent = "\n".join(call["user"] for call in calls)
    assert "OO대학교" not in sent and '"agency": "대학"' in sent
    calls.clear()
    bid.generate(source=_source(), company=COMPANY)
    assert '"agency": "OO대학교"' in "\n".join(call["user"] for call in calls)


def test_식별_낱말은_회사자료와_실적_기관에서_모으고_이번_공고_글은_뺀다() -> None:
    rows = [{"agency": "가나대학교 산학협력단"}, {"agency": "관계기관"}, {"agency": "주식회사 시험파트너"}, {"agency": "나라시청"},
            {"agency": FULL_NAME}]
    words = gate.identity_words(VALUES, rows, exclude="나라시청 발주 「AI 교육」")
    assert set(words) == {("회사 이름", SHORT_NAME), ("대표자", CEO), ("전화", PHONE), ("사업자번호", BUSINESS_NO), ("주소", ADDRESS),
                          ("홈페이지", "ganada21.kr"), ("설립일", "2021. 04. 15."), ("인증번호", CERT_NO),
                          ("실적 기관", "가나대학교"), ("실적 기관", "시험파트너")}
    # 띄어쓰기 · 「·」 · 붙임표 · 괄호 · 점 · 대소문자는 무시하고 찾는다(PDF 글에도 같은 함수)
    left = gate.identity_leaks("가나다 21 은 · 062) 111-2222 · 가나대학교와 · 제 1234-56 호 · WWW.GANADA21.KR", words)
    assert {kind for kind, _word in left} == {"회사 이름", "전화", "실적 기관", "인증번호", "홈페이지"}
    assert gate.identity_leaks("당사는 AI 교육을 운영합니다", words) == []
    assert gate.identity_words({}, []) == []
    # 검사 줄은 (자리, 글) 입력 — 올린 PDF 쪽 글도 같은 함수(T8)
    lines = gate.identity_findings([("3쪽", "가나다 21 은 운영합니다"), ("5쪽", "가나대학교와 · 가나대학교")], words)
    assert [(f["severity"], f["count"], f["location"]) for f in lines] == [("BLOCKER", 1, "평가본 › 3쪽"), ("MAJOR", 1, "평가본 › 5쪽")]
    assert gate.identity_findings([("1쪽", "당사")], words) == []


def _blind_view(monkeypatch: pytest.MonkeyPatch, *texts: str) -> dict[str, Any]:
    _fake_writer(monkeypatch)
    view = bid.generate(source=_source(BLIND_RFP), company=COMPANY)
    body = next(s for s in view["sections"] if s.get("kind") != "fields" and s.get("sentences"))
    body["sentences"] += [{"text": text, "type": "AI_SUGGESTION"} for text in texts]
    return view


def test_평가본에_남은_식별_낱말은_종류와_수만_알린다(monkeypatch: pytest.MonkeyPatch) -> None:
    """D7 — 회사 이름 · 대표자 · 전화 · 사업자번호 · 인증번호는 차단 · 실적 기관 이름은 중요 · 값은 검사 줄에 싣지 않는다."""
    view = _blind_view(monkeypatch, f"- {CEO} 대표가 직접 점검합니다.", "- 가나대학교와 함께한 운영 경험을 살립니다.")
    meta = bid.export_meta(view, company=FULL_NAME)
    words = gate.identity_words(VALUES, [{"agency": "가나대학교 산학협력단"}], exclude=gate.notice_text(view))
    quality = gate.evaluate(view, meta=meta, draft_hash="h", identity=words)
    left = [f for f in quality["findings"] if f["code"] == "BLIND_IDENT_LEFT"]
    assert [(f["severity"], f["count"], f["axis"]) for f in left] == [("BLOCKER", 1, "auto"), ("MAJOR", 1, "auto")]
    assert "대표자 1" in left[0]["detail"] and "실적 기관 1" in left[1]["detail"]
    shown = json.dumps(left, ensure_ascii=False)
    assert CEO not in shown and "가나대학교" not in shown and SHORT_NAME not in shown  # 회사 이름은 「당사」로 바뀌어 남지 않음
    # 원문이 평가본을 요구하지 않으면 검사하지 않는다
    plain = gate.evaluate({**view, "format": {**view["format"], "blind": False}}, meta=meta, draft_hash="h", identity=words)
    assert "BLIND_IDENT_LEFT" not in {f["code"] for f in plain["findings"]}
    # 원본 · 사본 구분이 없는 평가본 규정 — 평가본이 제출 파일이라고 알린다(D8)
    rule = next(f for f in quality["findings"] if f["code"] == "BLIND_RULE")
    assert "평가본이 제출 파일" in rule["detail"]


def test_평가본만_받는_공고는_빈칸_셈도_평가본_기준(monkeypatch: pytest.MonkeyPatch) -> None:
    """T6 검토 — 평가본만 내는 공고(`format.blind_only`)는 평가본이 제출 파일이다. 게이트 빈칸 · 화면 「제출 전 채울 칸」 · 한글 다시 읽기가
    같은 판(평가본)을 센다(Review Focus 5) — 줄째 뺀 식별 칸(대표자 · 설립일 …)을 PLACEHOLDER 가 가리키지 않는다."""
    view = _blind_view(monkeypatch)
    assert view["format"]["blind_only"]
    meta = bid.export_meta(view, company=FULL_NAME)
    form = view.get("form") or {}
    blind_n = plan_export_service.blank_total(view, form, meta, variant="blind")
    assert blind_n < plan_export_service.blank_total(view, form, meta)  # 식별 칸이 줄째 빠져 두 판이 갈린다
    assert plan_export_service.submit_variant(view) == "blind"
    assert plan_export_service.submit_blank_count(view, form, meta) == blind_n
    quality = gate.evaluate(view, meta=meta, draft_hash="h")
    assert quality["submit_blanks"] == blind_n
    shown = " ".join(f["detail"] for f in quality["findings"] if f["code"] == "PLACEHOLDER")
    assert "대표자" not in shown and "기관명" not in shown
    # 원본 · 사본 구분이 있는 공고 · 옛 초안(칸 없음)은 회사명 판(제출용) 기준 그대로
    for fmt in ({**view["format"], "blind_only": False}, {}):
        split = {**view, "format": fmt}
        assert plan_export_service.submit_variant(split) == "submit"
        assert plan_export_service.submit_blank_count(split, form, meta) == plan_export_service.blank_total(split, form, meta) > blind_n
        assert gate.evaluate(split, meta=meta, draft_hash="h")["submit_blanks"] > blind_n


def test_API_화면_검사는_회사자료로_식별_낱말을_찾는다(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    codes = {f["code"] for f in api.get(f"/api/proposal/{PID}/plan-draft", params=PARAMS).json()["quality"]["findings"]}
    assert "BLIND_RULE" in codes and "BLIND_IDENT_LEFT" not in codes  # 회사 이름 · 대표자는 「당사」 · 「대표」로 · 식별 칸은 줄째 뺌
    # 본문에 실적 원장 기관 이름 — read_view 가 원장 행을 identity_words 로 넘겨야 잡힌다(가짜 identity_words 없이 · T6 검토).
    # 회사 이름 · 대표자는 평가본에서 바뀌고 전화 · 번호는 근거 없는 숫자라 작성기가 빈칸으로 바꾸므로 숫자 없는 기관 이름으로 본다
    from app.services import performance_match_service

    monkeypatch.setattr(performance_match_service, "load_ledger_for",
                        lambda _ctx: {"rows": [{"id": "L1", "agency": "가나대학교 산학협력단", "title": "AI 실무 교육"}]})
    _fake_writer(monkeypatch, units={"M1-1": [{"text": "○ 운영 장소", "type": "AI_SUGGESTION"},
                                              {"text": "- 가나대학교 강의실에서 교육을 운영합니다.", "type": "AI_SUGGESTION"}]})
    assert api.post(f"/api/proposal/{PID}/plan-draft", json={**PARAMS, "writer": "claude"}).status_code == 200
    quality = api.get(f"/api/proposal/{PID}/plan-draft", params=PARAMS).json()["quality"]
    left = [f for f in quality["findings"] if f["code"] == "BLIND_IDENT_LEFT"]
    assert [f["severity"] for f in left] == ["MAJOR"] and "실적 기관 1" in left[0]["detail"]
    assert "가나대학교" not in json.dumps(left, ensure_ascii=False)  # 값은 싣지 않음(D7)


def _file_name(response: Any) -> str:
    from urllib.parse import unquote

    return unquote(response.headers["content-disposition"].split("''", 1)[1])


def test_평가본만_받는_공고는_평가본이_제출용_이름이고_회사명_판은_포함본(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """D8 — 원문 규정에 원본 · 사본 구분이 없으면(`format.blind_only`) 평가본이 「제출용」(승인 전 「초안」) · 회사명 판은 「회사명 포함본」."""
    import io

    from docx import Document

    original = bid.generate
    only = {**PREVIEW["format"], "blind_only": True}
    monkeypatch.setattr(bid, "generate", lambda **kw: {**original(**kw), "format": only})
    assert api.post(f"/api/proposal/{PID}/plan-draft", json={**PARAMS, "writer": "claude"}).status_code == 200
    blind = _export(api, "docx", "blind")
    assert _file_name(blind).startswith("제안서_초안_") and Document(io.BytesIO(blind.content)).core_properties.title.endswith("(초안)")
    named = _export(api, "docx", "submit")
    assert _file_name(named).startswith("제안서_회사명_포함본_")
    assert Document(io.BytesIO(named.content)).core_properties.title.endswith("(회사명 포함본)")
    assert plan_export_service.export_file_name("사업", "docx", variant="blind", doc_kind="제안서", blind_only=True).startswith("제안서_제출용_사업_")
    assert plan_export_service.export_file_name("사업", "docx", variant="blind", doc_kind="제안서").startswith("제안서_평가본_사업_")
    assert plan_export_service.variant_label("review", final=True, blind_only=True) == "검토용"
