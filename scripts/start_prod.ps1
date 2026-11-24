# BidPilot AI - 발표용 production 실행 (Windows PowerShell 5.1)
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_prod.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_prod.ps1 -SkipBuild   # 이미 빌드했으면
#
# 하는 일:
#   1. backend  : .venv 의 uvicorn 을 --reload 없이 8110 포트로 띄운다 (새 창)
#   2. frontend : `next build` 후 `next start -p 3110` (새 창). 개발용 "N" 배지·HMR 없이 뜬다.
#   3. 브라우저를 http://localhost:3110 으로 연다
#
# 준비물은 scripts\start_dev.ps1 과 같다 (backend\.venv, frontend\node_modules, 루트 .env).
# 처음이면 start_dev.bat 을 한 번 실행해 의존성을 설치해 둔다.
param(
  [int]$FrontendPort = 3110,
  [int]$BackendPort = 8110,
  [switch]$SkipBuild,
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
  Write-Host "[FAIL] backend\.venv 가 없습니다. scripts\start_dev.bat 을 먼저 한 번 실행해 주세요." -ForegroundColor Red
  exit 1
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
  Write-Host "[FAIL] frontend\node_modules 가 없습니다. frontend 폴더에서 npm install 을 먼저 실행해 주세요." -ForegroundColor Red
  exit 1
}

function Test-PortOpen([int]$port) {
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect("127.0.0.1", $port)
    $client.Close()
    return $true
  } catch { return $false }
}

# 1) backend
if (Test-PortOpen $BackendPort) {
  Write-Host "[OK] backend :$BackendPort 이미 실행 중 - 그대로 사용합니다."
} else {
  Write-Host "[..] backend :$BackendPort 시작 (production, --reload 없음)"
  Start-Process powershell -ArgumentList @(
    "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
    "`$Host.UI.RawUI.WindowTitle = 'BidPilot Backend :$BackendPort (prod)'; Set-Location '$backend'; & '$python' -m uvicorn app.main:app --port $BackendPort"
  )
}

# 2) frontend build
# 브라우저가 부를 백엔드 주소는 **빌드할 때** 박힌다(NEXT_PUBLIC_*). -BackendPort 를 바꿨으면 여기서 넘겨야
# 화면이 그 포트를 부른다. -SkipBuild 면 지난 빌드의 주소가 그대로다.
$env:NEXT_PUBLIC_BACKEND_URL = "http://localhost:$BackendPort"
# -SkipBuild 여도 지난 빌드가 **이 백엔드 주소를 부르는지** 먼저 본다. 포트를 3000/8000 → 3110/8110 으로 바꾸기 전에
# 만든 빌드는 옛 주소(다른 프로젝트의 백엔드)를 품고 있다 — 그러면 -SkipBuild 를 무시하고 다시 빌드한다.
if ($SkipBuild) {
  $chunkDir = Join-Path $frontend ".next\static\chunks"
  $buildHasBackend = (Test-Path $chunkDir) -and (Select-String -Path (Join-Path $chunkDir "*.js") -SimpleMatch "localhost:$BackendPort" -Quiet)
  if (-not $buildHasBackend) {
    Write-Host "[WARN] 지난 빌드가 백엔드 localhost:$BackendPort 를 부르지 않습니다 - -SkipBuild 를 무시하고 다시 빌드합니다." -ForegroundColor Yellow
    $SkipBuild = $false
  }
}
if (-not $SkipBuild) {
  Write-Host "[..] frontend production build (npm run build) - 1~2분 걸릴 수 있습니다"
  Push-Location $frontend
  try {
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build 실패 (exit $LASTEXITCODE)" }
  } finally { Pop-Location }
  Write-Host "[OK] build 완료"
} else {
  Write-Host "[OK] build 건너뜀 (-SkipBuild)"
}

# 3) frontend start
if (Test-PortOpen $FrontendPort) {
  Write-Host "[WARN] :$FrontendPort 이 이미 사용 중입니다. 개발 서버(npm run dev)가 떠 있으면 먼저 끄거나 -FrontendPort 로 다른 포트를 지정하세요." -ForegroundColor Yellow
} else {
  Write-Host "[..] frontend :$FrontendPort 시작 (next start)"
  Start-Process powershell -ArgumentList @(
    "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
    "`$Host.UI.RawUI.WindowTitle = 'BidPilot Frontend :$FrontendPort (prod)'; Set-Location '$frontend'; npx next start -p $FrontendPort --hostname 127.0.0.1"
  )
}

# 4) 응답 대기 후 브라우저
$deadline = (Get-Date).AddSeconds(60)
$ready = $false
while ((Get-Date) -lt $deadline) {
  if ((Test-PortOpen $FrontendPort) -and (Test-PortOpen $BackendPort)) { $ready = $true; break }
  Start-Sleep -Seconds 1
}
if ($ready) {
  Write-Host "[OK] http://localhost:$FrontendPort (frontend)  http://localhost:$BackendPort/health (backend)"
  if (-not $NoBrowser) { Start-Process "http://localhost:$FrontendPort" }
} else {
  Write-Host "[WARN] 60초 안에 응답이 없습니다. 열린 두 창의 로그를 확인해 주세요." -ForegroundColor Yellow
}
