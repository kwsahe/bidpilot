"""**하루치 자격 정보 저장소** — 받은 날은 다시 부르지 않는다 (0922.md §4-A-1·§4-A-2).

## 왜 이 모양인가

7차는 면허제한·참가가능지역을 「30일 창 전체를 뒤에서부터」 받으려 했다. 창에 35,000행이
있어 예산(19회)으로는 끝 페이지 몇 장이 전부였고, 그 페이지에는 물품·공사만 있어서
**「이 API 는 용역 공고를 주지 않는다」는 틀린 결론**이 나왔다(ISSUE-081).

창을 **하루로** 좁히면 1,500~1,850행이라 999건씩 2페이지로 끝나고 용역 공고의 업종
코드가 그대로 온다(2026-09-22 재검증 §2-1 실측). 그래서 수집 단위를 「창」이 아니라
**「날」**로 바꾼다.

- 하루치를 받으면 `qualifications/<YYYY-MM-DD>.json` 에 **정규 형태로** 저장한다.
- 이미 있는 날은 다시 부르지 않는다. 그래서 백필은 한 번, 그 뒤로는 새로 생긴 날만 받는다.
- 공고는 **게시일**로 그 날의 자격 정보와 맞춘다. 맞는 날 파일이 없으면 「미확인」(None)이다.

## 「미확인」과 「제한 없음」

`license_limits`·`allowed_regions` 가 `None` 이면 **받아 본 적이 없다**, `[]` 면 **받았는데
제한이 없다**. 두 사실을 같은 값으로 적으면 참가할 수 없는 공고를 참가 가능으로 보여 주게
된다. 그 구분을 저장소가 지킨다 — 날 파일이 있으면 그 날의 공고는 전부 `[]` 이상이다.

## 정정 차수에 대한 정직한 한계

자격 행은 `bidNtceNo`+`bidNtceOrd` 로 맞춘다. 어떤 공고가 우리가 그 날을 받은 **뒤에**
정정되면 차수가 올라가고, 새 차수의 자격 행은 그 뒤 날짜에 등록된다. 그날을 아직 안
받았으면 최신 차수는 「미확인」으로 남는다 — 그것을 「제한 없음」이라고 말하지 않는다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from app.core import storage
from app.core.paths import DATA_ROOT
from app.services import g2b_mapper

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

STORE_DIR = DATA_ROOT / "public" / "sample_procurements" / "qualifications"
#: 39차 D20 — 매일 받기가 쓰는 하루치는 **Git 밖**이다(조항 파일과 같은 방식 · 38차 (7) 8). 추적 폴더(`STORE_DIR`)의 30개 날은
#: 기준본으로 읽기만 한다 — 10-16 예약 작업이 반쪽 날 2026-09-17 을 다시 받으며 추적 파일을 고쳤다(DAILY-07).
PRIVATE_STORE_DIR = DATA_ROOT / "private" / "qualifications"

#: 저장 형식 판. 모양을 바꾸면 올린다.
#:
#: v2 — **면허 정의표 + 참조**. 하루 1,543개 면허제한 행 중 서로 다른 정의는 213개뿐이라
#: (2026-09-17 실측), 정의를 한 번만 적고 공고는 번호로 가리킨다. 들여쓰기도 뺀다.
#: 같은 자료가 파일로는 442KB → 80KB 가 된다. 30일이면 13MB 와 2.4MB 의 차이다.
STORE_VERSION = 2


def path_for(day: date, *, private: bool = True) -> "Any":
    """그 날 파일 — 쓰기는 Git 밖(`private=True`), 기준본은 추적 폴더."""
    return (PRIVATE_STORE_DIR if private else STORE_DIR) / f"{day.isoformat()}.json"


def _existing_path(day: date) -> "Any | None":
    """읽을 파일 — Git 밖이 먼저, 없으면 추적 기준본. 둘 다 없으면 None."""
    for path in (path_for(day), path_for(day, private=False)):
        if path.exists():
            return path
    return None


@dataclass(frozen=True)
class DayRecord:
    """하루치 자격 정보 — **정규 형태로** 저장된 것."""

    day: date
    fetched_at: datetime
    #: 공고번호-차수 → `[{name, code, allowed_industries}]`
    licenses: dict[str, list[dict[str, Any]]]
    #: 공고번호-차수 → `[지역 이름]`
    regions: dict[str, list[str]]
    license_rows: int = 0
    region_rows: int = 0

    def license_limits(self, key: str) -> list[dict[str, Any]]:
        """이 날 받은 것 중 공고의 면허제한. 없으면 `[]` — **제한 없음**이라는 사실이다."""
        return self.licenses.get(key, [])

    def allowed_regions(self, key: str) -> list[str]:
        return self.regions.get(key, [])


def normalize(raw_licenses: dict[str, list[dict[str, Any]]], raw_regions: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    """원본 API 행 → 저장·판정이 읽는 정규 형태.

    원본 행을 그대로 두지 않는 이유: 하루 1,500행 × 30일이면 저장소가 수십 MB가 된다.
    판정이 실제로 읽는 것은 코드·이름·허용 업종·지역 이름뿐이다.
    """
    licenses = {
        key: rows
        for key, items in raw_licenses.items()
        if (rows := g2b_mapper.license_limits_of(items))
    }
    regions = {
        key: names
        for key, items in raw_regions.items()
        if (names := g2b_mapper.allowed_regions_of(items))
    }
    return licenses, regions


def _pack(licenses: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, list[int]]]:
    """면허제한을 **정의표 + 참조**로 접는다. 같은 정의가 하루에 수십 번 되풀이된다."""
    defs: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    packed: dict[str, list[int]] = {}
    for key, rows in licenses.items():
        refs: list[int] = []
        for row in rows:
            entry = {
                "name": row.get("name"),
                "code": row.get("code"),
                "allowed_industries": list(row.get("allowed_industries") or []),
            }
            token = json.dumps(entry, ensure_ascii=False, sort_keys=True)
            position = index.get(token)
            if position is None:
                position = len(defs)
                index[token] = position
                defs.append(entry)
            if position not in refs:
                refs.append(position)
        if refs:
            packed[key] = refs
    return defs, packed


def _unpack(defs: list[dict[str, Any]], packed: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for key, refs in packed.items():
        if not isinstance(refs, list):
            continue
        rows = [defs[i] for i in refs if isinstance(i, int) and 0 <= i < len(defs)]
        if rows:
            out[key] = rows
    return out


def save_day(
    day: date,
    *,
    licenses: dict[str, list[dict[str, Any]]],
    regions: dict[str, list[str]],
    fetched_at: datetime,
    license_rows: int = 0,
    region_rows: int = 0,
) -> DayRecord:
    """하루치를 저장한다(Git 밖). 이미 정규화된 값을 받는다."""
    PRIVATE_STORE_DIR.mkdir(parents=True, exist_ok=True)
    defs, packed = _pack(licenses)
    payload = {
        "_note": "나라장터 면허제한·참가가능지역 하루치 (0922 §4-A). 값이 없는 공고는 「제한 없음」이다.",
        "version": STORE_VERSION,
        "day": day.isoformat(),
        "fetched_at": fetched_at.astimezone(timezone.utc).isoformat(),
        "license_rows": license_rows,
        "region_rows": region_rows,
        "license_defs": defs,
        "licenses": packed,
        "regions": regions,
    }
    storage.write_json_atomic(path_for(day), payload, compact=True)
    return DayRecord(
        day=day,
        fetched_at=fetched_at,
        licenses=_unpack(defs, packed),
        regions=regions,
        license_rows=license_rows,
        region_rows=region_rows,
    )


def load_day(day: date) -> DayRecord | None:
    """저장된 하루치(Git 밖이 먼저 · 없으면 추적 기준본). 없거나 깨졌으면 None — 그 날의 공고는 「미확인」이다."""
    path = _existing_path(day)
    if path is None:
        return None
    payload = storage.read_json(path)
    if not isinstance(payload, dict):
        logger.warning("자격 저장소를 읽지 못했습니다: %s", path)
        return None
    try:
        fetched = datetime.fromisoformat(str(payload.get("fetched_at")))
    except ValueError:
        fetched = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    licenses = payload.get("licenses")
    regions = payload.get("regions")
    defs = payload.get("license_defs")
    if isinstance(defs, list) and isinstance(licenses, dict):
        # v2 — 정의표 + 참조.
        rows = _unpack(defs, licenses)
    else:
        # v1 — 공고마다 정의를 통째로 들고 있던 모양. 읽기만 지원한다.
        rows = licenses if isinstance(licenses, dict) else {}
    return DayRecord(
        day=day,
        fetched_at=fetched if fetched.tzinfo else fetched.replace(tzinfo=timezone.utc),
        licenses=rows,
        regions=regions if isinstance(regions, dict) else {},
        license_rows=int(payload.get("license_rows") or 0),
        region_rows=int(payload.get("region_rows") or 0),
    )


def known_days() -> set[date]:
    """이미 받아 둔 날들(Git 밖 · 추적 기준본 둘 다). **여기 있는 날은 다시 부르지 않는다.**"""
    out: set[date] = set()
    for folder in (PRIVATE_STORE_DIR, STORE_DIR):
        if not folder.exists():
            continue
        for path in folder.glob("*.json"):
            try:
                out.add(date.fromisoformat(path.stem))
            except ValueError:
                continue
    return out


def settled(record: DayRecord) -> bool:
    """그 날이 다 지난 뒤(KST 다음 날 이후)에 받은 하루치인가.

    그날 안에 받으면 그 뒤에 올라온 공고가 파일에 없고, 없는 공고는 「제한 없음」(`[]`)으로 읽힌다 —
    9-29 15:47 에 받은 9-29 파일이 반쪽이었다(33차 · 옛 최신화 절차서 발견 A · 지금 절차는 `docs/refresh_procedure.md`). 그런 날은 다음 수집에서 다시 받는다.
    """
    return record.fetched_at.astimezone(KST).date() > record.day


def settled_days(days: Iterable[date]) -> set[date]:
    """다시 부르지 않아도 되는 날 — 파일이 있고 그 날이 지난 뒤에 받은 것."""
    return {day for day, record in load_all(days).items() if settled(record)}


def load_all(days: Iterable[date]) -> dict[date, DayRecord]:
    records: dict[date, DayRecord] = {}
    for day in days:
        record = load_day(day)
        if record is not None:
            records[day] = record
    return records


_FIRST_DAY_MEMO: dict[str, Any] = {"key": None, "days": {}}


def first_published_days() -> dict[str, date]:
    """공고번호(차수 뺌) → 처음 게시된 날(자격 하루치 파일은 게시일별로 받는다 · 43차 M2). 변경공고(001+)의 원공고 게시일을 여기서 안다.
    파일 목록 · 수정 시각이 같으면 다시 읽지 않는다."""
    paths = sorted({*PRIVATE_STORE_DIR.glob("*.json"), *STORE_DIR.glob("*.json")}) if PRIVATE_STORE_DIR.exists() or STORE_DIR.exists() else []
    key = tuple((str(p), p.stat().st_mtime_ns) for p in paths)
    if _FIRST_DAY_MEMO["key"] == key:
        return _FIRST_DAY_MEMO["days"]
    days: dict[str, date] = {}
    for path in paths:
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        record = load_day(day)
        if record is None:
            continue
        for notice_key in (*record.licenses.keys(), *record.regions.keys()):
            bid_no = notice_key.split("-")[0]
            if bid_no and (bid_no not in days or day < days[bid_no]):
                days[bid_no] = day
    _FIRST_DAY_MEMO.update(key=key, days=days)
    return days


def published_day(published_at: datetime | None) -> date | None:
    """공고 게시일시 → 자격 저장소의 날 (KST 기준). 자격 행의 `rgstDt` 와 같은 축이다."""
    if published_at is None:
        return None
    moment = published_at if published_at.tzinfo else published_at.replace(tzinfo=KST)
    return moment.astimezone(KST).date()


@dataclass(frozen=True)
class Coverage:
    """읽어 둔 날들로 「이 공고의 자격은 무엇인가」에 답한다.

    `g2b_mapper.map_notices` 가 이것 하나만 받는다 — 매핑 쪽이 저장소를 모르게 한다.
    """

    records: dict[date, DayRecord]

    def lookup(self, key: str, published_at: datetime | None) -> tuple[list[dict[str, Any]] | None, list[str] | None, datetime | None]:
        """`(license_limits, allowed_regions, checked_at)`. 못 받은 날이면 `(None, None, None)`."""
        day = published_day(published_at)
        record = self.records.get(day) if day is not None else None
        if record is None:
            return None, None, None
        # 파일을 받은 **뒤에** 게시된 공고는 그 파일에 있을 수 없다 — 「제한 없음」이 아니라 「미확인」(33차 · 절차서 A)
        if published_at is not None and record.fetched_at <= (published_at if published_at.tzinfo else published_at.replace(tzinfo=KST)):
            return None, None, None
        return record.license_limits(key), record.allowed_regions(key), record.fetched_at

    @property
    def days(self) -> list[date]:
        return sorted(self.records)


def coverage_for(days: Iterable[date]) -> Coverage:
    return Coverage(records=load_all(days))
