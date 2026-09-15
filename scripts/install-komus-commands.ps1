# Установка
# .\scripts\install-komus-commands.ps1

[CmdletBinding()]
param(
    [string]$WorkingRepo = (Split-Path -Parent $PSScriptRoot),
    [string]$InstituteRepo = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'commus-institute'),
    [string]$RuntimeRoot = (Join-Path $env:USERPROFILE '.komus-git'),
    [string[]]$ProfilePath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

function U { param([string]$Base64) return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Base64)) }
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
function Test-ManagedComusCommand {
    param([System.Management.Automation.CommandInfo]$Command,[string[]]$Paths)
    if ($null -eq $Command -or $Command.CommandType -ne 'Function' -or [string]::IsNullOrWhiteSpace($Command.ScriptBlock.File)) { return $false }
    $commandSource = [IO.Path]::GetFullPath($Command.ScriptBlock.File)
    foreach ($path in $Paths) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        if ($commandSource -ne [IO.Path]::GetFullPath($path)) { continue }
        $text = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8)
        $start = $text.IndexOf('# >>> KOMUS GIT HELPER >>>', [StringComparison]::Ordinal)
        if ($start -lt 0) { continue }
        $end = $text.IndexOf('# <<< KOMUS GIT HELPER <<<', $start, [StringComparison]::Ordinal)
        if ($end -lt 0) { continue }
        if ($text.Substring($start, $end - $start) -match '(?m)^function global:comus\s*\{') { return $true }
    }
    return $false
}
function Get-ProfileBlock {
    param([string]$Helper,[string]$Config,[string]$Review,[string]$PrototypeRepo)
    $h=$Helper.Replace("'","''"); $c=$Config.Replace("'","''"); $r=$Review.Replace("'","''"); $p=$PrototypeRepo.Replace("'","''")
    return @"
# >>> KOMUS GIT HELPER >>>
function global:Invoke-KomusRuntime {
    param([Parameter(Mandatory = `$true)][ValidateSet('push','institute')][string]`$Action,[AllowEmptyString()][string]`$Comment)
    & '$h' -Action `$Action -Comment `$Comment -ConfigPath '$c'
}
function global:kpush {
    param([Parameter(ValueFromRemainingArguments = `$true)][string[]]`$CommentParts)
    if (`$CommentParts.Count -gt 1) { Write-Host ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('a3B1c2gg0L/RgNC40L3QuNC80LDQtdGCINGC0L7Qu9GM0LrQviDQvtC00LjQvSDQvdC10L7QsdGP0LfQsNGC0LXQu9GM0L3Ri9C5INC60L7QvNC80LXQvdGC0LDRgNC40Lku'))) -ForegroundColor Yellow; return }
    Invoke-KomusRuntime -Action push -Comment (`$CommentParts -join ' ')
}
function global:kinst {
    param([Parameter(ValueFromRemainingArguments = `$true)][string[]]`$CommentParts)
    if (`$CommentParts.Count -gt 1) { Write-Host ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('a2luc3Qg0L/RgNC40L3QuNC80LDQtdGCINGC0L7Qu9GM0LrQviDQvtC00LjQvSDQvdC10L7QsdGP0LfQsNGC0LXQu9GM0L3Ri9C5INC60L7QvNC80LXQvdGC0LDRgNC40Lku'))) -ForegroundColor Yellow; return }
    Invoke-KomusRuntime -Action institute -Comment (`$CommentParts -join ' ')
}
function global:Invoke-KomusReviewRuntime {
    param([Parameter(Mandatory = `$true)][ValidateSet('start','prepare')][string]`$Action)
    if (-not (Test-Path -LiteralPath '$r' -PathType Leaf)) { Write-Host ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('UnVudGltZSByZXZpZXcgaGVscGVyINC90LUg0L3QsNC50LTQtdC9LiDQl9Cw0L/Rg9GB0YLQuNGC0LUgaW5zdGFsbGVyINC10YnRkSDRgNCw0Lcu'))) -ForegroundColor Yellow; return }
    try { `$workingRepo = (Get-Content -LiteralPath '$c' -Raw -Encoding UTF8 | ConvertFrom-Json).working_repo }
    catch { Write-Host ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('0J3QtSDRg9C00LDQu9C+0YHRjCDQv9GA0L7Rh9C40YLQsNGC0Ywg0LrQvtC90YTQuNCz0YPRgNCw0YbQuNGOIEtPTVVTLg=='))) -ForegroundColor Yellow; return }
    if (-not (Test-Path -LiteralPath `$workingRepo -PathType Container)) { Write-Host (([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('0KDQsNCx0L7Rh9C40Lkg0YDQtdC/0L7Qt9C40YLQvtGA0LjQuSDQvdC1INC90LDQudC00LXQvTo='))) + " `$workingRepo") -ForegroundColor Yellow; return }
    Push-Location -LiteralPath `$workingRepo
    try { & '$r' `$Action }
    finally { Pop-Location }
}
function global:revs { Invoke-KomusReviewRuntime -Action start }
function global:revp { Invoke-KomusReviewRuntime -Action prepare }
function global:comus {
    `$repository = '$p'
    if (-not (Test-Path -LiteralPath (Join-Path `$repository 'pyproject.toml') -PathType Leaf) -or -not (Test-Path -LiteralPath (Join-Path `$repository 'app\streamlit_app.py') -PathType Leaf)) {
        Write-Host (([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('0KDQtdC/0L7Qt9C40YLQvtGA0LjQuSBLT01VUyDQvdC1INGA0LDRgdC/0L7Qt9C90LDQvTog'))) + "`$repository") -ForegroundColor Red
        return
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('0JrQvtC80LDQvdC00LAgdXYg0L3QtSDQvdCw0LnQtNC10L3QsC4g0KPRgdGC0LDQvdC+0LLQuNGC0LUgdXYg0Lgg0YHQvdC+0LLQsCDQvtGC0LrRgNC+0LnRgtC1IFBvd2VyU2hlbGwu'))) -ForegroundColor Red
        return
    }
    Push-Location -LiteralPath `$repository
    try { & uv run python -m streamlit run app/streamlit_app.py }
    finally { Pop-Location }
}
# <<< KOMUS GIT HELPER <<<
"@
}

try {
    $prototypeRepo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    if (-not (Test-Path -LiteralPath (Join-Path $prototypeRepo 'pyproject.toml') -PathType Leaf) -or -not (Test-Path -LiteralPath (Join-Path $prototypeRepo 'app\streamlit_app.py') -PathType Leaf)) { throw "KOMUS repository was not recognized near: $PSScriptRoot" }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw (U '0JrQvtC80LDQvdC00LAgdXYg0L3QtSDQvdCw0LnQtNC10L3QsC4g0KPRgdGC0LDQvdC+0LLQuNGC0LUgdXYg0Lgg0L/QvtCy0YLQvtGA0LjRgtC1INGD0YHRgtCw0L3QvtCy0LrRgy4=') }
    if (-not $ProfilePath -or $ProfilePath.Count -eq 0) { $ProfilePath=@([string]$PROFILE.CurrentUserAllHosts,[string]$PROFILE.CurrentUserCurrentHost) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique }
    $existingComus = Get-Command comus -ErrorAction SilentlyContinue
    if ($existingComus -and -not (Test-ManagedComusCommand $existingComus $ProfilePath)) { throw (U '0JrQvtC80LDQvdC00LAgY29tdXMg0YPQttC1INC40YHQv9C+0LvRjNC30YPQtdGC0YHRjyDQtNGA0YPQs9C+0Lkg0L/RgNC+0LPRgNCw0LzQvNC+0LkuINCj0YHRgtCw0L3QvtCy0LrQsCDQvtGB0YLQsNC90L7QstC70LXQvdCwLg==') }
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
    $block=Get-ProfileBlock $runtimeHelper $configPath $runtimeReview $prototypeRepo
    foreach ($path in $ProfilePath) {
        $dir=Split-Path -Parent $path; if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $old=if (Test-Path -LiteralPath $path -PathType Leaf) { [IO.File]::ReadAllText($path,[Text.Encoding]::UTF8) } else { '' }
        $new=(Remove-ManagedBlock $old '# >>> KOMUS GIT HELPER >>>' '# <<< KOMUS GIT HELPER <<<').TrimEnd(); if ($new) { $new += [Environment]::NewLine + [Environment]::NewLine }
        [IO.File]::WriteAllText($path,$new+$block+[Environment]::NewLine,(New-Object Text.UTF8Encoding($true)))
    }
    Write-Host ''; Write-Host (U '0KPQodCi0JDQndCe0JLQmtCQINCX0JDQktCV0KDQqNCV0J3QkA==') -ForegroundColor Green; Write-Host ((U '0KDQsNCx0L7Rh9C40Lkg0YDQtdC/0L7Qt9C40YLQvtGA0LjQuTo=') + " $($config.working_repo)"); Write-Host ((U '0KDQtdC/0L7Qt9C40YLQvtGA0LjQuSDQmNC90YHRgtC40YLRg9GC0LA6') + " $($config.institute_repo)"); if ($ghPath) { Write-Host "GitHub CLI: $ghPath" }; Write-Host ((U '0JTQvtGB0YLRg9C/0L3Ri9C1INC60L7QvNCw0L3QtNGLOg==') + ' kpush, kinst, revs, revp, comus'); Write-Host ((U '0J7QsdC90L7QstC40YLRjCDQutC+0LzQsNC90LTRiyDQsiDRgtC10LrRg9GJ0LXQvCDRgtC10YDQvNC40L3QsNC70LU6') + ' . $PROFILE') -ForegroundColor Cyan; Write-Host ''
}
catch { Write-Host ''; Write-Host (U '0J3QtSDRg9C00LDQu9C+0YHRjCDRg9GB0YLQsNC90L7QstC40YLRjCBLT01VUyBHaXQgSGVscGVyLg==') -ForegroundColor Red; Write-Host $_.Exception.Message; exit 1 }
