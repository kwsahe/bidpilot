"""나라장터 API client 테스트 (네트워크 없음).

핵심 계약
    - 공공데이터포털이 주는 두 형태(Encoding / Decoding) 중 무엇을 넣어도 동작해야 한다.
      인코딩된 키를 그대로 쓰면 httpx가 한 번 더 인코딩해 %2F가 %252F가 되고 403이 난다
      (실측: 키 교체 직후 403 Forbidden).
    - 서비스키는 오류 메시지에 절대 남지 않는다 (CLAUDE.md 21).
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import g2b_client


# --------------------------------------------------------------------------
# 서비스키 형태 정규화
# --------------------------------------------------------------------------


def test_원본_키는_그대로_쓴다() -> None:
    """Decoding 키는 base64라 %가 없다. 건드리지 않는다."""
    raw = "jZTHxMRti/E5qLjIMQ5G0q0iijWQ1gRC4dhZE2xsDorQ+Co9wCjZdG5OHV1zj0ypIMJKo="
    assert g2b_client.normalize_service_key(raw) == raw


def test_인코딩된_키는_한_번_풀어_쓴다() -> None:
    """Encoding 키를 그대로 보내면 %2F가 %252F로 이중 인코딩된다."""
    encoded = "jZTHxMRti%2FE5qLjIMQ5G%2B0q0i%3D"
    assert g2b_client.normalize_service_key(encoded) == "jZTHxMRti/E5qLjIMQ5G+0q0i="


def test_정규화는_두_번_해도_같은_결과다() -> None:
    encoded = "abc%2Fdef%3D"
    once = g2b_client.normalize_service_key(encoded)
    assert g2b_client.normalize_service_key(once) == once


@pytest.mark.parametrize("key", ["", "plainkey", "a+b/c="])
def test_퍼센트가_없으면_그대로_둔다(key: str) -> None:
    assert g2b_client.normalize_service_key(key) == key


# --------------------------------------------------------------------------
# 오류 메시지에 키를 남기지 않는다
# --------------------------------------------------------------------------


def test_오류_메시지에서_원본_키를_지운다() -> None:
    key = "SECRET/KEY+VALUE="
    message = f"401 for url https://apis.data.go.kr/x?serviceKey={key}&pageNo=1"
    redacted = g2b_client._redact(message, key)
    assert key not in redacted
    assert "<KEY>" in redacted


def test_오류_메시지에서_인코딩된_키도_지운다() -> None:
    """httpx 예외 문자열에는 URL 인코딩된 형태로 들어온다."""
    key = "SECRET/KEY+VALUE="
    encoded = "SECRET%2FKEY%2BVALUE%3D"
    message = f"403 Forbidden for url http://apis.data.go.kr/x?serviceKey={encoded}"
    redacted = g2b_client._redact(message, key)
    assert encoded not in redacted
    assert "<KEY>" in redacted


def test_키가_없는_메시지는_그대로_둔다() -> None:
    message = "connection timed out"
    assert g2b_client._redact(message, "SECRET") == message


def test_HTML_안내_화면은_쉬운_글로_서비스키_XML_은_원문으로() -> None:
    """11-01 — 「시스템 점검 안내」 HTML 앞부분이 사업기회 띠에 그대로 떴다. XML 오류는 원인 풀이가 원문을 읽으므로 둔다."""
    from app.services import auto_collect

    page = '<!DOCTYPE html>\r\n<html lang="ko">\r\n<head>\r\n<meta charset="UTF-8">\r\n<title>시스템 점검 안내</title>'
    message = g2b_client._non_json_message(page, "SECRET")
    assert message == "조달청(나라장터)이 목록 대신 안내 화면을 보냈습니다 — 「시스템 점검 안내」"
    assert "<" not in message and "non-JSON" not in message
    assert "시스템 점검" in (auto_collect.failure_hint(message) or "")
    plain = g2b_client._non_json_message("<html><body>bad gateway</body></html>", "SECRET")
    assert plain == "조달청(나라장터)이 목록 대신 안내 화면을 보냈습니다"
    assert "안내 화면" in (auto_collect.failure_hint(plain) or "")

    xml = "<OpenAPI_ServiceResponse><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg> SECRET"
    raw = g2b_client._non_json_message(xml, "SECRET")
    assert raw.startswith("G2B API returned non-JSON response: <OpenAPI_ServiceResponse>")
    assert "SECRET" not in raw and "<KEY>" in raw
    assert "서비스키" in (auto_collect.failure_hint(raw) or "")


def test_HTTP_오류는_포털_오류_코드를_남기고_주소는_뺀다() -> None:
    """11-01 — 하루 한도 초과가 HTTP 429 + JSON 봉투로 왔다. raise_for_status 글만 올려 띠에 영어 URL 이 뜨고
    「하루 호출 한도」 풀이도 붙지 않았다."""
    import httpx

    from app.services import auto_collect

    request = httpx.Request("GET", "https://apis.data.go.kr/1230000/ad/x?serviceKey=SECRET")
    body = (
        '{ "OpenAPI_ServiceResponse": { "cmmMsgHeader": { "errMsg": "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",'
        ' "returnAuthMsg": "일일 서비스 요청제한 횟수 초과 에러", "returnReasonCode": "22" } } }'
    )
    message = g2b_client._status_message(httpx.Response(429, text=body, request=request))
    assert message == "공공데이터포털이 나라장터 호출을 막았습니다(HTTP 429 · 일일 서비스 요청제한 횟수 초과 에러 · LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR)"
    assert "하루 호출 한도" in (auto_collect.failure_hint(message) or "")
    plain = g2b_client._status_message(httpx.Response(503, text="<html>busy</html>", request=request))
    assert plain == "조달청(나라장터) API 가 오류를 돌려줬습니다(HTTP 503)"
    assert "SECRET" not in message + plain and "http" not in plain.lower().replace("(http 503)", "")


_REAL_ASYNC_GET = __import__("httpx").AsyncClient.get  # conftest 가 막기 전 진짜 구현(가짜 transport 로만 부른다)


def test_두_호출_함수가_HTTP_오류를_포털_글로_올린다(monkeypatch: pytest.MonkeyPatch) -> None:
    """11-01 독립 검토 — `_status_message` 만 시험하면 두 호출 함수의 `except HTTPStatusError` 가 빠져도 몰랐다."""
    from datetime import datetime

    import httpx

    body = '{"OpenAPI_ServiceResponse":{"cmmMsgHeader":{"errMsg":"LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR","returnReasonCode":"22"}}}'
    original_init = httpx.AsyncClient.__init__

    def with_mock(self: httpx.AsyncClient, *args: object, **kwargs: object) -> None:
        kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(429, text=body, request=request))  # type: ignore[assignment]
        original_init(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx.AsyncClient, "__init__", with_mock)
    monkeypatch.setattr(httpx.AsyncClient, "get", _REAL_ASYNC_GET)
    monkeypatch.setattr(g2b_client, "_require_key", lambda: "SECRET-KEY-1")
    calls = [
        g2b_client.fetch_bid_notices_raw(begin=datetime(2026, 10, 1), end=datetime(2026, 11, 1)),
        g2b_client._ao_page(g2b_client.PRESPEC_SERVICE, g2b_client.OP_PRESPEC_LIST, {}),
    ]
    for call in calls:
        with pytest.raises(g2b_client.G2BClientError) as caught:
            asyncio.run(call)
        text = str(caught.value)
        assert text.startswith("공공데이터포털이 나라장터 호출을 막았습니다(HTTP 429 · LIMITED_NUMBER"), text
        assert "SECRET-KEY-1" not in text and "apis.data.go.kr" not in text


# ---------------------------------------------------------------------------
# 조회 창 순회 — 기본이 아닌 선택 경로 (0920.md §4-A-1)
# ---------------------------------------------------------------------------
#
# 이 경로는 더 이상 기본 수집기가 아니다. 기본은 `collect_notices`(공고명 키워드 조회)이고,
# 여기 테스트들은 「그래도 이 함수를 쓰면 이렇게 돈다」를 고정한다.
#
# 이 함수의 옛 설명은 「나라장터가 공고게시일 오름차순으로 주니 마지막 페이지가 최신」이라고
# 단정했다. **틀린 가정이었다.** 실제 정렬은 «용역구분 → 게시일» 이라 마지막 600건은 기술용역
# 꼬리이고, AI 교육·컨설팅 공고(전부 일반용역)는 이 경로로 한 건도 들어오지 않았다
# (docs/reports/2026-09-20_qa_recheck5.md §1-3, ISSUE-072).


def test_fetch_collects_newest_pages_first() -> None:
    """한 용역구분 **안에서는** 게시일 오름차순이 맞다 — 그 안에서 뒤 페이지가 최신이다.

    동작(뒤 페이지부터 모은다)은 그대로 두고, 「그러면 창의 최신 공고를 다 본다」는 기대만
    거둬들였다. 창 전체의 최신을 보려면 키워드 조회(`collect_notices`)를 쓴다.
    """
    pages: dict[int, list[dict[str, str]]] = {
        p: [{"bidNtceNo": f"P{p}-{i}"} for i in range(100)] for p in range(1, 6)
    }

    calls: list[int] = []

    async def fake_raw(*, begin, end, page_no=1, num_rows=100, operation="", extra_params=None):
        calls.append(page_no)
        return {"totalCount": 500, "items": pages[page_no]}

    original = g2b_client.fetch_bid_notices_raw
    g2b_client.fetch_bid_notices_raw = fake_raw  # type: ignore[assignment]
    try:
        items = asyncio.run(g2b_client.fetch_bid_notices(days=14, max_items=200))
    finally:
        g2b_client.fetch_bid_notices_raw = original  # type: ignore[assignment]

    # 마지막 페이지부터 받았는지 (그 용역구분 안에서의 최신)
    assert calls[0] == 1, "totalCount 를 읽기 위해 1페이지를 먼저 본다"
    assert calls[1] == 5 and calls[2] == 4, f"최신 페이지부터 거꾸로 받아야 한다: {calls}"
    assert [i["bidNtceNo"] for i in items[:2]] == ["P5-0", "P5-1"]
    assert len(items) == 200


def test_fetch_survives_a_failing_page() -> None:
    """뒤쪽 페이지는 응답이 느려 가끔 끊긴다 — 한 페이지 때문에 수집 전체를 버리지 않는다."""

    async def flaky_raw(*, begin, end, page_no=1, num_rows=100, operation="", extra_params=None):
        if page_no == 5:
            raise g2b_client.G2BClientError("timeout")
        return {"totalCount": 500, "items": [{"bidNtceNo": f"P{page_no}-0"}]}

    original = g2b_client.fetch_bid_notices_raw
    g2b_client.fetch_bid_notices_raw = flaky_raw  # type: ignore[assignment]
    try:
        items = asyncio.run(g2b_client.fetch_bid_notices(days=14, max_items=200))
    finally:
        g2b_client.fetch_bid_notices_raw = original  # type: ignore[assignment]

    assert items, "일부 페이지가 실패해도 모은 것은 돌려준다"
    assert all(i["bidNtceNo"] != "P5-0" for i in items)


def test_fetch_raises_when_nothing_collected() -> None:
    """한 건도 못 모으면 조용히 빈 목록을 주지 않고 오류를 올린다 (캐시로 넘어가야 한다)."""

    async def always_fail(*, begin, end, page_no=1, num_rows=100, operation="", extra_params=None):
        if page_no == 1:
            return {"totalCount": 500, "items": []}
        raise g2b_client.G2BClientError("down")

    original = g2b_client.fetch_bid_notices_raw
    g2b_client.fetch_bid_notices_raw = always_fail  # type: ignore[assignment]
    try:
        with pytest.raises(g2b_client.G2BClientError):
            asyncio.run(g2b_client.fetch_bid_notices(days=14, max_items=200))
    finally:
        g2b_client.fetch_bid_notices_raw = original  # type: ignore[assignment]
