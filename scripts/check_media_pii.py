"""커밋된 스크린샷·영상에 실명이 **픽셀로** 렌더돼 있는지 검사한다.

    py -3.12 scripts/check_media_pii.py              # 추적 중인 이미지·영상 전부
    py -3.12 scripts/check_media_pii.py --fps 2      # 영상을 더 촘촘히 (기본 1fps)
    py -3.12 scripts/check_media_pii.py docs/a.png   # 지정한 파일만

numpy 와 Pillow 가 필요하다. backend/.venv 에는 numpy 가 없으므로 시스템 파이썬으로 돌린다.

왜 필요한가
-----------
`scripts/snapshot_demo_api.py` 의 실명 검사도, git grep 도, 어떤 텍스트 검사도 PNG·MP4 안의
글자는 못 읽는다. 실제로 화면 캡처 한 장과 영상 두 편에 직원 실명이 렌더된 채 커밋돼 있었다.

어떻게 찾나
-----------
OCR 없이 **글자 비트맵 자체를 템플릿으로 놓고** 정규화 상호상관(zero-mean NCC)을 돌린다.
같은 앱·같은 폰트로 찍힌 화면이라 글자 모양이 사실상 동일하다. 평균을 뺀 상관이라
배경색·밝기가 달라도 잡히고, 여러 배율을 함께 본다. 1920 폭 영상은 1280 으로 줄여
템플릿과 글자 크기를 맞춘다.

실측 보정값 (2026-09-08, 이미지 103장 + 영상 8편):
    진짜 일치   0.987 ~ 1.000
    오탐 상한   0.801   (「사업 생성형 AI 활용 교…」 같은 평범한 한글 문장)
임계 0.90 은 두 무리가 실제로 갈라지는 자리를 재서 정한 값이다.

템플릿은 어디에 두나
--------------------
`data/private/pii_templates/*.png` (gitignore). 이 스크립트는 Git 에 올라가므로 이름 이미지를
저장소에 넣으면 그 자체가 유출이다 — `data/private/pii_names.txt` 와 같은 이유다.
템플릿은 실명이 보이는 화면에서 글자 부분만 잘라 만든다. 글자 **모양이 다르면**
(입력란의 굵은 흰 글자 vs 툴팁의 작은 초록 글자) 서로 안 잡히므로 모양마다 하나씩 넣는다.

찾은 뒤 가리는 일은 이 스크립트가 하지 않는다 (검사 전용).
이미지는 PIL 사각형, 영상은 ffmpeg drawbox 로 해당 구간만 덮는다.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "data" / "private" / "pii_templates"
HIT = 0.90
SCALES = (0.875, 1.0, 1.125, 1.25)
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
VIDEO_EXT = {".mp4", ".webm", ".mov"}

try:
    import numpy as np
    from PIL import Image
except ImportError:  # pragma: no cover - 실행 환경 안내
    print("numpy 와 Pillow 가 필요합니다. 시스템 파이썬으로 실행하세요: py -3.12 scripts/check_media_pii.py", file=sys.stderr)
    raise SystemExit(2)


# 영상 프레임만 이 폭으로 맞춘다. 1920 짜리 녹화본의 글자를 템플릿(1280 기준 화면에서 떼어냄)과
# 같은 크기로 만들기 위해서다. **이미지는 줄이지 않는다** — 줄이면 글자가 뭉개져 점수가 떨어진다
# (1440 스크린샷을 1280 으로 줄였더니 1.000 이 나와야 할 자리에서 0.925 까지 내려갔다).
VIDEO_MATCH_WIDTH = 1280


def to_gray(path: Path, normalize_width: int | None = None) -> "np.ndarray":
    im = Image.open(path).convert("L")
    if normalize_width and im.width > normalize_width:
        im = im.resize((normalize_width, round(im.height * normalize_width / im.width)), Image.LANCZOS)
    return np.asarray(im, dtype=np.float64)


def ncc_map(img: "np.ndarray", tpl: "np.ndarray") -> "np.ndarray":
    """img 위에서 tpl 의 정규화 상호상관 지도 (유효 영역만)."""
    th, tw = tpl.shape
    ih, iw = img.shape
    if th > ih or tw > iw:
        return np.zeros((0, 0))
    t = tpl - tpl.mean()
    t_norm = float(np.sqrt((t**2).sum()))
    if t_norm == 0:
        return np.zeros((0, 0))

    fh = 1 << (ih + th - 2).bit_length()
    fw = 1 << (iw + tw - 2).bit_length()
    corr = np.fft.irfft2(np.fft.rfft2(img, s=(fh, fw)) * np.fft.rfft2(t[::-1, ::-1], s=(fh, fw)), s=(fh, fw))
    corr = corr[th - 1 : ih, tw - 1 : iw]

    ii = np.pad(img, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    ii2 = np.pad(img**2, ((1, 0), (1, 0))).cumsum(0).cumsum(1)

    def window(a: "np.ndarray") -> "np.ndarray":
        return a[th:, tw:] - a[:-th, tw:] - a[th:, :-tw] + a[:-th, :-tw]

    var = window(ii2) - (window(ii) ** 2) / (th * tw)
    var[var < 1e-9] = np.inf  # 균일한 영역은 상관을 정의하지 않는다
    return corr / (np.sqrt(var) * t_norm)


def load_templates() -> list[tuple[str, float, "np.ndarray"]]:
    if not TEMPLATE_DIR.exists():
        return []
    out: list[tuple[str, float, "np.ndarray"]] = []
    for path in sorted(TEMPLATE_DIR.glob("*.png")):
        base = to_gray(path)
        for scale in SCALES:
            if scale == 1.0:
                out.append((path.name, scale, base))
                continue
            h, w = round(base.shape[0] * scale), round(base.shape[1] * scale)
            resized = Image.fromarray(base.astype(np.uint8)).resize((w, h), Image.LANCZOS)
            out.append((path.name, scale, np.asarray(resized, dtype=np.float64)))
    return out


def best_score(img: "np.ndarray", tpls: list[tuple[str, float, "np.ndarray"]]) -> tuple[float, str, tuple[int, int, int, int] | None]:
    best, who, box = -1.0, "", None
    for name, _scale, tpl in tpls:
        m = ncc_map(img, tpl)
        if m.size == 0:
            continue
        idx = int(np.argmax(m))
        y, x = divmod(idx, m.shape[1])
        if m[y, x] > best:
            best, who, box = float(m[y, x]), name, (x, y, x + tpl.shape[1], y + tpl.shape[0])
    return best, who, box


def rel(path: Path) -> str:
    """저장소 기준 상대경로. 저장소 밖 파일도 그대로 찍는다 (검사 자체는 어디든 할 수 있다)."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def tracked_media() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8").stdout
    return [
        REPO_ROOT / line.strip()
        for line in out.splitlines()
        if line.strip() and Path(line.strip()).suffix.lower() in IMAGE_EXT | VIDEO_EXT
    ]


def check_video(path: Path, tpls: list, fps: float) -> list[tuple[float, float, tuple]]:
    work = Path(tempfile.mkdtemp(prefix="pii_frames_"))
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps}", str(work / "f_%05d.png"), "-y"],
            check=True,
        )
        hits = []
        for index, frame in enumerate(sorted(work.glob("*.png"))):
            score, _who, box = best_score(to_gray(frame, normalize_width=VIDEO_MATCH_WIDTH), tpls)
            if score >= HIT:
                hits.append((round(index / fps, 2), round(score, 3), box))
        return hits
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="스크린샷·영상 안의 실명 검사 (템플릿 매칭)")
    parser.add_argument("paths", nargs="*", help="검사할 파일 (없으면 Git 추적 중인 이미지·영상 전부)")
    parser.add_argument("--fps", type=float, default=1.0, help="영상에서 초당 몇 프레임을 볼지 (기본 1)")
    args = parser.parse_args()

    tpls = load_templates()
    if not tpls:
        print(f"템플릿이 없습니다: {TEMPLATE_DIR}", file=sys.stderr)
        print("  실명이 보이는 화면에서 글자 부분만 잘라 PNG 로 넣으세요 (이 폴더는 Git 에 올라가지 않습니다).", file=sys.stderr)
        print("  템플릿이 없으면 검사할 수 없습니다 — 「이상 없음」이 아니라 「검사 불가」입니다.", file=sys.stderr)
        return 2

    names = sorted({name for name, _s, _t in tpls})
    print(f"템플릿 {len(names)}종 × 배율 {len(SCALES)}: {', '.join(names)} · 임계 {HIT}")

    targets = [Path(p) for p in args.paths] if args.paths else tracked_media()
    failures = []
    for path in targets:
        suffix = path.suffix.lower()
        try:
            if suffix in VIDEO_EXT:
                hits = check_video(path, tpls, args.fps)
                if hits:
                    failures.append((path, hits))
                    print(f"  실명 발견  {rel(path)}  {len(hits)}프레임 {hits[:5]}")
            elif suffix in IMAGE_EXT:
                score, _who, box = best_score(to_gray(path), tpls)
                if score >= HIT:
                    failures.append((path, [(0.0, round(score, 3), box)]))
                    print(f"  실명 발견  {rel(path)}  score={score:.3f} box={box}")
        except Exception as exc:  # noqa: BLE001 - 한 파일이 실패해도 나머지는 계속 본다
            print(f"  건너뜀 {path.name}: {type(exc).__name__} {exc}", file=sys.stderr)

    print(f"\n검사 {len(targets)}개 · 실명이 보이는 파일 {len(failures)}개")
    if failures:
        print("가릴 것: 이미지는 PIL 사각형, 영상은 ffmpeg drawbox 로 해당 구간만 덮으세요.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
