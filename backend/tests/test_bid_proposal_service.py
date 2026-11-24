"""11-03 입찰 제안서 작성기 — 제안요청서 목차 · 평가 기준대로 쓰고, 「확인 필요」 없는 제출용 문서를 낸다.

기준 공고 g2b-R26BK01786460(사전규격 R26BD00285788 제안요청서)의 발췌를 시험 자료로 쓴다(`fixtures/bid_rfp_1103.txt` ·
발주기관 담당자 이름 · 전화 줄은 뺐다). AI 는 가짜로 — 네트워크 · CLI 를 부르지 않는다.
"""

from __future__ import annotations

import html
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.organization import AnalysisContext, OrganizationCreateRequest
from app.services import (
    bid_proposal_service as bid,
    llm_client,
    organization_service,
    plan_export_service,
    plan_fill_service,
    plan_hwpx_service,
    plan_validation,
    procurement_service,
    proposal_service,
    rfp_parser,
)
from app.services.hwpx_template_service import validate_hwpx

RFP = (Path(__file__).parent / "fixtures" / "bid_rfp_1103.txt").read_text(encoding="utf-8")
PID = "g2b-R26BK09999999-000"
ORG = "org-demo-company"

COMPANY: dict[str, Any] = {
    "profile": {
        "name": "시험회사", "address": "광주광역시 시험로 123", "phone": "062-000-1111", "founded_year": 2021,
        "business_domains": ["AI 활용 교육", "디지털 역량 교육"], "certifications": ["사회적기업"], "preferred_regions": ["광주광역시"],
        "certification_history": ["2021.07 사회적기업 인증"],
    },
    "capacity": {"skills": [{"name": "생성형 AI 교육", "level": "proven"}], "credentials": [{"name": "직접생산확인", "held": True}],
                 "business_items": ["교육 서비스업"], "team_note": "비밀 메모 — 강사 7명"},
    "ledger_all": [
        {"seq": 3, "title": "OO대학교 AI 실무 교육", "year": "2024", "field": "대학·교육기관", "agency": "OO대학교",
         "summary": "재학생 대상 AI 실무 교육 운영", "external_use": "가능", "amount_thousand_krw": 12345, "evidence_note": "증빙메모-가"},
        {"seq": 9, "title": "공개하지 않는 실적", "year": "2025", "field": "공공·지자체", "external_use": "증빙 확인 후"},
    ],
}


def _source(text: str = RFP) -> dict[str, Any]:
    return {"procurement_id": PID, "title": "27년 사이버보안인력양성 교육(수료)생 취업지원 프로그램 운영·고도화",
            "agency": "한국인터넷진흥원(조달청 대행)", "text": text, "document": "사전규격 규격서 1(R26BD00285788)",
            "requirement_set_hash": "hash-1"}


def _fake_writer(monkeypatch: pytest.MonkeyPatch, *, units: dict[str, list[dict]] | None = None,
                 evals: dict[str, list[str]] | None = None, fail: tuple[str, ...] = (),
                 scope: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    """대항목 호출마다 소항목 key 를 받아 문장을 돌려주는 가짜 작성기. 보낸 본문을 모은다. scope — 「과업별 대응」 표가 딸린 소항목에 돌려줄 행."""
    calls: list[dict[str, str]] = []

    def fake(*, system: str, user: str, schema: Any, purpose: str, **_: Any) -> Any:
        if purpose == bid.EVAL_RETRY_PURPOSE:  # 조견표 다시 묻기(3차 지시서 §3) — 대항목 호출 수에 세지 않는다
            return schema.model_validate({"pairs": []})
        calls.append({"system": system, "user": user, "purpose": purpose})
        if any(word in purpose for word in fail):
            raise llm_client.LLMUnavailableError("시험 — 이 대항목은 실패")
        line = next(row for row in user.splitlines() if row.startswith("소항목(JSON): "))
        items = json.loads(line.removeprefix("소항목(JSON): "))
        out = []
        for item in items:
            sentences = (units or {}).get(item["key"]) or [
                {"text": "○ 수행 방안", "type": "AI_SUGGESTION"},
                {"text": "- 당사는 교육(수료)생 상담을 정기적으로 운영합니다.", "type": "AI_SUGGESTION"},
            ]
            out.append({"key": item["key"], "sentences": sentences, "eval_items": (evals or {}).get(item["key"], []),
                        "scope": (scope or []) if "scope" in item["tables"] else []})
        return schema.model_validate({"units": out})

    monkeypatch.setattr(llm_client, "complete_structured", fake)
    monkeypatch.setattr(llm_client, "plan_writer_ready", lambda writer="claude": (True, None))
    return calls


# ---------------------------------------------------------------------------
# 제안요청서 읽기
# ---------------------------------------------------------------------------


def test_제안서_목차와_작성_방법을_그대로_읽는다() -> None:
    outline = bid.read_outline(RFP)
    assert [f"{m['no']}. {m['title']}" for m in outline] == [
        "Ⅰ. 제안개요", "Ⅱ. 제안사 일반", "Ⅲ. 사업수행부문", "Ⅳ. 사업관리 부문", "V. 안전 및 보건 준수사항", "Ⅵ. 결과 활용성 부문", "Ⅶ. 기타"]
    assert [i["title"] for i in outline[2]["items"]] == ["개요", "추진목표 및 전략", "주요사업내용", "세부과제별 추진방안", "결과물 제출계획"]
    assert "세부 과제 체계 및 전략 제시" in " ".join(outline[2]["items"][3]["guide"])
    assert outline[5]["items"] == [] and "활용" in " ".join(outline[5]["guide"])  # 소항목 없는 대항목은 대항목 글이 작성 방법


def test_목차는_다음_장_머리에서_끝난다_장_번호_줄을_작성_방법으로_싣지_않는다() -> None:
    # 11-03 검토 — 「Ⅶ. 기타」 작성 방법에 「V」 · 「입찰 및 제안 안내」가 실렸다
    text = RFP.replace("□ 입찰 방법", "V\n입찰 및 제안 안내\n1. 입찰 방법\n2. 제안서 평가\n□ 입찰 방법", 1)
    last = bid.read_outline(text)[-1]
    assert last["title"] == "기타" and last["items"] == []
    assert not {"V", "입찰 및 제안 안내", "1. 입찰 방법"} & set(last["guide"])
    # 장 머리 없이 바로 「1. 입찰 방법」이 와도 작성 방법 글 뒤의 번호 줄은 소항목이 아니다
    bare = RFP.replace("□ 입찰 방법", "1. 입찰 방법\n2. 제안서 평가\n□ 입찰 방법", 1)
    assert bid.read_outline(bare)[-1]["items"] == []


def _outline(body: str) -> list[dict]:
    return bid.read_outline("□ 제안서 목차 및 작성 방법\n" + body + "\n□ 기술능력평가 기준")


def test_숫자_대항목_목차와_가나다_소항목을_읽는다() -> None:
    outline = _outline("1. 제안 개요\n가. 제안 목적\n○ 목적 기술\n나. 추진 전략\n2. 사업 수행\n가. 과업별 수행 방안\n3. 사업 관리\n가. 일정\n나. 인력")
    assert [m["title"] for m in outline] == ["제안 개요", "사업 수행", "사업 관리"]
    assert [i["title"] for i in outline[0]["items"]] == ["제안 목적", "추진 전략"]
    assert [i["title"] for i in outline[2]["items"]] == ["일정", "인력"]


def test_Ⅰ_1_꼴_소항목과_작성_방법_속_번호_글머리() -> None:
    outline = _outline("Ⅰ. 제안 개요\nⅠ-1. 제안 목적\n1) 사업의 목적을 기술\n2) 목표를 기술\nⅠ-2. 제안 범위\nⅡ. 사업 수행\nⅡ-1. 수행 방안\nⅢ. 사업 관리\n"
                       "■ 사업 관리 계획을 일정 · 인력 · 품질 순서로 빠짐없이 자세히 적습니다")
    assert [i["title"] for i in outline[0]["items"]] == ["제안 목적", "제안 범위"]  # 「1) 목적을 기술」은 작성 방법
    assert "1) 사업의 목적을 기술" in outline[0]["items"][0]["guide"]
    assert outline[2]["guide"] and outline[2]["guide"][0].startswith("■ 사업 관리 계획")  # 긴 ■ 줄은 작성 방법


def test_목차_머리는_있는데_못_읽으면_unread() -> None:
    outlines, found = bid.find_outline("□ 제안서 목차\n제안서는 자유 양식으로 작성\n" + "설명 줄\n" * 12)
    assert outlines == [] and found is True


def test_평가_기준_15항목_배점_합_100() -> None:
    evaluation = bid.read_evaluation(RFP)
    assert len(evaluation["items"]) == 15 and evaluation["total"] == 100
    first = evaluation["items"][0]
    assert (first["area"], first["name"], first["points"]) == ("공통사항", "사업 이해도", 5)
    names = [i["name"] for i in evaluation["items"]]
    assert "채용기업 발굴 및 관리" in names  # 두 줄로 나뉜 항목 이름
    assert {i["area"] for i in evaluation["items"]} >= {"안전·보건 사항"}


def test_한_줄_영역_배점도_읽고_배점이_안_맞는_표는_조견표를_만들지_않는다() -> None:
    one_line = RFP.replace("공통사항\n(15점)", "공통사항 (15점)", 1)
    items = bid.read_evaluation(one_line)["items"]
    assert len(items) == 15 and items[0]["area"] == "공통사항" and items[0]["name"] == "사업 이해도"
    # 배점이 기준보다 먼저 오는 표 — 11-06 부터 바르게 읽는다(이름 뒤 배점 · 그 뒤 기준은 앞 항목 기준 · 1793373 · 1731641 꼴).
    # 11-03 에는 이름 · 배점이 밀려 읽혀 항목을 비웠다(기대값이 바뀐 까닭).
    shifted = ("□ 기술능력평가 기준\n공통사항\n(15점)\n사업 이해도\n5점\no 사업 목적 이해도\n사업 수행계획\n5점\no 계획의 구체성\n"
               "수행능력\n5점\no 인력 구성\n□ 기술평가 방법")
    result = bid.read_evaluation(shifted)
    assert [(i["name"], i["points"], i["criteria"]) for i in result["items"]] == [
        ("사업 이해도", 5, ["사업 목적 이해도"]), ("사업 수행계획", 5, ["계획의 구체성"]), ("수행능력", 5, ["인력 구성"])]
    # 영역 배점과 항목 합이 안 맞는 표는 여전히 조견표를 만들지 않고 원문만 남긴다
    mismatched = shifted.replace("수행능력\n5점", "수행능력\n10점")
    result = bid.read_evaluation(mismatched)
    assert result["items"] == [] and "사업 이해도" in result["text"]


def test_쪽_번호_없는_앞_목차를_발췌_시작으로_잡지_않는다() -> None:
    # 11-03 검토 — HWPX 는 목차의 쪽 번호(탭 뒤 글자)가 빠진다: 「I. 사업개요」 · 「Ⅳ. 제안서 작성 안내」만 남는다
    no_pages = re.sub(r"\t\d+", "", RFP)
    excerpt, _ = bid.rfp_excerpt(no_pages)
    assert len(excerpt) > 3000 and "2027년 1월 1일" in excerpt
    assert bid.project_terms(excerpt)["months"] == 12


def test_지침_문장_속_조견표_말은_평가_기준_머리가_아니다() -> None:
    text = "◯ 제안서 첫페이지에 [별첨1] 기술능력 평가항목별 조견표를 작성하여야 함\n" + RFP
    assert len(bid.read_evaluation(text)["items"]) == 15


def test_발췌는_사업_개요부터_제안서_작성_안내_앞까지이고_전화_줄이_없다() -> None:
    excerpt, rules = bid.rfp_excerpt(RFP)
    assert excerpt.startswith("사업 개요")
    assert "제안서 목차 및 작성 방법" not in excerpt and "기술능력평가 기준" not in excerpt
    assert not re.search(r"\d{2,3}\)?[\s-]\d{3,4}-\d{4}", excerpt)
    assert "모호한 표현은 평가 시 불가능한 것으로 간주" in rules


def test_사업_기간과_금액() -> None:
    terms = bid.project_terms(bid.rfp_excerpt(RFP)[0])
    # 2.10.0 T1 — 부가세 포함 · 별도(budget_vat) · 공고 원본 금액 칸 · 계약 예정일 일수 · 주차(D1) 칸이 늘었다(값이 없으면 None) ·
    # T8 — 입찰 마감(deadline · 제출서류 유효기간 기준일) · 참가자격등록 마감(T8 검토 · 보고서 엑셀 칸)
    assert terms == {"period": "2027년 1월 1일 ~ 2027년 12월 10일", "months": 12, "end": "2027-12", "start": "2027-1",
                     "end_date": "2027-12-10", "start_label": None, "budget": "275,000,000원(부가세 포함)", "budget_won": 275_000_000,
                     "budget_vat": "포함"}
    assert bid.stored_terms(terms) == {"period": "2027년 1월 1일 ~ 2027년 12월 10일", "start_label": None, "end": "2027-12-10",
                                       "budget": "275,000,000원(부가세 포함)", "budget_won": 275_000_000, "budget_vat": "포함",
                                       "assigned_budget": None, "estimated_price": None, "contract_from": None, "days": None, "weeks": None,
                                       "deadline": None, "qualification_deadline": None}


@pytest.mark.parametrize(("excerpt", "period", "end_date"), [
    # 표 머리줄 · 문서 목차 · 「계약기간 내 …」는 사업 기간 글이 아니다 — 표지 「사업기간」 줄에 그대로 실린다(2.8.0 검토 · 받아 둔 원문 20건 중 4건)
    ("계약기간\n계약금액\n2025.03~2025.12", None, None),
    ("수행 실적표: 계약기간 이행실적(금액)\n발주처", None, None),
    ("4. 사업기간 및 금액\t 3\n5. 과업 내용\t 4", None, None),
    # 「과업 기간」도 머리 — 뒤에 나오는 「계약기간 내 …」 대신 이 줄을 읽는다(1691972)
    ("나. 과업 기간 : 계약체결일로부터 2027년 2월 22일까지\n※ 계약기간 내 기자재 전략물자 판정 결과보고서 제출",
     "계약체결일로부터 2027년 2월 22일까지", "2027-02-22"),
    # 앞 자리가 기간 글이 아니면 다음 자리를 본다
    ("계약기간 이행실적\n□ 사업기간 : 계약일로부터 8개월", "계약일로부터 8개월", None),
])
def test_사업기간_글은_날짜나_개월이_읽히는_자리만(excerpt: str, period: str | None, end_date: str | None) -> None:
    terms = bid.project_terms(excerpt)
    assert terms["period"] == period and terms["end_date"] == end_date
    meta = bid.export_meta({"title": "시험", "agency": "가상기관", "terms": bid.stored_terms(terms)}, company="가상교육")
    rows = dict(meta["rows"])
    assert rows.get("사업기간") == period  # 표지에도 읽힌 기간만(없으면 줄이 없다)


@pytest.mark.parametrize(("excerpt", "end_date", "months"), [
    # 첫 날짜 바로 뒤가 「까지」면 그 날짜가 끝날 — 뒤 괄호의 중간 일정은 범위 끝이 아니다(2.8.0 검토 · 1766093 원문 꼴)
    ("아. 계약기간 : 계약일로부터 2027년 1월 8일까지(※ 개발 콘텐츠 1차 납품은 2026년 12월 17", "2027-01-08", None),
    ("사업기간: 계약일로부터 2027. 12. 15.까지(결과보고서는 2028. 1. 15.까지 제출)", "2027-12-15", None),
    # 둘째 날짜가 첫째보다 앞이면 범위가 아니다 — 첫 날짜 하나로 읽는다
    ("□ 사업기간: 계약체결일 ~ 2027. 12. 15.(교육 운영 2027. 3. ~ 2027. 11.)", "2027-12-15", None),
    ("사업기간: 계약일 ~ 2027년 12월 15일 (2026년 12월 착수 예정)", "2027-12-15", None),
    # 첫 날짜 앞에 「~ · 로부터」가 있으면 그 날짜가 끝날 — 뒤 괄호의 더 늦은 날짜도 범위 끝이 아니다(3차 검증 · 1779511 원문 꼴)
    ("나. 계약기간 : 계약체결일 ~ 2027년 1월 (현장실습 조사는 2027년 3월까지)", "2027-01", None),
    ("사업기간: 계약일 ~ 2027. 12. 15.(결과보고서는 2028. 1. 15.까지 제출)", "2027-12-15", None),
    ("사업기간: 계약체결일 ~ 2027. 12. 31. (하자보수기간 2032. 12. 31.)", "2027-12-31", None),
    # 「까지」가 붙은 첫 날짜가 착수 · 체결 기한이고 뒤에 진짜 끝날이 오면 범위다(괄호 안 부속 일정일 때만 첫 날짜)
    ("사업기간: 계약일(2027. 3. 31.까지 체결 예정) ~ 2027. 12. 31.", "2027-12-31", 10),
    ("사업기간: 2027. 3. 31.까지 착수하여 2027. 12. 31.까지 완료", "2027-12-31", 10),
    # 바른 범위는 그대로
    ("사업기간 : 2027. 1. 1. ~ 2027. 12. 31.", "2027-12-31", 12),
    ("사업기간: (2027. 1. 1.~2027. 12. 31.)을 기준으로 운영", "2027-12-31", 12),
])
def test_끝날은_범위의_끝이거나_까지가_붙은_날짜(excerpt: str, end_date: str, months: int | None) -> None:
    terms = bid.project_terms(excerpt)
    assert terms["end_date"] == end_date and terms["months"] == months


def test_종료일만_있는_사업기간은_끝날을_두고_개월_수는_짓지_않는다() -> None:
    """2.8.0 B6 — 「계약 체결일 ~ 2027년 12월 15일」 꼴은 종료일을 버려 「협약 기간 밖」 검사가 꺼졌다(11-11 조사 1 · 3위)."""
    terms = bid.project_terms("□ 사업기간 : 계약 체결일 ~ 2027년 12월 15일\n□ 사업금액 : 350,000,000원 (부가세 포함)  □ 기타")
    assert terms["months"] is None and terms["end"] == "2027-12" and terms["end_date"] == "2027-12-15"
    assert terms["start_label"] == "계약 체결일" and terms["start"] is None
    assert terms["budget"] == "350,000,000원 (부가세 포함)" and terms["budget_won"] == 350_000_000
    assert bid.project_terms("사업기간: 계약일로부터 2027. 12. 15.까지")["end_date"] == "2027-12-15"
    assert bid.project_terms("사업기간: 2027년 1월부터 12개월")["months"] == 12  # 날짜 하나 + 개월 수는 예전처럼
    form = bid.build_form([{"no": "Ⅰ", "title": "개요", "items": []}], {"items": []}, terms, title="시험")
    period = form["agreement_period"]
    assert period["open_start"] is True and period["months"] is None
    # 끝 쪽만 본다 — 끝 뒤는 「협약 기간 밖」 · 앞은 시작을 몰라 걸지 않는다
    window = bid.plan_validation.agreement_window(period)
    assert bid.plan_validation.outside_window("2028년 1월", window) == ["2028.1월"]
    assert bid.plan_validation.outside_window("2026년 3월", window) == []


@pytest.mark.parametrize(("excerpt", "won", "vat"), [
    # 11-13 동국대 — 맨 「사업비」 머리 · 숫자 앞 「금」(표지 사업금액 줄 · 금액 대조가 꺼져 있었다)
    ("나. 사업비 : 금40,700,000원(금사천칠십만원)(부가세 포함)", 40_700_000, "포함"),
    ("나. 기초금액 : 금40,700,000원(부가세 포함)", 40_700_000, "포함"),
    ("사업예산(기초금액) : 140,000,000원(부가가치세 포함)", 140_000_000, "포함"),
    ("□ 총사업비 : 일금 50,000,000원(VAT 별도)", 50_000_000, "별도"),
    ("□ 사업금액 : 350,000,000원 (부가세 포함)  □ 기타", 350_000_000, "포함"),
    ("사업금액: 40,700,000원", 40_700_000, None),
    # 「미포함 · 불포함」은 별도다(틈이 「미 · 불」을 삼켜 「포함」이 되던 것 · 11-13 T1 검토)
    ("사업예산 : 50,000,000원(부가세 미포함)", 50_000_000, "별도"),
    ("사업금액 : 50,000,000원(VAT 불포함)", 50_000_000, "별도"),
    # 일부 금액(앞에 다른 명사가 붙은 사업비)은 사업금액이 아니다
    ("- 교육 운영 사업비 3,000,000원", None, None),
    ("- 운영 사업비 : 1,000,000원", None, None),
])
def test_사업금액은_사업비_기초금액_금_꼴도_읽고_부가세_포함_별도를_남긴다(excerpt: str, won: int | None, vat: str | None) -> None:
    terms = bid.project_terms(excerpt)
    assert terms["budget_won"] == won and terms["budget_vat"] == vat


def test_사업금액_글이_20자에서_잘려_괄호가_닫히지_않으면_괄호_앞까지() -> None:
    # 1687776 「라. 용역금액 : 금148,244,000원(금일억사천팔백이십사만사천원, 부가세 포함)」 — 표지 사업금액 줄에 「…, 부가세」가 실렸다(11-13 T1 검토)
    terms = bid.project_terms("라. 용역금액 : 금148,244,000원(금일억사천팔백이십사만사천원, 부가세 포함)")
    assert terms["budget"] == "148,244,000원" and terms["budget_won"] == 148_244_000 and terms["budget_vat"] == "포함"
    # 닫힌 괄호는 그대로 둔다
    assert bid.project_terms("나. 사업비 : 금40,700,000원(금사천칠십만원)(부가세 포함)")["budget"] == "40,700,000원(금사천칠십만원)(부가세 포함)"


def test_공고_원본_금액_칸은_배정예산과_추정가격() -> None:
    # 나라장터 기본정보 — 배정예산(부가세 포함) · 추정가격(부가세 별도). 원문 글보다 먼저 쓴다(11-13 조사 바로잡음)
    assert bid.notice_budget({"assigned_budget": "40700000", "estimated_price": "37000000"}) == {
        "assigned_budget": 40_700_000, "estimated_price": 37_000_000}
    assert bid.notice_budget({}) == {"assigned_budget": None, "estimated_price": None}
    assert bid.notice_budget(None) == {"assigned_budget": None, "estimated_price": None}


def _notice_doc(text: str) -> dict[str, Any]:
    return {"name": "0_1. 입찰공고문.pdf", "role": "notice", "pages": [(2, text)], "text": text}


def test_계약_예정일은_공고문의_계약체결_이후_줄에서만() -> None:
    found = bid.contract_from([_notice_doc("② 제안서 평가 ▪ 제안서 평가 및 가격평가\n~26.11.18.(수)\n③ 계약체결 26.11.18.(수) 이후 ▪ 선정 업체 개별 통보")])
    assert found["date"] == "2026-11-18" and found["quote"].startswith("③ 계약체결") and found["page"] == 2
    assert bid.contract_from([_notice_doc("계약체결 2026. 12. 1. 이후 착수")])["date"] == "2026-12-01"
    # 「이후」가 없거나 날짜가 아니면 읽지 않는다(애매하면 놓친다)
    assert bid.contract_from([_notice_doc("③ 계약체결 26.11.18.(수)")]) is None
    assert bid.contract_from([_notice_doc("낙찰자는 계약 체결 후 30일 이내 착수")]) is None
    assert bid.contract_from([]) is None


@pytest.mark.parametrize(("period", "contract", "expect"), [
    # 동국대 — 계약 예정일 11-18 ~ 12-31 = 44일 · 6주(13주 미만이면 주차)
    ("다. 사업기간 : 계약체결일 ~ 2026. 12. 31.", "③ 계약체결 26.11.18.(수) 이후", {"contract_from": "2026-11-18", "days": 44, "weeks": 6}),
    # 1년짜리는 일수만(주차 꼴 아님)
    ("다. 사업기간 : 계약체결일 ~ 2027. 12. 31.", "③ 계약체결 26.11.18.(수) 이후", {"contract_from": "2026-11-18", "days": 409, "weeks": None}),
    # 끝날이 연-월뿐 · 범위(개월 수가 있음) · 계약 줄이 없으면 계산하지 않는다
    ("다. 사업기간 : 계약체결일 ~ 2026년 12월", "③ 계약체결 26.11.18.(수) 이후", {}),
    ("사업기간 : 2027. 1. 1. ~ 2027. 12. 31.", "③ 계약체결 26.11.18.(수) 이후", {}),
    ("다. 사업기간 : 계약체결일 ~ 2026. 12. 31.", "③ 선정 업체 개별 통보", {}),
])
def test_계약_예정일부터_고정_끝날까지_일수와_주차(period: str, contract: str, expect: dict[str, Any]) -> None:
    span = bid.contract_span(bid.project_terms(period), [_notice_doc(contract)])
    assert {k: span.get(k) for k in expect} == expect and (bool(span) == bool(expect))


def test_계약_일수_주차는_초안_사업_기본정보와_협약_기간에_싣는다() -> None:
    terms = {**bid.project_terms("다. 사업기간 : 계약체결일 ~ 2026. 12. 31.\n나. 사업비 : 금40,700,000원(부가세 포함)"),
             **bid.contract_span(bid.project_terms("다. 사업기간 : 계약체결일 ~ 2026. 12. 31."), [_notice_doc("③ 계약체결 26.11.18.(수) 이후")])}
    stored = bid.stored_terms(terms)
    assert stored["contract_from"] == "2026-11-18" and stored["days"] == 44 and stored["weeks"] == 6
    assert stored["budget_vat"] == "포함" and stored["assigned_budget"] is None
    period = bid.build_form([{"no": "Ⅰ", "title": "개요", "items": []}], {"items": []}, terms, title="시험")["agreement_period"]
    assert period["contract_from"] == "2026-11-18" and period["days"] == 44 and period["weeks"] == 6 and period["open_start"] is True
    # 옛 초안(새 칸 없음)도 그대로 읽는다
    assert bid.draft_terms({"terms": {"period": "계약체결일 ~ 2026. 12. 31.", "end": "2026-12-31"}})["period"] == "계약체결일 ~ 2026. 12. 31."


def test_작성_방법이_추진일정을_요구하면_계획_소항목에_일정표() -> None:
    """2.10.0 T2 — 11-13 동국대 Ⅳ-2 「사업 수행계획」(작성 방법 「추진방법, 추진일정 등」)에 일정표가 없어 주차 간트 · 핵심 마감 표가 붙을 곳이 없었다."""
    plan = {"no": "Ⅳ", "title": "사업수행계획 및 방법", "items": [
        {"no": "1", "title": "개요", "guide": ["- 사업 수행 방향, 범위 및 비전 제시"]},
        {"no": "2", "title": "사업 수행계획", "guide": ["- 구체적인 사업 추진체계, 추진방법, 추진일정 등"]}]}
    # 대항목 작성 방법이 마지막 소항목에 몰린 목차(1697240 「6. 산출물 내역」)에는 붙이지 않는다 — 제목이 계획 · 추진 · 일정 · 실행일 때만
    lumped = {"no": "Ⅲ", "title": "사업수행 부문", "items": [{"no": "6", "title": "산출물 내역", "guide": ["∙ 사업수행 내용 및 단계별 업무, 추진일정 등 기술"]}]}
    form = bid.build_form([lumped, plan], {"items": []}, {}, title="시험")
    assert [(t["key"], t["item"]) for t in form["tables"]] == [("schedule", "M2-2")]
    assert not bid.build_form([lumped], {"items": []}, {}, title="시험")["tables"]
    # 제목에 일정 낱말이 있으면 그 소항목이 먼저(지금 그대로)
    titled = {"no": "Ⅴ", "title": "사업 관리", "items": [{"no": "1", "title": "추진 일정 계획", "guide": []}]}
    assert [(t["key"], t["item"]) for t in bid.build_form([plan, titled], {"items": []}, {}, title="시험")["tables"]] == [("schedule", "M2-1")]


def _paged_fixture(name: str, doc_name: str, role: str) -> dict[str, Any]:
    """「=== n쪽 ===」 쪽 표식이 든 고정 자료 → 원문 문서(쪽마다)."""
    raw = (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")
    parts = re.split(r"^=== (\d+)쪽 ===$", raw, flags=re.M)
    pages = [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts), 2)]
    return {"name": doc_name, "role": role, "pages": pages, "text": "\n".join(body for _, body in pages)}


# 11-13 동국대 입찰공고문(받아 둔 PDF 글 그대로 · 연락처 · 번호 가림)
DONGGUK_NOTICE = _paged_fixture("bid_notice_dongguk_1113.txt", "1. 입찰공고문.pdf", "notice")


def test_입찰공고문_제출서류_목록과_제출_방법_줄() -> None:
    # 2쪽 「다. 제출서류 (…)」 머리 · ①~⑪ · 이어지는 줄 · 「※」 제출 방법 줄(파일 구분 · 용량 · 최종 확인 · 주민번호 가림)
    papers = bid.submission_papers([{"name": "2. 제안요청서.hwp", "role": "rfp", "pages": [(4, "다. 제출서류 : 입찰공고서 참조")],
                                     "text": "다. 제출서류 : 입찰공고서 참조"}, DONGGUK_NOTICE])
    assert len(papers) == 1
    found = papers[0]
    assert found["document"] == "1. 입찰공고문.pdf" and found["page"] == 2 and found["head"].startswith("다. 제출서류")
    assert [p["no"] for p in found["items"]] == list("①②③④⑤⑥⑦⑧⑨⑩⑪")
    assert found["items"][0] == {"no": "①", "text": "사업자등록증 1부", "subs": []}
    assert "완납증명서) 1부" in found["items"][4]["text"]  # 다음 줄로 이어진 항목
    assert "10%" in found["items"][8]["text"] and "보증기간 : 30일 이상" in found["items"][8]["text"]
    assert found["items"][10]["text"].startswith("제안서 전자파일")
    notes = " / ".join(found["notes"])
    assert len(found["notes"]) == 5 and "총 2개" in notes and "200MB" in notes and "최종입찰여부확인" in notes and "주민(법인)등록번호" in notes
    assert "가급적 마감일 전일까지" not in notes  # 머리 앞 ※ 줄은 아니다
    assert not any("제안서 제출 매뉴얼" in p["text"] for p in found["items"])  # 「라.」 줄은 항목이 아니다
    # 제출서류 머리가 없으면 빈 목록
    assert bid.submission_papers([_notice_doc("1. 입찰에 부치는 사항\n가. 공고명 : 시험")]) == []


def test_제출서류_머리_아래_다른_절_번호_목록은_서류가_아니다() -> None:
    # 1731641 꼴 — 「-」 서류 두 줄은 서류(11-13 「-」 글머리 목록)이고, 위 절 「4. 낙찰자 공고」 · 「5. 입찰무효」 · 「1) …」 무효 사유는 아니다
    hanyang = ("5) 제출서류(제안서, 입찰서류)\n- 제안서 전체본\n- 본교 소정양식 및 기관별 소정양식 일체의 입찰서류\n4. 낙찰자 공고 : 개별 연락\n"
               "5. 입찰무효 : 다음 각 호에 해당하는 입찰은 무효로 한다.\n1) 입찰 참가 자격이 없는 자가 한 입찰\n2) 대리권이 없는 자가 한 입찰")
    found = bid.submission_papers([_notice_doc(hanyang)])
    assert [[i["text"] for i in p["items"]] for p in found] == [["제안서 전체본", "본교 소정양식 및 기관별 소정양식 일체의 입찰서류"]]
    # 1781608 꼴 — 「○」 서류 · 「-」 하위 줄 · 쪽 가운데 절 번호 「8」에서 끝난다(뒤 절의 「○」 · 「11 불공정행위」 ①~⑤ 를 읽지 않는다)
    standard = ("나. 제출서류\n○ 정성제안서 1부\n○ 정량제안서 1부(기업신용평가등급확인서)\n○ 발표자료 1부\n"
                "○ 입찰참가자격 확인용 서류 각 1부(1개 파일로 일괄 스캔)\n- 조달청 경쟁입찰참가자격 등록증 사본 1부\n"
                "※ 국가계약법 시행규칙 제44조제1항 입찰무효 사항 확인용\n- 사업자등록증 사본 1부\n8\n제안서평가 기준 및 우선협상대상자 지정 등\n"
                "○ 제안서 평가에 관한 사항\n- 입찰등록업체에 한해 제안서 평가를 실시\n11\n불공정행위 금지\n① 금품·향응 등의 공여·약속\n② 입찰가격의 사전 협의")
    found = bid.submission_papers([_notice_doc(standard)])
    assert len(found) == 1 and [p["text"][:7] for p in found[0]["items"]] == ["정성제안서 1", "정량제안서 1", "발표자료 1부", "입찰참가자격 "]
    assert "사업자등록증 사본" in found[0]["items"][3]["text"]  # ※ 줄 뒤 「-」 줄도 앞 서류에
    assert found[0]["notes"] == ["국가계약법 시행규칙 제44조제1항 입찰무효 사항 확인용"]
    # 머리 아래 표시 없는 줄이 넷 넘게 이어지면 서류 목록이 없다
    lead = "다. 제출서류\n(아래 서류를 제출)\n각종 증명서는 원본\n유효기간을 확인하고\n스캔하여 올린다\n① 사업자등록증 1부"
    assert bid.submission_papers([_notice_doc(lead)]) == []
    assert len(bid.submission_papers([_notice_doc(lead.replace("스캔하여 올린다\n", ""))])[0]["items"]) == 1  # 셋까지는 머리 설명 줄


def test_조달청_표준_공고서_번호_없는_머리와_글머리_서류_목록() -> None:
    # 1805118 꼴 — 번호 없이 쌍점으로 끝나는 머리 「제안서 관련 제출서류:」 아래 ① 목록 · 「-」 줄은 앞 서류에 이어 붙음
    standard = ("3-1. 제출서류\n○\n‘국가종합전자조달시스템’에서 확인이 가능한 입찰참가자격은 별도의 서류를 제출할 필요가 없습니다.\n"
                "제안서 관련 제출서류:\n① 정성제안서 1부\n② 정량제안서 1부\n③ 발표자료 1부\n④ 기타문서 각 1부\n"
                "- 입찰참가자격 확인을 위한 서류: 제안요청서에서 요구한 경우 등 필요시 기타문서에 포함\n-\n제출장소: 국가종합전자조달시스템(나라장터)")
    found = bid.submission_papers([_notice_doc(standard)])
    assert [p["head"] for p in found] == ["제안서 관련 제출서류:"]
    assert [i["no"] for i in found[0]["items"]] == list("①②③④") and found[0]["items"][0]["text"] == "정성제안서 1부"
    # 문장 안의 「제출서류」(「※ 제출방법 : … 제출서류 일체」)는 머리가 아니다
    assert bid.submission_papers([_notice_doc("※ 제출방법 : 제안서, 발표자료 등 입찰공고에서 요구하는 제출서류 일체\n① 정성제안서 1부")]) == []
    # 1822864 꼴 — 「8. 입찰참가 신청서류」 아래 「-」 글머리 서류 · 위 꼴 번호 「9.」에서 끝
    dash = ("8. 입찰참가 신청서류\n- 입찰참가신청서(당 원 양식)\n- 제안서\n- 법인등기부등본\n- 입찰보증금(보증보험증권)\n"
            "9. 입찰보증금\n- 입찰금액의 5% 이상")
    found = bid.submission_papers([_notice_doc(dash)])
    assert [[i["text"] for i in p["items"]] for p in found] == [["입찰참가신청서(당 원 양식)", "제안서", "법인등기부등본", "입찰보증금(보증보험증권)"]]
    # 문장 머리(「계약담당자는 제출서류(…)에 대하여」) 아래 「-」 줄 · 첫 줄이 「일시 : …」 이름표 줄 · 문장인 「-」 줄은 서류 목록이 아니다
    rules = "마. 계약담당자는 제출서류(입찰보증금 포함)에 대하여 다음 규정을 적용합니다.\n- 전자입찰특별유의서\n- 입찰참가자격등록규정"
    assert bid.submission_papers([_notice_doc(rules)]) == []
    visit = "나. 제안서 및 입찰참가등록서류(가격제안서 포함) 제출\n- 일시 : 2026. 11. 24. (화)\n- 제출방법 : 방문접수만 허용"
    assert bid.submission_papers([_notice_doc(visit)]) == []
    assert bid.submission_papers([_notice_doc("가. 제출서류\n- 각종 증명서는 공고일 이후 발급분이어야 함\n각 1부")]) == []
    # 머리 괄호 · 꺾쇠 안 안내의 「는」은 문장 판정에서 뺀다(1811356)
    aside = "라. 제출 서류 <제출서류는 공고문 순서로 정리해주시기 바랍니다>\n- 사업제안서 7부\n- 제안서 제출 공문서 1부"
    assert [i["text"] for i in bid.submission_papers([_notice_doc(aside)])[0]["items"]] == ["사업제안서 7부", "제안서 제출 공문서 1부"]


def test_제출서류_목록은_번호가_되돌아가거나_끝_줄이면_끝나고_자격_절_제목은_머리가_아니다() -> None:
    # 1759644 꼴 — 「1. … 4. 기타서류」 뒤 「3. 입찰 참가자의 자격」(차례가 되돌아감)은 다음 장
    back = ("라. 제출서류\n1. 정성적 제안서 1부\n2. 정량적 제안서 1부\n3. 발표자료 1부\n4. 기타서류\n"
            "3. 입찰 참가자의 자격에 관한 사항\n4. 낙찰자 결정 방법")
    found = bid.submission_papers([_notice_doc(back)])
    assert [i["no"] for i in found[0]["items"]] == ["1.", "2.", "3.", "4."] and "자격" not in found[0]["items"][-1]["text"]
    # 1747255 꼴 — 「(서식6,」 다음 줄 「7) 각 1부」는 앞 항목의 줄바꿈 조각 · 1774718 꼴 — 같은 번호 두 번(「라.」 오타)은 이어 감 ·
    # 같은 머리 아래 ①로 다시 시작하는 둘째 목록도 이어 감
    wrap = "4. 제출서류\n1) 입찰참가신청서 1부\n2) 사업자등록증 1부\n3) 제안서 10부\n4) 실적증명서(제안요청서 서식6,\n2) 각 1부\n5) 수강료제안서 1부"
    items = bid.submission_papers([_notice_doc(wrap)])[0]["items"]
    assert [i["no"] for i in items] == ["1)", "2)", "3)", "4)", "5)"] and items[3]["text"].endswith("2) 각 1부")
    typo = "5. 구비서류\n가. 사업자등록증\n나. 완납증명서\n다. 입찰참가신청서\n다. 개인정보 동의서\n라. 확약서"
    assert [i["text"] for i in bid.submission_papers([_notice_doc(typo)])[0]["items"]][-1] == "확약서"
    again = "다. 제출서류 :\n① 정성제안서 1부\n② 발표자료 1부\n① 경쟁입찰참가자격등록증 1부\n② 법인등기부등본 1부"
    assert len(bid.submission_papers([_notice_doc(again)])[0]["items"]) == 4
    # 1748554 꼴 — 「끝. 상기와 같이 공고 함」은 한글 번호가 아니다
    end = "10. 제출서류\n가. 입찰참가신청서 1부\n나. 제안서 5부\n※ 제출서류는 유효한 서류\n끝.  상기와 같이 공고 함."
    assert [i["no"] for i in bid.submission_papers([_notice_doc(end)])[0]["items"]] == ["가.", "나."]
    # 1766093 꼴 — 「3. 입찰참가자의 자격(구비서류 등)에 관한 사항」은 자격 절 제목
    rule = "3. 입찰참가자의 자격(구비서류 등)에 관한 사항\n가. 「국가를 당사자로 하는 계약에 관한 법률 시행령」 제12조 …\n나. 부정당업자가 아닌 자"
    assert bid.submission_papers([_notice_doc(rule)]) == []
    # 첫 항목 전 「※ 기타 유의사항」 절 머리 뒤 번호 줄은 유의사항 문장이다
    note = "다. 제출서류\n※ 기타 유의사항\n1. 제출된 서류는 반환하지 않습니다\n2. 허위 서류는 무효로 합니다"
    assert bid.submission_papers([_notice_doc(note)]) == []
    # 원 번호 차례(「①」.isdigit() 이 참이라 int 가 멈추던 것) — 예산 과업 읽기도 같은 함수
    assert bid._task_mark("① 예산 계획 수립") == ("circled", ord("①")) and bid._task_mark("12. 기타") == ("dot", 12)
    assert bid.budget_tasks("① 교육 운영\n② 예산 계획 수립 및 집행\n③ 결과 보고") == ["① 교육 운영", "② 예산 계획 수립 및 집행", "③ 결과 보고"]


def test_참여인력_표_역할에_발주_쪽_역할은_넣지_않는다() -> None:
    units = [{"key": "M4-5", "plain": "사업수행조직", "guide": "수행조직 및 업무분장"}]
    sections = [{"key": "M4-5", "by": "llm", "sentences": [
        {"text": "- PM: 일정 · 품질 총괄, 발주부서 협의와 진행보고를 맡습니다."},
        {"text": "- 운영 담당: 교육 운영과 출결 관리를 맡습니다."},
        {"text": "- 발주부서: 설계안 · 자료 승인, 결과보고서 심의를 맡습니다."},
        {"text": "- 발주기관: 중간보고 검토와 승인을 맡습니다."}]}]
    assert [row[0] for row in bid.staff_roles(sections, units, None)] == ["PM", "운영 담당"]


def test_참여인력_표_역할은_조직_투입인력_소항목을_합치고_단계_비상대응_줄은_뺀다() -> None:
    # 11-14 평가: 참여인력 소항목 한 곳만 보아 투입 계획 소항목의 PM 이 빠졌고(1805118), 단계 줄이 역할이 됐고(1782790),
    # 비상대응 조직 줄(「- 운영인력: 대피 유도를 맡습니다」)이 섞일 뻔했다
    units = [{"key": "M4-4", "plain": "참여인력 현황", "guide": "참여인력"}, {"key": "M4-3", "plain": "투입인력 및 관리 계획", "guide": "투입 인력"},
             {"key": "M5-1", "plain": "비상대응계획", "guide": "비상대응 조직도"}]
    sections = [
        {"key": "M4-3", "by": "llm", "sentences": [{"text": "- PM: 사업 총괄과 발주기관 보고를 맡습니다."},
                                                  {"text": "- 교육운영 담당: 대상별 교육 운영을 맡습니다."},
                                                  {"text": "- 마무리(11~12개월차): 결과보고서 작성을 맡습니다."}]},
        {"key": "M4-4", "by": "llm", "sentences": [{"text": "- 운영 담당: 출결 관리를 맡습니다."}, {"text": "- 연구반 지원 담당: 회의 지원을 맡습니다."}]},
        {"key": "M5-1", "by": "llm", "sentences": [{"text": "- 운영인력: 현장 대피 유도와 신고를 맡습니다."}]}]
    rows = bid.staff_roles(sections, units, "M4-4")
    # 참여인력 소항목 먼저 · 「교육운영 담당」은 「운영 담당」을 품어 하나 · PM 은 맨 앞 · 단계 · 비상대응 줄 없음
    assert [row[0] for row in rows] == ["PM", "운영 담당", "연구반 지원 담당"]
    assert rows[0][1] == "사업 총괄과 발주기관 보고"


def test_조견표_근거_소제목은_평가_항목과_낱말이_겹치는_것() -> None:
    # 11-14 평가: 대항목에 짝지은 여러 행이 그 대항목의 앞 소제목 셋을 똑같이 받아 엉뚱한 문단을 가리켰다
    sections = [{"key": "M3-4", "major_key": "M3", "sentences": [
        {"text": "○ 세부 과제 체계"}, {"text": "본문"}, {"text": "○ 교육운영(대상별 교육 운영)"}, {"text": "○ 교육과정 분석 · 설계"},
        {"text": "○ 연구반 지원"}, {"text": "○ 검수와 품질관리"}]}]
    develop = {"name": "교육개발 역량", "criteria": ["교육과정 분석 및 후보주제 도출 · 교육과정 설계"]}
    research = {"name": "연구반운영역량", "criteria": ["연구반 구성 및 운영의 적정성"]}
    assert bid._heads_of(["M3-4"], sections, develop) == "교육과정 분석 · 설계"
    assert bid._heads_of(["M3-4"], sections, research) == "연구반 지원"
    # 겹치는 낱말이 없으면 소항목 짝은 앞 소제목 · 대항목 짝뿐이면 빈 글 · 항목을 주지 않으면 예전대로 앞 셋
    nothing = {"name": "산업재해", "criteria": []}
    assert bid._heads_of(["M3-4"], sections, nothing).startswith("세부 과제 체계")
    assert bid._heads_of(["M3"], sections, nothing) == ""
    assert bid._heads_of(["M3-4"], sections) == "세부 과제 체계 · 교육운영(대상별 교육 운영) · 교육과정 분석 · 설계"


def test_제출서류_하위_번호는_그_서류_묶음의_하위_서류이고_현장설명_준비서류는_아니다() -> None:
    # 1718694 꼴 — 「가. 입찰 참가 서류」 아래 「1) …」이 하위 서류 · 다음 머리 번호 「4.」에서 끝
    nested = ("3. 제출서류 (사본은 원본대조필 날인하여 제출)\n가. 입찰 참가 서류 (전자 및 오프라인 제출 필수)\n1) 입찰참가신청서 1부\n"
              "2) 사업자등록증 사본 1부\n나. 발표 및 평가 서류\n1) 제안서 원본 1부, 사본 5부\n- 제안업체 일반현황 및 연혁\n"
              "2) 가격제안서 및 세부 산출내역서 각 1부\n4. 입찰보증금 및 귀속\n가. 입찰참가자격등록 마감일시까지 …")
    items = bid.submission_papers([_notice_doc(nested)])[0]["items"]
    assert [(i["no"], [s["no"] for s in i["subs"]]) for i in items] == [("가.", ["1)", "2)"]), ("나.", ["1)", "2)"])]
    assert items[1]["subs"][0]["text"] == "제안서 원본 1부, 사본 5부 - 제안업체 일반현황 및 연혁"
    # 1691972 꼴 — 「3-2.」 갈래 절 · 가로줄에서 끝난다
    dash = "라. 제출서류 : (반드시 학교에 제출)\n① 입찰참가신청서 1부.\n② 사용인감계 1부.\n3-2. 입찰참가자격등록 및 제안서 : 학교방문 후 제출\n————————\n4. 주요공지사항"
    assert [i["text"] for i in bid.submission_papers([_notice_doc(dash)])[0]["items"]] == ["입찰참가신청서 1부.", "사용인감계 1부."]
    # 1699556 꼴 — 현장설명 준비서류(인감도장 지참)는 제출서류가 아니다
    assert bid.submission_papers([_notice_doc("6. 현장설명 준비서류 (미지참시 현장설명 참석 불가)\n가. 인감도장\n나. 재직증명서")]) == []


def test_동국대_입찰공고문_계약_예정일() -> None:
    found = bid.contract_from([DONGGUK_NOTICE])
    assert found["date"] == "2026-11-18" and found["page"] == 1 and "계약체결" in found["quote"]


def test_동국대_원문으로_쓰면_양식_계약_일수_금액이_초안에_남는다(monkeypatch: pytest.MonkeyPatch) -> None:
    rfp_doc = _paged_fixture("bid_rfp_dongguk_1113.txt", "2. 제안요청서.hwp", "rfp")
    _fake_writer(monkeypatch)
    source = {**_source(rfp_doc["text"]), "docs": [rfp_doc, DONGGUK_NOTICE],
              "notice_budget": bid.notice_budget({"assigned_budget": "40700000", "estimated_price": "37000000"})}
    draft = bid.generate(source=source, company=COMPANY)
    assert draft["format"]["blind"] and draft["format"]["page_limit"] == 25
    assert draft["outline_source"] == "rfp" and draft["evaluation_total"] == 80
    terms = draft["terms"]
    assert terms["contract_from"] == "2026-11-18" and terms["days"] == 44 and terms["weeks"] == 6
    assert terms["budget_won"] == 40_700_000 and terms["budget_vat"] == "포함"
    assert terms["assigned_budget"] == 40_700_000 and terms["estimated_price"] == 37_000_000
    assert draft["form"]["agreement_period"]["weeks"] == 6


# ---------------------------------------------------------------------------
# 쓰기
# ---------------------------------------------------------------------------


def test_대항목마다_한_번씩_부르고_보내는_본문은_허용_목록뿐(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_writer(monkeypatch)
    # 증빙 메모가 「미확인」인 실적은 외부 사용 「가능」이어도 근거 후보가 아니다(2.8.0 B7)
    company = {**COMPANY, "ledger_all": [*COMPANY["ledger_all"], {"seq": 11, "title": "증빙 미확인 실적", "year": "2025", "field": "공공·지자체",
                                                                  "agency": "OO군", "external_use": "가능", "evidence_note": "계약서 미확인"}]}
    draft = bid.generate(source=_source(), company=company)
    # 일반현황(칸) · 조직 및 인원(사람)만 있는 Ⅱ 는 부르지 않는다 — 대항목 7개 중 6번
    assert len(calls) == 6
    sent = "\n".join(c["user"] + c["system"] for c in calls)
    for secret in ("062-000-1111", "시험로 123", "12345", "증빙메모-가", "비밀 메모", "공개하지 않는 실적", "시험회사", "증빙 미확인 실적", "ledger:11"):
        assert secret not in sent
    assert "OO대학교 AI 실무 교육" in sent and "ledger:3" in sent
    # 원장 「주관 · 발주 · 협력기관」 한 칸은 역할을 모르는 agency 로 보낸다(발주기관 client_agency 로 보내 협력기관이 발주처가 됐다 · 2.8.0 B7)
    assert '"agency": "OO대학교"' in sent and '"client_agency"' not in sent
    assert "사업 이해도" in sent  # 평가 기준이 함께 간다
    # 정량 · 정성 구분도(원문에서 읽은 값) — 「배점이 가장 큰 정성 항목」을 AI 가 가를 근거(T3 검토 · m3)
    assert '"kind": "정성"' in sent
    assert draft["outline_source"] == "rfp" and draft["evaluation_total"] == 100


def test_확인_필요와_지어낸_회사_주장은_본문에서_빠지고_모호한_표현은_경고(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_writer(monkeypatch, units={"M1-1": [
        {"text": "당사는 수료생 취업지원 프로그램을 운영합니다.", "type": "AI_SUGGESTION"},
        {"text": "세부 일정은 발주기관과 확인이 필요합니다.", "type": "AI_SUGGESTION"},
        {"text": "필요 시 추가 상담을 제공할 수 있습니다.", "type": "AI_SUGGESTION"},
        {"text": "당사는 사이버보안 취업지원 사업을 수행한 경험을 바탕으로 운영합니다.", "type": "AI_SUGGESTION"},
        {"text": "당사는 보안 기업 300곳 네트워크를 보유하고 있습니다.", "type": "COMPANY_EVIDENCE_GROUNDED", "source_ids": []},
        {"text": "당사는 OO대학교가 발주한 AI 실무 교육을 운영했습니다.", "type": "COMPANY_EVIDENCE_GROUNDED",
         "source": "OO대학교 AI 실무 교육", "source_ids": ["ledger:3"]},
    ]})
    draft = bid.generate(source=_source(), company=COMPANY)
    body = [s for sec in draft["sections"] if sec["key"] == "M1-1" for s in sec["sentences"]]
    texts = [s["text"] for s in body]
    assert "세부 일정은 발주기관과 확인이 필요합니다." not in texts
    assert not any("수행한 경험" in t or "300곳" in t for t in texts)
    assert "당사는 OO대학교가 발주한 AI 실무 교육을 운영했습니다." in texts
    vague = next(s for s in body if s["text"].startswith("필요 시"))
    assert any(f.startswith(bid.FLAG_VAGUE) for f in vague["flags"])
    whys = [b["why"] for b in draft["blanks"]]
    assert "세부 일정은 발주기관과 확인이 필요합니다." in whys
    assert any("300곳" in w for w in whys) and any("수행한 경험" in w for w in whys)
    assert not any("확인 필요" in t or "확인이 필요" in t for sec in draft["sections"] for t in (s["text"] for s in sec["sentences"]))


def test_대항목_하나가_실패해도_나머지는_남는다(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_writer(monkeypatch, fail=("사업수행부문",))
    draft = bid.generate(source=_source(), company=COMPANY)
    by_key = {s["key"]: s for s in draft["sections"]}
    assert by_key["M3-4"]["by"] == "rules" and by_key["M3-4"]["llm_error"]
    assert by_key["M3-4"]["sentences"][0]["text"].startswith("(담당자 입력) — ")
    assert by_key["M1-1"]["by"] == "llm"
    assert "실패 소항목 5개" in draft["llm_note"] and "첫 사유: 시험 — 이 대항목은 실패" in draft["llm_note"]


def test_AI_가_꺼져_있으면_목차와_빈칸만(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "plan_writer_ready", lambda writer="claude": (False, "Claude CLI 로그인 안 됨"))
    draft = bid.generate(source=_source(), company=COMPANY)
    assert draft["generated_by"] == "rules" and "Claude CLI 로그인 안 됨" in draft["llm_note"]
    assert all(s["by"] == "rules" for s in draft["sections"])


def test_목차가_없는_제안요청서는_표준_목차로(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_writer(monkeypatch)
    text = RFP.split("제안서 작성 안내")[0]  # 제안서 작성 안내 장(목차 · 평가 기준)이 없는 원문
    draft = bid.generate(source=_source(text), company=COMPANY)
    assert draft["outline_source"] == "standard" and draft["evaluation_total"] is None
    assert [s["major_title"] for s in draft["sections"]][0] == "Ⅰ. 제안 개요"  # 평가 기준이 없으면 조견표도 없다


def test_지침_문장이_목차를_가리켜도_그_뒤의_목차를_읽는다() -> None:
    text = RFP.replace("□ 제안서 목차 및 작성 방법", "□ 작성 안내")
    assert len(bid.read_outline(text)) == 7


def test_일반현황은_AI_없이_칸으로_두고_회사자료로_채운다(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_writer(monkeypatch)
    draft = bid.generate(source=_source(), company=COMPANY)
    general = next(s for s in draft["sections"] if s["key"] == "M2-1")
    assert general["kind"] == "fields" and [f["label"] for f in general["fields"]] == list(bid.GENERAL_FIELDS)
    filled = plan_fill_service.apply(draft, {"name": "시험회사", "opened_on": "2021. 04. 15.", "history": "2021.07 사회적기업 인증"})
    values = {f["label"]: f["value"] for f in next(s for s in filled["sections"] if s["key"] == "M2-1")["fields"]}
    assert values["기관명"] == "시험회사" and values["설립년월일"] == "2021. 04. 15." and values["주요 연혁"] == "2021.07 사회적기업 인증"
    assert not any(b["field"] == "기관명" for b in filled["blanks"])
    people = next(t for t in draft["tables"] if t["key"] == "people")
    assert people["human_only"] and all(cell == "(담당자 입력)" for cell in people["rows"][0])


def test_조견표는_평가항목_배점과_AI_가_다뤘다는_목차를_싣는다(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_writer(monkeypatch, evals={"M3-4": ["취업지원 프로그램 운영", "없는 항목"], "M5-1": ["비상대응 계획"]})
    draft = bid.generate(source=_source(), company=COMPANY)
    assert draft["sections"][0]["kind"] == "table_only"
    table = next(t for t in draft["tables"] if t["key"] == bid.EVAL_TABLE_KEY)
    rows = {row[1]: row for row in table["rows"]}
    assert rows["취업지원 프로그램 운영"][2:4] == ["10점", "Ⅲ-4"]  # 다섯째 칸 「제안서 근거(소제목)」(2.10.0 T7 m5 — 예전 단언은 [2:])
    # 원문 라틴 「V」는 로마 숫자 글자 「Ⅴ」로 — 조견표 · 대항목 제목에서 「Ⅲ」 글자와 섞이지 않게(11-06 심사)
    assert rows["비상대응 계획"][3] == "Ⅴ-1"
    assert "Ⅴ. 안전 및 보건 준수사항" in [s["major_title"] for s in draft["sections"]]
    assert rows["사업 이해도"][3] == "(담당자 입력)"


def test_n_n_소항목_조견표_번호는_그_번호_그대로이고_서식_소항목은_AI_에_보내지_않는다() -> None:
    # 11-06 3차 검토 #19 · #21 — 1731641 꼴: 조견표가 「1.1」 · 「1.2」를 모두 「1-1」로 썼고, 붙임서식 · 견적서 소항목이 AI 본문으로 갔다
    outline = bid.read_outline("□ 제안서 목차\n1. 제안사 사업현황\n1.1. 제안사 사업현황 (【붙임서식 1호】참조)\n1.2. 재무건정성(【붙임서식 2호】참조)\n"
                               "1.3. 유사사업 수행 경험\n2. 사업수행 부문\n2.1. 기술 제안서\n2.2. 가격 제안서\n"
                               "2.3. 견적서 (구축 예산과 운영 예산을 구분)\n3. 기타 사항\n3.1. 추가 제안 사항 및 아이디어")
    form = bid.build_form(outline, {}, {}, title="시험")
    assert [bid.unit_number(form, key) for key in ("M1-1", "M1-3", "M2-1", "M2-3", "M3-1")] == ["1.1", "1.3", "2.1", "2.3", "3.1"]
    units = {u["key"]: u for u in bid.form_units(form)}
    assert [k for k, u in units.items() if u["human"]] == ["M1-1", "M1-2", "M2-2", "M2-3"]
    # 서식 이름만 싣는다 — 「(【붙임서식 2호】참조)」의 괄호 · 「참조」는 빼고(4차 확인)
    assert units["M1-2"]["form"] == "붙임서식 2호" and units["M2-2"]["form"] == "제안요청서 서식"
    roman = bid.build_form(bid.read_outline(
        "□ 제안서 목차\nⅠ. 제안서 요약 ※ <서식8> 참조하여 자율 작성\nⅡ. 제안 업체 일반 사항\n1. 입찰 참가 신청서 <서식1> ※ 원본 별도 제출\n"
        "2. 일반 현황 및 연혁 <서식3>\n3. 주요 사업 실적 <서식4>\n4. 경영상태(신용평가 등급 심사) 자료 ※ 증빙서류 별도 제출\n5. 서약서 <서식6>\n"
        "6. 보안각서 <서식7>\nⅢ. 사업 수행\n1. 교육 운영\nⅣ. 사업 관리\n1. 일정\nV. 안전 및 보건\n1. 비상대응 계획"), {}, {}, title="시험")
    kinds = {u["title"]: ("서식" if u["form"] else "사람" if u["human"] else u["kind"]) for u in bid.form_units(roman)}
    assert kinds == {"제안서 요약": "item", "1. 입찰 참가 신청서": "서식", "2. 일반 현황 및 연혁": "fields", "3. 주요 사업 실적": "서식",
                     "4. 경영상태(신용평가 등급 심사) 자료": "서식", "5. 서약서": "서식", "6. 보안각서": "서식", "1. 교육 운영": "item",
                     "1. 일정": "item", "1. 비상대응 계획": "item"}
    # 「자율 작성」 대항목은 그 번호만 · 라틴 「V」는 「Ⅴ」(제목 · 조견표 모두)
    assert [bid.unit_number(roman, key) for key in ("M1", "M2-5", "M5-1")] == ["Ⅰ", "Ⅱ-5", "Ⅴ-1"]
    assert roman["sections"][4]["title"] == "Ⅴ. 안전 및 보건"
    forms = {u["plain"]: (u["form"], u["form_order"]) for u in bid.form_units(roman) if u["form"]}
    assert forms["입찰 참가 신청서"] == ("<서식1>", "원본 별도 제출") and forms["경영상태(신용평가 등급 심사) 자료"] == ("제안요청서 서식", "증빙서류 별도 제출")


def test_서식_소항목_자리_줄에는_서식_이름만_싣고_원문_지시는_빈칸_목록으로(monkeypatch: pytest.MonkeyPatch) -> None:
    # 4차 확인 — 제출용에 「서식 첨부: <서식1> ※ 원본 별도 제출」 · 「서식 첨부: (【붙임서식 1호】참조)」가 실렸고,
    # 빈칸 목록은 「제안요청서 서식((【붙임서식 1호】참조))」 · 「제안요청서 서식(제안요청서 서식)」이었다(1690926 · 1731641)
    _fake_writer(monkeypatch)
    rfp = RFP.replace("◦ 제안사의 조직 및 인원현황 근거제시\n", "◦ 제안사의 조직 및 인원현황 근거제시\n3. 입찰 참가 신청서 <서식1> ※ 원본 별도 제출\n"
                      "4. 재무건정성(【붙임서식 2호】참조)\n5. 가격 제안서\n", 1)
    draft = bid.generate(source={**_source(), "text": rfp}, company=COMPANY)
    lines = [s["text"] for sec in draft["sections"] for s in sec["sentences"] if "서식 첨부" in s["text"]]
    assert lines == ["(담당자 입력) — 서식 첨부: <서식1>", "(담당자 입력) — 서식 첨부: 붙임서식 2호", "(담당자 입력) — 서식 첨부: 제안요청서 서식"]
    whys = [b["why"] for b in draft["blanks"] if b["why"].startswith("서식 첨부")]
    assert whys == ["서식 첨부 — 제안요청서 서식(<서식1>)을 채워 붙이세요 · 원문 지시: ※ 원본 별도 제출",
                    "서식 첨부 — 제안요청서 서식(붙임서식 2호)을 채워 붙이세요", "서식 첨부 — 제안요청서 서식을 채워 붙이세요"]
    submit = plan_export_service.document_blocks(draft, draft["form"], variant="submit", meta=bid.export_meta(draft, company="시험회사"))
    text = repr(submit)
    assert "※" not in text and "【" not in text and "참조" not in text


def test_대항목_하나뿐인_목차는_개요_분량으로_줄이지_않는다() -> None:
    # 11-06 3차 검토 #20 — 1690465 「Ⅰ. 제안내용」 하나에 가~마: 본문 전체가 700자(개요 분량)로 줄었다
    single = bid.build_form(bid.read_outline("□ 제안서 목차\nⅠ. 제안내용\n가. 점검내용\n나. 점검방법\n다. 감리일정 및 절차\n라. 감리인력\n"
                                             "마. 기타 지원사항 등"), {}, {}, title="시험")
    assert [u["target"] for u in bid.form_units(single)] == ["default"] * 5
    assert [bid.unit_number(single, u["key"]) for u in bid.form_units(single)] == ["Ⅰ-가", "Ⅰ-나", "Ⅰ-다", "Ⅰ-라", "Ⅰ-마"]
    two = bid.form_units(bid.build_form(bid.read_outline("□ 제안서 목차\nⅠ. 제안 개요\n1. 제안 목적\nⅡ. 사업 수행\n1. 교육 운영\n2. 세부과제별 추진방안"),
                                        {}, {}, title="시험"))
    assert [u["target"] for u in two] == ["overview", "default", "task"]


#: 1805118 꼴 — 별첨 서식 장(「[별첨1]」 다음 줄 이름)과 입찰 · 계약 서식 장(서식 목록 + 괄호 붙은 서식 본문 머리).
FORMS = """VI  제안 관련 별첨 서식
[별첨1]
제안사 일반현황
□ 일반사항
[별첨2]
업무별 인력 투입계획
[별첨3]
투입인력 이력사항
VII  입찰 및 계약 관련 서식
[서식 1호] 개인정보수집이용동의서(제안서 발표평가 발표자 및 참석자 대상 작성)
[별지 1호] 비밀유지협약서
[별지 2호] 표준 개인정보처리위탁 계약서
[서식 1호] 개인정보수집이용동의서(제안서 발표평가 발표자 및 참석자 대상 작성)
개인정보 수집․이용 동의서
[별지 1호] 비밀유지 협약서(계약상대자 대상 작성)
비밀유지 협약서
[별지 2호] 표준 개인정보처리위탁 계약서(계약상대자 대상 작성)
"""
#: 1805118 규격서 466 · 641행 꼴 — 원문이 붙이라고 한 입증 자료(4차 #3).
PROOFS = """○ 유의사항
- 제안서의 내용을 객관적으로 입증할 수 있는 관련 자료는 제안서의 붙임으로 제출
주)  1. 1인이 자격증을 여러 개 소지한 경우 상위 1개만 작성 요망
4. 자격증, 경력 및 수행업무와 관련된 사항을 증명할 수 있는 자료를 붙임으로 첨부하여야 하며, 첨부되지 않은 자료에 대하여는 인정하지 않음
- 사업자등록증 사본을 붙임으로 제출
"""


def test_제출_서류_목록_소항목은_원문_서식_머리로_표를_만들고_AI_에_보내지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    # 11-06 심사 ② — 「Ⅶ. 기타(별지서식 자료 · 제출 서류 목록을 작성 및 붙임)」를 AI 가 써서 우리 제출 절차 문장이 본문이 됐다
    calls = _fake_writer(monkeypatch)
    source = {**_source(), "docs": [bid._text_doc(RFP, name="제안요청서"), bid._text_doc(FORMS, name="서식", role="other")]}
    draft = bid.generate(source=source, company=COMPANY)
    assert len(calls) == 5 and not any("Ⅶ. 기타" in c["purpose"] for c in calls)
    annex = next(t for t in draft["tables"] if t["key"] == bid.ANNEX_TABLE_KEY)
    # 원문 [별첨1] 「기술능력 평가항목별 조견표」는 문서 맨 앞 조견표가 맡는다 · 계약 · 발표평가 서식은 검토 메모로
    # 붙임 4 = 시험 원문(1786460) 「…입증할 수 있는 관련 자료 … 별첨 자료로 제출」(4차 #3)
    assert annex["rows"] == [["붙임 1", "제안사 일반현황", "[별첨1]"], ["붙임 2", "업무별 인력 투입계획", "[별첨2]"], ["붙임 3", "투입인력 이력사항", "[별첨3]"],
                             ["붙임 4", "제안서 내용 입증 자료", "—"]]
    other = next(s for s in draft["sections"] if s["major_title"] == "Ⅶ. 기타")
    assert other["tables"] == [bid.ANNEX_TABLE_KEY] and other["sentences"][0]["text"] == "제안서와 함께 내는 서류는 다음과 같습니다."
    notes = [i for n in draft["removed_notes"] for i in n["items"]]
    assert "[서식 1호] 개인정보수집이용동의서 — 발표평가 때 제출" in notes and "[별지 2호] 표준 개인정보처리위탁 계약서 — 계약 때 제출" in notes
    # 4차 #7 — 검토용 문서가 이 메모를 「고치지 못한 약점」으로 그렸다(옛 저장본은 review_notes 에 있다)
    for saved in (draft, {**draft, "review_notes": draft["removed_notes"], "removed_notes": []}):
        memo = [b[1] for b in plan_export_service.document_blocks(saved, saved["form"], variant="review", meta=bid.export_meta(saved, company="시험회사"))
                if b[0] == "memo"]
        assert "제출용에서 뺀 문장 · 나중에 내는 서식(기타): [별지 2호] 표준 개인정보처리위탁 계약서 — 계약 때 제출" in memo
        assert not any(str(line).startswith("고치지 못한 약점") for line in memo)
    blocks = plan_export_service.document_blocks(draft, draft["form"], variant="submit", meta=bid.export_meta(draft, company="시험회사"))
    head = blocks.index(("h1", "Ⅶ. 기타"))
    assert blocks[head + 2][0] == "table" and blocks[head + 2][1]["rows"][0][1] == "제안사 일반현황"
    # 서식 머리 줄을 못 찾으면 지금처럼 AI 가 쓴다(시험 원문의 [별첨1]은 조견표뿐)
    assert bid.annex_rows([bid._text_doc(RFP)], built=("조견표",)) == ([], [])


def test_붙임_표에_원문이_요구한_입증_자료를_더하고_빈칸_목록에도_올린다(monkeypatch: pytest.MonkeyPatch) -> None:
    # 4차 #3 — 표가 [별첨n] 서식 셋뿐이라 「…증명할 수 있는 자료를 붙임으로 첨부 · 첨부되지 않은 자료는 인정하지 않음」이 사라졌다(1805118 · 1786460)
    _fake_writer(monkeypatch)
    proofs = {**bid._text_doc(PROOFS, name="규격서", role="spec"), "pages": [(31, PROOFS)]}
    source = {**_source(), "docs": [bid._text_doc(RFP, name="제안요청서"), bid._text_doc(FORMS, name="서식", role="other"), proofs]}
    draft = bid.generate(source=source, company=COMPANY)
    annex = next(t for t in draft["tables"] if t["key"] == bid.ANNEX_TABLE_KEY)
    # 같은 서류명(「제안서 내용 입증 자료」)은 처음 원문 줄만 · 입증 낱말이 없는 「사업자등록증 사본을 붙임으로 제출」은 아니다
    # 원문 서식이 없는 서류라 셋째 칸은 「—」 — 제출용에 앱의 원문 쪽 표기를 싣지 않는다(4차 검토)
    assert annex["rows"][3:] == [["붙임 4", "제안서 내용 입증 자료", "—"], ["붙임 5", "자격증, 경력 및 수행업무 증명 자료", "—"]]
    blocks = plan_export_service.document_blocks(draft, draft["form"], variant="submit", meta=bid.export_meta(draft, company="시험회사"))
    assert not re.search(r"원문 \d+쪽", str(blocks))
    proof = [b for b in draft["blanks"] if b["field"] == "붙임 증빙"]
    # 검토용 빈칸 글은 어느 문서인지 이름과 함께 · 한글 문서는 「(근사)」 쪽
    assert [b["why"] for b in proof] == [
        "제안요청서 1쪽 ‘기술적인 설명자료 또는 제안서의 내용을 객관적으로 입증할 수 있는 관련 자료의 내용이 많을 경우 제안서의 별첨 자료로 제출하여야 함’",
        "규격서 31쪽 ‘자격증, 경력 및 수행업무와 관련된 사항을 증명할 수 있는 자료를 붙임으로 첨부하여야 하며, 첨부되지 않은 자료에 대하여는 인정하지 않음’"]
    assert bid._where_label({"name": "사전규격 규격서 1 > 제안요청서.hwpx"}, 17) == "사전규격 규격서 1 > 제안요청서.hwpx 17쪽(근사)"
    assert bid._where_label({"name": "제안요청서.pdf"}, 9) == "제안요청서.pdf 9쪽"
    assert {b["section"] for b in proof} == {"기타"}
    # 서류명은 원문 낱말로 — 앞 마디 · 주어 · 줄 머리 번호는 뗀다(367건 원문 꼴)
    assert [bid._proof_name(line) for line in (
        "라. 허위사실이 발견되면 계약을 해지할 수 있으며, 제안서의 내용을 객관적으로 입증할 수 있는 관련 자료는 제안서의 별첨으로 제출하여야 합니다.",
        "제안사는 기술제안서의 내용을 객관적으로 입증할 수 있는 관련 자료를 제안서의 별첨으로 제출하여야 함.",
        "2.8. 수행계획서 내용을 객관적으로 입증할 수 있는 관련 자료는 별첨으로 제출",
        "실적증명자료는 붙임으로 첨부하여야 하며 실적증명첨부서류에 페이지를 명시")] == [
        "제안서 내용 입증 자료", "기술제안서 내용 입증 자료", "수행계획서 내용 입증 자료", "실적증명자료"]


def test_사람_몫_표가_딸린_소항목은_표_위에_빈칸_줄을_또_찍지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    # 11-06 심사 ③ — 「(담당자 입력)」 줄 + 「조직 및 인원 현황」 표의 「(담당자 입력)」 칸이 겹쳤다
    _fake_writer(monkeypatch)
    draft = bid.generate(source=_source(), company=COMPANY)
    org = next(s for s in draft["sections"] if s["key"] == "M2-2")
    assert [s["text"] for s in org["sentences"]] == ["조직 및 인원 현황은 다음 표와 같습니다."]
    assert not any(b["section"] == org["section"] and b["why"] == "본문 — 담당자 입력" for b in draft["blanks"])
    blocks = plan_export_service.document_blocks(draft, draft["form"], variant="submit", meta=bid.export_meta(draft, company="시험회사"))
    at = next(i for i, b in enumerate(blocks) if b[0] == "h2" and b[1] == org["section"])
    assert blocks[at + 1][1][0][0] == "조직 및 인원 현황은 다음 표와 같습니다." and blocks[at + 2][0] == "table"


def test_다른_대항목_목록을_함께_보내고_참여인력에는_회사_실적을_쓰지_않게_한다(monkeypatch: pytest.MonkeyPatch) -> None:
    # 11-06 심사 ④ ⑤ — 대항목마다 따로 쓰니 다른 대항목의 문장 · 실적이 되풀이됐고, 「참여인력」 절에 회사 실적이 들어갔다
    calls = _fake_writer(monkeypatch)
    bid.generate(source=_source(), company=COMPANY)
    first = next(c for c in calls if c["purpose"] == "bid_plan:Ⅰ. 제안개요")
    # 2.7.0 — 다른 대항목 줄은 원문 경계 표식 안에 있다(표식 줄은 뺀다)
    others = [line for line in first["user"].split("다른 대항목(그 대항목이 맡는 내용은 여기서 쓰지 않습니다):\n", 1)[1].split("\n사업(JSON)", 1)[0].splitlines()
              if not line.startswith("<<<")]
    assert others[0] == "- Ⅱ. 제안사 일반: 일반현황 · 조직 및 인원" and not any(line.startswith("- Ⅰ.") for line in others)
    # 2.9.0 — 참여인력은 역할별 투입 시기 · 방식 · 담당 과업만(조직 · 협업 설명은 수행조직 소항목에서만 · 3차 지시서 §11)
    assert "참여인력 소항목은 역할(PM · 운영인력 등)별 투입 시기 · 참여 방식 · 담당 과업만 쓰고 회사 실적은 쓰지 않습니다" in first["system"]
    assert "「수행조직」 · 「참여인력」" not in first["system"]


def _s(text: str, *ids: str) -> dict[str, Any]:
    return {"text": text, "type": "COMPANY_EVIDENCE_GROUNDED" if ids else "AI_SUGGESTION", "source_ids": list(ids), "flags": []}


def test_절_사이_같은_문장과_이미_쓴_회사_근거와_빈_소제목은_뺀다() -> None:
    # 11-06 심사 ③ ④ — 1805118 실측: Ⅰ-1 ↔ Ⅲ-1 같은 문장 · ledger:16 이 세 절에 · 아래 문장이 모두 빠진 「○ 공동수급·하도급」
    form = bid.build_form([{"no": "Ⅰ", "title": "제안개요", "guide": [], "items": [{"no": "1", "title": "제안 목적", "guide": []}]},
                           {"no": "Ⅲ", "title": "사업수행부문", "guide": [], "items": [{"no": "1", "title": "개요", "guide": []}]},
                           {"no": "Ⅵ", "title": "기타", "guide": ["◦ 기타 제출 서류 목록을 작성 및 붙임"], "items": []}], {}, {}, title="시험")
    first = [_s("○ 제안 목적"), _s("- 당사는 정보주체의 개인정보 보호 인식을 높이고 개인정보처리자의 보호 역량을 강화하겠습니다."),
             _s("- 당사는 OO대학교가 발주한 AI 실무 교육을 운영했습니다.", "ledger:3")]
    second = [_s("○ 사업 목적"), _s("- 당사는 정보주체의 개인정보 보호 인식을 높이고, 개인정보처리자의 보호 역량을 강화하겠습니다."),
              _s("○ 공동수급·하도급"), _s("○ 당사 실적"), _s("- 당사의 OO대학교 재학생 실무 교육 운영 경험을 과정 설계에 반영합니다.", "ledger:3"),
              _s("- 대상별 과정은 온라인 이론과 오프라인 실습을 이어 운영합니다.")]
    annex = [_s("- OO대학교 AI 실무 교육 수행 증빙", "ledger:3")]
    sections = [{"key": "M1-1", "section": "1. 제안 목적", "by": "llm", "sentences": first},
                {"key": "M2-1", "section": "1. 개요", "by": "llm", "sentences": second},
                {"key": "M3", "section": "기타", "by": "llm", "sentences": annex}]
    notes = bid.tidy_sections(sections, form, exempt={"M3"})
    assert [s["text"] for s in sections[0]["sentences"]] == [s["text"] for s in first]
    assert [s["text"] for s in sections[1]["sentences"]] == ["○ 당사 실적", "- 대상별 과정은 온라인 이론과 오프라인 실습을 이어 운영합니다."]
    assert [n.split(" — ")[0] for n in notes["1. 개요"]] == ["Ⅰ-1 과 같은 문장이라 뺐습니다", "Ⅰ-1 에서 이미 쓴 회사 근거(ledger:3)라 뺐습니다"]
    assert len(sections[2]["sentences"]) == 1 and "기타" not in notes  # 붙임 목록 소항목은 같은 실적을 다시 적는다


def _tidy_form() -> dict[str, Any]:
    outline = bid.read_outline("□ 제안서 목차 및 작성 방법\nⅠ. 제안개요\n1. 제안 목적\no 본 제안의 목적 및 목표 제시\n2. 제안의 특징 및 장점\n"
                               "o 제안의 특징 및 장점 요약 기술\nⅡ. 사업수행부문\n1. 개요\n◦ 본 사업의 수행에 관한 대략적인 개요를 기술\n"
                               "2. 추진목표 및 전략\n◦ 본 사업의 추진목표 및 전략을 제시\nⅢ. 사업관리부문\n1. 참여인력 및 이력사항\n"
                               "◦ 본 사업을 수행할 인력을 작업 단위별로 제시\n2. 기밀보안사항\n◦ 본 사업과 관련한 기밀 및 보안관리 방안 제시")
    return bid.build_form(outline, {}, {}, title="시험")


def _entries(**units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"key": key, "section": key, "by": "llm", "sentences": sentences} for key, sentences in units.items()]


def test_같은_문장은_그_내용을_맡은_절에_남긴다() -> None:
    # 4차 #2 — 늘 뒤 문장을 지워 추진목표 절이 「(목표 1)」을, 기밀보안 절이 「폐기하거나 반납」을 잃었다(1786460 · 1805118 실제 초안)
    goal = "26년 수료생 대상 27년 목표 취업률 78.3% 이상을 달성하겠습니다."
    sections = _entries(**{
        "M1-1": [_s("○ 제안 목표"), _s(f"- 당사는 {goal}"), _s("- 협약기업 네트워크를 유지하며 신규 협약기업을 늘리겠습니다.")],
        "M2-1": [_s("○ 성과 목표"), _s(f"- 당사는 {goal}"), _s("- 과정별 교육기간에 맞춰 상담 주기를 정합니다.")],
        "M2-2": [_s("○ 추진 목표"), _s(f"- (목표 1) {goal}"), _s("- (목표 2) 취업현황을 1~2개월 주기 유선 조사로 갱신하겠습니다."),
                 _s("○ 전략 5. 보안 내재화"), _s("- 수강 대상 증빙 등 개인정보는 필요한 항목만 받고 접근권한을 제한하겠습니다."),
                 _s("- 사업 종료 시 취득 자료는 발주기관 보안 담당자 입회 아래 폐기하거나 반납하겠습니다.")],
        "M3-2": [_s("○ 사업 종료 시 처리"), _s("- 당사는 사업 종료 시 취득 자료를 발주기관 보안 담당자 입회하에 완전 폐기하거나 반납하겠습니다."),
                 _s("- 폐기·반납 내역은 확인서로 남겨 발주기관에 제출합니다.")],
    })
    notes = bid.tidy_sections(sections, _tidy_form())
    kept = {e["key"]: [s["text"] for s in e["sentences"]] for e in sections}
    assert f"- (목표 1) {goal}" in kept["M2-2"] and kept["M2-2"][2].startswith("- (목표 2)")  # 목표 목록이 「(목표 1)」부터
    assert not any(goal in t for t in kept["M1-1"] + kept["M2-1"])  # 개요 · 목적 쪽 같은 문장은 뺀다
    assert "- 당사는 사업 종료 시 취득 자료를 발주기관 보안 담당자 입회하에 완전 폐기하거나 반납하겠습니다." in kept["M3-2"]
    assert not any("폐기하거나 반납" in t for t in kept["M2-2"]) and "○ 전략 5. 보안 내재화" in kept["M2-2"]
    assert any(n.startswith("Ⅲ-2 과 같은 문장이라 뺐습니다") for n in notes["M2-2"])


def test_뺀_문장을_가리키는_다음_문장도_빼고_모두_빠지면_첫_문장은_남긴다() -> None:
    # 4차 #6 — 「○ 당사 교육 운영 실적」 아래 실적 두 줄이 빠지고 「- 이 온·오프라인 연계 운영 방식을 …」만 남았다(1805118 Ⅳ-4)
    # 전체 확인 — 문장이 모두 빠진 소항목은 맨 「(담당자 입력)」 줄로 떨어져 사람 몫 표와 겹쳤다
    first = [_s("○ 당사 역량"), _s("- 당사는 OO대학교가 발주한 AI 실무 아카데미를 온라인·오프라인 연계로 운영했습니다.", "ledger:3"),
             _s("- 이 연계 운영 방식을 개인정보처리자 과정에 적용하겠습니다.")]
    people = [_s("○ 작업 단위별 투입 인력"), _s("- (PM) 사업 전 기간 투입해 일정·품질·보안과 보고를 총괄합니다."),
              _s("○ 당사 교육 운영 실적"), _s("- 당사는 OO대학교가 발주한 AI 실무 아카데미를 온라인·오프라인 연계로 운영했습니다.", "ledger:3"),
              _s("- 이 온·오프라인 연계 운영 방식을 개인정보처리자·전문관리자 과정에 적용합니다.")]
    only = [_s("○ 사업 종료 시 처리"), _s("- 당사는 OO대학교가 발주한 AI 실무 교육에서 보안 서약을 받아 운영했습니다.", "ledger:3")]
    sections = _entries(**{"M1-2": first, "M3-1": people, "M3-2": only})
    notes = bid.tidy_sections(sections, _tidy_form())
    assert [s["text"] for s in sections[1]["sentences"]] == ["○ 작업 단위별 투입 인력", "- (PM) 사업 전 기간 투입해 일정·품질·보안과 보고를 총괄합니다."]
    assert notes["M3-1"][-1].startswith("앞 문장을 뺀 자리라 함께 뺐습니다")
    assert [s["text"] for s in sections[2]["sentences"]] == [s["text"] for s in only] and "M3-2" not in notes


def test_번호_없는_목표_줄도_추진목표_절에_남고_메모는_지금_남은_자리를_가리킨다() -> None:
    # 4차 검토 — 「(목표 n)」 머리가 없으면 Ⅰ-1 작성 방법의 「목표」 한 낱말로 비겨 추진목표 절이 성과지표를 잃었고,
    # 뒤에서 Ⅰ-1 문장을 다시 빼면 Ⅱ-1 메모 「Ⅰ-1 과 같은 문장」이 빠진 자리를 가리켰다
    goal = "26년 수료생 대상 27년 목표 취업률 78.3% 이상을 달성하겠습니다."
    sections = _entries(**{
        "M1-1": [_s("○ 제안 목표"), _s(f"- 당사는 {goal}"), _s("- 협약기업 네트워크를 유지하며 신규 협약기업을 늘리겠습니다.")],
        "M2-1": [_s("○ 성과 목표"), _s(f"- 당사는 {goal}"), _s("- 과정별 교육기간에 맞춰 상담 주기를 정합니다.")],
        "M2-2": [_s("○ 추진 목표"), _s(f"- {goal}"), _s("- 취업현황을 1~2개월 주기 유선 조사로 갱신하겠습니다.")],
    })
    notes = bid.tidy_sections(sections, _tidy_form())
    kept = {e["key"]: [s["text"] for s in e["sentences"]] for e in sections}
    assert kept["M2-2"][1] == f"- {goal}" and not any(goal in t for t in kept["M1-1"] + kept["M2-1"])
    assert [n.split(" — ")[0] for n in notes["M1-1"] + notes["M2-1"]] == ["Ⅱ-2 과 같은 문장이라 뺐습니다"] * 2


def test_작성_방법이_기타에_몰린_목차에서도_전용_절이_제_문장을_지킨다() -> None:
    # 4차 검토 — 1802078 은 사업관리 작성 방법 일곱 줄이 모두 「기타」에 붙어, 「기타」가 「사업」 · 「월간」으로 이겨 업무보고 · 기밀보안 절이 문장을 잃었다
    form = bid.build_form([{"no": "Ⅳ", "title": "사업관리 부문", "guide": [], "items": [
        {"no": "1", "title": "업무보고", "guide": []}, {"no": "2", "title": "기밀보안", "guide": []},
        {"no": "3", "title": "기타", "guide": ["◦ 사업기간 동안 이루어질 보고 및 검토계획을 상세하게 제시", "- 월간 보고 및 최종 완료보고 등",
                                              "◦ 본 사업과 관련한 기밀 및 보안관리 방안 제시"]}]}], {}, {}, title="시험")
    report = "- 매월 5일까지 월간 보고서를 제출하고 발주기관 담당자와 검토 회의를 엽니다."
    secure = "- 사업 종료 시 취득 자료는 발주기관 보안 담당자 입회 아래 폐기하거나 반납하겠습니다."
    sections = _entries(**{"M1-1": [_s("○ 월간 보고"), _s(report)], "M1-2": [_s("○ 사업 종료 시 처리"), _s(secure)],
                           "M1-3": [_s("○ 기타"), _s(report), _s(secure), _s("- 발주기관이 요청하면 추가 자료를 7일 안에 냅니다.")]})
    bid.tidy_sections(sections, form)
    kept = {e["key"]: [s["text"] for s in e["sentences"]] for e in sections}
    assert report in kept["M1-1"] and secure in kept["M1-2"]
    assert kept["M1-3"] == ["○ 기타", "- 발주기관이 요청하면 추가 자료를 7일 안에 냅니다."]


def test_첫_문장을_되살리면_그_문장을_가리키는_문장도_되살린다() -> None:
    # 4차 검토 — [앞 절과 같은 실적 A, 「이 …」 P]뿐인 소항목에서 A 만 되살아나 이 사업에 적용하는 유일한 새 문장 P 가 사라졌다
    record = "- 당사는 OO대학교가 발주한 AI 실무 아카데미를 온라인·오프라인 연계로 운영했습니다."
    only = [_s("○ 관련 실적과 적용"), _s(record, "ledger:3"), _s("- 이 연계 운영 방식을 개인정보 보호 교육의 온라인 수료 후 오프라인 실습에 적용하겠습니다.")]
    sections = _entries(**{"M1-2": [_s("○ 당사 역량"), _s(record, "ledger:3")], "M3-1": only})
    notes = bid.tidy_sections(sections, _tidy_form())
    assert [s["text"] for s in sections[1]["sentences"]] == [s["text"] for s in only] and "M3-1" not in notes


def test_11_06_심사_결함_넷() -> None:
    # 11-06 심사(1805118 이번 판) — 표지 「(조달청 대행)」 · 「설립 + 사업영역」 문장 · 하도급 없음 단정 · 붙임 표에 빠진 인력 소속 증빙
    meta = bid.export_meta({"title": "시험", "agency": "한국인터넷진흥원(조달청 대행)"}, company="시험회사")
    assert dict(meta["rows"])["발주기관"] == "한국인터넷진흥원"
    blanks: list[dict[str, str]] = []
    dropped: list[str] = []
    texts = {"profile:domains": "공공 위탁교육 및 과정개발", "profile:founded": "2021"}
    domains = "- 당사는 2021년에 설립했고 공공 위탁교육 및 과정개발을 사업영역으로 합니다."
    staff = "- 제안사 소속 외 인력은 하도급으로 간주하는 기준을 지켜, 참여인력은 당사 소속 직원으로 구성하겠습니다."
    pm = "- PM은 공고일 이전부터 제안서 평가일까지 계속 재직 중인 당사 소속 직원으로 배치하겠습니다."
    kept, moved = bid.bid_filter([_s(domains, "profile:founded", "profile:domains"), _s(staff), _s(pm)], blanks, "참여인력",
                                 sources=[RFP], company_texts=texts, dropped=dropped)
    assert [s["text"] for s in kept] == [pm] and moved == 1  # PM 자격 요건을 지킨다는 문장은 남는다
    assert dropped == [f"{bid.DROP_DOMAINS} — {domains}"] and blanks[0]["field"] == "회사가 정할 사항"
    line = "3. 투입인력은 입찰자 소속 임직원이어야 하며, 투입인력 소속 확인을 위한 증빙서류(재직증명서, 경력증명서, 4대보험 가입확인서 등) 추가 증빙서류 제출 필요"
    doc = {**bid._text_doc(line, name="사전규격 규격서 1(R26BD00288735)"), "format": "hwpx", "pages": [(17, line)]}
    assert bid.proof_lines([doc]) == [("투입인력 소속 확인 증빙서류(재직증명서, 경력증명서, 4대보험 가입확인서 등)",
                                       "사전규격 규격서 1(R26BD00288735) 17쪽(근사)", line[3:])]


def test_제출_절차_그물은_제출_서류를_다루는_소항목에서_켠다() -> None:
    # 4차 검토 — 제목이 「기타」와 똑같을 때만 켜서 「Ⅵ. 첨부자료」 · 「5. 증빙자료」 · 「기타 지원사항 등」의 제출 절차 문장이 본문에 남았다
    def unit(plain: str, major: str = "Ⅵ. 기타", guide: str = "") -> dict[str, Any]:
        return {"plain": plain, "major_title": major, "guide": guide, "annex": False}

    assert bid.submit_unit(unit("첨부자료", "Ⅵ. 첨부자료"))
    assert bid.submit_unit(unit("사업실적(계약서 또는 납품실적증명서)", "5. 증빙자료"))
    assert bid.submit_unit(unit("기타 지원사항 등", "Ⅰ. 제안내용", "※ 제안서 첨부문서(감리원 일정현황표 …)는 제안서 뒤편에 같이 제본하여 제출"))
    assert bid.submit_unit(unit("기타", guide="◦ 제안서 이외의 입찰 참가를 위한 별지서식 자료, 기타 제출 서류 목록을 작성 및 붙임"))
    assert bid.submit_unit(unit("기타사항", "Ⅳ. 기타사항", "필요에 의해 제시한 내용"))
    assert bid.submit_unit({**unit("교육 운영 방안", "Ⅲ. 사업수행"), "annex": True})
    # 사업관리 · 추가 제안을 모은 「기타」 · 과업 소항목은 본문이다
    assert not bid.submit_unit(unit("기타", "Ⅳ. 사업관리 부문", "◦ 사업 추진일정을 상세히 제시 ◦ 본 사업을 수행할 조직 및 업무 분장"))
    assert not bid.submit_unit(unit("기타", "Ⅱ. 수행계획", "‧ 기타 본 과업과 관련하여 지원할 사항의 내용 기술 및 추가 제안"))
    assert not bid.submit_unit(unit("교육 운영 방안", "Ⅲ. 사업수행부문"))


@pytest.mark.parametrize("text", [
    "- 모든 증명서는 제출일 기준 유효기간을 점검하고, 사본은 원본과 대조한 뒤 편철합니다.",
    "- 인력 증빙에 담긴 주민등록번호 뒷자리 등 평가에 불필요한 개인정보는 가린 뒤 제출합니다.",
    "- 붙임 전자파일은 암호를 걸어 보관하고, 열람 권한은 제안 담당자로 한정합니다.",
    "- 붙임 서류는 아래 순서로 묶고, 맨 앞에 서류명 · 부수 · 쪽 번호를 적은 제출 서류 목록표를 둡니다.",
    "- 제안요청서 「Ⅶ. 입찰 및 계약 관련 서식」의 서식을 서식 번호 순서로 편철합니다.",
])
def test_우리_제출_절차_문장은_빈칸_목록이_아니라_그냥_뺀다(text: str) -> None:
    # 11-06 심사 ② — 1805118 「○ 제출 서류 관리」 세 문장 · 「붙임 서류 구성」이 제출용 본문이 됐다
    blanks: list[dict[str, str]] = []
    dropped: list[str] = []
    kept, moved = bid.bid_filter([_s(text)], blanks, "기타", sources=[RFP], dropped=dropped, annex=True)
    assert kept == [] and moved == 0 and blanks == [] and dropped == [f"{bid.DROP_SUBMIT} — {text}"]


@pytest.mark.parametrize("text", [
    "- 개인정보 파일은 암호화해 저장하고, 접근 권한은 담당자로 한정하며 열람·출력 기록을 남깁니다.",
    "- 수강생 개인정보가 담긴 서류는 암호를 걸어 보관하고 열람 권한을 최소화합니다.",
    "- 결과보고서의 수강생 개인정보는 가린 뒤 제출합니다.",
    "- 교육은 사전 안내, 이론, 실습, 평가의 아래 순서로 진행합니다.",
    # 4차 #4 — 과업 · 결과물 · 보안 절의 정상 문장(제출 절차 그물은 붙임 · 기타 소항목에만)
    "- 결과보고서는 A4 크기로 제본·편철해 인쇄본 10부와 전자파일을 함께 제출합니다.",
    "- 우즈베키스탄어 매뉴얼 요약본은 책자 형태로 편철·제본해 납품하겠습니다.",
    "- 수강 대상자 증빙서류(재직증명서 등)는 열람 권한을 운영사무국 담당자로 한정합니다.",
    "- 교육 실적 증빙자료(출석부·사진)는 열람 권한을 담당자로 한정하고 반출을 막습니다.",
    "- 수료증명서 발급 대장은 주민등록번호를 가린 뒤 제출합니다.",
])
def test_보안_절_정상_문장은_제출_절차_그물에_걸리지_않는다(text: str) -> None:
    kept, _ = bid.bid_filter([_s(text)], [], "기밀보안사항", sources=[RFP], dropped=(dropped := []))
    assert [s["text"] for s in kept] == [text] and dropped == []


def test_역량_이름_사업영역만_근거인_회사_경험과_해_왔_꼴은_뺀다() -> None:
    # 11-06 심사 ⑤ — 「RAG와 챗봇 기술을 개발에 적용해 왔습니다」(근거 skill: 뿐) · 「사업영역으로 두고 있습니다」(profile:domains 뿐)가 남았다
    assert bid.is_company_claim("당사는 교육을 운영해 왔습니다.") and bid.is_company_claim("당사는 교육을 운영하여 왔으며")
    blanks: list[dict[str, str]] = []
    dropped: list[str] = []
    texts = {"skill:RAG": "RAG", "skill:챗봇": "챗봇", "skill:생성형 AI 교육": "생성형 AI 교육", "profile:domains": "공공 위탁교육 및 과정개발",
             "profile:cert:사회적기업": "사회적기업"}
    kept, moved = bid.bid_filter([
        _s("- 당사는 RAG와 챗봇 기술을 개발에 적용해 왔습니다.", "skill:RAG", "skill:챗봇"),
        _s("- 당사는 사회적기업으로서 취약계층 교육을 수행했습니다.", "profile:cert:사회적기업"),
        _s("- 당사는 공공 위탁교육 및 과정개발을 사업영역으로 두고 있습니다.", "profile:domains"),
        _s("- 당사는 생성형 AI 교육 역량을 살려 실습 과정을 설계하겠습니다.", "skill:생성형 AI 교육"),
    ], blanks, "특징 및 장점", sources=[RFP], company_texts=texts, dropped=dropped)
    assert [s["text"] for s in kept] == ["- 당사는 생성형 AI 교육 역량을 살려 실습 과정을 설계하겠습니다."]
    assert moved == 2 and all(b["field"] == "회사 근거 없는 회사 주장" for b in blanks)
    assert dropped == [f"{bid.DROP_DOMAINS} — - 당사는 공공 위탁교육 및 과정개발을 사업영역으로 두고 있습니다."]
    # 4차 #5 — 「활용해 온라인」은 지난 경험이 아니고, 인증 근거로 인증 취득 자체를 말하는 문장은 남는다
    texts |= {"profile:cert:프리미엄 훈련기관": "프리미엄 훈련기관"}
    keep = [_s("- 당사는 생성형 AI 교육 역량을 활용해 온라인 실습 과정을 운영하겠습니다.", "skill:생성형 AI 교육"),
            _s("- 당사는 RAG 기술을 적용해 온라인 상담 도구를 만들겠습니다.", "skill:RAG"),
            _s("- 당사는 2023년 사회적기업 인증을 취득했습니다.", "profile:cert:사회적기업"),
            _s("- 당사는 사회적기업 인증을 받았습니다.", "profile:cert:사회적기업"),
            _s("- 당사는 고용노동부 프리미엄 훈련기관 지정을 획득하였습니다.", "profile:cert:프리미엄 훈련기관"),
            # 4차 검토 — 가운뎃점을 띄운 「활용해 온 · 오프라인」 · 인증 + 역량 근거 문장의 인증 취득 동사
            _s("- 당사는 생성형 AI 실습 도구를 활용해 온 · 오프라인 연계 실습을 운영하겠습니다.", "skill:생성형 AI 교육"),
            _s("- 당사는 사회적기업 인증을 취득했으며 RAG 기술을 교육 과정에 적용하겠습니다.", "profile:cert:사회적기업", "skill:RAG")]
    kept, moved = bid.bid_filter(keep, [], "특징 및 장점", sources=[RFP], company_texts=texts)
    assert [s["text"] for s in kept] == [s["text"] for s in keep] and moved == 0
    # 인증 근거여도 인증 동사 말고 지난 실적 동사가 남으면 그대로 옮긴다
    kept, moved = bid.bid_filter([_s("- 당사는 사회적기업 인증을 획득했으며 취약계층 교육을 운영했습니다.", "profile:cert:사회적기업")], [],
                                 "특징 및 장점", sources=[RFP], company_texts=texts)
    assert kept == [] and moved == 1


# ---------------------------------------------------------------------------
# 문서
# ---------------------------------------------------------------------------


def _docx_text(payload: bytes) -> str:
    document = Document(io.BytesIO(payload))
    parts = [p.text for p in document.paragraphs]
    parts += [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    return "\n".join(parts)


def test_제출용_워드에는_확인_필요_표식_검토_메모가_없다(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_writer(monkeypatch, units={"M1-1": [
        {"text": "당사는 OO대학교가 발주한 AI 실무 교육을 운영했습니다.", "type": "COMPANY_EVIDENCE_GROUNDED",
         "source": "OO대학교 AI 실무 교육", "source_ids": ["ledger:3"]},
        {"text": "확인 필요 — 담당자가 채울 내용입니다.", "type": "AI_SUGGESTION"},
    ]})
    draft = bid.generate(source=_source(), company=COMPANY)
    meta = bid.export_meta(draft, company="시험회사")
    submit = _docx_text(plan_export_service.build_docx(draft, draft["form"], title=draft["title"], variant="submit", meta=meta))
    for banned in ("확인 필요", "[공고]", "[회사]", "AI 덧붙임", "검토용", "검토 메모", "채택된 회사 근거자료"):
        assert banned not in submit
    assert "제안서" in submit and "Ⅰ. 제안개요" in submit and "1. 제안 목적" in submit
    # 표지는 수요기관 이름만 — 화면 표시값 「(조달청 대행)」은 싣지 않는다(11-06 심사)
    assert "기술능력 평가항목별 조견표" in submit and "발주기관" in submit and "한국인터넷진흥원" in submit and "조달청 대행" not in submit
    assert "1. 결과 활용성 부문" not in submit  # 제안요청서 번호를 그대로 — 앱 번호를 덧붙이지 않는다
    review = _docx_text(plan_export_service.build_docx(draft, draft["form"], title=draft["title"], variant="review", meta=meta))
    assert "검토용" in review and "검토 메모" in review
    name = plan_export_service.export_file_name(draft["title"], "docx", variant="submit", doc_kind=bid.DOC_KIND)
    assert name.startswith("제안서_제출용_")


def _hwpx_text(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        section = zf.read("Contents/section0.xml").decode("utf-8")
    return html.unescape("".join(re.findall(r"<hp:t>([^<]*)</hp:t>", section)))


def test_한글_HWPX_는_워드와_같은_글을_싣고_제출용에는_표식이_없다(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_writer(monkeypatch, units={"M1-1": [
        {"text": "당사는 OO대학교가 발주한 AI 실무 교육을 운영했습니다.", "type": "COMPANY_EVIDENCE_GROUNDED",
         "source": "OO대학교 AI 실무 교육", "source_ids": ["ledger:3"]},
    ]})
    draft = bid.generate(source=_source(), company=COMPANY)
    meta = bid.export_meta(draft, company="시험회사")
    built = {v: plan_hwpx_service.build_hwpx(draft, draft["form"], title=draft["title"], variant=v, meta=meta) for v in ("submit", "review")}
    for payload in built.values():
        report = validate_hwpx(payload)
        assert report.zip_ok and report.required_members_ok and report.xml_ok and report.mimetype_ok, report
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            assert zf.namelist()[0] == "mimetype" and zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
            section = zf.read("Contents/section0.xml").decode("utf-8")
            meta_xml = zf.read("Contents/content.hpf").decode("utf-8") + zf.read("version.xml").decode("utf-8")
        assert section.count("<hp:tc ") == section.count("<hp:cellAddr ")
        # 문서 정보 지은이 · 만든 프로그램에 도구 이름이 남지 않는다(한글 문서 정보 · 한글로 만든 PDF 지은이 · 11-04 검토)
        assert "BidPilot" not in meta_xml and '<opf:meta name="creator" content="text"/>' in meta_xml
        # 본문 자리는 워드 판과 같은 위 22 · 아래 20mm — 한글은 위 = 위 여백 + 머리말(11-04 검토: 34mm 에서 시작했다)
        mm = plan_hwpx_service.mm
        assert f'header="{mm(10)}" footer="{mm(10)}"' in section and f'top="{mm(12)}" bottom="{mm(10)}"' in section
    submit, review = _hwpx_text(built["submit"]), _hwpx_text(built["review"])
    for banned in ("확인 필요", "[공고]", "[회사]", "AI 덧붙임", "검토용", "검토 메모", "(근거:"):
        assert banned not in submit
    assert "당사는 OO대학교가 발주한 AI 실무 교육을 운영했습니다." in submit and "Ⅰ. 제안개요" in submit and "기술능력 평가항목별 조견표" in submit
    assert "한국인터넷진흥원" in submit and "조달청 대행" not in submit
    # 워드 판과 같은 블록 — 블록이 싣는 글은 모두 HWPX 에도 있다
    for block in plan_export_service.document_blocks(draft, draft["form"], variant="submit", meta=meta):
        text = plan_export_service._block_text(block)
        if text and block[0] in plan_export_service.TEXT_KINDS:
            assert plan_export_service._clean(text) in submit
    assert "검토용 — 제출하지 마세요" in review and "검토 메모 — 제출용 파일에는 없습니다" in review


def _tables(section: str) -> list[tuple[int, str, int]]:
    """표마다 (행 수, 글자처럼 취급, 칸 좌우 여백)."""
    found = re.findall(r'<hp:tbl [^>]*rowCnt="(\d+)"[^>]*>.*?<hp:pos treatAsChar="(\d)".*?<hp:inMargin left="(\d+)"', section)
    return [(int(rows), char, int(side)) for rows, char, side in found]


def test_HWPX_작은_표는_한_쪽에_긴_표는_행으로_나누고_월별_칸은_여백을_줄인다() -> None:
    def table(n: int) -> tuple:
        return ("table", {"title": f"표 {n}", "columns": ["구분", "내용"], "rows": [[f"행{i}", "값"] for i in range(n)]})

    grid = {"title": "월별", "columns": ["추진 내용"] + [f"{m}월" for m in range(1, 37)], "rows": [["착수"] + ["■"] * 36], "grid": True}
    fields = [("field", f"칸{i}", "값", "") for i in range(9)]  # 칸 표 — 두 칸씩 한 줄 → 5행
    section = plan_hwpx_service.section_xml([table(6), table(7), ("table", grid), *fields], review=False)
    tables = _tables(section)
    # 워드 판 규칙과 같다 — 본문 6행 이하 · 칸 8행 이하는 통째로(쪽 끝에 표 제목 · 머리줄만 남던 것) · 긴 표는 행 단위로 나눔(쪽 아래로 넘치던 것)
    # 긴 표는 제목이 첫 행이라 한 행 더(2.10.0 T7 layout8 — 예전 단언은 (8, "0"))
    assert [(rows, char) for rows, char, _ in tables] == [(7, "1"), (9, "0"), (2, "1"), (5, "1")]
    assert section.count('pageBreak="TABLE"') == section.count("<hp:tbl ")
    # 36개월 칸 표는 칸 여백을 줄이고 머리를 작은 글자로 — 칸 폭 3.6mm 에 좌우 1.8mm 여백이면 표가 쪽 밖으로 넘쳤다(11-04 검토)
    assert tables[2][2] < tables[0][2] and f'charPrIDRef="{plan_hwpx_service.C["grid_head"]}"' in section
    assert "<hp:t>36</hp:t>" in section and "<hp:t>36월</hp:t>" not in section  # 3mm 칸에서 「36월」이 잘렸다 — 숫자만


def test_HWPX_긴_표는_제목을_표_첫_행으로_두고_머리와_함께_되풀이() -> None:
    """2.10.0 T7(layout8) — 떠 있는 긴 표(본문 7행 이상)에는 앞 문단 「다음과 함께」가 걸리지 않아 11-13 수정본 9쪽 「< 주차별 추진 일정 >」
    제목만 쪽 끝에 남았다. 제목을 테두리 없는 병합 첫 행으로 넣고 머리 두 줄(제목 + 칸 이름)을 쪽마다 되풀이한다. 작은 표는 제목 문단 그대로."""
    def table(n: int) -> tuple:
        return ("table", {"title": f"표 {n}", "columns": ["구분", "내용", "비고"], "rows": [[f"행{i}", "값", ""] for i in range(n)]})

    section = plan_hwpx_service.section_xml([table(6), table(7), ("table", {"title": "", "columns": ["가", "나"], "rows": [["1", "2"]] * 8})],
                                            review=False)
    small, long, untitled = re.findall(r"<hp:tbl .*?</hp:tbl>", section, flags=re.S)
    assert "&lt; 표 6 &gt;" not in small and section.index("&lt; 표 6 &gt;") < section.index(small)  # 작은 표 — 제목 문단(다음과 함께)
    assert section.count("&lt; 표 7 &gt;") == 1 and "&lt; 표 7 &gt;" in long
    first = re.search(r"<hp:tr>(.*?)</hp:tr>", long, flags=re.S).group(1)
    assert "&lt; 표 7 &gt;" in first and first.count("<hp:tc ") == 1 and 'colSpan="3"' in first
    assert f'borderFillIDRef="{plan_hwpx_service.B["none"]}"' in first and f'paraPrIDRef="{plan_hwpx_service.P["table_title"]}"' in first
    assert 'repeatHeader="1"' in long and re.findall(r'<hp:tc name="" header="(\d)"', long)[:6] == ["1", "1", "1", "1", "0", "0"]
    assert re.search(r'<hp:tbl [^>]*rowCnt="9"', long) and '<hp:pos treatAsChar="0"' in long
    # 제목 없는 긴 표는 머리 한 줄 그대로
    assert re.search(r'<hp:tbl [^>]*rowCnt="9"', untitled) and re.findall(r'<hp:tc name="" header="(\d)"', untitled)[:3] == ["1", "1", "0"]


def test_검토용_HWPX_회사자료_표식은_칸의_마지막_조각_뒤에() -> None:
    section = plan_hwpx_service.section_xml([("field", "주요 사업내용", "AI 교육 · 컨설팅 · 과정 개발", "company")], review=True)
    text = html.unescape("".join(re.findall(r"<hp:t>([^<]*)</hp:t>", section)))
    assert "과정 개발 [회사자료]" in text and "AI 교육 [회사자료]" not in text


def test_주요_실적은_겹친_줄을_빼고_최근_5건(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import plan_draft_service

    ledger = [{"year": "2026", "title": "같은 실적"}, {"year": "2026", "title": "같은 실적"}]
    ledger += [{"year": str(2025 - i), "title": f"실적 {i}"} for i in range(5)]
    monkeypatch.setattr(plan_draft_service, "company_sources", lambda org, scope: {"profile": {"name": "시험회사"}, "ledger": ledger})
    values = plan_fill_service.company_values("org-x", None)
    assert values["performance"] == "2026 같은 실적 / 2025 실적 0 / 2024 실적 1 / 2023 실적 2 / 2022 실적 3"


def test_인증_이력_칸은_한_이력_한_줄이고_회사_메모는_싣지_않는다() -> None:
    line = plan_fill_service._history_line
    assert line("직접생산확인(행사 관련) 제2026-0000-00001호 · 유효 2026-01-02~2028-01-01 · 세부품명 확인 필요") == (
        "직접생산확인(행사 관련) 제2026-0000-00001호, 유효 2026-01-02~2028-01-01")
    assert line("가상형 예비사회적기업 지정 · 2021-01 (지금의 사회적기업 인증과 별개)") == "가상형 예비사회적기업 지정, 2021-01"
    assert line("가상기관 데이터 공급기업 지정 · 2022-02 이력 (지금 지정 상태는 재확인 필요)") == "가상기관 데이터 공급기업 지정, 2022-02 이력"
    assert line("가상 훈련 사업 수행기관 선정 · 2025-03-03 (가상공단)") == (
        "가상 훈련 사업 수행기관 선정, 2025-03-03 (가상공단)")
    assert line("세부품명 확인 필요") == ""


@pytest.mark.parametrize("text", [
    "만족도 조사는 연 2회 실시합니다(확인 필요)",
    "[확인 필요] 강사 배정 일정",
    "확인 필요: 강사 배정 일정",
    "강사 배정 일정은 확인 필요 사항입니다.",
    "운영 장소(미정)",
    "세부 일정은 발주기관과 협의가 필요합니다.",
    "운영 방식은 추후 결정합니다.",
])
def test_확인_필요_변형은_모두_본문에서_빠진다(text: str) -> None:
    kept, moved = bid.bid_filter([{"text": text, "type": "AI_SUGGESTION"}], [], "시험", sources=[RFP])
    assert kept == [] and moved == 1


@pytest.mark.parametrize("text", [
    "취업 여부가 확인되지 않은 수료생은 교육사와 협력해 2주 안에 재조사합니다.",
    "교육사 담당자에게 확인해 미응답 수료생의 취업 여부를 집계합니다.",
    "기업 담당자가 확인한 채용 공고를 수료생에게 사전 공유합니다.",
    "증빙 근거가 없는 취업 신고는 집계에서 제외합니다.",
    "확인이 필요한 수료생에게는 교육사를 거쳐 연락합니다.",
    "당사는 발주기관이 보유한 협약기업 104개사 리스트를 기반으로 네트워크를 관리합니다.",
    "당사는 연간 수행한 프로그램별 운영 결과를 최종 보고서로 제출합니다.",
    "당사는 교육사가 운영해 온 취업지원 프로그램을 기반으로 연간 계획을 수립합니다.",
    "결과물 제출 후 당사가 보유한 개인정보는 지체 없이 파기합니다.",
    "면접 경험이 있는 수료생은 심화 모의면접 반으로 배정합니다.",
    # 11-03 실측 — 투입 인력 자격 약속(평가항목 「수행능력 및 전문성」)은 회사 실적 주장이 아니다
    "당사는 보안직무 현직자이자 면접관 경험을 다수 보유한 인력을 취업전문컨설턴트로 배치하겠습니다.",
    "당사는 정보보호 실무 경험이 풍부한 현직자 멘토를 섭외하겠습니다.",
    # 2.10.0 T3 — 조건과 쓰기 동사 사이에 낱말이 있는 계획 문장은 작성자 메모가 아니다
    "만족도 결과를 확인한 뒤 결과보고서에 기재합니다.",
])
def test_정상_계획_문장은_본문에_남는다(text: str) -> None:
    kept, moved = bid.bid_filter([{"text": text, "type": "AI_SUGGESTION"}], [], "시험", sources=[RFP], names=("당사", "샘플에듀"))
    assert moved == 0 and kept[0]["text"] == text


@pytest.mark.parametrize("text", [
    "당사는 지난 5년간 공공기관 AI 교육 30건을 수행하였습니다.",
    "당사는 ISO 9001 인증을 받은 품질 체계로 운영합니다.",
    "당사는 공공기관 AI 교육을 운영한 경험으로 과정을 설계합니다.",
    "당사는 정보보안 전문 강사진 20명을 확보하고 있습니다.",
    "샘플에듀는 KISA 와 3년간 협력해 온 경험을 살립니다.",
    "공공기관 교육 운영 경험이 풍부한 전문 강사진이 교육을 맡습니다.",
])
def test_근거_없는_회사_주장은_빠진다(text: str) -> None:
    kept, moved = bid.bid_filter([{"text": text, "type": "AI_SUGGESTION"}], [], "시험", sources=[RFP], names=("당사", "샘플에듀"))
    assert kept == [] and moved == 1


def test_회사_근거_문장에_덧붙인_근거_밖_보유_주장은_빠진다() -> None:
    cited = {"ledger:3": "2024 대학·교육기관 OO대학교 AI 실무 교육 OO대학교 재학생 대상 AI 실무 교육 운영"}
    padded = {"text": "당사는 OO대학교 AI 실무 교육을 수행했으며, 채용기업 네트워크와 보안 전문 강사진을 보유하고 있습니다.",
              "type": "COMPANY_EVIDENCE_GROUNDED", "source_ids": ["ledger:3"]}
    honest = {"text": "당사는 OO대학교가 발주한 AI 실무 교육을 운영했습니다.", "type": "COMPANY_EVIDENCE_GROUNDED", "source_ids": ["ledger:3"]}
    kept, moved = bid.bid_filter([padded, honest], [], "시험", sources=[RFP], company_texts=cited)
    assert [s["text"] for s in kept] == [honest["text"]] and moved == 1


def test_보유한_개인정보_파기_같은_계획_문장은_회사_주장이_아니다_빈칸_문장은_넘긴다(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_writer(monkeypatch, units={"M3-5": [
        {"text": "결과물 제출 후 당사가 보유한 개인정보는 지체 없이 파기합니다.", "type": "AI_SUGGESTION"},
        {"text": "당사가 보유한 보안 기업 네트워크로 채용을 연계합니다.", "type": "AI_SUGGESTION"},
        {"text": "신규 협약기업을 (담당자 입력)개社 이상 늘리겠습니다.", "type": "AI_SUGGESTION"},
    ]})
    draft = bid.generate(source=_source(), company=COMPANY)
    texts = [s["text"] for s in next(s for s in draft["sections"] if s["key"] == "M3-5")["sentences"]]
    assert texts == ["결과물 제출 후 당사가 보유한 개인정보는 지체 없이 파기합니다."]
    fields = {b["field"] for b in draft["blanks"]}
    assert {"회사 근거 없는 회사 주장", "값을 정하면 넣을 문장"} <= fields


def test_공고에_없는_값_경고는_제안요청서_전문과_다시_대조한다() -> None:
    flagged = {"text": "사업 기간은 2027년 1월 1일부터 12월 10일까지입니다.", "type": "AI_SUGGESTION",
               "flags": ["공고에 없는 값이 있습니다: 2027년, 1월 1일, 12월 10일 — 확인하세요"]}
    wrong = {"text": "교육은 2029년 3월까지 운영합니다.", "type": "AI_SUGGESTION",
             "flags": ["공고에 없는 값이 있습니다: 2029년, 3월 — 확인하세요"]}
    kept, _ = bid.bid_filter([flagged, wrong], [], "시험", sources=[RFP])
    assert not any(f.startswith("공고에 없는 값") for f in kept[0]["flags"])
    assert any(f.startswith("공고에 없는 값") and "2029년" in f for f in kept[1]["flags"])


def test_회사가_정할_사항은_빼고_제안요청서_말투는_경고(monkeypatch: pytest.MonkeyPatch) -> None:
    # 11-03 실측 — 공동수급이 허용된 공고에 「단독으로 수행하며, 공동수급과 하도급 없이」를 AI 가 정했다
    _fake_writer(monkeypatch, units={"M4-3": [
        {"text": "당사는 본 사업을 단독으로 수행하며, 공동수급과 하도급 없이 전 과업을 직접 수행합니다.", "type": "AI_SUGGESTION"},
        {"text": "산업재해가 발생할 급박한 위험이 있으면 작업을 즉시 중지시켜야 합니다.", "type": "AI_SUGGESTION"},
    ]})
    draft = bid.generate(source=_source(), company=COMPANY)
    body = next(s for s in draft["sections"] if s["key"] == "M4-3")["sentences"]
    assert [s["text"] for s in body] == ["산업재해가 발생할 급박한 위험이 있으면 작업을 즉시 중지시켜야 합니다."]
    assert bid.FLAG_RFP_VOICE in body[0]["flags"]
    assert any(b["field"] == "회사가 정할 사항" for b in draft["blanks"])


# ---------------------------------------------------------------------------
# 본문 작성 규칙(2.10.0 T3 · 11-13 동국대 수정 방식 — 시험 문장은 동국대 원문 줄 · 규칙은 다른 공고에도 같은 꼴)
# ---------------------------------------------------------------------------

DONGGUK_TASKS = ("- 투자 유치 전략 등의 기업별 맞춤형 IR 제작 지원 → 해외 VC 대상 피칭     코칭 → 현지화 실무 컨설팅\n"
                 "- 사전 준비(제품, 서비스 등 현지 적합성 점검) → 글로벌 기업 매칭      및 네트워킹 → PoC 실증 진행 → 대면 미팅 통한 후속 협력 논의")


def test_과업_용어를_약한_말로_바꾸면_경고하고_원문_낱말은_그대로_둔다() -> None:
    # wording0 · diff8 — 앱 초안 「해외 VC 관점의 피칭 코칭」(원문 「해외 VC 대상 피칭 코칭」) · 「현지화 실무 점검」(원문 「현지화 실무 컨설팅」)
    phrases = plan_validation.task_phrases(DONGGUK_TASKS)
    assert {"VC 대상 피칭 코칭", "현지화 실무 컨설팅", "글로벌 기업 매칭", "PoC 실증", "대면 미팅"} <= set(phrases)
    weak = ["- 해외 VC 관점의 피칭 코칭으로 이어갑니다.", "- 현지화 실무 점검(법률 · 세무 · 비자)을 진행합니다."]
    fine = ["- 기업당 사전 진단(대면 · 화상)을 운영합니다.", "- 화상 미팅은 발주기관 협의 대안으로 둡니다.",
            "- 현지 적합성 점검 → 글로벌 기업 매칭 → 대면 미팅 순서로 운영합니다.", "- 해외 VC 대상 피칭 코칭을 기업마다 운영합니다."]
    kept, moved = bid.bid_filter([_s(t) for t in weak + fine], [], "시험", sources=[DONGGUK_TASKS], notice_sources=[DONGGUK_TASKS],
                                 task_terms=phrases)
    assert moved == 0
    flagged = {s["text"]: next(f for f in s["flags"] if f.startswith(bid.FLAG_SOFTENED)) for s in kept
               if any(f.startswith(bid.FLAG_SOFTENED) for f in s["flags"])}
    assert list(flagged) == weak
    assert "「VC 대상 피칭 코칭」 → 「VC 관점의 피칭 코칭」" in flagged[weak[0]]
    # 원문이 그 약한 말을 이미 쓰면 바꾼 것이 아니다
    kept, _ = bid.bid_filter([_s(weak[1])], [], "시험", sources=[DONGGUK_TASKS], notice_sources=[f"{DONGGUK_TASKS}\n- 현지화 실무 점검"],
                             task_terms=phrases)
    assert not any(f.startswith(bid.FLAG_SOFTENED) for f in kept[0]["flags"])
    # 꾸밈 · 기호 낱말(「위한 · 통해 · 따른 · +」)은 구 머리가 아니다 — 그 뒤부터 구(T3 검토 · 동국대 원문 탐침)
    lines = ("- 수출 전략 수립을 위한 기업별 맞춤형 컨설팅\n- 글로벌 진출 전략 컨설팅 + 1:1 사전 진단\n"
             "- 데모데이를 통해 후속 투자자·파트너 매칭\n- 프로그램 운영에 따른 컨설팅")
    assert plan_validation.task_phrases(lines) == ["기업별 맞춤형 컨설팅", "글로벌 진출 전략 컨설팅", "1:1 사전 진단", "후속 투자자·파트너 매칭"]
    dongguk = plan_validation.task_phrases(bid.rfp_excerpt(_paged_fixture("bid_rfp_dongguk_1113.txt", "r.hwp", "rfp")["text"])[0])
    assert {"VC 대상 피칭 코칭", "현지화 실무 컨설팅", "PoC 실증", "대면 미팅"} <= set(dongguk)
    assert not [p for p in dongguk if re.match(r"(?:위한|통해|따른|\+)\s", p) or " 따른 " in p]
    assert "약한 말로 바꾸" in bid.SYSTEM_PROMPT and "과제로 정리해 전달" in bid.SYSTEM_PROMPT


def test_실적의_역할_대상은_원장_제목_요약_낱말만_분야는_근거가_아니다() -> None:
    # wording2 — 원장 「데이터 분석 · 시각화 교육」을 「기업별 컨설팅을 운영」으로 넓혔는데 분야 「기업·재직자·컨설팅」이 근거가 됐다
    row = "가상기업 데이터 분석 활용 지원사업 데이터 분석 · 시각화 교육"
    texts = {"ledger:45": f"2022 기업·재직자·컨설팅 {row} 가상진흥원", "ledger:19": "2024 기업 가상 DX 전환교육 재직자 대상 DX 전환교육"}
    roles = {"ledger:45": row, "ledger:19": "가상 DX 전환교육 재직자 대상 DX 전환교육"}
    wide = _s("당사는 2022년 가상기업 데이터 분석 활용 지원사업에서 기업별 컨설팅을 운영했습니다.", "ledger:45")
    other = _s("당사는 2024년 창업기업 대상 DX 전환교육을 운영했습니다.", "ledger:19")
    honest = _s("당사는 2022년 가상기업 데이터 분석 활용 지원사업에서 데이터 분석 · 시각화 교육을 운영했습니다.", "ledger:45")
    blanks: list[dict[str, str]] = []
    kept, moved = bid.bid_filter([wide, other, honest], blanks, "시험", sources=[RFP], company_texts=texts, role_texts=roles)
    assert [s["text"] for s in kept] == [honest["text"]] and moved == 2
    assert [b["field"] for b in blanks] == ["회사 근거 없는 회사 주장"] * 2
    assert "「컨설팅」" in blanks[0]["why"] and "「창업기업」" in blanks[1]["why"]
    assert blanks[0]["why"].rsplit(" — ", 1)[-1] == wide["text"]  # 게이트 예문은 문장만(`_PREFIXED_FIELDS`)
    # role_texts 를 주지 않으면(옛 호출) 지금 그대로
    assert bid.bid_filter([wide], [], "시험", sources=[RFP], company_texts=texts)[1] == 0
    assert "분야 field 는 분류 이름" in bid.SYSTEM_PROMPT
    # 실적 마디 뒤 계획 꼬리(「…운영한 경험으로 재직자 과정을 기획하겠습니다」)의 역할 · 대상은 계획이라 대조하지 않는다(T3 검토)
    cited = {"ledger:3": "2024 대학·교육기관 OO대학교 AI 실무 교육 OO대학교 재학생 대상 AI 실무 교육 운영"}
    row3 = {"ledger:3": "OO대학교 AI 실무 교육 재학생 대상 AI 실무 교육 운영"}
    mixed = _s("당사는 OO대학교 AI 실무 교육을 운영한 경험으로 재직자 과정을 기획하겠습니다.", "ledger:3")
    assert bid.bid_filter([mixed], [], "시험", sources=[RFP], company_texts=cited, role_texts=row3)[1] == 0
    # 실적 쪽에 넓힌 역할이 있으면 그 낱말만(계획 꼬리의 「재직자」 · 「기획」은 사유에 없다)
    blanks = []
    wider = _s("당사는 OO대학교 AI 실무 교육 컨설팅을 운영한 경험으로 재직자 과정을 기획하겠습니다.", "ledger:3")
    assert bid.bid_filter([wider], blanks, "시험", sources=[RFP], company_texts=cited, role_texts=row3)[1] == 1
    assert "「컨설팅」" in blanks[0]["why"] and "재직자" not in blanks[0]["why"].split(" — ")[0]


def test_회사_과거_실적_수치를_이_사업_목표로_쓰면_경고() -> None:
    # wording3 — 「만족도 4.9점」(원장)을 이 사업 목표로 쓰면 회사 조각이 숫자 근거라 경고가 없었다
    notice = "교육 만족도 4.5점 이상 달성"
    company = "2025 가상 생성형 AI 실무 과정 30명 만족도 4.9점"
    past = {"text": "- 프로그램 만족도 4.9점 이상을 목표로 운영하겠습니다.", "type": "AI_SUGGESTION"}
    kept, _ = bid.bid_filter([past], [], "시험", sources=[notice, company], notice_sources=[notice])
    assert any(f.startswith(bid.FLAG_PAST_TARGET) and "4.9점" in f for f in kept[0]["flags"])
    assert not any(f.startswith(bid.FLAG_NUMBER) for f in kept[0]["flags"])
    official = {"text": "- 프로그램 만족도 4.5점 이상을 목표로 운영하겠습니다.", "type": "AI_SUGGESTION"}
    plan = {"text": "- 교육 30명 운영 결과를 결과보고서에 정리합니다.", "type": "AI_SUGGESTION"}  # 목표 낱말 없음
    kept, _ = bid.bid_filter([official, plan], [], "시험", sources=[notice, company], notice_sources=[notice])
    assert not any(f.startswith(bid.FLAG_PAST_TARGET) for s in kept for f in s["flags"])
    for phrase in ("공식 요구", "제안 목표", "사후 측정", "측정 전 결과를 이미 얻은 성과처럼 쓰지 않습니다"):
        assert phrase in bid.SYSTEM_PROMPT, phrase


def test_동국대_원문으로_쓰면_과업_용어_약화_과거_수치_목표_넓힌_역할이_초안에서_걸린다(monkeypatch: pytest.MonkeyPatch) -> None:
    # T3 검토 — 위 시험들은 bid_filter 만 불러 generate 가 task_terms · notice_sources · role_texts 를 빼먹어도 통과했다
    weak = {"text": "- 해외 VC 관점의 피칭 코칭으로 이어갑니다.", "type": "AI_SUGGESTION"}
    past = {"text": "- 만족도 4.9점 이상을 목표로 운영하겠습니다.", "type": "AI_SUGGESTION"}  # 4.9점은 회사 원장에만
    wide = {"text": "당사는 OO대학교 AI 실무 교육 컨설팅을 운영했습니다.", "type": "COMPANY_EVIDENCE_GROUNDED",
            "source": "OO대학교 AI 실무 교육", "source_ids": ["ledger:3"]}
    scope = [{"task": "해외 VC 대상 피칭 코칭", "detail": "해외 VC 관점의 피칭 코칭을 기업마다 운영", "output": "피칭 자료"},
             {"task": "현지화 실무 컨설팅", "detail": "현지화 실무 컨설팅을 기업마다 운영", "output": ""}]
    _fake_writer(monkeypatch, units={"M4-4": [{"text": "○ 수행 방법", "type": "AI_SUGGESTION"}, weak, past, wide]}, scope=scope)
    ledger = [{**COMPANY["ledger_all"][0], "summary": "재학생 대상 AI 실무 교육 운영 · 만족도 4.9점"}, *COMPANY["ledger_all"][1:]]
    rfp_doc = _paged_fixture("bid_rfp_dongguk_1113.txt", "2. 제안요청서.hwp", "rfp")
    assert "4.9" not in rfp_doc["text"] + DONGGUK_NOTICE["text"]
    draft = bid.generate(source={**_source(rfp_doc["text"]), "docs": [rfp_doc, DONGGUK_NOTICE]}, company={**COMPANY, "ledger_all": ledger})
    body = {s["text"]: s["flags"] for s in next(sec for sec in draft["sections"] if sec["key"] == "M4-4")["sentences"]}
    assert any(f.startswith(bid.FLAG_SOFTENED) for f in body[weak["text"]])
    assert any(f.startswith(bid.FLAG_PAST_TARGET) and "4.9점" in f for f in body[past["text"]])
    assert wide["text"] not in body and any("「컨설팅」" in b["why"] and wide["text"] in b["why"] for b in draft["blanks"])
    # 과업별 대응 「제안 대응」 칸도 같은 검사 — 칸 끝 검토 표식 + 확인할 원문 값 한 줄 · 원문 그대로 쓴 칸은 표식 없음
    rows = next(t for t in draft["tables"] if t["key"] == "scope")["rows"]
    assert rows[0][1].startswith("해외 VC 관점의 피칭 코칭을 기업마다 운영 ⚠") and bid.FLAG_SOFTENED in rows[0][1]
    assert "⚠" not in rows[1][1]
    assert any(b["field"] == "원문 정량값 확인" and "과업별 대응" in b["why"] and "VC 대상 피칭 코칭" in b["why"] for b in draft["blanks"])
    blocks = plan_export_service.document_blocks(draft, draft["form"], variant="submit", meta=bid.export_meta(draft, company="시험회사"))
    assert next(b[1] for b in blocks if b[0] == "table" and b[1].get("key") == "scope")["rows"][0][1] == "해외 VC 관점의 피칭 코칭을 기업마다 운영"


@pytest.mark.parametrize("text", [
    "- 해외 진출 경험은 증빙이 확인되는 경우에만 추가합니다.",
    "- 협력 기관 이름은 확약을 받은 뒤 기재합니다.",
    "- 해외 진출 · PoC 지원 직접 수행 경험은 증빙이 확인되는 경우에만 추가합니다 (담당자 확인).",
    "- 상시 인원 (담당자 확인)",
])
def test_고치는_사람에게_하는_말은_본문이_아니라_담당자_확인으로(text: str) -> None:
    # wording5 · submit8 — 손 수정본이 남긴 메모 문장 · 「(담당자 확인)」(빈칸 셈은 `plan_form_service.HUMAN_INPUT_RE` 한 곳)
    blanks: list[dict[str, str]] = []
    kept, moved = bid.bid_filter([{"text": text, "type": "AI_SUGGESTION"}], blanks, "시험", sources=[RFP])
    assert kept == [] and moved == 1 and blanks == [{"field": "담당자 확인", "why": text, "section": "시험"}]
    assert "「증빙이 확인되면 추가합니다」" in bid.SYSTEM_PROMPT


def test_공동수급_불허_공고는_단독_수행_문장을_본문에_남긴다(monkeypatch: pytest.MonkeyPatch) -> None:
    # m0 — 동국대 「본 사업의 공동수급은 불허함」인데 「공동수급 없이 단독으로 수행」을 회사 결정으로 빼 빈칸 목록에 올렸다
    solo = {"text": "당사는 공동수급 없이 단독으로 모든 과업을 수행하겠습니다.", "type": "AI_SUGGESTION", "source_ids": []}
    kept, moved = bid.bid_filter([solo], [], "s", sources=[], solo=True)
    assert [s["text"] for s in kept] == [solo["text"]] and moved == 0
    assert bid.bid_filter([solo], [], "s", sources=[])[1] == 1  # 공동수급 허용 · 모름이면 그대로 회사가 정할 사항
    subcontract = {**solo, "text": "당사는 하도급 없이 수행하겠습니다."}
    assert bid.bid_filter([subcontract], [], "s", sources=[], solo=True)[1] == 1  # 하도급은 여전히 회사가 정한다
    calls = _fake_writer(monkeypatch, units={"M4-3": [solo]})
    draft = bid.generate(source={**_source(), "joint_solo": True}, company=COMPANY)
    assert [s["text"] for s in next(s for s in draft["sections"] if s["key"] == "M4-3")["sentences"]] == [solo["text"]]
    assert all('"joint": "공동수급 불허"' in c["user"] for c in calls)
    calls = _fake_writer(monkeypatch)
    bid.generate(source=_source(), company=COMPANY)
    assert not any('"joint"' in c["user"] for c in calls)
    assert "joint" in bid.SYSTEM_PROMPT


def test_제안_범위_소항목에_과업별_대응표를_싣고_비면_표를_두지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    # wording1 — 범위 절이 과업 두 줄 요약뿐이었다(수정본은 과업 · 제안 대응 · 주요 산출물 표)
    rows = [{"task": "가. 교육(수료)생 취업 지원", "detail": "수료생별 상담과 기업 연계를 운영합니다", "output": "취업 지원 결과"},
            {"task": "나. 결과 보고", "detail": "운영 결과를 정리해 보고합니다", "output": ""}]
    calls = _fake_writer(monkeypatch, scope=rows)
    draft = bid.generate(source=_source(), company=COMPANY)
    sent = next(c["user"] for c in calls if '"key": "M1-2"' in c["user"])
    items = json.loads(next(line for line in sent.splitlines() if line.startswith("소항목(JSON): ")).removeprefix("소항목(JSON): "))
    assert {item["key"]: item["tables"] for item in items}["M1-2"] == ["scope"]  # 「수행범위」 — 첫 「범위」 소항목만
    # 개월차 상한 · 보고 줄은 일정표 소항목만(과업별 대응 행에 보고 줄을 넣지 않게 · T3 검토)
    assert "months" not in next(item for item in items if item["key"] == "M1-2")
    assert "schedule_reports" not in next(item for item in items if item["key"] == "M1-2")
    table = next(t for t in draft["tables"] if t["key"] == "scope")
    assert table["columns"] == ["과업(제안요청서)", "제안 대응", "주요 산출물"] and table["by"] == "llm" and table["item"] == "M1-2"
    assert [row[0] for row in table["rows"]] == ["가. 교육(수료)생 취업 지원", "나. 결과 보고"] and table["rows"][1][2] == ""
    assert "scope" in next(s for s in draft["sections"] if s["key"] == "M1-2")["tables"]
    assert sum(1 for t in draft["tables"] if t["key"] == "scope") == 1
    payload = plan_export_service.build_docx(draft, draft["form"], title="시험", variant="submit", meta=bid.export_meta(draft, company="시험회사"))
    assert "과업별 대응" in _docx_text(payload) and "취업 지원 결과" in _docx_text(payload)
    hwpx = plan_hwpx_service.build_hwpx(draft, draft["form"], title="시험", variant="submit", meta=bid.export_meta(draft, company="시험회사"))
    assert "과업별 대응" in _hwpx_text(hwpx) and "취업 지원 결과" in _hwpx_text(hwpx)
    _fake_writer(monkeypatch)  # AI 가 비워 두면(원문에 과업 목록이 없음) 표를 두지 않는다 — 빈 표는 「(담당자 입력)」 차단이 된다
    draft = bid.generate(source=_source(), company=COMPANY)
    assert not any(t["key"] == "scope" for t in draft["tables"])
    assert "scope" in bid.SYSTEM_PROMPT


def test_지시문_역할_한_벌_섭외_단계_실증_운영안_최대_배점_항목() -> None:
    # wording6 · diff10 · m1 · m2 · m3 — 규칙만(사업 고유 낱말 없음)
    for phrase in ("역할 이름은 문서 전체에서 한 벌", "줄여 쓰지 않습니다", "대체 후보 전환", "「후보」로 쓰고", "성공 판정 기준",
                   "착수 전 대상 기관 · 기업과 합의", "「예상 결과」와 「증빙으로 확인한 성과」", "배점(points)이 가장 큰"):
        assert phrase in bid.SYSTEM_PROMPT, phrase
    for word in ("동국대", "매칭 기준", "6주", "아웃바운드"):
        assert word not in bid.SYSTEM_PROMPT, word


def test_제출용_표_칸에는_검토_표식이_없고_일반현황_소제목이_있다(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_writer(monkeypatch)
    draft = bid.generate(source=_source(), company=COMPANY)
    schedule = next(t for t in draft["tables"] if t["key"] == "schedule")
    schedule["rows"] = [["교육(수료)생 관리 및 상담 ⚠ 공고 문장과 거의 같음", "1~12개월차 ⚠ 협약 기간 밖(2028.1월)", "정기 방문 상담"]]
    meta = bid.export_meta(draft, company="시험회사")
    submit = _docx_text(plan_export_service.build_docx(draft, draft["form"], title=draft["title"], variant="submit", meta=meta))
    assert "⚠" not in submit and "교육(수료)생 관리 및 상담" in submit
    assert "1. 일반현황" in submit and "2. 조직 및 인원" in submit
    review = _docx_text(plan_export_service.build_docx(draft, draft["form"], title=draft["title"], variant="review", meta=meta))
    assert "⚠ 공고 문장과 거의 같음" in review


def test_사업계획서_표지는_예전_그대로() -> None:
    meta = {"notice": "공고", "task": "과제", "company": "회사", "date": "2026. 11. 3."}
    assert plan_export_service.cover_rows(meta) == [("과제명", "과제"), ("기업명", "회사"), ("제출일", "2026. 11. 3.")]
    assert plan_export_service.export_file_name("사업", "docx", variant="submit").startswith("사업계획서_제출용_")


# ---------------------------------------------------------------------------
# 원문 · API
# ---------------------------------------------------------------------------


def test_원문이_공고서뿐이면_쓰지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rfp_parser, "load_generated", lambda pid: SimpleNamespace(document_role="notice", document="공고서.hwpx"))
    with pytest.raises(bid.NoRfpError):
        bid.load_source(PID, SimpleNamespace(notice=SimpleNamespace(raw_data={})))


def test_받아_둔_원문은_첨부_목록에서_빠져도_캐시_폴더에서_찾는다(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # 11-03 검토 — 사전규격 저장본이 30일 뒤 정리되면 첨부 목록에서 규격서가 빠진다. 받아 둔 파일은 그대로 쓴다
    from app.services import attachment_service, document_extractor

    monkeypatch.setattr(attachment_service, "CACHE_DIR", tmp_path / "real_rfp")
    name = "사전규격 규격서 1(R26BD09999999)"
    target = attachment_service.cache_path(PID, 2, name)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"HWP-binary")
    monkeypatch.setattr(rfp_parser, "load_generated", lambda pid: SimpleNamespace(document_role="rfp", document=name, requirement_set_hash="h1"))
    # 11-06 부터 받아 둔 원문을 모두 읽어 쪽 · 이름이 있는 추출 결과를 쓴다(예전 가짜는 글만 돌려줬다)
    monkeypatch.setattr(document_extractor, "extract_document", lambda path, file_name=None, **_: document_extractor.ExtractedDocument(
        file_name=file_name or path.name, doc_format="hwp", pages=[document_extractor.DocumentPage(page=1, text=RFP)]))
    view = SimpleNamespace(notice=SimpleNamespace(title="공고", agency="한국인터넷진흥원", raw_data={}))  # 첨부 목록에 규격서 없음
    source = bid.load_source(PID, view)
    assert source["text"] == RFP and source["document"] == name and source["requirement_set_hash"] == "h1"
    # 나라장터 공동수급 칸(2.10.0 m0) — 모르면 False(지금 그대로) · 「불허」면 True
    assert source["joint_solo"] is False
    solo = SimpleNamespace(notice=SimpleNamespace(title="공고", agency="기관", raw_data={"cmmnSpldmdMethdNm": "(없음)공동수급불허"}))
    assert bid.load_source(PID, solo)["joint_solo"] is True
    target.write_bytes("<!doctype html><title>시스템 점검 안내</title>".encode("utf-8"))  # 안내 화면이면 없는 것으로
    with pytest.raises(bid.SourceMissingError):
        bid.load_source(PID, view)


def test_AI_가_모두_실패한_다시_쓰기는_있던_AI_초안을_덮지_않고_덮을_때는_옛_판을_남긴다(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.services import analysis_store

    monkeypatch.setattr(proposal_service, "PROPOSALS_DIR", tmp_path / "public_proposals")
    organization_service.create_organization(OrganizationCreateRequest(display_name="데모교육연구소", organization_id=ORG, data_class="synthetic", created_by="k"))
    context = AnalysisContext(organization_id=ORG, evidence_scope="internal")
    _fake_writer(monkeypatch)
    first = bid.generate(source=_source(), company=COMPANY)
    assert bid.save(first, context=context, procurement_id=PID) == (first, False)
    monkeypatch.setattr(llm_client, "plan_writer_ready", lambda writer="claude": (False, "사용 한도"))
    failed = bid.generate(source=_source(), company=COMPANY)
    shown, kept = bid.save(failed, context=context, procurement_id=PID)
    assert kept is True and shown["generated_by"] == "llm" and "있던 AI 초안을 그대로 둡니다" in shown["llm_note"]
    assert bid.load(PID, context=context)["generated_by"] == "llm"
    _fake_writer(monkeypatch)
    second = bid.generate(source=_source(), company=COMPANY)
    bid.save(second, context=context, procurement_id=PID)
    assert list((analysis_store.private_dir(context, PID) / bid.VERSIONS_DIR).glob("*.json"))


def test_분석을_안_했으면_먼저_분석하라고_한다(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(pid: str) -> Any:
        raise rfp_parser.RfpNotParsedError(pid)

    monkeypatch.setattr(rfp_parser, "load_generated", missing)
    with pytest.raises(bid.SourceMissingError):
        bid.load_source(PID, SimpleNamespace(notice=SimpleNamespace(raw_data={})))


@dataclass
class _Notice:
    id: str = PID
    title: str = "27년 사이버보안인력양성 교육(수료)생 취업지원 프로그램 운영·고도화"
    agency: str = "한국인터넷진흥원"
    raw_data: dict[str, Any] = field(default_factory=dict)


@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(proposal_service, "PROPOSALS_DIR", tmp_path / "public_proposals")
    organization_service.create_organization(OrganizationCreateRequest(display_name="데모교육연구소", organization_id=ORG, data_class="synthetic", created_by="k"))

    async def fake_notice(notice_id: str, **_: Any) -> Any:
        return SimpleNamespace(notice=_Notice()) if notice_id == PID else None

    monkeypatch.setattr(procurement_service, "get_notice", fake_notice)
    monkeypatch.setattr(bid, "load_source", lambda pid, view: _source())
    _fake_writer(monkeypatch)
    return TestClient(app)


def test_API_로_쓰고_읽고_제출용을_내려받는다(api: TestClient) -> None:
    params = {"organization_id": ORG, "evidence_scope": "internal"}
    assert api.get(f"/api/proposal/{PID}/plan-draft", params=params).status_code == 404
    made = api.post(f"/api/proposal/{PID}/plan-draft", json={**params, "writer": "claude"})
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["kind"] == "제안서" and body["generated_by"] == "llm" and isinstance(body["submit_blanks"], int)
    assert body["stale"] is False
    got = api.get(f"/api/proposal/{PID}/plan-draft", params=params).json()
    assert [s["key"] for s in got["sections"]] == [s["key"] for s in body["sections"]]
    exported = api.get(f"/api/proposal/{PID}/plan-draft/export", params={**params, "format": "docx", "variant": "submit"})
    assert exported.status_code == 200
    # 2.7.0(대표 결정 11-08) — 빈칸(조직 표 · 일반현황)이 남은 초안은 제출용 판이라도 이름이 「제안서_초안_…」(본문은 같다)
    assert got["quality"]["status"] == "BLOCKED" and got["quality"]["file_label"] == "초안"
    assert "%EC%A0%9C%EC%95%88%EC%84%9C_%EC%B4%88%EC%95%88" in exported.headers["content-disposition"]  # 제안서_초안
    assert "확인 필요" not in _docx_text(exported.content)
    hwpx = api.get(f"/api/proposal/{PID}/plan-draft/export", params={**params, "format": "hwpx", "variant": "submit"})
    assert hwpx.status_code == 200 and hwpx.headers["content-type"] == "application/hwp+zip"
    assert hwpx.headers["content-disposition"].endswith(".hwpx")
    assert "확인 필요" not in _hwpx_text(hwpx.content)


def test_API_제안요청서가_없으면_422(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_rfp(pid: str, view: Any) -> Any:
        raise bid.NoRfpError("제안요청서가 없어 입찰공고문만 분석했습니다")

    monkeypatch.setattr(bid, "load_source", no_rfp)
    response = api.post(f"/api/proposal/{PID}/plan-draft", json={"organization_id": ORG, "evidence_scope": "internal"})
    assert response.status_code == 422 and "제안요청서" in response.json()["detail"]


def test_API_공용_데모에는_쓰지_않는다(api: TestClient) -> None:
    # 공용 데모 결과는 기본 조직만 쓴다 — 다른 회사는 AI 를 부르기 전에 403
    response = api.post(f"/api/proposal/{PID}/plan-draft", json={"organization_id": ORG, "evidence_scope": "public_demo"})
    assert response.status_code == 403
