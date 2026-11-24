<#
.SYNOPSIS
  키트용 가상 예시 제안요청서 PDF — make_kit_sample_rfp.py 가 만든 DOCX 를 Word 로 PDF 저장한다 (31차 R30-14).
.DESCRIPTION
  원본 PDF 도 같은 DOCX 를 Microsoft Word 로 저장해 만들었다(문서 속성 Producer). 같은 Word 로 저장해야 쪽 나눔이 같아
  요구사항의 쪽 번호가 맞는다. Word 가 없는 PC 에서는 멈춘다 — 만든 PDF 는 scripts/kit/assets/ 에 커밋해 둔다.
  Word 가 숨은 대화상자에서 멈추지 않게 알림을 끄고(DisplayAlerts 0) · 매크로를 막고 · 120초 안에 끝나지 않으면 끝낸다.
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\kit\make_kit_sample_rfp.ps1
#>
$ErrorActionPreference = "Stop"
$Assets = Join-Path $PSScriptRoot "assets"
$Docx = Join-Path $Assets "synthetic_ai_training_rfp.docx"
$Pdf = Join-Path $Assets "synthetic_ai_training_rfp.pdf"
if (-not (Test-Path $Docx)) { throw "먼저 make_kit_sample_rfp.py 로 DOCX 를 만드세요: $Docx" }
$before = @(Get-Process WINWORD -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
$job = Start-Job -ArgumentList $Docx, $Pdf -ScriptBlock {
    param($Docx, $Pdf)
    $word = New-Object -ComObject Word.Application
    try {
        $word.Visible = $false
        $word.DisplayAlerts = 0          # wdAlertsNone
        $word.AutomationSecurity = 3     # msoAutomationSecurityForceDisable
        $doc = $word.Documents.Open($Docx)
        try { $doc.ExportAsFixedFormat($Pdf, 17) } finally { $doc.Close($false) }  # 17 = wdExportFormatPDF
    } finally { $word.Quit() }
}
if (-not (Wait-Job $job -Timeout 120)) {
    Stop-Job $job
    # 이 스크립트가 띄운 Word(COM 자동화 — 명령줄에 /Automation)만 끈다. 그새 사용자가 연 Word 는 건드리지 않는다(34차 R33-K4)
    Get-CimInstance Win32_Process -Filter "Name = 'WINWORD.EXE'" -ErrorAction SilentlyContinue |
        Where-Object { $before -notcontains [int]$_.ProcessId -and ([string]$_.CommandLine) -match "/Automation" } |
        ForEach-Object { Stop-Process -Id ([int]$_.ProcessId) -Force -ErrorAction SilentlyContinue }
    throw "Word 가 120초 안에 끝나지 않았습니다 — Word 를 한 번 직접 열어 첫 실행 창을 닫은 뒤 다시 하세요"
}
Receive-Job $job
Write-Host "PDF: $Pdf"
