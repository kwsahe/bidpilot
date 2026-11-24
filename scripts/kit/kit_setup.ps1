<#
.SYNOPSIS
  BidPilot AI 범용 설치 키트 — 프로그램 확인 · 설치 · 첫 실행 질문 · 시작 (30차 §3-G).
.DESCRIPTION
  1) Python 3.11 이상 · Node 20 이상이 있는지 본다. 없으면 winget 설치 명령을 보여 주고 멈춘다(대신 설치하지 않는다).
  2) .env 가 없으면 .env.example 을 복사한다. 빈 칸만 채운다(값은 화면 · 로그에 찍지 않는다).
  3) 백엔드 venv · pip 설치, 프론트 npm 설치 — 설치가 끝났는지는 실제로 불러 보고(fastapi · pydantic_settings · pdfplumber ·
     node_modules\.bin\next.cmd) 정한다. 지난번 설치가 끊겼으면 다시 설치한다(31차 R30-08).
  4) 처음 켤 때만 묻는다 — 회사 이름 · 사업영역 · 활동 지역 · 나라장터 키 · 기업마당 키 · Claude/Codex 사용 여부.
     매개변수로도 받는다(시험 · 무인 설치용). 회사 이름은 화면에서 못 고치므로 백엔드를 띄우기 전에 받는다.
  5) 실시간 모드로 시작한다(-Frozen 없음). 키가 없으면 「저장된 예시 목록만 보입니다」라고 알린다.
  Claude · Codex 답과 바꾼 포트는 .env(KIT_PLAN_WRITER · KIT_FRONTEND_PORT · KIT_BACKEND_PORT)에 남겨 다음 실행도 같게 켠다(31차 R30-07 · R30-11).
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File kit_setup.ps1
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File kit_setup.ps1 -CompanyName "주식회사 시험" -Domains "AI 교육, 컨설팅" -NonInteractive -FrontendPort 3120 -BackendPort 8120 -NoBrowser
#>
[CmdletBinding()]
param(
    [string]$CompanyName = "",
    [string]$Domains = "",
    [string]$Regions = "",
    [string]$G2bKey = "",
    [string]$BizinfoKey = "",
    [switch]$UseClaude,
    [switch]$UseCodex,
    [switch]$NonInteractive,
    [int]$FrontendPort = 0,
    [int]$BackendPort = 0,
    [switch]$NoBrowser,
    [switch]$SkipStart
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$Root = $PSScriptRoot
$Utf8 = New-Object System.Text.UTF8Encoding $false

function Write-Step([string]$Message) { Write-Host ""; Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message)   { Write-Host "  [OK]   $Message" -ForegroundColor Green }
function Write-Info([string]$Message) { Write-Host "  [..]   $Message" -ForegroundColor Gray }
function Write-Warn([string]$Message) { Write-Host "  [주의] $Message" -ForegroundColor Yellow }
function Stop-Kit([string]$Message)   { Write-Host "  [멈춤] $Message" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------------------
# 1) 프로그램 확인
# ---------------------------------------------------------------------------
Write-Step "프로그램 확인 (Python 3.11 이상 · Node 20.9 이상)"

function Get-PythonCommand {
    $candidates = @()
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { $candidates += , @($py.Source, "-3") }
    # WindowsApps 경로는 맨 뒤 — Store 의 가짜 별칭은 아래 버전 확인에서 걸러지고, Store 에서 설치한 진짜 Python 은 그 경로뿐이다
    $pythonCmds = @(Get-Command python -All -ErrorAction SilentlyContinue)
    foreach ($cmd in @($pythonCmds | Where-Object { $_.Source -notlike "*WindowsApps*" }) + @($pythonCmds | Where-Object { $_.Source -like "*WindowsApps*" })) {
        $candidates += , @($cmd.Source)
    }
    foreach ($candidate in $candidates) {
        try {
            $exe = $candidate[0]
            $rest = @($candidate | Select-Object -Skip 1)
            $version = (& $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null)
            if ($version -match "^(\d+)\.(\d+)$" -and ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11))) {
                return , $candidate
            }
        } catch { }
    }
    return $null
}

$python = Get-PythonCommand
$node = Get-Command node -ErrorAction SilentlyContinue
$nodeOk = $false
if ($node) {
    $nodeVersion = (& $node.Source --version) -replace "^v", ""
    $parts = $nodeVersion.Split(".")
    # Next 16 은 Node 20.9 이상에서만 돈다(31차 R30-13 — 20.0~20.8 이 통과했다)
    $nodeOk = ([int]$parts[0] -gt 20) -or ([int]$parts[0] -eq 20 -and [int]$parts[1] -ge 9)
}
if (-not $python -or -not $nodeOk) {
    if (-not $python) { Write-Warn "Python 3.11 이상이 없습니다. 설치 명령:  winget install -e --id Python.Python.3.12" }
    if (-not $nodeOk) { Write-Warn "Node 20.9 이상이 없습니다. 설치 명령:  winget install -e --id OpenJS.NodeJS.LTS" }
    Stop-Kit "위 프로그램을 설치한 뒤 창을 새로 열고 다시 실행하세요"
}
Write-Ok "Python $(& $python[0] @($python | Select-Object -Skip 1) --version 2>&1) · Node v$nodeVersion"

# ---------------------------------------------------------------------------
# 2) .env (빈 칸만 채운다 · 값은 찍지 않는다)
# ---------------------------------------------------------------------------
Write-Step "설정 파일 (.env)"
$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $Root ".env.example") $envFile
    Write-Ok ".env.example 을 복사해 .env 를 만들었습니다"
} else {
    Write-Ok ".env 가 이미 있어 빈 칸만 채웁니다"
}

function Get-EnvValue([string]$Key) {
    $line = [System.IO.File]::ReadAllLines($envFile, $Utf8) | Where-Object { $_ -match "^$Key=" } | Select-Object -First 1
    if (-not $line) { return "" }
    return ($line -replace "^$Key=", "").Trim()
}

# KIT_PLAN_WRITER — 1(둘 다) · claude · codex · 0(안 씀). KIT_README 4-1 의 「1」과 같은 뜻.
function PlanWriterValue([bool]$Claude, [bool]$Codex) {
    if ($Claude -and $Codex) { return "1" }
    if ($Claude) { return "claude" }
    if ($Codex) { return "codex" }
    return "0"
}

function Set-EnvLine([string]$Key, [string]$Value, [bool]$Overwrite) {
    $lines = [System.Collections.Generic.List[string]]([System.IO.File]::ReadAllLines($envFile, $Utf8))
    $index = -1
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match "^$Key=") { $index = $i; break } }
    if ($index -ge 0) {
        $current = ($lines[$index] -replace "^$Key=", "").Trim()
        if ($current -eq $Value) { return $false }
        if ($current -and -not $Overwrite) {
            # 다시 실행 때 새로 준 값이 말없이 버려지던 것(31차 R30-16) — 값은 찍지 않고 알린다.
            Write-Warn "$Key 는 .env 에 이미 값이 있어 새로 준 값을 넣지 않았습니다 — 바꾸려면 .env 를 메모장으로 열어 고치세요 (값은 표시하지 않음)"
            return $false
        }
        $lines[$index] = "$Key=$Value"
    } else {
        $lines.Add("$Key=$Value")
    }
    [System.IO.File]::WriteAllLines($envFile, $lines, $Utf8)
    # 이번 실행에 설정을 바꿨다 — 서버가 이미 켜져 있으면 껐다 켜야 적용된다(33차 KIT-02)
    if ($Key -ne "KIT_KEYS_ASKED") { $script:EnvChanged = $true }
    return $true
}
$script:EnvChanged = $false

function Set-EnvIfEmpty([string]$Key, [string]$Value) {
    if (-not $Value) { return }
    if (Set-EnvLine $Key $Value $false) { Write-Ok "$Key 를 채웠습니다 (값은 표시하지 않음)" }
}

function Set-EnvValue([string]$Key, [string]$Value) {
    if (Set-EnvLine $Key $Value $true) { Write-Ok "$Key=$Value 를 기억합니다" }
}

# 포트 — 이번에 주면 기억하고, 안 주면 지난번 값(없으면 3110 · 8110)으로 켠다(31차 R30-11).
if ($FrontendPort -gt 0) { Set-EnvValue "KIT_FRONTEND_PORT" "$FrontendPort" }
elseif (Get-EnvValue "KIT_FRONTEND_PORT") { $FrontendPort = [int](Get-EnvValue "KIT_FRONTEND_PORT") }
else { $FrontendPort = 3110 }
if ($BackendPort -gt 0) { Set-EnvValue "KIT_BACKEND_PORT" "$BackendPort" }
elseif (Get-EnvValue "KIT_BACKEND_PORT") { $BackendPort = [int](Get-EnvValue "KIT_BACKEND_PORT") }
else { $BackendPort = 8110 }

$frontEnv = Join-Path $Root "frontend\.env.local"
if (-not (Test-Path $frontEnv)) {
    [System.IO.File]::WriteAllText($frontEnv, "NEXT_PUBLIC_DEFAULT_ORGANIZATION_ID=org-main`r`nNEXT_PUBLIC_KIT=1`r`n", $Utf8)
    Write-Ok "frontend\.env.local 을 만들었습니다 (기본 회사 org-main)"
}

# ---------------------------------------------------------------------------
# 3) 설치 (처음에만 — 인터넷이 필요합니다)
# ---------------------------------------------------------------------------
Write-Step "설치 (처음에만 몇 분 걸립니다)"
$venvPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
# 폴더만 보고 건너뛰면 지난번에 끊긴 설치가 그대로 남았다(31차 R30-08) — 실제로 불러 본다.
# PowerShell 5.1 은 $ErrorActionPreference=Stop 에서 네이티브 프로그램의 stderr(2>$null 로 돌린 것)를 멈추는 오류로
# 바꾼다 — 끊긴 설치를 알아보려는 바로 이 줄이 빨간 오류로 죽었다(32차 R31-25). 이 줄만 Continue 로 두고 종료 코드로 판단한다.
function Test-BackendImport {
    if (-not (Test-Path $venvPython)) { return $false }
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $venvPython -c "import fastapi, pydantic_settings, pdfplumber" 2>$null | Out-Null } finally { $ErrorActionPreference = $previousPreference }
    return ($LASTEXITCODE -eq 0)
}
# 설치 표시 — 설치 목록 파일(pyproject.toml · package-lock.json)의 해시. 새 zip 을 옛 폴더에 덮어 풀면 부품 목록이 바뀌었는데
# 「설치가 이미 되어 있습니다」로 건너뛰어 /guide 가 react-markdown 을 못 찾았다(33차 KIT-03). 해시가 다르면 다시 설치한다.
function Get-FileSha1([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    return (Get-FileHash -Algorithm SHA1 -LiteralPath $Path).Hash
}
$backendManifest = Get-FileSha1 (Join-Path $Root "backend\pyproject.toml")
$backendMark = Join-Path $Root "backend\.venv\.kit_installed"
$frontendManifest = Get-FileSha1 (Join-Path $Root "frontend\package-lock.json")
$frontendMark = Join-Path $Root "frontend\node_modules\.kit_installed"
function Test-Mark([string]$Mark, [string]$Hash) {
    return (Test-Path -LiteralPath $Mark) -and ([System.IO.File]::ReadAllText($Mark).Trim() -eq $Hash)
}
# pip 가 없는 venv(만들다 끊김) — 매번 「인터넷 연결을 확인하세요」에서 멈췄다(33차 KIT-01). 그런 venv 는 --clear 로 다시 만든다.
function Test-VenvPip {
    if (-not (Test-Path $venvPython)) { return $false }
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $venvPython -m pip --version 2>$null | Out-Null } finally { $ErrorActionPreference = $previousPreference }
    return ($LASTEXITCODE -eq 0)
}
$backendReady = (Test-BackendImport) -and (Test-Mark $backendMark $backendManifest)
if ((Test-Path $venvPython) -and -not $backendReady) {
    if (Test-BackendImport) { Write-Info "백엔드 부품 목록이 바뀌었거나 설치 표시가 없어 한 번 더 설치합니다" }
    else { Write-Warn "지난번 백엔드 설치가 끝나지 않았습니다 — 다시 설치합니다" }
}
if (-not $backendReady) {
    if ((Test-Path $venvPython) -and -not (Test-VenvPip)) {
        Write-Warn "백엔드 가상환경에 pip 가 없습니다(만들다 끊긴 것) — 가상환경을 다시 만듭니다"
        & $python[0] @($python | Select-Object -Skip 1) -m venv --clear (Join-Path $Root "backend\.venv")
        if ($LASTEXITCODE -ne 0 -or -not (Test-VenvPip)) { Stop-Kit "가상환경을 다시 만들지 못했습니다 — 이 폴더의 backend\.venv 폴더를 지우고 다시 실행하세요" }
    }
    if (-not (Test-Path $venvPython)) {
        Write-Info "백엔드 가상환경을 만듭니다"
        & $python[0] @($python | Select-Object -Skip 1) -m venv (Join-Path $Root "backend\.venv")
        if ($LASTEXITCODE -ne 0) { Stop-Kit "가상환경을 만들지 못했습니다" }
    }
    Push-Location (Join-Path $Root "backend")
    try {
        & $venvPython -m pip install --disable-pip-version-check -q -e .
        if ($LASTEXITCODE -ne 0) { Stop-Kit "백엔드 패키지 설치(pip)에 실패했습니다 — 인터넷 연결을 확인하세요" }
        # 설치 기록은 남고 파일만 빠진 패키지는 pip 가 「이미 있음」으로 넘긴다 — 그대로 켜면 백엔드가 뜨지 않고 60초를
        # 기다리다 끝났다(32차 키트 시험). 한 번 더 불러 보고, 안 되면 모두 다시 설치한다.
        if (-not (Test-BackendImport)) {
            Write-Warn "설치가 깨져 있어 백엔드 패키지를 모두 다시 설치합니다"
            & $venvPython -m pip install --disable-pip-version-check -q --force-reinstall -e .
            if ($LASTEXITCODE -ne 0) { Stop-Kit "백엔드 패키지 설치(pip)에 실패했습니다 — 인터넷 연결을 확인하세요" }
        }
    } finally { Pop-Location }
    if (-not (Test-BackendImport)) { Stop-Kit "백엔드 설치를 마치지 못했습니다 — 이 폴더의 backend\.venv 폴더를 지우고 다시 실행하세요" }
    [System.IO.File]::WriteAllText($backendMark, $backendManifest, $Utf8)
    Write-Ok "백엔드 설치 끝"
} else {
    Write-Ok "백엔드 설치가 이미 되어 있습니다"
}
$frontendInstalled = Test-Path (Join-Path $Root "frontend\node_modules\.bin\next.cmd")
if (-not $frontendInstalled -or -not (Test-Mark $frontendMark $frontendManifest)) {
    if ($frontendInstalled) { Write-Info "프론트 부품 목록(package-lock.json)이 바뀌었거나 설치 표시가 없어 한 번 더 설치합니다" }
    elseif (Test-Path (Join-Path $Root "frontend\node_modules")) { Write-Warn "지난번 프론트 설치가 끝나지 않았습니다 — 다시 설치합니다" }
    Push-Location (Join-Path $Root "frontend")
    try {
        & npm install --no-audit --no-fund --loglevel=error
        if ($LASTEXITCODE -ne 0) { Stop-Kit "프론트 패키지 설치(npm)에 실패했습니다 — 인터넷 연결을 확인하세요" }
    } finally { Pop-Location }
    [System.IO.File]::WriteAllText($frontendMark, $frontendManifest, $Utf8)
    Write-Ok "프론트 설치 끝"
} else {
    Write-Ok "프론트 설치가 이미 되어 있습니다"
}

# ---------------------------------------------------------------------------
# 4) 처음 켤 때만 묻기
# ---------------------------------------------------------------------------
$registry = Join-Path $Root "data\private\organizations\registry.json"
if (-not (Test-Path $registry)) {
    Write-Step "처음 켜는 설정 — 우리 회사"
    function Ask([string]$Current, [string]$Prompt, [bool]$Required, [bool]$Secret = $false) {
        if ($Current -or $NonInteractive) { return $Current }
        while ($true) {
            if ($Secret) {
                $secure = Read-Host -Prompt $Prompt -AsSecureString
                $value = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
            } else {
                $value = Read-Host -Prompt $Prompt
            }
            if ($value -or -not $Required) { return $value.Trim() }
            Write-Warn "꼭 적어야 합니다"
        }
    }
    $CompanyName = Ask $CompanyName "회사 이름 (나중에 화면에서 못 고칩니다)" $true
    $Domains = Ask $Domains "사업영역 (쉼표로 구분 — 공고를 고르는 기준이 됩니다)" $true
    $Regions = Ask $Regions "활동 지역 (쉼표로 구분 · 비우면 지역 판정은 「확인 필요」)" $false
    $G2bKey = Ask $G2bKey "나라장터(공공데이터포털) 인증키 (비우면 저장된 예시 목록만)" $false $true
    $BizinfoKey = Ask $BizinfoKey "기업마당 인증키 (비우면 저장된 예시 목록만)" $false $true
    if (-not $NonInteractive) { Set-EnvLine "KIT_KEYS_ASKED" "1" $true | Out-Null }  # 다시 실행 때 또 묻지 않는다(33차 KIT-04)
    if (-not $NonInteractive -and -not $UseClaude -and -not $UseCodex) {
        $UseClaude = (Read-Host -Prompt "사업계획서를 Claude 로도 쓸까요? (y/N)") -match "^[yY]"
        $UseCodex = (Read-Host -Prompt "사업계획서를 Codex 로도 쓸까요? (y/N)") -match "^[yY]"
    }
    Set-EnvValue "KIT_PLAN_WRITER" (PlanWriterValue $UseClaude $UseCodex)
    if (-not $CompanyName -or -not $Domains) { Stop-Kit "회사 이름과 사업영역은 꼭 필요합니다 (-CompanyName · -Domains)" }
    Set-EnvIfEmpty "DEFAULT_ORGANIZATION_NAME" $CompanyName
    # PowerShell 5.1 은 빈 문자열 인자를 빼 버린다 — 「--이름=값」 한 덩어리로 넘긴다
    & $venvPython (Join-Path $Root "scripts\kit_first_run.py") "--name=$CompanyName" "--domains=$Domains" "--regions=$Regions"
    if ($LASTEXITCODE -ne 0) { Stop-Kit "회사를 만들지 못했습니다" }
} else {
    Write-Ok "회사 설정이 이미 있습니다 — 회사는 다시 묻지 않습니다"
    # 다시 실행 때 준 회사 매개변수는 쓰지 않는다 — 말없이 버리지 않고 알린다(32차 R31-27)
    $ignored = @()
    if ($CompanyName) { $ignored += "-CompanyName" }
    if ($Domains) { $ignored += "-Domains" }
    if ($Regions) { $ignored += "-Regions" }
    if ($ignored.Count -gt 0) {
        Write-Warn "회사 설정이 이미 있어 $($ignored -join ' · ') 는 쓰지 않았습니다 — 사업영역 · 활동 지역은 화면 「회사자료」에서 고치세요(회사 이름은 고칠 수 없습니다)"
    }
    # 인증키는 매 실행 넣을 수 있다(-G2bKey · -BizinfoKey) — 처음에 비워 둔 키를 다시 실행 때 주면 버려졌다(32차 R31-27).
    # 묻는 것은 **한 번만**(KIT_KEYS_ASKED) — 키가 빈 동안 실행할 때마다 두 번씩 물었다(33차 KIT-04). 나중에 넣는 법은 아래 안내 줄.
    if (-not $NonInteractive -and -not (Get-EnvValue "KIT_KEYS_ASKED")) {
        if (-not $G2bKey -and -not (Get-EnvValue "DATA_GO_KR_SERVICE_KEY")) {
            $secure = Read-Host -Prompt "나라장터(공공데이터포털) 인증키 (비우면 저장된 예시 목록만)" -AsSecureString
            $G2bKey = ([Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))).Trim()
        }
        if (-not $BizinfoKey -and -not (Get-EnvValue "BIZINFO_API_KEY")) {
            $secure = Read-Host -Prompt "기업마당 인증키 (비우면 저장된 예시 목록만)" -AsSecureString
            $BizinfoKey = ([Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))).Trim()
        }
        Set-EnvLine "KIT_KEYS_ASKED" "1" $true | Out-Null
    }
    # 처음 답한 Claude · Codex 사용을 다시 읽는다 — 두 번째 실행부터 「Claude로 쓰기」가 꺼지던 것(31차 R30-07).
    # 무엇을 골랐는지까지 기억한다 — Codex 만 고른 사람에게 매번 Claude 안내가 뜨던 것(31차 마지막 검토).
    if ($UseClaude -or $UseCodex) { Set-EnvValue "KIT_PLAN_WRITER" (PlanWriterValue $UseClaude $UseCodex) }
    else {
        $remembered = Get-EnvValue "KIT_PLAN_WRITER"
        $UseClaude = $remembered -eq "1" -or $remembered -eq "claude"
        $UseCodex = $remembered -eq "1" -or $remembered -eq "codex"
    }
}

# 처음 실행 · 다시 실행 모두 — 빈 칸이면 채우고, 다른 값이 이미 있으면 넣지 않고 알린다(Set-EnvLine · 31차 R30-16)
Set-EnvIfEmpty "DATA_GO_KR_SERVICE_KEY" $G2bKey
Set-EnvIfEmpty "BIZINFO_API_KEY" $BizinfoKey
if (-not (Get-EnvValue "DATA_GO_KR_SERVICE_KEY") -or -not (Get-EnvValue "BIZINFO_API_KEY")) {
    Write-Warn "나라장터 · 기업마당 키가 없어 저장된 예시 목록만 보입니다. 키를 받으면 .env 의 빈 칸에 넣고 다시 켜세요."
}
$planWriter = $UseClaude -or $UseCodex
# 서버는 Windows 에서 .exe 만 부른다(llm_client.claude_cli_path · codex_cli_path) — npm 으로 깐 .cmd · .ps1 판을 「있음」이라
# 하면 /plan 단추가 꺼진 채 이유를 모른다(32차 R31-26). .env 의 경로 → PATH 의 .exe → npm 판만 있음 → 없음 순으로 본다.
function Test-CliProgram([string]$Name, [string]$EnvKey, [string]$Label, [string]$Login) {
    $configured = Get-EnvValue $EnvKey
    if ($configured) {
        # .env 에 경로가 있으면 서버는 그 경로만 본다 — 틀린 경로인데 PATH 의 .exe 로 [OK] 를 내면 서버만 「찾지 못했습니다」였다(33차 KIT-05)
        if ((Test-Path -LiteralPath $configured) -and $configured.ToLower().EndsWith(".exe")) {
            Write-Ok "$Label 프로그램 경로가 .env($EnvKey)에 있습니다 — 로그인은 터미널에서: $Login"
        } else {
            Write-Warn "$Label 프로그램 경로가 .env($EnvKey)에 있는데 그 자리에 $Name.exe 가 없습니다 — 서버는 그 경로만 봅니다. 경로를 고치거나 그 줄을 비우세요"
        }
        return
    }
    if (Get-Command "$Name.exe" -ErrorAction SilentlyContinue) { Write-Ok "$Label 프로그램이 있습니다 — 로그인은 터미널에서: $Login"; return }
    if (Get-Command $Name -ErrorAction SilentlyContinue) {
        Write-Warn "$Label 은 npm 으로 설치한 판($Name.cmd)만 있습니다 — 서버는 $Name.exe 만 부릅니다. 네이티브 설치판을 깔거나, .env 의 $EnvKey= 뒤에 $Name.exe 의 전체 경로를 적으세요"
        return
    }
    Write-Warn "$Label 프로그램이 없습니다 — 설치하면 「$($Label)로 쓰기」가 켜집니다"
}
if ($UseClaude) { Test-CliProgram "claude" "CLAUDE_CLI_PATH" "Claude" "claude auth login" }
if ($UseCodex) { Test-CliProgram "codex" "CODEX_CLI_PATH" "Codex" "codex login" }

# ---------------------------------------------------------------------------
# 5) 시작 (실시간 모드)
# ---------------------------------------------------------------------------
if ($SkipStart) { Write-Ok "설치 끝 — 시작은 start_kit.bat"; exit 0 }
Write-Step "시작 (실시간 모드)"
# 이번에 .env 를 바꿨는데 서버가 이미 켜져 있으면 바뀐 키 · Claude/Codex 선택이 적용되지 않는다(33차 KIT-02)
if ($script:EnvChanged -and (Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue)) {
    Write-Warn "이번에 설정(.env)을 바꿨는데 서버가 이미 켜져 있어 바뀐 설정은 아직 적용되지 않습니다 — 서버 창 두 개를 닫거나 scripts\stop_dev.ps1 로 끈 뒤 start_kit.bat 으로 다시 켜세요"
}
$startArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $Root "scripts\start_dev.ps1"), "-FrontendPort", $FrontendPort, "-BackendPort", $BackendPort)
if ($NoBrowser) { $startArgs += "-NoBrowser" }
if ($planWriter) { $startArgs += "-PlanWriter" }
& powershell @startArgs
exit $LASTEXITCODE
