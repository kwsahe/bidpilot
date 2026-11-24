"""43차 §2-F — 선제준비 · 직접 넣기 · 후보함(M12~M16 · H4 · Q16~Q20 · N19)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.manual_notice import ManualNoticeInput
from app.services import manual_notice_service as manual
from app.services import notice_inbox_service as inbox
from app.services import prespec_service

KST = timezone(timedelta(hours=9))


def test_Q16_사전규격_행에_본공고_예상_사업기간_할_일() -> None:
    opinion = datetime(2026, 10, 22, 18, tzinfo=KST)
    line = prespec_service.prespec_plan({"dlvrDaynum": "180"}, opinion)
    assert "본공고 예상 10/23~10/25" in line and "사업기간 180일" in line and "의견 마감 전 의견 등록" in line


def test_M15_김담당_표_접수방식은_날짜가_아니고_공고일_판단을_읽는다() -> None:
    text = (
        "| 분류 | 후보 | 접수방식 | 공고일 | 마감 | 판단 | 링크 |\n|---|---|---|---|---|---|---|\n"
        "| 조건부 | 서강대 AI 성장전략 컨설팅 | 대학 자체 전자입찰 | 10/16 | 11/24 | 조건부 검토 | [바로가기](https://ebiz4u.co.kr/x?no=1) |\n"
        "| 제외 | 한-두바이 포럼 | 이메일 | 10/10 | 10/30 | ❌ 제외 행사 대행 | [바로가기](https://a.go.kr/b) |\n"
    )
    rows = inbox.parse(text)[0]
    assert rows[0]["date_text"] == "11/24" and rows[0]["published_text"] == "10/16" and rows[0]["gpt_note"] is None
    assert rows[1]["gpt_note"].startswith("GPT: 제외")


def test_M15_선제준비_블록은_위쪽_제목을_공고명으로() -> None:
    rows = inbox.parse("## 2027년 방과후 특색분야 사전규격\n- [바로가기](https://www.g2b.go.kr/pre?x=1)\n")[0]
    assert rows[0]["title"] == "2027년 방과후 특색분야 사전규격"


def test_N19_미리_보기는_저장하지_않는다(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inbox, "path_of", lambda organization_id: tmp_path / "inbox.json")
    monkeypatch.setattr(manual, "find_existing", lambda url, body=None, index=None: (None, None))
    monkeypatch.setattr(manual, "similar_existing", lambda title, index=None: (None, None))
    result = inbox.paste("org-x", "공고 [시험 공고 하나](https://a.go.kr/1)", preview=True)
    assert result.preview and result.added == 1
    assert inbox.load("org-x") == []


def test_Q20_상시_미정이면_마감을_비울_수_있고_아니면_적어야_한다() -> None:
    base = {"url": "https://a.go.kr/1", "title": "시험 공고", "agency": "기관", "recruit": "bid"}
    assert ManualNoticeInput(**base, deadline_open=True).deadline is None
    with pytest.raises(ValueError):
        ManualNoticeInput(**base)


def test_H4_사전규격_번호도_저장본과_잇는다(monkeypatch: pytest.MonkeyPatch) -> None:
    index = manual.StoreIndex()
    monkeypatch.setattr(index, "prespecs", lambda: {"R26BD00284797"})
    monkeypatch.setattr(index, "g2b", lambda: {})
    found, why = manual.find_existing("https://www.g2b.go.kr/x?bfSpecRgstNo=R26BD00284797", index=index)
    assert found == f"{prespec_service.ID_PREFIX}R26BD00284797" and "사전규격" in why


def test_H4_공고명이_같은_나라장터_공고는_같은_공고일_수_있음(monkeypatch: pytest.MonkeyPatch) -> None:
    index = manual.StoreIndex()
    key = prespec_service.title_key("2026년 전문대학 혁신지원사업 AI 활용 재학생 역량강화 프로그램 위탁운영")
    monkeypatch.setattr(index, "titles", lambda: {key: "g2b-R26BK01780000-000"})
    found, why = manual.similar_existing("전문대학 혁신지원사업 AI 활용 재학생 역량강화 프로그램 위탁운영", index=index)
    assert found == "g2b-R26BK01780000-000" and "같은 공고일 수 있음" in why
