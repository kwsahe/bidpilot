"""기준 답안 40건과 앱을 대조한다 — 0921 §4-F-1 · **0922 §4-E-1 확장** 수용 스크립트.

## 무엇을 재는가

검수자가 손으로 조사해 만든 `docs/reports/2026-09-20_apply_candidates.csv`
(나라장터 24건 + 기업마당 16건)를 읽어, **지금 도는 앱이 같은 답을 내는지** 항목마다
확인한다. 「테스트가 통과했다」가 아니라 **「사람이 손으로 찾은 것을 앱도 찾는가」**를
재는 것이 이 스크립트의 목적이다.

## 재는 항목

| 항목 | 기준 답안 | 앱에서 읽는 값 |
| --- | --- | --- |
| 존재 | 40건 전부 | `/api/business-opportunities` 에 id 가 있는가 |
| 예산 | CSV `예산(원)` | `item.budget` |
| 마감 | CSV `마감/접수` | `item.deadline` (날짜까지) |
| 실적 | 「실적 없음」 | `ELIG-TRACK-RECORD` 가 「가능」 |
| 공동수급 | 「공동수급 불허 / 공동이행 허용」 | 공고의 `cmmnSpldmdMethdNm` |
| 업종 | 「SW사업자(…)」 등 | `ELIG-INDUSTRY` 가 「확인 필요」(회사 등록 업종 미입력이므로) |
| 지역 | 「지역 해당없음 / 투찰제한 있음」 | `ELIG-REGION` |
| 기업마당 | 16건 | 존재 + 판정이 「불가」가 아닐 것 |

## 10차에서 더한 검사 (0924 §4-E-1)

검수자가 **공고문 26건을 직접 내려받아 읽고** 만든 두 번째 기준 답안
(`docs/reports/2026-09-24_bizinfo_candidates.csv`)과 견준다.

| 항목 | 기준 답안 | 앱에서 읽는 값 |
| --- | --- | --- |
| 존재 | 26건 전부 | `/api/business-opportunities` 에 id 가 있는가 |
| **판정** | 가능 / 확인 필요 / 불가 / 간접 | `eligibility_gate` · `participation` |
| **근거(공고문)** | 검수자가 인용한 조항 | 앱 `clause_quotes` 에 그 조각이 있는가 |
| **받는 것** | 금액·비율 | 앱이 공고문에서 읽은 금액·비율과 맞는가 |
| **순위** | A1~A3 상위 10(10-11 검수자 결정 · 전에는 5) · E 그룹 상위 30 밖 · C4 숨김 | 기업마당 `source_rank` |
| **엑셀** | 시트 일곱 | 워크북의 「기업마당」 시트에 같은 판정으로 있는가 |

**판정 대조의 예외 둘** — 앱이 검수자보다 «더 확신해서는 안 되는» 자리다.

- 검수자가 「추정」이라고 적은 행(E2, 20인 미만 추정)은 **불가 또는 확인 필요** 둘 다 맞다.
  회사 상시 근로자 수는 아직 미입력이라 앱이 「불가」로 단정하면 근거 없는 판정이 된다.
- 「낮음」·「부적합」은 자격이 아니라 **우선순위** 판단이다. 그 행은 판정 대신 **순위**로 잰다
  (E 그룹 상위 30 밖). 검수자 자신도 82건 중 26건만 공고문을 읽었으므로, 앱이 그 26건 밖에서
  더 나은 건을 찾는 것은 어긋남이 아니다.

## 8차에서 더한 검사 (0922 §4-E-1)

| 항목 | 기준 | 앱에서 읽는 값 |
| --- | --- | --- |
| **업종 코드** | CSV 「SW사업자(1468)」·「4종」·「9999」 | `ELIG-INDUSTRY` 의 `source` 에 적힌 코드 |
| **지역 값** | CSV 「지역 투찰제한 있음」·「지역 해당없음」 | `ELIG-REGION` 의 `source` 에 적힌 지역 이름 |
| **1468 → +9** | 개발 공고 15건 중 9건 | A그룹에서 1468 을 요구하는 건수 |
| **순위 (상위 5 안)** | A1 한양사이버대 · A2 한남대 · A3 KISTI | 나라장터 개발형 순위 |
| **순위 (A 행보다 아래)** | 강원대 3.8억 · 울산항 · 콜롬비아 · 박람회 대행 · SBS · 임차 · 감리 · 영향평가 | 뺀 것 각각이 **마감 전 A 행 전부보다 아래**(절대 순위를 쓰지 않는다 — 18차 ISSUE-135) |
| **점수 분포** | 두 값에 몰리지 않을 것 | 상위 30건의 고유 점수 ≥ 8개 |
| **마감 무관** | 마감은 점수에 없다 | `score_components` 에 `schedule` 키 없음 · 성분이 같으면 점수도 같음 |
| **기업마당 관련** | 검수자가 고른 16건 전부 「관련」 | `relevance_note is null` |
| **관련 낮음** | 페어링·무기체계·모두의 창업 | `relevance_note` 가 있을 것 |

## 19차에서 더한 검사 (prompt_09 §4-D)

담당자 지시: 「자격요건은 확실하게 가져와서 판단해야 해. 따로 판단하도록 해줘.」
기준 답안의 「공고서」는 **나라장터 화면에 값이 없어 입찰공고문을 열어야 확인됐다**는 뜻이다.
앱이 그 공고문을 열어 같은 것을 찾는지 `qual-doc` 으로 잰다. **마감 지난 행도 이 검사만은
한다** — 파일이 있는지·조항이 나오는지는 마감과 무관하다.

| 항목 | 기준 답안 | 앱에서 읽는 값 |
| --- | --- | --- |
| 조항 파일 | 24행 전부 | `qualification_clauses/<id>.json` 이 있고 `status == ok` (image·no_section 은 [못 잼]) |
| 업종 | 「SW사업자(1468)」·「(1426/…)」·「(9999)」 | 업종 줄(`ELIG-INDUSTRY`·`QUAL-INDUSTRY-*`)이 확인 필요(회사 쪽)이고 열리는 조건에 그 코드 |
| 지역/업종 공고서 | 공고문을 열어야 했던 행 | 공고문 조항에 지역·업종 조항이 하나 이상. 절을 다 읽었는데 없으면 [못 잼] — 기준 답안이 제한 유무를 적지 않았다 |
| 공동수급 | 「불허」·「공동이행 허용」 | 공고문 조항까지 본 앱의 공동수급 읽기 |
| 실적 | 「실적 없음」 | `ELIG-TRACK-RECORD` 가능(필드). 실적 조항이 있으면 그 줄에 **원장 대조 결과**가 적힌다 |
| 두 화면(나라장터) | 마감 전 기준 답안 행 | 목록 `eligibility_gate` == `/api/eligibility/{id}` 종합 |
| 1468 (시나리오) | `--industry-scenario` | 시험 계정에 1468 을 적으면 1468 행의 업종 줄이 전부 가능 |

## 마감이 지난 기준 답안 행 (ISSUE-132 · 17차 §4-B)

기준 답안은 **2026-09-20 에 만든 사진**이다. 그 안의 공고·사업은 날짜가 가면 마감된다.
126347(광양 실증)은 9-21 에 마감돼 `BIZ-PERIOD FAIL` 이 붙었고, 그러면 「소재만 막는
경우 간접」 규칙이 닫혀 「불가」가 됐다 — **앱이 맞다.** 틀린 것은 마감 지난 행을 그대로
견주는 쪽이었다. 기준 답안에는 9-23 · 9-27 · 9-28 마감이 더 있어서, 그대로 두면 시연
전에 상위 5 검사까지 줄줄이 빨개진다.

그래서 마감이 지난 행은 **있는지만 확인하고** 판정·근거·순위·두 화면 대조에서 뺀다.
빼는 것을 감추지 않는다.

- 머리말에 「마감 지나 제외 n행」과 그 행의 마감 시각을 전부 적는다.
- 뺀 검사는 사라지지 않고 **「마감으로 검사 못 함」**으로 남는다(`[못 잼]`). 일치도
  불일치도 아니라 분모에서도 빠진다 — 「조용히 초록」이 되지 않게 하는 것이 요점이다.
  A1~A3 이 9-28 에 마감되면 「1~3순위가 상위 5 안」 검사가 그렇게 표시된다.
- 「상시 접수」·「예산 소진시까지」·「선착순」·「충원 시」처럼 **끝나는 날이 적혀 있지 않은
  것은 마감으로 보지 않는다.** 지어내면 살아 있는 사업을 검사에서 빼 버린다.

## 쓰는 법

서버가 떠 있어야 한다(`scripts/start_demo.bat` 또는 `start_dev.ps1 -Frozen`).

```
backend/.venv/Scripts/python.exe scripts/check_apply_candidates.py
backend/.venv/Scripts/python.exe scripts/check_apply_candidates.py --json
backend/.venv/Scripts/python.exe scripts/check_apply_candidates.py --today 2026-09-29
```

`--today` 는 **기준 답안의 마감이 지났는지 가리는 데만** 쓴다. 앱의 시계는 밖에서
앞당길 수 없으므로 앱의 판정은 그대로다 — 「그 날이 되면 어떤 검사가 사라지는가」를
미리 보는 용도다.

불일치가 하나라도 있으면 **종료 코드 1**이다. 「마감으로 검사 못 함」은 종료 코드를
바꾸지 않는다 — 그것은 앱의 잘못이 아니라 기준 답안이 늙은 것이다.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "docs" / "reports" / "2026-09-20_apply_candidates.csv"
#: 검수자가 **공고문을 읽고** 만든 두 번째 기준 답안 (0924 §4-E-1).
BIZINFO_CSV_PATH = ROOT / "docs" / "reports" / "2026-09-24_bizinfo_candidates.csv"
BACKEND = "http://127.0.0.1:8110"
ORG = "org-sample"

OK = "  [일치] "
BAD = "  [다름] "
INFO = "  [참고] "
SKIP = "  [못 잼] "

#: 업무 날짜는 한국 시간이다 (앱의 `storage.kst_today()` 와 같은 규칙).
KST = timezone(timedelta(hours=9))

#: 이 실행이 보는 「지금」. `main()` 이 정한다 — 기본은 실제 시계(= 앱의 `storage.utc_now()`),
#: `--today` 를 주면 그 시각이다.
NOW: datetime = datetime.now(KST)

#: 개발형 마감 전 풀 크기(`NOW` 기준). `_extra_checks` 가 정하고 머리말이 적는다.
#: 순위 검사는 이 풀 안에서만 뜻이 있다 — 풀이 줄면 「상위 N」이 저절로 틀려진다(ISSUE-135).
DEV_POOL: int | None = None


@dataclass
class Check:
    """한 건에 대한 대조 결과."""

    key: str
    title: str
    #: (항목, 기준, 앱, 같은가) — 「같은가」는 참·거짓·**None** 셋이다.
    #: None 은 「잴 수 없음」이다. 불일치도 일치도 아니라서 따로 센다 (ISSUE-132 · §4-B).
    rows: list[tuple[str, str, str, bool | None]] = field(default_factory=list)

    def add(self, label: str, expected: str, actual: str, same: bool) -> None:
        self.rows.append((label, expected, actual, same))

    def cannot(self, label: str, expected: str, why: str) -> None:
        """**조용히 초록이 되지 않게** 한다 (§4-B-2).

        기준 답안의 마감이 지나면 그 행으로는 아무것도 잴 수 없다. 그렇다고 검사를
        지우거나 「대상 없음」으로 통과시키면, 시연 전에 상위 5 검사가 저절로 사라진다.
        여기 남겨서 「마감으로 검사 못 함」이라고 적는다.
        """
        self.rows.append((label, expected, why, None))

    @property
    def mismatches(self) -> list[tuple[str, str, str, bool | None]]:
        return [row for row in self.rows if row[3] is False]

    @property
    def unmeasured(self) -> list[tuple[str, str, str, bool | None]]:
        return [row for row in self.rows if row[3] is None]


def fetch(path: str) -> Any:
    try:
        with urllib.request.urlopen(f"{BACKEND}{path}", timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError:
        # 서버는 떠 있고 이 주소 하나가 실패했다 — 부른 쪽이 그 행만 실패로 적는다.
        # (HTTPError 는 URLError 의 자식이라 아래로 떨어지면 「연결하지 못했습니다」로 스크립트가 멎는다.)
        raise
    except urllib.error.URLError as exc:
        print(f"백엔드에 연결하지 못했습니다 ({BACKEND}) — {exc}")
        print("서버를 먼저 띄우세요: scripts\\start_demo.bat 또는 start_dev.ps1 -Frozen -NoBrowser")
        raise SystemExit(2) from exc


def rules_of(procurement_id: str) -> dict[str, dict[str, Any]]:
    """공고 하나의 자격 규칙 결과. 판정 근거를 항목별로 보려면 이것이 필요하다."""
    try:
        report = fetch(f"/api/eligibility/{procurement_id}?organization_id={ORG}&evidence_scope=internal")
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        return {}
    return {r["rule_id"]: r for r in report.get("results", [])}


def money(text: str) -> int | None:
    digits = "".join(ch for ch in (text or "") if ch.isdigit())
    return int(digits) if digits else None


def day(text: str | None) -> str:
    """날짜만 비교한다 — 시각까지 맞추면 시간대 표기 차이로 거짓 불일치가 난다.

    기업마당의 「마감/접수」는 `시작 ~ 종료` 범위로 적혀 있다. 우리가 견줄 것은 **종료**다 —
    시작을 견주면 아홉 건이 전부 거짓 불일치로 나온다.
    """
    if not text:
        return ""
    value = str(text)
    if "~" in value:
        value = value.split("~")[-1]
    return value.strip()[:10]


_GOLD_DAY = re.compile(r"(20\d\d)[-./](\d\d)[-./](\d\d)")
_GOLD_TIME = re.compile(r"(\d\d):(\d\d)")


def gold_deadline(text: str | None) -> datetime | None:
    """기준 답안의 마감 열에서 **끝나는 순간**을 뽑는다. 못 뽑으면 None.

    열에 적힌 꼴이 여러 가지다 — `2026-09-28T14:00` · `2026-09-16 ~ 2026-09-23` ·
    `2026-09-08 ~ 2026-09-23 18:00` · `~2026-10-30 (개별 일정 협의)` ·
    `2026-09-11 ~ 충원 시` · `예산 소진시까지` · `상시 접수` · `선착순 상시`.

    「끝나는 날이 적혀 있지 않은 것」(상시·예산 소진·충원 시·선착순)은 **마감으로 보지
    않는다.** 지어내면 살아 있는 사업을 검사에서 빼 버린다.

    시각이 없으면 그 날 23:59 로 본다 — 「~2026-09-23」은 23일까지 받는다는 뜻이다.
    """
    if not text:
        return None
    tail = str(text).split("~")[-1]
    day_match = _GOLD_DAY.search(tail)
    if not day_match:
        return None
    year, month, dom = (int(g) for g in day_match.groups())
    time_match = _GOLD_TIME.search(tail[day_match.end():])
    if time_match:
        return datetime(year, month, dom, int(time_match.group(1)), int(time_match.group(2)), tzinfo=KST)
    return datetime(year, month, dom, 23, 59, tzinfo=KST)


def _app_deadline(item: dict[str, Any]) -> datetime | None:
    """앱 항목의 마감(`deadline`, ISO · 시간대 포함). 없으면 None."""
    raw = item.get("deadline")
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=KST)


def _app_closed(item: dict[str, Any]) -> bool:
    """앱 항목이 **이 실행의 「지금」(`NOW`)** 에 마감됐는가.

    앱의 `closed` 는 앱의 시계다. `--today` 로 앞당겨 볼 때도 같은 판단이 되도록
    마감 시각을 직접 견준다. 마감이 없으면(상시) 마감으로 보지 않는다.
    """
    end = _app_deadline(item)
    return end is not None and end < NOW


#: 앱이 「불가」로 숨긴 사유가 **마감**인 표지 (ISSUE-142). 입찰 마감 전이라도 참가자격 등록 마감이 지나면
#: 앱은 불가로 숨긴다 — 앱이 맞다. 그것을 「목록에 없음 → 다름」으로 세지 않는다.
DEADLINE_BLOCK_WORDS = ("참가자격 등록 마감", "입찰서 제출 마감")


def _deadline_block(item: dict[str, Any] | None) -> str | None:
    """앱 항목이 마감 때문에 「불가」면 그 사유 낱말(예 「참가자격 등록 마감」), 아니면 None."""
    if not item or item.get("eligibility_gate") != "FAIL":
        return None
    reason = item.get("gate_reason") or ""
    return next((word for word in DEADLINE_BLOCK_WORDS if word in reason), None)


def _deadline_text(item: dict[str, Any]) -> str:
    end = _app_deadline(item)
    return f"{end.astimezone(KST):%Y-%m-%d %H:%M}" if end else "마감일 없음"


def gold_closed(text: str | None) -> datetime | None:
    """마감이 **이미 지났으면** 그 순간을, 아니면 None."""
    end = gold_deadline(text)
    return end if end is not None and end < NOW else None


def closed_gold_rows(
    reference: list[dict[str, str]], bizinfo_rows: list[dict[str, str]]
) -> dict[str, str]:
    """`{앱 id: 마감 표시}` — 판정·근거·순위·두 화면 대조에서 뺄 행들.

    **앱이 맞고 기준 답안이 늙은 것이다.** 126347(광양 실증)은 9-21 에 마감돼
    `BIZ-PERIOD FAIL` 이 붙었고, 그러면 「소재만 막는 경우 간접」 규칙이 닫혀 「불가」가
    된다 — 앱의 판정이 옳다. 마감 지난 행을 그대로 견주면 시연 전에 상위 5 검사까지
    줄줄이 빨개진다(9-23 · 9-27 · 9-28 마감이 기준 답안에 있다).

    존재 검사는 **그대로 한다** — 마감됐어도 목록에는 있어야 한다.
    """
    closed: dict[str, str] = {}
    for row in reference:
        end = gold_closed(row["마감/접수"])
        if end is not None:
            prefix = "g2b-" if row["출처"] == "나라장터" else "bizinfo-"
            closed[prefix + row["공고번호/ID"]] = f"{end:%Y-%m-%d %H:%M} 마감"
    for row in bizinfo_rows:
        end = gold_closed(row["접수"])
        if end is not None:
            closed["bizinfo-" + row["ID"].strip()] = f"{end:%Y-%m-%d %H:%M} 마감"
    return closed


def main() -> int:
    parser = argparse.ArgumentParser(description="기준 답안 40건과 앱을 대조한다 (0921 §4-F-1)")
    parser.add_argument(
        "--today",
        metavar="YYYY-MM-DD[THH:MM]",
        help="이 시각을 「지금」으로 본다 (기준 답안의 마감이 지났는지 가리는 데만 쓴다). "
             "앱의 시계는 앞당길 수 없으므로 **스크립트 쪽 판정만** 바뀐다. "
             "날짜만 주면 그 날 00:00 KST 다.",
    )
    parser.add_argument("--json", action="store_true", help="결과를 JSON 한 덩어리로 출력")
    parser.add_argument(
        "--industry-scenario",
        action="store_true",
        help="시험 계정(org-test-alpha)에 업종 1468 을 넣어 몇 건이 바뀌는지 잰 뒤 되돌린다",
    )
    args = parser.parse_args()

    global NOW
    if args.today:
        raw = args.today.strip()
        NOW = datetime.fromisoformat(raw if "T" in raw else raw + "T00:00").replace(tzinfo=KST)

    if not CSV_PATH.exists():
        print(f"기준 답안 CSV 가 없습니다: {CSV_PATH}")
        return 2

    reference = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    #: 공고문 기준 답안(26행)도 여기서 읽는다 — 마감 행을 **판정 전에** 가려야 한다.
    bizinfo_rows = (
        list(csv.DictReader(BIZINFO_CSV_PATH.open(encoding="utf-8-sig")))
        if BIZINFO_CSV_PATH.exists()
        else []
    )
    closed = closed_gold_rows(reference, bizinfo_rows)
    listing = fetch(
        f"/api/business-opportunities?organization_id={ORG}&evidence_scope=internal"
        "&source=all&days=30&include_closed=true&include_blocked=true&include_low=true"
    )
    items = {item["id"]: item for item in listing["items"]}

    checks: list[Check] = []
    for row in reference:
        is_g2b = row["출처"] == "나라장터"
        key = ("g2b-" if is_g2b else "bizinfo-") + row["공고번호/ID"]
        check = Check(key=key, title=row["공고명"].strip()[:46])
        checks.append(check)

        item = items.get(key)
        if item is None and data_missing(key):
            check.cannot("존재", "있어야 함", MISSING_NOTE)
            continue
        check.add("존재", "있어야 함", "있음" if item else "없음", item is not None)
        if item is None:
            continue
        if key in closed:
            # 마감이 지난 행이다. **있는지만 보고 판정은 견주지 않는다** (ISSUE-132 · §4-B-1).
            check.cannot("판정·근거", "마감 전이어야 견줄 수 있음", f"{closed[key]} — 검사 못 함")
            continue

        expected_budget = money(row["예산(원)"])
        if expected_budget:
            check.add("예산", f"{expected_budget:,}", f"{item['budget']:,}" if item["budget"] else "없음",
                      item["budget"] == expected_budget)
        expected_deadline = day(row["마감/접수"])
        if expected_deadline and len(expected_deadline) == 10:
            check.add("마감", expected_deadline, day(item.get("deadline")), day(item.get("deadline")) == expected_deadline)

        limits = row["제한·대상(확인값)"]
        if is_g2b:
            rules = rules_of(key)
            # --- 실적 ---
            track = rules.get("ELIG-TRACK-RECORD")
            if "실적 없음" in limits and track:
                check.add("실적", "제한 없음 → 가능", _ko(track["status"]), track["status"] == "PASS")
            # --- 업종 ---
            #
            # **기준 답안이 실제로 확인한 것만 견준다.** CSV 의 「지역/업종 공고서」는
            # 「나라장터 상세 화면에 값이 없어 공고문을 열어야 한다」는 뜻이지 「제한이 있다」가
            # 아니다. 그 칸을 「확인 필요」로 읽으면, API 플래그(`indstrytyLmtYn`)로 이미
            # 아는 것까지 불일치로 세게 된다. 아무 말도 없는 칸도 「제한 없음」이 아니다.
            industry = rules.get("ELIG-INDUSTRY")
            named = any(w in limits for w in ("SW사업자", "자유업종")) or "(14" in limits or "(9999" in limits
            if industry and named:
                # 회사 등록 업종이 「미입력」이므로 정답은 「확인 필요」다 (0921 §4-F-1).
                check.add("업종", "확인 필요", _ko(industry["status"]), industry["status"] == "CHECK")
            # --- 업종 «코드» (0922 §4-E-1) ---
            #
            # 8차부터 면허제한을 하루 창으로 받아 **코드가 온다.** 기준 답안이 상세 화면에서
            # 읽은 코드와 같은지 견준다 — 이번 회차의 핵심이라 「확인 필요」만으로는 모자란다.
            wanted_codes = _codes_in(limits)
            if wanted_codes and industry:
                got = _codes_in(industry.get("source", ""))
                check.add(
                    "업종 코드",
                    " · ".join(wanted_codes),
                    " · ".join(got) or "(없음)",
                    set(wanted_codes) <= set(got),
                )
            elif "공고서" in limits and industry:
                # CSV 의 「업종 공고서」는 「화면에 값이 없어 공고문을 열어야 한다」였다.
                # 8차 목표는 **그것까지 코드로 확정**하는 것이다 — 코드가 왔거나(제한 있음),
                # 행이 없어 「제한 없음」으로 확정됐거나 둘 중 하나여야 한다.
                resolved = industry["status"] in ("PASS", "CHECK") and "미수집" not in industry.get("source", "")
                check.add(
                    "업종 공고서 → 코드 확정",
                    "확정",
                    industry.get("source", "")[:48] or "(근거 없음)",
                    resolved,
                )
            # --- 지역 ---
            region = rules.get("ELIG-REGION")
            if region:
                if "지역 해당없음" in limits:
                    check.add("지역", "제한 없음 → 가능", _ko(region["status"]), region["status"] == "PASS")
                elif "지역 투찰제한 있음" in limits:
                    check.add("지역", "제한 있음 → 확인 필요·불가", _ko(region["status"]), region["status"] in ("CHECK", "FAIL"))
                    # 8차부터 **대상 지역 이름**이 온다 (0922 §4-E-1). 값이 실제로 실려야 한다.
                    check.add(
                        "지역 값",
                        "대상 지역 이름",
                        region.get("source", "")[:40] or "(근거 없음)",
                        "참가가능지역" in region.get("source", "") and "(없음)" not in region.get("source", ""),
                    )
            # --- 공동수급 ---
            award = (item.get("award_line") or "")
            if "공동수급 불허" in limits:
                check.add("공동수급", "불허", award or "(없음)", "불허" in award)
            elif "공동이행 허용" in limits or "공동이행(수기) 허용" in limits:
                check.add("공동수급", "허용", award or "(없음)", "공동이행" in award)
        else:
            gate = item.get("eligibility_gate")
            if row["공고번호/ID"].strip() in CORRECTED_BY_ROUND10:
                # **10차 기준 답안이 8차 것을 정정했다.**
                #
                # 검수자가 공고문을 직접 읽고 「Multi AI Agent 점프업은 스마트제조혁신R&D
                # 완료과제 수행기관만 신청할 수 있어 불가」·「기업훈련 탄력운영제는 훈련기관
                # 제외라 불가」라고 고쳐 적었다(`bizinfo_candidates.md` §0·D3).
                # 옛 기준으로 재면 앱이 «맞게 고친 것»이 불일치로 나온다.
                check.add(
                    "판정",
                    f"불가 (10차 정정: {CORRECTED_BY_ROUND10[row['공고번호/ID'].strip()]})",
                    _ko(gate or ""),
                    gate == "FAIL",
                )
            else:
                check.add("판정", "불가가 아닐 것", _ko(gate or ""), gate != "FAIL")
            # CSV 의 「지역 …」 칸에 전남광주가 있으면 앱의 지역 태그에도 있어야 한다.
            if "전남광주" in limits:
                tags = item.get("region_tags") or []
                # 전국 대상 사업은 태그가 비어 있을 수 있다 — 그때는 지역으로 막히지만 않으면 된다.
                nationwide = limits.count(",") >= 5
                check.add(
                    "지역",
                    "전국 대상" if nationwide else "전남광주 포함",
                    ", ".join(tags) or "(태그 없음)",
                    nationwide or "전남광주" in tags,
                )
            # CSV 의 「대상 …」 칸이 인증·업력을 말하면 앱이 그것으로 판정했는지 본다.
            for word in ("사회적기업", "창업벤처"):
                if f"대상 {word}" in limits:
                    reason = (item.get("gate_reason") or "")
                    hit = word in reason or "창업" in reason
                    check.add(f"대상({word})", "회사 자료로 판정", reason[:40] or "(사유 없음)", hit or gate != "FAIL")

    gaps = fetch(f"/api/eligibility/gaps?organization_id={ORG}&evidence_scope=internal&days=30")
    extras = _extra_checks(reference, items, closed)
    checks.extend(extras)

    # --- 10차: 공고문 기준 답안 26행 (0924 §4-E-1) ---
    #
    # 순위는 **담당자가 실제로 보는 목록과 같은 조건**에서 읽는다 — 기본 목록이므로
    # 「불가」는 빠져 있고(그래서 C4 가 숨김으로 나온다), 마감된 것도 빠져 있다.
    # **자르지 않는다** (0925 §4-E-3). `limit=200` 이면 「가능」을 세는 분모가 200 이 되어
    # 201위 밖의 「가능」이 빠진다 — 실측으로 578건 중 19건이고 그중 여섯이 200 밖이다.
    shown_biz = fetch(
        f"/api/business-opportunities?organization_id={ORG}&evidence_scope=internal"
        "&source=bizinfo&days=30&sort=priority"
    )
    biz_ranks = {item["id"]: item["source_rank"] for item in shown_biz["items"]}
    checks.extend(bizinfo_checks(items, biz_ranks, closed))
    if bizinfo_rows:
        checks.extend(workbook_checks(bizinfo_rows, items))

    # --- 11차: 부정 답안 · 「가능」 건수 · 두 화면 대조 · 이번 주 자리 (0925 §4-E) ---
    #
    # 기준 답안(「무엇이 맞는가」)만으로는 ISSUE-096 을 잡을 수 없었다. 10차는 조항을 못
    # 찾은 공고를 전부 「가능」이라 했고, 그것은 기준 답안 26건 어디에도 어긋나지 않았다.
    # **틀린 답이 다시 나오지 않는지**를 여기서 잰다.
    week = week_rows(items)
    checks.extend(negative_checks(items, biz_ranks, week, closed))
    checks.extend(pass_count_checks(shown_biz))
    checks.extend(week_place_checks(week))
    checks.extend(
        two_screen_checks(
            [r["ID"].strip() for r in bizinfo_rows] + list(BIZINFO_NEGATIVE),
            items,
            closed,
        )
    )
    # --- 19차: 공고문 참가자격 조항 (prompt_09 §4-D) ---
    checks.extend(qual_doc_checks(reference))
    checks.extend(g2b_two_screen_checks(reference, items, closed))
    scenario = industry_scenario(reference) if args.industry_scenario else None
    if scenario is not None:
        checks.append(scenario["qual_doc"])

    if args.json:
        print(json.dumps(
            {
                "checks": [{"key": c.key, "title": c.title, "rows": c.rows} for c in checks],
                "gaps": gaps,
            },
            ensure_ascii=False,
            indent=1,
        ))
    else:
        _print_report(checks, gaps, reference, closed)
        if scenario is not None:
            _print_scenario(scenario)

    bad = sum(len(c.mismatches) for c in checks)
    return 1 if bad else 0


_CODE_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _codes_in(text: str) -> list[str]:
    """글에서 업종 코드(네 자리)를 뽑는다. 연도(2026 등)는 걸러낸다."""
    out: list[str] = []
    for code in _CODE_RE.findall(text or ""):
        if code.startswith("20"):  # 2026 · 2025 … 는 연도다
            continue
        if code not in out:
            out.append(code)
    return out


#: 기준 답안이 **골랐다가 뺀 것** — 나라장터 개발형 상위 20 밖이어야 한다 (0922 §3-14).
EXCLUDED_FROM_TOP = {
    "R26BK01730343": "강원대 3.8억",
    "R26BK01732564": "울산항 PoC 2.4억",
    "R26BK01718476": "콜롬비아 3.1억",
    "R26BK01731699": "AI/SW 융합페어 대행",
    "R26BK01726683": "SBS 방송 제작",
    "R26BK01718581": "연수시설 임차",
    "R26BK01715589": "위탁 감리",
    "R26BK01734751": "개인정보 영향평가",
}
#: 검수자 1~3순위 — 나라장터 개발형 상위 5 안이어야 한다.
WANTED_TOP = {
    "R26BK01731641": "A1 한양사이버대 AI 챗봇",
    "R26BK01728112": "A2 한남대 RAG",
    "R26BK01734476": "A3 KISTI 군 장병 AI 교육",
}
#: 검수자가 「관련 낮음」으로 본 기업마당 사업 (제목 조각).
UNRELATED_TITLES = ("SEOUL FOOD", "무기체계 부품국산화", "모두의 창업")

#: 기업마당 실호출 캐시. 「목록에 없음」이 **앱 탓인지 자료 탓인지** 가르는 데 쓴다.
BIZINFO_CACHE_PATH = ROOT / "data" / "private" / "cache" / "bizinfo" / "bizinfo_cache.json"


#: 나라장터 공고 저장본. 「목록에 없음」이 앱 탓인지 자료 탓인지 가른다(28차). 33차부터 살아 있는 저장본은 Git 밖이고
#: 추적 파일은 기준본이다 — 서버와 같은 규칙(살아 있는 것이 있으면 그것)으로 읽는다.
G2B_LIVE_CACHE_PATH = ROOT / "data" / "private" / "cache" / "g2b" / "g2b_cache.json"
G2B_BASELINE_CACHE_PATH = ROOT / "data" / "public" / "sample_procurements" / "g2b_cache.json"


def _g2b_cache_path() -> Path:
    """서버 `procurement_service.cache_read_path` 와 같은 규칙 — 살아 있는 저장본을 **읽을 수 있을 때만** 그것(35차 R34-S3)."""
    try:
        payload = json.loads(G2B_LIVE_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return G2B_BASELINE_CACHE_PATH
    return G2B_LIVE_CACHE_PATH if isinstance(payload, dict) and isinstance(payload.get("notices"), list) else G2B_BASELINE_CACHE_PATH


G2B_CACHE_PATH = _g2b_cache_path()


def cached_g2b_numbers() -> set[str] | None:
    """캐시에 담긴 나라장터 공고번호(차수 뺀 앞자리). 캐시를 못 읽으면 None (판단을 보류한다)."""
    try:
        payload = json.loads(G2B_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    notices = payload.get("notices") if isinstance(payload, dict) else None
    if not isinstance(notices, list):
        return None
    return {
        str((row.get("notice") or {}).get("notice_no", "")).split("-")[0]
        for row in notices
        if isinstance(row, dict)
    }


def cached_bizinfo_ids() -> set[str] | None:
    """캐시에 담긴 기업마당 사업 id(PBLN_…). 캐시를 못 읽으면 None."""
    try:
        payload = json.loads(BIZINFO_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return None
    return {str(item.get("pblancId", "")) for item in items if isinstance(item, dict)}


_CACHE_IDS: dict[str, set[str] | None] = {}


def data_missing(key: str) -> bool:
    """기준 답안 공고가 **지금 캐시(자료)에 없는가** — 앱 탓이 아니라 자료 탓이라 「검사 못 함」(28차 · 9-29 캐시 교체).

    캐시를 못 읽으면 거짓(판단 보류 — 예전처럼 견준다). 캐시에 있는데 앱 목록 · 순위에 없으면 여전히 실패다.
    """
    if key.startswith("g2b-"):
        if "g2b" not in _CACHE_IDS:
            _CACHE_IDS["g2b"] = cached_g2b_numbers()
        known = _CACHE_IDS["g2b"]
        return known is not None and key.removeprefix("g2b-").split("-")[0] not in known
    if key.startswith("bizinfo-"):
        if "bizinfo" not in _CACHE_IDS:
            _CACHE_IDS["bizinfo"] = cached_bizinfo_ids()
        known = _CACHE_IDS["bizinfo"]
        return known is not None and key.removeprefix("bizinfo-") not in known
    return False


def _cache_day() -> str:
    """지금 읽는 나라장터 저장본을 받은 날(KST) — 「자료에 없음」 문구에 쓴다(33차 · 날짜를 손으로 적지 않는다)."""
    try:
        raw = json.loads(G2B_CACHE_PATH.read_text(encoding="utf-8")).get("fetched_at")
        return datetime.fromisoformat(str(raw)).astimezone(KST).strftime("%m-%d")
    except (OSError, ValueError, TypeError, AttributeError):
        return "날짜 모름"


MISSING_NOTE = f"자료에 없음 — 지금 저장본({_cache_day()} 받음)에 이 공고가 없다 · 검사 못 함"


def cached_bizinfo_titles() -> list[str] | None:
    """캐시에 담긴 기업마당 사업 제목. 캐시를 못 읽으면 None (판단을 보류한다)."""
    try:
        payload = json.loads(BIZINFO_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return None
    return [str(item.get("pblancNm", "")) for item in items if isinstance(item, dict)]

#: **10차 기준 답안이 8차 것을 정정한 건** (0924 · `bizinfo_candidates.md`).
#:
#: 8차 기준 답안(요약문만 보고 만든 것)은 이 둘을 후보로 올렸다. 공고문을 직접 읽은 검수자가
#: 「불가」로 고쳤다. 옛 기준으로 재면 앱이 «맞게 고친 것»이 불일치로 나온다.
CORRECTED_BY_ROUND10: dict[str, str] = {
    "PBLN_000000000125978": "스마트제조혁신R&D 완료과제 수행기관만 신청 가능",
    "PBLN_000000000116853": "교육·훈련을 주 사업으로 하는 훈련기관은 제외",
}

# --------------------------------------------------------------------------
# 10차 — 기업마당 공고문 기준 답안 26행 (0924 §4-E-1)
# --------------------------------------------------------------------------

#: CSV 「판정」 → 앱이 내야 하는 값. 「낮음」·「부적합」은 **순위로 잰다**(아래 설명 참고).
BIZINFO_VERDICTS: dict[str, str] = {
    "가능": "가능",
    "가능(과제 확인)": "가능",
    "확인 필요": "확인 필요",
    "낮음(확인)": "확인 필요",
    "간접(공급기업)": "간접",
    "간접(기술기업)": "간접",
    "불가": "불가",
    "불가(영업 근거)": "불가",
    "낮음": "순위로 잰다",
    "부적합": "순위로 잰다",
}

#: 검수자가 「근거(공고문)」에 인용한 **핵심 조항 조각**.
#:
#: CSV 의 근거 열은 사람이 읽기 좋게 줄인 글이라 그대로는 못 견준다. 그 안에서
#: **공고문에 그대로 있는 조각**만 뽑아 둔다 — 앱의 `clause_quotes`(원문 인용)에
#: 이 글자가 들어 있어야 「같은 근거를 봤다」고 할 수 있다.
#: 공고문이 이미지라 못 읽은 두 건(122497 · 120215)은 여기 없다.
BIZINFO_CLAUSES: dict[str, tuple[str, ...]] = {
    "PBLN_000000000123852": ("광주광역시 본사소재",),
    "PBLN_000000000126574": ("전라남도에 소재",),
    "PBLN_000000000125345": ("사회적기업",),
    "PBLN_000000000126368": ("전라남도내에 본사",),
    "PBLN_000000000126473": ("비영리법인",),
    "PBLN_000000000125426": ("10인 이상",),
    "PBLN_000000000126482": ("창업 7년 이내",),
    "PBLN_000000000125978": ("완료판정",),
    "PBLN_000000000116853": ("훈련기관",),
    "PBLN_000000000119201": ("기업부설연구소",),
    "PBLN_000000000117371": ("유치기업",),
    "PBLN_000000000121614": ("광주광역시 소재",),
    "PBLN_000000000126347": ("광양시 소재",),
    "PBLN_000000000120097": ("데이터",),
    "PBLN_000000000120083": ("데이터",),
}

#: 검수자 1~3순위 — 기업마당 **상위 10 안**이어야 한다 (0924 §4-B-2 · 검수자 결정 10-11 「상위 5 → 10」 — 덜 깎기 뒤 125426 6위).
BIZINFO_WANTED_TOP: dict[str, str] = {
    "PBLN_000000000123852": "A1 디지털 품질관리 테스팅",
    "PBLN_000000000123682": "A2 ICT 정보보호",
    "PBLN_000000000125426": "A3 미래내일 인턴형",
}

#: 검수자가 E(부적합) 그룹으로 뺀 여덟 건 — **상위 30 밖**이어야 한다.
BIZINFO_OUT_OF_TOP = {
    "PBLN_000000000117371": "E1 인공지능 유치기업",
    "PBLN_000000000120215": "E2 산업·일자리전환",
    "PBLN_000000000122609": "E3 경북AI데이터센터",
    "PBLN_000000000126538": "E4 스마트공장 주관기관",
    "PBLN_000000000126049": "E5 명품강소기업",
    "PBLN_000000000120275": "E6 K-Global",
    "PBLN_000000000126542": "E7 창업-BuS",
    "PBLN_000000000119201": "E8 연구인력 양성",
}

#: 검수자가 「불가」로 판정해 목록에서 **숨겨져야** 하는 것.
BIZINFO_HIDDEN = {"PBLN_000000000125978": "C4 Multi AI Agent 점프업"}

#: **부정 답안** — 10차가 「가능」이라고 한 여덟 건 (0925 §4-A-7 · 재검증 §3 표).
#:
#: 기준 답안(「무엇이 맞는가」)만으로는 이 회귀를 잡을 수 없었다. 10차는 조항을 못 찾은
#: 공고를 전부 「가능」으로 냈고, 그 60건 중 44건에 회사 사실과 맞은 요건이 하나도 없었다.
#: **틀린 답이 다시 나오지 않는지**를 재는 것이 여기다.
#:
#: 값은 (이름, 「가능」이 금지인가) 다. 넷은 「불가」여도 맞고 넷은 「확인 필요」 이상이어야
#: 한다 — 어느 쪽이든 **「가능」은 아니다**가 공통 조건이므로 그것만 못박는다.
BIZINFO_NEGATIVE: dict[str, str] = {
    "PBLN_000000000118350": "장애인 창업 컨설팅 (제외 절의 「비영리사회적기업」을 요건으로 읽었다)",
    "PBLN_000000000126159": "정보보호 인증제품 벤처나라 추천 (인증제품 보유는 회사 쪽 미입력)",
    "PBLN_000000000120566": "지식재산 경영인증 (수수료·보증한도를 받는 것으로 읽었다)",
    "PBLN_000000000124697": "소상공인 현장 맞춤형 컨설팅 (상시근로자 수 미입력)",
    "PBLN_000000000117367": "강진군 밀키트 장비 (선정업소·업종 제한)",
    "PBLN_000000000117368": "강진군 밀키트 포장재 (선정업소·업종 제한)",
    "PBLN_000000000126458": "공예 온라인 유통·AI 교육프로그램 (교육생 모집 — 개인 대상)",
    "PBLN_000000000126331": "AI 융합 에스테틱 의료기기 (전국 소재 의료기기 개발 기업)",
}

#: 120566 의 「회사에 뜻하는 것」에 있어서는 **안 되는** 말 (0925 §4-E-1).
#: 33만원은 회사가 내는 신청수수료, 10억원은 SGI 서울보증의 보증한도다.
MONEY_MUST_NOT = ("무료", "10억")

#: 30일 기업마당 목록의 「가능」 상한 (0925 §4-E-3). 10차는 60건이었다.
PASS_LIMIT = 20

#: 엑셀 워크북에 있어야 하는 시트.
WORKBOOK_SHEETS = ("사업기회", "나라장터", "기업마당", "이번 주 할 일", "갭 리포트", "자격 판정 근거", "브리핑")

_MONEY_RE = re.compile(r"(\d[\d,]*)\s*(억|천만|백만|만)?\s*원|(\d{1,3})\s*%")


def _money_tokens(text: str) -> list[str]:
    """「받는 것」·「부담」에서 **금액·비율 조각**만 뽑는다. 없으면 빈 목록이다."""
    out: list[str] = []
    for match in _MONEY_RE.finditer(text or ""):
        if match.group(3):
            token = f"{match.group(3)}%"
        else:
            token = f"{match.group(1)}{match.group(2) or ''}"
        if token not in out:
            out.append(token)
    return out


def _verdict_of(item: dict[str, Any]) -> str:
    """화면·엑셀과 **같은 말**로 읽는다 (규칙 11)."""
    if item.get("participation"):
        return "간접"
    return {"PASS": "가능", "CHECK": "확인 필요", "FAIL": "불가"}.get(item.get("eligibility_gate") or "", "미확인")


def bizinfo_checks(
    items: dict[str, Any], ranks: dict[str, int], closed: dict[str, str]
) -> list[Check]:
    """공고문 기준 답안 26행 대조 (0924 §4-E-1)."""
    if not BIZINFO_CSV_PATH.exists():
        check = Check(key="bizinfo-csv", title="공고문 기준 답안 CSV")
        check.add("파일", "있어야 함", f"없음: {BIZINFO_CSV_PATH.name}", False)
        return [check]

    rows = list(csv.DictReader(BIZINFO_CSV_PATH.open(encoding="utf-8-sig")))
    out: list[Check] = []
    for row in rows:
        program_id = row["ID"].strip()
        key = f"bizinfo-{program_id}"
        check = Check(key=key, title=f"{row['그룹'][0]}{row['순']} {row['사업명'].strip()[:40]}")
        out.append(check)

        item = items.get(key)
        if item is None and data_missing(key):
            check.cannot("존재", "있어야 함", MISSING_NOTE)
            continue
        check.add("존재", "있어야 함", "있음" if item else "없음", item is not None)
        if item is None:
            continue
        if key in closed:
            check.cannot("판정·근거", "마감 전이어야 견줄 수 있음", f"{closed[key]} — 검사 못 함")
            continue

        expected = BIZINFO_VERDICTS.get(row["판정"].strip(), "확인 필요")
        actual = _verdict_of(item)
        if expected == "순위로 잰다":
            # 「낮음」·「부적합」은 자격이 아니라 우선순위 판단이다 — 아래 순위 검사가 잰다.
            check.add("판정", "순위로 잽니다 (자격 판정 아님)", actual, True)
        elif expected == "불가" and "추정" in row["회사 대조"]:
            # 검수자 자신이 「추정」이라고 적었다. 앱이 그보다 더 확신하면 근거 없는 판정이다.
            check.add("판정", "불가 또는 확인 필요 (기준 답안이 「추정」)", actual, actual in ("불가", "확인 필요"))
        else:
            check.add("판정", expected, actual, actual == expected)

        quotes = " ".join(item.get("clause_quotes") or [])
        wanted = BIZINFO_CLAUSES.get(program_id)
        if wanted:
            hit = [w for w in wanted if w in quotes]
            check.add(
                "근거(공고문)",
                " · ".join(wanted),
                (quotes[:60] or "(인용 없음)"),
                len(hit) == len(wanted),
            )
        elif not item.get("document_read"):
            check.add("공고문", "이미지 — 요약문 기준", item.get("document_note") or "(사유 없음)",
                      bool(item.get("document_note")))

        wanted_money = _money_tokens(f"{row['받는 것']} {row['부담']}")
        if wanted_money and item.get("document_read"):
            evidence = " ".join(
                [item.get("company_meaning") or "", *(item.get("clause_quotes") or [])]
            ).replace(" ", "")
            hit = [token for token in wanted_money if token.replace(" ", "") in evidence]
            check.add(
                "받는 것(금액·비율)",
                " · ".join(wanted_money[:4]),
                " · ".join(hit[:4]) or "(맞는 값 없음)",
                bool(hit),
            )

    # **순위는 마감 전 목록에서만 뜻이 있다** (§4-B-2). 마감된 행을 조용히
    # 「대상 없음 → 통과」로 만들면, 시연 전에 검사가 사라진 것을 아무도 모른다.
    check = Check(key="bizinfo-rank-top", title="검수자 1~3순위가 기업마당 상위 10 안")
    for program_id, label in BIZINFO_WANTED_TOP.items():
        gone = closed.get(f"bizinfo-{program_id}")
        if gone:
            check.cannot(label, "상위 10 안", f"{gone} — 검사 못 함")
            continue
        rank = ranks.get(f"bizinfo-{program_id}")
        check.add(label, "상위 10 안", f"{rank}위" if rank else "목록에 없음", rank is not None and rank <= 10)
    out.append(check)

    check = Check(key="bizinfo-rank-out", title="E 그룹 여덟 건이 상위 30 밖")
    for program_id, label in BIZINFO_OUT_OF_TOP.items():
        gone = closed.get(f"bizinfo-{program_id}")
        if gone:
            check.cannot(label, "상위 30 밖", f"{gone} — 검사 못 함")
            continue
        rank = ranks.get(f"bizinfo-{program_id}")
        check.add(label, "상위 30 밖", f"{rank}위" if rank else "목록에 없음(불가로 숨김)", rank is None or rank > 30)
    out.append(check)

    check = Check(key="bizinfo-hidden", title="불가는 기본 목록에서 숨긴다")
    for program_id, label in BIZINFO_HIDDEN.items():
        gone = closed.get(f"bizinfo-{program_id}")
        if gone:
            check.cannot(label, "숨김", f"{gone} — 검사 못 함")
            continue
        rank = ranks.get(f"bizinfo-{program_id}")
        check.add(label, "숨김", f"{rank}위" if rank else "숨김", rank is None)
    out.append(check)
    return out


def workbook_bytes() -> bytes | None:
    """엑셀을 한 번만 내려받아 여러 검사가 함께 쓴다 (1,700건 워크북은 만드는 데 오래 걸린다)."""
    global _WORKBOOK_CACHE
    if _WORKBOOK_CACHE is not None:
        return _WORKBOOK_CACHE or None
    url = (
        f"/api/business-opportunities/export?organization_id={ORG}&evidence_scope=internal"
        "&format=xlsx&days=30&include_closed=true&include_blocked=true&save=false"
    )
    try:
        with urllib.request.urlopen(f"{BACKEND}{url}", timeout=300) as response:
            _WORKBOOK_CACHE = response.read()
    except Exception:  # noqa: BLE001
        _WORKBOOK_CACHE = b""
    return _WORKBOOK_CACHE or None


_WORKBOOK_CACHE: bytes | None = None


def week_rows(items: dict[str, Any]) -> list[dict[str, Any]]:
    """엑셀 「이번 주 할 일」 시트에 실린 것 (0925 §4-E-4).

    규칙(`opportunity_workbook.this_week`)을 여기서 세 번째로 베끼지 않는다 — 엑셀이
    그 규칙으로 고른 결과를 읽고, 사업명으로 목록의 항목과 이어 붙인다. 시트에 ID 열이
    없는 것은 사람이 읽는 파일이기 때문이고, 그것을 고치려고 화면 파일을 바꾸지 않는다.
    """
    body = workbook_bytes()
    if body is None:
        return []
    try:
        from openpyxl import load_workbook
    except ImportError:
        return []
    sheet = load_workbook(io.BytesIO(body))["이번 주 할 일"]
    header = [cell.value for cell in sheet[1]]
    try:
        source_col, title_col, verdict_col = (header.index(n) for n in ("출처", "사업명", "판정"))
    except ValueError:
        return []
    by_title = {i["title"]: i for i in items.values()}
    out: list[dict[str, Any]] = []
    for row in sheet.iter_rows(min_row=2):
        title = row[title_col].value
        if not title:
            continue
        item = by_title.get(str(title), {})
        out.append(
            {
                "id": item.get("id", ""),
                # 시트의 출처는 「기업마당 지원사업」·「나라장터 입찰」이다.
                "source_type": "bizinfo" if str(row[source_col].value).startswith("기업마당") else "g2b",
                "title": str(title),
                "sheet_verdict": str(row[verdict_col].value or ""),
                "participation": item.get("participation"),
                "check_side": item.get("check_side"),
                "eligibility_gate": item.get("eligibility_gate"),
            }
        )
    return out


def two_screen_checks(
    ids: list[str], items: dict[str, Any], closed: dict[str, str]
) -> list[Check]:
    """**목록과 신청 분석이 같은 답을 내는가** (0925 §4-E-2 · ISSUE-097).

    10차에는 A1 이 목록에서 「85점 · 가능」, 신청 분석에서 「57점 · 확인 필요」였다.
    담당자가 목록을 보고 들어가면 다른 답을 만났다. 점수·판정·「회사에 뜻하는 것」 셋을
    **글자까지** 견준다.
    """
    check = Check(key="two-screen", title="목록 ↔ 신청 분석 — 점수·판정·회사에 뜻하는 것")
    for program_id in ids:
        item = items.get(f"bizinfo-{program_id}")
        if item is None:
            continue
        gone = closed.get(f"bizinfo-{program_id}")
        if gone:
            # 마감 뒤에는 두 화면이 「마감」으로 같아진다 — 같다는 것이 아무 뜻이 없다.
            check.cannot(program_id, "목록 = 상세", f"{gone} — 검사 못 함")
            continue
        try:
            detail = fetch(
                f"/api/support-programs/bizinfo-{program_id}"
                f"?organization_id={ORG}&evidence_scope=internal"
            )
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            if data_missing(f"bizinfo-{program_id}"):
                check.cannot(program_id, "열림", MISSING_NOTE)
                continue
            check.add(program_id, "열림", f"실패: {exc}", False)
            continue
        name = (item.get("title") or program_id)[:20]
        pairs = (
            ("점수", item.get("company_priority_score"), detail.get("company_priority_score")),
            ("판정", _verdict_of(item), _verdict_of(detail)),
            ("뜻하는 것", item.get("company_meaning"), detail.get("company_meaning")),
        )
        for label, listed, shown in pairs:
            check.add(
                f"{name} {label}",
                f"목록 「{listed}」",
                f"상세 「{shown}」",
                listed == shown,
            )
    return [check]


QUAL_CLAUSE_DIR = ROOT / "data" / "public" / "sample_procurements" / "qualification_clauses"


def _qual_payload(notice_id: str) -> dict[str, Any] | None:
    path = QUAL_CLAUSE_DIR / f"{notice_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _industry_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in results if r["rule_id"] == "ELIG-INDUSTRY" or r["rule_id"].startswith("QUAL-INDUSTRY")]


def _unlock_text(row: dict[str, Any]) -> str:
    return " ".join(row.get("unlock_options") or [row.get("unlock_condition") or ""])


def _wants_industry(limits: str) -> bool:
    """기준 답안이 업종을 **이름으로** 적은 행 — 「SW사업자(1468)」·「(1426/…)」·「기타자유업종(9999)」."""
    return any(w in limits for w in ("SW사업자", "자유업종")) or "(14" in limits or "(9999" in limits


def _consortium_reading(results: list[dict[str, Any]], award: str) -> str:
    """앱이 **공고문 조항까지 보고** 공동수급을 어떻게 읽었나.

    조항과 필드가 어긋나면 `QUAL-CONSORTIUM-<조항>` 줄이 「공고문은 공동수급 …인데」라고 적는다(원문이
    우선). 맞으면 그 줄은 「… 공고 필드 「…」와 같습니다」다(20차부터 조항은 제 줄을 갖는다).
    """
    rows = [r for r in results if r["rule_id"].startswith("QUAL-CONSORTIUM")]
    clash = next((r for r in rows if "공고문은 공동수급" in r["reason"]), None)
    if clash:
        return clash["reason"].split("인데")[0].replace("공고문은 공동수급 ", "공고문 ")
    field = "불허" if "불허" in award else ("공동이행 허용" if "공동이행" in award else award or "(없음)")
    same = any("와 같습니다" in r["reason"] for r in rows)
    return f"{field} (공고문 조항 일치)" if same else f"{field} (공고문에 조항 없음 · 필드)"


def qual_doc_checks(reference: list[dict[str, str]]) -> list[Check]:
    """**공고문을 열어야 확인되던 것을 앱이 여는가** (19차 §4-D).

    마감 지난 행도 잰다 — 파일이 있는지·조항이 나오는지는 마감과 무관하다(§4-D 머리).
    """
    check = Check(key="qual-doc", title="공고문 참가자격 조항 ↔ 기준 답안 「제한(확인값)」 (나라장터 24행)")
    for row in reference:
        if row["출처"] != "나라장터":
            continue
        notice_id = "g2b-" + row["공고번호/ID"]
        tag = row["공고번호/ID"][:13]
        limits = row["제한·대상(확인값)"]
        payload = _qual_payload(notice_id)
        status = (payload or {}).get("status")
        if payload is None or status in ("not_fetched", "error"):
            why = (payload or {}).get("note") or "조항 파일 없음"
            check.add(f"{tag} 조항 파일", "있음 · ok", f"{status or '없음'} — {why}"[:60], False)
            continue
        if status in ("image", "no_section"):
            check.cannot(f"{tag} 조항 파일", "ok", f"{status} — {(payload.get('note') or '')}"[:70])
            continue
        clauses = payload.get("clauses") or []
        second = (payload.get("second_source") or {}).get("clauses") or []
        check.add(f"{tag} 조항 파일", "있음 · ok", f"ok · 공고문 조항 {len(clauses)}개" + (f" + 제안요청서 {len(second)}개" if second else ""), True)
        try:
            report = fetch(f"/api/eligibility/{notice_id}?organization_id={ORG}&evidence_scope=internal")
        except Exception as exc:  # noqa: BLE001
            if data_missing(notice_id if notice_id.startswith("g2b-") else f"g2b-{notice_id}"):
                check.cannot(f"{tag} 판정", "열림", MISSING_NOTE)
                continue
            check.add(f"{tag} 판정", "열림", f"실패: {exc}", False)
            continue
        results = report.get("results", [])

        # 2) 업종 — 코드가 오고, 채울 쪽이 회사이며, 열리는 조건에 그 코드가 있다.
        if _wants_industry(limits):
            codes = _codes_in(limits) or ["소프트웨어사업자"]
            rows = _industry_rows(results)
            seen = " ".join(r.get("source", "") for r in rows)
            hit = [
                r for r in rows
                if r["status"] == "CHECK" and r.get("check_side") == "company"
                and all(c in _unlock_text(r) for c in codes)
            ]
            got = hit[0] if hit else (rows[0] if rows else None)
            check.add(
                f"{tag} 업종",
                f"{'/'.join(codes)} · 확인 필요(회사 쪽) · 열리는 조건에 코드",
                (f"{got['rule_id']} {_ko(got['status'])}({got.get('check_side') or '-'}) · {_unlock_text(got)[:48]}" if got else "(업종 줄 없음)"),
                bool(hit) and all(c in seen for c in codes),
            )

        # 3) 지역/업종 공고서 — 공고문에서 지역·업종 조항이 나왔나.
        if "공고서" in limits and ("지역" in limits or "업종" in limits):
            found = [c for c in clauses if c.get("kind") in ("region", "industry")]
            if found:
                summary = " · ".join(f"{c['id']} {'지역' if c['kind'] == 'region' else '업종'} {c['text'][:24]}" for c in found[:2])
                check.add(f"{tag} 지역/업종 공고서", "공고문에서 지역·업종 조항", summary, True)
            else:
                # 절을 다 읽었는데 지역·업종 조항이 없다. 앱의 잘못이라고도, 맞았다고도 할 수 없다 —
                # 기준 답안의 「공고서」는 「열어 봐야 안다」였지 제한이 있다는 말이 아니다. 통과로 세지 않는다.
                check.cannot(
                    f"{tag} 지역/업종 공고서",
                    "공고문에서 지역·업종 조항",
                    f"공고문 참가자격 절 조항 {len(clauses)}개에 지역·업종 조항 없음 — 기준 답안은 제한 유무를 적지 않음",
                )

        # 4) 공동수급 — 공고문 조항까지 본 읽기.
        wanted = "불허" if "공동수급 불허" in limits else ("허용" if "공동이행" in limits else None)
        # 공고 필드(공동수급 방식 · 실적 제한)는 캐시의 공고 원본에서 온다 — 캐시에서 빠진 공고는 견줄 필드가 없다(28차).
        fields_gone = data_missing(notice_id)
        if wanted and fields_gone:
            check.cannot(f"{tag} 공동수급", wanted, MISSING_NOTE)
        elif wanted:
            reading = _consortium_reading(results, _award_of(results))
            check.add(f"{tag} 공동수급", wanted, reading, ("불허" in reading) == (wanted == "불허"))

        # 5) 실적 없음 — 필드는 가능 그대로, 실적 조항은 실적 목록 대조와 함께(31차 §3-D 「원장」 → 「실적 목록」).
        if "실적 없음" in limits:
            track = next((r for r in results if r["rule_id"] == "ELIG-TRACK-RECORD"), None)
            if fields_gone and track is None:
                check.cannot(f"{tag} 실적(필드)", "가능", MISSING_NOTE)
            else:
                check.add(f"{tag} 실적(필드)", "가능", _ko(track["status"]) if track else "(줄 없음)", bool(track) and track["status"] == "PASS")
            for qual in (r for r in results if r["rule_id"].startswith("QUAL-TRACK")):
                check.add(
                    f"{tag} 실적 조항 ↔ 실적 목록",
                    "실적 목록 대조 결과가 줄에 적힘",
                    qual["reason"].split(" — ", 1)[-1][:60],
                    "실적 목록에" in qual["reason"],  # 32차 — 「실적 목록에 비슷한 일 N건」
                )
    return [check]


def _award_of(results: list[dict[str, Any]]) -> str:
    """계약·낙찰 방식 줄의 이유 문장 — 목록의 `award_line` 과 같은 글이다."""
    return next((r["reason"] for r in results if r["rule_id"] == "ELIG-AWARD"), "")


def g2b_two_screen_checks(
    reference: list[dict[str, str]], items: dict[str, Any], closed: dict[str, str]
) -> list[Check]:
    """**나라장터도** 목록과 상세가 같은 종합을 내는가 (19차 §4-D).

    목록 배지(`eligibility_gate`)와 참가 가능 여부 화면(`/api/eligibility/{id}` 종합)을 견준다.
    참가자격 조항은 줄 수가 아니라 **조항 id 집합**으로 견준다(20차 §4-B) — 목록 `clause_ids` 와
    상세 줄의 `clause_id`.
    마감 뒤에는 목록이 「마감」으로 불가를 달고 상세는 규칙표만 보므로 뜻이 없다 — 기업마당 두 화면과
    같은 규칙으로 [못 잼]이다.
    """
    check = Check(key="two-screen-g2b", title="나라장터 목록 ↔ 참가 가능 여부 — 종합 판정")
    for row in reference:
        if row["출처"] != "나라장터":
            continue
        notice_id = "g2b-" + row["공고번호/ID"]
        item = items.get(notice_id)
        if item is None:
            continue
        tag = row["공고번호/ID"][:13]
        if notice_id in closed:
            check.cannot(tag, "목록 = 상세", f"{closed[notice_id]} — 검사 못 함")
            continue
        try:
            detail = fetch(f"/api/eligibility/{notice_id}?organization_id={ORG}&evidence_scope=internal")
        except Exception as exc:  # noqa: BLE001
            check.add(tag, "열림", f"실패: {exc}", False)
            continue
        listed, shown = item.get("eligibility_gate") or "", detail.get("verdict") or ""
        check.add(tag, f"목록 「{_ko(listed)}」", f"상세 「{_ko(shown)}」", listed == shown)
        in_list = set(item.get("clause_ids") or [])
        in_detail = {r["clause_id"] for r in detail.get("results", []) if r.get("clause_id")}
        check.add(
            f"{tag} 조항 id", f"목록 {len(in_list)}개", f"상세 {len(in_detail)}개"
            + ("" if in_list == in_detail else f" · 다름 {sorted(in_list ^ in_detail)[:4]}"),
            in_list == in_detail,
        )
    return [check]


def negative_checks(
    items: dict[str, Any],
    ranks: dict[str, int],
    week: list[dict[str, Any]],
    closed: dict[str, str],
) -> list[Check]:
    """**부정 답안** 여덟 건 (0925 §4-E-1).

    셋을 잰다: 판정이 「가능」이 아니다 · 기업마당 상위 30 밖이다 ·
    「이번 주 할 일」에 없다. 하나라도 어기면 ISSUE-096 이 되살아난 것이다.
    """
    out: list[Check] = []
    check = Check(key="negative-verdict", title="10차가 「가능」이라 한 여덟 건 — 이제 「가능」이 아니다")
    week_ids = {w["id"] for w in week}
    for plain, name in BIZINFO_NEGATIVE.items():
        gone = closed.get(f"bizinfo-{plain}")
        if gone:
            check.cannot(name, "「가능」 아님", f"{gone} — 검사 못 함")
            continue
        item = items.get(f"bizinfo-{plain}")
        if item is None:
            # 목록에서 빠졌으면 「가능」일 수 없다 — 숨겨졌거나 마감이다.
            check.add(name, "「가능」 아님", "목록에 없음(숨김·마감)", True)
            continue
        verdict = _verdict_of(item)
        check.add(name, "「가능」 아님", verdict, verdict != "가능")
    out.append(check)

    check = Check(key="negative-rank", title="부정 답안 여덟 건 — 기업마당 상위 30 밖")
    for plain, name in BIZINFO_NEGATIVE.items():
        gone = closed.get(f"bizinfo-{plain}")
        if gone:
            check.cannot(name, "상위 30 밖", f"{gone} — 검사 못 함")
            continue
        rank = ranks.get(f"bizinfo-{plain}")
        check.add(
            name,
            "상위 30 밖",
            "목록에 없음" if rank is None else f"{rank}위",
            rank is None or rank > 30,
        )
    out.append(check)

    check = Check(key="negative-week", title="부정 답안 여덟 건 — 「이번 주 할 일」에 없다")
    for plain, name in BIZINFO_NEGATIVE.items():
        gone = closed.get(f"bizinfo-{plain}")
        if gone:
            check.cannot(name, "없음", f"{gone} — 검사 못 함")
            continue
        in_week = f"bizinfo-{plain}" in week_ids
        check.add(name, "없음", "있음" if in_week else "없음", not in_week)
    out.append(check)

    check = Check(key="negative-money", title="120566 「회사에 뜻하는 것」 — 무료·10억이 없다")
    item = items.get("bizinfo-PBLN_000000000120566")
    meaning = (item or {}).get("company_meaning") or ""
    for word in MONEY_MUST_NOT:
        check.add(f"「{word}」", "없음", f"있음 — 「{meaning}」" if word in meaning else "없음", word not in meaning)
    out.append(check)
    return out


def pass_count_checks(shown: dict[str, Any]) -> list[Check]:
    """「가능」 건수와 **그 사유에 회사 사실이 이름으로 적혀 있는가** (0925 §4-E-3)."""
    passes = [
        i
        for i in shown["items"]
        if i["source_type"] == "bizinfo" and i.get("eligibility_gate") == "PASS" and not i.get("participation")
    ]
    check = Check(key="pass-count", title="30일 기업마당 목록의 「가능」")
    check.add(f"{PASS_LIMIT}건 이하", f"≤{PASS_LIMIT}건", f"{len(passes)}건", len(passes) <= PASS_LIMIT)

    # 10차의 「가능」 60건 중 49건이 이 문장 하나로 가능이었다.
    NO_LIMIT = "소재를 제한하는 문장을 찾지 못했다"
    only_nationwide = [
        i for i in passes if NO_LIMIT in (i.get("gate_reason") or "") or NO_LIMIT in (i.get("fit_line") or "")
    ]
    check.add(
        "「전국 대상으로 본다」만으로 가능",
        "0건",
        f"{len(only_nationwide)}건"
        + (f" — {only_nationwide[0]['title'][:24]}…" if only_nationwide else ""),
        not only_nationwide,
    )

    # 사유에 회사 사실이 **이름으로** 적혀 있어야 한다.
    FACT_WORDS = ("사회적기업", "광주", "전남", "설립", "년차", "사업영역", "ICT", "인증", "보유")
    nameless = [
        i
        for i in passes
        if not any(w in f"{i.get('gate_reason') or ''} {i.get('fit_line') or ''}" for w in FACT_WORDS)
    ]
    check.add(
        "사유에 회사 사실이 이름으로",
        "전부",
        f"{len(passes) - len(nameless)}/{len(passes)}건"
        + (f" — 빠진 것: {nameless[0]['title'][:24]}…" if nameless else ""),
        not nameless,
    )
    return [check]


def week_place_checks(week: list[dict[str, Any]]) -> list[Check]:
    """「이번 주 할 일」 지원사업 자리 — 가능 또는 **공고 쪽** 확인 필요만 (0925 §4-E-4)."""
    check = Check(key="week-place", title="「이번 주 할 일」 지원사업 자리")
    support = [w for w in week if w["source_type"] == "bizinfo"]
    check.add("지원사업 건수", "1건 이상", f"{len(support)}건", bool(support))
    wrong = [
        w
        for w in support
        if w.get("participation") or w.get("check_side") == "company"
    ]
    check.add(
        "회사 쪽 확인 필요·간접",
        "0건",
        f"{len(wrong)}건" + (f" — {wrong[0]['title'][:24]}…" if wrong else ""),
        not wrong,
    )
    for w in support:
        verdict = _verdict_of(w)
        check.add(
            f"{w['title'][:22]}",
            "가능 또는 확인 필요(공고 쪽)",
            f"{verdict} · {w.get('check_side') or '해당 없음'}",
            verdict in ("가능", "확인 필요") and w.get("check_side") != "company",
        )
    return [check]


def workbook_checks(rows: list[dict[str, str]], items: dict[str, Any]) -> list[Check]:
    """엑셀 워크북 대조 (0924 §4-C-4 · §4-E-1)."""
    check = Check(key="workbook", title="엑셀 워크북 — 시트 일곱과 같은 판정")
    try:
        from openpyxl import load_workbook
    except ImportError:
        check.add("openpyxl", "설치되어 있어야 함", "없음", False)
        return [check]

    body = workbook_bytes()
    if body is None:
        check.add("내려받기", "성공", "실패", False)
        return [check]

    book = load_workbook(io.BytesIO(body))
    check.add("시트", " · ".join(WORKBOOK_SHEETS), " · ".join(book.sheetnames), tuple(book.sheetnames) == WORKBOOK_SHEETS)

    sheet = book["기업마당"]
    header = [cell.value for cell in sheet[1]]
    id_column = header.index("ID")
    verdict_column = header.index("판정")
    in_sheet = {
        str(row[id_column].value): str(row[verdict_column].value)
        for row in sheet.iter_rows(min_row=2)
        if row[id_column].value
    }
    gone = [r["ID"].strip() for r in rows if data_missing("bizinfo-" + r["ID"].strip())]
    missing = [r["ID"] for r in rows if r["ID"].strip() not in in_sheet and r["ID"].strip() not in gone]
    check.add(f"기준 답안 26건(캐시에 없는 {len(gone)}건 제외)", "엑셀 시트에 전부", f"빠진 것 {len(missing)}건" + (f" — {missing[0]}" if missing else ""), not missing)

    mismatched: list[str] = []
    for row in rows:
        program_id = row["ID"].strip()
        item = items.get(f"bizinfo-{program_id}")
        if item is None or program_id not in in_sheet:
            continue
        # 엑셀은 「간접(공급기업)」처럼 자리 이름까지 적는다. 같은 판정인지만 본다.
        sheet_verdict = "간접" if in_sheet[program_id].startswith("간접") else in_sheet[program_id]
        if sheet_verdict != _verdict_of(item):
            mismatched.append(f"{program_id} 엑셀 {in_sheet[program_id]} ≠ 화면 {_verdict_of(item)}")
    check.add("판정이 화면과 같다", "전부 같음", f"{len(mismatched)}건 다름" + (f" — {mismatched[0]}" if mismatched else ""), not mismatched)
    return [check]


def _extra_checks(
    reference: list[dict[str, str]], items: dict[str, Any], closed: dict[str, str]
) -> list[Check]:
    """8차에서 더한 검사들 (0922 §4-E-1)."""
    out: list[Check] = []

    # --- 1468 → +9 : 기준 답안 A그룹 개발 공고 중 1468 을 요구하는 건수 ---
    #
    # 「+9」는 검수자가 **자기가 고른 개발 공고 15건 안에서** 센 값이다
    # (`apply_candidates.md` §0). 앱 전체 후보에서 센 값이 아니다 — 앱은 훨씬 더 찾는다.
    dev_rows = [r for r in reference if r["그룹"].startswith("A")]
    need_1468 = 0
    for row in dev_rows:
        rules = rules_of("g2b-" + row["공고번호/ID"])
        industry = rules.get("ELIG-INDUSTRY")
        if industry and "1468" in _codes_in(industry.get("source", "")):
            need_1468 += 1
    check = Check(key="gap-1468", title="소프트웨어사업자(1468) 등록 시 열리는 개발 공고")
    gone_dev = [r for r in dev_rows if data_missing("g2b-" + r["공고번호/ID"])]
    if gone_dev:
        # 기준 답안 「9건」은 개발 공고 15건이 모두 있을 때의 값이다 — 일부가 캐시에서 빠지면 견줄 수 없다.
        check.cannot("1468 요구 건수", "9건 (기준 답안 §0)", f"기준 개발 공고 {len(dev_rows)}건 중 {len(gone_dev)}건이 지금 캐시에 없음 · 남은 것 중 {need_1468}건 — 검사 못 함")
    else:
        check.add("1468 요구 건수", "9건 (기준 답안 §0)", f"{need_1468}건", need_1468 == 9)
    out.append(check)

    # --- 순위: 나라장터 개발형 (담당자가 실제로 보는 목록과 같은 조건) ---
    shown = fetch(
        f"/api/business-opportunities?organization_id={ORG}&evidence_scope=internal"
        "&source=g2b&days=30&sort=priority&limit=200"
    )
    dev = [
        item
        for item in shown["items"]
        if "development" in (item.get("work_tracks") or []) and not item["closed"]
    ]
    position = {item["id"].split("-")[1]: index for index, item in enumerate(dev, start=1)}

    # **풀은 날마다 줄어든다** (ISSUE-135). 고정 캐시(9-17 수집)에서 마감이 빠지므로
    # 기준 답안을 만든 9-20 의 40건 남짓이 9-22 오후 23건이 됐다. 그래서 절대 순위
    # (「상위 20」)는 날짜에 매인다 — 풀 크기를 머리말에 적고, 순위는 **상대 순서**로 잰다.
    global DEV_POOL
    pool = [item for item in dev if not _app_closed(item)]
    DEV_POOL = len(pool)

    # **A1~A3 은 9-28 에 마감된다** (§4-B-2). 그때 이 검사가 조용히 초록이 되면,
    # 시연 전에 「1~3순위가 상위 5 안」을 아무도 재지 않게 된 것을 모른다.
    # 풀이 5건 이하면 「상위 5 안」은 누구에게나 참이다 — 그것도 잴 수 없는 것으로 적는다.
    check = Check(key="rank-top", title="검수자 1~3순위가 개발형 상위 5 안")
    in_cache = cached_g2b_numbers()
    for no, label in WANTED_TOP.items():
        # 캐시(자료)에 없으면 앱이 순위에 올릴 수 없다 — 자료 탓이라 「검사 못 함」.
        # 캐시에 있는데 순위에 없으면 아래에서 그대로 실패한다(UNRELATED_TITLES 와 같은 규칙).
        if in_cache is not None and no not in in_cache:
            check.cannot(label, "상위 5 안", MISSING_NOTE)
            continue
        gone = next((v for k, v in closed.items() if k.startswith(f"g2b-{no}")), None)
        if gone:
            check.cannot(label, "상위 5 안", f"{gone} — 검사 못 함")
            continue
        if DEV_POOL <= 5:
            check.cannot(label, "상위 5 안", f"개발형 마감 전 {DEV_POOL}건 — 상위 5 가 뜻이 없어 검사 못 함")
            continue
        # 입찰 마감 전이어도 참가자격 등록 마감이 지나면 앱이 「불가」로 숨긴다 — 앱이 맞다 (ISSUE-142).
        blocked = _deadline_block(next((v for k, v in items.items() if k.startswith(f"g2b-{no}")), None))
        if blocked:
            check.cannot(label, "상위 5 안", f"{blocked} 지남(앱 「불가」로 숨김) — 검사 못 함")
            continue
        rank = position.get(no)
        check.add(label, "상위 5 안", f"{rank}위" if rank else "목록에 없음", rank is not None and rank <= 5)
    out.append(check)

    # **골랐다가 뺀 것은 고른 것보다 아래여야 한다** (ISSUE-135 · 18차 §4-A).
    #
    # 예전 규칙은 「상위 20 밖」이었다. 풀이 23건이면 20 밖 자리가 셋뿐이라 여덟 건이
    # 들어갈 수 없다 — 9-22 07:40 강원대 20위 → 오후 강원대 18위 · 울산항 19위로 붉어졌다.
    # 앱은 맞았다: 둘 다 마감 전 A 행(1·2·3·4·5·6·9·14위)보다 **전부 아래**였다.
    # 그 뜻을 그대로 잰다 — 풀이 줄어도 상대 순서는 남는다.
    open_a = {
        row["공고번호/ID"].split("-")[0]: row["공고명"].strip()[:14].strip()
        for row in reference
        if row["출처"] == "나라장터"
        and row["그룹"].startswith("A")
        and f"g2b-{row['공고번호/ID']}" not in closed
    }
    a_ranks = {no: position[no] for no in open_a if no in position}
    lowest_a = max(a_ranks.values()) if a_ranks else None
    lowest_name = open_a[max(a_ranks, key=a_ranks.get)] if a_ranks else ""
    check = Check(key="rank-out", title="골랐다가 뺀 것이 마감 전 A 행 전부보다 아래")
    for no, label in EXCLUDED_FROM_TOP.items():
        item = next((v for k, v in items.items() if k.startswith(f"g2b-{no}")), None)
        if item is not None and _app_closed(item):
            # 뺀 행이 마감됐으면 목록에서 빠진다. 그것을 「목록에 없음 → 통과」로 세면
            # 조용히 초록이 된다 — 예전 루프가 그랬다.
            check.cannot(label, "A 행보다 아래", f"{_deadline_text(item)} 마감 — 검사 못 함")
            continue
        if lowest_a is None:
            check.cannot(label, "A 행보다 아래", "견줄 A 행이 전부 마감 — 검사 못 함")
            continue
        rank = position.get(no)
        expected = f"{lowest_a}위({lowest_name}) 아래"
        check.add(
            label,
            expected,
            f"{rank}위" if rank else "목록에 없음(숨김·갈래 밖)",
            rank is None or rank > lowest_a,
        )
    out.append(check)

    # --- 점수 분포: 두 값에 몰리지 않는다 ---
    scores = [i["company_priority_score"] for i in dev[:30] if i["company_priority_score"] is not None]
    check = Check(key="score-spread", title="점수가 두 값에 몰리지 않는다")
    unique = len(set(scores))
    # 기준은 「상위 30건에 고유 점수 8개」 — 풀이 날마다 줄어 30건이 안 되면 같은 비율(8/30)로 맞춘다
    # (ISSUE-142 · 9-28 개발형 마감 전 9건). 5건 미만이면 분포가 뜻이 없어 검사 못 함(18차 rank-out 과 같은 방식).
    if len(scores) < 5:
        check.cannot("상위 30건 고유 점수", "8개 이상", f"점수 있는 개발형 {len(scores)}건 — 분포가 뜻이 없어 검사 못 함")
    else:
        need = 8 if len(scores) >= 30 else max(3, -(-len(scores) * 8 // 30))
        expected = "8개 이상" if len(scores) >= 30 else f"{need}개 이상 (풀 {len(scores)}건 — 30건 기준 8개를 비례로)"
        check.add("상위 30건 고유 점수", expected, f"{unique}개 {sorted(set(scores), reverse=True)}", unique >= need)
    out.append(check)

    # --- 마감 무관 (0922 §4-B-0) ---
    check = Check(key="deadline-free", title="마감은 점수에 들어가지 않는다")
    with_schedule = [i["id"] for i in shown["items"] if any(c["key"] == "schedule" for c in i["score_components"])]
    check.add("score_components 에 schedule", "없어야 함", f"{len(with_schedule)}건", not with_schedule)
    # 성분이 같은데 점수가 다르면 마감이 숨어 들어간 것이다.
    by_components: dict[tuple, set[int]] = {}
    for item in shown["items"]:
        if item["company_priority_score"] is None:
            continue
        key = tuple(sorted((c["key"], c["score"]) for c in item["score_components"]))
        by_components.setdefault(key, set()).add(item["company_priority_score"])
    split = [k for k, values in by_components.items() if len(values) > 1]
    check.add("성분이 같으면 점수도 같다", "갈리지 않음", f"{len(split)}묶음이 갈림", not split)
    out.append(check)

    # --- 기업마당 관련성 (0922 §4-C-2) ---
    check = Check(key="bizinfo-related", title="검수자가 고른 지원사업 16건은 전부 「관련」")
    biz_rows = [
        r
        for r in reference
        if r["출처"] != "나라장터" and ("bizinfo-" + r["공고번호/ID"]) not in closed
    ]
    unrelated = [
        (r["공고명"][:30], items["bizinfo-" + r["공고번호/ID"]].get("relevance_note"))
        for r in biz_rows
        if items.get("bizinfo-" + r["공고번호/ID"])
        and items["bizinfo-" + r["공고번호/ID"]].get("relevance_note")
    ]
    check.add(
        "관련 낮음으로 접힌 건",
        "0건",
        f"{len(unrelated)}건" + (f" — {unrelated[0][0]}…" if unrelated else ""),
        not unrelated,
    )
    out.append(check)

    check = Check(key="bizinfo-unrelated", title="검수자가 「관련 낮음」이라 한 셋")
    # 「관련 낮음」은 «앱이 접었는가»를 재는 검사다. 그런데 기업마당 캐시는 실호출마다
    # 내용이 바뀌고(1,578 → 1,620건), 그 사이 사라진 사업은 앱이 접을 기회조차 없다.
    # 자료에 없는 것을 앱의 실패로 세면 캐시가 바뀔 때마다 이 검사가 붉어진다
    # (11차·12차 모두 SEOUL FOOD 가 그랬다 — 재검증 §3-1). 캐시에도 없으면 사유를
    # 적고 넘어간다. 캐시에는 있는데 목록에만 없으면 그건 앱의 문제이므로 그대로 실패다.
    cached_titles = cached_bizinfo_titles()
    for needle in UNRELATED_TITLES:
        hits = [i for i in items.values() if i["source_type"] == "bizinfo" and needle in i["title"]]
        if not hits:
            in_cache = None if cached_titles is None else any(needle in t for t in cached_titles)
            if in_cache is False:
                check.add(needle, "관련 낮음", "캐시에 없음 — 접을 대상이 없다", True)
            else:
                check.add(needle, "관련 낮음", "목록에 없음", False)
            continue
        folded = [i for i in hits if i.get("relevance_note")]
        check.add(
            needle,
            "관련 낮음",
            (folded[0]["relevance_note"] if folded else "관련 있음으로 남음"),
            bool(folded),
        )
    out.append(check)
    return out


#: 8차에서 더한 검사의 열쇠. 보고서가 값을 그대로 옮길 수 있게 맞아도 출력한다.
_EXTRA_KEYS = frozenset(
    {
        "gap-1468", "rank-top", "rank-out", "score-spread", "deadline-free",
        "bizinfo-related", "bizinfo-unrelated",
        # 11차 (0925 §4-E)
        "negative-verdict", "negative-rank", "negative-week", "negative-money",
        "pass-count", "week-place", "two-screen",
        # 10차 (0924 §4-E-1)
        "bizinfo-rank-top", "bizinfo-rank-out", "bizinfo-hidden", "workbook",
        # 19차 (prompt_09 §4-D)
        "qual-doc", "two-screen-g2b", "qual-doc-1468",
    }
)

TEST_ORG = "org-test-alpha"


def _put(path: str, body: dict[str, Any]) -> Any:
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{BACKEND}{path}", data=data, method="PUT", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def _gate_counts(organization_id: str) -> dict[str, int]:
    listing = fetch(
        f"/api/business-opportunities?organization_id={organization_id}&evidence_scope=internal"
        "&source=g2b&days=30&include_closed=true&include_blocked=true&include_low=true"
    )
    counts: dict[str, int] = {}
    for item in listing["items"]:
        gate = item.get("eligibility_gate") or ""
        counts[gate] = counts.get(gate, 0) + 1
    return counts


def _industry_counts(organization_id: str) -> dict[str, int]:
    """업종 제한이 **실제로 있는** 공고들의 ELIG-INDUSTRY 판정 분포 (0922 §4-A-7).

    종합 게이트는 사업 규모·사업자등록번호 때문에 그대로 「확인 필요」다. 업종을 넣었을 때
    실제로 무엇이 바뀌는지는 **그 항목 하나**를 세야 보인다.
    """
    listing = fetch(
        f"/api/business-opportunities?organization_id={organization_id}&evidence_scope=internal"
        "&source=g2b&days=30&include_closed=true&include_blocked=true&include_low=true&limit=200"
    )
    counts: dict[str, int] = {}
    for item in listing["items"]:
        report = fetch(
            f"/api/eligibility/{item['id']}?organization_id={organization_id}&evidence_scope=internal"
        )
        rule = next((r for r in report.get("results", []) if r["rule_id"] == "ELIG-INDUSTRY"), None)
        # 제한 행이 **실제로 있는** 공고만 센다. 「면허제한 (없음)」은 원래 가능이라 세면 「116 → 128」처럼
        # 전보다 많아진다(19차 — 상세 메모가 회사 사실을 따라가게 고친 뒤 드러났다).
        if rule is None or "면허제한" not in rule.get("source", "") or "면허제한 (없음)" in rule.get("source", ""):
            continue
        counts[rule["status"]] = counts.get(rule["status"], 0) + 1
    return counts


def _industry_1468_ids(reference: list[dict[str, str]]) -> list[str]:
    """1468 등록으로 풀려야 하는 기준 답안 행 — 1468 이 요구 목록에 있거나 「SW사업자(4종 중 하나)」."""
    out = []
    for row in reference:
        limits = row["제한·대상(확인값)"]
        if row["출처"] == "나라장터" and ("1468" in limits or "SW사업자(4종" in limits):
            out.append("g2b-" + row["공고번호/ID"])
    return out


def industry_scenario(reference: list[dict[str, str]]) -> dict[str, Any]:
    """**시험 계정**에 업종 1468 을 넣어 판정이 어떻게 바뀌는지 잰다 (0921 §4-F-1).

    쓰기는 `org-test-alpha` 에만 한다(0921 §3-2). 재고 나면 **반드시 되돌린다** —
    끝에서 원래 값을 그대로 다시 저장한다.
    """
    before_profile = fetch(f"/api/capability/profile?organization_id={TEST_ORG}&evidence_scope=internal")
    before = _gate_counts(TEST_ORG)
    before_industry = _industry_counts(TEST_ORG)
    after_industry: dict[str, int] = {}
    #: 19차 §4-D-2 — 회사가 등록 업종을 적으면 **조항 줄까지** 가능으로 바뀌어야 한다.
    qual_doc = Check(key="qual-doc-1468", title="시험 계정에 1468 을 적으면 — 기준 답안 1468 행의 업종 줄")

    payload = {
        key: before_profile.get(key)
        for key in (
            "developer_count", "team_note", "skills", "credentials", "budget_ceiling_krw",
            "concurrent_project_limit", "business_items", "location_region",
            "joint_bid_partner", "proposal_lead_days", "note",
        )
    }
    payload["proposal_lead_days"] = before_profile.get("proposal_lead_days") or 4
    payload["updated_by"] = "수용 스크립트"
    try:
        _put(
            f"/api/capability/profile?organization_id={TEST_ORG}&evidence_scope=internal",
            {**payload, "registered_industries": [{"code": "1468", "name": "소프트웨어사업자(컴퓨터관련서비스사업)"}]},
        )
        after = _gate_counts(TEST_ORG)
        after_industry = _industry_counts(TEST_ORG)
        for notice_id in _industry_1468_ids(reference):
            report = fetch(f"/api/eligibility/{notice_id}?organization_id={TEST_ORG}&evidence_scope=internal")
            for rule in _industry_rows(report.get("results", [])):
                qual_doc.add(f"{notice_id[4:17]} {rule['rule_id']}", "가능", _ko(rule["status"]), rule["status"] == "PASS")
    finally:
        # 되돌린다. 시험 값이 남으면 다음 사람이 그것을 회사 자료로 읽는다.
        _put(
            f"/api/capability/profile?organization_id={TEST_ORG}&evidence_scope=internal",
            {**payload, "registered_industries": before_profile.get("registered_industries") or []},
        )
    restored = fetch(f"/api/capability/profile?organization_id={TEST_ORG}&evidence_scope=internal")
    industry_delta = {
        "before_check": before_industry.get("CHECK", 0),
        "after_pass": after_industry.get("PASS", 0),
    }
    return {
        "before": before,
        "after": after,
        "industry": industry_delta,
        "restored": restored.get("registered_industries") == (before_profile.get("registered_industries") or []),
        "qual_doc": qual_doc,
    }


def _print_scenario(scenario: dict[str, Any]) -> None:
    print()
    print("== 업종 1468 을 넣으면 (시험 계정 org-test-alpha)")
    before, after = scenario["before"], scenario["after"]
    for gate in ("PASS", "CHECK", "FAIL"):
        b, a = before.get(gate, 0), after.get(gate, 0)
        mark = "" if b == a else f"  ← {a - b:+d}"
        print(f"  {_ko(gate):>6}  {b:>4} → {a:>4}{mark}")
    if before == after:
        print(INFO + "종합 판정은 그대로입니다 — 업종이 확정돼도 다른 「확인 필요」(사업 규모·")
        print("         사업자등록번호)가 남아 있기 때문입니다. 업종 항목 자체가 바뀌는 건수는")
        print("         아래 「업종 항목」 줄이 말합니다.")
    industry = scenario.get("industry")
    if industry:
        print(f"  업종 항목  확인 필요 {industry['before_check']}건 → 가능 {industry['after_pass']}건")
    print(("  [일치] " if scenario["restored"] else "  [다름] ") + "시험 값 되돌림" + ("" if scenario["restored"] else " 실패 — 손으로 확인하세요"))


def _ko(status: str) -> str:
    return {"PASS": "가능", "CHECK": "확인 필요", "FAIL": "불가", "": "판정 없음"}.get(status, status)


def _print_report(
    checks: list[Check],
    gaps: dict[str, Any],
    reference: list[dict[str, str]],
    closed: dict[str, str],
) -> None:
    print("기준 답안 대조 — docs/reports/2026-09-20_apply_candidates.csv")
    print(f"  기준 {len(reference)}건 (나라장터 {sum(1 for r in reference if r['출처'] == '나라장터')} ·"
          f" 기업마당 {sum(1 for r in reference if r['출처'] != '나라장터')})")
    print(f"  기준 시각 {NOW:%Y-%m-%d %H:%M} KST")
    if DEV_POOL is not None:
        print(f"  개발형 마감 전 {DEV_POOL}건 (순위 검사의 풀)")
    if closed:
        print(f"  마감 지나 제외 {len(closed)}행:")
        for key, when in sorted(closed.items()):
            print(f"      {key} — {when}")
    else:
        print("  마감 지나 제외 0행")
    print()

    missing = [c for c in checks if any(row[0] == "존재" and row[3] is False for row in c.rows)]
    print(f"== 존재 — {len(checks) - len(missing)}/{len(checks)}건")
    for check in missing:
        print(BAD + f"{check.key} {check.title}")
    if not missing:
        print(OK + "기준 답안 전부 앱 목록에 있습니다")

    print("\n== 항목별 판정")
    total = bad = 0
    unmeasured: list[str] = []
    for check in checks:
        for label, expected, actual, same in check.rows:
            if label == "존재":
                continue
            if same is None:
                # 잴 수 없는 것은 분모에서도 뺀다 — 안 그러면 「366/367」처럼 보인다.
                unmeasured.append(f"{check.key} · {label} — {actual}")
                continue
            total += 1
            if not same:
                bad += 1
                print(BAD + f"{check.key} · {label} — 기준 「{expected}」 vs 앱 「{actual}」")
                print(f"           {check.title}")
    print(f"  {total - bad}/{total} 일치" + ("" if bad else " — 불일치 없음"))
    if unmeasured:
        print(f"  검사 못 함 {len(unmeasured)}건 (마감 · 원문 사정 — 줄마다 사유):")
        for line in unmeasured:
            print(SKIP + line)

    # 8차에서 더한 검사는 **맞아도 값을 적는다** — 보고서가 그대로 옮길 수 있어야 한다.
    extras = [c for c in checks if c.key in _EXTRA_KEYS]
    if extras:
        print("\n== 8차 검사 (0922 §4-E-1)")
        for check in extras:
            print(f"  · {check.title}")
            for label, expected, actual, same in check.rows:
                mark = "못 잼" if same is None else ("일치" if same else "다름")
                print(f"      [{mark}] {label} — 기준 「{expected}」 · 앱 「{actual}」")

    print("\n== 갭 리포트 (무엇을 갖추면 몇 건이 열리는가)")
    print(f"  판정 {gaps['total']}건 · 지금 불가 {gaps['blocked_total']}건")
    for gap in gaps["gaps"]:
        print(f"  · {gap['condition']}")
        print(f"      불가가 풀림 {gap['blocked']}건 · 판정이 확정됨 {gap['pending']}건  [{gap['label']}]")
    named = [g for g in gaps["gaps"] if "1468" in g["condition"]]
    if named:
        print(OK + f"「1468 등록 시」 항목이 있습니다 — 불가 {named[0]['blocked']}건")
    else:
        print(INFO + "기준 답안의 「소프트웨어사업자(1468) 등록 시 +9건」은 이 이름으로 나오지 않습니다.")
        print("         나라장터 목록 API 에 요구 업종의 «이름»이 오지 않고(플래그 `indstrytyLmtYn` 뿐),")
        print("         면허제한 API 는 우리 용역 공고를 한 건도 주지 않았습니다 (0921 §4-A-3 실측).")
        print("         업종 이름을 지어내지 않고 「공고문에서 확인해 적으면 n건이 확정된다」로 말합니다.")

    tail = "불일치 없음 — 기준 답안과 같은 판정입니다." if not bad else f"불일치 {bad}건 — 위 목록을 보세요."
    if unmeasured:
        tail += f" (검사 못 함 {len(unmeasured)}건)"
    print(f"\n{tail}")


if __name__ == "__main__":
    sys.exit(main())
