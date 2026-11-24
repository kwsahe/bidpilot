"""10-31 최종 점검 W2 — 요구사항을 한 번도 뽑지 않은 공고의 조건 보고서는 「다시 뽑은 뒤 안 찾음」(stale)이 아니다."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import critical_condition_service as ccs

PID = "g2b-TEST1031-000"


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import rfp_parser

    monkeypatch.setattr(ccs, "CONDITION_DIR", tmp_path / "conditions")
    monkeypatch.setattr(rfp_parser, "GENERATED_DIR", tmp_path / "generated-empty")


def test_never_extracted_requirements_are_not_stale() -> None:
    built = ccs.build_report(PID, parse_result=None, eligibility=None, notice_available=True)
    assert built.stale is False
    assert built.stale_reason is None
    ccs.save_report(built)
    loaded = ccs.load_report(PID)
    assert loaded.stale is False
    assert loaded.stale_reason is None
    # 「아직 모름」은 그대로 — 0건을 「없음」이라 하지 않는다
    assert loaded.gate.reason.startswith("아직 모름")
