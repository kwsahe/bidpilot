import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    audit_log,
    auditor,
    capability,
    company,
    conditions,
    demo,
    eligibility,
    insights,
    manual,
    notice_qa,
    organizations,
    procurement,
    proposal,
    review,
    rfp,
    templates,
)

# 로그인 API. `app.core.auth`(토큰 미들웨어)와 이름이 겹쳐 헷갈리므로 별칭을 준다.
from app.api import auth as auth_api
from app.core.auth import TokenAuthMiddleware, token_required
from app.core.config import get_settings
from app.core import storage
from app.services import analysis_store, attachment_service, bizinfo_service, g2b_client, llm_client, procurement_service, semantic_matcher
from app.services import collect_keywords_service, support_application_service

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """기동 직후 AI 검색 사용 가능 여부를 **백그라운드에서** 한 번 잰다.

    예전에는 첫 `/health` 가 그 측정을 동기로 했다. 외부망이 막힌 서버에서는 SDK 기본
    타임아웃(60초)과 재시도 때문에 첫 응답이 수십 초 걸려, 컨테이너·nginx 헬스체크가
    기동 직후 실패할 수 있었다. 측정은 스레드에서 5초 안에 끝난다(llm_client).
    """
    llm_client.start_embedding_probe()
    try:  # 남은 PDF 임시 폴더(Edge 프로필) 정리 — 실패해도 서버는 뜬다(30차 R29-11)
        from app.services import plan_pdf_service

        plan_pdf_service.cleanup_leftovers()
    except Exception:  # noqa: BLE001
        pass
    yield


#: 앱 판 — `backend/pyproject.toml` · `frontend/package.json` 과 같아야 한다(시험이 견준다 · 35차 §4-4 「1차 — 로컬 완성」).
APP_VERSION = "2.10.0"

app = FastAPI(title="BidPilot AI API", version=APP_VERSION, lifespan=lifespan)

settings = get_settings()
logger = logging.getLogger(__name__)

# 허용 오리진: ALLOWED_ORIGINS 가 있으면 그 목록만, 없으면 기존대로 frontend_url.
_cors_origins = settings.allowed_origin_list or [settings.frontend_url]
# 개발 환경에서는 로컬 프론트엔드가 임의 포트로 뜰 수 있어 localhost 전체를 허용한다.
# 단 ALLOWED_ORIGINS 를 명시한 배포에서는 그 목록만 신뢰한다(느슨한 정규식으로 덮지 않는다).
_cors_origin_regex = (
    r"http://(localhost|127\.0\.0\.1):\d+"
    if settings.app_env == "development" and not settings.allowed_origin_list
    else None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # 파일 내려받기 파일명을 브라우저 스크립트에서도 읽을 수 있게 노출한다.
    expose_headers=["Content-Disposition"],
)

# 토큰 검사는 CORS **뒤에** 등록한다. Starlette 는 나중에 등록한 미들웨어가 바깥쪽에
# 놓이므로 이 미들웨어가 요청을 먼저 본다. preflight(OPTIONS)는 예외로 통과시키므로
# CORS 가 그대로 preflight 를 처리한다. API_TOKEN 이 비어 있으면 아무것도 막지 않는다.
app.add_middleware(TokenAuthMiddleware)

app.include_router(procurement.router)
app.include_router(rfp.router)
app.include_router(demo.router)
app.include_router(eligibility.router)
app.include_router(proposal.router)
app.include_router(auditor.router)
app.include_router(review.router)
app.include_router(conditions.router)
app.include_router(capability.router)
app.include_router(company.router)
app.include_router(organizations.router)
app.include_router(insights.router)
# 공고 직접 넣기 · 확인 전 후보함 · 오늘 열어 본 곳 (38차 §3-E)
app.include_router(manual.router)
# 공고문에 질문하기 (판 2.4.0)
app.include_router(notice_qa.router)
app.include_router(templates.router)
# 활동 기록 조회. 관리자 전용 판정은 라우터가 아니라 TokenAuthMiddleware 가 한다(계약서 5장).
app.include_router(audit_log.router)
# 로그인. 아직 세션이 없는 요청이라 신원 헤더 없이 들어온다 → 토큰 보유자(관리자)로 판정된다.
app.include_router(auth_api.router)


def _origin_allowed(origin: str) -> bool:
    """CORSMiddleware 에 넘긴 것과 **같은 규칙**으로 판정한다 (목록 + 개발용 정규식)."""
    if origin in _cors_origins:
        return True
    return bool(_cors_origin_regex and re.fullmatch(_cors_origin_regex, origin))


@app.exception_handler(analysis_store.PublicDemoReadOnlyError)
async def public_demo_read_only(_request: Request, exc: analysis_store.PublicDemoReadOnlyError) -> JSONResponse:
    """공용 데모 결과에 다른 회사가 쓰려 했다.

    데모 공고(`synthetic-*`)의 결과는 회사 구분 없이 한 파일이라, 어떤 조직 id 로든
    쓰기를 보내면 발표용 화면이 바뀐다. 읽기는 그대로 두고 쓰기만 막는다.
    """
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(storage.CorruptJsonError)
async def corrupt_json(_request: Request, exc: storage.CorruptJsonError) -> JSONResponse:
    """저장 파일이 깨져 읽지 못했다 (ISSUE-023 · TASK-020).

    예전에는 이 예외를 잡는 곳이 세 경로뿐이었다. 나머지는 500 으로 떨어졌고,
    `read_json` 이 깨진 파일을 `.corrupt-<시각>` 으로 옮기므로 **두 번째 조회부터는
    404「아직 저장된 결과가 없습니다」**가 됐다. 담당자에게는 검토 기록이 사라진 것으로
    보인다 — 실제로는 옆에 그대로 있다.

    409(충돌)로 답하고 격리된 파일 이름을 함께 준다. 「없다」고 말하지 않는다.
    """
    logger.warning("깨진 JSON 파일: %s", exc.path)
    # (2.0.6 safety-1) 옮긴 뒤에는 다시 시도하면 파일이 없어 처음 상태(빈 후보함 · 처음 목록)로 열리고 그 위에 저장된다 — 그 일을 미리 말한다.
    # 막지는 않는다: 영영 409 만 내면 처음 쓰는 대표가 막다른 화면에 선다. 원본은 옮긴 파일에 그대로 남는다.
    after = (
        f"원본은 {exc.quarantined.name} 에 그대로 있습니다. 다시 시도하면 옛 기록 없이 처음 상태에서 새로 시작합니다 — "
        "옛 기록이 필요하면 관리자에게 알려 주세요."
        if exc.quarantined
        else "관리자에게 알려 주세요."
    )
    return JSONResponse(
        status_code=409,
        content={"detail": f"저장된 파일이 손상되어 읽지 못했습니다. 기록이 사라진 것은 아닙니다 — {after}"},
    )


@app.exception_handler(storage.StaleWriteError)
async def stale_write(_request: Request, exc: storage.StaleWriteError) -> JSONResponse:
    """처음 읽은 뒤 다른 사람이 먼저 저장했다(43차 M25). 화면은 `code` 로 「다시 불러오기」를 보인다."""
    return JSONResponse(status_code=409, content={"detail": {"code": "stale_write", "message": str(exc)}})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    """예상 못 한 오류도 **JSON + CORS 헤더**로 답한다.

    기본 동작(Starlette ServerErrorMiddleware)은 CORSMiddleware 바깥에서 응답을 만들어
    `Access-Control-Allow-Origin` 이 붙지 않는다. 그러면 브라우저 fetch 는 상태 코드조차
    못 보고 `TypeError` 로 떨어지고, 화면은 그것을 「서버가 꺼졌다」로 잘못 안내한다.
    실제로 임베딩 키가 거부될 때 그렇게 보였다 — 서버는 멀쩡히 떠 있었다.

    사유 문장에 내부 정보를 싣지 않는다. 자세한 것은 서버 로그에 남는다.
    """
    logger.exception("처리하지 못한 오류: %s %s", request.method, request.url.path)
    response = JSONResponse(
        status_code=500,
        content={"detail": "처리 중 문제가 생겼습니다. 다시 시도해 주세요. 계속되면 관리자에게 알려 주세요."},
    )
    # CORS 헤더는 **허용 목록에 있는 Origin 에만** 붙인다.
    # 요청 Origin 을 그대로 반사하면 허용하지 않은 출처에도 자격증명 공유를 열어 주는 셈이라
    # CORS 정책과 어긋난다. 본문이 일반 문장이라 실해는 작지만, 예외를 만들 이유도 없다.
    origin = request.headers.get("origin")
    if origin and _origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


@app.get("/health")
async def health() -> dict[str, str | bool | int]:
    return {
        "status": "ok",
        "service": "bidpilot-api",
        # 판 · 규칙 판 — 지금 도는 것이 어느 판인지 화면 · 점검이 읽는다(35차 §4-4). 규칙 판은 판정 메모의 열쇠이기도 하다.
        "version": APP_VERSION,
        "rules_version": support_application_service.RULES_VERSION,
        "g2b_api_configured": g2b_client.is_configured(),
        # 키 «문자열이 있는지»가 아니라 실제로 쓸 수 있는지. 거부되는 키를 true 로 보고하면
        # 화면이 AI 검색 기능을 열어 두었다가 실패한다.
        "embedding_available": llm_client.embedding_available(),
        "public_demo_mode": settings.public_demo_mode,
        # 시연 고정 모드 (ISSUE-062). 켜져 있으면 목록 조회가 나라장터·기업마당을 부르지 않고
        # 저장된 캐시만 쓴다. 키가 있어도 부르지 않으므로 `g2b_api_configured` 와 다른 사실이다.
        "live_fetch_frozen": not (procurement_service.live_fetch_enabled() and bizinfo_service.live_fetch_enabled()),
        # 출처별 실호출 문 (20차 §4-G). 사업기회 화면의 「나라장터 재수집」「기업마당 재수집」 단추가 이것으로 잠긴다.
        "g2b_live": procurement_service.live_fetch_enabled(),
        "bizinfo_live": bizinfo_service.live_fetch_enabled(),
        # 「찾는 낱말」 바로 찾기를 할 수 있는가(2.0.7) — 좁은 문 `KEYWORD_SEARCH_LIVE` 또는 위 나라장터 문. 목록 조회와 다른 문이다.
        "keyword_search_live": collect_keywords_service.search_live(),
        # 임베딩 문 둘 (ISSUE-129 · prompt_05 §4-A-2). `embedding_available` 과 다른 사실이다 —
        # 저쪽은 「재 보니 쓸 수 있더라」이고 이쪽은 「부를 생각이 있는가 · 점수에 쓸 것인가」다.
        # 시연 전 점검(`demo_preflight`)과 화면 「데이터 상태」가 이 두 값을 읽는다.
        "embedding_live": llm_client.embedding_live_enabled(),
        "semantic_fit": semantic_matcher.semantic_fit_enabled(),
        # 완성 문 (ISSUE-130 · prompt_06 §4-A-3). 「AI 초안이 붙는가」는 이 값과 `credit_ok`
        # **둘 다** 참일 때다 — 켜 두어도 크레딧이 없으면 규칙 초안이 나간다.
        "llm_live": llm_client.llm_live_enabled(),
        "llm_credit_ok": llm_client.credit_ok(),
        # 완성 공급자와 **실제로 쓰는** 모델 이름 (25차 §4-A-6). 키는 싣지 않는다.
        "llm_provider": llm_client.completion_provider(),
        "llm_model": llm_client.completion_model(),
        # 사업계획서 작성 페이지(/plan) 단추만 CLI(Claude · Codex)를 부르는 문 (28차 §3-D) — `llm_live` 와 다른 문.
        "plan_writer_cli": llm_client.plan_writer_enabled(),
        # 그 단추가 쓰는 모델 이름 — 시연 전 점검이 고정값 대신 이것을 적는다 (29차 R28-18). Codex 는 비우면 CLI 기본.
        "plan_writer_model": llm_client.plan_writer_model("claude"),
        "plan_writer_codex_model": llm_client.plan_writer_model("codex"),
        "default_organization_id": settings.default_organization_id,
        # 첨부(제안요청서)를 저절로 받는가 — 기본 꺼짐. 꺼져 있어도 /rfp 확인 창에서 사람이 고른 한 건은 받는다(27차 §3-A).
        "attachment_fetch": attachment_service.attachment_fetch_enabled(),
        # 토큰 인증이 켜져 있는지만 알린다. 토큰 값은 절대 싣지 않는다.
        "auth_required": token_required(),
    }
