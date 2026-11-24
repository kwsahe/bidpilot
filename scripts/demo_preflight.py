#!/usr/bin/env python
r"""시연 30분 전에 돌리는 점검 (ISSUE-055·056 · 0917.md §4-1-4).

## 왜 필요한가

시연이 깨지는 방식은 늘 같았다. 서버가 안 떠 있거나, 화면에 옛 결과가 남아 있거나,
큐시트가 가리키는 공고가 선택기에 없다. 셋 다 **누르기 전에** 알 수 있는 것들인데,
알려면 여러 곳을 따로 열어 봐야 했다.

이 스크립트는 그 확인을 한 번에 한다. 고치지는 않는다 — 무엇이 어긋났는지만 말한다.
고치는 방법은 각 줄에 함께 적는다.

    backend\.venv\Scripts\python.exe scripts\demo_preflight.py
    backend\.venv\Scripts\python.exe scripts\demo_preflight.py --backend http://127.0.0.1:8110 --frontend http://localhost:3110

    (시스템 python 으로도 돌지만 AI 초안 공급자가 claude_cli 이면 백엔드 모듈이 필요해 「막는 문제」로 알린다.)

종료 코드: 0 = 전부 통과, 1 = 빨간 줄이 하나라도 있음.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KST = timezone(timedelta(hours=9))

#: 시연 동선이 반드시 필요로 하는 공고. 큐시트와 같아야 한다.
DEMO_PROCUREMENT_ID = "synthetic-rfp-0001"

OK = "  [OK]  "
WARN = "  [주의] "
BAD = "  [!!]  "

_failures: list[str] = []
_warnings: list[str] = []


def ok(message: str) -> None:
    print(f"{OK}{message}")


def warn(message: str, fix: str = "") -> None:
    _warnings.append(message)
    print(f"{WARN}{message}" + (f"\n         → {fix}" if fix else ""))


def bad(message: str, fix: str = "") -> None:
    _failures.append(message)
    print(f"{BAD}{message}" + (f"\n         → {fix}" if fix else ""))


def section(title: str) -> None:
    print(f"\n== {title}")


def fetch(url: str, timeout: float = 10.0):
    """(상태코드, 본문). 못 붙으면 (None, 사유)."""
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310 — 로컬 주소만 쓴다
            return response.status, response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except (URLError, OSError, ValueError) as exc:
        return None, str(exc)


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 점검 항목
# ---------------------------------------------------------------------------


def check_servers(backend: str, frontend: str) -> dict | None:
    section("서버")
    status, body = fetch(f"{backend}/health")
    health = None
    if status != 200:
        bad(f"백엔드가 응답하지 않습니다 ({backend}) — {body[:80]}", "scripts/start_dev.ps1 -NoBrowser")
    else:
        # 8110 에 다른 프로그램이 떠 있으면 JSON 이 아니거나 우리 서비스가 아니다 — 멈추지 않고 알린다(36차 KIT-R35-02)
        try:
            health = json.loads(body)
        except ValueError:
            health = None
        if not isinstance(health, dict) or health.get("service") != "bidpilot-api":
            bad(f"{backend}/health 가 BidPilot 백엔드가 아닙니다 — {str(body)[:80]}", "다른 프로그램이 그 포트를 쓰는지 확인 · scripts/stop_dev.ps1 뒤 start_dev.bat")
            health = None
        else:
            ok(f"백엔드 200 · 공고 API 키 {'있음' if health.get('g2b_api_configured') else '없음'}")

    status, body = fetch(frontend, timeout=20.0)
    if status != 200:
        bad(f"화면이 응답하지 않습니다 ({frontend}) — {str(body)[:80]}", "scripts/start_dev.ps1 -NoBrowser")
    elif not re.search(r"<title>[^<]*BidPilot AI", str(body)):
        # start_dev 와 같은 판별 — 200 이면 무엇이든 OK 였다(저장소 폴더를 띄운 다른 http 서버도 200)
        bad(f"{frontend} 는 BidPilot 화면이 아닙니다(페이지 제목에 「BidPilot AI」 없음)", "다른 프로그램이 그 포트를 쓰는지 확인 · scripts/stop_dev.ps1 뒤 start_dev.bat")
    else:
        ok(f"화면 200 ({frontend} · BidPilot AI)")
    return health


def check_ai_key(health: dict | None) -> None:
    section("AI 검색 설정")
    if health is None:
        warn("백엔드를 못 읽어 확인할 수 없습니다")
        return
    if health.get("embedding_available"):
        ok("AI 검색 사용 가능 — 근거 연결·의미 매칭이 실제로 돕니다")
    else:
        # 이것은 시연을 막지 않는다. 규칙 경로는 키 없이도 전부 돈다.
        warn(
            "AI 검색을 쓸 수 없습니다 (키가 없거나 크레딧 부족)",
            "규칙 경로는 그대로 돕니다. 화면은 「AI 검색 설정이 잘못되었습니다」를 사유로 보여 줍니다. "
            "근거 연결·의미 매칭 장면은 건너뛰거나 사유를 그대로 읽어 주세요.",
        )


def check_completion_provider(health: dict | None) -> None:
    """AI 초안 공급자 한 줄 (25차 §4-A-6) — openai | xai · 모델 · 꺼짐/켜짐. 키 값은 보지 않는다."""
    section("AI 초안 공급자")
    if health is None:
        warn("백엔드를 못 읽어 확인할 수 없습니다")
        return
    provider = health.get("llm_provider") or "?"
    model = health.get("llm_model") or "?"
    live = "켜짐" if health.get("llm_live") else "꺼짐"
    # 사업계획서 작성 페이지 문 (28차 §3-D · 29차 §3-A) — 켜져 있으면 /plan 단추만 이 PC 의 Claude · Codex CLI 를 부른다.
    # 모델 이름은 서버 설정에서 읽는다(29차 R28-18 — 예전엔 고정값을 적었다).
    if health.get("plan_writer_cli"):
        check_claude_login(health.get("plan_writer_model") or "?", "사업계획서 작성 단추만")
        check_codex_login(health.get("plan_writer_codex_model") or "?")
    else:
        ok("사업계획서 작성(Claude · Codex) 꺼짐 — /plan 은 저장본 보기 · 규칙 초안만(켜려면 start_demo_claude.bat)")
    if provider == "claude_cli":
        check_claude_login(model, live)
        return
    credit = "크레딧 확인됨" if health.get("llm_credit_ok") else "크레딧 미확인(규칙 초안으로 간다)"
    ok(f"AI 초안 공급자 {provider} · 모델 {model} · {live} · {credit}")


def _backend_cli() -> tuple[str | None, str | None, dict | None, str | None]:
    """백엔드가 **실제로 부를** CLI 와 환경 — `llm_client.claude_cli_path()` · `cli_env()` 그대로 (26차 ISSUE-153).

    예전에는 PATH 의 `claude` 를 부모 환경 그대로 확인했다 — 백엔드는 `CLAUDE_CLI_PATH` + `cli_env()` 를 쓰므로
    여기는 초록불인데 실제로는 실패할 수 있었다. → (찾은 파일, 부를 파일, 환경, 읽지 못한 사유)
    """
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        from app.services import llm_client
    except Exception as exc:  # noqa: BLE001 — 시스템 python 이면 백엔드 패키지가 없다
        return None, None, None, f"백엔드 모듈을 읽지 못했습니다({type(exc).__name__}) — backend\\.venv\\Scripts\\python.exe 로 실행하세요"
    return llm_client.claude_cli_candidate(), llm_client.claude_cli_path(), llm_client.cli_env(os.environ), None


def check_claude_login(model: str, live: str) -> None:
    """`claude_cli` — 이 PC 의 Claude Code CLI 로그인. `claude auth status` 는 로컬만 읽는다(모델을 부르지 않는다)."""
    candidate, exe, env, problem = _backend_cli()
    if problem:
        # 공급자가 claude_cli 인데 로그인을 확인하지 못했다 — 막는다(시연 중 절마다 규칙 초안으로 떨어질 수 있다 · 26차 검수).
        bad(f"AI 초안 공급자 claude_cli · 모델 {model} · {live} · CLI 확인 못 함", problem)
        return
    if exe is None:
        if candidate and candidate.lower().endswith((".cmd", ".bat")):
            bad(f"AI 초안 공급자 claude_cli · 모델 {model} · {live} · npm 판 {Path(candidate).name} 는 지원하지 않습니다",
                "네이티브 설치(claude.exe)를 쓰세요 — cmd.exe 가 여러 줄 지시를 첫 줄에서 자릅니다")
        else:
            bad(f"AI 초안 공급자 claude_cli · 모델 {model} · {live} · CLI 없음(CLAUDE_CLI_PATH · PATH)",
                "이 PC 에 Claude Code 를 설치하거나 CLAUDE_CLI_PATH 에 claude.exe 경로를 적으세요")
        return
    # 로그인 읽기는 백엔드와 한 곳(llm_client.claude_cli_auth_status · 28차 — 사업계획서 작성 상태 API 도 이것을 쓴다)
    from app.services import llm_client  # _backend_cli 가 backend 경로를 넣었다

    status = llm_client.claude_cli_auth_status(timeout=30)
    if not status.get("loggedIn"):
        bad(f"AI 초안 공급자 claude_cli · 모델 {model} · {live} · CLI 로그인 안 됨",
            "이 PC 에서 claude auth login 으로 로그인하세요 (안 되면 절마다 규칙 초안으로 간다)")
        return
    ok(f"AI 초안 공급자 claude_cli(구독 CLI) · 모델 {model} · {live} · 로그인 {status.get('authMethod')}"
       f"({status.get('subscriptionType') or '?'})")
    if status.get("subscriptionType") in ("free", "pro", "max"):
        warn("개인 요금제입니다 — claude.ai 설정 → 개인정보 → 「Claude 개선에 도움 주기」가 꺼져 있는지 확인",
             "켜져 있으면 사업계획서 초안(회사 실적)이 모델 학습에 쓰일 수 있습니다")


def check_codex_login(model: str) -> None:
    """사업계획서 작성(Codex) — 이 PC 의 Codex CLI 로그인 (29차 §3-A). `codex login status` 는 로컬만 읽는다.

    Claude 와 나란히 고르는 두 번째 길이라 없거나 로그인이 안 되어도 **막지 않는다**(그 단추만 비활성 + 이유).
    """
    candidate, exe, env, problem = _backend_cli()
    if problem:
        warn(f"사업계획서 작성(Codex) · 모델 {model} · CLI 확인 못 함", problem)
        return
    from app.services import llm_client  # _backend_cli 가 backend 경로를 넣었다

    if llm_client.codex_cli_path() is None:
        warn(f"사업계획서 작성(Codex) · 모델 {model} · CLI 없음(CODEX_CLI_PATH · PATH)",
             "Codex 단추는 비활성으로 보입니다 — 쓰려면 Codex 를 설치하고 codex login 으로 로그인하세요")
        return
    status = llm_client.codex_cli_login_status(timeout=30)
    if not status.get("logged_in"):
        warn(f"사업계획서 작성(Codex) · 모델 {model} · CLI 로그인 안 됨", "이 PC 에서 codex login 으로 로그인하세요")
        return
    ok(f"사업계획서 작성(Codex · 구독 CLI) · 모델 {model} · 로그인 {status.get('auth_method') or '?'}")
    if status.get("auth_method") == "chatgpt":
        warn("ChatGPT 로그인입니다 — 개인 요금제면 chatgpt.com 설정 → 데이터 제어 → 「모두를 위한 모델 개선」이 꺼져 있는지 확인",
             "켜져 있으면 사업계획서 초안(회사 실적)이 모델 학습에 쓰일 수 있습니다")


def check_freeze_mode(health: dict | None) -> None:
    """시연 고정 모드인가 (ISSUE-062).

    막는 문제로 다루는 이유: 키가 실린 채 고정이 아니면, 목록을 한 번 여는 것만으로
    나라장터를 부르고 **큐시트가 가리키는 숫자가 바뀐다.** 게다가 그 결과가 Git 이
    추적하는 캐시 파일을 덮어써서 되돌리려면 `git checkout` 이 필요하다.
    시연 30분 전에 알아야 할 것이 있다면 이것이다.
    """
    section("시연 고정 모드")
    if health is None:
        warn("백엔드를 못 읽어 확인할 수 없습니다")
        return
    frozen = bool(health.get("live_fetch_frozen"))
    key = bool(health.get("g2b_api_configured"))
    if frozen:
        ok("고정 모드 — 목록은 저장된 자료만 씁니다 (실호출 없음)")
        return
    if key:
        bad(
            "실호출 모드인데 나라장터 키가 있습니다 — 목록을 열면 공고가 바뀔 수 있습니다",
            "서버를 내리고 scripts/start_dev.bat(저장본 + Claude · Codex 단추) 또는 scripts/start_demo.bat 으로 다시 띄우세요.",
        )
    else:
        warn(
            "고정 모드가 아닙니다 (키가 없어 실호출은 실패하지만, 목록 출처가 「캐시」로만 표시됩니다)",
            "시연에는 scripts/start_demo.bat 으로 띄우는 편이 낫습니다 — 화면이 「시연 고정 모드」라고 말해 줍니다.",
        )


def check_attachment_fetch(health: dict | None) -> None:
    """첨부 자동 받기 (27차 §3-A · §3-I) — 꺼져 있어야 목록 · 대시보드가 저절로 나라장터 첨부를 받지 않는다."""
    section("첨부 받기")
    if health is None or "attachment_fetch" not in health:
        warn("백엔드가 첨부 받기 설정을 알려 주지 않습니다 — 서버를 새로 띄우세요")
        return
    if health["attachment_fetch"]:
        warn(
            "첨부 자동 받기가 켜져 있습니다 — 요구사항을 열면 제안요청서를 저절로 받습니다",
            "시연에는 끈 설정으로 띄우세요(기본값이 꺼짐).",
        )
    else:
        ok("첨부 자동 받기 꺼짐 · 사람이 확인한 제안요청서 1건 받기 가능(사업기회 › 요구사항 정리표 확인 창 · 인터넷 필요)")


def _local_ipv4_addresses() -> list[str]:
    """이 컴퓨터의 루프백이 아닌 IPv4 주소들. 못 구하면 빈 목록."""
    found: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if not address.startswith("127.") and address not in found:
                found.append(address)
    except OSError:
        pass
    return found


def check_backend_host(backend: str) -> None:
    """백엔드가 바깥(LAN)에도 열려 있는지 (ISSUE-063).

    `/health` 만 봐서는 알 수 없다 — 어느 주소로 물어도 같은 답이 온다. 그래서 **이 컴퓨터의
    LAN 주소로 직접 붙어 본다.** 붙으면 `--host 0.0.0.0` 으로 떠 있다는 뜻이고, 그러면 같은
    공유기에 있는 누구나 인증 없이 회사자료 API 를 부를 수 있다.
    """
    section("백엔드 접근 범위")
    try:
        port = int(backend.rsplit(":", 1)[-1].split("/")[0])
    except (ValueError, IndexError):
        warn(f"백엔드 주소에서 포트를 읽지 못했습니다 ({backend})")
        return
    addresses = _local_ipv4_addresses()
    if not addresses:
        warn("이 컴퓨터의 LAN 주소를 찾지 못해 확인하지 못했습니다")
        return
    reachable = []
    for address in addresses:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(1.0)
            if probe.connect_ex((address, port)) == 0:
                reachable.append(address)
    if reachable:
        bad(
            f"백엔드가 LAN 에도 열려 있습니다 ({', '.join(reachable)}:{port}) — 같은 공유기의 누구나 부를 수 있습니다",
            "손으로 띄운 uvicorn(--host 0.0.0.0)일 가능성이 높습니다. "
            "scripts/stop_dev.ps1 로 내리고 scripts/start_demo.bat 으로 다시 띄우세요 (127.0.0.1 전용).",
        )
    else:
        ok(f"127.0.0.1 에서만 열려 있습니다 (LAN 주소 {len(addresses)}개에서 접속 안 됨)")


def check_demo_conditions(backend: str) -> None:
    section("데모 공고 조건·할 일")
    status, body = fetch(f"{backend}/api/conditions/{DEMO_PROCUREMENT_ID}")
    if status != 200:
        bad(f"조건을 읽지 못했습니다 (HTTP {status})", "백엔드 로그를 확인하세요")
        return
    report = json.loads(body)
    freshness = report.get("freshness")
    if freshness == "current":
        ok(f"조건 {len(report.get('conditions', []))}건 · 지금 요구사항 기준")
    else:
        bad(
            f"조건 보고서가 「{freshness}」 — 화면에 「조건을 다시 찾아야 합니다」 경고가 뜹니다",
            'curl -X POST .../api/conditions/detect -d \'{"procurement_id":"synthetic-rfp-0001"}\'',
        )

    staffing_on_021 = [
        c for c in report.get("conditions", [])
        if c.get("requirement_id") == "REQ-021" and c.get("condition_type") == "staffing"
    ]
    if staffing_on_021:
        bad("REQ-021 에 인력 요건 오탐이 남아 있습니다", "조건을 다시 탐지하세요 (규칙은 이미 고쳐져 있습니다)")
    else:
        ok("REQ-021 인력 요건 오탐 없음")

    status, body = fetch(f"{backend}/api/actions/{DEMO_PROCUREMENT_ID}")
    if status != 200:
        bad(f"할 일 목록을 읽지 못했습니다 (HTTP {status})")
        return
    items = json.loads(body).get("items", [])
    titles = [i.get("title") for i in items]
    duplicates = {t for t in titles if titles.count(t) > 1}
    if duplicates:
        bad(f"할 일 제목이 겹칩니다: {sorted(duplicates)}", "python scripts/dedupe_action_titles.py --prune-orphans --write")
    else:
        ok(f"할 일 {len(items)}건 · 제목 중복 없음")

    live = {c.get("id") for c in report.get("conditions", [])}
    orphans = [i for i in items if i.get("source_condition_id") and i["source_condition_id"] not in live]
    if orphans:
        bad(
            f"근거가 사라진 할 일 {len(orphans)}건 (조건이 더 이상 없습니다)",
            "python scripts/dedupe_action_titles.py --prune-orphans --write",
        )
    else:
        ok("모든 할 일이 살아 있는 조건에 붙어 있음")


def check_notice_picker(backend: str) -> None:
    section("공고 선택기")
    status, body = fetch(f"{backend}/api/procurements")
    if status != 200:
        bad(f"공고 목록을 읽지 못했습니다 (HTTP {status})", "나라장터 조회 실패 시 캐시가 쓰입니다 — 캐시도 없으면 503")
        return
    payload = json.loads(body)
    notices = payload.get("notices", [])
    ok(f"목록 {len(notices)}건 · 출처 {payload.get('source')}")

    pinned = read_json(DATA / "public" / "sample_procurements" / "pinned_notices.json") or {}
    pinned_ids = [
        (n.get("notice") or n).get("id")
        for n in (pinned.get("notices") or pinned.get("items") or [])
    ]
    listed = {n.get("id") for n in notices}
    missing = [pid for pid in pinned_ids if pid and pid not in listed]
    if missing:
        bad(f"시연용 고정 공고가 목록에 없습니다: {missing}", "data/public/sample_procurements/pinned_notices.json 확인")
    else:
        ok(f"시연용 고정 공고 {len(pinned_ids)}건 전부 목록에 있음")

    # 첨부 로컬 캐시 (19차 §4-A-4). 고정 모드에서는 첨부를 새로 받지 않는다(`ATTACHMENT_FETCH` 꺼짐) —
    # 시연 공고의 공고문·제안요청서가 디스크에 없으면 4단계·3단계가 그 자리에서 멈춘다.
    real_rfp = DATA / "public" / "real_rfp"
    clause_dir = DATA / "public" / "sample_procurements" / "qualification_clauses"
    lacking: list[str] = []
    clause_ok = 0
    for pid in [p for p in pinned_ids if p]:
        names = [f.name for f in (real_rfp / pid).glob("*")] if (real_rfp / pid).is_dir() else []
        notice_doc = any("공고" in n and "제안요청" not in n for n in names)
        rfp_doc = any("제안요청" in n or "과업" in n or n.lower().endswith(".zip") for n in names)
        if not (notice_doc and rfp_doc):
            lacking.append(f"{pid}(공고문 {'있음' if notice_doc else '없음'} · 제안요청서 {'있음' if rfp_doc else '없음'})")
        clause = read_json(clause_dir / f"{pid}.json") or {}
        clause_ok += clause.get("status") == "ok"
    if lacking:
        warn(
            f"시연용 공고 첨부가 로컬 캐시에 없습니다: {lacking}",
            "고정 모드에서는 새로 받지 않습니다 — 받으려면 "
            "backend\\.venv\\Scripts\\python.exe scripts\\fetch_qualification_clauses.py --ids <공고 id>",
        )
    else:
        ok(f"시연용 {len(pinned_ids)}건 첨부 로컬 캐시 있음 · 참가자격 조항 파일 {clause_ok}/{len(pinned_ids)}건 읽음")

    now = datetime.now(KST)
    closed = []
    for notice in notices:
        if notice.get("id") not in pinned_ids:
            continue
        deadline = notice.get("deadline_at")
        if deadline and datetime.fromisoformat(deadline) < now:
            closed.append(notice.get("id"))
    if closed:
        # 마감이어도 시연은 된다 — 저장된 자료로 분석 화면이 열린다. 다만 알고 있어야 한다.
        warn(
            f"시연용 공고 {len(closed)}건이 이미 마감입니다: {closed}",
            "선택기 「시연용 (마감)」 그룹에서 고르면 분석 화면이 열립니다. 마감 배지는 그대로 보입니다.",
        )
    else:
        ok("시연용 공고 전부 마감 전")


def check_saved_results(backend: str) -> None:
    section("저장된 분석 결과 (데모 공고)")
    for label, path in (
        ("요구사항", f"/api/rfp/{DEMO_PROCUREMENT_ID}/requirements"),
        ("제안서 초안", f"/api/proposal/{DEMO_PROCUREMENT_ID}"),
    ):
        status, body = fetch(f"{backend}{path}")
        if status == 200:
            payload = json.loads(body)
            count = len(payload.get("requirements") or payload.get("sentences") or [])
            ok(f"{label} 있음 ({count}건)")
        else:
            bad(f"{label}이 없습니다 (HTTP {status})", "시연 전에 한 번 생성해 두세요")

    runs = sorted((DATA / "public" / "audit_runs").glob("audit-*.json")) if (DATA / "public" / "audit_runs").exists() else []
    if runs:
        ok(f"제출 전 점검 결과 파일 {len(runs)}건 보관 중")
    else:
        warn("저장된 점검 결과가 없습니다", "시연에서 붙여넣기로 새로 돌리면 되지만, 미리 한 번 돌려 두면 안전합니다")


LIVE_CACHE = DATA / "private" / "cache" / "g2b" / "g2b_cache.json"
BASELINE_CACHE = DATA / "public" / "sample_procurements" / "g2b_cache.json"
TASK_NAME = "BidPilot-DailyCollect"


def _live_cache() -> dict | None:
    """서버가 읽는 살아 있는 저장본 — 읽을 수 있을 때만(서버 `cache_read_path` 와 같은 규칙 · 34차 R33-R1)."""
    payload = read_json(LIVE_CACHE) if LIVE_CACHE.exists() else None
    return payload if isinstance(payload, dict) and isinstance(payload.get("notices"), list) else None


def check_cache_age() -> None:
    section("캐시 시각")
    # 살아 있는 저장본(Git 밖 · 매일 아침 자동 받기)을 읽을 수 있으면 그것, 아니면 기준본 — 서버와 같은 규칙
    live_payload = _live_cache()
    live = LIVE_CACHE if live_payload is not None else None
    cache = live_payload if live_payload is not None else read_json(BASELINE_CACHE)
    if not cache:
        warn("공고 캐시를 읽지 못했습니다")
        return
    fetched = cache.get("fetched_at")
    if not fetched:
        warn("캐시에 받은 시각이 없습니다")
        return
    moment = datetime.fromisoformat(fetched)
    age = datetime.now(moment.tzinfo or KST) - moment
    text = f"공고 캐시({'살아 있는 저장본' if live else '기준본'}) {moment.astimezone(KST):%Y-%m-%d %H:%M} KST ({age.days}일 전)"
    # 나라장터는 한도가 있어 자주 못 부른다. 오래됐다고 고장은 아니지만 알고 있어야 한다.
    (ok if age.days <= 3 else warn)(text)


def check_cache_unchanged() -> None:
    """기준본(장애 대비 예시)이 커밋된 것과 같은가.

    33차부터 받기는 살아 있는 저장본(`data/private/cache/g2b/` · Git 밖)에만 쓴다. 추적 파일은 기준본이라
    담당자가 정해 복사 · 커밋할 때만 바뀐다 — 다르면 누가 손으로 덮어쓴 것이다.
    """
    section("시연 자료가 그대로인가")
    rel = "data/public/sample_procurements/g2b_cache.json"
    try:
        changed = subprocess.run(
            ["git", "diff", "--quiet", "--", rel],
            cwd=ROOT, capture_output=True, timeout=20,
        ).returncode
    except (OSError, subprocess.SubprocessError):
        warn("git 으로 확인하지 못했습니다 (저장소 밖에서 실행했을 수 있습니다)")
        return
    if changed == 0:
        ok("공고 기준본이 커밋된 것과 같습니다 (살아 있는 저장본은 Git 밖)")
        return
    warn(
        "공고 기준본이 커밋된 것과 다릅니다 — 받기는 이 파일에 쓰지 않으니 손으로 덮어쓴 것입니다",
        f"되돌리려면: git checkout -- {rel}",
    )


def check_scheduled_task() -> None:
    """자동 받기(예약 작업 · 40차 D30 로그온 · 잠금 해제 · 07:30 · 하루 한 번)가 켜져 있으면 시연 중 목록이 바뀔 수 있다(34차 R33-R2).

    `.env` 나 서버 `-Frozen` 으로는 이 작업이 멈추지 않는다 — 끄는 길은 `Disable-ScheduledTask` 뿐이다.
    """
    section("자동 받기(하루 한 번)")
    command = (
        f"$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue; "
        "if ($t) { $i = Get-ScheduledTaskInfo -TaskName $t.TaskName; "
        "'{0}|{1:yyyy-MM-dd HH:mm}|{2:yyyy-MM-dd HH:mm}|{3}' -f $t.State, $i.LastRunTime, $i.NextRunTime, $i.LastTaskResult } "
        "else { 'NONE' }"
    )
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        warn("예약 작업 상태를 읽지 못했습니다 (PowerShell 없음)", f"직접 확인: Get-ScheduledTask -TaskName {TASK_NAME}")
        return
    out = (done.stdout or "").strip()
    # 「없음 OK」는 조회가 성공해 정확히 NONE 을 돌려줬을 때만 — 실패 · 오류 · 빈 출력은 모르는 것이다(35차 R34-S1)
    if done.returncode != 0 or (done.stderr or "").strip() or not out:
        warn(
            "예약 작업 상태를 읽지 못했습니다 — 직접 확인하세요",
            f"Get-ScheduledTask -TaskName {TASK_NAME} (rc {done.returncode}{' · 오류 출력 있음' if (done.stderr or '').strip() else ''})",
        )
        return
    if out == "NONE":
        ok(f"예약 작업 {TASK_NAME} 없음 — 시연 중 목록이 저절로 바뀌지 않습니다")
        return
    state, last, upcoming, result = (out.split("|") + ["", "", "", ""])[:4]
    if state in ("Ready", "Running"):
        warn(
            f"자동 받기가 켜져 있어 시연 중 목록이 바뀔 수 있습니다 — {TASK_NAME} {state} · 마지막 {last} (결과 {result}) · 다음 {upcoming}",
            f"시연 · 검수 동안 끄기: Disable-ScheduledTask -TaskName {TASK_NAME} (끝나면 Enable-ScheduledTask)",
        )
    else:
        ok(f"자동 받기 {TASK_NAME} {state} — 시연 중 목록이 저절로 바뀌지 않습니다")


#: 받을 때마다 바뀌는 키 — 내용 비교에서 뺀다(서버 `procurement_service._CACHE_VOLATILE_KEYS` 와 같음).
_VOLATILE_KEYS = ("fetched_at", "stored_at", "updated_at", "collect_calls")


def _content(payload: dict) -> str:
    """바뀌는 키를 뺀 공고 목록 — 정렬한 JSON 글."""
    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in _VOLATILE_KEYS}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value
    return json.dumps(strip(payload.get("notices") or []), ensure_ascii=False, sort_keys=True)


def check_live_vs_baseline() -> None:
    """서버가 보여 주는 목록(살아 있는 저장본)이 큐시트 기준본과 같은가(34차 R33-R2).

    「기준본이 커밋된 것과 같다」만 보면 매일 자동 받기가 시연 숫자를 바꿔도 모두 정상이었다 — 서버는 살아 있는 저장본을 읽는다.
    """
    section("서버가 보여 주는 목록 = 기준본?")
    live = _live_cache()
    if live is None:
        ok("살아 있는 저장본이 없어 서버가 기준본을 그대로 보여 줍니다")
        return
    base = read_json(BASELINE_CACHE) or {}

    def ids(payload: dict) -> set[str]:
        return {str((n.get("notice") or {}).get("id")) for n in payload.get("notices") or []}

    live_ids, base_ids = ids(live), ids(base)
    # 받은 시각 · id 만 보면 백필로 자격 값이 바뀌어도 OK 였다 — 바뀌는 키(받은 시각 등)를 뺀 공고 내용까지 견준다(35차 R34-S2)
    same_content = _content(live) == _content(base)
    if same_content and live.get("fetched_at") == base.get("fetched_at"):
        ok(f"살아 있는 저장본 = 기준본 (받은 시각 {live.get('fetched_at')} · 공고 내용도 같음)")
        return
    if same_content:
        ok(f"살아 있는 저장본과 기준본의 공고 내용이 같습니다 (받은 시각만 다름: {live.get('fetched_at')} · {base.get('fetched_at')})")
        return
    if live_ids == base_ids and live.get("fetched_at") == base.get("fetched_at"):
        # id · 받은 시각이 같은데 내용만 다르다 — 「받은 시각이 다릅니다」라고 적으면 틀린 말이었다(36차 KIT-R35-04)
        warn(
            f"받은 시각은 같은데 공고 내용이 다릅니다(받은 시각 {live.get('fetched_at')}) — 자격 하루치를 다시 받았거나 "
            "손으로 고친 저장본일 수 있습니다",
            "숫자는 그날 화면 값으로 말한다(체크리스트 4)",
        )
        return
    if live_ids == base_ids:
        warn(
            f"서버가 보여 주는 목록은 기준본과 공고는 같지만 받은 시각이 다릅니다(살아 있는 저장본 {live.get('fetched_at')} · "
            f"기준본 {base.get('fetched_at')}) — 마감 · 자격 같은 내용이 다를 수 있습니다",
            "숫자는 그날 화면 값으로 말한다(체크리스트 4)",
        )
        return
    warn(
        f"서버가 보여 주는 목록이 큐시트 기준본과 다릅니다 — 살아 있는 저장본 받은 시각 {live.get('fetched_at')} · "
        f"기준본 {base.get('fetched_at')} · 공고 더해짐 {len(live_ids - base_ids)} · 빠짐 {len(base_ids - live_ids)}",
        "숫자는 그날 화면 값으로 말한다(체크리스트 4) · 기준본에 맞추려면 담당자가 살아 있는 저장본을 기준본으로 복사해 커밋",
    )


def check_llm_usage() -> None:
    section("LLM 호출 누계")
    usage = DATA / "private" / "llm_usage.jsonl"
    if not usage.exists():
        ok("기록 없음 (호출 0회)")
        return
    lines = [l for l in usage.read_text(encoding="utf-8").splitlines() if l.strip()]
    total = 0
    for line in lines:
        try:
            total += int(json.loads(line).get("calls", 1))
        except ValueError:
            continue
    ok(f"기록 {len(lines)}줄 · 호출 누계 {total}회")


def check_view_mode_default() -> None:
    """첫 방문 기본 보기 (24차) — 시연은 전체 보기이므로 주소에 mode=full 을 붙인다."""
    section("첫 방문 기본 보기")
    source = ROOT / "frontend" / "src" / "lib" / "viewMode.ts"
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        warn("viewMode.ts 를 읽지 못했습니다", "frontend/src/lib/viewMode.ts 가 있는지 확인")
        return
    marker = 'DEFAULT_VIEW_MODE: DisplayMode = "'
    value = text.split(marker, 1)[1].split('"', 1)[0] if marker in text else "?"
    label = {"simple": "쉬운 보기", "full": "전체 보기"}.get(value, value)
    ok(f"DEFAULT_VIEW_MODE = {value} ({label}) — 시연 탭은 ?mode=full 로 연다(큐시트 「발표 30분 전」)")


def check_demo_deadline() -> None:
    """데모 공고 마감 (ISSUE-160 · 27차 §3-F) — 날짜는 화면을 연 시각 기준이다. 규칙은 demoNotice.ts 한 곳."""
    section("데모 공고 날짜")
    source = ROOT / "frontend" / "src" / "lib" / "cosmos" / "demoNotice.ts"
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        warn("demoNotice.ts 를 읽지 못했습니다", "frontend/src/lib/cosmos/demoNotice.ts 가 있는지 확인")
        return

    def number(name: str) -> int | None:
        marker = f"export const {name} = "
        if marker not in text:
            return None
        raw = text.split(marker, 1)[1].split(";", 1)[0].strip()
        return int(raw) if raw.isdigit() else None

    deadline_days = number("DEMO_DEADLINE_DAYS")
    published_days = number("DEMO_PUBLISHED_DAYS_AGO")
    if deadline_days is None:
        bad("데모 공고 마감 규칙(DEMO_DEADLINE_DAYS)을 찾지 못했습니다 — 날짜가 박혀 있으면 그날이 지나 첫 화면이 「입찰 종료」로 열립니다",
            "frontend/src/lib/cosmos/demoNotice.ts 확인")
        return
    ok(f"데모 공고 마감 D-{deadline_days}(로드 시각 기준) · 공고일 {published_days}일 전 — 화면을 연 날부터 셉니다(RFP 원문 속 날짜는 그대로)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", default="http://127.0.0.1:8110")
    parser.add_argument("--frontend", default="http://localhost:3110")
    args = parser.parse_args()

    print("BidPilot AI — 시연 전 점검")
    health = check_servers(args.backend, args.frontend)
    check_freeze_mode(health)
    check_attachment_fetch(health)
    check_backend_host(args.backend)
    check_ai_key(health)
    check_completion_provider(health)
    if health is not None:
        check_demo_conditions(args.backend)
        check_notice_picker(args.backend)
        check_saved_results(args.backend)
    check_cache_age()
    check_cache_unchanged()
    check_scheduled_task()
    check_live_vs_baseline()
    check_llm_usage()
    check_view_mode_default()
    check_demo_deadline()

    print()
    if _failures:
        print(f"막는 문제 {len(_failures)}건 · 알아 둘 것 {len(_warnings)}건")
        for item in _failures:
            print(f"  - {item}")
        return 1
    print(f"막는 문제 없음 · 알아 둘 것 {len(_warnings)}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
