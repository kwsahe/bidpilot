"""나라장터(G2B) OpenAPI client — 조달청 입찰공고정보서비스 실호출.

- 공공데이터포털 "조달청_나라장터 입찰공고정보서비스" (BidPublicInfoService)
- 이 모듈은 HTTP 호출과 응답 봉투(header/body) 해석까지만 담당한다.
  item -> ProcurementNotice 매핑은 g2b_mapper.py가 맡는다.
- 필드명은 2026-09-03 실제 응답을 확인한 뒤 작성했다 (CLAUDE.md 25-4, 25-5).
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any, Sequence

from urllib.parse import quote, unquote

import httpx

from app.core import storage
from app.core.config import get_settings

# https 로 부른다. 인증키가 쿼리스트링에 실리므로 평문 http 면 경로상에서 그대로 보인다 (ISSUE-040).
G2B_BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"

# 용역(서비스) 입찰공고 목록 조회
OP_BID_LIST_SERVC = "getBidPblancListInfoServcPPSSrch"
# 물품 입찰공고 목록 조회 (필요 시 사용)
OP_BID_LIST_THNG = "getBidPblancListInfoThngPPSSrch"

# --------------------------------------------------------------------------
# 자격 제한 조회 (0921.md §4-A-1)
# --------------------------------------------------------------------------
# 같은 서비스의 다른 오퍼레이션이다. 봉투(response.body.items)도 같다.
#
# **둘 다 공고번호로 콕 집어 물을 수 없다.** `inqryDiv=2` + `bidNtceNo` 는 「필수값 입력
# 에러」가 난다(검수자 실측, 0921 §2). 그래서 목록과 **같은 게시일 창**으로 받아
# 공고번호+차수로 합친다.
OP_LICENSE_LIMIT = "getBidPblancListInfoLicenseLimit"
OP_PARTICIPATION_REGION = "getBidPblancListInfoPrtcptPsblRgn"

# --------------------------------------------------------------------------
# 사전규격 · 발주계획 (38차 §3-D · 담당자 결정 2 · data.go.kr 15129437 · 15129462 · 같은 인증키)
# --------------------------------------------------------------------------
# 경로 · 오퍼레이션 · 필드는 **2026-10-15 실제 응답**으로 확인했다(L3 · 진행 기록 §1). 둘 다 `/ao/` 아래다(입찰공고는 `/ad/`).
# - 사전규격(용역): `inqryDiv=1` + `inqryBgnDt` · `inqryEndDt`(YYYYMMDDHHMM · 등록일 창). 필드 `bfSpecRgstNo`(R26BD…) ·
#   `prdctClsfcNoNm`(사업명) · `orderInsttNm` · `rlDminsttNm` · `asignBdgtAmt` · `rcptDt` · `opninRgstClseDt`(**의견 마감 — 입찰 마감 아님**) ·
#   `bidNtceNoList`(본공고 번호 · 차수 없음) · `specDocFileUrl1~5`(규격서 · g2b.go.kr) · `ofclNm` · `ofclTelNo`(가린다). 상세 주소 칸은 없다.
# - 발주계획(용역): `inqryDiv=1` + `orderBgnYm` · `orderEndYm`(YYYYMM). 필드 `bizNm` · `orderInsttNm` · `orderYear` · `orderMnth` ·
#   `sumOrderAmt` · `cntrctMthdNm` · `orderPlanDtlUrl`(공식 상세) · `orderPlanUntyNo`(R26DD…) · `bidNtceNoList`(차수 붙은 꼴) ·
#   `deptNm` · `ofclNm` · `telNo`(가린다).
# - 한 페이지 999행을 준다(L3 실측 — 이틀 사전규격 797행 · 10월 발주계획 375행). 그래서 낱말마다 부르지 않고 창을 받아 같은 수집 낱말로 거른다.
AO_BASE_URL = "https://apis.data.go.kr/1230000/ao"
PRESPEC_SERVICE = "HrcspSsstndrdInfoService"
OP_PRESPEC_LIST = "getPublicPrcureThngInfoServc"
ORDERPLAN_SERVICE = "OrderPlanSttusService"
OP_ORDERPLAN_LIST = "getOrderPlanSttusListServc"
AO_ROWS_PER_PAGE = 999
#: 한 번 받을 때 서비스마다 부를 수 있는 최대 페이지(예산). 사전규격 7일 창 약 3페이지 · 발주계획 석 달 약 1~2페이지.
AO_MAX_PAGES = 5

logger = logging.getLogger(__name__)

# 뒤쪽 페이지(최신 공고)는 응답이 느린 편이라 읽기 시간을 넉넉히 준다.
DEFAULT_TIMEOUT = httpx.Timeout(35.0, connect=5.0)
KST = timezone(timedelta(hours=9))

# 조회구분: 1 = 공고게시일시 기준
INQRY_DIV_NOTICE_DATE = 1

# 한 번에 받을 최대 페이지 수 (안전장치)
MAX_PAGES = 20
# 뒤쪽 페이지 연속 실패 허용 횟수. 이 이상이면 모은 것까지만 쓴다.
MAX_PAGE_FAILURES = 3
MAX_ROWS_PER_PAGE = 100

# --------------------------------------------------------------------------
# 공고명 키워드 수집 (0920.md §4-A-1 · ISSUE-072)
# --------------------------------------------------------------------------
# 한 번의 수집에서 나라장터를 부를 수 있는 최대 횟수. 일일 한도를 갉아먹지 않으려는 예산이다.
# 실측(2026-09-17, 30일 창): 마감 전 totalCount 가 AI 193 · 인공지능 7 · 생성형 7 이라
# 키워드 10개면 첫 페이지 10회 + 두 번째 페이지 몇 회로 끝난다.
MAX_COLLECT_CALLS = 15
# 38차 §3-A — 수집 낱말을 회사 사업영역으로 넓혀(10개 → 21개) 하루 키워드 호출이 약 24회가 됐다(L1 실측 · 2026-10-15).
# 낱말이 늘어 페이지가 늘어도 끝까지 받을 여유를 둔다. data.go.kr 개발계정 하루 1,000회 안이다.
# 2.0.7 대표 결정 ④ — 추가 낱말(최대 10개)이 첫 쪽마다 한 번씩 쓰므로 기본 낱말의 2 · 3쪽이 밀리지 않게 40 → 50.
# 2.8.1 — 조달청이 조회 기간을 7일로 막아(`MAX_WINDOW_DAYS`) 30일을 창 5개로 나눠 부른다: 기본 낱말 21 × 5 = 105 + 추가 낱말 10 × 5 = 50
# + 2 · 3쪽 몫 → 200. 하루 한 번 성공하면 약 110회 · data.go.kr 개발계정 하루 1,000회 안(노트북 · 서버가 같은 키를 써도).
MAX_COLLECT_CALLS = 200
# 키워드 하나 · 창 하나에 쓸 수 있는 최대 페이지. 한 키워드가 예산을 통째로 먹지 않게 한다.
MAX_PAGES_PER_KEYWORD = 3
#: 조달청 입찰공고 목록의 조회 기간 상한 — **시작일 포함 7일(날짜 칸으로 잼)**. 넘으면 resultCode 07 「입력범위값 초과 에러」.
#: 2026-11-11 07:30 부터 생긴 제한이다(11-10 까지는 30일 창이 됐다). 2026-11-12 실측: 끝 11-12 10:33 에서 시작 11-06 04:33(150시간)은 되고
#: 11-05 23:33(155시간) · 7일 · 14일 · 30일은 거절 — 시간 길이가 아니라 날짜 칸으로 잰다. 자격 조회는 원래 하루 창이라 상관없다.
MAX_WINDOW_DAYS = 7
#: 한 건도 받지 못한 채 잇달아 이만큼 실패하면 그만 부른다 — 조달청이 모두 거절하는 날 하루 한도를 헛되이 쓰지 않게(11-11 · 21회 모두 실패).
ABORT_AFTER_FAILURES = 10

#: 공고명 검색 파라미터. 실측으로 확인했다 (docs/reports/2026-09-20_qa_recheck5.md §1-4).
PARAM_NOTICE_NAME = "bidNtceNm"
#: 마감된 공고를 빼는 파라미터. 「Y」면 마감 전만 준다.
PARAM_CLOSED_EXCLUDED = "bidClseExcpYn"


class G2BClientError(Exception):
    """나라장터 API 호출 실패."""


class G2BKeyMissingError(G2BClientError):
    """DATA_GO_KR_SERVICE_KEY 환경변수가 설정되지 않음."""


class G2BApiError(G2BClientError):
    """API가 정상(resultCode=00) 이외의 결과를 반환함."""

    def __init__(self, result_code: str, result_msg: str) -> None:
        super().__init__(f"G2B API error {result_code}: {result_msg}")
        self.result_code = result_code
        self.result_msg = result_msg


def is_configured() -> bool:
    """서비스키가 설정되어 있는지 여부."""
    return bool(get_settings().data_go_kr_service_key)


def normalize_service_key(key: str) -> str:
    """공공데이터포털이 주는 두 형태(Encoding/Decoding) 중 무엇을 넣어도 동작하게 만든다.

    포털은 같은 키를 URL 인코딩된 형태와 원본 형태 두 가지로 보여준다. 인코딩된 쪽을
    그대로 쓰면 httpx가 쿼리 파라미터로 한 번 더 인코딩해 `%2F`가 `%252F`가 되고
    403이 떨어진다 (실측). 원본 키는 base64라 `%`가 없으므로, `%`가 있으면
    인코딩된 형태로 보고 한 번 풀어 준다.
    """
    return unquote(key) if "%" in key else key


def _require_key() -> str:
    key = get_settings().data_go_kr_service_key
    if not key:
        raise G2BKeyMissingError("DATA_GO_KR_SERVICE_KEY is not set. Configure it in .env")
    return normalize_service_key(key)


def _redact(text: str, key: str) -> str:
    """오류 메시지에서 서비스키를 지운다 (원본·인코딩 형태 모두). CLAUDE.md 21."""
    cleaned = text.replace(key, "<KEY>")
    return cleaned.replace(quote(key, safe=""), "<KEY>")


_PORTAL_ERR_RE = re.compile(r'"errMsg"\s*:\s*"([A-Z_]{3,80})"')
_PORTAL_AUTH_MSG_RE = re.compile(r'"returnAuthMsg"\s*:\s*"([^"]{1,80})"')


def _status_message(response: httpx.Response) -> str:
    """4xx · 5xx 오류 글 — 공공데이터포털 오류 봉투(하루 한도 초과 등)면 풀이와 코드를 남긴다(받기 원인 풀이가 코드를 읽는다).

    11-01 — 하루 한도 초과가 HTTP 429 + JSON 봉투로 와서 `raise_for_status` 의 영어 글(요청 주소 포함)만 띠에 떴다.
    요청 주소는 넣지 않는다(서비스키가 든다)."""
    head = response.text[:2000]
    code = _PORTAL_ERR_RE.search(head)
    if code:
        auth = _PORTAL_AUTH_MSG_RE.search(head)
        detail = f"{auth.group(1)} · {code.group(1)}" if auth else code.group(1)
        return f"공공데이터포털이 나라장터 호출을 막았습니다(HTTP {response.status_code} · {detail})"
    return f"조달청(나라장터) API 가 오류를 돌려줬습니다(HTTP {response.status_code})"


_HTML_PAGE_RE = re.compile(r"^\s*<(?:!DOCTYPE\s+html|html)", re.I)
_HTML_TITLE_RE = re.compile(r"<title>\s*([^<]{1,60}?)\s*</title>", re.I)


def _non_json_message(text: str, key: str) -> str:
    """JSON 이 아닌 응답의 오류 글. 서비스키 오류 XML 은 원문을 둔다(받기 원인 풀이 `auto_collect.failure_hint` 가 읽는다).

    11-01 — 조달청이 「시스템 점검 안내」 HTML 을 보낸 날, 그 HTML 앞부분이 사업기회 띠 · 대시보드에 그대로 떴다.
    """
    if _HTML_PAGE_RE.match(text):
        title = _HTML_TITLE_RE.search(text[:3000])
        return "조달청(나라장터)이 목록 대신 안내 화면을 보냈습니다" + (f" — 「{title.group(1)}」" if title else "")
    return f"G2B API returned non-JSON response: {_redact(text[:300], key)}"


def format_inquiry_dt(value: datetime) -> str:
    """API가 요구하는 조회일시 형식 (YYYYMMDDHHMM, KST 기준)."""
    return value.astimezone(KST).strftime("%Y%m%d%H%M")


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    """응답 봉투에서 body를 꺼낸다. resultCode가 정상이 아니면 예외."""
    response = payload.get("response")
    if not isinstance(response, dict):
        raise G2BClientError(f"Unexpected G2B response shape: {str(payload)[:200]}")
    header = response.get("header") or {}
    code = str(header.get("resultCode", ""))
    if code != "00":
        raise G2BApiError(code, str(header.get("resultMsg", "")))
    body = response.get("body")
    if not isinstance(body, dict):
        raise G2BClientError("G2B response has no body")
    return body


def _total_count_of(body: dict[str, Any]) -> int | None:
    """응답의 전체 건수. 못 읽으면 None (그때는 앞에서부터 모으는 예전 방식으로 돈다)."""
    value = body.get("totalCount")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _items_of(body: dict[str, Any]) -> list[dict[str, Any]]:
    """items는 결과가 없으면 빈 문자열로 오는 경우가 있어 정규화한다."""
    items = body.get("items")
    if isinstance(items, list):
        return [i for i in items if isinstance(i, dict)]
    if isinstance(items, dict):
        return [items]
    return []


async def fetch_bid_notices_raw(
    *,
    begin: datetime,
    end: datetime,
    num_rows: int = MAX_ROWS_PER_PAGE,
    page_no: int = 1,
    operation: str = OP_BID_LIST_SERVC,
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """입찰공고 목록 한 페이지를 조회하고 body(dict)를 반환한다.

    begin/end는 공고게시일시 조회 범위이며 API 필수 파라미터다.
    """
    key = _require_key()
    params: dict[str, Any] = {
        "serviceKey": key,
        "pageNo": page_no,
        "numOfRows": min(num_rows, MAX_ROWS_PER_PAGE),
        "type": "json",
        "inqryDiv": INQRY_DIV_NOTICE_DATE,
        "inqryBgnDt": format_inquiry_dt(begin),
        "inqryEndDt": format_inquiry_dt(end),
    }
    if extra_params:
        params.update(extra_params)

    url = f"{G2B_BASE_URL}/{operation}"
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise G2BClientError(_status_message(exc.response)) from exc
    except httpx.HTTPError as exc:
        # 예외 문자열에 요청 URL(=서비스키 포함)이 들어온다. 반드시 지우고 올린다.
        raise G2BClientError(f"G2B API request failed: {_redact(str(exc), key)}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        # 서비스키 오류 등은 XML로 내려온다. 키 값은 로그에 남기지 않는다.
        raise G2BClientError(_non_json_message(response.text, key)) from exc

    return _unwrap(payload)


async def _ao_page(service: str, operation: str, params: dict[str, Any]) -> dict[str, Any]:
    """`/ao/` 서비스 한 페이지의 body. 키 마스킹 · 봉투 해석은 입찰공고와 같은 함수(`_redact` · `_unwrap`)를 쓴다."""
    key = _require_key()
    query: dict[str, Any] = {"serviceKey": key, "type": "json", **params}
    url = f"{AO_BASE_URL}/{service}/{operation}"
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.get(url, params=query)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise G2BClientError(_status_message(exc.response)) from exc
    except httpx.HTTPError as exc:
        raise G2BClientError(f"G2B API request failed: {_redact(str(exc), key)}") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise G2BClientError(_non_json_message(response.text, key)) from exc
    return _unwrap(payload)


@dataclass(frozen=True)
class AoOutcome:
    """사전규격 · 발주계획 한 번 받기. 받은 원본 · 부른 횟수 · 전체 건수 · 덜 받았나."""

    items: list[dict[str, Any]]
    calls: int
    total: int | None
    truncated: bool


async def _drain_ao(service: str, operation: str, params: dict[str, Any], *, max_pages: int) -> AoOutcome:
    items: list[dict[str, Any]] = []
    calls = 0
    total: int | None = None
    page = 1
    while page <= max_pages:
        calls += 1
        body = await _ao_page(service, operation, {**params, "pageNo": page, "numOfRows": AO_ROWS_PER_PAGE})
        total = _total_count_of(body)
        got = _items_of(body)
        items.extend(got)
        if total is None:
            if len(got) < AO_ROWS_PER_PAGE:
                return AoOutcome(items, calls, total, False)
        elif page * AO_ROWS_PER_PAGE >= total:
            return AoOutcome(items, calls, total, False)
        page += 1
    return AoOutcome(items, calls, total, True)


async def fetch_prespecs(*, days: int = 7, now: datetime | None = None, max_pages: int = AO_MAX_PAGES) -> AoOutcome:
    """사전규격(용역) — 등록일 `days` 일 창을 통째로(999행씩). 거르기는 부르는 쪽이 한다(수집 낱말 · `prespec_service`)."""
    end = (now or storage.utc_now()).astimezone(KST)
    begin = end - timedelta(days=days)
    params = {"inqryDiv": 1, "inqryBgnDt": format_inquiry_dt(begin), "inqryEndDt": format_inquiry_dt(end)}
    return await _drain_ao(PRESPEC_SERVICE, OP_PRESPEC_LIST, params, max_pages=max_pages)


async def fetch_order_plans(*, months: int = 3, now: datetime | None = None, max_pages: int = AO_MAX_PAGES) -> AoOutcome:
    """발주계획(용역) — 이번 달부터 `months` 달(YYYYMM 창)을 통째로(999행씩)."""
    start = (now or storage.utc_now()).astimezone(KST)
    year, month = start.year, start.month
    end_index = year * 12 + (month - 1) + max(1, months) - 1
    params = {
        "inqryDiv": 1,
        "orderBgnYm": f"{year:04d}{month:02d}",
        "orderEndYm": f"{end_index // 12:04d}{end_index % 12 + 1:02d}",
    }
    return await _drain_ao(ORDERPLAN_SERVICE, OP_ORDERPLAN_LIST, params, max_pages=max_pages)


async def search_bid_notices(
    keyword: str,
    *,
    days: int = 30,
    now: datetime | None = None,
    page_no: int = 1,
    num_rows: int = MAX_ROWS_PER_PAGE,
    closed_excluded: bool = True,
    operation: str = OP_BID_LIST_SERVC,
    begin: datetime | None = None,
    end: datetime | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """공고명에 `keyword` 가 든 공고를 한 페이지 받는다. `(items, totalCount)`.

    창은 `begin` · `end` 를 주면 그대로, 없으면 `now` 에서 `days` 일 전까지 — 조달청 기간 상한(`MAX_WINDOW_DAYS`)을
    넘는 창은 거절되므로 긴 창은 `inquiry_windows` 로 나눠 부른다(`collect_notices`).

    나라장터는 공고명 검색(`bidNtceNm`)과 마감 제외(`bidClseExcpYn=Y`)를 받는다.
    창을 통째로 훑는 것(`fetch_bid_notices`)과 달리 **필요한 것만** 받으므로 호출이 훨씬 적다 —
    30일 창에서 「AI」가 마감 전 193건이라 2페이지면 끝난다.

    `totalCount` 를 함께 돌려주는 이유: 호출자가 「이 키워드에 몇 페이지가 더 필요한가」를
    받아 보기 **전에** 알아야 예산을 나눌 수 있다.

    HTTP·인증·키 마스킹·봉투 해석은 `fetch_bid_notices_raw` 하나만 쓴다 — 여기서 httpx 를
    직접 부르면 오류 메시지의 서비스키 마스킹(CLAUDE.md 21)이 통째로 빠진다.
    """
    end = end or now or storage.utc_now().astimezone(KST)
    begin = begin or end - timedelta(days=days)
    extra: dict[str, Any] = {PARAM_NOTICE_NAME: keyword}
    if closed_excluded:
        extra[PARAM_CLOSED_EXCLUDED] = "Y"
    body = await fetch_bid_notices_raw(
        begin=begin,
        end=end,
        page_no=page_no,
        num_rows=num_rows,
        operation=operation,
        extra_params=extra,
    )
    return _items_of(body), _total_count_of(body)


def inquiry_windows(begin: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """[begin, end] 를 조달청 기간 상한(시작일 포함 `MAX_WINDOW_DAYS` 일 · 날짜 칸) 안의 창으로 나눈다 — **새 창 먼저**
    (예산이 모자라면 최신 공고부터 받게). 30일이면 다섯 창: 오늘 포함 7일 · 그 앞 7일씩 · 남은 며칠."""
    # 조회 칸은 분 단위다 — 시작을 분으로 내려야 「시작이 23:59:초」일 때 그 마지막 1분 창을 버리지 않는다(2.8.1 검토)
    begin, end = begin.astimezone(KST).replace(second=0, microsecond=0), end.astimezone(KST)
    windows: list[tuple[datetime, datetime]] = []
    upper = end
    while True:
        first_day = upper.date() - timedelta(days=MAX_WINDOW_DAYS - 1)
        lower = max(begin, datetime(first_day.year, first_day.month, first_day.day, tzinfo=KST))
        windows.append((lower, upper))
        if lower <= begin:
            return windows
        before = lower.date() - timedelta(days=1)
        upper = datetime(before.year, before.month, before.day, 23, 59, tzinfo=KST)
        if upper < begin:  # 시작이 전날 23:59 뒤(초 단위)라 남은 몫이 없다
            return windows


def _item_key(item: dict[str, Any]) -> str:
    """같은 공고인지 가리는 열쇠. 공고번호 + 차수 — `g2b_mapper.notice_id` 와 같은 조합이다."""
    return f"{item.get('bidNtceNo', '')}-{item.get('bidNtceOrd', '')}"


#: 자격 정보를 받는 데 쓸 수 있는 최대 호출 횟수. **목록 예산과 따로 둔다.**
#:
#: 같은 예산을 쓰면 목록 페이지가 밀려 공고를 놓친다 — ISSUE-072 가 그렇게 생겼다.
#:
#: 이 값은 **하루 창 방식의 한 번 백필**을 위한 천장이다(0922 §3-10′: 백필 120 + 목록 10).
#: 하루치를 받는 데 두 오퍼레이션 × 2페이지 = 4회이므로 30일이면 120회다. 한 번 받은 날은
#: 저장소에 남아 다시 부르지 않으므로(`qualification_store`), 그 뒤로는 새로 생긴 날만
#: 받아 매일 4~6회로 끝난다.
MAX_QUALIFICATION_CALLS = 120
#: 자격 조회 한 페이지의 건수.
#:
#: 목록 조회는 100 이 상한인데(`MAX_ROWS_PER_PAGE`), **자격 조회는 999 를 그대로 준다**
#: (2026-09-17 실측). 1000 이상을 넣으면 기본값 10건으로 떨어지므로 999 가 실측 상한이다.
QUALIFICATION_ROWS_PER_PAGE = 999
#: 하루 창 한 번에 받을 최대 페이지.
#:
#: 실측(2026-09-22 재검증 §2-1): 하루 1,500~1,850행이라 999건씩 **2페이지**면 끝난다.
#: 3 으로 두는 것은 행이 늘어난 날의 여유일 뿐이고, 넘치면 「덜 받았다」고 말한다.
QUALIFICATION_MAX_PAGES_PER_DAY = 3


async def fetch_qualification_page(
    operation: str,
    *,
    begin: datetime,
    end: datetime,
    page_no: int = 1,
    num_rows: int = QUALIFICATION_ROWS_PER_PAGE,
) -> tuple[list[dict[str, Any]], int | None]:
    """자격 제한 한 페이지. `(items, totalCount)`.

    공고명(`bidNtceNm`)·마감 제외(`bidClseExcpYn`)를 붙이지 않는다 — **이 오퍼레이션들은
    공고번호·업무구분 필터를 받지 않는다**(2026-09-17 실측: `bidNtceNo`·`bsnsDivNm` 를 넣어도
    totalCount 가 그대로다). 좁힐 수 있는 것은 게시일 창 하나뿐이고, 그래서 **창을 하루로**
    좁힌다(0922 §2).

    `numOfRows` 는 `fetch_bid_notices_raw` 의 100 clamp 를 넘겨야 하므로 `extra_params` 로 준다.
    """
    body = await fetch_bid_notices_raw(
        begin=begin,
        end=end,
        page_no=page_no,
        operation=operation,
        extra_params={"numOfRows": max(1, int(num_rows))},
    )
    return _items_of(body), _total_count_of(body)


def _qualification_key(item: dict[str, Any]) -> str:
    """자격 항목을 공고에 붙일 열쇠. 목록 항목의 `_item_key` 와 같은 조합이어야 한다."""
    return f"{item.get('bidNtceNo', '')}-{item.get('bidNtceOrd', '')}"


def day_window(day: date) -> tuple[datetime, datetime]:
    """하루 창 (KST 00:00 ~ 23:59). 자격 조회는 이 창으로만 부른다."""
    begin = datetime(day.year, day.month, day.day, 0, 0, tzinfo=KST)
    end = datetime(day.year, day.month, day.day, 23, 59, tzinfo=KST)
    return begin, end


@dataclass(frozen=True)
class DayQualifications:
    """**하루치** 자격 정보 (0922 §4-A-1).

    7차의 「창 전체를 뒤에서부터」 설계를 버리고 하루 창으로 바꾼 결과다. 창을 하루로 좁히면
    1,500~1,850행이라 999건씩 2페이지면 끝나고, **용역 공고의 업종 코드가 그대로 온다**
    (7차는 창 끝 페이지만 보고 「용역은 한 건도 없다」고 잘못 판단했다 — ISSUE-081).
    """

    day: date
    #: 공고번호-차수 → 면허제한 원본 항목 목록.
    licenses: dict[str, list[dict[str, Any]]]
    #: 공고번호-차수 → 참가가능지역 원본 항목 목록.
    regions: dict[str, list[dict[str, Any]]]
    #: 실제로 부른 횟수 (실패도 센다 — 한도를 쓴 것은 같다).
    calls: int
    #: 두 오퍼레이션을 **끝까지** 받았는가. False 면 이 날은 「미확인」으로 남긴다.
    complete: bool
    #: 받은 행 수 (면허, 지역).
    license_rows: int = 0
    region_rows: int = 0
    #: 못 받은 사유. 없으면 None.
    note: str | None = None


async def fetch_qualifications_for_day(
    day: date,
    *,
    max_pages: int = QUALIFICATION_MAX_PAGES_PER_DAY,
) -> DayQualifications:
    """하루 창으로 면허제한·참가가능지역을 **끝까지** 받아 공고번호+차수로 묶는다.

    실패해도 예외를 올리지 않는다 — 자격 정보가 없다고 목록 수집 전체를 죽이면 안 된다.
    대신 `complete=False` 와 사유를 남기고, 그 날의 공고는 「미확인」으로 둔다.
    """
    begin, end = day_window(day)
    licenses: dict[str, list[dict[str, Any]]] = {}
    regions: dict[str, list[dict[str, Any]]] = {}
    calls = 0
    problems: list[str] = []
    complete = True
    rows = {"면허제한": 0, "참가가능지역": 0}

    async def drain(operation: str, bucket: dict[str, list[dict[str, Any]]], label: str) -> None:
        nonlocal calls, complete
        page = 1
        while page <= max_pages:
            calls += 1
            try:
                items, total = await fetch_qualification_page(
                    operation, begin=begin, end=end, page_no=page
                )
            except G2BClientError as exc:
                problems.append(f"{label} {page}페이지 실패: {exc}")
                logger.warning("나라장터 %s 조회 실패 (%s %s페이지)", label, day, page)
                complete = False
                return
            for item in items:
                bucket.setdefault(_qualification_key(item), []).append(item)
                rows[label] += 1
            received = page * QUALIFICATION_ROWS_PER_PAGE
            if total is None:
                # 전체 건수를 못 읽었다. 한 페이지가 덜 찼으면 끝난 것으로 본다.
                if len(items) < QUALIFICATION_ROWS_PER_PAGE:
                    return
            elif received >= total:
                return
            page += 1
        problems.append(f"{label} {day} 하루치를 {max_pages}페이지 안에 다 받지 못했습니다")
        complete = False

    await drain(OP_LICENSE_LIMIT, licenses, "면허제한")
    await drain(OP_PARTICIPATION_REGION, regions, "참가가능지역")
    return DayQualifications(
        day=day,
        licenses=licenses,
        regions=regions,
        calls=calls,
        complete=complete,
        license_rows=rows["면허제한"],
        region_rows=rows["참가가능지역"],
        note=" · ".join(problems) or None,
    )


@dataclass(frozen=True)
class CollectOutcome:
    """키워드 수집 한 번의 결과. **호출 횟수를 결과와 함께 돌려준다.**

    화면과 보고서가 「몇 번 불렀는가」를 물어보기 때문이다(0920 §4-A-1·§4-A-3). 호출 횟수를
    로그에만 남기면 화면은 그것을 알 길이 없고, 전역 카운터로 두면 동시 요청에서 섞인다.
    """

    items: list[dict[str, Any]]
    #: 실제로 나라장터를 부른 횟수 (실패한 호출도 센다 — 한도를 쓴 것은 같다).
    calls: int
    #: 화면에 그대로 적는 한국어 한 줄. 「공고명 키워드 10개 · 마감 제외 · 최근 30일」
    method: str
    #: 키워드별 마감 전 전체 건수 (totalCount). 못 읽었으면 None.
    keyword_totals: dict[str, int | None]
    #: 예산이 모자라 끝까지 못 받은 키워드. **조용히 자르지 않는다.**
    truncated: tuple[str, ...]
    #: 페이지 조회가 한 번이라도 실패한 키워드(39차 DAILY-02 — 그 낱말 몫은 부르는 쪽이 지난 저장본으로 채운다).
    failed: tuple[str, ...] = ()
    #: 실패한 호출 수(`calls` 에 들어 있다).
    failures: int = 0


class G2BCollectError(G2BClientError):
    """키워드 조회에서 한 건도 못 받았다 — 이번 실행의 호출 · 실패 수를 함께 든다(39차 DAILY-06 · 로그가 지난 호출 수를 적던 것)."""

    def __init__(self, message: str, *, calls: int, failures: int) -> None:
        super().__init__(message)
        self.calls = calls
        self.failures = failures


async def collect_notices(
    *,
    keywords: Sequence[str],
    days: int = 30,
    now: datetime | None = None,
    max_calls: int = MAX_COLLECT_CALLS,
    closed_excluded: bool = True,
    operation: str = OP_BID_LIST_SERVC,
) -> CollectOutcome:
    """공고명 키워드로 마감 전 공고를 모은다. **이것이 기본 수집 경로다** (0920 §4-A-1).

    ## 왜 창 순회를 그만두었나

    `fetch_bid_notices` 는 「창을 통째로 훑되 마지막 페이지가 최신이니 뒤에서 600건만 보면
    된다」고 가정했다. **그 가정이 틀렸다.** 나라장터는 «용역구분 → 게시일» 순으로 준다 —
    30일 창 12,807건 중 앞 9,078건이 일반용역, 그 뒤가 기술용역이고 각각 안에서 게시일
    오름차순이다. 「마지막 600건」은 기술용역 꼬리라서, AI 교육·컨설팅 공고(전부 일반용역)는
    **구조적으로 한 건도 들어오지 않았다.** 실측으로 마감 전 후보 117건 중 앱 캐시에는
    4건뿐이었다 (docs/reports/2026-09-20_qa_recheck5.md §1-3).

    ## 예산을 어떻게 나누나

    0. (2.8.1) 조달청이 조회 기간을 시작일 포함 7일로 막아(`MAX_WINDOW_DAYS`) `days` 일을 7일 창으로 나눈다(`inquiry_windows` ·
       30일이면 다섯 · 새 창 먼저). 아래 「키워드」는 (키워드 · 창) 한 칸이다.
    1. 창마다(새 창 먼저) 키워드마다 1페이지씩 받는다. 이때 `totalCount` 도 함께 읽는다.
    2. 남은 예산을 **아직 못 받은 건수가 많은 (키워드 · 창)부터** 한 페이지씩 나눠 준다.
    3. 한 건도 못 받은 채 잇달아 `ABORT_AFTER_FAILURES` 번 실패하면 그만 부른다(모두 거절하는 날 하루 한도를 지킨다).

    예산이 모자라 다 못 받은 키워드는 `truncated` 로 **말한다.** 조용히 자르면 다음 사람이
    「그 공고는 원래 없다」로 읽는다.

    한 건도 못 모으면 예외를 올린다 — 호출자(`procurement_service`)가 캐시로 넘어가는
    계약이다. 빈 목록을 조용히 돌려주면 캐시가 빈 목록으로 덮어써진다.
    """
    end = now or storage.utc_now().astimezone(KST)
    picked = [k for k in dict.fromkeys(keywords) if k.strip()]
    if not picked:
        raise ValueError("수집 키워드가 비어 있습니다")
    # 조달청 기간 상한(7일) 때문에 창을 나눈다 — 새 창 먼저(2.8.1). 받는 범위(최근 days 일 · 마감 전)는 그대로다.
    windows = inquiry_windows(end - timedelta(days=days), end)

    Unit = tuple[str, int]  # (낱말, 창 번호)
    merged: dict[str, dict[str, Any]] = {}
    # 받은 공고의 줄 순서 — 부르는 쪽이 앞에서부터 상한(`procurement_service.DEFAULT_MAX_ITEMS`)까지만 쓴다. 창을 나누기 전과 같은
    # 우선순위로 줄 세운다: 첫 쪽 먼저 → 낱말 순서 → 새 창 먼저(2.8.1 검토 — 상한이 600 이던 때 「새 창 먼저」로 쌓았더니 2~4주 전
    # 게시된 마감 전 후보 23건(2 · 3순위 공고 포함)이 잘렸다 · 상한도 2000 으로 올림).
    rank: dict[str, tuple[int, int, int, int]] = {}
    order = {keyword: index for index, keyword in enumerate(picked)}
    totals: dict[Unit, int | None] = {}
    received: dict[Unit, int] = {}
    pages_used: dict[Unit, int] = {}
    calls = 0
    failures = 0
    in_a_row = 0
    succeeded = False
    failed: set[str] = set()
    # (2.0.7) 마지막 실패 사유 — 한 건도 못 받았을 때 예외 글에 붙여 「할 일」 안내(failure_hint)가 원인을 알아보게 한다.
    # 원문은 G2BClientError 가 이미 키를 가린(_redact) 코드 · 메시지뿐이다.
    last_error = ""

    def stop() -> bool:
        """예산을 다 썼거나, 한 번도 받지 못한 채 잇달아 실패했다(모두 거절하는 날 하루 한도를 지킨다)."""
        return calls >= max_calls or (not succeeded and in_a_row >= ABORT_AFTER_FAILURES)

    async def one_page(unit: Unit, page_no: int) -> bool:
        """한 페이지를 받아 합친다. 성공하면 True. 호출 횟수는 실패해도 센다."""
        nonlocal calls, failures, last_error, in_a_row, succeeded
        keyword, window = unit
        calls += 1
        try:
            items, total = await search_bid_notices(
                keyword,
                begin=windows[window][0],
                end=windows[window][1],
                page_no=page_no,
                closed_excluded=closed_excluded,
                operation=operation,
            )
        except G2BClientError as exc:
            failures += 1
            in_a_row += 1
            failed.add(keyword)
            last_error = str(exc)
            logger.warning("나라장터 키워드 조회 실패 (%s 창 %d · %d페이지, 누적 %d회)", keyword, window + 1, page_no, failures)
            return False
        in_a_row = 0
        succeeded = True
        if page_no == 1:
            totals[unit] = total
        received[unit] = received.get(unit, 0) + len(items)
        for seq, item in enumerate(items):
            key = _item_key(item)
            merged.setdefault(key, item)
            here = (0 if page_no == 1 else 1, order[keyword], window, seq)
            rank[key] = min(rank.get(key, here), here)
        return True

    # 1) 창마다(새 창 먼저) 낱말마다 첫 쪽 — 예산이 모자라도 모든 낱말의 최근 공고가 먼저 들어온다.
    for window in range(len(windows)):
        for keyword in picked:
            if stop():
                break
            pages_used[(keyword, window)] = 1
            await one_page((keyword, window), 1)

    # 2) 남은 예산을 「아직 못 받은 건수」가 큰 (낱말 · 창)부터 나눠 준다. (2.0.7) **기본 낱말이 먼저** — 넓은 추가 낱말(사람이 더한 낱말)이
    # 「교육」 · 「AI」의 2 · 3쪽을 밀어내 본업 공고가 저장본에서 빠졌다. 추가 낱말은 기본 몫이 끝난 뒤에만 2 · 3쪽을 받는다.
    from app.services.opportunity_filter import COLLECT_KEYWORDS

    while not stop():
        best: tuple[tuple[bool, int], Unit] | None = None
        for unit, used in pages_used.items():
            total = totals.get(unit)
            if total is None or used >= MAX_PAGES_PER_KEYWORD:
                continue
            remaining = total - received.get(unit, 0)
            key = (unit[0] in COLLECT_KEYWORDS, remaining)
            if remaining > 0 and (best is None or key > best[0]):
                best = (key, unit)
        if best is None:
            break
        unit = best[1]
        pages_used[unit] += 1
        await one_page(unit, pages_used[unit])

    def short(keyword: str) -> bool:
        """그 낱말을 다 받지 못했다 — 예산이 모자라 부르지 못한 창이 있거나, 받은 창에서 전체 건수보다 덜 받았다(실패한 창은 `failed`)."""
        for window in range(len(windows)):
            unit = (keyword, window)
            if unit not in pages_used:
                return True
            total = totals.get(unit)
            if total is not None and received.get(unit, 0) < total:
                return True
        return False

    truncated = tuple(keyword for keyword in picked if short(keyword))
    keyword_totals: dict[str, int | None] = {}
    for keyword in picked:
        known = [t for w in range(len(windows)) if (t := totals.get((keyword, w))) is not None]
        keyword_totals[keyword] = sum(known) if known else None

    items = [merged[key] for key in sorted(merged, key=rank.__getitem__)]
    if not items:
        raise G2BCollectError(
            f"나라장터 키워드 조회에서 한 건도 받지 못했습니다 (호출 {calls}회 · 실패 {failures}회)."
            + (f" — 마지막 오류: {last_error[:160]}" if last_error else ""),
            calls=calls,
            failures=failures,
        )

    window = "마감 제외" if closed_excluded else "마감 포함"
    method = f"공고명 키워드 {len(picked)}개 · {window} · 최근 {days}일"
    if truncated:
        logger.warning("키워드 %s 는 호출 예산 안에서 다 받지 못했습니다", ", ".join(truncated))
    return CollectOutcome(
        items=items,
        calls=calls,
        method=method,
        keyword_totals=keyword_totals,
        truncated=truncated,
        failed=tuple(k for k in picked if k in failed),
        failures=failures,
    )


async def fetch_bid_notices(
    *,
    days: int = 14,
    now: datetime | None = None,
    max_items: int = 600,
    operation: str = OP_BID_LIST_SERVC,
) -> list[dict[str, Any]]:
    """최근 days일 창을 **뒤 페이지부터** 훑어 item 목록을 모은다 (원문 dict 그대로).

    ## 이 함수는 더 이상 기본 수집 경로가 아니다 (0920.md §4-A-1)

    기본은 `collect_notices()`(공고명 키워드 조회)다. 이 함수는 「창을 통째로 보고 싶다」는
    선택 경로(`--full-window`)로 남겨 둔다. (2.8.1) 조달청 조회 기간 상한(`MAX_WINDOW_DAYS` · 시작일 포함 7일) 때문에
    `days` 가 7을 넘으면 거절된다 — 이 경로는 창을 나누지 않는다(기본 경로만 나눈다).

    ## 예전 독스트링이 적어 둔 가정은 **틀렸다**

    여기에는 「나라장터는 공고게시일 오름차순으로 주니 마지막 페이지가 최신이다」라고 적혀
    있었다. 2026-09-17 에 30일 창 129페이지를 순서대로 받아 확인한 실제 정렬은 이렇다
    (docs/reports/2026-09-20_qa_recheck5.md §1-3):

        1 ~ 9,078번        일반용역   08-18 → 09-17 오름차순
        9,079 ~ 12,805번   기술용역   08-18 → 09-17 오름차순(다시 시작)
        마지막 2건         일반용역(리스)

    즉 **용역구분 → 게시일** 순이다. 「마지막 600건」은 기술용역 꼬리이고, AI 교육·컨설팅
    공고는 전부 **일반용역**이라 이 경로로는 구조적으로 들어오지 않는다. 캐시 108건이
    내진성능평가·설계·감리·안전점검으로 채워져 있던 이유가 이것이다 — 마감 전 후보 117건 중
    앱이 아는 것은 4건뿐이었다.

    창을 넓혀도 소용없다. 창이 넓을수록 기술용역 꼬리만 더 깊게 본다.

    ## 그래도 뒤에서부터 받는 이유

    한 용역구분 **안에서는** 게시일 오름차순이 맞다. 그래서 이 경로를 쓸 때는 여전히 뒤
    페이지가 그 구분의 최신이다. 동작은 그대로 두고 기대만 바로잡는다.
    totalCount 를 못 읽으면 앞에서부터 모은다(동작이 멈추지는 않게).
    """
    end = now or storage.utc_now().astimezone(KST)
    begin = end - timedelta(days=days)

    first = await fetch_bid_notices_raw(begin=begin, end=end, page_no=1, operation=operation)
    total = _total_count_of(first)
    first_items = _items_of(first)

    # totalCount 를 못 읽거나 한 페이지로 끝나면 그대로 돌려준다.
    if total is None or total <= MAX_ROWS_PER_PAGE:
        return first_items[:max_items]

    last_page = (total + MAX_ROWS_PER_PAGE - 1) // MAX_ROWS_PER_PAGE
    collected: list[dict[str, Any]] = []
    failures = 0
    for offset in range(MAX_PAGES):
        page = last_page - offset
        if page < 1 or len(collected) >= max_items:
            break
        if page == 1:
            collected.extend(first_items)
            continue
        try:
            body = await fetch_bid_notices_raw(
                begin=begin, end=end, page_no=page, operation=operation
            )
        except G2BClientError:
            # 뒤쪽 페이지는 응답이 느려 가끔 끊긴다. 한 페이지 때문에 수집 전체를 버리지 않는다 —
            # 이미 모은 최신 공고만으로도 화면은 의미가 있다. 연속으로 실패하면 그만둔다.
            failures += 1
            logger.warning("나라장터 %d페이지 수집 실패 (누적 %d회) — 모은 것까지만 쓴다", page, failures)
            if failures >= MAX_PAGE_FAILURES:
                break
            continue
        collected.extend(_items_of(body))

    # 한 건도 못 모았으면 캐시로 넘어가도록 오류를 올린다 (조용히 빈 목록을 주지 않는다).
    if not collected:
        raise G2BClientError("나라장터 목록을 한 페이지도 받지 못했습니다.")
    return collected[:max_items]
