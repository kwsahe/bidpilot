@echo off
chcp 65001 >nul
rem BidPilot 「지금 받기」 (39차 §3-F-3 · 40차 D30) — 두 번 누르면 예약 작업(BidPilot-DailyCollect)과 같은 명령을 「하루 한 번」 검사 없이(--force) 바로 돌린다.
rem 화면에 「오늘 목록을 아직 받지 않았습니다」가 뜰 때 쓴다. 나라장터 · 사전규격 · 발주계획 · 공고문 · 기업마당을 받고 로그에 붙인다.
rem 이미 받는 중이면(예약 작업이나 이 파일이 먼저 도는 중) 멈춘다 — collect_daily.py 의 받기 잠금이 두 길을 함께 막는다. 바탕화면 바로가기 만드는 법은 docs\user_guide.md 「지금 받기」.
rem   지금_받기.bat /check  — 받지 않고 무엇을 돌릴지만 보인다(시험용 · 바깥 호출 0).
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*collect_daily.py*' }) { exit 1 } else { exit 0 }"
if errorlevel 1 goto busy
if /i "%~1"=="/check" goto check
if not exist data\private\logs mkdir data\private\logs
echo 새 공고를 받는 중입니다 — 5분쯤 걸립니다. 이 창을 닫지 마세요.
backend\.venv\Scripts\python.exe -X utf8 scripts\collect_daily.py --run --force --json >> data\private\logs\collect_daily.log 2>&1
if errorlevel 4 goto nonet
if errorlevel 3 goto busy
if errorlevel 1 goto failed
echo.
echo 다 받았습니다 — 화면을 새로 고치세요
pause
exit /b 0
:busy
echo 이미 받는 중입니다 — 끝난 뒤 화면을 새로 고치세요
if /i not "%~1"=="/check" pause
exit /b 1
:check
echo [확인만] 이 명령을 돌립니다: backend\.venv\Scripts\python.exe -X utf8 scripts\collect_daily.py --run --force --json ^>^> data\private\logs\collect_daily.log
exit /b 0
:nonet
echo.
echo 인터넷 연결을 확인하고 다시 누르세요 — 지금은 받지 않았습니다(네트워크가 60초 안에 잡히지 않음)
pause
exit /b 4
:failed
echo.
echo 받기가 끝까지 되지 않았습니다 — data\private\logs\collect_daily.log 마지막 줄을 보세요
pause
exit /b 2
