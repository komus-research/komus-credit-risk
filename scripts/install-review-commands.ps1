# UNIVERSAL REVIEW HELPER
#
# Один раз на компьютере:
#   Unblock-File .\scripts\*.ps1
#   .\scripts\install-review-commands.ps1
#
# Перед работой Codex:
#   revs
#
# После работы Codex:
#   revp
#
# revp сам проверяет изменения, пушит review-ветку
# и печатает готовый текст для Reviewer.

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ProfileBlock = @'
# >>> universal-review-helper-v4 >>>
function global:revs { Invoke-UniversalReviewHelper -Action start }
function global:revp { Invoke-UniversalReviewHelper -Action prepare }
function global:Invoke-UniversalReviewHelper {
    param([Parameter(Mandatory = $true)][ValidateSet('start', 'prepare')][string]$Action)
    $root = & git rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $root) {
        Write-Host 'Не найден Git-репозиторий.' -ForegroundColor Yellow
        return
    }
    $helper = Join-Path -Path ([string]($root | Select-Object -First 1)).Trim() -ChildPath 'scripts\review.ps1'
    if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) {
        Write-Host 'Нет scripts\review.ps1 в текущем репозитории.' -ForegroundColor Yellow
        return
    }
    & $helper $Action
}
# <<< universal-review-helper-v4 <<<
'@

function Remove-ManagedBlock {
    param([AllowEmptyString()][string]$Text, [Parameter(Mandatory = $true)][string]$Start, [Parameter(Mandatory = $true)][string]$End)
    while ($true) {
        $StartIndex = $Text.IndexOf($Start, [System.StringComparison]::Ordinal)
        if ($StartIndex -lt 0) { return $Text }
        $EndIndex = $Text.IndexOf($End, $StartIndex, [System.StringComparison]::Ordinal)
        if ($EndIndex -lt 0) { return $Text }
        $Text = $Text.Remove($StartIndex, ($EndIndex + $End.Length) - $StartIndex)
    }
}

function Update-ProfileFile {
    param([Parameter(Mandatory = $true)][string]$ProfilePath)
    $Directory = Split-Path -Parent $ProfilePath
    if (-not (Test-Path -LiteralPath $Directory)) { New-Item -ItemType Directory -Path $Directory -Force | Out-Null }
    $Existing = if (Test-Path -LiteralPath $ProfilePath -PathType Leaf) { [System.IO.File]::ReadAllText($ProfilePath, [System.Text.Encoding]::UTF8) } else { '' }
    foreach ($Version in @('v1', 'v2', 'v3', 'v4')) {
        $Existing = Remove-ManagedBlock -Text $Existing -Start "# >>> universal-review-helper-$Version >>>" -End "# <<< universal-review-helper-$Version <<<"
    }
    $Updated = $Existing.TrimEnd()
    if (-not [string]::IsNullOrWhiteSpace($Updated)) { $Updated += [Environment]::NewLine + [Environment]::NewLine }
    $Updated += $ProfileBlock + [Environment]::NewLine
    [System.IO.File]::WriteAllText($ProfilePath, $Updated, (New-Object System.Text.UTF8Encoding($true)))
}

function global:Invoke-UniversalReviewHelper {
    param([Parameter(Mandatory = $true)][ValidateSet('start', 'prepare')][string]$Action)
    $root = & git rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $root) { Write-Host 'Не найден Git-репозиторий.' -ForegroundColor Yellow; return }
    $helper = Join-Path -Path ([string]($root | Select-Object -First 1)).Trim() -ChildPath 'scripts\review.ps1'
    if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) { Write-Host 'Нет scripts\review.ps1 в текущем репозитории.' -ForegroundColor Yellow; return }
    & $helper $Action
}
function global:revs { Invoke-UniversalReviewHelper -Action start }
function global:revp { Invoke-UniversalReviewHelper -Action prepare }

try {
    $ReviewScript = Join-Path $PSScriptRoot 'review.ps1'
    if (Test-Path -LiteralPath $ReviewScript -PathType Leaf) { Unblock-File -LiteralPath $ReviewScript -ErrorAction SilentlyContinue }
    $Profiles = @([string]$PROFILE.CurrentUserAllHosts, [string]$PROFILE.CurrentUserCurrentHost) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
    foreach ($ProfilePath in $Profiles) { Update-ProfileFile -ProfilePath $ProfilePath }
    Write-Host ''
    Write-Host 'revs / revp установлены и уже активны.' -ForegroundColor Green
    foreach ($ProfilePath in $Profiles) { Write-Host "Profile: $ProfilePath" }
    Write-Host ''
}
catch {
    Write-Host ''
    Write-Host 'Не удалось установить revs / revp.' -ForegroundColor Red
    Write-Host $_.Exception.Message
    Write-Host ''
}
