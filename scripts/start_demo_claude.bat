@echo off
rem BidPilot AI - 시연용 런처 (사업계획서 작성 = 이 PC 의 Claude Code CLI · 구독). 더블클릭.
rem
rem 28차: 사업계획서 작성 페이지(/plan)의 "Claude로 ... 쓰기" 단추만 CLI 를 부른다 (-PlanWriter).
rem   - 나라장터/기업마당/임베딩/의미 유사도는 그대로 꺼져 있다 (-Frozen)
rem   - 서버 전체 AI 는 꺼져 있다 - 대시보드 6단계 제안서 / 제출 전 점검 / 자격 보강은 규칙만 쓴다
rem   - API 키가 필요 없고 .env 를 고치지 않는다
rem
rem 켜기 전에 확인할 것:
rem   1) 이 PC 에서 claude 에 로그인되어 있는가 (claude auth status)
rem   2) 개인 요금제(Pro/Max)면 claude.ai 설정 - 개인정보 - "Claude 개선에 도움 주기" 를 끈다
rem      (켜져 있으면 사업계획서 초안의 회사 실적이 모델 학습에 쓰일 수 있다)
rem   3) 8110 에 백엔드가 이미 떠 있으면 새로 띄우지 않고 건너뛴다 - 먼저 scripts\stop_dev.ps1 로 끈다.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_dev.ps1" -Frozen -PlanWriter %*
echo.
echo (아무 키나 누르면 이 창만 닫힙니다. 서버 창 두 개는 그대로 둡니다.)
pause >nul
