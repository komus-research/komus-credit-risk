param(
    [switch]$BackendWorker,
    [switch]$FrontendWorker,
    [string]$LauncherMarker
)

$ErrorActionPreference = 'Stop'

# Worker modes run in their own visible console. The unique marker is present
# in this PowerShell process command line and is checked before any tree kill.
if ($BackendWorker) {
    $ErrorActionPreference = 'Continue'
    $Host.UI.RawUI.WindowTitle = 'AXION — Backend'
    Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
    $env:UV_CACHE_DIR = Join-Path $PSScriptRoot '..\.axion-run\uv-cache'
    New-Item -ItemType Directory -Path $env:UV_CACHE_DIR -Force | Out-Null
    & uv run --no-sync uvicorn app.api.main:app --host 127.0.0.1 --port 8000 2>&1 |
        Tee-Object -FilePath ([System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\.axion-run\backend.log')))
    exit $LASTEXITCODE
}
if ($FrontendWorker) {
    $ErrorActionPreference = 'Continue'
    $Host.UI.RawUI.WindowTitle = 'AXION — Frontend'
    Set-Location -LiteralPath (Join-Path $PSScriptRoot '..\frontend')
    & npm run dev -- --host 127.0.0.1 2>&1 |
        Tee-Object -FilePath ([System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\.axion-run\frontend.log')))
    exit $LASTEXITCODE
}

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$RunDirectory = Join-Path $ProjectRoot '.axion-run'
$StatePath = Join-Path $RunDirectory 'state.json'
$BackendLog = Join-Path $RunDirectory 'backend.log'
$FrontendLog = Join-Path $RunDirectory 'frontend.log'
$CanonicalUrl = 'http://127.0.0.1:5173/#/home'
$BackendHealthUrl = 'http://127.0.0.1:8000/api/v1/health'
$FrontendReadyUrl = 'http://127.0.0.1:5173/'

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
        # Re-read identity immediately before tree termination to avoid PID reuse.
        if (Test-OwnedRoot $Entry $InstanceId) {
            & taskkill.exe /PID ([int]$Entry.pid) /T /F | Out-Null
        }
    }
}

function Test-HttpReady([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 2 -UseBasicParsing
        return ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 400)
    } catch { return $false }
}

function Test-PortFree([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        $connected = $task.AsyncWaitHandle.WaitOne(400)
        if ($connected) {
            try { $client.EndConnect($task); return $false } catch { return $true }
        }
        return $true
    } finally { $client.Close() }
}

function Remove-ActiveState {
    if (Test-Path -LiteralPath $StatePath) { Remove-Item -LiteralPath $StatePath -Force }
}

function Start-Worker([string]$Mode, [string]$InstanceId) {
    $marker = "AXION_LAUNCHER_INSTANCE_ID=$InstanceId"
    $scriptPath = Join-Path $PSScriptRoot 'start_axion.ps1'
    $args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $scriptPath), "-$Mode", '-LauncherMarker', $marker)
    Start-Process -FilePath 'powershell.exe' -ArgumentList $args -WorkingDirectory $ProjectRoot -WindowStyle Normal -PassThru
}

function Wait-ForReady([string]$Url, $Process, $Entry, [string]$InstanceId, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ([int]$Process.Id -ne [int]$Entry.pid) { return $false }
        $Process.Refresh()
        if ($Process.HasExited) { return $false }
        if (-not (Test-OwnedRoot $Entry $InstanceId)) { return $false }
        if (Test-HttpReady $Url) {
            $Process.Refresh()
            if (-not $Process.HasExited -and (Test-OwnedRoot $Entry $InstanceId)) { return $true }
            return $false
        }
        Start-Sleep -Milliseconds 500
    }
    if ([int]$Process.Id -ne [int]$Entry.pid) { return $false }
    $Process.Refresh()
    if ($Process.HasExited -or -not (Test-OwnedRoot $Entry $InstanceId)) { return $false }
    if (-not (Test-HttpReady $Url)) { return $false }
    $Process.Refresh()
    return (-not $Process.HasExited -and (Test-OwnedRoot $Entry $InstanceId))
}

$normalizedRoot = $ProjectRoot.TrimEnd('\').ToUpperInvariant()
$rootBytes = [System.Text.Encoding]::UTF8.GetBytes($normalizedRoot)
$sha256 = [System.Security.Cryptography.SHA256]::Create()
try { $rootHash = [System.BitConverter]::ToString($sha256.ComputeHash($rootBytes)).Replace('-', '') } finally { $sha256.Dispose() }
$mutexName = "Local\AXION_LAUNCHER_$($rootHash.Substring(0, 20))"
$startupMutex = [System.Threading.Mutex]::new($false, $mutexName)
$mutexAcquired = $false

try {
    try {
        $mutexAcquired = $startupMutex.WaitOne([TimeSpan]::FromSeconds(120))
    } catch [System.Threading.AbandonedMutexException] {
        $mutexAcquired = $true
    }
    if (-not $mutexAcquired) {
        Write-Error 'Не удалось дождаться завершения другого запуска AXION.'
        exit 1
    }

    # Process metadata is required before touching state or starting service roots.
    try {
        $selfRecord = Get-ProcessRecord $PID
        if (-not $selfRecord -or -not (Get-CreationIdentity $selfRecord)) { throw 'metadata unavailable' }
    } catch {
        Write-Error 'Недоступны метаданные процессов Windows. Запуск AXION отменён до старта сервисов.'
        exit 1
    }

    New-Item -ItemType Directory -Path $RunDirectory -Force | Out-Null

# Reconcile old ownership state. Only roots with matching PID, creation time,
# and the recorded instance marker are eligible for tree termination.
    if (Test-Path -LiteralPath $StatePath) {
    try {
        $old = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        $backendEntry = [pscustomobject]@{ pid = $old.backend_root_pid; created_at = $old.backend_process_created_at }
        $frontendEntry = [pscustomobject]@{ pid = $old.frontend_root_pid; created_at = $old.frontend_process_created_at }
        $backendOwned = Test-OwnedRoot $backendEntry ([string]$old.launcher_instance_id)
        $frontendOwned = Test-OwnedRoot $frontendEntry ([string]$old.launcher_instance_id)
        if ($backendOwned -and $frontendOwned -and (Test-HttpReady $BackendHealthUrl) -and (Test-HttpReady $FrontendReadyUrl)) {
            Write-Host 'AXION уже запущен. Открываю приложение.'
            try { Start-Process $CanonicalUrl -ErrorAction Stop } catch { Write-Warning "Не удалось автоматически открыть браузер: $($_.Exception.Message)" }
            exit 0
        }
        Stop-OwnedRoot $backendEntry ([string]$old.launcher_instance_id)
        Stop-OwnedRoot $frontendEntry ([string]$old.launcher_instance_id)
    } catch {
        Write-Host 'Существующий state.json не удалось подтвердить; процессы не завершались без проверки identity.'
    }
    Remove-ActiveState
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "Не найден uv.`nУстановите uv и повторите запуск."
    exit 1
    }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Error "Не найден Node.js / npm.`nУстановите Node.js и повторите запуск."
    exit 1
    }
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'frontend\node_modules\vite\bin\vite.js'))) {
    Write-Error "Зависимости frontend не установлены.`nВыполните npm install --prefix frontend."
    exit 1
    }

    $env:UV_CACHE_DIR = Join-Path $RunDirectory 'uv-cache'
    $previousErrorActionPreference = $ErrorActionPreference
    $previousLocation = Get-Location
    try {
        $ErrorActionPreference = 'Continue'
        Set-Location -LiteralPath $ProjectRoot
        $backendPreflightOutput = & uv run --no-sync python -c "import uvicorn" 2>&1
        $backendPreflightExitCode = $LASTEXITCODE
    } finally {
        Set-Location -LiteralPath $previousLocation
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($backendPreflightExitCode -ne 0) {
        Write-Error "Зависимости backend не установлены.`nВыполните uv sync и повторите запуск."
        exit 1
    }

    if (-not (Test-PortFree 8000)) {
    Write-Error 'Не удалось запустить AXION: порт 8000 уже занят другим процессом.'
    exit 1
    }
    if (-not (Test-PortFree 5173)) {
    Write-Error 'Не удалось запустить AXION: порт 5173 уже занят другим процессом.'
    exit 1
    }

Set-Content -LiteralPath $BackendLog -Value '' -Encoding UTF8
Set-Content -LiteralPath $FrontendLog -Value '' -Encoding UTF8
$instanceId = [guid]::NewGuid().ToString('D')
$backend = $null
$frontend = $null
    try {
    $backend = Start-Worker 'BackendWorker' $instanceId
    $backendRecord = $null
    for ($i = 0; $i -lt 20 -and -not $backendRecord; $i++) {
        Start-Sleep -Milliseconds 100
        $backendRecord = Get-ProcessRecord $backend.Id
    }
    $backendIdentity = Get-CreationIdentity $backendRecord
    $backendEntry = [pscustomobject]@{ pid = $backend.Id; created_at = $backendIdentity }
    if (-not (Wait-ForReady $BackendHealthUrl $backend $backendEntry $instanceId 45)) {
        Stop-OwnedRoot $backendEntry $instanceId
        Remove-ActiveState
        Write-Error 'Backend AXION не запустился. Подробности: .axion-run\backend.log'
        exit 1
    }

    $frontend = Start-Worker 'FrontendWorker' $instanceId
    $frontendRecord = $null
    for ($i = 0; $i -lt 20 -and -not $frontendRecord; $i++) {
        Start-Sleep -Milliseconds 100
        $frontendRecord = Get-ProcessRecord $frontend.Id
    }
    $frontendIdentity = Get-CreationIdentity $frontendRecord
    $frontendEntry = [pscustomobject]@{ pid = $frontend.Id; created_at = $frontendIdentity }
    if (-not (Wait-ForReady $FrontendReadyUrl $frontend $frontendEntry $instanceId 45)) {
        Stop-OwnedRoot $frontendEntry $instanceId
        Stop-OwnedRoot $backendEntry $instanceId
        Remove-ActiveState
        Write-Error 'Frontend AXION не запустился. Подробности: .axion-run\frontend.log'
        exit 1
    }

    $state = [ordered]@{
        launcher_instance_id = $instanceId
        backend_root_pid = $backend.Id
        backend_process_created_at = $backendIdentity
        frontend_root_pid = $frontend.Id
        frontend_process_created_at = $frontendIdentity
        backend_port = 8000
        frontend_port = 5173
        started_at = [datetime]::UtcNow.ToString('o')
    }
    $temporaryState = "$StatePath.tmp"
    $state | ConvertTo-Json | Set-Content -LiteralPath $temporaryState -Encoding UTF8
    Move-Item -LiteralPath $temporaryState -Destination $StatePath -Force
    try { Start-Process $CanonicalUrl -ErrorAction Stop } catch { Write-Warning "Не удалось автоматически открыть браузер: $($_.Exception.Message)" }
    Write-Host 'AXION запущен.'
    exit 0
    } catch {
    if ($frontend) {
        $record = Get-ProcessRecord $frontend.Id
        Stop-OwnedRoot ([pscustomobject]@{ pid = $frontend.Id; created_at = (Get-CreationIdentity $record) }) $instanceId
    }
    if ($backend) {
        $record = Get-ProcessRecord $backend.Id
        Stop-OwnedRoot ([pscustomobject]@{ pid = $backend.Id; created_at = (Get-CreationIdentity $record) }) $instanceId
    }
    Remove-ActiveState
    Write-Error $_
    exit 1
    }
} finally {
    if ($mutexAcquired) { $startupMutex.ReleaseMutex() }
    $startupMutex.Dispose()
}
