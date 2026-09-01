[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('push', 'institute')][string]$Action,
    [AllowEmptyString()][string]$Comment,
    [string]$ConfigPath = (Join-Path $env:USERPROFILE '.komus-git\config.json'),
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

function Stop-Helper { param([string]$Message) throw "KOMUS_HELPER: $Message" }
function U { param([string]$Base64) return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Base64)) }
function Invoke-Git {
    param([string]$Repo, [string[]]$Arguments, [switch]$AllowFailure)
    $old = $ErrorActionPreference; $oldConsoleEncoding = [Console]::OutputEncoding; $oldOutputEncoding = $OutputEncoding
    try {
        $ErrorActionPreference = 'Continue'; [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false); $OutputEncoding = [Console]::OutputEncoding
        $out = @(& git -C $Repo -c 'i18n.logOutputEncoding=utf-8' @Arguments 2>&1); $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $old; [Console]::OutputEncoding = $oldConsoleEncoding; $OutputEncoding = $oldOutputEncoding }
    if ($null -eq $code) { $code = 0 }; $text = ($out | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    if ($code -ne 0 -and -not $AllowFailure) { Stop-Helper ((U '0KLQtdGF0L3QuNGH0LXRgdC60LDRjyDQv9GA0LjRh9C40L3QsCBHaXQ6') + " $text") }
    return [PSCustomObject]@{ ExitCode = [int]$code; Text = $text; Lines = @($out | ForEach-Object { [string]$_ }) }
}
function Resolve-GhPath {
    param([string]$ConfiguredPath)
    $command = Get-Command gh -ErrorAction SilentlyContinue
    if ($command -and (Test-Path -LiteralPath $command.Source -PathType Leaf)) { return $command.Source }
    foreach ($candidate in @($ConfiguredPath, (Join-Path $env:ProgramFiles 'GitHub CLI\gh.exe'), (Join-Path ${env:ProgramFiles(x86)} 'GitHub CLI\gh.exe'))) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return [IO.Path]::GetFullPath($candidate) }
    }
    return $null
}
function Invoke-Gh {
    param([string]$GhPath, [string[]]$Arguments, [switch]$AllowFailure)
    $old = $ErrorActionPreference; $oldConsoleEncoding = [Console]::OutputEncoding; $oldOutputEncoding = $OutputEncoding
    try {
        $ErrorActionPreference = 'Continue'; [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false); $OutputEncoding = [Console]::OutputEncoding
        $out = @(& $GhPath @Arguments 2>&1); $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $old; [Console]::OutputEncoding = $oldConsoleEncoding; $OutputEncoding = $oldOutputEncoding }
    if ($null -eq $code) { $code = 0 }; $text = ($out | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    if ($code -ne 0 -and -not $AllowFailure) { Stop-Helper "GitHub CLI failed: $text" }
    return [PSCustomObject]@{ ExitCode = [int]$code; Text = $text }
}
function Read-Config {
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { Stop-Helper "Config not found: $ConfigPath. Run the installer." }
    try { $c = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { Stop-Helper "Cannot read config: $($_.Exception.Message)" }
    foreach ($key in @('working_repo','institute_repo','working_remote_url','institute_remote_url','institute_base_branch','institute_prefix')) { if ([string]::IsNullOrWhiteSpace([string]$c.$key)) { Stop-Helper "Config field missing: $key" } }
    return $c
}
function Normalize-Url { param([string]$Url) return $Url.Trim().TrimEnd('/').Replace('.git','').ToLowerInvariant() }
function Assert-Repo {
    param([string]$Repo,[string]$ExpectedOrigin,[string]$Label)
    if (-not (Test-Path -LiteralPath $Repo -PathType Container)) { Stop-Helper "$Label repository is missing: $Repo" }
    $inside = Invoke-Git $Repo @('rev-parse','--is-inside-work-tree') -AllowFailure
    if ($inside.ExitCode -ne 0 -or $inside.Text.Trim() -ne 'true') { Stop-Helper "$Label path is not a Git repository: $Repo" }
    $origin = Invoke-Git $Repo @('remote','get-url','origin') -AllowFailure
    if ($origin.ExitCode -ne 0 -or (Normalize-Url $origin.Text) -ne (Normalize-Url $ExpectedOrigin)) { Stop-Helper "$Label origin does not match the configured repository." }
}
function Confirm-Yes { param([string]$Prompt) return (Read-Host $Prompt) -match '^(?i:y|yes)$' }
function Head-Info {
    param([string]$Repo,[string]$Ref='HEAD')
    $sha = (Invoke-Git $Repo @('rev-parse','--verify',$Ref)).Text.Trim()
    $subject = (Invoke-Git $Repo @('log','-1','--format=%s',$Ref)).Text.Trim()
    return [PSCustomObject]@{ Sha=$sha; Short=$sha.Substring(0,[Math]::Min(7,$sha.Length)); Subject=$subject }
}
function Is-Ancestor { param([string]$Repo,[string]$A,[string]$B) return (Invoke-Git $Repo @('merge-base','--is-ancestor',$A,$B) -AllowFailure).ExitCode -eq 0 }
function Publish-Head {
    param([string]$Repo,[switch]$Preview,[switch]$AlreadyConfirmed)
    $head = Head-Info $Repo; $branch = (Invoke-Git $Repo @('branch','--show-current')).Text.Trim()
    if (-not (Is-Ancestor $Repo 'origin/main' 'HEAD')) { Stop-Helper "HEAD is not a safe descendant of origin/main. Nothing was pushed. Current: $branch $($head.Sha)" }
    if ($branch -ne 'main' -and -not $AlreadyConfirmed -and -not (Confirm-Yes ((U '0J/RgNC+0LTQvtC70LbQuNGC0Yw/IFt5L05d')))) { Write-Host (U '0J7RgtC80LXQvdC10L3Qvi4g0JjQt9C80LXQvdC10L3QuNGPINC90LUg0YHQvtGF0YDQsNC90LXQvdGLLg==') -ForegroundColor Yellow; return }
    if ($Preview) { Write-Host (U '0KHRg9GF0L7QuSDQt9Cw0L/Rg9GB0Lo6INCx0LXQt9C+0L/QsNGB0L3Ri9C5IHB1c2gg0LIgb3JpZ2luL21haW4g0L3QtSDQstGL0L/QvtC70L3Rj9C70YHRjy4=') -ForegroundColor Cyan; return }
    if ($branch -eq 'main') { Invoke-Git $Repo @('push','origin','main') | Out-Null } else { Invoke-Git $Repo @('push','origin','HEAD:main') | Out-Null }
    Invoke-Git $Repo @('fetch','origin') | Out-Null
    if ((Head-Info $Repo 'origin/main').Sha -ne $head.Sha) { Stop-Helper 'origin/main SHA differs after push.' }
    if ($branch -ne 'main' -and [string]::IsNullOrWhiteSpace((Invoke-Git $Repo @('status','--porcelain')).Text)) {
        if ((Invoke-Git $Repo @('show-ref','--verify','--quiet','refs/heads/main') -AllowFailure).ExitCode -eq 0) {
            if ((Invoke-Git $Repo @('switch','main') -AllowFailure).ExitCode -eq 0) { Invoke-Git $Repo @('merge','--ff-only','origin/main') -AllowFailure | Out-Null }
        }
    }
    Write-Host (U '0JPQntCi0J7QktCe') -ForegroundColor Green; Write-Host ((U '0KDQsNCx0L7Rh9Cw0Y8g0LLQtdGC0LrQsCBtYWluINC+0LHQvdC+0LLQu9C10L3QsDo=') + " $($head.Short) - $($head.Subject)")
}
function Invoke-WorkingPush {
    param($Config,[string]$Message,[switch]$Preview)
    $repo = [string]$Config.working_repo
    Write-Host (U '0J/QoNCe0JLQldCg0JrQkA==') -ForegroundColor Cyan; Write-Host (U '0J/RgNC+0LLQtdGA0Y/RjiDRgNCw0LHQvtGH0LjQuSDRgNC10L/QvtC30LjRgtC+0YDQuNC5Li4u')
    Assert-Repo $repo ([string]$Config.working_remote_url) 'Working'
    Invoke-Git $repo @('fetch','origin') | Out-Null
    if ((Invoke-Git $repo @('show-ref','--verify','--quiet','refs/remotes/origin/main') -AllowFailure).ExitCode -ne 0) { Stop-Helper 'origin/main is missing.' }
    $head = Head-Info $repo; $branch = (Invoke-Git $repo @('branch','--show-current')).Text.Trim(); $status = Invoke-Git $repo @('-c','core.quotepath=false','status','--short')
    Write-Host ((U '0KDQsNCx0L7Rh9C40Lkg0YDQtdC/0L7Qt9C40YLQvtGA0LjQuTo=') + " $repo"); Write-Host ((U '0JLQtdGC0LrQsDo=') + " $branch"); Write-Host ((U '0KLQtdC60YPRidC40LkgY29tbWl0Og==') + " $($head.Short) - $($head.Subject)")
    if ([string]::IsNullOrWhiteSpace($status.Text)) {
        if ($head.Sha -eq (Head-Info $repo 'origin/main').Sha) { Write-Host (U '0JPQntCi0J7QktCe') -ForegroundColor Green; Write-Host (U '0KDQsNCx0L7Rh9Cw0Y8g0LLQtdGC0LrQsCBtYWluINGD0LbQtSDRgdC40L3RhdGA0L7QvdC40LfQuNGA0L7QstCw0L3QsC4='); return }
        Publish-Head $repo -Preview:$Preview; return
    }
    Write-Host (U '0JHRg9C00YPRgiDRgdC+0YXRgNCw0L3QtdC90Ys6') -ForegroundColor Yellow; $status.Lines | ForEach-Object { Write-Host $_ }
    if ($Preview) { Write-Host (U '0KHRg9GF0L7QuSDQt9Cw0L/Rg9GB0Lo6IHN0YWdpbmcsIGNvbW1pdCDQuCBwdXNoINC90LUg0LLRi9C/0L7Qu9C90Y/Qu9C40YHRjC4=') -ForegroundColor Cyan; return }
    if ([string]::IsNullOrWhiteSpace($Message)) { $defaultMessage = U '0J7QsdC90L7QstC40YLRjCDRgNCw0LHQvtGH0YPRjiDQstC10YDRgdC40Y4gS09NVVM='; $Message = Read-Host ((U '0JrQvtC80LzQtdC90YLQsNGA0LjQuQ==') + " [$defaultMessage]"); if ([string]::IsNullOrWhiteSpace($Message)) { $Message = $defaultMessage } }
    Write-Host ((U '0JrQvtC80LzQtdC90YLQsNGA0LjQuQ==') + ": $Message")
    if (-not (Confirm-Yes (U '0KHQvtGF0YDQsNC90LjRgtGMINC4INC+0YLQv9GA0LDQstC40YLRjCDQsiBtYWluPyBbeS9OXQ=='))) { Write-Host (U '0J7RgtC80LXQvdC10L3Qvi4g0JjQt9C80LXQvdC10L3QuNGPINC90LUg0YHQvtGF0YDQsNC90LXQvdGLLg==') -ForegroundColor Yellow; return }
    Invoke-Git $repo @('add','--all') | Out-Null
    $check = Invoke-Git $repo @('diff','--cached','--check') -AllowFailure
    if ($check.ExitCode -ne 0) { Stop-Helper "git diff --cached --check failed: $($check.Text)" }
    Invoke-Git $repo @('commit','-m',$Message) | Out-Null
    Invoke-Git $repo @('fetch','origin') | Out-Null
    Publish-Head $repo -AlreadyConfirmed
}
function New-IntegrationBranch { param([string]$Repo) return 'integration/credit-scoring-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0,6)) }
function Clear-IntegrationBranch {
    param([string]$Repo,[string]$Base,[string]$Branch)
    $switch = Invoke-Git $Repo @('switch',$Base) -AllowFailure
    if ($switch.ExitCode -ne 0) { Write-Host (U '0J3QtSDRg9C00LDQu9C+0YHRjCDQstC10YDQvdGD0YLRjCDRgNC10L/QvtC30LjRgtC+0YDQuNC5INCY0L3RgdGC0LjRgtGD0YLQsCDQvdCwIERhdGFfS29tdXMu') -ForegroundColor Yellow; return $false }
    $delete = Invoke-Git $Repo @('branch','-D',$Branch) -AllowFailure
    if ($delete.ExitCode -ne 0) { Write-Host ((U '0J3QtSDRg9C00LDQu9C+0YHRjCDQstC10YDQvdGD0YLRjCDRgNC10L/QvtC30LjRgtC+0YDQuNC5INCY0L3RgdGC0LjRgtGD0YLQsCDQvdCwIERhdGFfS29tdXMu') + " $($delete.Text)") -ForegroundColor Yellow; return $false }
    Write-Host ((U '0JLRgNC10LzQtdC90L3QsNGPIGludGVncmF0aW9uIGJyYW5jaCDRg9C00LDQu9C10L3QsDo=') + " $Branch") -ForegroundColor Yellow
    return $true
}
function Invoke-InstitutePush {
    param($Config,[string]$Message,[switch]$Preview)
    $work = [string]$Config.working_repo; $inst = [string]$Config.institute_repo; $base = [string]$Config.institute_base_branch; $prefix = ([string]$Config.institute_prefix).TrimEnd('/')
    Write-Host (U '0J/QoNCe0JLQldCg0JrQkA==') -ForegroundColor Cyan; Write-Host (U '0J/RgNC+0LLQtdGA0Y/RjiDRgNCw0LHQvtGH0LjQuSDRgNC10L/QvtC30LjRgtC+0YDQuNC5INC4INGA0LXQv9C+0LfQuNGC0YPRgtC+0YDQuNC5INCY0L3RgdGC0LjRgtGD0YLQsC4uLg==')
    Assert-Repo $work ([string]$Config.working_remote_url) 'Working'; Invoke-Git $work @('fetch','origin') | Out-Null; $source = Head-Info $work 'origin/main'
    Assert-Repo $inst ([string]$Config.institute_remote_url) 'Institute'
    $ghPath = Resolve-GhPath ([string]$Config.gh_path)
    if ([string]::IsNullOrWhiteSpace($ghPath)) { Stop-Helper ((U 'R2l0SHViIENMSSDQvdC1INC90LDQudC00LXQvS4=') + ' ' + (U '0J7QttC40LTQsNC70YHRjywg0L3QsNC/0YDQuNC80LXRgDo=') + ' C:\Program Files\GitHub CLI\gh.exe') }
    Invoke-Gh $ghPath @('auth','status') | Out-Null
    $dirty = Invoke-Git $inst @('-c','core.quotepath=false','status','--porcelain'); if (-not [string]::IsNullOrWhiteSpace($dirty.Text)) { Stop-Helper "Institute repository is dirty:`n$($dirty.Text)" }
    $remote = Invoke-Git $inst @('remote','get-url','credit-risk') -AllowFailure
    if ($remote.ExitCode -eq 0 -and (Normalize-Url $remote.Text) -ne (Normalize-Url ([string]$Config.working_remote_url))) { Stop-Helper 'credit-risk remote URL does not match.' }
    $branch = New-IntegrationBranch $inst
    if ($Preview) { Write-Host ((U '0KHRg9GF0L7QuSDQt9Cw0L/Rg9GB0Lo6INC40YHRgtC+0YfQvdC40Lo=') + " $($source.Short); " + (U '0LLQtdGC0LrQsCDQuNC90YLQtdCz0YDQsNGG0LjQuA==') + " $branch; " + (U '0YHQvtGB0YLQvtGP0L3QuNC1INGA0LXQv9C+0LfQuNGC0L7RgNC40Y8g0L3QtSDQuNC30LzQtdC90LXQvdC+Lg==')) -ForegroundColor Cyan; return }
    $integrationCreated = $false; $pushed = $false
    try {
        Invoke-Git $inst @('fetch','origin') | Out-Null; Invoke-Git $inst @('switch',$base) | Out-Null; Invoke-Git $inst @('pull','--ff-only','origin',$base) | Out-Null
        if ($remote.ExitCode -ne 0) { Invoke-Git $inst @('remote','add','credit-risk',([string]$Config.working_remote_url)) | Out-Null }
        Invoke-Git $inst @('fetch','credit-risk','main') | Out-Null
        if ((Head-Info $inst 'credit-risk/main').Sha -ne $source.Sha) { Stop-Helper 'credit-risk/main does not equal working origin/main.' }
        Invoke-Git $inst @('switch','-c',$branch,$base) | Out-Null; $integrationCreated = $true
        $oldEditor = $env:GIT_EDITOR; try { $env:GIT_EDITOR = 'true'; Invoke-Git $inst @('subtree','pull',('--prefix=' + $prefix),'credit-risk','main','--squash') | Out-Null } finally { if ($null -eq $oldEditor) { Remove-Item Env:GIT_EDITOR -ErrorAction SilentlyContinue } else { $env:GIT_EDITOR=$oldEditor } }
        $changed = Invoke-Git $inst @('-c','core.quotepath=false','diff','--name-only',($base + '...HEAD'))
        if ([string]::IsNullOrWhiteSpace($changed.Text)) { Clear-IntegrationBranch $inst $base $branch | Out-Null; $integrationCreated = $false; Write-Host (U '0JPQntCi0J7QktCe') -ForegroundColor Green; Write-Host (U '0KDQtdC/0L7Qt9C40YLQvtGA0LjQuSDQmNC90YHRgtC40YLRg9GC0LAg0YPQttC1INGB0L7QtNC10YDQttC40YIg0LjRgdGC0L7Rh9C90LjQui4='); return }
        $outside = @($changed.Lines | Where-Object { -not $_.StartsWith($prefix + '/') }); if ($outside.Count) { Stop-Helper ((U '0J7QsdC90LDRgNGD0LbQtdC90Ysg0LjQt9C80LXQvdC10L3QuNGPINCy0L3QtSBjcmVkaXQtc2NvcmluZzo=') + "`n$($outside -join "`n")") }
        $check = Invoke-Git $inst @('diff','--check',($base + '...HEAD')) -AllowFailure; if ($check.ExitCode -ne 0) { Stop-Helper "git diff --check failed: $($check.Text)" }
        if ([string]::IsNullOrWhiteSpace($Message)) { $defaultMessage = (U '0KHQuNC90YXRgNC+0L3QuNC30LjRgNC+0LLQsNGC0YwgY3JlZGl0LXNjb3Jpbmc=') + " - $($source.Short)"; $Message = Read-Host ((U '0JrQvtC80LzQtdC90YLQsNGA0LjQuSDQuNC90YLQtdCz0YDQsNGG0LjQuA==') + " [$defaultMessage]"); if ([string]::IsNullOrWhiteSpace($Message)) { $Message = $defaultMessage } }
        Write-Host (U '0JPQntCi0J7QktCeINCaINCe0KLQn9Cg0JDQktCa0JU=') -ForegroundColor Green; Write-Host ((U '0JjRgdGC0L7Rh9C90LjQujo=') + " $($source.Sha)"); Write-Host ((U '0JLQtdGC0LrQsCDQuNC90YLQtdCz0YDQsNGG0LjQuDo=') + " $branch"); Write-Host ((U '0JjQt9C80LXQvdC10L3QviDRhNCw0LnQu9C+0LI6') + " $(@($changed.Lines).Count)"); Write-Host (U '0KLQvtC70YzQutC+IGNyZWRpdC1zY29yaW5nLzog0JTQkA==')
        if (-not (Confirm-Yes (U '0KHQvtC30LTQsNCy0YwgUFI/IFt5L05d'))) { Clear-IntegrationBranch $inst $base $branch | Out-Null; $integrationCreated = $false; Write-Host (U '0J7RgtC80LXQvdC10L3Qvi4g0JLRgNC10LzQtdC90L3QsNGPIGludGVncmF0aW9uIGJyYW5jaCDRg9C00LDQu9C10L3QsC4=') -ForegroundColor Yellow; return }
        Invoke-Git $inst @('push','-u','origin',$branch) | Out-Null; $pushed = $true
        $repoName = ([string]$Config.institute_remote_url).Replace('https://github.com/','').Replace('.git',''); $body = "Source repository: $($Config.working_remote_url)`nSource branch: main`nSource SHA: $($source.Sha)`nSource commit: $($source.Subject)`nChanges are limited to $prefix/."
        $url = (Invoke-Gh $ghPath @('pr','create','--repo',$repoName,'--base',$base,'--head',$branch,'--title',$Message,'--body',$body)).Text.Trim(); Write-Host ((U 'UFIg0YHQvtC30LTQsNC9Og==') + " $url") -ForegroundColor Green
        if (-not (Confirm-Yes (U '0KHQu9C40YLRjCBQUiDQsiBEYXRhX0tvbXVzINGB0LXQudGH0LDRgT8gW3kvTl0='))) { return }
        Invoke-Gh $ghPath @('pr','merge',$url,'--merge','--delete-branch') | Out-Null; Invoke-Git $inst @('switch',$base) | Out-Null; Invoke-Git $inst @('pull','--ff-only','origin',$base) | Out-Null
        if (-not [string]::IsNullOrWhiteSpace((Invoke-Git $inst @('status','--porcelain')).Text)) { Stop-Helper 'Institute working tree is not clean after merge.' }
        Write-Host (U '0JPQntCi0J7QktCe') -ForegroundColor Green; Write-Host ((U 'Y3JlZGl0LXNjb3Jpbmcg0YHQuNC90YXRgNC+0L3QuNC30LjRgNC+0LLQsNC9Lg==') + " PR: $url")
    }
    catch {
        if ($integrationCreated -and -not $pushed) { Clear-IntegrationBranch $inst $base $branch | Out-Null }
        throw
    }
}
try { $config=Read-Config; if ($Action -eq 'push') { Invoke-WorkingPush $config $Comment -Preview:$DryRun } else { Invoke-InstitutePush $config $Comment -Preview:$DryRun } }
catch { $m=[string]$_.Exception.Message; if ($m.StartsWith('KOMUS_HELPER: ')) { $m=$m.Substring(14) }; Write-Host ''; Write-Host (U '0J7QodCi0JDQndCe0JLQm9CV0J3Qng==') -ForegroundColor Red; Write-Host ((U '0J/RgNC40YfQuNC90LA6') + ' ' + (U '0J7Qv9C10YDQsNGG0LjRjyDQvdC1INCy0YvQv9C+0LvQvdC10L3QsC4=')) -ForegroundColor Yellow; Write-Host ((U '0KLQtdGF0L3QuNGH0LXRgdC60LjQtSDQtNC10YLQsNC70Lg6') + " $m") -ForegroundColor DarkYellow; Write-Host (U '0KHQu9C10LTRg9GO0YnQtdC1INC00LXQudGB0YLQstC40LU6INGD0YHRgtGA0LDQvdC40YLQtSDRg9C60LDQt9Cw0L3QvdGD0Y4g0L/RgNC40YfQuNC90YMg0Lgg0L/QvtCy0YLQvtGA0LjRgtC1INC60L7QvNCw0L3QtNGDLg=='); exit 1 }
