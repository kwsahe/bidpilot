<#
.SYNOPSIS
  BidPilot AI 범용 설치 키트를 묶는다 (30차 §3-G).
.DESCRIPTION
  1) git archive (커밋된 것만 · 허용 목록) → 임시 폴더에 푼다. 추적하지 않는 파일(data/private · .env 등)은 저절로 빠진다.
  2) 키트 파일(start_kit.bat · kit_setup.ps1 · KIT_README.md · kit_first_run.py)과 변환기 · 키트용 가상 예시 제안요청서도
     **같은 -Ref 에서** 꺼낸다(31차 R30-17 — 예전에는 작업 트리 파일이었다). 처음 하는 회사 가이드(frontend/content/first_time_guide.md)는 화면(/guide)이 읽고 GUIDE.md 로도 복사.
  3) scripts/kit/kit_transform.py — 바꿔 넣기(스냅샷 {} · 고정 공고 빈 목록 · 합성 자료만 · 기본 회사 org-main · 이름 중립)
     + 「샘플에듀 자료 없음」 검사 다섯. 하나라도 실패하면 압축 파일을 만들지 않는다.
  4) 저장소 밖에 zip 을 만든다(기본 %USERPROFILE%\BidPilotKit\).
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_kit.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_kit.ps1 -OutDir D:\kits -KeepFolder
#>
[CmdletBinding()]
param(
    [string]$OutDir = (Join-Path $env:USERPROFILE "BidPilotKit"),
    [string]$Ref = "HEAD",
    [switch]$KeepFolder
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$Repo = Split-Path $PSScriptRoot -Parent

function Write-Step([string]$Message) { Write-Host ""; Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message)   { Write-Host "  [OK]   $Message" -ForegroundColor Green }

$Allow = @(
    "backend/app", "backend/pyproject.toml",
    "frontend/package.json", "frontend/package-lock.json", "frontend/next.config.ts", "frontend/tsconfig.json",
    "frontend/postcss.config.mjs", "frontend/eslint.config.mjs", "frontend/src", "frontend/public",
    "data/public/sample_procurements", "data/public/sample_bizinfo", "data/public/sample_rfp",
    "data/public/conditions", "data/public/actions", "data/synthetic_company",
    ".env.example",
    "scripts/start_dev.ps1", "scripts/stop_dev.ps1", "scripts/process_safety.ps1", "scripts/collect_daily.py", "scripts/refetch_bizinfo_cache.py",
    "scripts/kit", "frontend/content"
)

$stamp = Get-Date -Format "yyyyMMdd"
$work = Join-Path $env:TEMP ("bidpilot-kit-" + $stamp + "-" + (Get-Random))
$kit = Join-Path $work "BidPilotKit"
New-Item -ItemType Directory -Force -Path $kit | Out-Null

Write-Step "묶을 파일 ($Ref · 허용 목록 $($Allow.Count)개)"
$tar = Join-Path $work "kit.tar"
& git -C $Repo archive --format=tar -o $tar $Ref -- @Allow
if ($LASTEXITCODE -ne 0) { throw "git archive 실패" }
& tar -xf $tar -C $kit
if ($LASTEXITCODE -ne 0) { throw "tar 풀기 실패" }
Remove-Item $tar -Force
# 키트 파일 · 변환기 · 가이드 · 키트용 가상 예시 제안요청서 — 모두 $Ref 에서 꺼낸 것(R30-17)
$kitSrc = Join-Path $kit "scripts\kit"
Move-Item (Join-Path $kitSrc "start_kit.bat"), (Join-Path $kitSrc "kit_setup.ps1"), (Join-Path $kitSrc "KIT_README.md") -Destination $kit
Move-Item (Join-Path $kitSrc "kit_first_run.py") -Destination (Join-Path $kit "scripts")
Move-Item (Join-Path $kitSrc "kit_transform.py") -Destination (Join-Path $work "kit_transform.py")
Copy-Item (Join-Path $kitSrc "assets\synthetic_ai_training_rfp.docx"), (Join-Path $kitSrc "assets\synthetic_ai_training_rfp.pdf") -Destination (Join-Path $kit "data\public\sample_rfp") -Force
# 가이드 원본은 frontend/content 한 곳(32차 §3-A-1) — 화면(/guide)이 읽고, 키트 맨 위 GUIDE.md 로도 복사한다
Copy-Item (Join-Path $kit "frontend\content\first_time_guide.md") -Destination (Join-Path $kit "GUIDE.md")
Remove-Item $kitSrc -Recurse -Force
Write-Ok "풀었습니다: $kit"

Write-Step "바꿔 넣기 · 「샘플에듀 자료 없음」 검사 다섯"
$py = Join-Path $Repo "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py (Join-Path $work "kit_transform.py") $kit --repo $Repo
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [멈춤] 검사가 실패해 압축 파일을 만들지 않습니다. 폴더: $kit" -ForegroundColor Red
    exit 1
}

Write-Step "압축 ($OutDir)"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$zip = Join-Path $OutDir ("BidPilotKit_" + $stamp + ".zip")
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $kit -DestinationPath $zip
$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Ok "키트: $zip ($size MB)"
if (-not $KeepFolder) { Remove-Item $work -Recurse -Force }
exit 0
