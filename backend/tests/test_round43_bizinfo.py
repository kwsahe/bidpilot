"""43차 §2-E — 기업마당 · 지원사업 흐름(M8 · BIZ-02 · BIZ-15 · N4)."""

from __future__ import annotations

import io
import zipfile

from app.services import document_extractor, opportunity_priority as priority
from app.services import qualification_clause_service as qc


def test_압축_안_한글_이름은_cp949로_다시_읽는다() -> None:
    # 한글 Windows 압축 꼴 — UTF-8 표시 없이 cp949 바이트(자리표시 ASCII 이름을 같은 길이의 cp949 바이트로 바꿔 만든다)
    korean = "제안요청서".encode("cp949")
    placeholder = b"A" * len(korean)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(f"4. {placeholder.decode()}.hwpx", b"x")
    data = buf.getvalue().replace(placeholder, korean)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = document_extractor.zip_display_names(archive)
    assert "4. 제안요청서.hwpx" in names
    assert document_extractor.pick_zip_member(list(names)) == "4. 제안요청서.hwpx"


def test_열기_실패는_아직_안_읽음이_아니다() -> None:
    assert qc.evidence_line({"status": "error", "clauses": []})[0] == qc.OPEN_FAILED
    assert qc.evidence_line(None)[0] == qc.NOT_READ


def test_사업영역_낱말은_영문_경계와_기관_이름을_본다() -> None:
    assert priority._hits("Main-Biz 인증 · K-Digital Training · 전남인력개발원 · 교육장 소지", ["AI", "개발", "교육"]) == []
    assert priority._hits("생성형 AI 실무 교육 운영", ["AI", "교육"]) == ["AI", "교육"]
