[CmdletBinding()]
param(
    [string]$RuntimeDir,
    [string]$HfCacheDir,
    [string]$PythonExe,
    [switch]$NonInteractive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$RequirementsPath = Join-Path $RepoRoot 'requirements-tabfm-v1.txt'
$KernelName = 'komus-stage13-tabfm-v1'
$KernelDisplayName = 'KOMUS Stage 13 TabFM (Python 3.11)'
$ExpectedDatasetSha = 'fc742be66d238c529daba52ccc755f774f836b7d052ed062cdf0b345080e7930'
$ExpectedTabfmCommit = 'd8678b6895f1428a468d4cc299c1ff4cf704e726'
$ExpectedCheckpointSha = '928cb350becdc77cdb7a9e8c36deda88917bfd14a3091894a2dc516db58a2085'
$ExpectedRevision = '77cb9cc1b4fd3a9c77fbb9552c218200bb4dab83'

$RepoDriveRoot = [System.IO.Path]::GetPathRoot($RepoRoot)
$DefaultRuntimeDir = Join-Path $RepoDriveRoot 'KOMUS\stage13-tabfm-v1'
$FallbackHfHome = Join-Path $RepoDriveRoot 'huggingface-cache'

$Summary = [ordered]@{
    'Runtime directory' = 'STOP'
    'HF cache directory' = 'STOP'
    'Python 3.11'        = 'STOP'
    'venv'               = 'STOP'
    'dependencies'       = 'STOP'
    'TabFM commit'       = 'STOP'
    'Jupyter kernel'     = 'STOP'
    'dataset SHA'        = 'STOP'
    'required artifacts' = 'STOP'
    'output guard'       = 'STOP'
    'memory/commit'      = 'WARN'
    'HF checkpoint'      = 'WARN'
}
$SummaryDetails = [ordered]@{}
$HasStop = $false

function Write-Stage([int]$Number, [string]$Text) {
    Write-Host "`n[$Number/8] $Text"
}

function Set-Check([string]$Name, [ValidateSet('PASS', 'WARN', 'STOP')][string]$Status, [string]$Message) {
    $script:Summary[$Name] = $Status
    $script:SummaryDetails[$Name] = $Message
    if ($Status -eq 'STOP') {
        $script:HasStop = $true
    }
    Write-Host "${Status}: $Message"
}

function Test-Python311([string]$Executable, [string[]]$Prefix = @(), [Parameter(Mandatory)][ref]$FailureReason) {
    $FailureReason.Value = $null
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        $FailureReason.Value = 'path отсутствует'
        return $null
    }
    try {
        $versionProbe = @'
import sys
print(sys.executable)
print(*sys.version_info[:3], sep='.')
'@
        $details = @(& $Executable @Prefix -c $versionProbe 2>$null)
        if ($LASTEXITCODE -ne 0) {
            $FailureReason.Value = 'executable не запускается'
            return $null
        }
        if ($details.Count -lt 2) {
            $FailureReason.Value = 'version output не получен'
            return $null
        }
        $version = ([string]$details[-1]).Trim()
        if ($version -notmatch '^3\.11\.\d+$') {
            $FailureReason.Value = "версия $version, требуется Python 3.11.x"
            return $null
        }
        return [pscustomobject]@{
            Executable = ([string]$details[0]).Trim()
            Launcher = $Executable
            Prefix = $Prefix
            Version = $version
        }
    } catch {
        $FailureReason.Value = "executable не запускается: $($_.Exception.Message)"
        return $null
    }
}

function Find-Python311([ref]$Diagnostics) {
    $discoveryDiagnostics = [System.Collections.Generic.List[string]]::new()
    if ($null -ne $Diagnostics) { $Diagnostics.Value = $discoveryDiagnostics }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        $pyExecutable = $py.Path
        if ([string]::IsNullOrWhiteSpace($pyExecutable)) { $pyExecutable = $py.Source }
        $reason = $null
        $found = Test-Python311 -Executable $pyExecutable -Prefix @('-3.11') -FailureReason ([ref]$reason)
        if ($null -ne $found) { return $found }
        $discoveryDiagnostics.Add("py -3.11: $reason")
    } else {
        $discoveryDiagnostics.Add('py launcher: не найден')
    }

    $knownPaths = @('C:\Program Files\Python311\python.exe', 'C:\Python311\python.exe')
    if ($env:LOCALAPPDATA) {
        $knownPaths += Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
    }
    if ($env:ProgramFiles) {
        $knownPaths += Join-Path $env:ProgramFiles 'Python311\python.exe'
    }
    $knownPaths = $knownPaths | Select-Object -Unique
    foreach ($path in $knownPaths) {
        $reason = $null
        $found = Test-Python311 -Executable $path -FailureReason ([ref]$reason)
        if ($null -ne $found) { return $found }
        $discoveryDiagnostics.Add("${path}: $reason")
    }

    $pythonCommands = @(Get-Command python -All -ErrorAction SilentlyContinue)
    if ($pythonCommands.Count -eq 0) {
        $discoveryDiagnostics.Add('Get-Command python -All: кандидаты не найдены')
    }
    foreach ($python in $pythonCommands) {
        $pythonExecutable = $python.Path
        if ([string]::IsNullOrWhiteSpace($pythonExecutable)) { $pythonExecutable = $python.Source }
        if ([string]::IsNullOrWhiteSpace($pythonExecutable)) {
            $discoveryDiagnostics.Add('Get-Command python -All: путь кандидата не определён')
            continue
        }
        $reason = $null
        $found = Test-Python311 -Executable $pythonExecutable -FailureReason ([ref]$reason)
        if ($null -ne $found) { return $found }
        $discoveryDiagnostics.Add("${pythonExecutable}: $reason")
    }
    return $null
}

function Resolve-DirectoryPath([string]$PathValue) {
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        throw 'Путь не может быть пустым.'
    }
    $expandedPath = [Environment]::ExpandEnvironmentVariables($PathValue.Trim())
    $fullPath = [System.IO.Path]::GetFullPath($expandedPath)
    $root = [System.IO.Path]::GetPathRoot($fullPath)
    if ($fullPath.Length -gt $root.Length) {
        $fullPath = $fullPath.TrimEnd('\')
    }
    return $fullPath
}

function Select-DirectoryPath([string]$Label, [string]$DefaultPath, [string]$ExplicitPath) {
    $candidate = $ExplicitPath
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        Write-Host "`nРекомендуемая директория ${Label}:"
        Write-Host $DefaultPath
        if ($NonInteractive) {
            Write-Host 'NonInteractive: используется рекомендуемый путь.'
            $candidate = $DefaultPath
        } else {
            $candidate = Read-Host 'Нажмите Enter, чтобы использовать её, или введите другой путь'
            if ([string]::IsNullOrWhiteSpace($candidate)) {
                $candidate = $DefaultPath
            }
        }
    }
    return Resolve-DirectoryPath $candidate
}

function Select-HfCachePaths([string]$ExplicitPath) {
    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        $selectedHome = Resolve-DirectoryPath $ExplicitPath
        return [pscustomobject]@{
            Home = $selectedHome
            HubCache = Join-Path $selectedHome 'hub'
            XetCache = Join-Path $selectedHome 'xet'
        }
    }

    $selectedHome = if ($env:HF_HOME) {
        Resolve-DirectoryPath $env:HF_HOME
    } else {
        Resolve-DirectoryPath $FallbackHfHome
    }
    $selectedHubCache = if ($env:HF_HUB_CACHE) {
        Resolve-DirectoryPath $env:HF_HUB_CACHE
    } else {
        Join-Path $selectedHome 'hub'
    }
    $selectedXetCache = if ($env:HF_XET_CACHE) {
        Resolve-DirectoryPath $env:HF_XET_CACHE
    } else {
        Join-Path $selectedHome 'xet'
    }

    Write-Host "`nРекомендуемые пути HF cache:"
    Write-Host "HF_HOME: $selectedHome"
    Write-Host "HF_HUB_CACHE: $selectedHubCache"
    Write-Host "HF_XET_CACHE: $selectedXetCache"
    if ($NonInteractive) {
        Write-Host 'NonInteractive: используются указанные пути.'
    } else {
        $candidate = Read-Host 'Нажмите Enter, чтобы сохранить эти пути, или введите convenience root для HF_HOME/hub/xet'
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            $selectedHome = Resolve-DirectoryPath $candidate
            $selectedHubCache = Join-Path $selectedHome 'hub'
            $selectedXetCache = Join-Path $selectedHome 'xet'
        }
    }

    return [pscustomobject]@{
        Home = $selectedHome
        HubCache = $selectedHubCache
        XetCache = $selectedXetCache
    }
}

function Get-FreeSpaceGiB([string]$DirectoryPath) {
    try {
        $root = [System.IO.Path]::GetPathRoot($DirectoryPath)
        $drive = New-Object System.IO.DriveInfo($root)
        return [double]$drive.AvailableFreeSpace / 1GB
    } catch {
        return $null
    }
}

function Add-RuntimeToLocalExclude([string]$RuntimePath) {
    $repoPrefix = $RepoRoot.TrimEnd('\') + '\'
    if (-not $RuntimePath.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        return
    }
    $excludePath = Join-Path $RepoRoot '.git\info\exclude'
    $excludeDirectory = Split-Path -Parent $excludePath
    if (-not (Test-Path -LiteralPath $excludeDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $excludeDirectory -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $excludePath -PathType Leaf)) {
        New-Item -ItemType File -Path $excludePath -Force | Out-Null
    }
    $excludeLines = @(Get-Content -LiteralPath $excludePath -ErrorAction Stop)
    $relativeRuntimePath = $RuntimePath.Substring($repoPrefix.Length).Replace('\', '/') + '/'
    if ($excludeLines -notcontains $relativeRuntimePath) {
        Add-Content -LiteralPath $excludePath -Value $relativeRuntimePath -Encoding utf8
    }
}

function Format-Stage13Elapsed([double]$TotalSeconds) {
    $seconds = [Math]::Max(0, [int][Math]::Floor($TotalSeconds))
    $hours = [int][Math]::Floor($seconds / 3600)
    $minutes = [int][Math]::Floor(($seconds % 3600) / 60)
    $remainingSeconds = $seconds % 60
    return '{0:00}:{1:00}:{2:00}' -f $hours, $minutes, $remainingSeconds
}

function Invoke-Stage13Pip([string]$Phase, [string[]]$PipArguments) {
    Write-Host "Фаза ${Phase}: запуск..."
    $startedAt = [System.Diagnostics.Stopwatch]::StartNew()
    $job = $null
    try {
        $invocation = [pscustomobject]@{
            PythonExecutable = $VenvPython
            PipArguments = @($PipArguments)
        }
        $job = Start-Job -ScriptBlock {
            param($Invocation)
            $previousErrorActionPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                $output = @(& $Invocation.PythonExecutable -m pip @($Invocation.PipArguments) 2>&1)
                $exitCode = $LASTEXITCODE
            } finally {
                $ErrorActionPreference = $previousErrorActionPreference
            }
            [pscustomobject]@{
                ExitCode = $exitCode
                Output = $output
            }
        } -ArgumentList $invocation

        $lastHeartbeatSeconds = 0
        while ($job.State -notin @('Completed', 'Failed', 'Stopped')) {
            Start-Sleep -Seconds 1
            $elapsedSeconds = [int][Math]::Floor($startedAt.Elapsed.TotalSeconds)
            if ($elapsedSeconds -ge ($lastHeartbeatSeconds + 30)) {
                Write-Host "Фаза ${Phase}: выполняется, прошло $(Format-Stage13Elapsed $elapsedSeconds)"
                $lastHeartbeatSeconds = $elapsedSeconds
            }
        }

        $jobResult = @(Receive-Job -Job $job -ErrorAction Stop)
        if ($jobResult.Count -ne 1) {
            throw "pip phase '$Phase' не вернула итоговый status."
        }
        $result = $jobResult[0]
        $exitCode = [int]$result.ExitCode
        $output = @($result.Output)
        if ($exitCode -eq 0) {
            Write-Host "PASS: $Phase завершено за $(Format-Stage13Elapsed $startedAt.Elapsed.TotalSeconds)."
        }
        return [pscustomobject]@{
            ExitCode = $exitCode
            Output = $output
        }
    } finally {
        $startedAt.Stop()
        if ($null -ne $job) {
            if ($job.State -notin @('Completed', 'Failed', 'Stopped')) {
                Stop-Job -Job $job -ErrorAction SilentlyContinue
            }
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        }
    }
}

function Assert-Stage13PipSuccess([object]$Result, [string]$Description) {
    if ($Result.ExitCode -eq 0) {
        return
    }
    $tail = @($Result.Output | Select-Object -Last 20 | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
    if ([string]::IsNullOrWhiteSpace($tail)) {
        $tail = 'pip не вернул диагностический output.'
    }
    throw "$Description (exit code $($Result.ExitCode)). Последний output pip:`n$tail"
}

function Show-Summary {
    Write-Host "`nИтог"
    foreach ($item in $script:Summary.GetEnumerator()) {
        Write-Host ('{0,-19} {1,-4} {2}' -f $item.Key, $item.Value, $script:SummaryDetails[$item.Key])
    }
    if ($script:HasStop) {
        Write-Host "`nSTOP: Подготовка Stage 13 не завершена. Исправьте указанные выше причины и повторите запуск helper."
        exit 1
    }
    Write-Host "`nГОТОВО К STAGE 13 SAFE-RUN"
    Write-Host 'Notebook: notebooks/13_Сравнение_TabFM_с_GBDT_baseline_V1.ipynb'
    Write-Host "Kernel: $KernelDisplayName"
    Write-Host 'Важно: для SAFE-RUN оставьте RUN_FULL_OOF=False.'
    Write-Host 'Полный OOF на текущем CPU KOMUS не выполнялся из-за высокой вычислительной стоимости.'
    exit 0
}

Write-Host 'Подготовка Stage 13 TabFM V1. Helper не загружает модель, не запускает SAFE-RUN и не выполняет OOF.'
Write-Host "Корень репозитория: $RepoRoot"

$SelectedRuntimeDir = $null
$VenvPath = $null
$VenvPython = $null
$SelectedHfHome = $null
$SelectedHfHubCache = $null
$SelectedHfXetCache = $null

try {
    $SelectedRuntimeDir = Select-DirectoryPath 'runtime' $DefaultRuntimeDir $RuntimeDir
    if (Test-Path -LiteralPath $SelectedRuntimeDir -PathType Leaf) {
        throw "Runtime directory существует как файл: $SelectedRuntimeDir"
    }
    $VenvPath = Join-Path $SelectedRuntimeDir 'venv'
    $VenvPython = Join-Path $VenvPath 'Scripts\python.exe'
    $runtimeFreeGiB = Get-FreeSpaceGiB $SelectedRuntimeDir
    $runtimeMessage = "Выбрана $SelectedRuntimeDir"
    if ($null -ne $runtimeFreeGiB) { $runtimeMessage += ('; свободно {0:N1} GiB.' -f $runtimeFreeGiB) }
    Set-Check 'Runtime directory' 'PASS' $runtimeMessage
} catch {
    Set-Check 'Runtime directory' 'STOP' "Не удалось выбрать RuntimeDir: $($_.Exception.Message)"
}

try {
    $selectedHfPaths = Select-HfCachePaths $HfCacheDir
    $SelectedHfHome = $selectedHfPaths.Home
    $SelectedHfHubCache = $selectedHfPaths.HubCache
    $SelectedHfXetCache = $selectedHfPaths.XetCache
    foreach ($hfPath in @($SelectedHfHome, $SelectedHfHubCache, $SelectedHfXetCache)) {
        if (Test-Path -LiteralPath $hfPath -PathType Leaf) {
            throw "HF cache path существует как файл: $hfPath"
        }
    }
    $env:HF_HOME = $SelectedHfHome
    $env:HF_HUB_CACHE = $SelectedHfHubCache
    $env:HF_XET_CACHE = $SelectedHfXetCache
    $cacheFreeGiB = Get-FreeSpaceGiB $SelectedHfHubCache
    $cacheMessage = "HF_HOME=$SelectedHfHome; HF_HUB_CACHE=$SelectedHfHubCache; HF_XET_CACHE=$SelectedHfXetCache; pinned checkpoint занимает около 6.11 GiB"
    if ($null -ne $cacheFreeGiB) { $cacheMessage += ('; свободно {0:N1} GiB.' -f $cacheFreeGiB) }
    Set-Check 'HF cache directory' 'PASS' $cacheMessage
} catch {
    Set-Check 'HF cache directory' 'STOP' "Не удалось выбрать HfCacheDir: $($_.Exception.Message)"
}

$Python311 = $null
$ExistingVenvInfo = $null
$DiscoveryDiagnostics = $null
Write-Stage 1 'Проверка existing locked Python 3.11 environment'
if ($Summary['Runtime directory'] -ne 'PASS') {
    Set-Check 'Python 3.11' 'STOP' 'Python 3.11 не проверяется, пока RuntimeDir не выбран корректно.'
} elseif (Test-Path -LiteralPath $VenvPath -PathType Container) {
    $existingVenvReason = $null
    $ExistingVenvInfo = Test-Python311 -Executable $VenvPython -FailureReason ([ref]$existingVenvReason)
    if ($null -eq $ExistingVenvInfo) {
        Set-Check 'Python 3.11' 'STOP' "Runtime environment существует, но невалиден: $VenvPath ($existingVenvReason). Укажите другой -RuntimeDir либо вручную удалите/переименуйте старую среду; helper её не пересоздаёт поверх существующей."
    } else {
        $Python311 = $ExistingVenvInfo
        if ([string]::IsNullOrWhiteSpace($PythonExe)) {
            Set-Check 'Python 3.11' 'PASS' "Используется existing runtime interpreter $($ExistingVenvInfo.Executable), версия $($ExistingVenvInfo.Version); system/base Python 3.11 не требуется."
        } else {
            $explicitReason = $null
            $explicitPython = Test-Python311 -Executable $PythonExe -FailureReason ([ref]$explicitReason)
            if ($null -eq $explicitPython) {
                Set-Check 'Python 3.11' 'STOP' "Указанный -PythonExe невалиден: $PythonExe ($explicitReason). Требуется запускающийся Python 3.11.x."
            } else {
                Set-Check 'Python 3.11' 'PASS' "Указанный Python $($explicitPython.Version) найден: $($explicitPython.Executable). Existing runtime будет переиспользован."
            }
        }
    }
} elseif (Test-Path -LiteralPath $VenvPath) {
    Set-Check 'Python 3.11' 'STOP' "Runtime environment существует, но не является каталогом: $VenvPath. Укажите другой -RuntimeDir либо вручную удалите/переименуйте этот путь; helper его не перезаписывает."
} else {
    try {
        if (-not [string]::IsNullOrWhiteSpace($PythonExe)) {
            $explicitReason = $null
            $Python311 = Test-Python311 -Executable $PythonExe -FailureReason ([ref]$explicitReason)
            if ($null -eq $Python311) {
                Set-Check 'Python 3.11' 'STOP' "Указанный -PythonExe невалиден: $PythonExe ($explicitReason). Требуется запускающийся Python 3.11.x."
            } else {
                Set-Check 'Python 3.11' 'PASS' "Указанный Python $($Python311.Version) найден: $($Python311.Executable)."
            }
        } else {
            $Python311 = Find-Python311 -Diagnostics ([ref]$DiscoveryDiagnostics)
            if ($null -eq $Python311) {
                $diagnosticText = if ($null -ne $DiscoveryDiagnostics -and $DiscoveryDiagnostics.Count -gt 0) {
                    $DiscoveryDiagnostics -join '; '
                } else {
                    'кандидаты не найдены'
                }
                Set-Check 'Python 3.11' 'STOP' "Python 3.11 не найден. Проверены py -3.11, standard paths и Get-Command python -All: $diagnosticText"
            } else {
                Set-Check 'Python 3.11' 'PASS' "Python $($Python311.Version) найден: $($Python311.Executable)."
            }
        }
    } catch {
        Set-Check 'Python 3.11' 'STOP' "Не удалось проверить system/base Python 3.11: $($_.Exception.Message)"
    }
}

Write-Stage 2 'Проверка isolated environment .venv-tabfm-v1'
if ($Summary['Runtime directory'] -ne 'PASS') {
    Set-Check 'venv' 'STOP' 'Runtime environment не проверяется, пока RuntimeDir не выбран корректно.'
} elseif (Test-Path -LiteralPath $VenvPath -PathType Container) {
    if ($null -eq $ExistingVenvInfo) {
        Set-Check 'venv' 'STOP' "Runtime environment существует, но невалиден: $VenvPath. Укажите другой -RuntimeDir либо вручную удалите/переименуйте старую среду; helper её не пересоздаёт автоматически."
    } else {
        try {
            Add-RuntimeToLocalExclude $SelectedRuntimeDir
            Set-Check 'venv' 'PASS' "Переиспользуется existing runtime environment $($ExistingVenvInfo.Executable), версия $($ExistingVenvInfo.Version)."
        } catch {
            Set-Check 'venv' 'STOP' "Не удалось подготовить runtime environment: $($_.Exception.Message)"
        }
    }
} elseif (Test-Path -LiteralPath $VenvPath) {
    Set-Check 'venv' 'STOP' "Runtime environment существует как файл, а не как каталог: $VenvPath. Укажите другой -RuntimeDir либо переименуйте или удалите этот файл вручную."
} elseif ($null -eq $Python311) {
    Set-Check 'venv' 'STOP' 'Runtime environment не может быть создан без system/base Python 3.11.'
} else {
    try {
        $null = & $Python311.Launcher @($Python311.Prefix) -m venv $VenvPath 2>&1
        if ($LASTEXITCODE -ne 0) { throw 'команда создания venv завершилась с ошибкой' }
        Write-Host "PASS: Создан runtime environment $VenvPath."
        $venvReason = $null
        $VenvInfo = Test-Python311 -Executable $VenvPython -FailureReason ([ref]$venvReason)
        if ($null -eq $VenvInfo) {
            throw "внутри выбранного runtime отсутствует Python 3.11: $venvReason"
        }
        Add-RuntimeToLocalExclude $SelectedRuntimeDir
        Set-Check 'venv' 'PASS' "Используется $($VenvInfo.Executable), версия $($VenvInfo.Version)."
    } catch {
        Set-Check 'venv' 'STOP' "Не удалось подготовить runtime environment: $($_.Exception.Message)"
    }
}

$DependenciesOk = $false
Write-Stage 3 'Установка и hard-check locked dependencies'
if ($Summary['venv'] -ne 'PASS') {
    Set-Check 'dependencies' 'STOP' 'Проверка зависимостей невозможна без корректного runtime environment.'
    Set-Check 'TabFM commit' 'STOP' 'Проверка commit невозможна без корректного runtime environment.'
} elseif (-not (Test-Path -LiteralPath $RequirementsPath -PathType Leaf)) {
    Set-Check 'dependencies' 'STOP' 'Не найден requirements-tabfm-v1.txt. Восстановите locked requirements.'
    Set-Check 'TabFM commit' 'STOP' 'Проверка commit невозможна без locked requirements.'
} else {
    try {
        $requirementsPip = Invoke-Stage13Pip 'requirements' @('install', '--disable-pip-version-check', '-r', $RequirementsPath)
        Assert-Stage13PipSuccess $requirementsPip 'Не удалось установить requirements-tabfm-v1.txt; проверьте доступ к сети, Git и PyTorch CPU index'
        $kernelPip = Invoke-Stage13Pip 'ipykernel' @('install', '--disable-pip-version-check', 'ipykernel==7.3.0')
        Assert-Stage13PipSuccess $kernelPip 'Не удалось установить ipykernel==7.3.0'
        $pipCheck = Invoke-Stage13Pip 'pip check' @('check')
        Assert-Stage13PipSuccess $pipCheck 'pip check обнаружил несовместимые зависимости'

        $probe = @'
import importlib.metadata as metadata
import json
import sys

versions = {name: metadata.version(name) for name in (
    'torch', 'safetensors', 'huggingface-hub', 'tabfm', 'ipykernel'
)}
direct_url = metadata.distribution('tabfm').read_text('direct_url.json')
commit = None if not direct_url else json.loads(direct_url).get('vcs_info', {}).get('commit_id')
print(json.dumps({'python': '.'.join(map(str, sys.version_info[:3])), 'versions': versions, 'commit': commit}))
'@
        $probeResult = @(& $VenvPython -c $probe 2>$null)
        if ($LASTEXITCODE -ne 0 -or $probeResult.Count -ne 1) { throw 'не удалось прочитать metadata установленных пакетов' }
        $installed = $probeResult[0] | ConvertFrom-Json
        $expectedVersions = @{ 'torch' = '2.12.1+cpu'; 'safetensors' = '0.8.0'; 'huggingface-hub' = '1.21.0'; 'tabfm' = '1.0.1'; 'ipykernel' = '7.3.0' }
        $mismatches = @()
        if ([string]$installed.python -notmatch '^3\.11\.\d+$') { $mismatches += "Python=$($installed.python)" }
        foreach ($name in $expectedVersions.Keys) {
            if ([string]$installed.versions.$name -ne $expectedVersions[$name]) { $mismatches += "${name}=$($installed.versions.$name)" }
        }
        if ($mismatches.Count -gt 0) { throw "hard-check не пройден: $($mismatches -join ', ')" }
        Set-Check 'dependencies' 'PASS' 'Python 3.11.x, torch 2.12.1+cpu, safetensors 0.8.0, huggingface_hub 1.21.0, tabfm 1.0.1 и ipykernel 7.3.0 подтверждены.'
        if ([string]$installed.commit -ne $ExpectedTabfmCommit) { throw "установлен commit TabFM $($installed.commit), ожидался $ExpectedTabfmCommit" }
        Set-Check 'TabFM commit' 'PASS' "Подтверждён locked commit $ExpectedTabfmCommit."
        $DependenciesOk = $true
    } catch {
        Set-Check 'dependencies' 'STOP' "Locked dependencies не подтверждены: $($_.Exception.Message)"
        if ($Summary['TabFM commit'] -ne 'PASS') {
            Set-Check 'TabFM commit' 'STOP' 'Locked commit TabFM не подтверждён. Исправьте environment и повторите запуск.'
        }
    }
}

Write-Stage 4 'Регистрация Jupyter kernel'
if (-not $DependenciesOk) {
    Set-Check 'Jupyter kernel' 'STOP' 'Kernel не регистрируется, пока locked dependencies не подтверждены.'
} elseif ($Summary['HF cache directory'] -ne 'PASS') {
    Set-Check 'Jupyter kernel' 'STOP' 'Kernel не регистрируется, пока HfCacheDir не выбран корректно.'
} else {
    try {
        $null = & $VenvPython -m ipykernel install --user --name $KernelName --display-name $KernelDisplayName `
            --env HF_HOME $SelectedHfHome --env HF_HUB_CACHE $SelectedHfHubCache --env HF_XET_CACHE $SelectedHfXetCache 2>&1
        if ($LASTEXITCODE -ne 0) { throw 'команда регистрации kernel завершилась с ошибкой' }
        Set-Check 'Jupyter kernel' 'PASS' "Kernel '$KernelDisplayName' зарегистрирован/обновлён без создания дубликатов; HF_HOME=$SelectedHfHome, HF_HUB_CACHE=$SelectedHfHubCache, HF_XET_CACHE=$SelectedHfXetCache."
    } catch {
        Set-Check 'Jupyter kernel' 'STOP' "Не удалось зарегистрировать Jupyter kernel: $($_.Exception.Message)"
    }
}

Write-Stage 5 'Проверка dataset и обязательных artifacts'
$datasetPath = Join-Path $RepoRoot 'data\raw\Data_final.xlsb'
if (-not (Test-Path -LiteralPath $datasetPath -PathType Leaf)) {
    Set-Check 'dataset SHA' 'STOP' 'Не найден data/raw/Data_final.xlsb. Восстановите исходный dataset.'
} else {
    try {
        $actualDatasetSha = (Get-FileHash -LiteralPath $datasetPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualDatasetSha -ne $ExpectedDatasetSha) { throw "получен SHA-256 $actualDatasetSha, ожидался $ExpectedDatasetSha" }
        Set-Check 'dataset SHA' 'PASS' 'Data_final.xlsb найден, SHA-256 совпадает.'
    } catch {
        Set-Check 'dataset SHA' 'STOP' "Dataset guard не пройден: $($_.Exception.Message)"
    }
}

$requiredArtifacts = @(
    'reports\generated\stage1_baseline_results_V2.json',
    'reports\generated\stage7_tabm_stacking_results_V1.json',
    'reports\generated\stage7_tabm_stacking_oof_V1.npz'
)
$missingArtifacts = @($requiredArtifacts | Where-Object { -not (Test-Path -LiteralPath (Join-Path $RepoRoot $_) -PathType Leaf) })
if ($missingArtifacts.Count -gt 0) {
    Set-Check 'required artifacts' 'STOP' "Отсутствуют обязательные artifacts: $($missingArtifacts -join '; '). Восстановите их перед Stage 13."
} else {
    Set-Check 'required artifacts' 'PASS' 'Все обязательные Stage 1/7 artifacts найдены.'
}

Write-Stage 6 'Проверка защиты output Stage 13'
$stage13Artifacts = @(
    'reports\generated\stage13_tabfm_oof_V1.npz',
    'reports\generated\stage13_tabfm_results_V1.json'
)
$existingStage13 = @($stage13Artifacts | Where-Object { Test-Path -LiteralPath (Join-Path $RepoRoot $_) -PathType Leaf })
if ($existingStage13.Count -gt 0) {
    Set-Check 'output guard' 'STOP' "Уже существуют Stage 13 artifacts: $($existingStage13 -join '; '). Автоматический overwrite запрещён; helper не удаляет и не переименовывает эти artifacts. Перед повторным Stage 13 оператор должен вручную проверить, что это за artifacts, и принять отдельное решение."
} else {
    Set-Check 'output guard' 'PASS' 'Stage 13 output artifacts пока отсутствуют; helper ничего не создаёт и не удаляет.'
}

Write-Stage 7 'Проверка RAM, pagefile и commit capacity'
try {
    $computerSystem = Get-CimInstance -ClassName Win32_ComputerSystem
    $ramGiB = [double]$computerSystem.TotalPhysicalMemory / 1GB
    $pageFiles = @(Get-CimInstance -ClassName Win32_PageFileUsage)
    $pagefileGiB = (@($pageFiles | Measure-Object -Property AllocatedBaseSize -Sum).Sum * 1MB) / 1GB
    $commitGiB = $ramGiB + $pagefileGiB
    Write-Host ('Физическая RAM: {0:N1} GiB' -f $ramGiB)
    Write-Host ('Текущий pagefile allocation: {0:N1} GiB' -f $pagefileGiB)
    Write-Host ('Приблизительная total commit capacity: {0:N1} GiB' -f $commitGiB)
    foreach ($pageFile in $pageFiles) {
        $drive = ([string]$pageFile.Name).Substring(0, 2)
        $disk = Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DeviceID='$drive'"
        if ($null -ne $disk) {
            Write-Host ('Свободное место на {0}: {1:N1} GiB' -f $drive, ([double]$disk.FreeSpace / 1GB))
        }
    }
    if ($commitGiB -lt 50) {
        Set-Check 'memory/commit' 'WARN' 'Для похожей конфигурации KOMUS этого может быть недостаточно. На проверенной машине стабильный model load был получен при total commit около 55 GiB. Helper pagefile автоматически не меняет.'
    } else {
        Set-Check 'memory/commit' 'PASS' 'Приблизительная total commit capacity не меньше 50 GiB.'
    }
} catch {
    Set-Check 'memory/commit' 'WARN' "Не удалось получить полные сведения о RAM/pagefile: $($_.Exception.Message). Проверьте их вручную; helper pagefile не меняет."
}

Write-Stage 8 'Проверка Hugging Face cache и pinned checkpoint'
if ($Summary['HF cache directory'] -ne 'PASS') {
    Set-Check 'HF checkpoint' 'STOP' 'HF checkpoint не проверяется, пока HfCacheDir не выбран корректно.'
} else {
    Write-Host "HF_HOME: $SelectedHfHome"
    Write-Host "HF_HUB_CACHE: $SelectedHfHubCache"
    Write-Host "HF_XET_CACHE: $SelectedHfXetCache"
    $checkpointPath = Join-Path $SelectedHfHubCache "models--google--tabfm-1.0.0-pytorch\snapshots\$ExpectedRevision\classification\model.safetensors"
    if (-not (Test-Path -LiteralPath $checkpointPath -PathType Leaf)) {
        Set-Check 'HF checkpoint' 'WARN' 'Checkpoint ещё не загружен. Первый SAFE-RUN notebook скачает pinned artifact (~6.11 GB). Helper checkpoint не скачивает.'
    } else {
        try {
            $checkpointStream = [System.IO.File]::OpenRead($checkpointPath)
            try {
                $checkpointSize = $checkpointStream.Length
            } finally {
                $checkpointStream.Dispose()
            }
            $checkpointSha = (Get-FileHash -LiteralPath $checkpointPath -Algorithm SHA256).Hash.ToLowerInvariant()
            Write-Host ('Размер pinned checkpoint: {0:N2} GiB' -f ([double]$checkpointSize / 1GB))
            if ($checkpointSha -ne $ExpectedCheckpointSha) { throw "SHA-256 $checkpointSha не совпадает с pinned SHA $ExpectedCheckpointSha" }
            Set-Check 'HF checkpoint' 'PASS' 'Pinned checkpoint найден; SHA-256 точно совпадает.'
        } catch {
            Set-Check 'HF checkpoint' 'STOP' "Pinned checkpoint повреждён или не соответствует revision: $($_.Exception.Message)"
        }
    }
}

Show-Summary
