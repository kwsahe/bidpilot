"""키트용 가상 예시 제안요청서 — 「BidPilot AI」 글을 뺀 DOCX 를 만든다 (31차 R30-14).

원본(`data/public/sample_rfp/synthetic_ai_training_rfp.docx`)은 그대로 두고, 본문 · 문서 속성의 「BidPilot AI」만
「BidPilot AI」로 바꾼 사본을 `scripts/kit/assets/` 에 쓴다. PDF 는 같은 Word 로 이 DOCX 를 저장해 만든다
(`make_kit_sample_rfp.ps1` — 쪽 나눔이 원본과 같아야 요구사항 쪽 번호가 맞는다). build_kit 이 키트 속 두 파일을 이 사본으로 바꾼다.

    backend\\.venv\\Scripts\\python.exe scripts\\kit\\make_kit_sample_rfp.py
"""

from __future__ import annotations

from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/public/sample_rfp/synthetic_ai_training_rfp.docx"
TARGET = ROOT / "scripts/kit/assets/synthetic_ai_training_rfp.docx"
OLD, NEW = "BidPilot AI", "BidPilot AI"


def main() -> None:
    doc = Document(str(SOURCE))
    changed = 0
    paragraphs = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)
    for section in doc.sections:
        paragraphs.extend(section.header.paragraphs)
        paragraphs.extend(section.footer.paragraphs)
    for paragraph in paragraphs:
        for run in paragraph.runs:
            if OLD in run.text:
                run.text = run.text.replace(OLD, NEW)
                changed += 1
    props = doc.core_properties
    for name in ("title", "subject", "author", "comments", "keywords", "last_modified_by"):
        value = getattr(props, name) or ""
        if OLD in value:
            setattr(props, name, value.replace(OLD, NEW))
            changed += 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(TARGET))
    print(f"{TARGET} — 바꾼 곳 {changed}")


if __name__ == "__main__":
    main()
