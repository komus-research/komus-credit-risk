#
# Universal review helper v6
#
# Before Developer/Codex:
#   revs
# After Developer/Codex:
#   revp
# Explicitly cancel a snapshot:
#   revc
#
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('start', 'prepare', 'cancel')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$SchemaVersion = 6
$EmptyTreeSha = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'

function Stop-ReviewOperation {
    param([Parameter(Mandatory = $true)][string]$Message)
    throw "REVIEW_HELPER: $Message"
}

function Invoke-Git {    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$AllowFailure
    )
    $SavedPreference = $ErrorActionPreference
    $SavedEncoding = [Console]::OutputEncoding
    try {
        $ErrorActionPreference = 'Continue'
        [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
        $OutputLines = @(& git @Arguments 2>&1)
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $SavedPreference
        [Console]::OutputEncoding = $SavedEncoding
    }
    if ($null -eq $ExitCode) { $ExitCode = 0 }
    $Text = ($OutputLines | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    if ($ExitCode -ne 0 -and -not $AllowFailure) {
        $Short = @(
            $Text -split "`r?`n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -Last 4
        ) -join ' | '
        if ([string]::IsNullOrWhiteSpace($Short)) { $Short = "git завершился с кодом $ExitCode" }
        Stop-ReviewOperation "Git: $Short"
    }
    return [PSCustomObject]@{
        ExitCode = [int]$ExitCode
        Text = $Text
        Lines = @($OutputLines | ForEach-Object { [string]$_ })
    }
}

function Get-RepoRoot {
    $Result = Invoke-Git @('rev-parse', '--show-toplevel') -AllowFailure
    if ($Result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($Result.Text)) {
        Stop-ReviewOperation 'Не найден Git-репозиторий.'
    }
    return [System.IO.Path]::GetFullPath($Result.Text.Trim()).TrimEnd([char[]]@('\', '/'))
}

function Get-GitDir {
    $Result = Invoke-Git @('rev-parse', '--absolute-git-dir') -AllowFailure
    if ($Result.ExitCode -ne 0) {
        Stop-ReviewOperation 'Не удалось определить служебную папку Git.'
    }
    return [System.IO.Path]::GetFullPath($Result.Text.Trim()).TrimEnd([char[]]@('\', '/'))
}

function Get-CurrentBranch {
    $Result = Invoke-Git @('symbolic-ref', '--quiet', '--short', 'HEAD') -AllowFailure
    if ($Result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($Result.Text)) {
        Stop-ReviewOperation 'HEAD не привязан к ветке.'
    }
    return $Result.Text.Trim()
}

function Get-CurrentHead {
    $Result = Invoke-Git @('rev-parse', '--verify', 'HEAD') -AllowFailure
    if ($Result.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($Result.Text)) {
        return $Result.Text.Trim()
    }
    return $null
}

function Get-HeadTree {
    param([AllowNull()][string]$Head)
    if ([string]::IsNullOrWhiteSpace($Head)) { return $EmptyTreeSha }
    return (Invoke-Git @('rev-parse', "$Head^{tree}")).Text.Trim()
}

function Test-SamePath {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )
    return [string]::Equals(
        [System.IO.Path]::GetFullPath($Left).TrimEnd([char[]]@('\', '/')),
        [System.IO.Path]::GetFullPath($Right).TrimEnd([char[]]@('\', '/')),
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function New-WorkingTreeSnapshot {
    param([AllowNull()][string]$Head)
    $TemporaryIndex = Join-Path ([System.IO.Path]::GetTempPath()) ('review-helper-' + [guid]::NewGuid().ToString('N') + '.index')
    $PreviousIndex = $env:GIT_INDEX_FILE
    try {
        $env:GIT_INDEX_FILE = $TemporaryIndex
        if ([string]::IsNullOrWhiteSpace($Head)) {
            Invoke-Git @('read-tree', '--empty') | Out-Null
        }
        else {
            Invoke-Git @('read-tree', $Head) | Out-Null
        }
        Invoke-Git @('add', '-A', '--', '.') | Out-Null
        return (Invoke-Git @('write-tree')).Text.Trim()
    }
    finally {
        if ($null -eq $PreviousIndex) {
            Remove-Item Env:GIT_INDEX_FILE -ErrorAction SilentlyContinue
        }
        else {
            $env:GIT_INDEX_FILE = $PreviousIndex
        }
        Remove-Item -LiteralPath $TemporaryIndex -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath ($TemporaryIndex + '.lock') -Force -ErrorAction SilentlyContinue
    }
}

function Get-ChangedEntries {
    param(
        [Parameter(Mandatory = $true)][string]$BeforeTree,
        [Parameter(Mandatory = $true)][string]$AfterTree
    )
    $Result = Invoke-Git @('-c', 'core.quotepath=false', 'diff', '--name-status', '--no-renames', $BeforeTree, $AfterTree, '--')
    $Entries = @()
    foreach ($Line in $Result.Lines) {
        if ([string]::IsNullOrWhiteSpace($Line)) { continue }
        $Parts = $Line -split "`t", 2
        if ($Parts.Count -ne 2) {
            Stop-ReviewOperation "Не удалось разобрать Git diff entry: $Line"
        }
        $Entries += [PSCustomObject]@{
            Status = $Parts[0].Trim()
            Path = $Parts[1]
        }
    }
    return @($Entries)
}

function Write-JsonUtf8 {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
    [System.IO.File]::WriteAllText(
        $Path,
        ($Value | ConvertTo-Json -Depth 10),
        (New-Object System.Text.UTF8Encoding($true))
    )
}

function Read-ReviewState {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        Stop-ReviewOperation 'Review snapshot повреждён. Выполните revc, затем revs.'
    }
}

function Assert-StateMatchesRepository {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$GitDir
    )
    if (
        [int]$State.schema_version -ne $SchemaVersion -or
        -not (Test-SamePath ([string]$State.repo_root) $RepoRoot) -or
        -not (Test-SamePath ([string]$State.git_dir) $GitDir)
    ) {
        Stop-ReviewOperation 'Snapshot не соответствует текущему репозиторию. Выполните revc, затем revs.'
    }
}

function Get-ActiveReviewState {
    param(
        [Parameter(Mandatory = $true)][string]$HelperDir,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$GitDir,
        [switch]$AllowMissing
    )
    $StatePath = Join-Path $HelperDir 'active.json'
    $BackupPath = Join-Path $HelperDir 'active.backup.json'
    $Path = $null
    if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
        $Path = $StatePath
    }
    elseif (Test-Path -LiteralPath $BackupPath -PathType Leaf) {
        $Path = $BackupPath
        Copy-Item -LiteralPath $BackupPath -Destination $StatePath -Force
        Write-Host 'Активный review snapshot восстановлен из резервной копии.' -ForegroundColor Yellow
    }
    elseif ($AllowMissing) {
        return $null
    }
    else {
        return $null
    }
    $State = Read-ReviewState $Path
    Assert-StateMatchesRepository $State $RepoRoot $GitDir
    return $State
}

function Write-ActiveReviewState {
    param(
        [Parameter(Mandatory = $true)][string]$HelperDir,
        [Parameter(Mandatory = $true)]$State
    )
    New-Item -ItemType Directory -Path $HelperDir -Force | Out-Null
    Write-JsonUtf8 (Join-Path $HelperDir 'active.json') $State
    Write-JsonUtf8 (Join-Path $HelperDir 'active.backup.json') $State
}

function Remove-ActiveReviewState {
    param([Parameter(Mandatory = $true)][string]$HelperDir)
    Remove-Item -LiteralPath (Join-Path $HelperDir 'active.json') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $HelperDir 'active.backup.json') -Force -ErrorAction SilentlyContinue
}

function New-SyntheticCommit {
    param(
        [Parameter(Mandatory = $true)][string]$Tree,
        [AllowNull()][string]$Parent,
        [Parameter(Mandatory = $true)][string]$Message
    )
    $Arguments = @(
        '-c', 'user.name=Universal Review Helper',
        '-c', 'user.email=review-helper@localhost',
        'commit-tree', $Tree
    )
    if (-not [string]::IsNullOrWhiteSpace($Parent)) {
        $Arguments += @('-p', $Parent)
    }
    $Arguments += @('-m', $Message)
    return (Invoke-Git $Arguments).Text.Trim()
}

function Start-ReviewCycle {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$GitDir
    )
    $HelperDir = Join-Path $GitDir 'review-helper'
    $Existing = Get-ActiveReviewState $HelperDir $RepoRoot $GitDir -AllowMissing
    if ($null -ne $Existing) {
        Write-Host ''
        Write-Host 'Review snapshot уже активен и НЕ перезаписан.' -ForegroundColor Yellow
        Write-Host "Branch: $($Existing.branch)"
        Write-Host "Base HEAD: $($Existing.head)"
        Write-Host 'Сначала завершите его через revp или отмените через revc.'
        Write-Host ''
        return
    }
    $Branch = Get-CurrentBranch
    $Head = Get-CurrentHead
    $BaselineTree = New-WorkingTreeSnapshot $Head
    $InitialEntries = @(Get-ChangedEntries (Get-HeadTree $Head) $BaselineTree)
    $State = [ordered]@{
        schema_version = $SchemaVersion
        created_at = (Get-Date).ToString('o')
        repo_root = $RepoRoot
        git_dir = $GitDir
        branch = $Branch
        head = $Head
        baseline_tree = $BaselineTree
        dirty_count = $InitialEntries.Count
    }
    Write-ActiveReviewState $HelperDir $State
    $HeadLabel = if ($null -eq $Head) {
        '(первый commit ещё не создан)'
    }
    else {
        $Head.Substring(0, [Math]::Min(7, $Head.Length))
    }
    Write-Host ''
    Write-Host 'REVIEW START подтверждён' -ForegroundColor Green
    Write-Host "Branch: $Branch"
    Write-Host "HEAD: $HeadLabel"
    Write-Host "Исходных локальных изменений: $($InitialEntries.Count)"
    Write-Host 'Snapshot сохранён в двух копиях.'
    Write-Host 'Теперь можно запускать Developer/Codex.'
    Write-Host 'После его работы: revp' -ForegroundColor Cyan
    Write-Host ''
}

function Cancel-ReviewCycle {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$GitDir
    )
    $HelperDir = Join-Path $GitDir 'review-helper'
    $State = Get-ActiveReviewState $HelperDir $RepoRoot $GitDir -AllowMissing
    if ($null -eq $State) {
        Write-Host ''
        Write-Host 'Активного review snapshot нет.' -ForegroundColor Yellow
        Write-Host ''
        return
    }
    Remove-ActiveReviewState $HelperDir
    Write-Host ''
    Write-Host 'Review snapshot отменён.' -ForegroundColor Yellow
    Write-Host "Branch: $($State.branch)"
    Write-Host "Base HEAD: $($State.head)"
    Write-Host ''
}

function Complete-ReviewCycle {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$GitDir
    )
    $HelperDir = Join-Path $GitDir 'review-helper'
    $State = Get-ActiveReviewState $HelperDir $RepoRoot $GitDir -AllowMissing
    if ($null -eq $State) {
        Write-Host ''
        Write-Host 'Нет активного review snapshot. Сначала выполните revs.' -ForegroundColor Yellow
        Write-Host ''
        return
    }
    $CurrentBranch = Get-CurrentBranch
    $CurrentHead = Get-CurrentHead
    $StartHead = [string]$State.head

    if ([string]$State.branch -ne $CurrentBranch) {
        Stop-ReviewOperation 'После revs изменилась ветка. Вернитесь на исходную ветку или выполните revc.'
    }
    if (-not [string]::IsNullOrWhiteSpace($StartHead)) {
        if ([string]::IsNullOrWhiteSpace($CurrentHead)) {
            Stop-ReviewOperation 'После revs HEAD исчез. Snapshot сохранён.'
        }
        $AncestorCheck = Invoke-Git @('merge-base', '--is-ancestor', $StartHead, $CurrentHead) -AllowFailure
        if ($AncestorCheck.ExitCode -ne 0) {
            Stop-ReviewOperation 'После revs история ветки была переписана. Snapshot сохранён; отмените его через revc только осознанно.'
        }
    }

    $CurrentTree = New-WorkingTreeSnapshot $CurrentHead
    $Entries = @(Get-ChangedEntries ([string]$State.baseline_tree) $CurrentTree)
    if ($Entries.Count -eq 0) {
        Write-Host ''
        Write-Host 'Изменений после revs пока нет.' -ForegroundColor Yellow
        Write-Host 'Review snapshot ОСТАВЛЕН активным и не удалён.'
        Write-Host 'После работы Developer/Codex просто снова выполните revp.' -ForegroundColor Cyan
        Write-Host ''
        return
    }

    $DiffCheck = Invoke-Git @(
        '-c', 'core.quotepath=false', 'diff', '--check',
        [string]$State.baseline_tree, $CurrentTree, '--'
    ) -AllowFailure
    if ($DiffCheck.ExitCode -ne 0) {
        Write-Host ''
        Write-Host 'git diff --check: FAIL' -ForegroundColor Red
        if (-not [string]::IsNullOrWhiteSpace($DiffCheck.Text)) {
            Write-Host $DiffCheck.Text
        }
        Write-Host 'Review snapshot оставлен активным.'
        Write-Host ''
        return
    }

    $ReviewBranch = 'review/' + [string]$State.branch
    if (
        (Invoke-Git @('check-ref-format', ('refs/heads/' + $ReviewBranch)) -AllowFailure).ExitCode -ne 0
    ) {
        Stop-ReviewOperation 'Не удалось безопасно сформировать имя review-ветки.'
    }

    $Origin = Invoke-Git @('remote', 'get-url', 'origin') -AllowFailure
    if ($Origin.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($Origin.Text)) {
        Stop-ReviewOperation 'Remote origin не настроен. Review snapshot оставлен активным.'
    }

    $StartHeadTree = Get-HeadTree $StartHead
    $ReviewParent = $StartHead
    if ([string]$State.baseline_tree -ne $StartHeadTree) {
        $ReviewParent = New-SyntheticCommit (
            [string]$State.baseline_tree
        ) $StartHead 'Review baseline (pre-existing local changes)'
    }
    $ReviewCommit = New-SyntheticCommit $CurrentTree $ReviewParent 'Review post-snapshot changes'
    $ReviewRange = $ReviewParent + '..' + $ReviewCommit
    $PushSpec = $ReviewCommit + ':refs/heads/' + $ReviewBranch
    $Push = Invoke-Git @(
        'push', 'origin', $PushSpec,
        ('--force-with-lease=refs/heads/' + $ReviewBranch)
    ) -AllowFailure
    if ($Push.ExitCode -ne 0) {
        Stop-ReviewOperation 'Не удалось отправить review-ветку в origin. Review snapshot оставлен активным.'
    }

    $Completed = [ordered]@{
        schema_version = $SchemaVersion
        completed_at = (Get-Date).ToString('o')
        source_branch = [string]$State.branch
        base_head = $StartHead
        current_head = $CurrentHead
        review_branch = $ReviewBranch
        review_commit = $ReviewCommit
        review_range = $ReviewRange
        changed_files = $Entries.Count
    }
    Write-JsonUtf8 (Join-Path $HelperDir 'last-completed.json') $Completed
    Remove-ActiveReviewState $HelperDir

    $RepoName = Split-Path -Leaf $RepoRoot
    Write-Host ''
    Write-Host '========================================'
    Write-Host 'REVIEW READY' -ForegroundColor Green
    Write-Host ''
    Write-Host "Repository: $RepoName"
    Write-Host "Source branch: $($State.branch)"
    Write-Host "Review branch: $ReviewBranch"
    Write-Host "Base HEAD: $StartHead"
    Write-Host "Current HEAD: $CurrentHead"
    Write-Host "Review commit: $ReviewCommit"
    Write-Host "Review range: $ReviewRange"
    Write-Host ''
    Write-Host "Files after revs: $($Entries.Count)"
    foreach ($Entry in $Entries) {
        Write-Host "  $($Entry.Status)  $($Entry.Path)"
    }
    Write-Host ''
    Write-Host 'git diff --check: PASS'
    Write-Host 'Push: PASS'
    Write-Host ''
    Write-Host 'REVIEWER MESSAGE:' -ForegroundColor Cyan
    Write-Host ''
    Write-Host 'Проверь изменения в ветке:'
    Write-Host $ReviewBranch
    Write-Host ''
    Write-Host 'Review range:'
    Write-Host $ReviewRange
    Write-Host ''
    Write-Host 'Scope:'
    Write-Host 'только изменения после review snapshot.'
    Write-Host ''
    Write-Host 'Проверь:'
    Write-Host '- соответствие задаче;'
    Write-Host '- scope;'
    Write-Host '- diff;'
    Write-Host '- отсутствие unrelated changes;'
    Write-Host '- ошибки/регрессии.'
    Write-Host ''
    Write-Host 'Вердикт:'
    Write-Host 'ACCEPT или FIX'
    Write-Host '+ BLOCKER / MAJOR / MINOR / NOTE при наличии замечаний.'
    Write-Host '========================================'
    Write-Host ''
}

function Invoke-Main {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Stop-ReviewOperation 'Git не найден в PATH.'
    }
    $RepoRoot = Get-RepoRoot
    $OriginalLocation = Get-Location
    try {
        Set-Location -LiteralPath $RepoRoot
        $GitDir = Get-GitDir
        switch ($Action) {
            'start' { Start-ReviewCycle $RepoRoot $GitDir }
            'prepare' { Complete-ReviewCycle $RepoRoot $GitDir }
            'cancel' { Cancel-ReviewCycle $RepoRoot $GitDir }
        }
    }
    finally {
        Set-Location -LiteralPath $OriginalLocation
    }
}

try {
    Invoke-Main
}
catch {
    $Message = [string]$_.Exception.Message
    Write-Host ''
    if ($Message.StartsWith('REVIEW_HELPER: ')) {
        Write-Host $Message.Substring(15) -ForegroundColor Yellow
    }
    else {
        Write-Host 'Не удалось выполнить review helper.' -ForegroundColor Red
        Write-Host $Message
    }
    Write-Host ''
}
