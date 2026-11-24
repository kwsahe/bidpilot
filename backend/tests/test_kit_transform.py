"""31차 §3-E — 키트 변환기 검사(R30-14 · R30-07): pdf · docx · .env.example · css · svg 도 보고, 꺼짐 사유의 파일 이름을 바꾼다.

`scripts/kit/kit_transform.py` 를 모듈로 불러 임시 키트 폴더에서 돈다. 실명 목록은 쓰지 않는다(빈 저장소 폴더).
"""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _kit_transform():
    spec = importlib.util.spec_from_file_location("kit_transform", ROOT / "scripts/kit/kit_transform.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _results(kit: Path, tmp_path: Path) -> dict[str, bool]:
    kt = _kit_transform()
    return {name.split(" ", 1)[0]: ok for name, ok, _ in kt.checks(kit, tmp_path / "repo")}


@pytest.fixture()
def kit(tmp_path: Path) -> Path:
    root = tmp_path / "kit"
    (root / "frontend/src/data").mkdir(parents=True)
    (root / "frontend/src/data/demo-snapshot.json").write_text("{}", encoding="utf-8")
    (root / "data").mkdir()
    return root


def test_docx_속_글자도_검사한다(kit: Path, tmp_path: Path) -> None:
    with zipfile.ZipFile(kit / "data/sample.docx", "w") as z:
        z.writestr("word/document.xml", "<w:t>SampleEdu BidPilot AI RFP</w:t>")
    assert _results(kit, tmp_path)["2"] is False
    with zipfile.ZipFile(kit / "data/sample.docx", "w") as z:
        z.writestr("word/document.xml", "<w:t>BidPilot AI RFP</w:t>")
    assert _results(kit, tmp_path)["2"] is True


@pytest.mark.parametrize("name", [".env.example", "style.css", "logo.svg"])
def test_env_예시_css_svg_도_검사한다(kit: Path, tmp_path: Path, name: str) -> None:
    (kit / name).write_text("APP_URL=https://sampleedu.example", encoding="utf-8")
    assert _results(kit, tmp_path)["2"] is False


def test_키트용_가상_예시_제안요청서는_검사를_통과한다(kit: Path, tmp_path: Path) -> None:
    assets = ROOT / "scripts/kit/assets"
    for name in ("synthetic_ai_training_rfp.docx", "synthetic_ai_training_rfp.pdf"):
        (kit / "data" / name).write_bytes((assets / name).read_bytes())
    assert _results(kit, tmp_path)["2"] is True


def test_꺼짐_사유가_키트에_없는_파일을_가리키지_않는다(kit: Path) -> None:
    kt = _kit_transform()
    target = kit / "backend/app/services/llm_client.py"
    target.parent.mkdir(parents=True)
    # 진짜 소스 줄 그대로 — 파이썬 문자열 안의 백슬래시 둘까지(36차 · 꺼짐 사유가 start_dev.bat 을 가리킨다)
    source = next(line for line in (ROOT / "backend/app/services/llm_client.py").read_text(encoding="utf-8").splitlines()
                  if line.startswith("PLAN_WRITER_OFF_REASON"))
    target.write_text(source + "\n", encoding="utf-8")
    kt.transform(kit)
    text = target.read_text(encoding="utf-8")
    assert "start_dev.bat" not in text and "stop_dev.ps1" not in text and "KIT_README.md" in text


def test_처음_안내_끝_문장은_가이드_화면을_가리키고_문서_경로가_없다(kit: Path) -> None:
    kt = _kit_transform()
    target = kit / "frontend/src/lib/terms.ts"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text((ROOT / "frontend/src/lib/terms.ts").read_text(encoding="utf-8"), encoding="utf-8")
    kt.transform(kit)
    text = target.read_text(encoding="utf-8")
    assert "사용 안내 「처음 입찰" not in text and "실전 가이드에서 보세요" in text


def test_가이드_6_4_출처의_docs_경로를_키트에_있는_것으로_바꾼다(kit: Path) -> None:
    """R31-30 — 키트에는 docs/ 가 없다. 화면이 읽는 frontend/content 원본과 GUIDE.md 둘 다."""
    kt = _kit_transform()
    guide = (ROOT / "frontend/content/first_time_guide.md").read_text(encoding="utf-8")
    for rel in ("frontend/content/first_time_guide.md", "GUIDE.md"):
        target = kit / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(guide, encoding="utf-8")
    kt.transform(kit)
    for rel in ("frontend/content/first_time_guide.md", "GUIDE.md"):
        text = (kit / rel).read_text(encoding="utf-8")
        assert "docs/user_guide.md" not in text and "docs/screen_guide.md" not in text, rel
        assert "KIT_README.md" in text, rel


def test_끄기_끝_문장도_키트에_있는_파일을_가리킨다(kit: Path) -> None:
    kt = _kit_transform()
    target = kit / "scripts/stop_dev.ps1"
    target.parent.mkdir(parents=True)
    target.write_text((ROOT / "scripts/stop_dev.ps1").read_text(encoding="utf-8"), encoding="utf-8")
    kt.transform(kit)
    text = target.read_text(encoding="utf-8")
    assert "start_dev.bat" not in text and "start_wireframe.bat" not in text and "start_kit.bat" in text
    assert "start_wireframe.ps1 로 띄운" not in text


def test_키트_env_는_키트에_없는_켜기_파일을_안내하지_않는다(kit: Path, tmp_path: Path) -> None:
    """32차 R31-29 — 저장소 .env.example 은 start_demo_*.bat 을 가리킨다. 키트에는 start_kit.bat 하나다."""
    kt = _kit_transform()
    (kit / ".env.example").write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    kt.transform(kit)
    text = (kit / ".env.example").read_text(encoding="utf-8")
    assert "start_demo" not in text and "start_kit.bat" in text
    assert _results(kit, tmp_path)["6"] is True


def test_검사_6_은_키트에_없는_켜기_파일_안내를_잡는다(kit: Path, tmp_path: Path) -> None:
    (kit / "KIT_README.md").write_text("다시 켜려면 scripts\\start_demo_ai.bat 을 누르세요\n", encoding="utf-8")
    assert _results(kit, tmp_path)["6"] is False


def test_켜기_요약_줄도_키트에_없는_start_dev_bat_을_가리키지_않는다(kit: Path, tmp_path: Path) -> None:
    """36차 마지막 검토 SC-2 — 키트는 실호출로 켜서 요약 줄 「매일 쓸 때는 start_dev.bat」이 그대로 보였다. 맨 위 도움말(<# … #>)은 보이지 않는다."""
    kt = _kit_transform()
    target = kit / "scripts/start_dev.ps1"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((ROOT / "scripts/start_dev.ps1").read_bytes())
    assert _results(kit, tmp_path)["6"] is False  # 바꾸기 전에는 검사 6 이 잡는다
    kt.transform(kit)
    assert "매일 쓸 때는 start_dev.bat" not in target.read_text(encoding="utf-8-sig")
    assert _results(kit, tmp_path)["6"] is True


def test_실전_가이드_켜기_줄은_키트에서_start_kit_bat(kit: Path, tmp_path: Path) -> None:
    """36차 §4 — 가이드 7장에 「켜기는 start_dev.bat 더블클릭」을 넣어 키트 GUIDE.md 가 검사 6 에 걸렸다(키트에는 start_kit.bat 하나)."""
    kt = _kit_transform()
    guide = kit / "GUIDE.md"
    guide.write_text((ROOT / "frontend/content/first_time_guide.md").read_text(encoding="utf-8"), encoding="utf-8")
    kt.transform(kit)
    text = guide.read_text(encoding="utf-8")
    assert "켜기는 `start_kit.bat` 더블클릭" in text and "start_dev.bat" not in text
    assert _results(kit, tmp_path)["6"] is True
