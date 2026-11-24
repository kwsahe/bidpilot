"""압축 첨부의 해제 크기·압축비·중첩 깊이에 상한을 둔다 (ISSUE-025 · TASK-020).

## 무엇을 막는가

첨부 압축을 풀 때 상한이 **하나도** 없었다. `zf.read()` 는 헤더가 뭐라 적혀 있든 끝까지
읽고, 임시 폴더로 복사할 때도 바이트를 세지 않았으며, 압축 안의 압축을 재귀로 따라갔다.

몇 KB 짜리 파일이 수 GB 로 펼쳐지는 압축은 만들기 쉽다(같은 바이트가 반복되면 압축비가
1000:1 을 훌쩍 넘는다). 서버 메모리·디스크가 먼저 죽고, 그동안 다른 모든 요청이 멈춘다.

들어오는 문은 셋이다: `/api/auditor/run/upload`(공개 데모에서도 열려 있다),
`/api/organizations/{org}/documents`, `/api/rfp/parse`(첨부 30MB).

## 어떻게 막는가

헤더의 선언 크기와 **실제 복사 바이트**를 둘 다 본다. 헤더는 만든 쪽이 적는 값이라
믿을 수 없지만, 거짓말이면 복사 중 바이트 세기가 다시 막는다.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.services import document_extractor as dx


def _zip_with(path: Path, name: str, data: bytes) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, data)
    return path


def test_압축을_풀면_너무_큰_파일은_거부한다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 바이트가 반복되면 몇 KB 가 수십 MB 로 펼쳐진다 — 실제 압축 폭탄의 모양이다."""
    monkeypatch.setattr(dx, "MAX_UNCOMPRESSED_BYTES", 1024)
    monkeypatch.setattr(dx, "MAX_COMPRESSION_RATIO", 10_000)  # 여기서는 크기만 본다
    archive = _zip_with(tmp_path / "bomb.zip", "제안요청서.pdf", b"A" * 100_000)

    with pytest.raises(dx.DocumentExtractionError) as exc:
        dx.extract_zip(archive)
    assert "너무 큽니다" in str(exc.value)


def test_압축비가_비정상이면_거부한다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dx, "MAX_COMPRESSION_RATIO", 5)
    archive = _zip_with(tmp_path / "ratio.zip", "제안요청서.pdf", b"A" * 100_000)

    with pytest.raises(dx.DocumentExtractionError) as exc:
        dx.extract_zip(archive)
    assert "압축 비율" in str(exc.value)


def test_헤더가_거짓말을_해도_복사_중에_막는다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`file_size` 는 만든 쪽이 적는 값이다. 그것만 믿으면 검사가 없는 것과 같다."""
    monkeypatch.setattr(dx, "MAX_UNCOMPRESSED_BYTES", 1024)

    class _Lying(io.BytesIO):
        pass

    src = _Lying(b"B" * 100_000)
    dst = io.BytesIO()
    with pytest.raises(dx.DocumentExtractionError) as exc:
        dx._copy_with_limit(src, dst)
    assert "넘었습니다" in str(exc.value)


def test_압축이_여러_겹이면_열지_않는다(tmp_path: Path) -> None:
    """무제한 재귀면 파일 하나로 서버를 재귀에 빠뜨릴 수 있다.

    지금은 `pick_zip_member` 가 `.zip` 을 «고르지 않아서» 실제로는 한 겹에서 멈춘다.
    그 규칙이 바뀌면 곧바로 무제한 재귀가 되므로, 깊이 제한 자체를 여기서 고정한다.
    """
    archive = _zip_with(tmp_path / "deep.zip", "제안요청서.pdf", b"%PDF-1.4 fake")

    with pytest.raises(dx.DocumentExtractionError) as exc:
        dx.extract_zip(archive, depth=dx.MAX_ZIP_DEPTH + 1)
    assert "여러 겹" in str(exc.value)


def test_정상_크기의_압축은_상한에_걸리지_않는다(tmp_path: Path) -> None:
    """고치면서 정상 첨부까지 막으면 더 나쁘다."""
    archive = _zip_with(tmp_path / "ok.zip", "제안요청서.pdf", b"%PDF-1.4 fake body")

    # 안쪽이 진짜 PDF 가 아니라 추출 자체는 실패한다. 상한 «검사»에 걸리지 않는 것만 본다.
    with pytest.raises(Exception) as exc:
        dx.extract_zip(archive)
    message = str(exc.value)
    assert "너무 큽니다" not in message
    assert "압축 비율" not in message
    assert "여러 겹" not in message
