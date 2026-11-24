"""32차 §3-G — 사업계획서 · 과제소개서(R31-31 · R31-32 · R31-34)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import bizinfo_document_store as store
from app.services import plan_draft_service, plan_form_service


@pytest.mark.parametrize("text", [
    "수치는 지어내지 않고 (담당자 입력)으로 비워 둡니다.",
    "확인되지 않은 실적은 단정하지 않고 확인 후 기재합니다.",
    "이 절은 제공된 자료만으로 작성했습니다.",
    "주어진 자료에 매출 수치가 없어 비워 두었습니다.",
    "입력 자료에서는 확인되지 않아 담당자가 채웁니다.",
    "수치는 지어내지 않고 담당자가 채워 넣습니다.",
])
def test_R31_31_작성_사정_문장은_본문에서_내린다(text: str) -> None:
    assert plan_draft_service._INTERNAL_RE.search(text), text


@pytest.mark.parametrize("text", [
    "근거가 없으면 답을 지어내지 않고 담당자에게 넘깁니다.",  # RAG 상담 흐름 — 시스템 동작
    "시스템은 출처를 단정하지 않고 근거 문서를 함께 보여 줍니다.",
    "AI가 답을 지어내지 않도록 제공된 정보만으로 답변합니다.",
    "RAG 파이프라인은 주어진 자료에서 근거 조각을 찾아 답변과 함께 보여 줍니다.",
    "모델은 결과를 단정하지 않고 담당자가 채택한 근거와 함께 제시합니다.",  # 마지막 검토 — 「채택」은 쓰는 사정이 아니다
    "시스템은 결과를 단정하지 않고 담당자가 적용 여부를 정하게 합니다.",
])
def test_R31_31_AI_RAG_기술_문장은_본문에_남는다(text: str) -> None:
    assert not plan_draft_service._INTERNAL_RE.search(text), text


def test_R31_32_텍스트가_없으면_원본을_다시_읽지_않는다(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.services import document_extractor

    monkeypatch.setattr(store, "DOCS_DIR", tmp_path)
    (tmp_path / f"P1.{store.ANNEX_TAG}.pdf").write_bytes(b"%PDF-1.4 not really")

    def _boom(*_a, **_kw):
        raise AssertionError("원본을 다시 읽었다")

    monkeypatch.setattr(document_extractor, "extract_document", _boom)
    assert plan_form_service._annex_text("bizinfo-P1") is None
    (tmp_path / f"P1.{store.ANNEX_TAG}.txt").write_text("과제 1 시험기관 과제소개서\n본문", encoding="utf-8")
    assert plan_form_service._annex_text("bizinfo-P1") == "과제 1 시험기관 과제소개서\n본문"


@pytest.mark.parametrize("old", [store.IMAGE_NOTE, store.NO_TEXT_NOTE])
def test_R31_34_스캔_과제소개서_안내는_과제소개서_말이다(monkeypatch: pytest.MonkeyPatch, old: str) -> None:
    record = store.DocumentRecord(program_id="P1", status="failed", note=old)
    monkeypatch.setattr(store, "load_index", lambda: store.DocumentIndex(annexes={"P1": record}))
    got = store.annex_record("P1")
    assert got is not None and got.note == store.ANNEX_UNREADABLE_NOTE
    assert "판정" not in got.note and "공고문" not in got.note
