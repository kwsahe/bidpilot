<#
.SYNOPSIS
  BidPilot AI 개발 서버(백엔드 + 프론트엔드)를 한 번에 띄우는 스크립트.

.DESCRIPTION
  1) node / python 버전 확인
  2) backend\.venv 생성 및 패키지 설치 (필요할 때만)
  3) frontend\node_modules 설치 (필요할 때만)
  4) 루트 .env 생성 (.env.example 복사, 이미 있으면 건드리지 않음)
  5) 백엔드(uvicorn) / 프론트엔드(next dev)를 각각 새 PowerShell 창에서 실행
  6) 서버가 응답할 때까지 기다린 뒤 브라우저 열기
  7) 실행한 PID를 %TEMP%\bidpilot_dev_pids.json 에 기록 (stop_dev.ps1 이 사용)

  Windows PowerShell 5.1 에서 동작하도록 작성했다 (&&, 삼항연산자, ?? 사용 안 함).

.PARAMETER FrontendPort
  프론트엔드 포트 (기본 3110). 다른 프로그램이 쓰고 있으면 그 프로그램을 알려 주고 멈춘다 —
  다른 포트로 몰래 옮기지 않는다(검사 스크립트와 문서가 3110 을 본다).

.PARAMETER BackendPort
  백엔드 포트 (기본 8110). 다른 프로그램이 쓰고 있으면 멈춘다(/health 로 BidPilot 인지 확인).

.PARAMETER NoBrowser
  서버가 뜬 뒤 브라우저를 자동으로 열지 않는다.

.PARAMETER Frozen
  시연 고정 모드로 띄운다 (G2B_LIVE_FETCH=0 · BIZINFO_LIVE_FETCH=0).
  목록 조회가 나라장터·기업마당을 부르지 않고 저장된 캐시만 쓴다.
  발표 중 목록 건수·순위가 바뀌지 않고, Git 이 추적하는 캐시 파일도 덮어써지지 않는다 (ISSUE-062).
  **시연 당일에는 이 스위치를 쓴다.** 키를 지우거나 .env 를 손대지 않아도 된다.

.PARAMETER Provider
  AI 초안 공급자(openai · xai · claude_cli). 비우면 .env 의 LLM_PROVIDER 를 따른다.
  claude_cli 는 키 없이 이 PC 에 로그인된 Claude Code CLI(구독)로 쓴다 — .env 를 고치지 않아도 된다.
  -Ai 와 함께 쓴다 (예: start_demo_claude.bat).

.PARAMETER PlanWriter
  사업계획서 작성 페이지(/plan)의 「Claude로 쓰기」 · 「Codex로 쓰기」 단추만 이 PC 의 CLI 를 부른다 (28차 §3-D · 29차 §3-A).
  서버 전체 AI(-Ai · LLM_LIVE)는 그대로 — 대시보드 6단계 제안서 · 제출 전 점검 · 자격 보강은 규칙만 쓴다.
  예: start_demo_claude.bat (= -Frozen -PlanWriter).

.PARAMETER DryRun
  아무것도 실행하지 않고 "무엇을 할 예정인지"만 출력한다. 스크립트 점검용.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_dev.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_dev.ps1 -DryRun
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_dev.ps1 -FrontendPort 3120 -NoBrowser
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_dev.ps1 -Frozen -NoBrowser
#>
[CmdletBinding()]
param(
    [int]$FrontendPort = 3110,
    [int]$BackendPort = 8110,
    [switch]$NoBrowser,
    [switch]$Frozen,
    # AI 초안만 켠다 (ISSUE-130 · prompt_06 §4-A-3).
    #
    # 담당자 방침: **순위·유사도는 규칙만, AI 는 제안서·사업계획서 초안과 제출 전 점검에만.**
    # 이 스위치는 완성 문(LLM_LIVE)만 열고 나라장터·기업마당·임베딩·의미 유사도는 그대로
    # 꺼 둔다. 시연 중 목록 건수·순위·점수가 바뀌지 않는다는 뜻이다.
    [switch]$Ai,
    [ValidateSet("", "openai", "xai", "claude_cli")]
    [string]$Provider = "",
    # 사업계획서 작성 페이지 단추만 Claude · Codex CLI (28차 §3-D · 29차 §3-A) — LLM_LIVE 와 다른 문
    [switch]$PlanWriter,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# 한글 출력이 깨지지 않도록 콘솔 인코딩을 UTF-8로 맞춘다 (실패해도 계속 진행).
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# ---------------------------------------------------------------------------
# 출력 도우미
# ---------------------------------------------------------------------------
function Write-Step([string]$Message) { Write-Host ""; Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message)   { Write-Host "  [OK]   $Message" -ForegroundColor Green }
function Write-Info([string]$Message) { Write-Host "  [..]   $Message" -ForegroundColor Gray }
function Write-Warn([string]$Message) { Write-Host "  [주의] $Message" -ForegroundColor Yellow }
function Write-Fail([string]$Message) { Write-Host "  [실패] $Message" -ForegroundColor Red }
function Write-Plan([string]$Message) { Write-Host "  [계획] $Message" -ForegroundColor Magenta }

# DryRun 이면 계획만 출력하고, 아니면 실제로 실행한다.
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

# 외부 프로그램을 조용히 실행해 stdout+stderr 를 문자열로 돌려준다.
# ($ErrorActionPreference = Stop 상태에서 stderr 출력이 예외로 바뀌는 것을 막는다)
function Invoke-NativeQuiet([string]$Exe, [string[]]$Arguments) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = (& $Exe @Arguments 2>&1 | Out-String)
        return @{ Output = $out; ExitCode = $LASTEXITCODE }
    } catch {
        return @{ Output = ""; ExitCode = 1 }
    } finally {
        $ErrorActionPreference = $prev
    }
}

# 문자열에서 "3.12.10" 같은 버전을 뽑아 [version] 으로 돌려준다. 못 찾으면 $null.
function ConvertTo-VersionObject([string]$Text) {
    if ($Text -match '(\d+)\.(\d+)(?:\.(\d+))?') {
        $patch = 0
        if ($Matches[3]) { $patch = [int]$Matches[3] }
        return New-Object System.Version ([int]$Matches[1]), ([int]$Matches[2]), $patch
    }
    return $null
}

# 해당 포트를 LISTEN 중인 프로세스 ID (없으면 0).
function Get-ListeningPid([int]$Port) {
    $cmd = Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue
    if ($cmd) {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) { return [int]$conn.OwningProcess }
        return 0
    }
    # 오래된 환경용 fallback: netstat 파싱
    $lines = netstat -ano | Select-String -Pattern "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)"
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
function Test-BidPilotFrontend([int]$Port) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$Port/" -UseBasicParsing -TimeoutSec 8
        return ($r.Content -cmatch '<title>[^<]*BidPilot AI')
    } catch {
        return $false
    }
}

# 해당 포트에 떠 있는 것이 BidPilot 백엔드인지 확인 (/health 의 service 가 bidpilot-api 인지).
function Test-BidPilotBackend([int]$Port) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 5
        return ($r.Content -match '"service"\s*:\s*"bidpilot-api"')
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
function Get-HttpStatus([string]$Url, [int]$TimeoutSec = 60) {
    # 응답 코드 하나 — 404 같은 오류 코드도 돌려준다(Invoke-WebRequest 는 던진다). 연결이 안 되면 0.
    try { return [int](Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec).StatusCode }
    catch [System.Net.WebException] {
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
        return 0
    }
    catch { return 0 }
}

# 동적 경로가 살아 있나 — 지원사업 신청 분석(/support/[id] · 화면은 공고가 없어도 200). 404 면 개발 캐시가 깨진 것이다(39차 §3-F-5).
# /api/[...path] 는 넣지 않는다 — 저장된 응답(스냅숏)을 돌려주는 곳이라 스냅숏이 빈 키트에서는 늘 404 다(39차 키트 시험).
function Test-DynamicRoutes([string]$BaseUrl) {
    return (Get-HttpStatus "$BaseUrl/support/bizinfo-PBLN_000000000123852?welcome=0") -ne 404
}

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
# (a) 저장소 위치 확인
# ---------------------------------------------------------------------------
$RepoRoot    = Split-Path -Parent $PSScriptRoot
$BackendDir  = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$VenvPython  = Join-Path $BackendDir ".venv\Scripts\python.exe"
$PidFile     = Join-Path $env:TEMP "bidpilot_dev_pids.json"
# 실행 기록은 PC 하나에 하나다(%TEMP%). 다른 폴더(저장소 · 키트)에서 켠 서버가 아직 살아 있는데 덮어쓰면, 그 폴더의
# stop_dev 가 자기 서버를 못 끄고 이 폴더의 stop_dev 가 남의 서버를 껐다(33차 KIT-06). 그런 기록이면 아무것도 켜지 않고 멈춘다.
$PreviousRecord = $null
if (Test-Path -LiteralPath $PidFile) {
    try { $PreviousRecord = Get-Content -LiteralPath $PidFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $PreviousRecord = $null }
}
# 기록의 PID 가 **그때 띄운 창**인가 — CIM 생성 시각이 기록 시각 전일 때만 우리 것 · 못 읽으면 남의 것(34차 R33-K2 · stop_dev 와 같은 판단).
# PS 5.1 의 Get-Process StartTime 은 권한이 없으면 예외 없이 비어 와 「우리 것」이 됐다.
. (Join-Path $PSScriptRoot "process_safety.ps1")
function Test-RecordedProcess($Entry, [string]$StartedAt) {
    if (-not $Entry -or -not $Entry.pid) { return $false }
    return (Test-RecordedRow (Get-ProcessTable) ([int]$Entry.pid) $StartedAt)
}
if ($PreviousRecord -and $PreviousRecord.repo -and ($PreviousRecord.repo -ne $RepoRoot) -and -not $DryRun) {
    $otherAlive = @(@($PreviousRecord.backend, $PreviousRecord.frontend) | Where-Object {
        $_ -and $_.started_by_script -and (Test-RecordedProcess $_ $PreviousRecord.started_at)
    })
    if ($otherAlive.Count -gt 0) {
        Write-Host "  [멈춤] 다른 폴더($($PreviousRecord.repo))에서 켠 BidPilot 서버가 아직 켜져 있습니다 — 그 폴더의 scripts\stop_dev.ps1 로 먼저 끄세요(실행 기록을 덮어쓰지 않으려고 멈춥니다)" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "BidPilot AI - 개발 서버 시작" -ForegroundColor White
if ($DryRun) { Write-Host "(DryRun 모드: 실제로 실행하지 않고 계획만 출력합니다)" -ForegroundColor Magenta }
if ($Frozen) {
    Write-Host "(시연 고정 모드: 나라장터·기업마당을 부르지 않고 저장된 목록만 씁니다)" -ForegroundColor Yellow
} else {
    Write-Host "(실호출 모드: 목록 조회가 나라장터를 부를 수 있습니다. 시연 당일에는 -Frozen 을 쓰세요)" -ForegroundColor DarkGray
}

Write-Step "저장소 위치 확인"
if (-not (Test-Path (Join-Path $BackendDir "pyproject.toml")) -or -not (Test-Path (Join-Path $FrontendDir "package.json"))) {
    Stop-WithGuidance "저장소 구조를 찾지 못했습니다: $RepoRoot" @(
        "이 스크립트는 프로그램 폴더의 scripts\ 안에 있어야 합니다.",
        "backend\pyproject.toml 과 frontend\package.json 이 있는지 확인해 주세요."
    )
}
Write-Ok "저장소: $RepoRoot"

# ---------------------------------------------------------------------------
# (b) node / python 확인
# ---------------------------------------------------------------------------
Write-Step "필수 프로그램 확인 (Node 20.9 이상, Python 3.11 이상)"

$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCmd) {
    Stop-WithGuidance "node 를 찾지 못했습니다." @(
        "Node.js LTS(20 이상)를 설치해 주세요: https://nodejs.org/",
        "설치 후 새 터미널을 열고 'node --version' 이 나오는지 확인합니다."
    )
}
$nodeVersion = ConvertTo-VersionObject (& node --version)
# Next 16 은 Node 20.9 이상에서만 돈다(31차 R30-13 — 20.0~20.8 이 통과했다)
if (-not $nodeVersion -or $nodeVersion -lt [System.Version]"20.9.0") {
    Stop-WithGuidance "Node.js 버전이 너무 낮습니다: $(& node --version)" @(
        "Node.js 20.9 이상이 필요합니다 (이 저장소는 22에서 개발). https://nodejs.org/ 에서 LTS 를 설치해 주세요."
    )
}
Write-Ok "node $nodeVersion  ($($nodeCmd.Source))"

# python: 키트(kit_setup.ps1)와 같은 규칙 하나(31차 R30-12) — `py -3` 먼저, 그다음 PATH 의 python, WindowsApps 경로는 맨 뒤
# · **버전을 실제로 물어 3.11 이상인 첫 것**을 쓴다. Store 의 '가짜 python' 별칭은 버전을 답하지 못해 걸러지고, Store 에서
# 설치한 진짜 Python 은 그 경로뿐이라 빼면 못 찾았다(31차 마지막 검토). 낮은 버전만 있으면 그 버전을 알린다.
$PythonExe = $null
$pythonVersion = $null
$lowVersion = $null
$pyCandidates = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $pyCandidates += "py" }
$pythonCmds = @(Get-Command python -All -ErrorAction SilentlyContinue)
$pyCandidates += @($pythonCmds | Where-Object { $_.Source -notlike "*WindowsApps*" } | ForEach-Object { $_.Source })
$pyCandidates += @($pythonCmds | Where-Object { $_.Source -like "*WindowsApps*" } | ForEach-Object { $_.Source })
foreach ($candidate in $pyCandidates) {
    if ($candidate -eq "py") { $probe = Invoke-NativeQuiet "py" @("-3", "--version") }
    else { $probe = Invoke-NativeQuiet $candidate @("--version") }
    $out = $probe.Output
    $v = ConvertTo-VersionObject $out
    if (-not ($v -and $out -match 'Python')) { continue }
    if ($v.Major -gt 3 -or ($v.Major -eq 3 -and $v.Minor -ge 11)) {
        $pythonVersion = $v
        if ($candidate -eq "py") { $PythonExe = "py -3" } else { $PythonExe = $candidate }
        break
    }
    if (-not $lowVersion) { $lowVersion = $v }
}
if (-not $PythonExe -and $lowVersion) { $pythonVersion = $lowVersion; $PythonExe = "(낮은 버전)" }
if (-not $PythonExe) {
    Stop-WithGuidance "python 을 찾지 못했습니다 (또는 Microsoft Store 별칭만 있습니다)." @(
        "Python 3.11 이상을 설치해 주세요: https://www.python.org/downloads/ (설치 시 'Add python.exe to PATH' 체크)",
        "설치했는데도 이 메시지가 나오면: 설정 > 앱 > 앱 실행 별칭 에서 'python.exe' 항목을 끄고 새 터미널을 여세요."
    )
}
if ($pythonVersion.Major -lt 3 -or ($pythonVersion.Major -eq 3 -and $pythonVersion.Minor -lt 11)) {
    Stop-WithGuidance "Python 버전이 너무 낮습니다: $pythonVersion" @(
        "Python 3.11 이상이 필요합니다 (이 저장소는 3.12에서 개발). https://www.python.org/downloads/"
    )
}
Write-Ok "python $pythonVersion  ($PythonExe)"

# ---------------------------------------------------------------------------
# (c) backend\.venv 생성
# ---------------------------------------------------------------------------
Write-Step "백엔드 가상환경 (backend\.venv)"
$venvExists = Test-Path $VenvPython
if ($venvExists) {
    Write-Ok "이미 있음: $VenvPython"
} else {
    Invoke-Action "python -m venv backend\.venv 로 가상환경을 만듭니다 (uv 는 사용하지 않습니다)" {
        if ($PythonExe -eq "py -3") { & py -3 -m venv (Join-Path $BackendDir ".venv") }
        else { & $PythonExe -m venv (Join-Path $BackendDir ".venv") }
        if ($LASTEXITCODE -ne 0) { throw "venv 생성 실패" }
    } | Out-Null
    if (-not $DryRun) { Write-Ok "가상환경 생성 완료" }
}

# ---------------------------------------------------------------------------
# (d) 백엔드 패키지 설치 (import 가 실패할 때만)
# ---------------------------------------------------------------------------
Write-Step "백엔드 패키지 (fastapi, pdfplumber 등)"
$needInstall = $true
if (Test-Path $VenvPython) {
    $probe = Invoke-NativeQuiet $VenvPython @("-c", "import fastapi, pdfplumber")
    if ($probe.ExitCode -eq 0) { $needInstall = $false }
}
if (-not $needInstall) {
    Write-Ok "이미 설치되어 있어 건너뜁니다"
} else {
    if (-not (Test-Path $VenvPython)) { Write-Info "가상환경이 아직 없으므로 생성 후 설치합니다" }
    Invoke-Action "backend\.venv\Scripts\python.exe -m pip install -e `".[dev]`"  (backend 폴더에서 실행, 1~2분 소요)" {
        Push-Location $BackendDir
        try {
            & $VenvPython -m pip install -e ".[dev]"
            if ($LASTEXITCODE -ne 0) { throw "pip install 실패" }
        } finally { Pop-Location }
    } | Out-Null
    if (-not $DryRun) { Write-Ok "백엔드 패키지 설치 완료" }
}

# ---------------------------------------------------------------------------
# (e) 프론트엔드 npm install (node_modules 가 없을 때만)
# ---------------------------------------------------------------------------
Write-Step "프론트엔드 패키지 (frontend\node_modules)"
if (Test-Path (Join-Path $FrontendDir "node_modules")) {
    Write-Ok "이미 설치되어 있어 건너뜁니다"
} else {
    Invoke-Action "npm install  (frontend 폴더에서 실행, 처음에는 몇 분 걸릴 수 있습니다)" {
        Push-Location $FrontendDir
        try {
            & npm install
            if ($LASTEXITCODE -ne 0) { throw "npm install 실패" }
        } finally { Pop-Location }
    } | Out-Null
    if (-not $DryRun) { Write-Ok "프론트엔드 패키지 설치 완료" }
}

# ---------------------------------------------------------------------------
# (f) 루트 .env
# ---------------------------------------------------------------------------
Write-Step "환경변수 파일 (.env)"
$envFile    = Join-Path $RepoRoot ".env"
$envExample = Join-Path $RepoRoot ".env.example"
if (Test-Path $envFile) {
    Write-Ok ".env 가 이미 있어 그대로 둡니다 (덮어쓰지 않음)"
} elseif (Test-Path $envExample) {
    Invoke-Action ".env.example 을 복사해 .env 를 만듭니다" {
        Copy-Item -LiteralPath $envExample -Destination $envFile
    } | Out-Null
    Write-Info "데모 실행에는 API 키가 필요 없습니다. 키 칸은 비워 두어도 됩니다 (나라장터 키가 없으면 sample 모드)."
} else {
    Write-Warn ".env.example 이 없어 .env 를 만들지 않습니다 (데모에는 없어도 동작합니다)"
}

# ---------------------------------------------------------------------------
# (f-2) 포트 확인 — 프론트 3110 · 백엔드 8110 (2026-09-28 담당자 지시 「앞으로도 계속」)
# ---------------------------------------------------------------------------
# 3000·8000 은 이 PC 의 다른 프로젝트가 쓴다. 예전 런처는 8000 에 **다른 앱의 백엔드**가 떠 있어도
# 「이미 실행 중」으로 보고 그것을 우리 백엔드로 썼고, 프론트는 3000 이 차 있으면 다음 빈 포트로
# 몰래 옮겼다. 그러면 화면·검사 스크립트·문서가 서로 다른 주소를 본다. 그래서 포트는 고정하고,
# 차 있으면 **누구인지 확인해** 우리 것이면 그대로 쓰고 아니면 멈춘다. 둘 다 먼저 본다 —
# 한쪽만 띄우고 멈추지 않게.
Write-Step "포트 확인 (프론트엔드 $FrontendPort · 백엔드 $BackendPort)"
$existingBackendPid = Get-ListeningPid $BackendPort
$existingFrontendPid = Get-ListeningPid $FrontendPort
if ($existingBackendPid -gt 0 -and -not (Test-BidPilotBackend $BackendPort)) {
    Stop-WithGuidance "포트 $BackendPort 은(는) 다른 프로그램($(Get-ProcessNameSafe $existingBackendPid), PID $existingBackendPid)이 쓰고 있습니다." @(
        "그 프로그램을 끄거나, -BackendPort 8120 처럼 다른 포트를 지정해 다시 실행해 주세요.",
        "BidPilot 기본 포트: 프론트엔드 3110 · 백엔드 8110"
    )
}
if ($existingFrontendPid -gt 0 -and -not (Test-BidPilotFrontend $FrontendPort)) {
    Stop-WithGuidance "포트 $FrontendPort 은(는) 다른 프로그램($(Get-ProcessNameSafe $existingFrontendPid), PID $existingFrontendPid)이 쓰고 있습니다." @(
        "그 프로그램을 끄거나, -FrontendPort 3120 처럼 다른 포트를 지정해 다시 실행해 주세요.",
        "BidPilot 기본 포트: 프론트엔드 3110 · 백엔드 8110"
    )
}
Write-Ok "포트를 쓸 수 있습니다"

# ---------------------------------------------------------------------------
# (g) 백엔드 실행
# ---------------------------------------------------------------------------
Write-Step "백엔드 서버 (FastAPI / uvicorn, 포트 $BackendPort)"
$backendPid = 0
$backendStartedByUs = $false
if ($existingBackendPid -gt 0) {
    Write-Ok "포트 $BackendPort 에 BidPilot 백엔드가 이미 실행 중입니다 (PID $existingBackendPid) - 건너뜁니다"
    $backendPid = $existingBackendPid
} else {
    # 127.0.0.1 을 명시한다. uvicorn 기본값도 같지만, 손으로 띄울 때 --host 0.0.0.0 을 붙인
    # 적이 있어 같은 LAN 의 누구나 인증 없이 회사자료 API 를 부를 수 있었다 (ISSUE-063).
    # 여기 적어 두면 「저장소 방식으로 띄운 서버는 밖에서 안 보인다」가 눈으로 확인된다.
    # 실조회는 **양쪽 다 명시한다** (ISSUE-120 · prompt_03 §4-A-1).
    #
    # 설정 기본값이 「꺼짐」으로 바뀌었다. 예전에는 -Frozen 일 때만 0 을 세우고 그 밖에는
    # 아무것도 안 세웠는데, 그때는 기본값이 켜짐이라 그것으로 충분했다. 지금은 반대다 —
    # 아무것도 안 세우면 개발 서버가 캐시만 읽는 서버가 된다. 그래서 고정 모드가 아닐 때
    # 여기서 1 을 **명시적으로** 세운다. 「부르는 쪽」은 언제나 손으로 적혀 있어야 한다.
    #
    # 임베딩 둘도 같은 자리에서 정한다 (ISSUE-129 · prompt_05 §4-A-2). 14차까지 고정 모드는
    # 나라장터·기업마당만 막았고, 그래서 고정 모드로 띄운 서버가 목록을 만들며 OpenAI
    # 임베딩 1,802건을 불렀다. EMBEDDING_LIVE 는 「바깥을 부르는가」, SEMANTIC_FIT 은
    # 「점수에 쓰는가」다 — 캐시 벡터가 디스크에 남아 있어도 뒤쪽이 0 이면 숫자가 고정된다.
    if ($Frozen) {
        $envPrefix = "`$env:G2B_LIVE_FETCH='0'; `$env:BIZINFO_LIVE_FETCH='0'; `$env:EMBEDDING_LIVE='0'; `$env:SEMANTIC_FIT='0'; "
    } else {
        $envPrefix = "`$env:G2B_LIVE_FETCH='1'; `$env:BIZINFO_LIVE_FETCH='1'; `$env:EMBEDDING_LIVE='1'; `$env:SEMANTIC_FIT='1'; "
    }
    # 완성 문은 **따로** 정한다 (ISSUE-130 · prompt_06 §4-A-3). `-Ai` 가 없으면 꺼짐이다 —
    # 고정 모드든 아니든 마찬가지다. 「AI 는 제안서·사업계획서·점검에만」이 방침이므로
    # 켜는 자리를 한 곳(이 스위치)으로 둔다.
    $envPrefix += if ($Ai) { "`$env:LLM_LIVE='1'; " } else { "`$env:LLM_LIVE='0'; " }
    # 공급자는 창 환경으로만 정한다 — 환경이 루트 .env 보다 앞서므로 .env 를 고치지 않아도 된다.
    if ($Provider) { $envPrefix += "`$env:LLM_PROVIDER='$Provider'; " }
    # 사업계획서 작성 문 (28차 §3-D) — 이것만 켜면 /plan 단추만 CLI 를 부른다(LLM_LIVE 는 위 -Ai 그대로).
    $envPrefix += if ($PlanWriter) { "`$env:PLAN_WRITER_CLI='1'; " } else { "`$env:PLAN_WRITER_CLI='0'; " }
    # 두 창이 같은 주소를 보게 여기서 정한다(루트 .env 보다 앞선다). FRONTEND_URL 은 CORS 허용
    # 목록의 기본값이다 — 개발 모드는 localhost 전 포트를 허용하지만 값은 한 곳에서 온다.
    $envPrefix += "`$env:FRONTEND_URL='http://localhost:$FrontendPort'; `$env:BACKEND_URL='http://localhost:$BackendPort'; "
    $backendCmd = "$envPrefix& '.venv\Scripts\python.exe' -m uvicorn app.main:app --reload --host 127.0.0.1 --port $BackendPort"
    $result = Invoke-Action "새 PowerShell 창에서 실행: (backend) $backendCmd" {
        Start-InNewWindow "BidPilot Backend :$BackendPort" $BackendDir $backendCmd
    }
    if (-not $DryRun) {
        $backendPid = [int]$result
        $backendStartedByUs = $true
        Write-Ok "백엔드 창 실행 (PID $backendPid)"
    }
}

# ---------------------------------------------------------------------------
# (h) 프론트엔드 실행
# ---------------------------------------------------------------------------
Write-Step "프론트엔드 서버 (Next.js, 포트 $FrontendPort)"
$frontendPid = 0
$frontendStartedByUs = $false
if ($existingFrontendPid -gt 0) {
    Write-Ok "포트 $FrontendPort 에 BidPilot 프론트엔드가 이미 실행 중입니다 (PID $existingFrontendPid) - 건너뜁니다"
    $frontendPid = $existingFrontendPid
    # 그 화면의 백엔드 주소는 **띄울 때** 정해졌다(기본 8110). -BackendPort 로 바꿨다면 옛 주소를 부른다.
    # 앞선 실행 기록에 같은 두 포트가 있으면 그 화면은 이 백엔드로 띄운 것이다 — 키트 다시 실행(3120/8120)에 거짓 주의가 났다(32차).
    $samePair = $false
    if (Test-Path -LiteralPath $PidFile) {
        try {
            $previous = Get-Content -LiteralPath $PidFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $samePair = ([int]$previous.frontend.port -eq $FrontendPort) -and ([int]$previous.backend.port -eq $BackendPort)
        } catch { $samePair = $false }
    }
    if ($BackendPort -ne 8110 -and -not $samePair) {
        Write-Warn "이미 떠 있는 화면은 띄울 때 정한 백엔드(기본 8110)를 부릅니다. -BackendPort $BackendPort 을(를) 쓰려면 scripts\stop_dev.ps1 로 끄고 다시 띄우세요."
    }
}
if ($existingFrontendPid -eq 0) {
    # 브라우저가 부를 백엔드 주소를 넘긴다. 넘기지 않으면 코드의 기본값(lib/api.ts)을 쓰는데,
    # -BackendPort 로 바꿔 띄우면 화면이 옛 주소를 불러 「백엔드에 연결할 수 없습니다」가 된다.
    # --hostname 127.0.0.1 — 이 PC 에서만 열린다. 빼면 next dev 가 모든 주소(::)에서 들어 같은 사내망의 다른 PC 가
    # 회사 프로필을 읽을 수 있었다(recheck28 DOC-05). 백엔드도 127.0.0.1 이다.
    $frontendCmd = "`$env:NEXT_PUBLIC_BACKEND_URL='http://localhost:$BackendPort'; npm run dev -- --port $FrontendPort --hostname 127.0.0.1"
    $result = Invoke-Action "새 PowerShell 창에서 실행: (frontend) $frontendCmd" {
        Start-InNewWindow "BidPilot Frontend :$FrontendPort" $FrontendDir $frontendCmd
    }
    if (-not $DryRun) {
        $frontendPid = [int]$result
        $frontendStartedByUs = $true
        Write-Ok "프론트엔드 창 실행 (PID $frontendPid)"
    }
}

$BackendUrl  = "http://localhost:$BackendPort"
$FrontendUrl = "http://localhost:$FrontendPort"

# ---------------------------------------------------------------------------
# (j) PID 기록 (stop_dev.ps1 용) - 우리가 직접 띄운 창만 기록한다
# ---------------------------------------------------------------------------
Write-Step "실행 정보 기록"
$record = [ordered]@{
    started_at = (Get-Date).ToString("s")
    repo       = $RepoRoot
    backend    = [ordered]@{ pid = $backendPid;  port = $BackendPort;  started_by_script = $backendStartedByUs;  url = $BackendUrl }
    frontend   = [ordered]@{ pid = $frontendPid; port = $FrontendPort; started_by_script = $frontendStartedByUs; url = $FrontendUrl }
}
# 한쪽만 이미 켜져 있었다 — 그쪽을 띄운 앞선 기록(같은 폴더 · 같은 포트 · 창이 살아 있음)을 옮겨 적는다. 덮으면 stop_dev 가
# 앞서 띄운 그 창을 끄지 못했다(33차 KIT-07).
if ($PreviousRecord -and ($PreviousRecord.repo -eq $RepoRoot)) {
    foreach ($side in @("backend", "frontend")) {
        $prev = $PreviousRecord.$side
        if ($record[$side].started_by_script -or -not $prev -or -not $prev.started_by_script) { continue }
        if ([int]$prev.port -ne [int]$record[$side].port) { continue }
        if (-not (Test-RecordedProcess $prev $PreviousRecord.started_at)) { continue }
        $record[$side] = [ordered]@{ pid = [int]$prev.pid; port = [int]$prev.port; started_by_script = $true; url = $record[$side].url }
    }
}
if (-not $backendStartedByUs -and -not $frontendStartedByUs -and (Test-Path -LiteralPath $PidFile)) {
    # 둘 다 이미 켜져 있었다 — 그 서버를 띄운 앞선 기록을 덮으면 stop_dev.ps1 이 아무것도 끄지 못한다(32차 R31-28)
    Write-Ok "두 서버 모두 이미 켜져 있어 앞선 실행 기록을 그대로 둡니다 (stop_dev.ps1 이 그 기록으로 끕니다)"
} else {
    Invoke-Action "PID 기록: $PidFile" {
        $record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $PidFile -Encoding UTF8
    } | Out-Null
    if (-not $DryRun) { Write-Ok "기록 완료 (stop_dev.ps1 이 이 파일을 읽어 종료합니다)" }
}

# ---------------------------------------------------------------------------
# (i) 서버 응답 대기 + 브라우저
# ---------------------------------------------------------------------------
Write-Step "서버가 응답할 때까지 대기 (최대 60초)"
if ($DryRun) {
    Write-Plan "$BackendUrl/health 가 응답할 때까지 기다립니다"
    Write-Plan "$FrontendUrl/ 가 응답할 때까지 기다립니다"
    if ($NoBrowser) { Write-Plan "브라우저는 열지 않습니다 (-NoBrowser)" }
    else { Write-Plan "브라우저에서 $FrontendUrl 을(를) 엽니다" }
} else {
    Write-Info "백엔드 health 확인 중 "
    $health = Wait-ForHttp "$BackendUrl/health" 60
    if ($health) { Write-Ok "백엔드 응답: $($health.Trim())" }
    else { Write-Warn "백엔드가 60초 안에 응답하지 않았습니다. 'BidPilot Backend' 창의 오류 메시지를 확인해 주세요." }

    Write-Info "프론트엔드 확인 중 (첫 컴파일은 시간이 걸립니다) "
    $page = Wait-ForHttp "$FrontendUrl/" 60
    if ($page) { Write-Ok "프론트엔드 응답 확인" }
    else { Write-Warn "프론트엔드가 60초 안에 응답하지 않았습니다. 'BidPilot Frontend' 창을 확인해 주세요. 조금 더 기다린 뒤 브라우저에서 새로고침하면 뜨는 경우가 많습니다." }

    # 39차 §3-F-5 — 개발 캐시(frontend\.next\dev)가 깨지면 첫 화면은 뜨는데 동적 경로(/support/<id>)가 404 였다
    # (10-18 · 「지원사업 신청 분석 열기」가 「찾는 화면이 없습니다」). 첫 화면 제목만 봐서는 못 잡는다 — 동적 경로를 한 번 부른다.
    # 11-01 — 깨진 캐시가 첫 화면부터 500 인 꼴도 있었다(글꼴 모듈 noto_sans_kr 을 못 찾음 · 폴더를 비키니 바로 200). 그때도 같이 고친다.
    $cacheBroken = if ($page) { -not (Test-DynamicRoutes $FrontendUrl) } else { (Get-HttpStatus "$FrontendUrl/") -eq 500 }
    if ($cacheBroken) {
        if ($frontendStartedByUs -and $frontendPid -gt 0) {
            Write-Warn "화면 캐시가 깨졌습니다(첫 화면 500 또는 동적 경로 404) — 화면 캐시(frontend\.next\dev)를 비키고 프론트엔드를 한 번 다시 켭니다"
            & taskkill.exe /PID $frontendPid /T /F 2>$null | Out-Null
            Start-Sleep -Seconds 2
            $devCache = Join-Path $FrontendDir ".next\dev"
            if (Test-Path -LiteralPath $devCache) {
                $stale = "dev.stale-" + (Get-Date).ToString("yyyyMMdd-HHmmss")
                try { Rename-Item -LiteralPath $devCache -NewName $stale -ErrorAction Stop; Write-Info "비킨 곳: frontend\.next\$stale (지워도 됩니다)" }
                catch { Write-Warn "화면 캐시를 비키지 못했습니다: $($_.Exception.Message)" }
            }
            $frontendPid = [int](Start-InNewWindow "BidPilot Frontend :$FrontendPort" $FrontendDir $frontendCmd)
            $record.frontend.pid = $frontendPid
            # 기록 시각도 새로 — stop_dev 는 「기록 시각(+5초) 전에 생긴 창」만 우리 것으로 끈다(process_safety). 백엔드 창은 더 일찍 생겨 그대로 맞다.
            $record.started_at = (Get-Date).ToString("s")
            $record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $PidFile -Encoding UTF8
            $page = Wait-ForHttp "$FrontendUrl/" 90
        }
        if ($page -and (Test-DynamicRoutes $FrontendUrl)) { Write-Ok "첫 화면 · 동적 경로 응답 확인(/support/…)" }
        # 캐시를 비키고 다시 켰는데도 첫 화면이 500 이면 캐시가 아니라 코드 오류일 수 있다(11-01 독립 검토) — 캐시를 또 지우라고 하지 않는다
        elseif (-not $page -and $frontendStartedByUs) { Write-Fail "화면 캐시를 비키고 다시 켰는데도 첫 화면이 열리지 않습니다 — 'BidPilot Frontend' 창의 빨간 오류 글을 확인하세요(캐시가 아니라 코드 오류일 수 있습니다)" }
        else { Write-Fail "화면 캐시를 지우고 다시 켜세요 — scripts\stop_dev.ps1 로 끈 뒤 frontend\.next\dev 폴더를 지우고 이 스크립트를 다시 실행합니다" }
    } elseif ($page) {
        Write-Ok "동적 경로 응답 확인(/support/…)"
    }

    if ($NoBrowser) {
        Write-Info "브라우저는 열지 않습니다 (-NoBrowser)"
    } else {
        Write-Info "브라우저를 엽니다: $FrontendUrl"
        try { Start-Process $FrontendUrl } catch { Write-Warn "브라우저를 자동으로 열지 못했습니다. 직접 $FrontendUrl 로 접속해 주세요." }
    }
}

# ---------------------------------------------------------------------------
# (k) 요약
# ---------------------------------------------------------------------------
$docsDir = Join-Path $RepoRoot "docs"
# 요약은 **실제 서버 상태**(/health)로 찍는다 — 이미 켜져 있던 서버를 건너뛰면 이번 플래그와 다를 수 있다
# (start_demo_claude.bat 을 눌렀는데 앞서 켠 실호출 서버가 남아 「단추를 누를 때만」으로 찍혔다 · recheck28 DOC-02).
$live = $null
if (-not $DryRun -and $health) { try { $live = $health | ConvertFrom-Json } catch { $live = $null } }
$isFrozen = if ($live) { [bool]$live.live_fetch_frozen } else { [bool]$Frozen }
$isPlanWriter = if ($live) { [bool]$live.plan_writer_cli } else { [bool]$PlanWriter }
$isAi = if ($live) { [bool]$live.llm_live } else { [bool]$Ai }
Write-Host ""
Write-Host "+------------------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "|  BidPilot AI - 개발 서버 요약                              |" -ForegroundColor Cyan
Write-Host "+------------------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "|  대시보드 (프론트)   $FrontendUrl"
Write-Host "|  공고 후보 목록      $FrontendUrl/opportunities"
Write-Host "|  사업계획서 작성     $FrontendUrl/plan"
Write-Host "|  백엔드 health       $BackendUrl/health"
if (-not $backendStartedByUs -and $live) {
Write-Host "|  (백엔드는 이미 켜져 있어 건너뜀 — 아래는 그 서버의 실제 상태 · 바꾸려면 끈 뒤 다시 켜세요)" -ForegroundColor Yellow
}
if ($isFrozen) {
Write-Host "|  데이터              저장본만 씀 (고정 모드 · 새로 받기 잠김)
|  사업계획서 작성: $(if ($isPlanWriter) { 'Claude · Codex — 단추를 누를 때만' } else { '꺼짐' })"
Write-Host "|  AI 초안            $(if ($isAi) { '켜짐 (제안서·사업계획서·점검에만 · 순위와 유사도는 규칙)' } else { '꺼짐 (규칙으로만)' })$(if ($Provider) { " · 공급자 $Provider" } else { '' })"
} else {
Write-Host "|  데이터              실호출 모드 (개발용 · 매일 쓸 때는 start_dev.bat)"
Write-Host "|  사업계획서 작성: $(if ($isPlanWriter) { 'Claude · Codex — 단추를 누를 때만' } else { '꺼짐' })"
Write-Host "|  새로 받기           실호출 모드라 사업기회 화면의 「나라장터 새로 받기」「기업마당 새로 받기」 단추가 켜집니다"
}
Write-Host "|  백엔드 API 문서     $BackendUrl/docs"
Write-Host "|"
Write-Host "|  끄기: BidPilot 서버 창 두 개를 닫거나 아래 명령(어느 폴더에서나)"
Write-Host "|        powershell -NoProfile -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\stop_dev.ps1`""
if (Test-Path (Join-Path $docsDir "getting_started.md")) {  # 키트에는 docs 가 없다(30차 §3-G — KIT_README.md)
    Write-Host "|  문서: $docsDir\getting_started.md (개발자용)"
    Write-Host "|        $docsDir\user_guide.md (사용 안내)"
}
Write-Host "+------------------------------------------------------------------+" -ForegroundColor Cyan
if ($DryRun) { Write-Host "(DryRun 이었으므로 실제로 실행된 것은 없습니다)" -ForegroundColor Magenta }
Write-Host ""
