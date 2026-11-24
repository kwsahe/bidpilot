<#
.SYNOPSIS
  start_dev.ps1 / start_wireframe.ps1 이 띄운 개발 서버를 종료한다.

.DESCRIPTION
  아래 두 실행 기록에 남은 PID(서버 창)와 그 자식 프로세스(uvicorn, node 등)를
  먼저 정상 종료(CloseMainWindow)로 시도하고, 몇 초 안에 안 꺼지면 강제 종료한다.
    - %TEMP%\bidpilot_dev_pids.json        (start_dev.ps1  · 3110 + 8110)
    - %TEMP%\bidpilot_wireframe_pids.json  (start_wireframe.ps1 · 4120)
  둘 중 있는 것만 처리한다.
  스크립트가 직접 띄우지 않은 서버(started_by_script = false)는 건드리지 않고 알려만 준다.
  (예: 와이어프레임 런처가 기존 백엔드를 그대로 쓴 경우 그 백엔드는 종료하지 않는다.)

.PARAMETER DryRun
  실제로 종료하지 않고 무엇을 종료할 예정인지만 출력한다.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop_dev.ps1
#>
[CmdletBinding()]
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Write-Ok([string]$Message)   { Write-Host "  [OK]   $Message" -ForegroundColor Green }
function Write-Info([string]$Message) { Write-Host "  [..]   $Message" -ForegroundColor Gray }
function Write-Warn([string]$Message) { Write-Host "  [주의] $Message" -ForegroundColor Yellow }
function Write-Plan([string]$Message) { Write-Host "  [계획] $Message" -ForegroundColor Magenta }

# 우리가 띄운 프로세스만 고르는 판단(생성 시각) — start_dev 와 같은 파일(34차 R33-K1 · K2)
. (Join-Path $PSScriptRoot "process_safety.ps1")

$PidFiles = [ordered]@{
    "개발 서버 (3110 + 8110)" = Join-Path $env:TEMP "bidpilot_dev_pids.json"
    "와이어프레임 (4120)"     = Join-Path $env:TEMP "bidpilot_wireframe_pids.json"
}

Write-Host ""
Write-Host "BidPilot AI - 개발 서버 종료" -ForegroundColor White
if ($DryRun) { Write-Host "(DryRun 모드: 실제로 종료하지 않습니다)" -ForegroundColor Magenta }
Write-Host ""

$foundGroups = @()
foreach ($groupName in $PidFiles.Keys) {
    if (Test-Path $PidFiles[$groupName]) { $foundGroups += $groupName }
}

if ($foundGroups.Count -eq 0) {
    Write-Warn "실행 기록 파일이 하나도 없습니다."
    foreach ($groupName in $PidFiles.Keys) { Write-Info "찾은 위치: $($PidFiles[$groupName])" }
    Write-Info "start_dev.ps1 / start_wireframe.ps1 로 띄운 서버가 없거나 이미 종료했습니다."
    Write-Info "직접 띄운 서버라면 해당 PowerShell 창에서 Ctrl+C 를 누르거나 창을 닫아 주세요."
    exit 0
}

function Stop-ProcessTree([string]$Label, [int]$RootId) {
    $root = Get-Process -Id $RootId -ErrorAction SilentlyContinue
    if (-not $root) {
        Write-Info "$Label (PID $RootId) 은(는) 이미 종료되어 있습니다."
        return
    }
    # 자식은 **부모보다 늦게 생긴 것만**(깊은 자식이 먼저) — 죽은 부모 번호를 물려받은 남의 트리를 모으지 않는다(34차 R33-K1)
    $targets = @(Get-OwnedDescendants (Get-ProcessTable) $RootId | ForEach-Object { [pscustomobject]@{ Id = $_.Id; Name = $_.Name } })
    $targets += [pscustomobject]@{ Id = $RootId; Name = $root.ProcessName }

    foreach ($t in $targets) {
        if ($DryRun) { Write-Plan "$Label 종료 예정: $($t.Name) (PID $($t.Id))"; continue }
        $p = Get-Process -Id $t.Id -ErrorAction SilentlyContinue
        if (-not $p) { continue }
        # 1) 창이 있으면 정상 종료 요청
        $closed = $false
        try { $closed = $p.CloseMainWindow() } catch { $closed = $false }
        if ($closed) {
            if ($p.WaitForExit(3000)) {
                Write-Ok "$Label 정상 종료: $($t.Name) (PID $($t.Id))"
                continue
            }
        }
        # 2) 안 꺼지면 강제 종료
        try {
            Stop-Process -Id $t.Id -Force -ErrorAction Stop
            Write-Ok "$Label 강제 종료: $($t.Name) (PID $($t.Id))"
        } catch {
            if (Get-Process -Id $t.Id -ErrorAction SilentlyContinue) {
                Write-Warn "$Label 종료 실패: $($t.Name) (PID $($t.Id)) - $($_.Exception.Message)"
            } else {
                Write-Ok "$Label 종료됨 (자식 종료 후 스스로 종료): $($t.Name) (PID $($t.Id))"
            }
        }
    }
}

# 끄고 난 뒤에도 켜져 있는 서버 — 「종료 완료」 대신 사실대로 알린다(32차 R31-28)
$stillRunning = @()
$skippedOther = 0
$stoppedGroups = 0
function Test-PortListening([int]$Port) {
    for ($i = 0; $i -lt 6; $i++) {
        $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if (-not $listening) { return $false }
        Start-Sleep -Milliseconds 500
    }
    return $true
}

foreach ($groupName in $foundGroups) {
    $pidFile = $PidFiles[$groupName]

    Write-Host ""

    try {
        $record = Get-Content -LiteralPath $pidFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Write-Host "[$groupName]" -ForegroundColor White
        Write-Warn "실행 기록 파일을 읽지 못했습니다($pidFile): $($_.Exception.Message)"
        continue
    }
    # 머리 줄은 기록의 실제 포트로 — 키트(3120 · 8120)를 끌 때도 「(3110 + 8110)」으로 찍혔다(35차 §4-2)
    $heading = $groupName
    if ($record.frontend.port -and $record.backend.port) {
        $heading = $groupName -replace '\(.*\)', "($($record.frontend.port) + $($record.backend.port))"
    }
    Write-Host "[$heading]" -ForegroundColor White
    # 다른 폴더(저장소 · 키트)에서 켠 서버 기록이면 건드리지 않는다 — 키트의 stop_dev 가 저장소 서버를 껐다(33차 KIT-06)
    $myRepo = Split-Path -Parent $PSScriptRoot
    if ($record.repo -and ($record.repo -ne $myRepo)) {
        Write-Warn "이 실행 기록은 다른 폴더($($record.repo))에서 켠 서버입니다 — 이 폴더에서는 끄지 않습니다. 그 폴더의 scripts\stop_dev.ps1 을 쓰세요"
        $skippedOther += 1
        continue
    }

    foreach ($name in @("backend", "frontend")) {
        $entry = $record.$name
        if (-not $entry) { continue }
        $label = "백엔드"
        if ($name -eq "frontend") { $label = "프론트엔드" }
        $procId = 0
        if ($entry.pid) { $procId = [int]$entry.pid }

        if (-not $entry.started_by_script) {
            if ($procId -gt 0) { Write-Info "$label (포트 $($entry.port), PID $procId) 은(는) 이 스크립트가 띄운 것이 아니므로 건드리지 않습니다." }
        } elseif ($procId -gt 0 -and -not (Test-RecordedRow (Get-ProcessTable) $procId $record.started_at)) {
            # 창을 닫아 끈 뒤 같은 번호를 다른 프로그램이 쓰면 남의 프로그램을 끌 뻔했다 — 생성 시각이 기록 시각 뒤이거나 못 읽으면 건드리지 않는다(34차 R33-K1 · K2)
            if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
                Write-Warn "$label (PID $procId) 은(는) 기록한 뒤에 생긴 프로세스이거나 시작 시각을 읽을 수 없어 다른 프로그램일 수 있습니다 — 건드리지 않습니다."
            } else {
                Write-Info "$label (PID $procId) 은(는) 이미 종료되어 있습니다."
            }
        } elseif ($procId -gt 0) {
            Stop-ProcessTree $label $procId
            $stoppedGroups += 1
        }
        if (-not $DryRun -and $entry.port -and (Test-PortListening ([int]$entry.port))) { $stillRunning += "$label 포트 $($entry.port)" }
    }

    if ($DryRun) {
        Write-Plan "실행 기록 파일 삭제 예정: $pidFile"
    } else {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        Write-Ok "실행 기록 파일 삭제: $pidFile"
    }
}

Write-Host ""
if ($skippedOther -gt 0 -and $stoppedGroups -eq 0 -and $stillRunning.Count -eq 0) {
    Write-Host "다른 폴더의 실행 기록이라 아무것도 끄지 않았습니다." -ForegroundColor Cyan
} elseif ($skippedOther -gt 0 -and $stillRunning.Count -eq 0) {
    # 끈 그룹이 있으면 그 사실을 먼저 — 끈 뒤에도 「아무것도 끄지 않았습니다」가 나왔다(34차 R33-K3)
    Write-Host "종료 완료 · 다른 폴더의 실행 기록 $skippedOther 개는 건드리지 않았습니다." -ForegroundColor Cyan
} elseif ($stillRunning.Count -gt 0) {
    Write-Warn "아직 켜져 있는 서버가 있습니다: $($stillRunning -join ' · ') — 그 서버 창을 닫거나 Ctrl+C 로 끄세요."
} else {
    Write-Host "종료 완료. 다시 띄우려면 scripts\start_dev.bat (3110) 또는 scripts\start_wireframe.bat (4120) 을 더블클릭하세요." -ForegroundColor Cyan
}
Write-Host ""
