"""판 1.0 — `/health` 가 판 · 규칙 판을 싣고, 세 곳(백엔드 · pyproject · package.json)의 판이 같다(35차 §4-4)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import APP_VERSION, app
from app.services import support_application_service

ROOT = Path(__file__).resolve().parents[2]


def test_판은_세_곳이_같다() -> None:
    pyproject = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert APP_VERSION == pyproject["project"]["version"] == package["version"] == "2.10.0"


def test_health_가_판과_규칙_판을_싣는다() -> None:
    body = TestClient(app).get("/health").json()
    assert body["version"] == APP_VERSION
    assert body["rules_version"] == support_application_service.RULES_VERSION
