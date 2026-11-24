"""JSON 저장소 공통 규칙 테스트 (app/core/storage.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import storage


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "doc.json"
    storage.write_json_atomic(path, {"a": 1, "한글": "값"})
    assert storage.read_json(path) == {"a": 1, "한글": "값"}
    # 임시 파일이 남지 않는다.
    assert [p.name for p in path.parent.iterdir()] == ["doc.json"]


def test_missing_file_returns_default(tmp_path: Path) -> None:
    assert storage.read_json(tmp_path / "none.json", default=[]) == []


def test_corrupt_file_is_quarantined_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(storage.CorruptJsonError) as exc:
        storage.read_json(path)
    assert not path.exists()
    quarantined = exc.value.quarantined
    assert quarantined is not None and quarantined.exists()
    assert quarantined.read_text(encoding="utf-8") == "{not json"


def test_stamp_sets_version_and_aware_timestamp() -> None:
    payload = storage.stamp({"x": 1})
    assert payload["schema_version"] == storage.SCHEMA_VERSION
    assert payload["updated_at"].endswith("+00:00")


def test_schema_version_defaults_to_1() -> None:
    assert storage.schema_version_of({}) == 1
    assert storage.schema_version_of({"schema_version": 3}) == 3
    assert storage.schema_version_of(None) == 1


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "x" * 65, "a b"])
def test_safe_id_rejects_path_like_values(bad: str) -> None:
    with pytest.raises(storage.InvalidIdError):
        storage.safe_id(bad)


def test_safe_id_accepts_notice_ids() -> None:
    assert storage.safe_id("g2b-R26BK01699556-000") == "g2b-R26BK01699556-000"


def test_ensure_aware_adds_utc() -> None:
    from datetime import datetime, timezone

    naive = datetime(2026, 9, 7, 9, 0)
    assert storage.ensure_aware(naive).tzinfo is timezone.utc
    aware = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)
    assert storage.ensure_aware(aware) is aware


def test_atomic_write_replaces_existing(tmp_path: Path) -> None:
    path = tmp_path / "doc.json"
    storage.write_json_atomic(path, {"v": 1})
    storage.write_json_atomic(path, {"v": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"v": 2}


# ---------------------------------------------------------------------------
# 업무 날짜는 한국 시간이다 (ISSUE-042 · TASK-020)
# ---------------------------------------------------------------------------


def test_업무_날짜는_서버_시간대가_아니라_한국_시간이다(monkeypatch) -> None:
    """`date.today()` 는 서버 로컬 시간대를 쓴다.

    UTC 로 도는 서버에서는 KST 기준 하루 «전» 날짜가 나오고, 그래서 어제 만료된 서류가
    다음 날 09:00 KST 까지 「유효」로 판정됐다. 담당자가 보는 날짜와 시스템이 판정하는
    날짜가 다르면 그 판정은 설명할 수 없는 값이 된다.

    17차부터 「오늘」은 「지금」(`utc_now`)에서 나온다(ISSUE-133). 그래서 그 한 자리를
    고정해서 잰다 — `datetime` 클래스를 갈아 끼우면 시계를 앞당겨 돌릴 때
    (`--timeshift-days`) 두 이음매가 겹쳐 무엇을 재는지 알 수 없어진다.
    """
    from datetime import date, datetime, timezone

    # UTC 로는 9월 16일 23:30, KST 로는 9월 17일 08:30 인 순간.
    moment = datetime(2026, 9, 16, 23, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(storage, "utc_now", lambda: moment)

    # `date.today()` 로 돌아가면 서버 로컬 날짜가 나와 틀리고, KST 변환을 빼먹으면
    # 9월 16일이 나와 틀린다. 둘 다 이 한 줄에 걸린다.
    assert storage.kst_today() == date(2026, 9, 17)
