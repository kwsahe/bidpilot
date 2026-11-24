@echo off
rem BidPilot AI - production launcher for the presentation (double-click me)
rem Builds the frontend (npm run build) and starts backend + `next start` without the dev badge/HMR.
rem Extra arguments pass through, e.g.:  start_prod.bat -SkipBuild
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_prod.ps1" %*
echo.
echo (Press any key to close this window. The two server windows stay open.)
pause >nul
