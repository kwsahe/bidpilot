"""캐시가 **크게 줄면 저장하지 않는다** (ISSUE-121 · prompt_03 §4-B).

## 왜 이 파일이 있나

13차에 기업마당 목록 조회가 100건만 받아 와 1,620건짜리 캐시를 덮었다. 파일이 깨진 것이
아니라 **정상적으로** 쓰였기 때문에 아무도 몰랐다 — 다음 사람이 목록을 열고 나서야
「왜 100건뿐이지」가 됐고, 그 캐시는 gitignore 아래라 되돌릴 수도 없었다.
11차에도 같은 모양으로 기준 답안 두 건이 영구히 사라졌다.

목록이 절반 아래로 줄어드는 것은 거의 언제나 「덜 받아 온 것」이지 「그만큼밖에 없는
것」이 아니다. **의심스러우면 옛것을 지킨다.**

## 무엇을 재는가

프롬프트 §4-B-2 가 지목한 두 줄 그대로다 — **1,620 → 100 은 막고, 1,620 → 1,578 은 쓴다.**
막았을 때 파일이 **그대로인지**까지 본다. 「막았다」고 말만 하고 쓰는 것이 제일 나쁘다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core import storage
from app.core.config import get_settings
from app.services import bizinfo_service

NOW = datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)


def _program(index: int) -> dict[str, str]:
    return {
        "pblancId": f"PBLN_{index:018d}",
        "pblancNm": f"시험 지원사업 {index}",
        "jrsdInsttNm": "시험 기관",
    }


# --------------------------------------------------------------------------
# 판정 자체 — 순수 함수라 경계가 분명하다
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "existing, incoming, blocked",
    [
        (1620, 100, True),  # 13차 사고 그대로
        (1620, 1578, False),  # 마감으로 줄어든 정상 감소
        (1620, 810, False),  # 정확히 절반 — 막지 않는다
        (1620, 809, True),  # 절반 바로 아래
        (1620, 0, True),  # 0 건은 가장 흔한 실패 모양이다
        (0, 100, False),  # 처음 받는 것을 막을 이유가 없다
        (100, 1620, False),  # 늘어나는 것은 언제나 좋다
    ],
)
def test_절반_아래로_줄면_막는다(existing: int, incoming: int, blocked: bool) -> None:
    reason = storage.cache_shrink_reason(existing=existing, incoming=incoming, allow_shrink=False)
    assert bool(reason) is blocked, reason


def test_막는_사유에_두_숫자가_다_적힌다() -> None:
    """사유만 보고 「무엇이 무엇을 덮으려 했는가」를 알 수 있어야 한다."""
    reason = storage.cache_shrink_reason(existing=1620, incoming=100, allow_shrink=False)
    assert reason is not None
    assert "100" in reason and "1,620" in reason
    # 되돌리는 법도 함께 — 기대값 바꿈(27차 §3-H): 설정 이름 대신 한국어 안내
    assert "허용" in reason and "CACHE_ALLOW_SHRINK" not in reason


def test_허용하면_그대로_쓴다() -> None:
    """실제로 줄어든 것이 맞을 때 담당자가 여는 문 (`CACHE_ALLOW_SHRINK=1`)."""
    assert storage.cache_shrink_reason(existing=1620, incoming=100, allow_shrink=True) is None


def test_설정을_안_주면_설정에서_읽는다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "cache_allow_shrink", True)
    assert storage.cache_shrink_reason(existing=1620, incoming=100) is None
    monkeypatch.setattr(get_settings(), "cache_allow_shrink", False)
    assert storage.cache_shrink_reason(existing=1620, incoming=100) is not None


# --------------------------------------------------------------------------
# 실제 저장 경로 — 막았을 때 **파일이 그대로인가**
# --------------------------------------------------------------------------


@pytest.fixture()
def bizinfo_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "bizinfo_cache.json"
    monkeypatch.setattr(bizinfo_service, "CACHE_FILE", path)
    payload = {
        "fetched_at": NOW.isoformat(),
        "total_fetched": 1620,
        "items": [bizinfo_service._normalize_item(_program(i)) for i in range(1620)],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_1620을_100으로_덮으려_하면_파일이_그대로다(bizinfo_cache: Path) -> None:
    """13차 사고 그대로. 사유를 돌려주고 **디스크는 건드리지 않는다.**"""
    before = bizinfo_cache.read_bytes()

    reason = bizinfo_service._save_cache([_program(i) for i in range(100)], NOW)

    assert reason is not None, "막았어야 한다"
    assert bizinfo_cache.read_bytes() == before, "막았다면서 파일을 썼다"
    assert len(json.loads(bizinfo_cache.read_text(encoding="utf-8"))["items"]) == 1620


def test_1620에서_1578은_그대로_저장한다(bizinfo_cache: Path) -> None:
    """정상적인 감소까지 막으면 캐시가 영영 낡는다."""
    reason = bizinfo_service._save_cache([_program(i) for i in range(1578)], NOW)

    assert reason is None
    assert len(json.loads(bizinfo_cache.read_text(encoding="utf-8"))["items"]) == 1578


def test_허용_설정을_켜면_줄어드는_저장도_쓴다(
    bizinfo_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "cache_allow_shrink", True)

    assert bizinfo_service._save_cache([_program(i) for i in range(100)], NOW) is None
    assert len(json.loads(bizinfo_cache.read_text(encoding="utf-8"))["items"]) == 100
