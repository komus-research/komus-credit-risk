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
function Invoke-Git {
    param([string]$Repo, [string[]]$Arguments, [switch]$AllowFailure)
    $old = $ErrorActionPreference
    try { $ErrorActionPreference = 'Continue'; $out = @(& git -C $Repo @Arguments 2>&1); $code = $LASTEXITCODE }
    finally { $ErrorActionPreference = $old }
    if ($null -eq $code) { $code = 0 }; $text = ($out | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    if ($code -ne 0 -and -not $AllowFailure) { Stop-Helper "Git failed: $text" }
    return [PSCustomObject]@{ ExitCode = [int]$code; Text = $text; Lines = @($out | ForEach-Object { [string]$_ }) }
}
function Invoke-Gh {
    param([string[]]$Arguments, [switch]$AllowFailure)
    $old = $ErrorActionPreference
    try { $ErrorActionPreference = 'Continue'; $out = @(& gh @Arguments 2>&1); $code = $LASTEXITCODE }
    finally { $ErrorActionPreference = $old }
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
    param([string]$Repo,[switch]$Preview)
    $head = Head-Info $Repo; $branch = (Invoke-Git $Repo @('branch','--show-current')).Text.Trim()
    if (-not (Is-Ancestor $Repo 'origin/main' 'HEAD')) { Stop-Helper "HEAD is not a safe descendant of origin/main. Nothing was pushed. Current: $branch $($head.Sha)" }
    if ($branch -ne 'main' -and -not (Confirm-Yes "Update origin/main to $($head.Short) - $($head.Subject)? [y/N]")) { Write-Host 'Cancelled. Remote main was not changed.' -ForegroundColor Yellow; return }
    if ($Preview) { Write-Host 'DRY RUN: a safe push to origin/main would be performed.' -ForegroundColor Cyan; return }
    if ($branch -eq 'main') { Invoke-Git $Repo @('push','origin','main') | Out-Null } else { Invoke-Git $Repo @('push','origin','HEAD:main') | Out-Null }
    Invoke-Git $Repo @('fetch','origin') | Out-Null
    if ((Head-Info $Repo 'origin/main').Sha -ne $head.Sha) { Stop-Helper 'origin/main SHA differs after push.' }
    if ($branch -ne 'main' -and [string]::IsNullOrWhiteSpace((Invoke-Git $Repo @('status','--porcelain')).Text)) {
        if ((Invoke-Git $Repo @('show-ref','--verify','--quiet','refs/heads/main') -AllowFailure).ExitCode -eq 0) {
            if ((Invoke-Git $Repo @('switch','main') -AllowFailure).ExitCode -eq 0) { Invoke-Git $Repo @('merge','--ff-only','origin/main') -AllowFailure | Out-Null }
        }
    }
    Write-Host 'DONE' -ForegroundColor Green; Write-Host "Working main updated: $($head.Short) - $($head.Subject)"
}
function Invoke-WorkingPush {
    param($Config,[string]$Message,[switch]$Preview)
    $repo = [string]$Config.working_repo
    Write-Host 'CHECKING working repository' -ForegroundColor Cyan
    Assert-Repo $repo ([string]$Config.working_remote_url) 'Working'
    Invoke-Git $repo @('fetch','origin') | Out-Null
    if ((Invoke-Git $repo @('show-ref','--verify','--quiet','refs/remotes/origin/main') -AllowFailure).ExitCode -ne 0) { Stop-Helper 'origin/main is missing.' }
    $head = Head-Info $repo; $branch = (Invoke-Git $repo @('branch','--show-current')).Text.Trim(); $status = Invoke-Git $repo @('-c','core.quotepath=false','status','--short')
    Write-Host "Repository: $repo"; Write-Host "Branch: $branch"; Write-Host "HEAD: $($head.Short) - $($head.Subject)"
    if ([string]::IsNullOrWhiteSpace($status.Text)) {
        if ($head.Sha -eq (Head-Info $repo 'origin/main').Sha) { Write-Host 'DONE: working main is already synchronized.' -ForegroundColor Green; return }
        Publish-Head $repo -Preview:$Preview; return
    }
    Write-Host 'Files to save:' -ForegroundColor Yellow; $status.Lines | ForEach-Object { Write-Host $_ }
    if ($Preview) { Write-Host 'DRY RUN: no staging, commit, or push was performed.' -ForegroundColor Cyan; return }
    if (-not (Confirm-Yes 'Save ALL listed changes? [y/N]')) { Write-Host 'Cancelled. Files were not changed.' -ForegroundColor Yellow; return }
    if ([string]::IsNullOrWhiteSpace($Message)) { $Message = Read-Host 'Commit message [Update KOMUS working version]'; if ([string]::IsNullOrWhiteSpace($Message)) { $Message = 'Update KOMUS working version' } }
    Write-Host "Files: $(@($status.Lines).Count)"; Write-Host "Commit: $Message"
    if (-not (Confirm-Yes 'Continue? [y/N]')) { Write-Host 'Cancelled. Files were not changed.' -ForegroundColor Yellow; return }
    Invoke-Git $repo @('add','--all') | Out-Null
    $check = Invoke-Git $repo @('diff','--cached','--check') -AllowFailure
    if ($check.ExitCode -ne 0) { Stop-Helper "git diff --cached --check failed: $($check.Text)" }
    Invoke-Git $repo @('commit','-m',$Message) | Out-Null
    Invoke-Git $repo @('fetch','origin') | Out-Null
    Publish-Head $repo
}
function New-IntegrationBranch { param([string]$Repo) return 'integration/credit-scoring-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0,6)) }
function Invoke-InstitutePush {
    param($Config,[string]$Message,[switch]$Preview)
    $work = [string]$Config.working_repo; $inst = [string]$Config.institute_repo; $base = [string]$Config.institute_base_branch; $prefix = ([string]$Config.institute_prefix).TrimEnd('/')
    Write-Host 'CHECKING source and Institute repositories' -ForegroundColor Cyan
    Assert-Repo $work ([string]$Config.working_remote_url) 'Working'; Invoke-Git $work @('fetch','origin') | Out-Null; $source = Head-Info $work 'origin/main'
    Assert-Repo $inst ([string]$Config.institute_remote_url) 'Institute'
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { Stop-Helper 'gh is not available in PATH.' }; Invoke-Gh @('auth','status') | Out-Null
    $dirty = Invoke-Git $inst @('-c','core.quotepath=false','status','--porcelain'); if (-not [string]::IsNullOrWhiteSpace($dirty.Text)) { Stop-Helper "Institute repository is dirty:`n$($dirty.Text)" }
    $remote = Invoke-Git $inst @('remote','get-url','credit-risk') -AllowFailure
    if ($remote.ExitCode -eq 0 -and (Normalize-Url $remote.Text) -ne (Normalize-Url ([string]$Config.working_remote_url))) { Stop-Helper 'credit-risk remote URL does not match.' }
    $branch = New-IntegrationBranch $inst
    if ($Preview) { Write-Host "DRY RUN: source $($source.Short); integration branch would be $branch; no repository state was changed." -ForegroundColor Cyan; return }
    Invoke-Git $inst @('fetch','origin') | Out-Null; Invoke-Git $inst @('switch',$base) | Out-Null; Invoke-Git $inst @('pull','--ff-only','origin',$base) | Out-Null
    if ($remote.ExitCode -ne 0) { Invoke-Git $inst @('remote','add','credit-risk',([string]$Config.working_remote_url)) | Out-Null }
    Invoke-Git $inst @('fetch','credit-risk','main') | Out-Null
    if ((Head-Info $inst 'credit-risk/main').Sha -ne $source.Sha) { Stop-Helper 'credit-risk/main does not equal working origin/main.' }
    Invoke-Git $inst @('switch','-c',$branch,$base) | Out-Null
    $oldEditor = $env:GIT_EDITOR; try { $env:GIT_EDITOR = 'true'; Invoke-Git $inst @('subtree','pull',('--prefix=' + $prefix),'credit-risk','main','--squash') | Out-Null } finally { if ($null -eq $oldEditor) { Remove-Item Env:GIT_EDITOR -ErrorAction SilentlyContinue } else { $env:GIT_EDITOR=$oldEditor } }
    $changed = Invoke-Git $inst @('diff','--name-only',($base + '...HEAD'))
    if ([string]::IsNullOrWhiteSpace($changed.Text)) { Invoke-Git $inst @('switch',$base) | Out-Null; Invoke-Git $inst @('branch','-d',$branch) | Out-Null; Write-Host 'DONE: Institute already contains the source.' -ForegroundColor Green; return }
    $outside = @($changed.Lines | Where-Object { -not $_.StartsWith($prefix + '/') }); if ($outside.Count) { Stop-Helper "Subtree changed paths outside $prefix/:`n$($outside -join "`n")" }
    $check = Invoke-Git $inst @('diff','--check',($base + '...HEAD')) -AllowFailure; if ($check.ExitCode -ne 0) { Stop-Helper "git diff --check failed: $($check.Text)" }
    if ([string]::IsNullOrWhiteSpace($Message)) { $Message = Read-Host "Integration comment [Synchronize credit-scoring - $($source.Short)]"; if ([string]::IsNullOrWhiteSpace($Message)) { $Message = "Synchronize credit-scoring - $($source.Short)" } }
    Write-Host "READY: source $($source.Sha); branch $branch; files $(@($changed.Lines).Count); scope $prefix/ only: YES" -ForegroundColor Green
    if (-not (Confirm-Yes 'Continue? [y/N]')) { Write-Host 'Cancelled. Integration branch was not pushed.' -ForegroundColor Yellow; return }
    Invoke-Git $inst @('push','-u','origin',$branch) | Out-Null
    $repoName = ([string]$Config.institute_remote_url).Replace('https://github.com/','').Replace('.git',''); $body = "Source repository: $($Config.working_remote_url)`nSource branch: main`nSource SHA: $($source.Sha)`nSource commit: $($source.Subject)`nChanges are limited to $prefix/."
    $url = (Invoke-Gh @('pr','create','--repo',$repoName,'--base',$base,'--head',$branch,'--title',$Message,'--body',$body)).Text.Trim(); Write-Host "PR created: $url" -ForegroundColor Green
    if (-not (Confirm-Yes "Merge PR into $base now? [y/N]")) { return }
    Invoke-Gh @('pr','merge',$url,'--merge','--delete-branch') | Out-Null; Invoke-Git $inst @('switch',$base) | Out-Null; Invoke-Git $inst @('pull','--ff-only','origin',$base) | Out-Null
    if (-not [string]::IsNullOrWhiteSpace((Invoke-Git $inst @('status','--porcelain')).Text)) { Stop-Helper 'Institute working tree is not clean after merge.' }
    Write-Host "DONE: credit-scoring synchronized. PR: $url" -ForegroundColor Green
}
try { $config=Read-Config; if ($Action -eq 'push') { Invoke-WorkingPush $config $Comment -Preview:$DryRun } else { Invoke-InstitutePush $config $Comment -Preview:$DryRun } }
catch { $m=[string]$_.Exception.Message; Write-Host ''; Write-Host 'STOP' -ForegroundColor Red; if ($m.StartsWith('KOMUS_HELPER: ')) { Write-Host $m.Substring(14) -ForegroundColor Yellow } else { Write-Host $m -ForegroundColor Yellow }; Write-Host 'No following actions were performed.'; exit 1 }
