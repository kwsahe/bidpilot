"""읽기-수정-쓰기를 잠근다 — 동시에 눌러도 한쪽이 사라지지 않는다 (ISSUE-032).

## 왜

`write_json_atomic` 은 **반쪽 파일**만 막는다. 임시 파일에 다 쓴 뒤 `os.replace` 하므로
읽는 쪽이 잘린 JSON 을 보는 일은 없다. 그런데 이 저장소의 쓰기는 거의 전부
「파일 전체를 읽고 → 한 항목을 고치고 → 파일 전체를 다시 쓰는」 모양이다.

    A: 목록[1,2] 읽음                 B: 목록[1,2] 읽음
    A: [1,2,3] 씀                     B: [1,2,4] 씀   ← 3 이 사라진다

파일은 멀쩡하다. **그래서 아무도 모른다.** 담당자는 방금 추가한 할 일이 새로고침하면
없어지는 것을 보고 「저장이 안 되네」라고만 생각한다.

여기서 고정하는 것은 두 가지다.

1. 두 스레드가 같은 체크리스트에 항목을 하나씩 더하면 **둘 다 남는다.**
2. 잠금 파일이 `data/private/.locks/` 밖으로 새지 않는다 — `data/public/` 에 `*.lock` 이
   생기면 git 작업 트리가 더러워지고, 시연 전에 `git status` 를 보는 사람이 놀란다.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.core import storage
from app.schemas.action import ActionCreateRequest
from app.services import action_service


@pytest.fixture
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """체크리스트 저장 위치와 잠금 폴더를 tmp 로 돌린다."""
    monkeypatch.setattr(storage, "LOCK_DIR", tmp_path / "locks")
    checklist = tmp_path / "actions" / "demo.json"
    monkeypatch.setattr(action_service, "checklist_path", lambda *_a, **_k: checklist)
    return checklist


def test_두_스레드가_동시에_더해도_둘_다_남는다(isolated_store: Path) -> None:
    started = threading.Barrier(2)
    errors: list[BaseException] = []

    def add(title: str) -> None:
        try:
            started.wait(timeout=5)
            action_service.create_action("demo", ActionCreateRequest(title=title))
        except BaseException as exc:  # noqa: BLE001 — 스레드 예외를 본문으로 옮긴다
            errors.append(exc)

    threads = [threading.Thread(target=add, args=(f"할 일 {i}",)) for i in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)

    assert not errors, errors
    titles = {item.title for item in action_service.load_checklist("demo").items}
    assert titles == {"할 일 1", "할 일 2"}


def test_잠금_파일은_잠금_폴더에만_생긴다(isolated_store: Path, tmp_path: Path) -> None:
    action_service.create_action("demo", ActionCreateRequest(title="하나"))

    assert list((tmp_path / "locks").glob("*.lock")), "잠금 파일이 잠금 폴더에 없습니다"
    strays = [p for p in isolated_store.parent.rglob("*.lock")]
    assert strays == [], f"대상 파일 옆에 잠금 파일이 샜습니다: {strays}"


def test_잠금은_재진입이_아니다_같은_경로를_두_번_잡으면_시간_안에_실패한다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """겹쳐 잠그면 **조용히 통과시키지 않고** 시간 안에 실패한다.

    재진입을 허용하면 「잠갔으니 안전하다」가 거짓이 된다. 대신 실패가 빨라야 하므로
    호출하는 쪽이 timeout 을 줄일 수 있게 해 두었다.
    """
    monkeypatch.setattr(storage, "LOCK_DIR", tmp_path / "locks")
    target = tmp_path / "x.json"
    with storage.locked(target):
        with pytest.raises(storage.LockTimeoutError):
            with storage.locked(target, timeout=0.2):
                pass


def test_잠금을_풀면_다음_사람이_바로_잡는다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "LOCK_DIR", tmp_path / "locks")
    target = tmp_path / "x.json"
    with storage.locked(target, timeout=1.0):
        pass
    with storage.locked(target, timeout=1.0):
        pass  # 예외 없이 두 번째도 잡힌다
