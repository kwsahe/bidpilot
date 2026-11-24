@echo off
rem BidPilot AI - daily launcher (double-click me)
rem Stored lists only (-Frozen: no live fetch, the scheduled task refreshes them once a day at logon / unlock) + Claude / Codex buttons (-PlanWriter).
rem Developer live-fetch mode: run start_dev.ps1 without flags (see docs\getting_started.md).
rem Extra arguments are passed through, e.g.:  start_dev.bat -NoBrowser -FrontendPort 3120
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_dev.ps1" -Frozen -PlanWriter %*
echo.
echo (Press any key to close this window. The two server windows stay open.)
pause >nul
