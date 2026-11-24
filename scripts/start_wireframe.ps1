<#
.SYNOPSIS
  와이어프레임 대시보드(포트 4120)만 띄우는 스크립트.

.DESCRIPTION
  Evidence Cosmos(3110)와 별개로, 와이어프레임 대시보드 전용 서버를 4120 포트에 올린다.
  두 서버는 동시에 켤 수 있다.

  1) 백엔드(8110)가 꺼져 있으면 같이 띄운다. 이미 떠 있으면 건드리지 않는다.
  2) 프론트엔드는 `npm run dev:wireframe` (= next dev --port 4120) 로 실행한다.
     포트가 4120이면 frontend\next.config.ts 가 루트(/)를 /wireframe 으로 rewrite 하고
     빌드 캐시를 .next-wireframe\ 로 분리한다.
  3) 실행한 PID를 %TEMP%\bidpilot_wireframe_pids.json 에 기록한다 (stop_dev.ps1 이 사용).

  최초 설치(파이썬 가상환경, npm install)는 이 스크립트가 하지 않는다.
  준비가 안 되어 있으면 scripts\start_dev.bat 을 한 번 먼저 실행하라고 안내하고 멈춘다.

  Windows PowerShell 5.1 에서 동작하도록 작성했다 (&&, 삼항연산자, ?? 사용 안 함).

.PARAMETER Port
  와이어프레임 프론트엔드 포트 (기본 4120).
  4120이 아닌 값을 주면 루트 rewrite가 꺼지므로 /wireframe 경로로 접속해야 한다.

.PARAMETER BackendPort
  백엔드 포트 (기본 8110).

.PARAMETER NoBrowser
  서버가 뜬 뒤 브라우저를 자동으로 열지 않는다.

.PARAMETER DryRun
  아무것도 실행하지 않고 "무엇을 할 예정인지"만 출력한다.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_wireframe.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_wireframe.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [int]$Port = 4120,
    [int]$BackendPort = 8110,
    [switch]$NoBrowser,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# 한글 출력이 깨지지 않도록 콘솔 인코딩을 UTF-8로 맞춘다 (실패해도 계속 진행).
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# ---------------------------------------------------------------------------
# 출력 도우미 (start_dev.ps1 과 같은 표기)
# ---------------------------------------------------------------------------
function Write-Step([string]$Message) { Write-Host ""; Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message)   { Write-Host "  [OK]   $Message" -ForegroundColor Green }
function Write-Info([string]$Message) { Write-Host "  [..]   $Message" -ForegroundColor Gray }
function Write-Warn([string]$Message) { Write-Host "  [주의] $Message" -ForegroundColor Yellow }
function Write-Fail([string]$Message) { Write-Host "  [실패] $Message" -ForegroundColor Red }
function Write-Plan([string]$Message) { Write-Host "  [계획] $Message" -ForegroundColor Magenta }

function Invoke-Action([string]$Description, [scriptblock]$Action) {
    if ($DryRun) {
        Write-Plan $Description
        return $null
    }
    Write-Info $Description
    return (& $Action)
}

function Stop-WithGuidance([string]$Message, [string[]]$Guidance) {
    Write-Fail $Message
    foreach ($line in $Guidance) { Write-Host "         $line" -ForegroundColor Yellow }
    Write-Host ""
    exit 1
}

# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

# 해당 포트를 LISTEN 중인 프로세스 ID (없으면 0).
function Get-ListeningPid([int]$TargetPort) {
    $cmd = Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue
    if ($cmd) {
        $conn = Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) { return [int]$conn.OwningProcess }
        return 0
    }
    # 오래된 환경용 fallback: netstat 파싱
    $lines = netstat -ano | Select-String -Pattern "^\s*TCP\s+\S+:$TargetPort\s+\S+\s+LISTENING\s+(\d+)"
    if ($lines) {
        $first = $lines | Select-Object -First 1
        return [int]$first.Matches[0].Groups[1].Value
    }
    return 0
}

function Get-ProcessNameSafe([int]$ProcessId) {
    if ($ProcessId -le 0) { return "" }
    $p = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($p) { return $p.ProcessName }
    return "(알 수 없음)"
}

# 해당 포트에 떠 있는 것이 BidPilot 프론트엔드인지 확인 — **페이지 제목(<title>)이 「BidPilot AI」인지**, 대소문자까지.
# 본문 어디서나 대소문자 없이 「BidPilot」을 찾으면 저장소 폴더를 띄운 다른 http 서버의 파일 목록(「BidPilot_AI_…html」)을
# 우리 화면으로 알고 「이미 실행 중 — 건너뜁니다」를 냈다(35차 §4-1 이상 상황 b).
function Test-BidPilotFrontend([int]$TargetPort) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$TargetPort/" -UseBasicParsing -TimeoutSec 8
        return ($r.Content -cmatch '<title>[^<]*BidPilot AI')
    } catch {
        return $false
    }
}

# 새 PowerShell 창에서 명령을 실행하고 그 창의 PID 를 돌려준다.
function Start-InNewWindow([string]$Title, [string]$WorkingDirectory, [string]$CommandLine) {
    $inner = "`$Host.UI.RawUI.WindowTitle = '$Title'; Set-Location -LiteralPath '$WorkingDirectory'; $CommandLine"
    $psArgs = @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $inner)
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $psArgs -WorkingDirectory $WorkingDirectory -PassThru
    return $proc.Id
}

# URL 이 응답할 때까지 최대 $TimeoutSec 초 기다린다. 성공하면 응답 본문, 실패하면 $null.
function Wait-ForHttp([string]$Url, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400) { return $r.Content }
        } catch { }
        Start-Sleep -Seconds 2
        Write-Host "." -NoNewline -ForegroundColor DarkGray
    }
    Write-Host ""
    return $null
}

# ---------------------------------------------------------------------------
# (a) 저장소 위치 / 준비 상태 확인
# ---------------------------------------------------------------------------
$RepoRoot    = Split-Path -Parent $PSScriptRoot
$BackendDir  = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$VenvPython  = Join-Path $BackendDir ".venv\Scripts\python.exe"
$PidFile     = Join-Path $env:TEMP "bidpilot_wireframe_pids.json"

Write-Host ""
Write-Host "BidPilot AI - 와이어프레임 대시보드 (포트 $Port)" -ForegroundColor White
if ($DryRun) { Write-Host "(DryRun 모드: 실제로 실행하지 않고 계획만 출력합니다)" -ForegroundColor Magenta }

Write-Step "저장소 위치 확인"
if (-not (Test-Path (Join-Path $FrontendDir "package.json"))) {
    Stop-WithGuidance "저장소 구조를 찾지 못했습니다: $RepoRoot" @(
        "이 스크립트는 sampleedu-bidpilot-ai\scripts\ 안에 있어야 합니다."
    )
}
Write-Ok "저장소: $RepoRoot"

Write-Step "설치 상태 확인"
if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Stop-WithGuidance "frontend\node_modules 가 없습니다 (npm install 이 아직 안 되었습니다)." @(
        "scripts\start_dev.bat 을 한 번 먼저 실행해 주세요. 설치를 자동으로 해 줍니다.",
        "또는 frontend 폴더에서 'npm install' 을 직접 실행해도 됩니다."
    )
}
Write-Ok "frontend\node_modules 확인"

$venvReady = Test-Path $VenvPython
if ($venvReady) {
    Write-Ok "backend\.venv 확인"
} else {
    Write-Warn "backend\.venv 가 없어 백엔드는 띄우지 않습니다."
    Write-Warn "화면은 뜨지만 'backend 연결 안 됨' 상태가 됩니다 — scripts\start_dev.bat 을 한 번 실행해 주세요."
}

# ---------------------------------------------------------------------------
# (b) 백엔드 (이미 떠 있으면 건드리지 않는다)
# ---------------------------------------------------------------------------
Write-Step "백엔드 서버 (FastAPI / uvicorn, 포트 $BackendPort)"
$backendPid = 0
$backendStartedByUs = $false
$existingBackendPid = Get-ListeningPid $BackendPort
if ($existingBackendPid -gt 0) {
    Write-Ok "포트 $BackendPort 이(가) 이미 실행 중입니다 (PID $existingBackendPid, $(Get-ProcessNameSafe $existingBackendPid)) - 그대로 씁니다"
    $backendPid = $existingBackendPid
} elseif ($venvReady) {
    $backendCmd = "& '.venv\Scripts\python.exe' -m uvicorn app.main:app --reload --port $BackendPort"
    $result = Invoke-Action "새 PowerShell 창에서 실행: (backend) $backendCmd" {
        Start-InNewWindow "BidPilot Backend :$BackendPort" $BackendDir $backendCmd
    }
    if (-not $DryRun) {
        $backendPid = [int]$result
        $backendStartedByUs = $true
        Write-Ok "백엔드 창 실행 (PID $backendPid)"
    }
} else {
    Write-Warn "가상환경이 없어 건너뜁니다."
}

# ---------------------------------------------------------------------------
# (c) 와이어프레임 프론트엔드
# ---------------------------------------------------------------------------
Write-Step "와이어프레임 서버 (Next.js, 포트 $Port)"
if ($Port -ne 4120) {
    Write-Warn "포트가 4120이 아니면 루트(/) rewrite가 꺼집니다. http://localhost:$Port/wireframe 로 접속해 주세요."
}

$frontendPid = 0
$frontendStartedByUs = $false
$existingFrontendPid = Get-ListeningPid $Port
if ($existingFrontendPid -gt 0) {
    if (Test-BidPilotFrontend $Port) {
        Write-Ok "포트 $Port 에 BidPilot 서버가 이미 실행 중입니다 (PID $existingFrontendPid) - 건너뜁니다"
        $frontendPid = $existingFrontendPid
    } else {
        $procName = Get-ProcessNameSafe $existingFrontendPid
        Stop-WithGuidance "포트 $Port 은(는) 다른 프로그램($procName, PID $existingFrontendPid)이 쓰고 있습니다." @(
            "그 프로그램을 끄거나, -Port 4121 처럼 다른 포트를 지정해 다시 실행해 주세요.",
            "(4120이 아닌 포트에서는 http://localhost:<포트>/wireframe 로 접속해야 합니다.)"
        )
    }
}
if ($existingFrontendPid -eq 0) {
    # npm run dev:wireframe 은 --port 4120 이 이미 붙어 있다. 다른 포트면 덮어쓴다.
    # 이 PC 에서만(--hostname 127.0.0.1 · package.json 에도 있음 · recheck28 DOC-05)
    $frontendCmd = "npm run dev:wireframe"
    if ($Port -ne 4120) { $frontendCmd = "npm run dev:wireframe -- --port $Port --hostname 127.0.0.1" }
    # 브라우저가 부를 백엔드 주소를 넘긴다(기본 8110 · -BackendPort 로 바꿨으면 그 값).
    $frontendCmd = "`$env:NEXT_PUBLIC_BACKEND_URL='http://localhost:$BackendPort'; $frontendCmd"
    $result = Invoke-Action "새 PowerShell 창에서 실행: (frontend) $frontendCmd" {
        Start-InNewWindow "BidPilot Wireframe :$Port" $FrontendDir $frontendCmd
    }
    if (-not $DryRun) {
        $frontendPid = [int]$result
        $frontendStartedByUs = $true
        Write-Ok "와이어프레임 창 실행 (PID $frontendPid)"
    }
}

$BackendUrl   = "http://localhost:$BackendPort"
$WireframeUrl = "http://localhost:$Port"
if ($Port -ne 4120) { $WireframeUrl = "http://localhost:$Port/wireframe" }

# ---------------------------------------------------------------------------
# (d) PID 기록 - 우리가 직접 띄운 창만 종료 대상이 된다
# ---------------------------------------------------------------------------
Write-Step "실행 정보 기록"
$record = [ordered]@{
    started_at = (Get-Date).ToString("s")
    repo       = $RepoRoot
    backend    = [ordered]@{ pid = $backendPid;  port = $BackendPort; started_by_script = $backendStartedByUs;  url = $BackendUrl }
    frontend   = [ordered]@{ pid = $frontendPid; port = $Port;        started_by_script = $frontendStartedByUs; url = $WireframeUrl }
}
Invoke-Action "PID 기록: $PidFile" {
    $record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $PidFile -Encoding UTF8
} | Out-Null
if (-not $DryRun) { Write-Ok "기록 완료 (stop_dev.ps1 이 이 파일도 함께 읽습니다)" }

# ---------------------------------------------------------------------------
# (e) 서버 응답 대기 + 브라우저
# ---------------------------------------------------------------------------
Write-Step "서버가 응답할 때까지 대기 (최대 60초)"
if ($DryRun) {
    Write-Plan "$WireframeUrl 가 응답할 때까지 기다립니다"
    if ($NoBrowser) { Write-Plan "브라우저는 열지 않습니다 (-NoBrowser)" }
    else { Write-Plan "브라우저에서 $WireframeUrl 을(를) 엽니다" }
} else {
    if ($backendPid -gt 0) {
        Write-Info "백엔드 health 확인 중 "
        $health = Wait-ForHttp "$BackendUrl/health" 60
        if ($health) { Write-Ok "백엔드 응답: $($health.Trim())" }
        else { Write-Warn "백엔드가 60초 안에 응답하지 않았습니다. 'BidPilot Backend' 창을 확인해 주세요." }
    }

    Write-Info "와이어프레임 확인 중 (첫 컴파일은 시간이 걸립니다) "
    $page = Wait-ForHttp $WireframeUrl 60
    if ($page) { Write-Ok "와이어프레임 응답 확인" }
    else { Write-Warn "60초 안에 응답하지 않았습니다. 'BidPilot Wireframe' 창을 확인한 뒤 브라우저에서 새로고침해 주세요." }

    if ($NoBrowser) {
        Write-Info "브라우저는 열지 않습니다 (-NoBrowser)"
    } else {
        Write-Info "브라우저를 엽니다: $WireframeUrl"
        try { Start-Process $WireframeUrl } catch { Write-Warn "브라우저를 자동으로 열지 못했습니다. 직접 $WireframeUrl 로 접속해 주세요." }
    }
}

# ---------------------------------------------------------------------------
# (f) 요약
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "+------------------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "|  BidPilot AI - 와이어프레임 대시보드                       |" -ForegroundColor Cyan
Write-Host "+------------------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "|  와이어프레임        $WireframeUrl"
Write-Host "|  Evidence Cosmos     http://localhost:$Port/cosmos"
Write-Host "|  공고 후보 목록      http://localhost:$Port/opportunities"
Write-Host "|  백엔드 health       $BackendUrl/health"
Write-Host "|"
Write-Host "|  회색 블록 = 미구현 영역 / 파란 값 = 실제 backend 응답 / 빨간 글씨 = 검토 주석"
Write-Host "|"
Write-Host "|  Evidence Cosmos 를 3110번에 따로 띄우려면: scripts\start_dev.bat"
Write-Host "|  종료: scripts\stop_dev.ps1 실행  (또는 서버 창을 닫기)"
Write-Host "+------------------------------------------------------------------+" -ForegroundColor Cyan
if ($DryRun) { Write-Host "(DryRun 이었으므로 실제로 실행된 것은 없습니다)" -ForegroundColor Magenta }
Write-Host ""
