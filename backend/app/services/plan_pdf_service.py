"""사업계획서 PDF — Word 없이도 (29차 · prompt_19 §3-D).

범용 설치 키트 PC 에 Word 가 없을 수 있다. 그래서 두 길이다:

1. **이 PC 의 Edge/Chrome 헤드리스 `--print-to-pdf`** — DOCX 와 같은 블록으로 만든 HTML(`plan_export_service.build_html`)을 찍는다.
   브라우저 찾기는 검사 스크립트(`scripts/check_visibility.mjs` 등)와 같은 경로 목록이다. 임시 프로필 · 로컬 파일만 연다(네트워크 없음).
2. **Microsoft Word(COM)** — 있으면 쓰는 두 번째 길(`proposal_export.docx_to_pdf`).

둘 다 없으면 `PdfConverterUnavailableError` — 화면의 PDF 단추가 그 이유를 보인다. 부르는 쪽은 스레드에서 부른다(26차 R26-03).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from app.services import plan_export_service
from app.services.proposal_export import PdfConverterUnavailableError, docx_to_pdf

logger = logging.getLogger(__name__)

#: 검사 스크립트와 같은 목록(Edge 먼저 — Windows 에 늘 있다).
BROWSER_CANDIDATES: tuple[str, ...] = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)
WORD_CANDIDATES: tuple[str, ...] = (
    r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
    r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE",
    r"C:\Program Files\Microsoft Office\Office16\WINWORD.EXE",
)
BROWSER_TIMEOUT_SECONDS = 90
#: Edge 실행기는 PDF 를 다 쓰기 전에 끝난다(29차 실측 — 끝난 직후엔 파일이 없고 1초 뒤에 있다). 크기가 멈출 때까지 기다리는 상한.
WRITE_WAIT_SECONDS = 20.0
NO_PDF_REASON = "이 PC 에 Edge · Chrome · Microsoft Word 가 없어 PDF 를 만들 수 없습니다 — DOCX 로 받아 주세요"


def browser_path() -> str | None:
    for candidate in BROWSER_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def word_available() -> bool:
    return sys.platform == "win32" and any(Path(p).is_file() for p in WORD_CANDIDATES)


def pdf_status() -> dict[str, Any]:
    """PDF 를 만들 수 있는가 — 화면의 PDF 단추가 읽는다. 프로세스를 띄우지 않는다(파일이 있는지만 본다)."""
    browser = browser_path()
    word = word_available()
    method = "browser" if browser else ("word" if word else None)
    return {"available": method is not None, "method": method, "browser": bool(browser), "word": word,
            "reason": None if method else NO_PDF_REASON}


def html_to_pdf(page: str, *, exe: str | None = None, timeout: float = BROWSER_TIMEOUT_SECONDS) -> bytes:
    """HTML 한 장 → PDF (헤드리스 브라우저). 실패하면 PdfConverterUnavailableError."""
    exe = exe or browser_path()
    if not exe:
        raise PdfConverterUnavailableError(NO_PDF_REASON)
    tmp = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    try:
        src, out = tmp / "plan.html", tmp / "plan.pdf"
        src.write_text(page, encoding="utf-8")
        args = [
            exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            "--disable-background-networking", "--disable-sync", "--disable-component-update", "--mute-audio",
            f"--user-data-dir={tmp / 'profile'}", "--no-pdf-header-footer", "--print-to-pdf-no-header",
            f"--print-to-pdf={out}", src.as_uri(),
        ]
        try:
            subprocess.run(args, capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("PDF 변환 실패 — 브라우저 실행 오류 %s: %s", type(exc).__name__, exc)
            raise PdfConverterUnavailableError("PDF 변환 실패: 브라우저(Edge · Chrome)를 실행하지 못했습니다 — DOCX 로 받아 주세요") from exc
        if not _wait_written(out):
            raise PdfConverterUnavailableError("PDF 변환 실패: 브라우저가 PDF 를 만들지 않았습니다 — DOCX 로 받아 주세요")
        return out.read_bytes()
    finally:
        _remove_temp(tmp)


#: 임시 폴더 이름 앞말 — 서버 시작 때 남은 것을 찾는다.
TEMP_PREFIX = "bidpilot-pdf-"


def _remove_temp(folder: Path, *, wait: float = 5.0) -> bool:
    """임시 폴더(Edge 프로필 약 7MB 포함)를 지운다 — Edge 가 파일을 놓을 때까지 잠깐 기다리며 다시 시도(30차 R29-11).
    끝내 못 지우면 경고 로그만 남기고 거짓(서버 시작 때 `cleanup_leftovers` 가 다시 지운다)."""
    deadline = time.monotonic() + wait
    while True:
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists():
            return True
        if time.monotonic() >= deadline:
            logger.warning("PDF 임시 폴더를 지우지 못했습니다(브라우저가 잡고 있음) — 다음 서버 시작 때 다시 지웁니다: %s", folder.name)
            return False
        time.sleep(0.5)


def cleanup_leftovers(*, older_than: float = 600.0, prefixes: tuple[str, ...] = (TEMP_PREFIX, "bidpilot-codex-")) -> int:
    """서버 시작 때 남은 임시 폴더를 지운다 — PDF(Edge 프로필) · Codex(끊긴 자식이 잡고 있던 out.json · 초안 본문) ·
    10분보다 오래된 것만 · 지운 수를 돌려준다(30차 R29-11 · §4 마지막 검토)."""
    removed = 0
    now = time.time()
    root = Path(tempfile.gettempdir())
    for folder in (f for prefix in prefixes for f in root.glob(f"{prefix}*")):
        try:
            if folder.is_dir() and now - folder.stat().st_mtime > older_than:
                shutil.rmtree(folder, ignore_errors=True)
                removed += int(not folder.exists())
        except OSError:
            continue
    return removed


def _wait_written(path: Path, limit: float = WRITE_WAIT_SECONDS) -> bool:
    """파일이 생기고 크기가 0.5초 동안 그대로면 참. 상한 안에 안 되면 거짓."""
    deadline = time.monotonic() + limit
    last = -1
    while time.monotonic() < deadline:
        size = path.stat().st_size if path.is_file() else -1
        if size >= 800 and size == last:
            return True
        last = size
        time.sleep(0.5)
    return False


def build_pdf(draft: dict[str, Any], form: dict[str, Any], *, title: str, variant: plan_export_service.Variant,
              meta: dict[str, Any] | None = None) -> tuple[bytes, str]:
    """사업계획서 PDF 한 벌 → (바이트, 쓴 길 「browser」 · 「word」). 브라우저가 실패하면 Word 로 한 번 더."""
    status = pdf_status()
    first_error: PdfConverterUnavailableError | None = None
    if status["browser"]:
        try:
            page = plan_export_service.build_html(draft, form, title=title, variant=variant, meta=meta)
            return html_to_pdf(page), "browser"
        except PdfConverterUnavailableError as exc:
            first_error = exc
    if status["word"]:
        docx = plan_export_service.build_docx(draft, form, title=title, variant=variant, meta=meta)
        return docx_to_pdf(docx), "word"
    raise first_error or PdfConverterUnavailableError(NO_PDF_REASON)
