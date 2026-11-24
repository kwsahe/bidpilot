"""테스트 공통 설정.

두 가지를 강제한다.

1. **네트워크 격리** — 테스트는 절대 나라장터 실 API를 호출하지 않는다.
   실호출을 시도하면 조용히 느려지는 대신 `NetworkAccessError`로 즉시 실패한다.
2. **캐시 파일 격리** — `procurement_service`의 공고 캐시를 tmp 디렉터리로 돌린다.
   테스트가 저장소의 실제 `data/public/sample_procurements/g2b_cache.json`을
   덮어쓰지 않도록 한다.
3. **파싱 결과 격리** — `rfp_parser.GENERATED_DIR` 도 같은 이유로 tmp 로 돌린다.
   `parse_and_store` 를 부르는 테스트가 추적 중인
   `data/public/sample_rfp/generated/*.requirements.json` 의 `generated_at` 을 새로 찍어
   작업 트리를 더럽혔다. 읽기만 하는 테스트도 많으므로 **비우지 않고 통째로 복사**해서 쓴다.

httpx 차단은 `Client.get` / `AsyncClient.get`이 아니라 **transport 계층**을 막는다.
Starlette `TestClient`가 `httpx.Client`를 상속해 `get()`을 그대로 물려받기 때문에
`httpx.Client.get`을 막으면 TestClient까지 죽는다. transport를 막으면
TestClient(ASGI transport)는 그대로 두고 실제 소켓 호출만 차단할 수 있어 더 안전하고
`get` 외의 모든 메서드(post/stream 등)까지 함께 막힌다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import types
from pathlib import Path
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core import storage
from app.core.config import get_settings
from app.services import audit_log_service, auditor_service, g2b_client, llm_client, procurement_service, rfp_parser

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
SAMPLE_PROCUREMENT_DIR = DATA_DIR / "public" / "sample_procurements"
RAW_RESPONSE_SAMPLE = SAMPLE_PROCUREMENT_DIR / "g2b_raw_response_sample.json"
SAMPLE_RFP_DIR = DATA_DIR / "public" / "sample_rfp"
SAMPLE_RFP_PDF = SAMPLE_RFP_DIR / "synthetic_ai_training_rfp.pdf"
SAMPLE_RFP_DOCX = SAMPLE_RFP_DIR / "synthetic_ai_training_rfp.docx"


class NetworkAccessError(RuntimeError):
    """테스트 중 실제 HTTP 호출을 시도했다."""


def _blocked_request(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
    # query string에는 serviceKey가 실려 있을 수 있으므로 절대 출력하지 않는다 (CLAUDE.md 21).
    target = f"{request.url.scheme}://{request.url.host}{request.url.path}"
    raise NetworkAccessError(
        f"테스트에서 실제 네트워크 호출이 차단되었습니다: {request.method} {target}. "
        "나라장터 호출은 monkeypatch로 대체하세요."
    )


async def _blocked_async_request(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
    return _blocked_request(self, request, *args, **kwargs)


async def _blocked_async_get(self: Any, url: Any, *args: Any, **kwargs: Any) -> Any:
    # params(serviceKey 포함)는 로그에 남기지 않는다. URL 경로만 보여준다.
    raise NetworkAccessError(
        f"테스트에서 실제 네트워크 호출이 차단되었습니다: GET {str(url).split('?')[0]}. "
        "나라장터 호출은 monkeypatch로 대체하세요."
    )


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """실제 소켓을 쓰는 httpx transport를 모두 막는다."""
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked_request)
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", _blocked_async_request
    )
    # g2b_client는 AsyncClient.get을 직접 쓴다. transport 차단으로도 잡히지만
    # 실패 메시지를 명확히 하기 위해 한 겹 더 막는다 (TestClient는 동기라 영향 없음).
    monkeypatch.setattr(httpx.AsyncClient, "get", _blocked_async_get)


#: 셸에 남아 있으면 테스트의 답을 바꾸는 환경변수 (0925 §4-D-5 · 15차 ISSUE-129).
#: 임베딩 둘도 같은 부류다 — 셸에 `SEMANTIC_FIT=1` 이 남아 있으면 키워드 값을 박아 둔
#: 회귀 테스트가 의미 유사도 값을 받는다.
LIVE_FETCH_VARS: tuple[str, ...] = (
    "G2B_LIVE_FETCH",
    "BIZINFO_LIVE_FETCH",
    "EMBEDDING_LIVE",
    "SEMANTIC_FIT",
    # 완성 문도 같은 부류다 (16차 ISSUE-130). 셸에 `LLM_LIVE=1` 이 남아 있으면
    # 「꺼져 있으면 규칙 경로」를 재는 검사가 조용히 다른 길을 간다.
    "LLM_LIVE",
    "LLM_CREDIT_CONFIRMED",
    # 첨부 내려받기 문 (19차 §4-A-4). 셸에 `ATTACHMENT_FETCH=1` 이 남아 있으면 「꺼져 있으면
    # 캐시만」을 재는 검사가 조용히 내려받는 쪽으로 간다.
    "ATTACHMENT_FETCH",
    # 완성 공급자 (26차 ISSUE-145). `.env` · 셸에 `LLM_PROVIDER=xai` 면 9건이 실패했고, `claude_cli` 면
    # pytest 가 **진짜 CLI** 쪽으로 갔다. 공급자 검사는 자기 값을 직접 넣는다.
    "LLM_PROVIDER",
    "XAI_API_KEY",
    "XAI_MODEL",
    "XAI_REASONING_EFFORT",
    "LLM_BASE_URL",
    "CLAUDE_CLI_PATH",
    "CLAUDE_CLI_MODEL",
    "CLAUDE_CLI_EFFORT",
    # 사업계획서 작성 문 (28차 §3-D) — 셸에 남은 값으로 진짜 CLI 를 부르지 않게
    "PLAN_WRITER_CLI",
    # Codex CLI (29차 §3-A)
    "CODEX_CLI_PATH",
    "CODEX_CLI_MODEL",
)

#: 위 환경변수에 대응하는 설정 필드 — 같은 인스턴스에서 기본값으로 되돌린다(`cache_clear()` 금지 · 아래 설명).
LIVE_FETCH_FIELDS: tuple[str, ...] = (
    "g2b_live_fetch",
    "bizinfo_live_fetch",
    "keyword_search_live",
    "embedding_live",
    "semantic_fit",
    "llm_live",
    "llm_credit_confirmed",
    "attachment_fetch",
    "llm_provider",
    "xai_api_key",
    "xai_model",
    "xai_reasoning_effort",
    "llm_base_url",
    "claude_cli_path",
    "claude_cli_model",
    "claude_cli_effort",
    "plan_writer_cli",
    "codex_cli_path",
    "codex_cli_model",
)


@pytest.fixture(autouse=True)
def no_live_fetch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """실조회 스위치를 **셸에서 떼어 낸다** (0925 §4-D-5).

    `scripts/start_dev.ps1 -Frozen` 을 쓴 셸에는 `G2B_LIVE_FETCH=0` 이 남는다. 그 셸에서
    pytest 를 돌리면 `test_health.py` 의 넷이 503·KeyError 로 죽었다 — **테스트 실패가
    코드가 아니라 셸 상태에서 나왔다.** 값이 `0` 이든 `1` 이든 테스트는 자기가 정한
    값만 봐야 한다.

    `delenv` 만으로는 모자라다. `get_settings()` 는 `lru_cache` 라 pytest 가 켜질 때의
    셸 환경에서 읽은 값을 그대로 들고 있다. 그렇다고 `cache_clear()` 를 부르면 안 된다 —
    `test_api_auth.py` 처럼 **그 인스턴스에 직접** `monkeypatch.setattr` 하는 테스트가
    있어서, 캐시를 갈아 끼우면 그 테스트가 손댄 것과 앱이 읽는 것이 서로 다른 객체가 된다.
    그래서 같은 인스턴스의 두 항목만 기본값으로 되돌린다 (같은 파일의 `no_token` 과 같은 방식).

    이 값을 실제로 보고 싶은 테스트는 자기 `monkeypatch.setattr` 로 덮어쓰면 된다 —
    테스트 본문이 나중에 실행되므로 이 픽스처를 이긴다.
    """
    from app.core.config import Settings, get_settings

    for name in LIVE_FETCH_VARS:
        monkeypatch.delenv(name, raising=False)
    settings = get_settings()
    for field in LIVE_FETCH_FIELDS:
        monkeypatch.setattr(settings, field, Settings.model_fields[field].default)
    # 빈 경로는 PATH 의 진짜 codex.exe 를 찾는다(이 PC 에 있다) — 시험은 없는 경로로 시작하고, Codex 를 재는 시험이 자기 값을 넣는다.
    monkeypatch.setattr(settings, "codex_cli_path", r"C:\nonexistent\codex.exe")


class CliAccessError(RuntimeError):
    """테스트에서 Claude CLI 를 실제로 부르려 했다."""


class _NoCliSubprocess(types.ModuleType):
    """`llm_client` 가 보는 `subprocess` 대역 — `run` 만 막고 나머지(TimeoutExpired 등)는 진짜 모듈 것을 준다.

    전역 `subprocess.run` 을 막지 않는 이유: git 을 부르는 검사(`test_public_demo_snapshot`)가 있다.
    CLI 를 재는 검사는 이 대역의 `run` 을 자기 가짜로 덮으면 된다(`test_llm_claude_cli.fake_run`).
    """

    def __init__(self) -> None:
        super().__init__("subprocess_no_cli")

    def __getattr__(self, name: str) -> Any:
        return getattr(subprocess, name)

    @staticmethod
    def run(*args: Any, **kwargs: Any) -> Any:
        raise CliAccessError("테스트에서 Claude CLI 호출이 차단되었습니다 — llm_client.subprocess.run 을 가짜로 바꾸세요.")


@pytest.fixture(autouse=True)
def block_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude CLI(`claude -p`)를 부르는 길을 막는다 (26차 ISSUE-145 · `block_network` 와 같은 자리)."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client, "subprocess", _NoCliSubprocess())


@pytest.fixture()
def live_fetch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """이 테스트는 **바깥을 부르는 경로**를 잰다 — 그래서 스위치를 켠다 (prompt_03 §4-A-3).

    14차부터 실호출은 **기본이 꺼짐**이다(ISSUE-120). 그래서 「나라장터를 부르고 그
    결과로 캐시를 쓴다」를 재는 테스트는 **자기가 켰다고 말해야** 한다. 이름으로 받게 한
    이유가 그것이다 — 테스트 서명만 봐도 「이건 부르는 쪽을 재는 테스트」임이 보인다.

    바깥으로 실제로 나가지는 않는다. `block_network` 가 소켓을 막고 있고, 이 픽스처를
    쓰는 테스트는 전부 `collect_notices`·`fetch_programs_raw` 를 자기 가짜로 갈아 끼운다.
    여기서 켜는 것은 「그 가짜를 부를지 말지」를 가르는 문 하나다.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "g2b_live_fetch", True)
    monkeypatch.setattr(settings, "bizinfo_live_fetch", True)


@pytest.fixture()
def attachment_fetch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """이 테스트는 **첨부를 실제로 내려받는 경로**를 잰다 (19차 §4-A-4).

    첨부 내려받기도 기본이 꺼짐이다. 바깥으로 나가지는 않는다 — 이 픽스처를 쓰는 테스트는
    httpx 를 `MockTransport` 로 갈아 끼운다. 여기서 켜는 것은 「그 가짜를 부를지」를 가르는 문이다.
    """
    monkeypatch.setattr(get_settings(), "attachment_fetch", True)


@pytest.fixture(autouse=True)
def usage_log_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """호출 누계 기록(`llm_usage.jsonl`)을 테스트별 tmp 로 돌린다 (15차 · ISSUE-129).

    15차부터 `embed()` 가 자기 호출을 기록에 적는다(§4-A-3). 그런데 그 파일은 **이
    저장소의 실제 감사 기록**이다 — 「LLM 호출은 지금까지 2줄」이 보고의 근거다. 가짜
    클라이언트로 `embed()` 를 재는 테스트가 여기에 한 줄을 더하면, 그 근거가 조용히
    틀린 값이 된다. 실제로 이 픽스처를 만들기 전에 한 줄이 들어갔다(되돌렸다).

    `credit_ok()` 가 이 파일의 마지막 줄을 읽으므로 **읽는 쪽도 함께 격리된다** —
    저장소 기록의 429 한 줄이 테스트 답을 정하지 않게 된다.

    자기 기록을 직접 보고 싶은 테스트는 자기 `monkeypatch.setattr` 로 덮어쓰면 된다
    (테스트 본문이 나중에 실행되므로 이 픽스처를 이긴다).
    """
    monkeypatch.setattr(llm_client, "USAGE_LOG", tmp_path / "llm_usage.jsonl")


@pytest.fixture(autouse=True)
def auto_collect_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """자동 받기 기록 · 받기 잠금을 테스트별 tmp 로 돌리고 예약 작업 상태는 「Ready」로 둔다(40차 D28 · D29 · D30).

    이 PC 의 실제 기록(`data/private/logs/collect_daily.log`)과 실제 예약 작업(PowerShell 조회)에 따라 답이 바뀌지 않게 한다 —
    기록이 없으면 「none」(키트)이다. 받은 때를 재는 테스트는 자기 `monkeypatch.setattr` 로 덮어쓴다.
    """
    from app.services import auto_collect

    monkeypatch.setattr(auto_collect, "LOG_FILE", tmp_path / "collect_daily.log")
    monkeypatch.setattr(auto_collect, "LOCK_FILE", tmp_path / "collect_daily.lock")
    monkeypatch.setattr(auto_collect, "task_state", lambda: "Ready")


@pytest.fixture(autouse=True)
def prespec_cache_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """사전규격 · 발주계획 저장본을 테스트별 tmp 로 돌린다 (38차 §3-D).

    매일 아침 받기가 살아 있는 저장본(`data/private/cache/g2b_prespec` · `g2b_orderplan`)을 채운다 — 목록 · 브리핑 테스트가
    그 날의 건수에 따라 답이 바뀌지 않게, 받기 테스트가 살아 있는 저장본을 덮지 않게 한다.
    """
    from app.services import prespec_service

    monkeypatch.setattr(prespec_service, "PRESPEC_CACHE_FILE", tmp_path / "prespec_cache.json")
    monkeypatch.setattr(prespec_service, "ORDERPLAN_CACHE_FILE", tmp_path / "orderplan_cache.json")


@pytest.fixture(autouse=True)
def collect_keywords_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """추가 수집 낱말 파일(2.0.7)을 테스트별 tmp 로 돌린다 — 이 PC 에 더해 둔 낱말이 분류 · 받기 테스트에 새어 들지 않게."""
    from app.services import collect_keywords_service

    monkeypatch.setattr(collect_keywords_service, "KEYWORDS_FILE", tmp_path / "collect_keywords.json")


@pytest.fixture()
def embedding_live_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """이 테스트는 **임베딩으로 바깥을 부르는 경로**를 잰다 (ISSUE-129 · prompt_05 §4-A).

    15차부터 임베딩도 기본이 꺼짐이다. 탐침·`embed()` 자체를 재는 테스트는 자기가 켰다고
    말해야 한다 — `live_fetch_on` 과 같은 규칙이다. 실제로 나가지는 않는다(`block_network`
    가 소켓을 막고, 이 픽스처를 쓰는 테스트는 `embed` 를 자기 가짜로 갈아 끼운다).
    """
    monkeypatch.setattr(get_settings(), "embedding_live", True)


@pytest.fixture()
def semantic_fit_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """이 테스트는 **의미 유사도를 점수에 쓰는 경로**를 잰다 (ISSUE-129 · prompt_05 §4-A).

    앞의 픽스처와 다른 문이다 — 이쪽을 켜도 바깥을 부르지는 않는다. 캐시(합성 벡터)에
    다 들어 있으면 `embed_cached` 가 나가지 않는다.
    """
    monkeypatch.setattr(get_settings(), "semantic_fit", True)


@pytest.fixture(autouse=True)
def notice_cache_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """공고 캐시를 테스트별 tmp 경로로 돌린다. 저장소의 실제 캐시를 건드리지 않는다.

    프로세스 메모리 캐시(_MEMO)도 함께 비운다 — 비우지 않으면 앞 테스트의 결과가
    다음 테스트로 새어 source가 'cached' 대신 'g2b'로 나온다.
    """
    cache_dir = tmp_path / "procurement_cache"
    cache_file = cache_dir / "g2b_cache.json"
    monkeypatch.setattr(procurement_service, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(procurement_service, "CACHE_FILE", cache_file)
    # 기준본(Git 추적)도 tmp 로 — 살아 있는 저장본이 없으면 기준본을 읽으므로 실제 파일이 새어 들어오지 않게(33차)
    monkeypatch.setattr(procurement_service, "BASELINE_CACHE_FILE", cache_dir / "baseline_g2b_cache.json")
    procurement_service.clear_memo()
    yield cache_file
    procurement_service.clear_memo()


@pytest.fixture(autouse=True)
def audit_log_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """활동 기록을 테스트별 tmp 경로로 돌린다. 사람의 실제 기록에 줄이 쌓이지 않게.

    지금은 `API_TOKEN` 이 비어 있으면 미들웨어가 기록 자체를 하지 않으므로 대부분의 테스트는
    이 안전망이 없어도 조용하다. 문제는 **앞으로** 누가 토큰을 켜고 쓰기를 하는 테스트를
    쓸 때다 — 그러면 pytest 를 돌릴 때마다 `data/private/audit_log.jsonl` 에 수백 줄이
    조용히 쌓인다. `data/private/` 는 gitignore 아래라 `git status` 로도 안 보인다.
    그래서 여기서 통째로 막아 둔다 (검수 권고, 2026-09-17).
    """
    path = tmp_path / "audit_log.jsonl"
    monkeypatch.setattr(audit_log_service, "AUDIT_LOG_FILE", path)
    return path


@pytest.fixture(autouse=True)
def lock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """파일 잠금 폴더를 테스트별 tmp 로 돌린다 (활동 기록과 같은 이유).

    `storage.locked()` 는 `data/private/.locks/` 에 경로 해시 이름으로 잠금 파일을 만든다.
    테스트가 쓰는 경로는 매번 다른 tmp 라, 그대로 두면 **실행할 때마다 새 파일이 쌓인다.**
    `data/private/` 는 gitignore 아래라 `git status` 에도 안 보인다 — 실제로 220개가
    쌓인 뒤에야 알아차렸다. 파일 하나가 1바이트라 해가 되지는 않지만, 사람의 데이터
    폴더에 테스트 찌꺼기를 남기지 않는다는 규칙이 더 중요하다.
    """
    path = tmp_path / "locks"
    monkeypatch.setattr(storage, "LOCK_DIR", path)
    return path


@pytest.fixture(autouse=True)
def offline_qualifications(monkeypatch: pytest.MonkeyPatch) -> None:
    """나라장터 **자격 제한 조회**를 기본으로 「받지 않음」으로 둔다 (0921 §4-A-1).

    `collect_candidates` 는 목록을 받은 뒤 면허제한·참가가능지역을 한 번 더 부른다. 목록
    조회만 monkeypatch 한 테스트가 수십 개라, 그대로 두면 전부 두 번째 문에서 실제
    네트워크로 나간다. 결론은 어차피 「못 받았다」이므로 **기다리지 않고** 같은 결론을 낸다.

    자격 정보를 실제로 보고 싶은 테스트는 자기 `monkeypatch` 로 덮어쓰면 된다 — 테스트
    본문의 setattr 이 나중에 실행되므로 이 픽스처를 이긴다.
    """

    from datetime import date as _date

    async def _none(day: _date, **_kwargs: object) -> object:
        return g2b_client.DayQualifications(
            day=day,
            licenses={},
            regions={},
            calls=0,
            complete=False,
            note="테스트 환경에서는 자격 제한을 받지 않습니다",
        )

    monkeypatch.setattr(g2b_client, "fetch_qualifications_for_day", _none, raising=False)


@pytest.fixture(autouse=True)
def clean_support_memo() -> None:
    """지원사업 판정 메모를 테스트마다 비운다 (0922 §4-D-3).

    메모 열쇠에 목록 출처·건수가 들어 있지만, 테스트는 같은 열쇠로 다른 것을 주입할 수 있다.
    한 테스트의 답이 다음 테스트로 새어 나가면 원인을 찾기 어려운 실패가 된다.
    """
    from app.services import opportunity_service

    opportunity_service.clear_support_memo()


@pytest.fixture(autouse=True)
def isolated_spec_doc_links(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """본공고 → 사전규격 규격서 연결 기록(11-03)을 테스트마다 빈 폴더로 — 실제 data/private/cache 에 쓰지 않게."""
    from app.services import prespec_service

    monkeypatch.setattr(prespec_service, "SPEC_LINKS_FILE", tmp_path_factory.mktemp("spec_links") / "spec_doc_links.json")


@pytest.fixture(autouse=True)
def isolated_qualification_store(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """자격 저장소를 테스트마다 빈 디렉터리로 둔다 (0922 §4-A-2).

    저장소는 `data/public/sample_procurements/qualifications/` 라 커밋된 파일이다. 테스트가
    거기에 쓰면 실제 자료가 바뀌고, 읽으면 테스트마다 답이 달라진다.
    """
    from app.services import qualification_store

    monkeypatch.setattr(
        qualification_store, "STORE_DIR", tmp_path_factory.mktemp("qualifications")
    )
    # 39차 D20 — 쓰기는 Git 밖 폴더 — 그것도 테스트마다 빈 디렉터리로
    monkeypatch.setattr(
        qualification_store, "PRIVATE_STORE_DIR", tmp_path_factory.mktemp("qualifications_private")
    )


@pytest.fixture(autouse=True)
def isolated_private_clauses(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Git 밖 조항 폴더(`data/private/qualification_clauses`)를 테스트마다 빈 디렉터리로 (11-09).

    직접 넣은 공고에 공고문을 올리는 테스트(`attach_document`)가 이 폴더에 `manual-<해시>.json` 을 썼다 —
    id 가 회사 · 주소 해시라 매번 같은 이름이어서 전체 시험마다 실제 저장본의 시각만 바뀌었다.
    """
    from app.services import qualification_clause_service

    monkeypatch.setattr(qualification_clause_service, "PRIVATE_CLAUSE_DIR", tmp_path_factory.mktemp("clauses_private"))


@pytest.fixture(autouse=True)
def isolated_clause_reviews(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """공개 시연 범위의 조항 확인 기록(`data/public/reviews/*.qualification_review.json`)을 떼어 둔다 (20차 §4-C).

    확인 기록은 판정(회사 쪽 사실)에 들어간다. 개발자가 화면에서 남긴 실제 기록이 테스트의 판정을
    바꾸면 안 된다 — 조직 범위 기록은 조직 폴더(`ORGANIZATIONS_DIR`)가 이미 임시 폴더다.
    """
    from app.services import qualification_review_service

    monkeypatch.setattr(qualification_review_service, "PUBLIC_DIR", tmp_path_factory.mktemp("clause_reviews"))


@pytest.fixture(autouse=True)
def offline_embedding_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """테스트에서 임베딩은 **언제나 쓸 수 없는 것**으로 둔다 (ISSUE-069).

    예전에는 키 «존재 여부»(`is_configured()`)로 대신했다. 개발자 `.env` 에 진짜 키가 있으면
    그 값이 `True` 가 되고, 그러면 의미 매칭이 실제 임베딩을 부르러 나간다. 네트워크는
    `block_network` 가 막지만 **openai SDK 는 그 실패를 재시도하며 백오프한다.** 공고 목록
    테스트는 공고 한 건마다 그 길을 가므로, 스위트 전체가 50초에서 **16분**으로 늘었다.
    개발자가 테스트를 안 돌리게 되는 값이다.

    `False` 로 고정하면 `embed_cached()` 가 임베딩을 부르기 전에 돌아서고, 목록·추천 테스트는
    키워드 경로로 간다 — 키가 없는 CI·다른 개발자 기계에서 이미 그러고 있던 동작과 같다.

    이 픽스처를 «끄고» 진짜 함수를 보고 싶은 테스트는 직접 되돌린다
    (`test_llm_unavailable.py`·`test_health_and_cors_hardening.py`·`test_embedding_probe.py`).
    의미 매칭의 계산 자체는 합성 벡터 픽스처로 검사한다 (`test_semantic_matching_order.py`).
    """
    monkeypatch.setattr(llm_client, "embedding_available", lambda **_kw: False, raising=False)


@pytest.fixture(autouse=True)
def offline_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """`llm_client.embed()` 자체도 **즉시** 실패시킨다.

    위 픽스처는 `embedding_available()` 을 보는 경로만 막는다. `embed()` 를 곧바로 부르는
    곳(색인 만들기 등)은 여전히 SDK 로 들어가 재시도·백오프를 기다린다. 결론은 어차피
    「못 쓴다」이므로, 같은 결론을 **기다리지 않고** 낸다.

    진짜 `embed` 를 보고 싶은 테스트는 자기 `monkeypatch` 로 덮어쓰면 된다 — 테스트 본문의
    setattr 이 나중에 실행되므로 이 픽스처를 이긴다.
    """

    def _offline(*_args: object, **_kwargs: object) -> list[list[float]]:
        raise llm_client.LLMUnavailableError("테스트 환경에서는 임베딩을 부르지 않습니다")

    monkeypatch.setattr(llm_client, "embed", _offline, raising=False)


@pytest.fixture(scope="session")
def _generated_sandbox(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """추적 중인 파싱 결과 폴더의 사본. 세션당 한 번만 만든다.

    비운 폴더를 쓰지 않는 이유: 많은 테스트가 여기 있는 합성 RFP 요구사항을 **읽는다**.
    비우면 그 테스트들이 「파싱된 적 없는 공고」로 떨어진다. 그래서 통째로 복사해
    읽기는 그대로 되게 하고, 쓰기만 tmp 로 흘려보낸다.
    """
    sandbox = tmp_path_factory.mktemp("rfp_generated")
    shutil.copytree(rfp_parser.GENERATED_DIR, sandbox, dirs_exist_ok=True)
    return sandbox


@pytest.fixture(autouse=True)
def audit_run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """검사 결과 폴더도 tmp 로 돌린다.

    `data/public/audit_runs/` 는 git 이 추적하지 않는 생성물이지만, 테스트가 거기에 쓰면
    실행할 때마다 실제 폴더가 불어나고 — 보존 상한(`prune_runs`)이 생긴 뒤로는 **줄어든다.**
    한 번의 pytest 로 288개가 정리됐다. 테스트가 사람의 작업 폴더를 건드릴 이유가 없다.
    """
    sandbox = tmp_path / "audit_runs"
    monkeypatch.setattr(auditor_service, "AUDIT_RUN_DIR", sandbox)
    return sandbox


@pytest.fixture(autouse=True)
def generated_dir(_generated_sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """모든 테스트를 사본 위에서 돌린다 — 저장소의 파일에는 손대지 않는다.

    `versions_dir()` 는 `generated_path().parent` 에서 나오므로 이 하나만 돌리면
    버전 보존 폴더까지 함께 따라온다.
    """
    monkeypatch.setattr(rfp_parser, "GENERATED_DIR", _generated_sandbox)
    return _generated_sandbox


@pytest.fixture(scope="session")
def raw_items() -> list[dict[str, Any]]:
    """저장해 둔 나라장터 실제 응답 item 목록 (서비스키 미포함)."""
    payload = json.loads(RAW_RESPONSE_SAMPLE.read_text(encoding="utf-8"))
    items = payload["items"]
    assert isinstance(items, list) and items
    return items


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# 조직(회사) 저장공간 격리 — 테스트는 절대 실제 data/private·data/company 를 읽거나 쓰지 않는다.
# ---------------------------------------------------------------------------
from app.core import org_storage as _org_storage  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_organizations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "organizations"
    monkeypatch.setattr(_org_storage, "ORGANIZATIONS_DIR", root)
    monkeypatch.setattr(_org_storage, "LEGACY_COMPANY_DIR", tmp_path / "legacy_company")
    return root
