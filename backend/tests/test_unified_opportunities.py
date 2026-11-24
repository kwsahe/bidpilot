"""통합 사업기회(나라장터 + 기업마당) · 회사 기준 검토 우선순위 · 지원사업 신청 분석 테스트.

네트워크와 실제 인증키를 절대 쓰지 않는다.
- 기업마당 호출은 `bizinfo_client.is_configured` / `fetch_programs_raw` / `httpx.AsyncClient.get` 을 monkeypatch 로 대체한다.
- 인증키는 테스트 안에서 만든 가짜 값(`_FAKE_KEY`)만 쓰며, 응답·캐시·예외 메시지에 새어 나오지 않는지 검사한다.
- 기업마당 응답은 tests/fixtures/bizinfo_sample_response.json (실응답 **구조**만 본뜬 가짜 값).

여기서 검증하는 계약:
- company_priority_score 는 "회사 기준 검토 우선순위"다. 낙찰확률·선정확률이 아니다.
- score=None 은 미확인이며 0점이 아니다 (정규화 분모에서 빠진다).
- 한쪽 출처가 실패해도 다른 쪽은 살아 있고 source_errors 에 사유가 남는다.
- 지원사업 화면 용어는 입찰 용어와 섞이지 않는다.

14차부터 실호출은 **기본이 꺼짐**이다(ISSUE-120). 그래서 「기업마당을 부르고 그 결과가
목록·상세에 실린다」를 재는 테스트는 `live_fetch_on` 을 인자로 받아 **자기가 켰다고 말한다** —
서명만 봐도 「이건 부르는 쪽을 재는 테스트」임이 보인다. 켜지 않은 테스트는 저장된 것만 보며,
그 쪽이 재는 것(매핑·점수 계산·정렬)은 실호출과 무관하다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.schemas.business_opportunity import NextRoute, PriorityComponent, UnifiedOpportunity
from app.schemas.organization import (
    AnalysisContext,
    OrganizationCreateRequest,
    OrganizationProfileUpdate,
)
from app.schemas.procurement import ProcurementNotice
from app.services import eligibility_engine  # noqa: F401
from app.services import (
    bizinfo_client,
    bizinfo_service,
    opportunity_priority as priority,
    opportunity_service,
    organization_service,
    procurement_service,
)
from app.services.opportunity_filter import classify

client = TestClient(app)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "bizinfo_sample_response.json"

# 테스트 안에서만 쓰는 가짜 인증키. 실제 키를 쓰지 않는다는 것을 코드로 못박는다.
_FAKE_KEY = "TEST-FAKE-BIZINFO-KEY-0000"

# 기업마당 화면에서 쓰지 않기로 한 말 (입찰 용어). 지원사업은 신청 흐름이다.
FORBIDDEN_BID_WORDS: tuple[str, ...] = ("입찰", "낙찰", "투찰", "RFP", "수주확률")

ALPHA = "org-test-alpha"
BETA = "org-test-beta"

# 고정 시각 — 마감·일정 점수가 실제 오늘 날짜에 흔들리지 않게 한다.
NOW = datetime(2026, 9, 8, 3, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 8)


# --------------------------------------------------------------------------
# 공통 헬퍼
# --------------------------------------------------------------------------


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def fixture_items() -> list[dict[str, Any]]:
    return load_fixture()["jsonArray"]


def item_by_id(program_id: str) -> dict[str, Any]:
    return next(i for i in fixture_items() if i.get("pblancId") == program_id)


class _FakeResponse:
    """httpx.Response 흉내 — 기업마당은 오류도 HTTP 200 으로 준다."""

    def __init__(self, payload: Any, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


def stub_http_get(monkeypatch: pytest.MonkeyPatch, payload: Any, *, calls: list[dict[str, Any]] | None = None) -> None:
    """conftest 의 네트워크 차단을 이 테스트에서만 가짜 응답으로 대체한다 (실제 소켓은 열리지 않는다)."""

    async def _get(self: Any, url: Any, *args: Any, **kwargs: Any) -> _FakeResponse:
        if calls is not None:
            calls.append({"url": str(url), "params": dict(kwargs.get("params") or {})})
        return _FakeResponse(payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", _get)


@pytest.fixture()
def fake_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """설정의 인증키를 가짜 값으로 고정한다 (.env 의 실제 키가 테스트에 새어 들어오지 않게)."""
    monkeypatch.setattr(get_settings(), "bizinfo_api_key", _FAKE_KEY)
    return _FAKE_KEY


@pytest.fixture()
def bizinfo_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """기업마당 캐시를 tmp 로 돌린다. 저장소의 실제 캐시를 읽거나 덮어쓰지 않는다."""
    path = tmp_path / "bizinfo" / "bizinfo_cache.json"
    monkeypatch.setattr(bizinfo_service, "CACHE_FILE", path)
    return path


@pytest.fixture()
def bizinfo_from_fixture(bizinfo_cache: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """기업마당 실호출을 fixture 응답으로 대체한다 (키가 있는 것처럼 동작)."""
    body = load_fixture()

    async def _fetch(**_kwargs: Any) -> dict[str, Any]:
        return body

    monkeypatch.setattr(bizinfo_client, "is_configured", lambda: True)
    monkeypatch.setattr(bizinfo_client, "fetch_programs_raw", _fetch)
    return bizinfo_cache


def make_notice(nid: str, title: str, *, agency: str = "가상광주광역시청", region: str | None = "광주광역시", budget: int | None = 50_000_000, deadline: datetime | None = None) -> ProcurementNotice:
    return ProcurementNotice(
        id=nid,
        notice_no=nid,
        title=title,
        agency=agency,
        published_at=NOW - timedelta(days=3),
        deadline_at=deadline if deadline is not None else NOW + timedelta(days=20),
        budget=budget,
        region=region,
        description=f"{title} 과업 개요(가상)",
    )


def procurement_result(notices: list[ProcurementNotice], *, source: str = "cached") -> procurement_service.ProcurementResult:
    views = [procurement_service.NoticeView(notice=n, match=classify(n)) for n in notices]
    return procurement_service.ProcurementResult(source=source, notices=views, fetched_at=NOW, total_fetched=len(views))


def stub_procurements(monkeypatch: pytest.MonkeyPatch, notices: list[ProcurementNotice] | None = None, *, error: Exception | None = None) -> None:
    async def _list(**_kwargs: Any) -> procurement_service.ProcurementResult:
        if error is not None:
            raise error
        return procurement_result(notices or [])

    monkeypatch.setattr(procurement_service, "list_ai_candidates", _list)


def make_organizations() -> None:
    """사업영역·지역이 다른 두 회사. 같은 공고를 서로 다르게 보는지 확인하는 데 쓴다."""
    organization_service.create_organization(
        OrganizationCreateRequest(organization_id=ALPHA, display_name="가상 AI교육 컴퍼니", data_class="synthetic", created_by="테스트")
    )
    organization_service.save_profile(
        ALPHA,
        OrganizationProfileUpdate(
            name="가상 AI교육 컴퍼니",
            business_domains=["생성형 AI 교육", "AI 컨설팅", "업무자동화 교육"],
            target_clients=["공공기관", "중소기업"],
            preferred_regions=["광주광역시", "전라남도"],
            certifications=["AI 교육 운영"],
            data_class="synthetic",
            updated_by="테스트",
        ),
    )
    organization_service.create_organization(
        OrganizationCreateRequest(organization_id=BETA, display_name="가상 제조설비 컴퍼니", data_class="synthetic", created_by="테스트")
    )
    organization_service.save_profile(
        BETA,
        OrganizationProfileUpdate(
            name="가상 제조설비 컴퍼니",
            business_domains=["스마트공장 구축", "제조 설비 자동화"],
            target_clients=["제조기업"],
            preferred_regions=["부산광역시"],
            certifications=[],
            data_class="synthetic",
            updated_by="테스트",
        ),
    )


@pytest.fixture()
def organizations() -> Iterator[None]:
    make_organizations()
    yield


async def list_for(organization_id: str, **kwargs: Any):
    """목록을 부른다.

    **기본으로 「불가」까지 함께 받는다** (0921 §4-C-2). 운영 화면은 불가를 숨기지만,
    여기 테스트 대부분은 「불가 판정이 제대로 실려 나가는가」를 재기 때문에 숨기면 잴 것이
    사라진다. 숨기는 동작 자체는 `test_불가는_기본으로_숨긴다` 가 따로 잰다.
    """
    context = AnalysisContext(organization_id=organization_id, evidence_scope="internal")
    params: dict[str, Any] = {"now": NOW, "include_blocked": True}
    params.update(kwargs)
    return await opportunity_service.list_opportunities(context=context, **params)


def score_of(listing, program_id: str) -> int | None:
    return next(i for i in listing.items if i.id == program_id).company_priority_score


def rank_of(listing, program_id: str) -> int:
    return next(i for i in listing.items if i.id == program_id).priority_rank


def iter_strings(node: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from iter_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from iter_strings(value, f"{path}[{index}]")
    elif isinstance(node, str):
        yield path, node


# ==========================================================================
# A. 기업마당 클라이언트 — 인증키 취급 · 응답 형태
# ==========================================================================


@pytest.mark.anyio
async def test_api_key_presence_is_reported_but_value_never_is(fake_key: str, bizinfo_cache: Path, live_fetch_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """지시서 1항 — 키가 설정됐는지 여부(bool)만 밖으로 나가고 값은 어디에도 나오지 않는다."""
    monkeypatch.setattr(bizinfo_client, "is_configured", lambda: False)
    without = await bizinfo_service.list_programs()
    assert without.bizinfo_api_configured is False
    assert without.source == "sample"

    async def _fetch(**_kwargs: Any) -> dict[str, Any]:
        return load_fixture()

    monkeypatch.setattr(bizinfo_client, "is_configured", lambda: True)
    monkeypatch.setattr(bizinfo_client, "fetch_programs_raw", _fetch)
    with_key = await bizinfo_service.list_programs(refresh=True)
    assert with_key.bizinfo_api_configured is True
    assert with_key.source == "bizinfo"

    for listing in (without, with_key):
        dumped = json.dumps(listing.model_dump(mode="json"), ensure_ascii=False)
        assert _FAKE_KEY not in dumped
        assert "crtfcKey" not in dumped


@pytest.mark.anyio
async def test_client_sends_key_as_param_only(fake_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """호출에는 인증키가 실리지만(필수), 반환 본문에는 남지 않는다."""
    calls: list[dict[str, Any]] = []
    stub_http_get(monkeypatch, load_fixture(), calls=calls)
    body = await bizinfo_client.fetch_programs_raw(count=7)
    assert calls and calls[0]["params"]["crtfcKey"] == _FAKE_KEY
    assert calls[0]["params"]["dataType"] == "json" and calls[0]["params"]["searchCnt"] == 7
    assert "crtfcKey" not in json.dumps(body, ensure_ascii=False)
    # URL 문자열에도 키가 붙어 있지 않다 (params 로만 전달).
    assert _FAKE_KEY not in calls[0]["url"]


@pytest.mark.anyio
async def test_count_is_clamped_to_max(fake_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    stub_http_get(monkeypatch, {"jsonArray": []}, calls=calls)
    await bizinfo_client.fetch_programs_raw(count=99_999)
    assert calls[0]["params"]["searchCnt"] == bizinfo_client.MAX_COUNT


def test_map_program_fills_every_documented_field() -> None:
    """지시서 2항 — 문서 필드 12개 + 신청 흐름 필드가 전부 채워진다."""
    program = bizinfo_service.map_program(item_by_id("PBLN_TEST_000000000001"))
    assert program is not None

    # 문서화된 12개 필드
    assert program.id == "bizinfo-PBLN_TEST_000000000001"          # pblancId
    assert program.title == "(가상) 광주 중소기업 생성형 AI 활용 실무교육 지원사업"  # pblancNm
    assert program.agency == "가상광주광역시청"                       # jrsdInsttNm
    assert program.executing_agency == "가상광주테크노파크"            # excInsttNm
    assert program.summary is not None and "생성형 AI" in program.summary  # bsnsSumryCn
    assert program.apply_period_text == "20260901 ~ 20260930"        # reqstBeginEndDe
    assert program.apply_start == date(2026, 9, 1) and program.apply_end == date(2026, 9, 30)
    assert program.category == "인력"                                # pldirSportRealmLclasCodeNm
    assert program.subcategory == "교육"                             # pldirSportRealmMlsfcCodeNm
    assert program.hashtags == ["AI", "교육", "광주", "바우처"]        # hashtags
    assert program.target == "중소기업"                              # trgetNm
    # 0921 §4-A-4 — 지역 태그와 「☞」 대상 문장을 정규 필드로 남긴다.
    # 「광주」 해시태그는 통합 이름 「전남광주」 하나로 접힌다 — 같은 지역을 두 이름으로
    # 세면 회사 소재지와 대조할 때 어긋난다.
    assert program.region_tags == ["전남광주"]
    assert program.requirement_sentences == ["광주광역시에 본사를 둔 중소기업", "창업 7년 이내 기업"]
    assert program.url == "https://www.example.invalid/bizinfo/test-000000000001"  # pblancUrl
    assert program.created_at == datetime(2026, 9, 7, 14, 24, tzinfo=bizinfo_service.KST)  # creatPnttm

    # 신청 흐름 필드
    assert program.updated_at == datetime(2026, 9, 8, 9, 10, tzinfo=bizinfo_service.KST)   # updtPnttm
    assert program.apply_method is not None and "사업계획서" in program.apply_method        # reqstMthPapersCn
    assert program.contact is not None and "02-1234-5678" in program.contact               # refrncNm
    assert program.reception_url == "https://www.example.invalid/apply/test-000000000001"  # rceptEngnHmpgUrl
    assert len(program.attachments) == 2

    # 하나도 None 으로 비어 있지 않다.
    empty = [k for k, v in program.model_dump().items() if v in (None, [], "")]
    assert empty == [], f"비어 있는 필드: {empty}"


def test_attachment_kinds_follow_field_names() -> None:
    """지시서 6항 — fileNm/flpthNm 는 신청 서식(form), printFileNm/printFlpthNm 는 공고문(notice)."""
    program = bizinfo_service.map_program(item_by_id("PBLN_TEST_000000000001"))
    assert program is not None
    by_kind = {a.kind: a for a in program.attachments}
    assert by_kind["form"].name == "가상_신청서식.hwp"
    assert by_kind["form"].url == "https://www.example.invalid/files/form-000000000001.hwp"
    assert by_kind["notice"].name == "가상_공고문.pdf"
    assert by_kind["notice"].url == "https://www.example.invalid/files/notice-000000000001.pdf"

    # 이름이나 주소 한쪽만 있으면 첨부로 만들지 않는다 (없는 링크를 지어내지 않는다).
    partial = bizinfo_service.map_program({"pblancId": "X1", "pblancNm": "이름만 있는 첨부", "fileNm": "서식.hwp"})
    assert partial is not None and partial.attachments == []
    # 첨부가 아예 없는 항목도 정상 매핑된다.
    plain = bizinfo_service.map_program(item_by_id("PBLN_TEST_000000000002"))
    assert plain is not None and plain.attachments == []
    assert plain.url == "https://www.example.invalid/bizinfo/test-000000000002"


@pytest.mark.parametrize(
    ("raw", "start", "end", "kind"),
    [
        ("20260901 ~ 20260930", date(2026, 9, 1), date(2026, 9, 30), "dated"),
        ("2026-09-01~2026-09-30", date(2026, 9, 1), date(2026, 9, 30), "dated"),
        ("상시 접수", None, None, "always_open"),
        ("예산 소진시까지", None, None, "until_budget"),
        ("모집 마감시", None, None, "conditional"),
        ("선착순 접수", None, None, "conditional"),
        ("지원내용별 상이", None, None, "unknown"),
    ],
)
def test_apply_period_variants(raw: str, start: date | None, end: date | None, kind: str) -> None:
    """지시서 5항 — 날짜가 아닌 문구도 성격을 남긴다. '마감일 없음'으로 뭉뚱그리지 않는다."""
    program = bizinfo_service.map_program({"pblancId": "P", "pblancNm": "기간 형식 확인", "reqstBeginEndDe": raw})
    assert program is not None
    assert program.apply_start == start
    assert program.apply_end == end
    assert program.apply_period_kind == kind
    # 원문 문구는 언제나 그대로 남는다.
    assert program.apply_period_text == raw


def test_items_without_required_fields_are_dropped() -> None:
    """지시서 7항 — pblancId 나 pblancNm 이 없으면 항목으로 만들지 않는다."""
    for item in fixture_items():
        program = bizinfo_service.map_program(item)
        if item.get("pblancId") and item.get("pblancNm"):
            assert program is not None
        else:
            assert program is None

    assert bizinfo_service.map_program({"pblancNm": "id 없음"}) is None
    assert bizinfo_service.map_program({"pblancId": "이름 없음"}) is None
    assert bizinfo_service.map_program({"pblancId": "  ", "pblancNm": "  "}) is None


@pytest.mark.anyio
async def test_empty_response_yields_zero_items(fake_key: str, bizinfo_cache: Path, live_fetch_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """지시서 3항 — 빈 결과({"jsonArray": []})는 예외가 아니라 0건이다."""
    monkeypatch.setattr(bizinfo_client, "is_configured", lambda: True)
    stub_http_get(monkeypatch, {"jsonArray": []})

    body = await bizinfo_client.fetch_programs_raw()
    assert bizinfo_client.extract_items(body) == []
    assert bizinfo_client.total_count([]) is None

    listing = await bizinfo_service.list_programs(refresh=True)
    assert listing.source == "bizinfo"
    assert listing.count == 0 and listing.items == []
    assert listing.error is None


@pytest.mark.anyio
async def test_req_err_raises_even_on_http_200(fake_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """지시서 4항 — 인증 오류는 HTTP 200 으로 온다. 조용히 빈 목록이 되면 안 된다."""
    stub_http_get(monkeypatch, {"reqErr": "존재하지 않는 인증키 입니다."})
    with pytest.raises(bizinfo_client.BizinfoError) as exc_info:
        await bizinfo_client.fetch_programs_raw()
    message = str(exc_info.value)
    assert "인증키" in message
    # 예외 메시지에 실제 키 값이 실리지 않는다.
    assert _FAKE_KEY not in message


@pytest.mark.anyio
async def test_req_err_does_not_become_an_empty_list(fake_key: str, bizinfo_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """오류 응답을 받은 목록 조회는 '0건 성공'이 아니라 합성 샘플 + 오류 사유로 떨어진다."""
    monkeypatch.setattr(bizinfo_client, "is_configured", lambda: True)
    stub_http_get(monkeypatch, {"reqErr": "존재하지 않는 인증키 입니다."})
    listing = await bizinfo_service.list_programs(refresh=True)
    assert listing.source == "sample"  # 실제 데이터가 아니라는 것이 출처로 드러난다
    assert listing.error and "인증" in listing.error
    assert _FAKE_KEY not in (listing.error or "")


def test_extract_items_ignores_non_dict_rows() -> None:
    assert bizinfo_client.extract_items({"jsonArray": [{"pblancId": "A"}, "쓰레기", 3]}) == [{"pblancId": "A"}]
    assert bizinfo_client.extract_items({}) == []
    assert bizinfo_client.total_count(fixture_items()) == 1520


@pytest.mark.anyio
async def test_api_key_never_reaches_cache_or_errors(fake_key: str, bizinfo_from_fixture: Path, live_fetch_on: None) -> None:
    """지시서 15항 — 인증키는 캐시 payload·오류 문자열 어디에도 남지 않는다."""
    await bizinfo_service.list_programs(refresh=True)
    assert bizinfo_from_fixture.exists()
    raw = bizinfo_from_fixture.read_text(encoding="utf-8")
    assert _FAKE_KEY not in raw
    payload = json.loads(raw)
    # 캐시 payload 최상위 키에 인증키 관련 항목이 없다.
    assert "crtfcKey" not in payload and "bizinfo_api_key" not in payload
    assert set(payload) >= {"fetched_at", "total_fetched", "items"}
    for row in payload["items"]:
        assert "crtfcKey" not in row

    # _redact 는 키가 섞인 문자열을 가린다.
    assert bizinfo_client._redact(f"https://x/?crtfcKey={_FAKE_KEY}&a=1") == "https://x/?crtfcKey=***&a=1"


def test_mask_contacts_hides_email_and_phone() -> None:
    """지시서 16항 — 공개 스냅샷용 마스킹."""
    raw = "가상지원센터 교육운영팀 02-1234-5678 / test-contact@example.invalid"
    masked = bizinfo_service.mask_contacts(raw)
    assert masked is not None
    assert "02-1234-5678" not in masked and "test-contact@example.invalid" not in masked
    assert "[전화 원문 확인]" in masked and "[이메일 원문 확인]" in masked
    assert "가상지원센터 교육운영팀" in masked  # 기관·부서명은 남는다
    assert bizinfo_service.mask_contacts("061-000-0000") == "[전화 원문 확인]"
    assert bizinfo_service.mask_contacts(None) is None
    assert bizinfo_service.mask_contacts("연락처 없음") == "연락처 없음"


# ==========================================================================
# B. 우선순위 점수 규칙 (배점 · 정규화 · 자격 상한)
# ==========================================================================


def test_priority_weights_match_the_agreed_scale() -> None:
    """배점은 합 100이고 항목별 값이 고정돼 있다 (CLAUDE.md §12 · 0922 §4-B).

    **「일정 여유」가 빠지고 「규모 적합도」가 들어왔다.** 마감은 적합도가 아니라 긴급도이고,
    그것이 배점에 있으면 키워드가 맞는 공고끼리는 마감 순서가 곧 순위가 된다(ISSUE-083).
    """
    assert priority.PRIORITY_WEIGHTS == {"domain": 35, "eligibility": 25, "evidence": 20, "scale": 10, "strategic": 10}
    assert "schedule" not in priority.PRIORITY_WEIGHTS
    assert sum(priority.PRIORITY_WEIGHTS.values()) == 100
    assert set(priority.PRIORITY_LABELS) == set(priority.PRIORITY_WEIGHTS)


def _component(key: str, score: float | None) -> PriorityComponent:
    return PriorityComponent(key=key, label=priority.PRIORITY_LABELS[key], weight=priority.PRIORITY_WEIGHTS[key], score=score, reason="테스트")


def test_missing_scores_are_not_treated_as_zero() -> None:
    """지시서 13항 — score=None 은 미확인이다. 분모에서 빠지며, 전부 None 이면 결과도 None 이다."""
    # domain 만 만점, 나머지 미확인 → 0.35 로 깎이지 않고 100 이 된다.
    only_domain = [_component("domain", 1.0), _component("eligibility", None), _component("evidence", None), _component("scale", None), _component("strategic", None)]
    assert priority.normalize(only_domain) == 100

    # 미확인을 0점으로 계산했다면 나올 값(35)과 다르다는 것을 못박는다.
    assert priority.normalize(only_domain) != 35

    mixed = [_component("domain", 1.0), _component("eligibility", 0.0), _component("evidence", None), _component("scale", None), _component("strategic", None)]
    assert priority.normalize(mixed) == round(100 * 35 / 60)

    all_unknown = [_component(key, None) for key in priority.PRIORITY_WEIGHTS]
    assert priority.normalize(all_unknown) is None  # 0 이 아니다
    assert priority.normalize([]) is None

    # 계산된 배점이 적으면 신뢰도가 떨어진다.
    assert priority.confidence_of(only_domain, source="bizinfo") == "low"
    assert priority.confidence_of([_component(key, 0.5) for key in priority.PRIORITY_WEIGHTS], source="bizinfo") == "high"
    assert priority.confidence_of([_component(key, 0.5) for key in priority.PRIORITY_WEIGHTS], source="sample") == "low"

    # 점수 미확인은 '미확인'이지 '후순위'도 '마감'도 아니다 (ISSUE-041).
    # 뒤로 보낸 것과 아직 재지 못한 것은 담당자에게 다른 뜻이다.
    assert priority.label_of(None, closed=False) == "미확인"
    assert priority.label_of(None, closed=True) == "마감"
    assert priority.label_of(100, closed=True) == "마감"


def test_지역_칸이_비면_한_카드가_서로_반대로_말하지_않는다(organizations: None) -> None:
    """나라장터 공고는 지역 칸이 비어 있는 쪽이 흔하다.

    그것을 「우선 활동 지역이 아니다」로 읽으면, 같은 카드의 지역 적합도가
    「지역제한 표기가 없습니다 — 제한 없음으로 보고 계산했습니다」라고 말하는 것과
    정면으로 어긋난다. 담당자가 둘 중 무엇을 믿어야 할지 모르게 된다.
    """
    profile = organization_service.load_profile(ALPHA)
    assert "전국" not in profile.preferred_regions, "전국이 있으면 이 갈래를 타지 않는다"

    notice = make_notice("g2b-REGION-000", "생성형 AI 활용 실무교육 운영", region=None)
    # 참가가능지역을 **받았는데 제한이 없는** 공고(34차 R33-D2 — 받아 본 적 없으면 확인 필요라 그 경우는 아래에서 따로 본다)
    notice = notice.model_copy(update={"raw_data": {"allowed_regions": []}})
    # 8차부터 자격 점수는 **규칙 종합(gate)** 을 그대로 읽는다 (0922 §4-B-2). 그래서 이
    # 약속은 점수 항목이 아니라 규칙표에서 지켜진다 — 판정과 점수가 한 사실에서 나온다.
    results = eligibility_engine.evaluate_notice_fields(
        notice.raw_data, as_of=NOW, regions=tuple(profile.preferred_regions)
    )
    region_rule = next(r for r in results if r.rule_id == "ELIG-REGION")
    assert region_rule.status == "PASS"
    assert "지역 제한이 등록돼 있지 않습니다" in region_rule.reason
    unknown = eligibility_engine.evaluate_notice_fields({}, as_of=NOW, regions=tuple(profile.preferred_regions))
    unknown_rule = next(r for r in unknown if r.rule_id == "ELIG-REGION")
    assert unknown_rule.status == "CHECK" and "자격 정보" in unknown_rule.reason  # 받아 본 적 없으면 「제한 없음」이라 하지 않는다

    gate, _reason = priority.procurement_eligibility_gate(
        notice, classify(notice), profile=profile, now=NOW, results=results
    )
    assert gate != "FAIL"

    # 지역이 실제로 다르게 적혀 있으면 그때는 확인하라고 말해야 한다.
    other = make_notice("g2b-REGION-001", "생성형 AI 활용 실무교육 운영", region="부산광역시")
    _c, _r, other_checks, _s = priority.score_procurement(
        other, classify(other), profile=profile, source="cached", now=NOW
    )
    assert any("부산광역시" in c for c in other_checks) or any("확인" in c for c in other_checks)


def test_eligibility_never_confirms_pass_before_reading_the_notice(organizations: None) -> None:
    """원문 확인 전에는 「가능」으로 확정하지 않는다 (CLAUDE.md §4-D).

    8차에서 지키는 자리가 바뀌었다 (0922 §4-B-2). 예전에는 점수 항목에 상한(0.6)을 씌웠는데,
    그러면 업종·지역이 코드로 확정돼도 점수가 움직이지 않는다. 이제 **규칙표가** 확정하지
    못한 조건을 남기고, 점수는 그 종합을 그대로 읽는다 — 확인 필요면 0.5 다.
    """
    profile = organization_service.load_profile(ALPHA)
    notice = make_notice("g2b-ELIG-000", "생성형 AI 활용 실무교육 운영", region="광주광역시")
    results = eligibility_engine.evaluate_notice_fields(
        notice.raw_data, as_of=NOW, regions=tuple(profile.preferred_regions)
    )
    gate, reason = priority.procurement_eligibility_gate(
        notice, classify(notice), profile=profile, now=NOW, results=results
    )
    # 업종·지역 자격 정보를 받지 못한 공고다 — 「가능」으로 확정하지 않는다.
    assert gate == "CHECK"
    assert reason and "공고문에서 볼 것" in reason
    components, _reasons, checks, _src = priority.score_procurement(
        notice, classify(notice), profile=profile, source="cached", now=NOW, gate=gate
    )
    eligibility = next(c for c in components if c.key == "eligibility")
    assert eligibility.score == 0.5
    assert any("원문" in c for c in checks)

    # 지원사업도 마찬가지 — 대상·지역이 모두 만점이어도 상한을 넘지 않는다.
    program = bizinfo_service.map_program(item_by_id("PBLN_TEST_000000000001"))
    assert program is not None
    fit = bizinfo_service.support_fit(program, today=TODAY, organization_id=ALPHA)
    by_key = {c.key: c for c in fit.components}
    assert by_key["target"].score == 1.0 and by_key["region"].score == 1.0
    s_components, _r, s_checks, _s = priority.score_support(
        program, fit, profile=profile, source="bizinfo", today=TODAY, gate="CHECK"
    )
    s_eligibility = next(c for c in s_components if c.key == "eligibility")
    assert s_eligibility.score == 0.5
    assert any("신청자격" in c for c in s_checks)

    # 모든 항목이 상한 이하인지 (0~1 범위 계약)
    for component in [*components, *s_components]:
        assert component.score is None or 0.0 <= component.score <= 1.0


def test_evidence_hint_is_capped_before_verification(organizations: None) -> None:
    """목록 단계의 근거 연결은 키워드 일치일 뿐이다 — 만점을 주지 않는다."""
    assert priority.EVIDENCE_HINT_CAP == 0.6
    profile = organization_service.load_profile(ALPHA)
    program = bizinfo_service.map_program(item_by_id("PBLN_TEST_000000000001"))
    assert program is not None
    fit = bizinfo_service.support_fit(program, today=TODAY, organization_id=ALPHA)
    components, _r, _c, _s = priority.score_support(program, fit, profile=profile, source="bizinfo", today=TODAY)
    evidence = next(c for c in components if c.key == "evidence")
    assert evidence.score is not None and evidence.score <= priority.EVIDENCE_HINT_CAP
    assert "아직 확인 안 함" in evidence.reason

    # 입찰공고는 RFP 분석 전이라 아예 미계산이다 (0점이 아니다).
    notice = make_notice("g2b-EV-000", "생성형 AI 활용 실무교육 운영")
    p_components, _r2, _c2, _s2 = priority.score_procurement(notice, classify(notice), profile=profile, source="cached", now=NOW)
    assert next(c for c in p_components if c.key == "evidence").score is None


def test_explicit_support_region_mismatch_is_a_hard_gate(organizations: None) -> None:
    """부산 소재 제한 사업은 광주·전남 회사에 높은 키워드 점수가 있어도 FAIL이다."""
    profile = organization_service.load_profile(ALPHA)
    program = bizinfo_service.map_program(item_by_id("PBLN_TEST_000000000005"))
    assert program is not None
    fit = bizinfo_service.support_fit(program, today=TODAY, organization_id=ALPHA)
    region = next(component for component in fit.components if component.key == "region")
    assert region.score == 0.0

    gate, reason = priority.support_eligibility_gate(fit)
    assert gate == "FAIL"
    assert reason and "신청 지역 불일치" in reason


def _notice_with_item(nid: str, title: str, **item: Any) -> ProcurementNotice:
    """공고 원문 필드(raw_data.item)까지 갖춘 fixture. 참가 가능 여부 규칙표가 이것을 읽는다."""
    notice = make_notice(nid, title, region=None)
    notice.raw_data = {"source": "g2b", "item": {"bidNtceNo": nid, **item}}
    return notice


def test_나라장터_공고에도_참가_가능_여부가_붙는다(organizations: None) -> None:
    """예전에는 기업마당에만 게이트가 있었다.

    입찰공고는 UnifiedOpportunity 를 만들 때 eligibility_gate 를 아예 넘기지 않아
    스키마 기본값 "CHECK" 가 사유 없이 굳었고, 담당자는 카드 앞면에서
    「내가 이 입찰에 참가할 수 있나」를 알 수 없었다.
    """
    profile = organization_service.load_profile(ALPHA)
    notice = _notice_with_item(
        "g2b-GATE-000",
        "생성형 AI 활용 실무교육 운영",
        cntrctCnclsMthdNm="일반경쟁",
        bidQlfctRgstDt="2026-09-25 18:00",
        bidClseDt="2026-09-28 10:00:00",
        indstrytyLmtYn="N",
        bidPrtcptLmtYn="N",
        asignBdgtAmt="50000000",
    )
    gate, reason = priority.procurement_eligibility_gate(notice, classify(notice), profile=profile, now=NOW)

    # 규칙이 모두 통과해도 PASS 로 확정하지 않는다 — 면허·업종·유사실적은 원문을 읽어야 안다.
    assert gate == "CHECK"
    assert reason and "공고문에서 볼 것" in reason  # 30차 §3-F #38 — 방침 문장은 카드마다 붙이지 않는다


def test_참가_가능_여부_사유는_무엇을_확인해야_하는지_말한다(organizations: None) -> None:
    profile = organization_service.load_profile(ALPHA)
    notice = _notice_with_item(
        "g2b-GATE-001",
        "생성형 AI 활용 실무교육 운영",
        cntrctCnclsMthdNm="제한경쟁",
        indstrytyLmtYn="Y",
        bidQlfctRgstDt="2026-09-25 18:00",
        bidClseDt="2026-09-28 10:00:00",
    )
    gate, reason = priority.procurement_eligibility_gate(notice, classify(notice), profile=profile, now=NOW)
    assert gate == "CHECK"
    assert reason is not None
    # 「계약방법」은 더 이상 확인 목록에 없다 — 자격 문제가 아니라 «어떻게 뽑는가»이고,
    # 그 정보는 `ELIG-AWARD` 가 따로 말한다 (0921 §4-B).
    assert "업종 제한" in reason and "계약방법" not in reason


def test_대상_지역을_모르는_지역제한은_참가불가로_읽지_않는다(organizations: None) -> None:
    """가장 비싼 실수는 근거 없는 FAIL 로 들어갈 수 있는 공고를 버리는 것이다.

    「본사또는참여지사소재지」는 지역 이름이 아니라 소재지 판단기준의 이름이다
    (캐시된 실응답 76건 중 53건이 이 갈래였고 지역 이름은 한 건도 없었다).
    """
    profile = organization_service.load_profile(ALPHA)
    assert "전국" not in profile.preferred_regions
    notice = _notice_with_item(
        "g2b-GATE-002",
        "생성형 AI 활용 실무교육 운영",
        rgnLmtBidLocplcJdgmBssNm="본사또는참여지사소재지",
        cntrctCnclsMthdNm="일반경쟁",
        bidQlfctRgstDt="2026-09-25 18:00",
        bidClseDt="2026-09-28 10:00:00",
    )
    gate, reason = priority.procurement_eligibility_gate(notice, classify(notice), profile=profile, now=NOW)
    assert gate == "CHECK"
    assert reason and "지역제한" in reason

    # 점수 항목도 이것을 「지역 제한 없음」으로 읽지 않는다 (한 카드가 서로 반대로 말하면 안 된다).
    # 8차부터는 구조로 보장된다 — 점수가 게이트를 그대로 읽으므로 두 값이 갈릴 수 없다.
    components, _r, _checks, _s = priority.score_procurement(
        notice, classify(notice), profile=profile, source="cached", now=NOW, gate=gate
    )
    eligibility = next(c for c in components if c.key == "eligibility")
    assert eligibility.score == 0.5
    assert "확인 필요" in eligibility.reason
    region_rule = next(
        r
        for r in eligibility_engine.evaluate_notice_fields(
            notice.raw_data, as_of=NOW, regions=tuple(profile.preferred_regions)
        )
        if r.rule_id == "ELIG-REGION"
    )
    assert region_rule.status == "CHECK" and "대상 지역이 아닙니다" in region_rule.reason


def test_대상_지역이_실제로_다르면_그때는_참가불가다(organizations: None) -> None:
    """지역 «이름»이 실제로 적혀 있고 회사 활동 지역 밖이면 FAIL 이다. 이 판정은 남아 있어야 한다."""
    profile = organization_service.load_profile(ALPHA)
    notice = _notice_with_item(
        "g2b-GATE-003",
        "생성형 AI 활용 실무교육 운영",
        rgnLmtBidLocplcJdgmBssNm="울산광역시",
        cntrctCnclsMthdNm="일반경쟁",
        bidClseDt="2026-09-28 10:00:00",
    )
    gate, reason = priority.procurement_eligibility_gate(notice, classify(notice), profile=profile, now=NOW)
    assert gate == "FAIL"
    assert reason and "울산광역시" in reason


def test_마감이_지난_공고는_참가불가_게이트다(organizations: None) -> None:
    profile = organization_service.load_profile(ALPHA)
    notice = make_notice("g2b-GATE-004", "생성형 AI 활용 실무교육 운영", deadline=NOW - timedelta(days=2))
    gate, reason = priority.procurement_eligibility_gate(notice, classify(notice), profile=profile, now=NOW)
    assert gate == "FAIL"
    assert reason and "마감" in reason


def test_사업영역_밖이라는_이유로_참가불가를_만들지_않는다(organizations: None) -> None:
    """«우리가 할 일이 아닌 것 같다»와 «참가할 수 없다»는 다른 말이다.

    후순위로 내리는 것은 점수와 라벨이 이미 하고 있다. 게이트까지 FAIL 로 닫으면
    컨소시엄 참여처럼 담당자가 판단할 여지가 사라진다.
    """
    profile = organization_service.load_profile(ALPHA)
    notice = _notice_with_item(
        "g2b-GATE-005",
        "AI 정보시스템 위탁감리 용역",
        cntrctCnclsMthdNm="일반경쟁",
        bidClseDt="2026-09-28 10:00:00",
    )
    _c, _r, _k, source_score = priority.score_procurement(
        notice, classify(notice), profile=profile, source="cached", now=NOW
    )
    assert source_score["gate_reason"], "감리 공고는 추천 쪽에서 후순위 사유가 붙어 있어야 한다"

    gate, reason = priority.procurement_eligibility_gate(notice, classify(notice), profile=profile, now=NOW)
    assert gate == "CHECK"
    assert reason and "감리" in reason  # 사유는 숨기지 않고 카드에 그대로 보여 준다


def test_참가_가능_여부는_PASS_를_만들지_않는다(organizations: None) -> None:
    """공고 필드만으로 PASS 를 찍으면 원문의 면허·유사실적 조건을 확인했다고 거짓말하는 것이다."""
    profile = organization_service.load_profile(ALPHA)
    notice = _notice_with_item(
        "g2b-GATE-006",
        "생성형 AI 활용 실무교육 운영",
        rgnLmtBidLocplcJdgmBssNm="광주광역시",
        cntrctCnclsMthdNm="일반경쟁",
        cmmnSpldmdCorpRgnLmtYn="N",
        indstrytyLmtYn="N",
        bidPrtcptLmtYn="N",
        bidQlfctRgstDt="2026-09-25 18:00",
        bidClseDt="2026-09-28 10:00:00",
        asignBdgtAmt="50000000",
    )
    gate, _reason = priority.procurement_eligibility_gate(notice, classify(notice), profile=profile, now=NOW)
    assert gate in ("CHECK", "FAIL")
    assert gate != "PASS"


def test_참가자격_규칙표를_먼저_불러도_import_가_깨지지_않는다() -> None:
    """opportunity_priority 가 eligibility_engine 을 recommendation 보다 먼저 부르면 순환 import 로 죽는다.

    알파벳 순 정렬 도구가 import 두 줄을 합치는 순간 다시 깨지므로, 새 인터프리터에서
    실제로 불러 본다. 같은 프로세스에서는 이미 sys.modules 에 올라와 있어 재현되지 않는다.
    """
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-c", "import app.services.opportunity_priority"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_source_specific_scores_are_kept_apart(organizations: None) -> None:
    """원본 점수(추천등급·지원 적합도)는 통합 점수에 흡수되지 않고 그대로 남는다."""
    profile = organization_service.load_profile(ALPHA)
    notice = make_notice("g2b-SRC-000", "생성형 AI 활용 실무교육 운영")
    _c, _r, _k, procurement_src = priority.score_procurement(notice, classify(notice), profile=profile, source="cached", now=NOW)
    assert procurement_src["kind"] == "recommendation" and "낙찰확률이 아닙니다" in procurement_src["note"]

    program = bizinfo_service.map_program(item_by_id("PBLN_TEST_000000000001"))
    assert program is not None
    fit = bizinfo_service.support_fit(program, today=TODAY, organization_id=ALPHA)
    _c2, _r2, _k2, support_src = priority.score_support(program, fit, profile=profile, source="bizinfo", today=TODAY)
    assert support_src["kind"] == "support_fit" and "선정확률이 아닙니다" in support_src["note"]
    assert support_src["label"] == fit.label and support_src["score"] == fit.score


# ==========================================================================
# C. 통합 목록 — 조직 반영 · 정렬 · 마감 · 부분 실패
# ==========================================================================


@pytest.mark.anyio
async def test_same_program_scores_differently_per_organization(organizations: None, bizinfo_from_fixture: Path, live_fetch_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """지시서 8항 — 사업영역·지역이 다른 두 회사는 같은 지원사업을 다르게 본다."""
    stub_procurements(monkeypatch, [])
    ai_program = "bizinfo-PBLN_TEST_000000000001"      # 광주 생성형 AI 교육
    factory_program = "bizinfo-PBLN_TEST_000000000005"  # 부산 스마트공장 설비

    alpha = await list_for(ALPHA, include_closed=True)
    beta = await list_for(BETA, include_closed=True)

    assert score_of(alpha, ai_program) is not None and score_of(beta, ai_program) is not None
    assert score_of(alpha, ai_program) > score_of(beta, ai_program)
    assert score_of(beta, factory_program) > score_of(alpha, factory_program)

    # 근거 문장도 회사별로 달라진다 (왜 이 점수인지 설명이 남는다).
    alpha_item = next(i for i in alpha.items if i.id == ai_program)
    beta_item = next(i for i in beta.items if i.id == ai_program)
    assert any("사업영역" in r for r in alpha_item.reasons)
    assert alpha_item.reasons != beta_item.reasons

    # 순위도 뒤집힌다.
    assert rank_of(alpha, ai_program) < rank_of(alpha, factory_program)
    assert rank_of(beta, factory_program) < rank_of(beta, ai_program)


def test_unified_api_reflects_selected_organization(organizations: None, bizinfo_from_fixture: Path, live_fetch_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """지시서 9항 — 통합 API 응답에 선택한 회사가 드러나고, 회사에 따라 점수가 달라진다."""
    stub_procurements(monkeypatch, [])
    ai_program = "bizinfo-PBLN_TEST_000000000001"
    factory_program = "bizinfo-PBLN_TEST_000000000005"

    def fetch(org_id: str) -> dict[str, Any]:
        # 「불가」도 함께 받는다 — 여기서 재는 것은 «회사마다 점수가 달라지는가»이고,
        # 자격으로 거르면 비교할 항목이 사라진다 (0921 §4-C-2).
        response = client.get(
            "/api/business-opportunities",
            params={"organization_id": org_id, "include_closed": True, "include_blocked": True},
        )
        assert response.status_code == 200, response.text
        return response.json()

    alpha = fetch(ALPHA)
    beta = fetch(BETA)

    assert alpha["organization_id"] == ALPHA and alpha["organization_name"] == "가상 AI교육 컴퍼니"
    assert beta["organization_id"] == BETA and beta["organization_name"] == "가상 제조설비 컴퍼니"
    assert all(item["organization_id"] == ALPHA for item in alpha["items"])

    alpha_scores = {i["id"]: i["company_priority_score"] for i in alpha["items"]}
    beta_scores = {i["id"]: i["company_priority_score"] for i in beta["items"]}
    assert alpha_scores[ai_program] > beta_scores[ai_program]
    assert beta_scores[factory_program] > alpha_scores[factory_program]

    # 점수의 의미가 응답에 그대로 적혀 있다 (확률이 아니다).
    assert "낙찰확률" in alpha["note"] and "선정확률" in alpha["note"]
    assert "우선순위" in alpha["note"]

    # 없는 회사는 404.
    assert client.get("/api/business-opportunities", params={"organization_id": "org-does-not-exist"}).status_code == 404


@pytest.mark.anyio
async def test_two_sources_share_one_ranked_list(organizations: None, bizinfo_from_fixture: Path, live_fetch_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """지시서 10항 — 두 출처가 한 목록에 섞이고 priority_rank 는 1부터 빈틈없이 매겨진다."""
    stub_procurements(
        monkeypatch,
        [
            make_notice("g2b-MIX-001", "생성형 AI 활용 실무교육 운영 용역"),
            make_notice("g2b-MIX-002", "공공기관 AI 컨설팅 및 업무자동화 교육", budget=None),
        ],
    )
    listing = await list_for(ALPHA, include_closed=True)

    assert listing.g2b_count == 2
    assert listing.bizinfo_count == 7  # fixture 유효 항목 7건 (필수값 없는 2건은 제외)
    assert listing.total_count == len(listing.items) == 9
    # 39차 D22 — 「전체」는 출처를 번갈아 세운다(목록 순서 ≠ 통합 순위). 통합 순위는 그대로 1부터 빈틈없다.
    assert sorted(i.priority_rank for i in listing.items) == list(range(1, 10))
    assert [i.source_type for i in listing.items][:4] == ["g2b", "bizinfo", "g2b", "bizinfo"]

    # 출처마다 다음 화면이 다르다 (지원사업을 입찰처럼 열지 않는다).
    for item in listing.items:
        if item.source_type == "g2b":
            assert item.opportunity_type == "procurement"
            assert item.next_route.kind == "procurement_analysis" and item.next_route.path == f"/analysis?notice={item.id}"
        else:
            assert item.opportunity_type == "support_program"
            assert item.next_route.kind == "support_application" and item.next_route.path == f"/support/{item.id}"
            # 지원 규모는 목록 API 에 없다 → 0원으로 표시하지 않는다.
            assert item.budget is None

    assert listing.source_errors == {"g2b": None, "bizinfo": None, "manual": None}  # 38차 §3-E — 출처 셋
    assert listing.source_status["bizinfo"] == "bizinfo" and listing.source_status["g2b"] == "cached"

    # source 필터도 목록을 갈라 준다.
    only_bizinfo = await list_for(ALPHA, source="bizinfo", include_closed=True)
    assert only_bizinfo.g2b_count == 0 and only_bizinfo.bizinfo_count == 7
    only_g2b = await list_for(ALPHA, source="g2b", include_closed=True)
    assert only_g2b.bizinfo_count == 0 and only_g2b.g2b_count == 2


@pytest.mark.anyio
async def test_통합_목록의_입찰공고에도_게이트와_사유가_실려_나간다(
    organizations: None, bizinfo_from_fixture: Path, live_fetch_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """예전에는 나라장터 항목의 gate_reason 이 전부 None 이었다 (게이트를 넘기지 않아 기본값이 굳었다)."""
    open_notice = _notice_with_item(
        "g2b-LIST-001",
        "생성형 AI 활용 실무교육 운영 용역",
        cntrctCnclsMthdNm="일반경쟁",
        bidClseDt="2026-09-28 10:00:00",
    )
    blocked = _notice_with_item(
        "g2b-LIST-002",
        "생성형 AI 활용 실무교육 운영 용역",
        rgnLmtBidLocplcJdgmBssNm="울산광역시",
        cntrctCnclsMthdNm="일반경쟁",
        bidClseDt="2026-09-28 10:00:00",
    )
    stub_procurements(monkeypatch, [open_notice, blocked])
    listing = await list_for(ALPHA, include_closed=True)

    by_id = {i.id: i for i in listing.items}
    for nid in ("g2b-LIST-001", "g2b-LIST-002"):
        assert by_id[nid].gate_reason, f"{nid} 에 참가 가능 여부 사유가 비어 있다"

    assert by_id["g2b-LIST-001"].eligibility_gate == "CHECK"
    assert by_id["g2b-LIST-002"].eligibility_gate == "FAIL"
    # FAIL 은 점수가 높아도 「우선 검토」로 부르지 않고, 검토 가능한 항목 뒤로 간다.
    assert by_id["g2b-LIST-002"].priority_label != "우선 검토"
    assert by_id["g2b-LIST-001"].priority_rank < by_id["g2b-LIST-002"].priority_rank

    # 기업마당 판정은 그대로다 (한쪽을 붙이면서 다른 쪽을 되돌리지 않는다).
    #
    # 사유 문구는 0921 §4-B 에서 **규칙 결과**로 바뀌었다 — 예전에는 점수 성분을 보고
    # 「신청 지역 불일치」라고만 적었고, 지금은 BIZ-REGION 이 지역 태그와 회사 지역을
    # 나란히 적는다. 근거가 화면에 그대로 보이는 쪽이 낫다.
    busan = by_id["bizinfo-PBLN_TEST_000000000005"]
    assert busan.eligibility_gate == "FAIL"
    assert busan.gate_reason and "부산" in busan.gate_reason
    assert "광주" in busan.gate_reason, "왜 안 되는지 회사 쪽 근거도 함께 적어야 한다"


@pytest.mark.anyio
async def test_불가는_기본으로_숨기고_토글로_되돌린다(
    organizations: None, bizinfo_from_fixture: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기업마당을 전부 받으면서 목록이 1,712건이 됐고 그중 1,002건이 「불가」였다.

    담당자가 볼 수 없는 것을 매번 스크롤해 지나가게 두지 않는다. **지우는 것이 아니다** —
    「불가 포함」을 켜면 그대로 돌아오고, **분모(summary)는 흔들리지 않는다** (0921 §4-C-2).
    """
    # 마감이 촉박한 공고는 「불가(촉박)」가 된다 — 이 픽스처의 불가 한 건이 그것이다.
    urgent = make_notice("g2b-LIST-011", "생성형 AI 교육 운영 용역", deadline=NOW + timedelta(days=1))
    roomy = make_notice("g2b-LIST-012", "생성형 AI 교육 기획 용역", deadline=NOW + timedelta(days=25))
    stub_procurements(monkeypatch, [urgent, roomy])

    hidden = await list_for(ALPHA, include_blocked=False)
    shown = await list_for(ALPHA, include_blocked=True)

    blocked = [i for i in shown.items if i.eligibility_gate == "FAIL"]
    assert blocked, "이 픽스처에는 불가 판정이 하나는 있어야 이 테스트가 뜻이 있다"
    assert all(i.eligibility_gate != "FAIL" for i in hidden.items)
    assert len(hidden.items) == len(shown.items) - len(blocked)
    # 숨겨도 분모는 같다 — 화면의 「전체 n건」이 토글에 따라 흔들리면 안 된다.
    assert hidden.summary.open_total == shown.summary.open_total
    assert hidden.blocked_count == shown.blocked_count == len(blocked)


def _unified(oid: str, *, score: int | None, deadline: datetime | None, closed: bool = False, budget: int | None = None, confidence: str = "medium", eligibility_gate: str = "CHECK") -> UnifiedOpportunity:
    return UnifiedOpportunity(
        id=oid,
        source_type="bizinfo",
        opportunity_type="support_program",
        title=f"정렬 확인용 {oid}",
        agency="가상기관",
        deadline=deadline,
        organization_id=ALPHA,
        company_priority_score=score,
        priority_rank=0,
        priority_label=priority.label_of(score, closed=closed),
        eligibility_gate=eligibility_gate,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        score_components=[],
        next_route=NextRoute(kind="support_application", path=f"/support/{oid}", label="지원사업 신청 분석 열기"),
        source="sample",
        closed=closed,
        budget=budget,
    )


def test_equal_scores_sort_stably_by_id() -> None:
    """지시서 11항 — 같은 점수·같은 마감이면 항상 같은 순서(id)다. 두 번 정렬해도 같다."""
    deadline = NOW + timedelta(days=10)
    items = [_unified(oid, score=70, deadline=deadline) for oid in ("bizinfo-c", "bizinfo-a", "bizinfo-b")]

    first = [i.id for i in opportunity_service.sort_opportunities(list(items), "priority")]
    assert first == ["bizinfo-a", "bizinfo-b", "bizinfo-c"]

    # 입력 순서를 바꿔도, 다시 정렬해도 같은 순서.
    shuffled = [items[2], items[0], items[1]]
    assert [i.id for i in opportunity_service.sort_opportunities(shuffled, "priority")] == first
    twice = opportunity_service.sort_opportunities(opportunity_service.sort_opportunities(list(items), "priority"), "priority")
    assert [i.id for i in twice] == first
    assert [i.priority_rank for i in twice] == [1, 2, 3]

    # deadline·value 정렬에서도 동률은 id 로 갈린다.
    assert [i.id for i in opportunity_service.sort_opportunities(list(items), "deadline")] == first
    assert [i.id for i in opportunity_service.sort_opportunities(list(items), "value")] == first


def test_sort_does_not_treat_missing_values_as_zero() -> None:
    """점수·금액이 없는 항목을 0으로 만들어 위로 올리거나 밀어내지 않는다."""
    deadline = NOW + timedelta(days=10)
    scored = _unified("bizinfo-scored", score=10, deadline=deadline, budget=1_000_000)
    unscored = _unified("bizinfo-unknown", score=None, deadline=deadline, budget=None)
    ordered = opportunity_service.sort_opportunities([unscored, scored], "priority")
    assert [i.id for i in ordered] == ["bizinfo-scored", "bizinfo-unknown"]  # 미확인은 0점이 아니라 뒤로

    by_value = opportunity_service.sort_opportunities([unscored, scored], "value")
    assert [i.id for i in by_value] == ["bizinfo-scored", "bizinfo-unknown"]  # 금액 미확인은 0원이 아니라 뒤로
    assert by_value[1].company_priority_score is None and by_value[1].priority_label == "미확인"


def test_hard_gate_fail_sorts_after_eligible_items_even_with_higher_score() -> None:
    deadline = NOW + timedelta(days=10)
    blocked = _unified("bizinfo-blocked", score=95, deadline=deadline, eligibility_gate="FAIL")
    reviewable = _unified("bizinfo-reviewable", score=50, deadline=deadline)
    ordered = opportunity_service.sort_opportunities([blocked, reviewable], "priority")
    assert [item.id for item in ordered] == ["bizinfo-reviewable", "bizinfo-blocked"]


@pytest.mark.anyio
async def test_closed_programs_are_separated(organizations: None, bizinfo_from_fixture: Path, live_fetch_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """지시서 12항 — 마감 사업은 기본에서 빠지고, 포함하면 맨 뒤에서 '마감'으로 표시된다."""
    stub_procurements(monkeypatch, [])
    closed_id = "bizinfo-PBLN_TEST_000000000007"  # 2025년에 접수 종료

    default = await list_for(ALPHA)
    assert closed_id not in {i.id for i in default.items}
    assert default.closed_count == 1  # 걸러도 몇 건이 마감인지는 알려준다
    assert all(i.closed is False for i in default.items)
    assert [i.priority_rank for i in default.items] == list(range(1, len(default.items) + 1))

    with_closed = await list_for(ALPHA, include_closed=True)
    ids = [i.id for i in with_closed.items]
    assert closed_id in ids
    closed_item = next(i for i in with_closed.items if i.id == closed_id)
    assert closed_item.closed is True
    assert closed_item.priority_label == "마감"
    assert closed_item.priority_rank == len(with_closed.items)  # 점수와 무관하게 맨 뒤
    assert [i.priority_rank for i in with_closed.items] == list(range(1, len(with_closed.items) + 1))

    # 마감 사업이 점수가 높아도 앞으로 오지 않는다.
    for sort in ("priority", "deadline", "value"):
        ordered = await list_for(ALPHA, include_closed=True, sort=sort)
        assert ordered.items[-1].id == closed_id, sort


@pytest.mark.anyio
async def test_one_source_failure_keeps_the_other(organizations: None, bizinfo_from_fixture: Path, live_fetch_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """지시서 14항 — 나라장터가 죽어도 기업마당은 나오고, 실패 사유가 남는다."""
    stub_procurements(monkeypatch, error=procurement_service.NoNoticeDataError("테스트: 나라장터 조회 실패"))
    listing = await list_for(ALPHA, include_closed=True)

    assert listing.g2b_count == 0
    assert listing.bizinfo_count == 7 and listing.items
    assert listing.source_errors["g2b"] and "테스트: 나라장터 조회 실패" in listing.source_errors["g2b"]
    assert listing.source_errors["bizinfo"] is None
    assert listing.source_status["g2b"] is None
    assert [i.priority_rank for i in listing.items] == list(range(1, len(listing.items) + 1))


@pytest.mark.anyio
async def test_support_failure_keeps_procurements(organizations: None, bizinfo_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """반대 방향 — 기업마당이 죽어도 나라장터 공고는 그대로 나온다."""
    stub_procurements(monkeypatch, [make_notice("g2b-ONLY-001", "생성형 AI 활용 실무교육 운영 용역")])

    async def _boom(**_kwargs: Any):
        raise bizinfo_client.BizinfoError("테스트: 기업마당 조회 실패")

    monkeypatch.setattr(bizinfo_service, "list_programs", _boom)
    listing = await list_for(ALPHA, include_closed=True)

    assert listing.bizinfo_count == 0
    assert listing.g2b_count == 1 and listing.items[0].id == "g2b-ONLY-001"
    assert listing.source_errors["bizinfo"] and "테스트: 기업마당 조회 실패" in listing.source_errors["bizinfo"]
    assert listing.source_errors["g2b"] is None
    assert listing.source_status["bizinfo"] is None


def test_unified_api_survives_both_sources_failing(organizations: None, bizinfo_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """둘 다 실패해도 500 이 아니라 '빈 목록 + 사유'로 답한다."""
    stub_procurements(monkeypatch, error=procurement_service.NoNoticeDataError("테스트: 나라장터 없음"))

    async def _boom(**_kwargs: Any):
        raise bizinfo_client.BizinfoError("테스트: 기업마당 없음")

    monkeypatch.setattr(bizinfo_service, "list_programs", _boom)
    response = client.get("/api/business-opportunities", params={"organization_id": ALPHA})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == [] and body["total_count"] == 0
    assert body["source_errors"]["g2b"] and body["source_errors"]["bizinfo"]


# ==========================================================================
# D. 지원사업 신청 분석 (상세)
# ==========================================================================


def test_support_detail_unknown_id_is_404(organizations: None, bizinfo_from_fixture: Path) -> None:
    """지시서 19항 앞부분 — 목록에 없는 id 는 404."""
    response = client.get("/api/support-programs/bizinfo-NOT-IN-LIST", params={"organization_id": ALPHA})
    assert response.status_code == 404
    assert "지원사업" in response.json()["detail"]


def test_support_detail_marks_missing_conditions_as_unknown(
    organizations: None, bizinfo_from_fixture: Path, live_fetch_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """지시서 19항 — 4묶음이 오고, 목록 API 에 없는 조건은 지어내지 않고 unknown 으로 남는다."""
    # 픽스처 신청기간이 「20260901 ~ 20260930」이다 — 10-01부터 「마감」이 되어 실패했다(26차 ISSUE-146).
    # 시계를 신청기간 가운데(9-15 KST 정오)에 고정한다. 테스트 본문이 timeshift 픽스처보다 늦게 덮는다.
    from datetime import datetime, timezone

    from app.core import storage

    monkeypatch.setattr(storage, "utc_now", lambda: datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc))
    program_id = "bizinfo-PBLN_TEST_000000000001"
    response = client.get(f"/api/support-programs/{program_id}", params={"organization_id": ALPHA})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["program_id"] == program_id and body["organization_id"] == ALPHA
    assert set(body["plan"]) == {"eligibility", "conditions", "schedule", "documents"}

    items = {i["key"]: i for group in body["plan"].values() for i in group}
    # 목록 API 에 없는 항목 — 값을 만들지 않는다.
    for key in ("business_age", "excluded", "scale", "self_burden"):
        assert items[key]["status"] == "unknown", key
        assert items[key]["value"] is None, key
        assert items[key]["note"] and "원문" in items[key]["note"], key
    # 목록 API 에 있는 항목 — 원문 필드가 함께 적힌다.
    assert items["target"]["status"] == "confirmed" and items["target"]["value"] == "중소기업"
    assert items["target"]["source_field"] == "trgetNm"
    assert items["period"]["status"] == "confirmed" and "2026-09-01" in items["period"]["value"]
    assert items["apply_method"]["status"] == "confirmed"
    assert items["forms"]["value"] == "가상_신청서식.hwp"
    assert items["notice_file"]["value"] == "가상_공고문.pdf"

    assert body["unknown_count"] >= 4 and body["confirmed_count"] >= 1
    assert body["unknown_count"] + body["confirmed_count"] == len(items)

    # 신청 전 점검에 미확인 항목이 그대로 올라온다 + 사람이 최종 판단한다.
    checks = body["pre_submit_checks"]
    assert any("창업 연차" in c for c in checks) and any("제외 대상" in c for c in checks)
    assert any("담당자 최종 검토" in c for c in checks)

    # 근거가 없으면 사업계획서 뼈대에서 '근거 없음'으로 남긴다 (지어내지 않는다).
    capability = next(s for s in body["draft_outline"] if s["section"] == "수행 역량·유사 실적")
    assert capability["grounded"] is False and "고른 회사 문장이 없습니다" in capability["note"]

    # 점수는 목록과 같은 축이며 확률이 아니다.
    assert body["source_specific_score"]["kind"] == "support_fit"
    assert "선정확률이 아닙니다" in body["source_specific_score"]["note"]
    assert body["priority_label"] in ("우선 검토", "검토", "후순위", "미확인")


def test_support_detail_does_not_borrow_bid_vocabulary(organizations: None, bizinfo_from_fixture: Path, live_fetch_on: None) -> None:
    """지시서 20항 — 지원사업 상세 응답에 입찰 용어(입찰/낙찰/투찰/RFP/수주확률)가 없다."""
    response = client.get("/api/support-programs/bizinfo-PBLN_TEST_000000000001", params={"organization_id": ALPHA})
    assert response.status_code == 200, response.text
    body = response.json()

    offenders = [
        (path, word, text)
        for path, text in iter_strings(body)
        for word in FORBIDDEN_BID_WORDS
        if word in text
    ]
    assert offenders == [], f"지원사업 상세에 입찰 용어가 있습니다: {offenders}"

    # 대신 신청 흐름 용어를 쓴다.
    haystack = json.dumps(body, ensure_ascii=False)
    for word in ("신청자격", "신청 기간", "제출서류", "사업계획서"):
        assert word in haystack, word


def test_support_list_api_reports_source_and_mapping_state(organizations: None, bizinfo_from_fixture: Path, live_fetch_on: None) -> None:
    """목록 API 는 데이터 출처와 필드 매핑 확인 여부를 숨기지 않는다."""
    response = client.get("/api/support-programs", params={"organization_id": ALPHA})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "bizinfo"
    assert body["bizinfo_api_configured"] is True
    assert body["field_mapping_verified"] is bizinfo_service.FIELD_MAPPING_VERIFIED
    assert body["total_available"] == 1520  # 실응답 totCnt — 받은 건수가 아니다
    assert body["count"] == 7 and body["total_fetched"] == 9
    assert all(view["kind"] == "support" for view in body["items"])


def test_33차_목록에서_빠진_마감_사업은_저장본으로_보이고_새_초안은_막는다(
    organizations: None, bizinfo_from_fixture: Path, live_fetch_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """126482 꼴 — 최신화로 마감 사업이 목록에서 빠지면 상세 · 새 초안이 404 였다(33차 §3-A-6 · 절차서 D)."""
    from datetime import datetime, timezone

    from app.core import org_storage, storage
    from app.services import support_application_service as sas

    monkeypatch.setattr(storage, "utc_now", lambda: datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc))
    program_id = "bizinfo-PBLN_TEST_000000000001"
    folder = org_storage.storage_for(ALPHA).analysis_dir(program_id)
    folder.mkdir(parents=True, exist_ok=True)  # 저장된 초안 · 분석이 있는 사업
    params = {"organization_id": ALPHA}
    assert client.get(f"/api/support-programs/{program_id}", params=params).status_code == 200
    assert (folder / sas.PROGRAM_SNAPSHOT).exists()  # 목록에 있을 때 공고 정보 사본을 남겼다

    original = bizinfo_service.list_programs

    async def _without(**kwargs: Any):
        listing = await original(**kwargs)
        return listing.model_copy(update={"items": [v for v in listing.items if v.program.id != program_id]})

    monkeypatch.setattr(bizinfo_service, "list_programs", _without)
    # 마감일(9-30) 전에 목록에서 빠짐 — 「마감」으로 단정하지 않고 원문 확인 · 막지 않는다(34차 R33-A1)
    detail = client.get(f"/api/support-programs/{program_id}", params=params)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["archived"] is True and body["archived_closed"] is False
    assert body["archived_note"] == sas.DELISTED_NOTE
    program, _fit, source = asyncio.run(sas.find_program(program_id, organization_id=ALPHA))
    assert source == sas.ARCHIVED_SOURCE and sas.archived_block(program, source) is None
    assert client.post(f"/api/support-programs/{program_id}/plan-draft", params=params, json={"no_ai": True}).status_code == 200
    # 마감일이 지나면 「마감된 공고」 · 새 초안은 막는다
    monkeypatch.setattr(storage, "utc_now", lambda: datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc))
    body = client.get(f"/api/support-programs/{program_id}", params=params).json()
    assert body["archived_closed"] is True and "마감된 공고" in (body["archived_note"] or "")
    created = client.post(f"/api/support-programs/{program_id}/plan-draft", params=params, json={})
    assert created.status_code == 409 and "새 초안은 만들 수 없습니다" in created.json()["detail"]
    # 저장된 것이 없는 사업은 그대로 404(사본을 남기지 않는다)
    other = client.get("/api/support-programs/bizinfo-PBLN_NOT_SAVED_000", params=params)
    assert other.status_code == 404
