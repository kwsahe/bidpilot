@echo off
rem BidPilot AI 범용 설치 키트 — 처음이면 설치하고 몇 가지를 묻고, 그다음 화면을 켭니다. (30차 §3-G)
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kit_setup.ps1" %*
if errorlevel 1 (
  echo.
  echo 설치나 시작이 멈췄습니다. 위 [멈춤] 줄을 읽고 다시 실행하세요.
)
pause
