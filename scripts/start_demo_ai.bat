@echo off
rem BidPilot AI - 시연용 런처 (AI 초안 켜짐). 더블클릭.
rem
rem start_demo.bat 과 같은데 -Ai 가 붙는다:
rem   - 나라장터/기업마당은 그대로 **부르지 않는다** (-Frozen)
rem   - 임베딩/의미 유사도도 그대로 **꺼져 있다** — 목록 건수/순위/점수가 바뀌지 않는다
rem   - 완성만 켠다: 제안서 섹션 생성 / 사업계획서 핵심 섹션 생성 / 제출 전 점검(Auditor)
rem
rem 담당자 방침 그대로다 - "순위와 유사도는 규칙만, AI 는 초안과 점검에만".
rem
rem 켜기 전에 확인할 것:
rem   1) 어느 공급자로 쓸지 .env 의 LLM_PROVIDER (openai | xai)
rem      - openai: OPENAI_API_KEY 가 살아 있는가 (검수자가 끊어 두었으면 이름을 되돌린다)
rem      - xai   : XAI_API_KEY 를 적는다. xAI 콘솔의 데이터 공유(학습 사용)는 켜지 않는다
rem   2) 크레딧이 있는가. 첫 실측 전에는 LLM_CREDIT_CONFIRMED=1 을 적는다
rem      (누계 마지막 판정이 OpenAI 429 이고 xai 는 성공 기록이 아직 없다 - 첫 호출이 성공하면 빼도 된다)
rem   3) .env 를 고치면 백엔드를 다시 띄운다 - 설정은 캐시되고 --reload 는 .env 를 다시 읽지 않는다.
rem      8110 에 백엔드가 이미 떠 있으면 이 런처는 새로 띄우지 않고 건너뛴다(LLM_LIVE=0 그대로).
rem      먼저 scripts\stop_dev.ps1 로 끈다.
rem
rem Claude Code CLI(이 PC 의 구독 로그인)로 쓰려면 이 런처 대신 start_demo_claude.bat - 키가 필요 없고 .env 를 고치지 않는다.
rem AI 없이 규칙으로만 시연하려면 start_demo.bat 을 쓴다.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_dev.ps1" -Frozen -Ai %*
echo.
echo (아무 키나 누르면 이 창만 닫힙니다. 서버 창 두 개는 그대로 둡니다.)
pause >nul
