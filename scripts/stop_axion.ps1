$ErrorActionPreference = 'Stop'
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$RunDirectory = Join-Path $ProjectRoot '.axion-run'
$StatePath = Join-Path $RunDirectory 'state.json'

function Get-ProcessRecord([int]$ProcessId) {
    Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
}

function Get-CreationIdentity($ProcessRecord) {
    if (-not $ProcessRecord -or -not $ProcessRecord.CreationDate) { return $null }
    $created = if ($ProcessRecord.CreationDate -is [datetime]) { $ProcessRecord.CreationDate } else { [System.Management.ManagementDateTimeConverter]::ToDateTime([string]$ProcessRecord.CreationDate) }
    $created.ToUniversalTime().ToString('o')
}

function Test-OwnedRoot($Entry, [string]$InstanceId) {
    if (-not $Entry -or -not $Entry.pid -or -not $Entry.created_at -or -not $InstanceId) { return $false }
    $record = Get-ProcessRecord ([int]$Entry.pid)
    if (-not $record) { return $false }
    $created = Get-CreationIdentity $record
    $expected = ([datetime]::Parse([string]$Entry.created_at)).ToUniversalTime().ToString('o')
    return ($created -eq $expected -and $record.CommandLine -and $record.CommandLine.Contains("AXION_LAUNCHER_INSTANCE_ID=$InstanceId"))
}

function Stop-OwnedRoot($Entry, [string]$InstanceId) {
    if (Test-OwnedRoot $Entry $InstanceId) {
        # Confirm identity again immediately before terminating only this tree.
        if (Test-OwnedRoot $Entry $InstanceId) {
            & taskkill.exe /PID ([int]$Entry.pid) /T /F | Out-Null
        }
    }
}

if (Test-Path -LiteralPath $StatePath) {
    try {
        $state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        $backend = [pscustomobject]@{ pid = $state.backend_root_pid; created_at = $state.backend_process_created_at }
        $frontend = [pscustomobject]@{ pid = $state.frontend_root_pid; created_at = $state.frontend_process_created_at }
        Stop-OwnedRoot $backend ([string]$state.launcher_instance_id)
        Stop-OwnedRoot $frontend ([string]$state.launcher_instance_id)
    } catch {
        Write-Host 'State не удалось прочитать; неподтверждённые процессы не завершались.'
    }
    Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
}

Write-Host 'AXION остановлен.'
