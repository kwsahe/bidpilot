@echo off
rem BidPilot AI - 시연용 런처 (더블클릭). 발표 당일에는 이것을 쓴다.
rem
rem start_dev.bat 과 같은데 -Frozen 이 붙는다:
rem   - 나라장터/기업마당을 부르지 않고 저장된 목록만 쓴다 (ISSUE-062)
rem   - 발표 중 공고 건수/순위가 바뀌지 않고, Git 이 추적하는 캐시 파일도 덮어써지지 않는다
rem   - 화면의 "데이터 상태"에 "시연 고정 모드"가 뜨고 새로고침 단추가 잠긴다
rem
rem 실호출로 돌려 보고 싶으면 start_dev.bat 을 쓴다.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_dev.ps1" -Frozen %*
echo.
echo (아무 키나 누르면 이 창만 닫힙니다. 서버 창 두 개는 그대로 둡니다.)
pause >nul
