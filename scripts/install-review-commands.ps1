#
# Installs global revs / revp commands.
# The installed helper is copied to LOCALAPPDATA so it works
# independently of the current repository branch.
#
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$InstallRoot = if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    Join-Path $env:LOCALAPPDATA 'UniversalReviewHelper'
}
else {
    Join-Path $HOME '.universal-review-helper'
}
$InstalledHelper = Join-Path $InstallRoot 'review.ps1'

$ProfileBlock = @'
# >>> universal-review-helper-v6 >>>
function global:Invoke-UniversalReviewHelper {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('start', 'prepare')]
        [string]$Action
    )
    $base = if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        Join-Path $env:LOCALAPPDATA 'UniversalReviewHelper'
    }
    else {
        Join-Path $HOME '.universal-review-helper'
    }
    $helper = Join-Path $base 'review.ps1'
    if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) {
        Write-Host 'Universal Review Helper не установлен. Запустите scripts\install-review-commands.ps1.' -ForegroundColor Yellow
        return
    }
    & $helper $Action
}
function global:revs { Invoke-UniversalReviewHelper -Action start }
function global:revp { Invoke-UniversalReviewHelper -Action prepare }
# <<< universal-review-helper-v6 <<<
'@

function Remove-ManagedBlock {
    param(
        [AllowEmptyString()][string]$Text,
        [Parameter(Mandatory = $true)][string]$Start,
        [Parameter(Mandatory = $true)][string]$End
    )
    while ($true) {
        $StartIndex = $Text.IndexOf($Start, [System.StringComparison]::Ordinal)
        if ($StartIndex -lt 0) { return $Text }
        $EndIndex = $Text.IndexOf($End, $StartIndex, [System.StringComparison]::Ordinal)
        if ($EndIndex -lt 0) { return $Text }
        $Text = $Text.Remove(
            $StartIndex,
            ($EndIndex + $End.Length) - $StartIndex
        )
    }
}

function Update-ProfileFile {
    param([Parameter(Mandatory = $true)][string]$ProfilePath)
    $Directory = Split-Path -Parent $ProfilePath
    if (-not (Test-Path -LiteralPath $Directory)) {
        New-Item -ItemType Directory -Path $Directory -Force | Out-Null
    }
    $Existing = if (Test-Path -LiteralPath $ProfilePath -PathType Leaf) {
        [System.IO.File]::ReadAllText($ProfilePath, [System.Text.Encoding]::UTF8)
    }
    else {
        ''
    }
    foreach ($Version in @('v1', 'v2', 'v3', 'v4', 'v5', 'v6')) {
        $Existing = Remove-ManagedBlock -Text $Existing -Start "# >>> universal-review-helper-$Version >>>" -End "# <<< universal-review-helper-$Version <<<"
    }
    $Updated = $Existing.TrimEnd()
    if (-not [string]::IsNullOrWhiteSpace($Updated)) {
        $Updated += [Environment]::NewLine + [Environment]::NewLine
    }
    $Updated += $ProfileBlock + [Environment]::NewLine
    [System.IO.File]::WriteAllText(
        $ProfilePath,
        $Updated,
        (New-Object System.Text.UTF8Encoding($true))
    )
}

function global:Invoke-UniversalReviewHelper {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('start', 'prepare')]
        [string]$Action
    )
    & $InstalledHelper $Action
}
function global:revs { Invoke-UniversalReviewHelper -Action start }
function global:revp { Invoke-UniversalReviewHelper -Action prepare }

try {
    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    $SourceHelper = Join-Path $PSScriptRoot 'review.ps1'
    if (-not (Test-Path -LiteralPath $SourceHelper -PathType Leaf)) {
        throw 'Не найден scripts\review.ps1 рядом с установщиком.'
    }
    Copy-Item -LiteralPath $SourceHelper -Destination $InstalledHelper -Force
    Unblock-File -LiteralPath $InstalledHelper -ErrorAction SilentlyContinue

    $Profiles = @(
        [string]$PROFILE.CurrentUserAllHosts,
        [string]$PROFILE.CurrentUserCurrentHost
    ) | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_)
    } | Select-Object -Unique

    foreach ($ProfilePath in $Profiles) {
        Update-ProfileFile -ProfilePath $ProfilePath
    }

    Write-Host ''
    Write-Host 'revs / revp установлены и уже активны.' -ForegroundColor Green
    Write-Host "Helper: $InstalledHelper"
    foreach ($ProfilePath in $Profiles) {
        Write-Host "Profile: $ProfilePath"
    }
    Write-Host ''
}
catch {
    Write-Host ''
    Write-Host 'Не удалось установить review helper.' -ForegroundColor Red
    Write-Host $_.Exception.Message
    Write-Host ''
}
