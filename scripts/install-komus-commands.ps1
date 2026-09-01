# Установка
# .\scripts\install-komus-commands.ps1

[CmdletBinding()]
param(
    [string]$WorkingRepo = 'D:\Projects\komus-work',
    [string]$InstituteRepo = 'D:\Projects\commus-institute',
    [string]$RuntimeRoot = (Join-Path $env:USERPROFILE '.komus-git'),
    [string[]]$ProfilePath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

function Remove-ManagedBlock {
    param([string]$Text,[string]$Start,[string]$End)
    while ($true) {
        $startAt = $Text.IndexOf($Start,[StringComparison]::Ordinal)
        if ($startAt -lt 0) { return $Text }
        $endAt = $Text.IndexOf($End,$startAt,[StringComparison]::Ordinal)
        if ($endAt -lt 0) { return $Text }
        $Text = $Text.Remove($startAt,($endAt + $End.Length) - $startAt)
    }
}
function Resolve-GhPath {
    param([string]$ConfiguredPath)
    $command = Get-Command gh -ErrorAction SilentlyContinue
    if ($command -and (Test-Path -LiteralPath $command.Source -PathType Leaf)) { return [IO.Path]::GetFullPath($command.Source) }
    foreach ($candidate in @($ConfiguredPath, (Join-Path $env:ProgramFiles 'GitHub CLI\gh.exe'), (Join-Path ${env:ProgramFiles(x86)} 'GitHub CLI\gh.exe'))) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return [IO.Path]::GetFullPath($candidate) }
    }
    return $null
}
function Get-ProfileBlock {
    param([string]$Helper,[string]$Config,[string]$Review)
    $h=$Helper.Replace("'","''"); $c=$Config.Replace("'","''"); $r=$Review.Replace("'","''")
    return @"
# >>> KOMUS GIT HELPER >>>
function global:Invoke-KomusRuntime {
    param([Parameter(Mandatory = `$true)][ValidateSet('push','institute')][string]`$Action,[AllowEmptyString()][string]`$Comment)
    & '$h' -Action `$Action -Comment `$Comment -ConfigPath '$c'
}
function global:kpush {
    param([Parameter(ValueFromRemainingArguments = `$true)][string[]]`$CommentParts)
    if (`$CommentParts.Count -gt 1) { Write-Host 'kpush accepts one optional comment.' -ForegroundColor Yellow; return }
    Invoke-KomusRuntime -Action push -Comment (`$CommentParts -join ' ')
}
function global:kinst {
    param([Parameter(ValueFromRemainingArguments = `$true)][string[]]`$CommentParts)
    if (`$CommentParts.Count -gt 1) { Write-Host 'kinst accepts one optional comment.' -ForegroundColor Yellow; return }
    Invoke-KomusRuntime -Action institute -Comment (`$CommentParts -join ' ')
}
function global:Invoke-KomusReviewRuntime {
    param([Parameter(Mandatory = `$true)][ValidateSet('start','prepare')][string]`$Action)
    if (-not (Test-Path -LiteralPath '$r' -PathType Leaf)) { Write-Host 'Runtime review helper is missing. Run the installer again.' -ForegroundColor Yellow; return }
    try { `$workingRepo = (Get-Content -LiteralPath '$c' -Raw -Encoding UTF8 | ConvertFrom-Json).working_repo }
    catch { Write-Host 'Cannot read KOMUS configuration.' -ForegroundColor Yellow; return }
    if (-not (Test-Path -LiteralPath `$workingRepo -PathType Container)) { Write-Host "Working repository is missing: `$workingRepo" -ForegroundColor Yellow; return }
    Push-Location -LiteralPath `$workingRepo
    try { & '$r' `$Action }
    finally { Pop-Location }
}
function global:revs { Invoke-KomusReviewRuntime -Action start }
function global:revp { Invoke-KomusReviewRuntime -Action prepare }
# <<< KOMUS GIT HELPER <<<
"@
}

try {
    $sourceHelper = Join-Path $PSScriptRoot 'komus-git.ps1'
    if (-not (Test-Path -LiteralPath $sourceHelper -PathType Leaf)) { throw "Helper is missing: $sourceHelper" }
    New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
    $runtimeHelper=Join-Path $RuntimeRoot 'komus-git.ps1'; $runtimeReview=Join-Path $RuntimeRoot 'review.ps1'; $configPath=Join-Path $RuntimeRoot 'config.json'
    Copy-Item -LiteralPath $sourceHelper -Destination $runtimeHelper -Force
    $sourceReview=Join-Path $PSScriptRoot 'review.ps1'; if (Test-Path -LiteralPath $sourceReview -PathType Leaf) { Copy-Item -LiteralPath $sourceReview -Destination $runtimeReview -Force }
    $oldGhPath = $null
    if (Test-Path -LiteralPath $configPath -PathType Leaf) { try { $oldGhPath = (Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json).gh_path } catch { } }
    $ghPath = Resolve-GhPath ([string]$oldGhPath)
    $config=[ordered]@{ working_repo=[IO.Path]::GetFullPath($WorkingRepo); institute_repo=[IO.Path]::GetFullPath($InstituteRepo); working_remote_url='https://github.com/komus-research/komus-credit-risk.git'; institute_remote_url='https://github.com/AIUniverstorage/commus.git'; institute_base_branch='Data_Komus'; institute_prefix='credit-scoring'; gh_path=$ghPath }
    [IO.File]::WriteAllText($configPath,($config | ConvertTo-Json -Depth 4),(New-Object Text.UTF8Encoding($true)))
    if (-not $ProfilePath -or $ProfilePath.Count -eq 0) { $ProfilePath=@([string]$PROFILE.CurrentUserAllHosts,[string]$PROFILE.CurrentUserCurrentHost) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique }
    $block=Get-ProfileBlock $runtimeHelper $configPath $runtimeReview
    foreach ($path in $ProfilePath) {
        $dir=Split-Path -Parent $path; if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $old=if (Test-Path -LiteralPath $path -PathType Leaf) { [IO.File]::ReadAllText($path,[Text.Encoding]::UTF8) } else { '' }
        $new=(Remove-ManagedBlock $old '# >>> KOMUS GIT HELPER >>>' '# <<< KOMUS GIT HELPER <<<').TrimEnd(); if ($new) { $new += [Environment]::NewLine + [Environment]::NewLine }
        [IO.File]::WriteAllText($path,$new+$block+[Environment]::NewLine,(New-Object Text.UTF8Encoding($true)))
    }
    Write-Host ''; Write-Host 'INSTALLATION COMPLETE' -ForegroundColor Green; Write-Host "Working repository: $($config.working_repo)"; Write-Host "Institute repository: $($config.institute_repo)"; if ($ghPath) { Write-Host "GitHub CLI: $ghPath" }; Write-Host 'Commands: kpush, kinst, revs, revp'; Write-Host 'Reload this terminal with: . $PROFILE' -ForegroundColor Cyan; Write-Host ''
}
catch { Write-Host ''; Write-Host 'KOMUS Git Helper installation failed.' -ForegroundColor Red; Write-Host $_.Exception.Message; exit 1 }
