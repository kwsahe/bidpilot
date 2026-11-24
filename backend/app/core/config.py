from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    frontend_url: str = "http://localhost:3110"
    backend_url: str = "http://localhost:8110"

    data_go_kr_service_key: str = ""
    # 기업마당(bizinfo.go.kr) 지원사업정보 OpenAPI 인증키. 없으면 캐시/합성 샘플로 동작한다.
    bizinfo_api_key: str = ""

    # LLM (없으면 규칙 기반으로만 동작한다 — 기능이 죽지 않는다)
    openai_api_key: str = ""
    llm_provider: str = "openai"
    llm_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"

    # --- 완성 공급자 스위치 (25차 · prompt_15 §4-A) ---
    #
    # `LLM_PROVIDER=openai|xai` 는 **완성**(제안서 · 사업계획서 · Auditor · 자격 보강)만 바꾼다.
    # 임베딩은 늘 OpenAI 다 — xAI 에는 임베딩이 없다. 그래서 `is_configured()`(임베딩 문)는
    # 지금처럼 OpenAI 키만 보고, 완성 문은 `completion_configured()` 가 공급자 키를 본다.
    #
    # 모델 이름은 공급자별이다. `LLM_MODEL` 은 openai 에만(지금 뜻 그대로) — 루트 `.env` 에
    # `LLM_MODEL=gpt-4.1-mini` 가 이미 있어 xai 로 바꾸면 그 이름이 xAI 로 나가는 사고를 막는다.
    # xai 는 `XAI_MODEL`(기본 grok-4.7). xai 인데 모델 이름이 gpt-·o·text- 로 시작하면 부르지 않는다.
    #
    # xAI 콘솔의 **데이터 공유(학습 사용)는 켜지 않는다** — 켜면 되돌릴 수 없고 입력·출력이
    # 모델 학습에 쓰인다. 사업계획서에는 회사 실적이 들어간다.
    xai_api_key: str = ""
    # 비우면 공급자 기본 주소(openai = SDK 기본 · xai = https://api.x.ai/v1).
    llm_base_url: str = ""
    xai_model: str = "grok-4.7"
    # 추론 모델의 추론 강도(low · high). 비우면 보내지 않는다 — grok-4.7 은 그때 high.
    xai_reasoning_effort: str = ""
    # 완성 호출 한 번의 제한 시간(초). 예전 60 은 추론 모델에 짧다. 임베딩 탐침(5초)과 무관하다.
    llm_timeout_seconds: float = 180.0
    # `LLM_PROVIDER=claude_cli` — 키 없이 이 PC 에 로그인된 Claude Code CLI(구독)로 쓴다.
    # 담당자 본인 PC 에서만 쓴다(회사 서버·Vercel 에는 CLI 로그인이 없고, 개인 구독으로 남을 위해 돌리지 않는다).
    # 개인 요금제(Pro·Max)면 claude.ai 「Claude 개선에 도움 주기」(학습 사용)를 끈 뒤 쓴다.
    # 경로를 비우면 PATH 의 `claude` · 모델을 비우면 claude-opus-5-5 · 강도(low~max)를 비우면 보내지 않는다.
    claude_cli_path: str = ""
    claude_cli_model: str = "claude-opus-5-5"
    claude_cli_effort: str = ""

    # 다회사 구조. 호환 API(/api/company/...)가 위임하는 기본 조직. 회사명이 아니라 영구 식별자다.
    default_organization_id: str = "org-sample"
    # 기본 조직을 처음 만들 때 이름(30차 §3-G 키트). 이미 등록부에 있으면 쓰지 않는다 — 회사 이름은 화면에서 못 고친다.
    default_organization_name: str = "주식회사 샘플에듀"
    # 키트(범용 설치)용 — 참이면 저장 전 합성 기본 프로필 · 지역 대체값에 샘플에듀 사업영역 · 광주·전남을 넣지 않는다(비어 있음 →
    # 「회사 정보 필요」 · 「확인 필요」). 샘플에듀 설치는 거짓(지금 동작 그대로).
    neutral_company_defaults: bool = False
    # 공개 배포(읽기 전용 데모) 모드: 회사 생성·자료 업로드·승인·색인을 막고 근거 범위는 public_demo 만 허용한다.
    public_demo_mode: bool = False

    # --- 시연 고정 모드 (ISSUE-062) · 실호출은 **기본이 꺼짐** (ISSUE-120) ---
    #
    # 목록 조회는 캐시가 15분(TTL) 지나면 나라장터를 다시 부르고, 그 결과로 git 이 추적하는
    # 캐시 파일을 덮어쓴다. 시연 중에는 그 한 번으로 「수집 107건」이 다른 숫자가 되고
    # 큐시트·리허설 캡처와 어긋난다. 꺼 두면 TTL·refresh 와 무관하게 **캐시만** 읽는다.
    # 키를 비우는 편법과 다르다 — 키는 그대로 두고 «부르지 않는다»는 사실을 화면에 표시한다.
    #
    # **기본값을 껐다** (14차 · prompt_03 §4-A-1). 예전 기본값은 켜짐이었고, 그래서
    # 환경변수를 세우지 않고 앱을 import 하기만 해도 바깥을 불렀다. 같은 사고가 세 번 났다 —
    # 11차 진단 스크립트(기준 답안 2건 영구 손실) · 12차 떠 있던 `start_dev.bat`(공고 캐시
    # 덮임) · 13차 진단 스크립트(기업마당 캐시 1,620건이 100건으로 덮임). 프롬프트에 세 번
    # 적었고 세 번 옮겨 적었지만 세 번 다 어겼다. **규칙으로 막을 일이 아니라 기본값이
    # 틀린 것이었다** — 실수로 부르는 쪽이 아니라 실수로 안 부르는 쪽이 안전하다.
    #
    # 켜려면 환경변수를 **명시적으로** 세운다: `G2B_LIVE_FETCH=1` · `BIZINFO_LIVE_FETCH=1`.
    # `scripts/start_dev.ps1`(고정 모드가 아닐 때)과 실제로 받아 오는 스크립트
    # (`collect_daily.py` · `refetch_bizinfo_cache.py` · `backfill_qualifications.py`)가 그렇게 한다.
    g2b_live_fetch: bool = False
    bizinfo_live_fetch: bool = False
    # 「찾는 낱말」 바로 찾기만 여는 좁은 문(2.0.7 · 대표 결정 ① · `KEYWORD_SEARCH_LIVE`). 켜도 목록 조회(GET)는 바깥을 부르지 않는다 —
    # 추가 낱말 **하나**의 공고명 검색(7일 창마다 첫 쪽 + 2쪽 · 30일이면 최대 7회 · 2.8.1) · 자격 하루치 최대 6회만 · 편집자 이상 · 하루 10번 · 아침 받기와 같은 잠금.
    # 회사 서버 `.env` 에만 적는다. 이름이 달라 `collect_daily.py` 의 `G2B_LIVE_FETCH` setdefault 를 막지 않는다.
    keyword_search_live: bool = False
    # 평일 아침 슬랙 브리핑(2.6.0 · `slack_brief_service`) — 슬랙 「Incoming Webhook」 주소. 비어 있으면 보내지 않는다.
    # **회사 서버 `.env` 에만** 적는다(노트북도 매일 받으므로 둘 다 적으면 두 번 간다). 비밀이라 로그 · 화면에 싣지 않는다.
    slack_webhook_url: str = ""

    # 캐시가 **크게 줄어드는 저장**을 허용할지 (ISSUE-121).
    #
    # 13차에 기업마당 목록 조회가 100건만 받아 와 1,620건짜리 캐시를 **말없이** 덮었다.
    # 파일이 깨진 것이 아니라 정상적으로 쓰였기 때문에 아무도 몰랐고, 그 캐시는
    # gitignore 아래라 되돌릴 수도 없었다. 목록이 절반 아래로 줄어드는 것은 거의 언제나
    # 「덜 받아 온 것」이지 「그만큼밖에 없는 것」이 아니다 — 의심스러우면 옛것을 지킨다.
    #
    # 1 로 두면 그대로 덮어쓴다. 실제로 줄어든 것이 맞을 때 담당자가 켠다.
    cache_allow_shrink: bool = False

    # --- OpenAI 임베딩도 스위치 아래에 (ISSUE-129 · 15차 · prompt_05 §4-A) ---
    #
    # 14차까지 시연 고정 모드는 나라장터·기업마당만 막았다. OpenAI 는 별개 문이었고,
    # 재검증 중 키에 크레딧이 생기자 서버가 목록을 만들며 **임베딩 1,802건을 실제로
    # 불렀다**(2026-09-21 11:20~11:26). 기록(`llm_usage.jsonl`)에도 남지 않았다.
    # 그 순간 점수가 바뀌어 목록(85)과 상세(74)가 갈렸고, 두 화면 대조가 33건 불일치였다.
    #
    # **둘은 다른 문이다.**
    #
    # `embedding_live` — 「바깥을 부르는가」. 꺼져 있으면 탐침도 `embed()` 도 아무것도
    #     부르지 않고 `LLMUnavailableError` 를 돌려준다. OpenAI 클라이언트를 만들지도 않는다.
    # `semantic_fit`  — 「점수에 쓰는가」. 꺼져 있으면 **캐시 벡터가 있어도** 의미 유사도를
    #     점수에 쓰지 않는다(키워드 경로만). 캐시를 지우지 않고도 숫자를 고정할 수 있다.
    #
    # 앞의 것만 끄면 이미 디스크에 있는 벡터 1,802개로 점수가 계속 달라진다. 뒤의 것만
    # 끄면 점수는 고정되지만 탐침이 여전히 바깥을 부른다. 그래서 둘이다.
    #
    # 기본값은 둘 다 **꺼짐**이다 — 실호출 기본값을 껐을 때와 같은 이유다(ISSUE-120).
    # 켜는 자리는 `scripts/start_dev.ps1`(`-Frozen` 이 아닐 때)뿐이다.
    embedding_live: bool = False
    semantic_fit: bool = False

    # --- 완성(제안서·사업계획서·Auditor)도 스위치 아래에 (ISSUE-130 · 16차 · prompt_06 §4-A) ---
    #
    # 담당자 방침: **순위·유사도는 규칙만, AI 는 제안서·사업계획서 초안과 제출 전 점검에만.**
    # 15차가 임베딩 문 둘을 만들었지만 완성 문은 `credit_ok()` 하나였다 — 「AI 는 제안서에만」을
    # 스위치로 말할 수가 없었다. 이제 문이 셋이다.
    #
    # `llm_live`  — 「완성을 부르는가」. 꺼지면 `complete_structured` 가 **클라이언트를 만들지
    #     않고** `LLMUnavailableError` 를 던진다. 호출자 넷(제안서·사업계획서·Auditor·자격
    #     보강)이 전부 그 예외를 「규칙 경로로 간다」로 이미 처리한다.
    # `llm_credit_confirmed` — 「담당자가 충전했다고 적은 것」.
    #
    # 뒤의 것이 왜 필요한가. `credit_ok()` 는 누계 기록의 마지막 줄이 429 면 거짓인데,
    # **한 번 429 가 찍히면 영원히 닫힌다** — 다시 열려면 성공 기록이 있어야 하고, 성공
    # 기록은 부르지 않으면 생기지 않는다. 충전을 해도 길이 없었다. 이 값이 그 자물쇠를
    # 여는 열쇠다. 첫 호출이 성공하면 누계에 성공 줄이 남으므로 그 뒤로는 없어도 된다.
    llm_live: bool = False
    llm_credit_confirmed: bool = False

    # --- 사업계획서 작성 페이지 전용 문 (28차 §3-D) ---
    # `plan_writer_cli` — 사업계획서 작성 페이지(/plan)의 「Claude로 쓰기」 · 「Codex로 쓰기」 단추만 이 PC 의 CLI 를 부른다.
    # 서버 전체 AI 스위치(`llm_live`)와 **다른 문**이다 — 이것만 켜면 대시보드 6단계 제안서 · 제출 전 점검 · 자격 보강은
    # 여전히 규칙만 쓴다. 보내는 것은 각 서비스의 허용 목록 그대로(사업계획서 llm_payload · 입찰은 승인된 회사자료 문단 중
    # 유사도 기준으로 고른 근거 문장만 — 사람이 하나씩 고르는 기능은 없다).
    plan_writer_cli: bool = False
    # Codex CLI (29차 §3-A) — 비면 PATH 의 codex.exe · 모델을 비우면 CLI(로그인한 요금제)가 정한 기본 모델.
    codex_cli_path: str = ""
    codex_cli_model: str = ""
    # 42차 — 회사 서버는 Claude 만 쓴다(`PLAN_WRITER_CODEX=0`) · Codex 단추는 「꺼짐」으로 보인다. 노트북은 그대로(켬).
    plan_writer_codex: bool = True

    # --- 나라장터 첨부(입찰공고문·제안요청서) 내려받기도 스위치 아래에 (19차 §4-A-4) ---
    #
    # `download_attachment` 에는 문이 없었다. 고정 모드에서도 4단계 「요구사항 정리표 생성」을
    # 누르면 캐시에 없는 첨부를 **조용히 실제로** 내려받았다 — 목록·임베딩·완성을 다 막아
    # 두고도 이 길 하나가 열려 있었다. 꺼져 있으면 캐시에 있는 파일만 쓰고, 없으면
    # `AttachmentFetchDisabledError` 를 던진다. 켜는 자리는 `scripts/fetch_qualification_clauses.py`
    # 하나다(스크립트가 앱을 import 하기 **전에** 자기 안에서 세운다). 서버는 켜지 않는다.
    attachment_fetch: bool = False

    # --- 사내 호스팅 대비 ---
    # API 토큰. 비어 있으면 인증을 요구하지 않는다(로컬 개발 그대로 동작).
    # 설정하면 Next.js 서버(중계자)만 이 값을 알고 헤더에 실어 보낸다. 프론트 번들에 노출 금지.
    api_token: str = ""
    # CORS 허용 오리진. 쉼표로 구분한다. 비어 있으면 기존 동작(frontend_url + 개발용 localhost)을 유지한다.
    allowed_origins: str = ""

    @property
    def allowed_origin_list(self) -> list[str]:
        """`allowed_origins` 를 쉼표로 나눈 목록. 공백은 제거하고 빈 항목은 버린다."""
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    # env 파일은 backend/ 실행 기준과 저장소 루트 기준 둘 다 지원한다.
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
