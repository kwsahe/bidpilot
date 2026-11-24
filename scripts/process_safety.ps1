<#
.SYNOPSIS
  우리가 띄운 서버 프로세스만 끄기 위한 판단 (34차 R33-K1 · K2) — start_dev.ps1 · stop_dev.ps1 이 점 소싱으로 함께 쓴다.
.DESCRIPTION
  Windows 는 PID 를 다시 쓰고, 부모가 죽어도 자식의 부모 번호(ParentProcessId)를 고치지 않는다. 그래서
  - 「살아 있는가」만 보면 창을 닫아 끈 뒤 같은 번호를 쓰게 된 남의 프로그램을 우리 서버로 안다.
  - 「부모 번호가 같은가」만 보면 죽은 부모 번호를 물려받은 남의 프로세스 트리(다른 프로젝트 3000 · 8000 서버 등)까지 자식으로 모은다.
  판단은 CIM 생성 시각(CreationDate)으로 한다 — 기록 시각 전에 생긴 창 · 부모보다 늦게 생긴 자식만 우리 것. 시각을 못 읽으면 남의 것.
  시험: backend/tests/test_process_safety.py (가짜 프로세스 표).
#>

function ConvertTo-ProcessRow($Cim) {
    [pscustomobject]@{ Id = [int]$Cim.ProcessId; ParentId = [int]$Cim.ParentProcessId; Name = [string]$Cim.Name; Created = $Cim.CreationDate }
}

function Get-ProcessTable {
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object { ConvertTo-ProcessRow $_ })
}

function Get-RowCreated($Row) {
    if (-not $Row -or -not $Row.Created) { return $null }
    try { return [datetime]$Row.Created } catch { return $null }
}

# 기록의 PID 가 그때 띄운 창인가 — 생성 시각이 기록 시각(+5초) 이전일 때만. 기록 시각 · 생성 시각 중 하나라도 없으면 남의 것.
function Test-RecordedRow($Table, [int]$ProcessId, [string]$StartedAt) {
    $row = @($Table | Where-Object { $_.Id -eq $ProcessId }) | Select-Object -First 1
    if (-not $row -or -not $StartedAt) { return $false }
    $created = Get-RowCreated $row
    if ($null -eq $created) { return $false }
    try { $recorded = [datetime]$StartedAt } catch { return $false }
    return ($created -le $recorded.AddSeconds(5))
}

# 뿌리 아래 자식 — **부모보다 늦게 생긴** 프로세스만(깊은 자식이 먼저). 생성 시각을 못 읽는 자식은 모으지 않는다.
function Get-OwnedDescendants($Table, [int]$RootId, [int]$Depth = 0) {
    if ($Depth -gt 16) { return @() }
    $root = @($Table | Where-Object { $_.Id -eq $RootId }) | Select-Object -First 1
    $rootCreated = Get-RowCreated $root
    if ($null -eq $rootCreated) { return @() }
    $out = @()
    foreach ($child in @($Table | Where-Object { $_.ParentId -eq $RootId -and $_.Id -ne $RootId })) {
        $childCreated = Get-RowCreated $child
        if ($null -eq $childCreated -or $childCreated -lt $rootCreated) { continue }
        $out += @(Get-OwnedDescendants $Table $child.Id ($Depth + 1))
        $out += $child
    }
    return $out
}
