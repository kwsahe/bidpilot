@echo off
rem BidPilot AI - wireframe dashboard launcher (double-click me)
rem Starts the backend (only if it is not running yet) and the wireframe-only
rem frontend on port 4120, then opens http://localhost:4120 in the browser.
rem The Evidence Cosmos dashboard on port 3110 is NOT touched - use start_dev.bat for that.
rem Extra arguments are passed through, e.g.:  start_wireframe.bat -NoBrowser
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_wireframe.ps1" %*
echo.
echo (Press any key to close this window. The server windows stay open.)
pause >nul
