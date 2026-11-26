"""사전규격 · 발주계획 저장본 (38차 §3-D · 담당자 결정 2 · data.go.kr 15129437 · 15129462).

## 무엇을 하나

- **받기**(매일 07:30 · `collect_daily.py`): 사전규격은 등록일 7일 창, 발주계획은 이번 달부터 석 달 창을 통째로 받아
  (한 페이지 999행 · 서비스마다 몇 번) **나라장터와 같은 수집 낱말**(`collect_keywords_service.all_keywords()` — 기본 + 추가)로 거른다.
  담당자 이름 · 전화는 가려서 저장한다. 캐시는 입찰공고와 따로 둔다(`data/private/cache/g2b_prespec` · `g2b_orderplan`).
- **선제준비 칸**(39차 결정 1): 사전규격은 **입찰 목록 밖**이다 — 사업기회 「선제준비」 탭 · 브리핑 🔵 칸에만 오른다
  (`opportunity_type="pre_spec"` · id `g2bpre-R26BD…` · `section`). 본업만 기본으로 보이고 나머지 · 의견 마감 지남은 접는다.
  판정은 「확인 필요 — 본공고 전」(「가능」 없음) · 공고 분석 · 제안서 단추 없음.
  **의견등록 마감은 「마감」이 아니라 「의견 마감」** 이다 — D-day · 마감 임박순 · 긴급 칸에 들지 않는다(실무 문서 오류 7).
- **본공고 잇기**: 사전규격 `bidNtceNoList` ↔ 본공고 `bfSpecRgstNo`. 본공고 행에는 「사전규격 n일 전 공개」, 사전규격 행은
  「본공고 나옴 →」(그 공고 분석 화면으로).
- **발주계획**은 「선제준비」 탭 아래 표 · 브리핑 「발주 예정(발주계획)」 표 · 엑셀 브리핑 시트에만 싣는다. 본공고가 이미 났으면
  (`ntceNticeYn=Y` · `bidNtceNoList`) 「본공고 나옴 →」 이고 「공고 전」이라 하지 않는다(PRESPEC-03).

필드는 2026-10-15 실제 응답으로 확인했다(`g2b_client` 주석 · CLAUDE.md §25-4). 제3자 명세는 길잡이로만 봤다.
"""

from __future__ import annotations

from types import SimpleNamespace

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core import storage
from app.core.paths import DATA_ROOT
from app.services import collect_keywords_service, g2b_client, g2b_mapper, home_agencies, opportunity_filter

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
PRESPEC_CACHE_FILE = DATA_ROOT / "private" / "cache" / "g2b_prespec" / "prespec_cache.json"
ORDERPLAN_CACHE_FILE = DATA_ROOT / "private" / "cache" / "g2b_orderplan" / "orderplan_cache.json"
#: 사전규격 받기 창(등록일) · 저장본에 남겨 두는 기간(등록일부터). 매일 받으면 창이 겹쳐 빠지는 날이 없다.
PRESPEC_DAYS = 7
PRESPEC_KEEP_DAYS = 30
#: 발주계획 받기 창(이번 달부터 몇 달).
ORDERPLAN_MONTHS = 3
#: 받은 양이 지난번의 이 비율 밑이면 「크게 줄었다」고 적는다(39차 §3-F-4 · 10-18 실행 8행 · 10-16 401행).
ORDERPLAN_DROP_RATIO = 0.2
#: 그 비교를 할 지난번 최소 행 수(적은 날끼리는 견주지 않는다).
ORDERPLAN_DROP_MIN = 50
ORDERPLAN_DROP_NOTE = "발주계획 받은 양이 크게 줄었습니다 — 지난 자료 그대로"
#: 저장하기 전에 가리는 칸 — 담당자 이름 · 전화 · 메일(공고문 속 연락처를 가리는 것과 같은 규칙).
MASK_FIELDS = ("ofclNm", "ofclTelNo", "telNo", "ofclEmail", "email")
ID_PREFIX = "g2bpre-"


def wanted(title: str | None) -> list[str]:
    """수집 낱말 중 `title` 에 걸리는 것 — 나라장터 공고명 검색과 같은 부분 일치(띄어쓰기 무시 · 짧은 영문은 경계).

    2.0.7 — 추가 낱말(이 서버 전체에 하나)도 본다 · 사전규격 · 발주계획 거르기와 실패 낱말 잇기가 함께 따라온다."""
    text = title or ""
    squashed = text.replace(" ", "")
    out: list[str] = []
    for keyword in opportunity_filter.COLLECT_KEYWORDS:
        if keyword in opportunity_filter._SHORT_ASCII:
            hit = opportunity_filter._contains(text, keyword)
        else:
            hit = keyword.replace(" ", "").lower() in squashed.lower()
        if hit:
            out.append(keyword)
    out.extend(w for w in collect_keywords_service.extra_words() if collect_keywords_service.matches(text, w))
    return out


def _mask(item: dict[str, Any]) -> dict[str, Any]:
    return {k: ("<가림>" if k in MASK_FIELDS and v else v) for k, v in item.items()}


def parse_dt(value: Any) -> datetime | None:
    """`2026-10-18 16:00:00` → KST 시각. 없거나 못 읽으면 None."""
    return g2b_mapper.parse_datetime(str(value or "").strip())


def _read(path) -> dict[str, Any]:
    try:
        payload = storage.read_json(path, default=None)
    except storage.CorruptJsonError:
        logger.warning("사전규격 · 발주계획 저장본을 읽지 못했습니다: %s", path.name)
        return {}
    return payload if isinstance(payload, dict) else {}


def load_prespecs() -> tuple[list[dict[str, Any]], datetime | None]:
    payload = _read(PRESPEC_CACHE_FILE)
    items = [i for i in payload.get("items") or [] if isinstance(i, dict) and i.get("bfSpecRgstNo")]
    return items, parse_dt(payload.get("fetched_at")) or _iso(payload.get("fetched_at"))


def load_order_plans() -> tuple[list[dict[str, Any]], datetime | None]:
    payload = _read(ORDERPLAN_CACHE_FILE)
    items = [i for i in payload.get("items") or [] if isinstance(i, dict) and i.get("bizNm")]
    return items, _iso(payload.get("fetched_at"))


def _iso(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


async def collect_prespecs(now: datetime | None = None) -> dict[str, Any]:
    """사전규격을 받아 수집 낱말로 거르고 저장본에 합친다. **바깥을 부른다** — 부르는 쪽이 고정 모드를 본다."""
    moment = now or storage.utc_now()
    outcome = await g2b_client.fetch_prespecs(days=PRESPEC_DAYS, now=moment)
    fresh = {str(i["bfSpecRgstNo"]): _mask(i) for i in outcome.items if i.get("bfSpecRgstNo") and wanted(i.get("prdctClsfcNoNm"))}
    previous, _ = load_prespecs()
    keep_from = moment - timedelta(days=PRESPEC_KEEP_DAYS)
    for item in previous:
        number = str(item["bfSpecRgstNo"])
        received = parse_dt(item.get("rcptDt"))
        if number not in fresh and received is not None and received >= keep_from:
            fresh[number] = item
    items = sorted(fresh.values(), key=lambda i: str(i.get("rcptDt") or ""), reverse=True)
    storage.write_json_atomic(PRESPEC_CACHE_FILE, {
        "_note": "나라장터 사전규격(용역) — 수집 낱말로 거른 것 · 담당자 이름 · 전화는 가림 · 서비스키 없음 (38차 §3-D)",
        "fetched_at": moment.isoformat(),
        "days": PRESPEC_DAYS,
        "keep_days": PRESPEC_KEEP_DAYS,
        "received": outcome.total,
        "calls": outcome.calls,
        "truncated": outcome.truncated,
        "items": items,
    })
    return {
        "출처": "사전규격",
        "결과": "g2b",
        "받아온_건수": outcome.total,
        "후보_건수": sum(1 for i in outcome.items if i.get("bfSpecRgstNo") and wanted(i.get("prdctClsfcNoNm"))),
        "저장_건수": len(items),
        "호출_횟수": outcome.calls,
        "수집_방식": f"등록일 {PRESPEC_DAYS}일 창 · 수집 낱말 {len(collect_keywords_service.all_keywords())}개로 거름" + (" · 덜 받음" if outcome.truncated else ""),
        "오류": None,
    }


def _plan_key(item: dict[str, Any]) -> str:
    return f"{item.get('orderPlanUntyNo') or item.get('bizNm')}-{item.get('orderPlanSno') or '0'}"


def _plan_month(item: dict[str, Any]) -> str:
    return f"{str(item.get('orderYear') or '0000')}{str(item.get('orderMnth') or '00').zfill(2)}"


async def collect_order_plans(now: datetime | None = None) -> dict[str, Any]:
    """발주계획을 받아 수집 낱말로 거르고 **지난 저장본과 합친다**. **바깥을 부른다.**

    39차 §3-F-4 — 저장 응답으로 보니 한 번 받으면 **최근 하루 이틀에 등록된** 계획만 온다(10-16 실행: 등록 10-15 · 16 뿐 401행 ·
    10-18 실행: 10-17 · 18 뿐 8행 · 둘 다 발주 10월만). 그런데 실행마다 저장본을 통째로 바꿔 10-16 의 28건이 10-18 에 2건이 됐다.
    그래서 사전규격처럼 합친다(같은 계획 번호는 새것이 이김 · 발주 달이 지난 것은 뺌). 받은 양이 지난번의 20% 밑이면 로그 · 화면에
    「발주계획 받은 양이 크게 줄었습니다 — 지난 자료 그대로」를 적는다(지난 행은 합치기로 그대로 남는다).
    """
    moment = now or storage.utc_now()
    outcome = await g2b_client.fetch_order_plans(months=ORDERPLAN_MONTHS, now=moment)
    fresh = {_plan_key(i): _mask(i) for i in outcome.items if i.get("bizNm") and wanted(i.get("bizNm"))}
    previous = _read(ORDERPLAN_CACHE_FILE)
    this_month = f"{moment.astimezone(KST):%Y%m}"
    merged = {_plan_key(i): i for i in previous.get("items") or [] if isinstance(i, dict) and i.get("bizNm") and _plan_month(i) >= this_month}
    merged.update(fresh)
    items = sorted(merged.values(), key=lambda i: (_plan_month(i), str(i.get("bizNm"))))
    before = previous.get("received")
    dropped = (
        isinstance(before, int) and before >= ORDERPLAN_DROP_MIN and outcome.total is not None
        and outcome.total < before * ORDERPLAN_DROP_RATIO
    )
    storage.write_json_atomic(ORDERPLAN_CACHE_FILE, {
        "_note": "나라장터 발주계획(용역) — 수집 낱말로 거른 것 · 실행마다 합침(39차) · 담당자 이름 · 전화는 가림 · 서비스키 없음 (38차 §3-D)",
        "fetched_at": moment.isoformat(),
        "months": ORDERPLAN_MONTHS,
        # 크게 줄었을 때는 견줄 기준(지난번 양)을 남긴다 — 줄어든 양이 다음 비교의 기준이 되지 않게
        "received": before if dropped else outcome.total,
        "received_last": outcome.total,
        "kept_note": ORDERPLAN_DROP_NOTE if dropped else None,
        "calls": outcome.calls,
        "truncated": outcome.truncated,
        "items": items,
    })
    return {
        "출처": "발주계획",
        "결과": "g2b",
        "받아온_건수": outcome.total,
        "후보_건수": len(fresh),
        "저장_건수": len(items),
        "호출_횟수": outcome.calls,
        "수집_방식": f"이번 달부터 {ORDERPLAN_MONTHS}달 · 수집 낱말로 거름 · 지난 저장본과 합침" + (" · 덜 받음" if outcome.truncated else ""),
        "경고": ORDERPLAN_DROP_NOTE if dropped else None,
        "오류": None,
    }


def order_plan_note() -> str | None:
    """마지막 받기에서 발주계획이 크게 줄었으면 그 글(화면 · 브리핑). 아니면 None."""
    note = _read(ORDERPLAN_CACHE_FILE).get("kept_note")
    return note if isinstance(note, str) and note else None


def spec_doc_url(item: dict[str, Any]) -> str | None:
    """공식 링크 — 사전규격은 상세 주소 칸이 없어 **규격서 파일**(g2b.go.kr)을 쓴다. 지어낸 주소는 쓰지 않는다."""
    for n in range(1, 6):
        url = str(item.get(f"specDocFileUrl{n}") or "").strip()
        if url.startswith("https://"):
            return url
    return None


def main_numbers(item: dict[str, Any]) -> list[str]:
    """사전규격이 가리키는 본공고 번호(차수 없음). 쉼표 · 공백으로 여럿일 수 있다."""
    raw = str(item.get("bidNtceNoList") or "")
    return [part.strip()[:13] for part in raw.replace(";", ",").split(",") if part.strip()]


#: 본공고 첨부 뒤에 붙이는 사전규격 규격서 이름 — 늘 같아야 받아 둔 파일(`attachment_service.cache_path`)을 다시 찾는다.
SPEC_DOC_NAME = "사전규격 규격서 {n}({no})"
_SPEC_DOC_RE = re.compile(r"사전규격 규격서 \d+\(")
#: 본공고 → 규격서 연결 기록 — 사전규격 저장본은 30일 뒤 정리되지만 본공고는 그 뒤에도 마감 전일 수 있다(11-03 검토).
#: 처음 붙일 때 남기고, 저장본에서 빠진 뒤에는 이 기록으로 붙인다.
SPEC_LINKS_FILE = PRESPEC_CACHE_FILE.parent / "spec_doc_links.json"


def is_spec_doc(name: Any) -> bool:
    """`SPEC_DOC_NAME` 꼴 문서 이름인가(압축 안 문서는 「압축 > 문서」의 앞 이름으로)."""
    return bool(_SPEC_DOC_RE.match(str(name or "").split(" > ")[0]))


def spec_docs_for(item: dict[str, Any] | None) -> list[dict[str, str]]:
    """본공고 원본 칸(`raw_data["item"]`) → 연결된 사전규격의 규격서 [{name, url}] (11-03).

    본공고 첨부가 공고서뿐이고 제안요청서는 사전규격에만 붙은 공고가 있다(g2b-R26BK01786460 · 사전규격 R26BD00285788) —
    공고서만 읽어 입찰 절차 조항이 제안서 본문이 됐다. 사전규격 번호(`bfSpecRgstNo`)로, 없으면 사전규격의 본공고 번호
    목록(`bidNtceNoList`)으로 찾는다. 저장본(최근 30일 · 수집 낱말)에 없으면 빈 목록 — 주소를 지어내지 않는다."""
    item = item or {}
    pre_no = str(item.get("bfSpecRgstNo") or "").strip()
    bid_no = str(item.get("bidNtceNo") or "").strip()[:13]
    if not pre_no and not bid_no:
        return []
    links = _read(SPEC_LINKS_FILE)
    prespecs, _ = load_prespecs()
    found = next((p for p in prespecs if pre_no and p.get("bfSpecRgstNo") == pre_no), None) or next(
        (p for p in prespecs if bid_no and bid_no in main_numbers(p)), None)
    if found is None:
        # 저장본에서 빠졌으면 처음 붙일 때 남긴 기록으로(주소를 지어내지 않는다 — 기록에 있던 주소 그대로)
        kept = links.get(bid_no) or links.get(pre_no) or []
        return [{"name": str(d.get("name")), "url": str(d.get("url"))} for d in kept
                if isinstance(d, dict) and str(d.get("url") or "").startswith("https://")]
    no = str(found.get("bfSpecRgstNo"))
    docs = []
    for n in range(1, 6):
        url = str(found.get(f"specDocFileUrl{n}") or "").strip()
        if url.startswith("https://"):
            docs.append({"name": SPEC_DOC_NAME.format(n=n, no=no), "url": url})
    keys = [k for k in (bid_no, pre_no) if k]
    if docs and any(links.get(k) != docs for k in keys):
        storage.write_json_atomic(SPEC_LINKS_FILE, {**links, **{k: docs for k in keys}})
    return docs


def received_at(item: dict[str, Any]) -> datetime | None:
    """공개(등록) 시각 — `rgstDt`, 없으면 `rcptDt`."""
    return parse_dt(item.get("rgstDt")) or parse_dt(item.get("rcptDt"))


def _main_pre_no(main: Any) -> str | None:
    """본공고(UnifiedOpportunity 의 원본 공고)가 가리키는 사전규격 번호 — 원본 `raw_data.item.bfSpecRgstNo`."""
    raw = getattr(main, "raw_data", None) or {}
    item = raw.get("item") if isinstance(raw, dict) else None
    value = str((item or {}).get("bfSpecRgstNo") or "").strip()
    return value or None


def opinion_text(moment: datetime | None) -> str:
    """마감 칸에 적는 글 — 의견등록 마감은 입찰 마감이 아니다(실무 문서 오류 7)."""
    if moment is None:
        return "사전규격 — 의견 마감일 없음 (입찰 마감 아님)"
    local = moment.astimezone(KST)
    return f"의견 마감 {local:%m/%d %H:%M} (입찰 마감 아님)"


#: 본공고가 의견 마감 뒤 며칠에 나왔나(43차 Q16 · 이어진 118건 실측 — +1일 47 · +2일 27 · +3일 14 · 중앙값 1일 · 13%는 그 전).
MAIN_AFTER_OPINION_DAYS: tuple[int, int] = (1, 3)


def prespec_plan(raw: dict[str, Any], opinion: datetime | None) -> str:
    """선제준비 행의 「본공고 예상 · 사업기간 · 할 일」(43차 M13 · Q16 · PREP-05)."""
    parts: list[str] = []
    if opinion is not None:
        start = (opinion + timedelta(days=MAIN_AFTER_OPINION_DAYS[0])).astimezone(KST)
        end = (opinion + timedelta(days=MAIN_AFTER_OPINION_DAYS[1])).astimezone(KST)
        parts.append(f"본공고 예상 {start:%m/%d}~{end:%m/%d}(실측: 의견 마감 뒤 1~3일 · 가끔 그 전)")
    days = str(raw.get("dlvrDaynum") or "").strip()
    until = parse_dt(raw.get("dlvrTmlmtDt"))
    if days.isdigit() and int(days) > 0:
        parts.append(f"사업기간 {int(days)}일")
    elif until is not None:
        parts.append(f"사업기간 ~{until.astimezone(KST):%Y-%m-%d}")
    parts.append("할 일: 규격서 읽기 → 자격 · 실적 미리 확인 → 의견 마감 전 의견 등록")
    return " · ".join(parts)


def build_items(
    *,
    notices: list[Any],
    organization_id: str,
    profile: Any,
    capacity: Any,
    now: datetime,
    main_items: list[Any],
) -> list[Any]:
    """사전규격 저장본 → 통합 목록 항목(나라장터 갈래 · `opportunity_type="pre_spec"`).

    `notices` 는 본공고의 원본(`ProcurementNotice`) — 사전규격 번호로 본공고를 잇는다. `main_items` 는 같은 본공고의
    통합 항목(같은 순서가 아니어도 된다 · id 로 잇는다). 본공고 행에는 「사전규격 n일 전 공개」를 단다.
    판정은 언제나 「확인 필요 — 본공고 전」이다(「가능」 없음) · 점수는 같은 공식에 사전규격 사업명 · 기관 · 배정예산만 넣는다.
    """
    from app.schemas.business_opportunity import NextRoute, UnifiedOpportunity
    from app.schemas.procurement import ProcurementNotice
    from app.services import opportunity_priority as priority
    from app.services import practical_priority as practical
    from app.services import work_kinds

    prespecs, _ = load_prespecs()
    if not prespecs:
        return []
    by_id = {getattr(m, "id", None): m for m in main_items}
    # 40차 PRESPEC-03 — 한 사전규격에 본공고가 여럿(원공고 + 재공고)이면 모두 잇는다(한 행에만 붙고 어느 행인지 순위로 갈렸다)
    main_of: dict[str, list[Any]] = {}
    for notice in notices:
        number = _main_pre_no(notice)
        if number:
            main_of.setdefault(number, []).append(notice)
    by_bid_no = {str(getattr(n, "notice_no", "") or "")[:13]: n for n in notices}
    # 43차 PREP-09 — 번호로 못 이은 사전규격도 같은 제목의 열린 입찰이 있으면 알린다(재발주 · 재공고일 수 있음)
    open_titles = {
        title_key(getattr(m, "title", "") or "")
        for m in main_items
        if getattr(m, "opportunity_type", "procurement") == "procurement" and not getattr(m, "closed", False)
    }
    # 43차 PREP-10 — 같은 기관 · 같은 제목의 사전규격 재등록(재공개)과 규격서 링크가 없을 때 같은 사업 발주계획의 공식 주소
    first_seen: dict[tuple[str, str], dict[str, Any]] = {}
    for other in sorted(prespecs, key=lambda r: (received_at(r) or now, str(r.get("bfSpecRgstNo")))):
        first_seen.setdefault((title_key(str(other.get("prdctClsfcNoNm") or "")), str(other.get("orderInsttNm") or "")), other)
    plan_urls: dict[str, str] = {}
    for plan in load_order_plans()[0]:
        url = str(plan.get("orderPlanDtlUrl") or "").strip()
        if url.startswith(G2B_HTTPS):
            plan_urls.setdefault(title_key(str(plan.get("bizNm") or "")), url)

    items: list[Any] = []
    for raw in prespecs:
        number = str(raw["bfSpecRgstNo"])
        title = str(raw.get("prdctClsfcNoNm") or "").strip() or f"사전규격 {number}"
        # 43차 M12 · PREP-01 — 조달청 대행이면 실수요기관을 앞에(「전남대학교 산학협력단(조달청 대행)」) · 광주 · 전남 판정도 실수요기관
        demand = str(raw.get("rlDminsttNm") or "").strip() or None
        agency = home_agencies.display_agency(str(raw.get("orderInsttNm") or demand or "").strip() or "기관 미상", demand)
        # 43차 M12 · PREP-02 — 사전규격에도 조달분류가 있다(세부품명 목록 · 28%) — 입찰과 같은 분류 · 유형 규칙(D19)을 타게 원본 칸에 둔다
        klass = next(iter(re.findall(r"\^\d{10}\^([^\]^]+)", str(raw.get("prdctDtlList") or ""))), None)
        published = received_at(raw)
        opinion = parse_dt(raw.get("opninRgstClseDt"))
        mains = main_of.get(number) or [by_bid_no[n] for n in main_numbers(raw) if n in by_bid_no]
        listed = [m for m in mains if getattr(m, "id", None) in by_id]
        open_listed = [m for m in listed if not getattr(by_id[m.id], "closed", False)]
        # 링크(「본공고 나옴 →」 · `main_notice_id`)는 마감 전이면서 공고번호가 가장 새것(재공고) — 없으면 목록에 있는 것 · 그 밖 새것
        main = max(open_listed or listed or mains, key=lambda m: str(getattr(m, "notice_no", "") or ""), default=None)
        # 43차 PREP-09 — 본공고 번호가 있는데 저장본에 없으면(마감돼 빠짐 · 받지 않은 공고) 「본공고 전」이 아니라 「본공고 나옴(나라장터에서 확인)」
        offlist_main = main is None and bool(main_numbers(raw))
        notes: list[str] = []
        if main is None and not offlist_main and title_key(title) in open_titles:
            notes.append("같은 제목 입찰 열려 있음 — 재발주 · 재공고 여부 확인")
        first = first_seen.get((title_key(title), str(raw.get("orderInsttNm") or "")))
        if first is not None and str(first.get("bfSpecRgstNo")) != number:
            before = g2b_mapper.parse_amount(str(first.get("asignBdgtAmt") or ""))
            after = g2b_mapper.parse_amount(str(raw.get("asignBdgtAmt") or ""))
            when = received_at(first)
            money = f" · 예산 {before / 1e8:.2f}억 → {after / 1e8:.2f}억" if before and after and before != after else ""
            # 같은 날 등록 · 예산이 크게 다른 쌍도 있다 — 단정하지 않고 「재공개일 수 있음」
            notes.append(f"재공개일 수 있음 — 같은 기관 · 같은 제목 사전규격 {when.astimezone(KST):%m/%d} 등록{money}" if when else "재공개일 수 있음")
        doc_url = spec_doc_url(raw) or plan_urls.get(title_key(title))
        notice = ProcurementNotice(
            id=f"{ID_PREFIX}{number}",
            notice_no=number,
            title=title,
            agency=agency,
            published_at=published or now,
            deadline_at=None,
            budget=g2b_mapper.parse_amount(str(raw.get("asignBdgtAmt") or "")),
            region=None,
            description=None,
            source_url=doc_url,
            raw_data={"procurement_class": klass, "demand_institution": demand} if klass or demand else {},
        )
        match = opportunity_filter.classify(notice)
        # 41차 CLASSIFY-R40-03 — 사전규격은 조달분류가 없다 — 공고명의 행사 · 전시 · 대행 꼴(교육 일 꼴 없음)은 본업이 아니다(사유와 함께 접음 · D15)
        event = opportunity_filter.event_title_of(title) if match.is_candidate else None
        work = work_kinds.of_notice(notice)
        components, reasons, checks, source_score = priority.score_procurement(
            notice,
            match,
            profile=profile,
            source="g2b",
            now=now,
            organization_id=organization_id,
            gate="CHECK",
            capacity=capacity,
            tracks=list(work["tracks"]),
            rules=[],
        )
        score = priority.normalize(components)
        # 40차 D26 — 사전규격은 조달분류가 없다 — 제목 · 일의 종류에 갈래가 없으면 「갈래 미분류 D」 대신 분류 낱말로 정한다
        fit_type, fit_basis = practical.type_of_kinds(list(work["kinds"]), title, fallback=practical.prespec_fallback(match, title))
        main_id = getattr(main, "id", None)
        for linked in listed:
            if published is None or not getattr(linked, "published_at", None):
                continue
            gap = (linked.published_at.astimezone(KST).date() - published.astimezone(KST).date()).days
            if gap >= 0:
                by_id[linked.id].pre_spec_note = f"사전규격 {gap}일 전 공개" if gap else "사전규격 같은 날 공개"
        items.append(
            UnifiedOpportunity(
                id=notice.id,
                source_type="g2b",
                opportunity_type="pre_spec",
                title=title,
                agency=agency,
                demand_agency=demand,
                summary=None,
                deadline=None,
                deadline_text=opinion_text(opinion),
                opinion_deadline=opinion,
                prespec_plan=" · ".join([prespec_plan(raw, opinion), *notes]) if notes else prespec_plan(raw, opinion),
                detail_url=notice.source_url,
                organization_id=organization_id,
                company_priority_score=score,
                procurement_fit_score=score,
                support_fit_score=None,
                review_priority_score=score,
                priority_rank=0,
                priority_label="미확인",
                eligibility_gate="CHECK",
                gate_reason=PRESPEC_GATE_REASON,
                confidence=priority.confidence_of(components, source="g2b"),
                score_components=components,
                source_specific_score=source_score,
                next_route=NextRoute(kind="procurement_analysis", path=f"/analysis?notice={main_id}", label=MAIN_OUT_LABEL)
                if main_id
                else NextRoute(kind="pre_spec", path="", label=MAIN_OUT_OFFLIST_LABEL)
                if offlist_main
                else NextRoute(kind="pre_spec", path="", label="본공고 전 — 규격서만 있음"),
                main_notice_id=main_id,
                source="g2b",
                closed=False,
                reasons=reasons,
                checks=checks,
                budget=notice.budget,
                work_kinds=work["kinds"],
                work_tracks=work["tracks"],
                work_basis=work["basis"],
                published_at=published,
                recruit_kind=practical.RECRUIT_BID,
                fit_type=fit_type,
                fit_type_basis=fit_basis,
                practical_candidate=match.is_candidate and event is None,
                evidence_line="공고문 아직 없음 — 본공고 전 사전규격",
                relevance_note=event
                if event
                else None
                if match.is_candidate
                else (match.low_reason or "후보 낱말 조합이 아닙니다(낱말 관련도 낮음)"),
            )
        )
    return items


#: 사전규격 판정 · 본공고 링크 글 (화면 · 브리핑이 같은 글을 쓴다).
PRESPEC_GATE_REASON = "확인 필요 — 본공고 전"
MAIN_OUT_LABEL = "본공고 나옴 →"
#: 본공고 번호는 있는데 저장본에 없는 사전규격(마감돼 목록에서 빠짐 · 받지 않은 공고 · 43차 PREP-09) — 발주계획과 같은 규칙.
MAIN_OUT_OFFLIST_LABEL = "본공고 나옴(나라장터에서 확인)"


#: 발주계획 공식 상세 주소의 앞머리 — 이것이 아니면 링크를 싣지 않는다(지어낸 · 바뀐 주소를 내보내지 않는다).
G2B_HTTPS = "https://www.g2b.go.kr/"


def plan_main_id(raw: dict[str, Any]) -> str | None:
    """발주계획이 가리키는 본공고 id(`R26BK01774291000` → `g2b-R26BK01774291-000`). 없으면 None."""
    first = str(raw.get("bidNtceNoList") or "").replace(";", ",").split(",")[0].strip()
    if len(first) < 13:
        return None
    order = first[13:16] or "000"
    return f"g2b-{first[:13]}-{order.zfill(3)}"


def plan_mains(notices: list[Any], main_ids: frozenset[str] | set[str] = frozenset()) -> dict[str, str]:
    """본공고 원본의 발주계획 번호(`raw_data.item.orderPlanUntyNo`) → 본공고 id (40차 PRESPEC-02).

    합쳐 남긴 옛 발주계획 행은 다시 오지 않아 `ntceNticeYn` 이 갱신되지 않는다 — 본공고 쪽에서 거꾸로 잇는다. 같은 계획에 공고가
    여럿이면 지금 목록(`main_ids`)에 있는 것 → 공고번호가 새것."""
    best: dict[str, tuple[bool, str, str]] = {}
    for notice in notices:
        raw = getattr(notice, "raw_data", None) or {}
        item = raw.get("item") if isinstance(raw, dict) else None
        plan = str((item or {}).get("orderPlanUntyNo") or "").strip()
        if not plan:
            continue
        rank = (notice.id in main_ids, str(getattr(notice, "notice_no", "") or ""), notice.id)
        if plan not in best or rank > best[plan]:
            best[plan] = rank
    return {plan: rank[2] for plan, rank in best.items()}


#: 제목 열쇠에서 떼는 낱말 — 「(사전규격)」 · 「[재공고]」 · 「【긴급】」 같은 괄호(둥근 · 네모 · 겹낫표 괄호)와 괄호 없는 「재공고 · 긴급」(44차 TEAM-R36-06)
_TITLE_NOISE_RE = re.compile(
    r"[(\[【［]\s*(?:사전\s*규격|긴급|재\s*공고|재\s*입찰)\s*[)\]】］]|재\s*공고|긴급|20\d\d\s*년?|\d{2}\s*년"
)


def title_key(title: str) -> str:
    """같은 사업을 잇는 제목 열쇠 — 띄어쓰기 · 문장부호 · 「(사전규격)」 · 「[재공고]」 · 「【긴급】」 · 괄호 없는 「재공고 · 긴급」 · 연도를 뺀다
    (43차 BRIEF-07 · H4 · 44차 TEAM-R36-06). 직접 넣기 중복 · 같은 사업 묶음 · 발주계획 잇기가 함께 쓴다."""
    text = _TITLE_NOISE_RE.sub(" ", title or "")
    return re.sub(r"[\W_]+", "", text).lower()


def order_plan_rows(
    now: datetime | None = None,
    *,
    main_ids: frozenset[str] | set[str] = frozenset(),
    plan_to_main: dict[str, str] | None = None,
    prespec_titles: frozenset[str] | set[str] = frozenset(),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """「발주 예정(발주계획)」 표 — `(후보, 후보 아님)`. 후보 판정은 나라장터 공고와 같은 `classify`(새 규칙 없음).

    `main_out` 은 본공고가 이미 난 것(`ntceNticeYn=Y` 이거나 `bidNtceNoList` · PRESPEC-03 · 또는 본공고 원본이 이 계획 번호를 가리킴 ·
    40차 PRESPEC-02 `plan_to_main`), `main_notice_id` 는 그 본공고가 `main_ids`(지금 저장본 목록)에 있을 때만.
    """
    from app.schemas.procurement import ProcurementNotice
    from app.services import practical_priority as practical

    plans, _ = load_order_plans()
    moment = now or storage.utc_now()
    keep: list[dict[str, Any]] = []
    low: list[dict[str, Any]] = []
    for raw in plans:
        title = str(raw.get("bizNm") or "").strip()
        notice = ProcurementNotice(
            id=f"g2bplan-{raw.get('orderPlanUntyNo') or title[:20]}",
            notice_no=str(raw.get("orderPlanUntyNo") or ""),
            title=title,
            agency=str(raw.get("orderInsttNm") or "").strip() or "기관 미상",
            published_at=parse_dt(raw.get("nticeDt")) or moment,
        )
        match = opportunity_filter.classify(notice)
        # 43차 BRIEF-07 — 사전규격과 같은 행사 · 전시 · 대행 규칙(CES 공동관 · AI+ 페스타가 발주계획 표에서 다시 섰다)
        event = opportunity_filter.event_title_of(title) if match.is_candidate else None
        plan_no = str(raw.get("orderPlanUntyNo") or "").strip()
        linked = (plan_to_main or {}).get(plan_no) if plan_no else None
        url = str(raw.get("orderPlanDtlUrl") or "").strip()
        month = str(raw.get("orderMnth") or "").strip()
        row = {
            "title": title,
            "agency": notice.agency,
            "when": f"{raw.get('orderYear') or '-'}-{month.zfill(2)}" if month else str(raw.get("orderYear") or "-"),
            "amount": g2b_mapper.parse_amount(str(raw.get("sumOrderAmt") or "")),
            "method": str(raw.get("cntrctMthdNm") or "").strip() or "-",
            "url": url if url.startswith(G2B_HTTPS) else None,
            "low_reason": event if event else (None if match.is_candidate else (match.low_reason or "후보 낱말 조합이 아닙니다(낱말 관련도 낮음)")),
            "main_out": str(raw.get("ntceNticeYn") or "").upper() == "Y" or bool(str(raw.get("bidNtceNoList") or "").strip()) or linked is not None,
            "main_notice_id": main_id if (main_id := plan_main_id(raw)) in main_ids else (linked if linked in main_ids else None),
        }
        row["prespec_out"] = title_key(title) in prespec_titles
        # 45차 M16 — 사전규격 · 입찰과 같은 유형(근사) · 주제 확인(제목 낱말) — 발주 예정 표 맨 위에 본업과 먼 계획이 섰다
        ptype, why = practical.type_of_kinds([], title, fallback=practical.prespec_fallback(match, title))
        row["fit_type"] = ptype
        if ptype in PLAN_FOLD_TYPES:
            row["note"] = f"유형(근사) {ptype} — {why} · 본업 덩어리 밖"
        else:
            row["note"] = practical.topic_of(SimpleNamespace(source_type="g2b", recruit_kind=None, fit_type=ptype, title=title))
        this_month = moment.astimezone(KST).strftime("%Y-%m")
        row["delayed"] = bool(month) and row["when"] < this_month and not row["main_out"] and not row["prespec_out"]
        (keep if match.is_candidate and not event else low).append(row)
    return keep, low


#: 발주 예정 표에서 접는 유형(근사) — 사전규격 「다른 사전규격」과 같은 본업 덩어리 밖(연구 · 감리 · 구매 · 제작)(45차 M16).
PLAN_FOLD_TYPES: frozenset[str] = frozenset({"B2", "D"})


def _opinion_open(item: Any, now: datetime) -> bool:
    return item.opinion_deadline is not None and item.opinion_deadline >= now


def section(
    pre_items: list[Any],
    *,
    now: datetime,
    main_ids: frozenset[str] | set[str] = frozenset(),
    plan_to_main: dict[str, str] | None = None,
    by_topic: bool = True,
) -> Any:
    """「선제준비」 칸(39차 결정 1). `pre_items` 는 `build_items` 결과에 실무 값(`practical_priority.annotate`)을 매긴 것.

    한 사전규격은 한 곳에만 든다(위에서부터): 본공고 나옴 → 본업 아님(비추천 · 연구 · 감리 · 구매 · 대형) → 의견 마감 지남 → 보임.
    칸 안 순서는 (실무순 회사면 주제 맞음 먼저 →) 의견 마감 남은 것 → 등록일 새것. 발주계획은 본공고 안 나온 것 먼저.
    `by_topic=False` — 점수순 회사(41차 TOPIC-02 · REGRESS-04 · D23 「점수순 회사는 꼬리표만 · 순서 그대로」).
    """
    from app.schemas.business_opportunity import OrderPlanRow, PrepareSection
    from app.services import practical_priority as practical

    merged: list[Any] = []
    others: list[Any] = []
    passed: list[Any] = []
    shown: list[Any] = []
    for item in pre_items:
        if item.main_notice_id or item.next_route.label == MAIN_OUT_OFFLIST_LABEL:
            merged.append(item)
        elif item.practical_group != "선제준비" or (item.practical_block or practical.BLOCK_CORE) != practical.BLOCK_CORE:
            others.append(item)
        elif item.opinion_deadline is not None and item.opinion_deadline < now:
            passed.append(item)
        else:
            shown.append(item)

    def key(item: Any) -> tuple:
        # 40차 D23 — 「보임」도 주제 맞음 먼저(「주제 확인」 · AI 「본업 아닐 수 있음」은 뒤) → 의견 마감 남은 것
        # 43차 Q5 — 그다음 의견 마감 7일 묶음(이번 주 · 다음 주 …) → 묶음 안 유형(A1 > A2 > B1 > C) → 점수 → 등록일 새것
        stamp = item.published_at.timestamp() if item.published_at else 0.0
        days = (item.opinion_deadline - now).days if _opinion_open(item, now) else 999
        return (
            practical.topic_rank(item) if by_topic else 0, 0 if _opinion_open(item, now) else 1, days // 7,
            practical.TYPE_ORDER.get(item.fit_type or "", 9), -(item.company_priority_score or 0), -stamp, item.id,
        )

    titles = frozenset(title_key(i.title) for i in pre_items)
    keep, low = order_plan_rows(now, main_ids=main_ids, plan_to_main=plan_to_main, prespec_titles=titles)
    core = [row for row in keep if row["fit_type"] not in PLAN_FOLD_TYPES]
    folded = [row for row in keep if row["fit_type"] in PLAN_FOLD_TYPES]

    def plan_key(row: dict[str, Any]) -> tuple:
        # 본공고 · 사전규격 안 나온 것 → (실무순 회사면) 주제 맞음 → 유형 A1 · A2 · B1 · C → 발주 지연 먼저(45차 M16 · 예전에는 앞 둘 · 지연만)
        return (
            row["main_out"] or row["prespec_out"], bool(row["note"]) if by_topic else False,
            practical.TYPE_ORDER.get(row["fit_type"] or "", 9), not row["delayed"],
        )

    _, prespec_fetched = load_prespecs()
    _, plans_fetched = load_order_plans()
    return PrepareSection(
        items=sorted(shown, key=key),
        others=sorted(others, key=key),
        opinion_passed=sorted(passed, key=key),
        merged=sorted(merged, key=key),
        plans=[OrderPlanRow(**row) for row in sorted(core, key=plan_key)],
        plans_folded=[OrderPlanRow(**row) for row in sorted(folded, key=plan_key)],
        plans_low=len(low),
        plans_note=order_plan_note(),
        fetched_at=prespec_fetched,
        plans_fetched_at=plans_fetched,
    )
