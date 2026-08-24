'''Запуск
.\scripts\make_review_bundle.ps1
'''

$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$ProjectRoot = (& git rev-parse --show-toplevel 2>$null).Trim()

if (-not $ProjectRoot) {
    throw "Git repository not found."
}

Set-Location $ProjectRoot

$BuildDir = Join-Path $ProjectRoot ".review_bundle_build"
$FilesDir = Join-Path $BuildDir "files"
$EvidenceDir = Join-Path $BuildDir "evidence"
$ZipPath = Join-Path $ProjectRoot "REVIEW_BUNDLE.zip"

$MaxFileSizeBytes = 100MB

function Invoke-CapturedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(Mandatory = $true)]
        [string]$OutputFile,
        [switch]$AllowFailure
    )

    $Result = & cmd.exe /d /c "$Command 2>&1"
    $ExitCode = $LASTEXITCODE

    @(
        "COMMAND: $Command"
        "EXIT_CODE: $ExitCode"
        ""
        $Result
    ) | Set-Content -Path $OutputFile -Encoding UTF8

    if (-not $AllowFailure -and $ExitCode -ne 0) {
        throw "Command failed: $Command"
    }

    return $ExitCode
}

function Test-ExcludedPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )

    $Normalized = $RelativePath.Replace("\", "/")

    $ExcludedPrefixes = @(
        ".git/",
        ".venv/",
        "venv/",
        ".review_bundle_build/",
        ".review_stage6_build/",
        ".pytest_cache/",
        ".mypy_cache/",
        ".ruff_cache/",
        "__pycache__/",
        ".ipynb_checkpoints/"
    )

    foreach ($Prefix in $ExcludedPrefixes) {
        if ($Normalized.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    $ExcludedFiles = @(
        "REVIEW_BUNDLE.zip",
        "REVIEW_STAGE6_PRERUN.zip",
        "REVIEW_STAGE6_RESULTS.zip"
    )

    foreach ($FileName in $ExcludedFiles) {
        if ($Normalized.Equals($FileName, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    return $false
}

if (Test-Path $BuildDir) {
    Remove-Item $BuildDir -Recurse -Force
}

if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

New-Item -ItemType Directory -Path $FilesDir -Force | Out-Null
New-Item -ItemType Directory -Path $EvidenceDir -Force | Out-Null

$Branch = (& git branch --show-current).Trim()
$Head = (& git rev-parse HEAD).Trim()

$Branch | Set-Content (Join-Path $EvidenceDir "BRANCH.txt") -Encoding UTF8
$Head | Set-Content (Join-Path $EvidenceDir "HEAD.txt") -Encoding UTF8

Invoke-CapturedCommand `
    -Command "git status --short --branch" `
    -OutputFile (Join-Path $EvidenceDir "GIT_STATUS.txt") | Out-Null

Invoke-CapturedCommand `
    -Command "git log -5 --oneline --decorate" `
    -OutputFile (Join-Path $EvidenceDir "GIT_LOG.txt") | Out-Null

Invoke-CapturedCommand `
    -Command "git diff HEAD --stat" `
    -OutputFile (Join-Path $EvidenceDir "GIT_DIFF_STAT.txt") | Out-Null

Invoke-CapturedCommand `
    -Command "git diff HEAD --no-ext-diff" `
    -OutputFile (Join-Path $EvidenceDir "GIT_DIFF.patch") | Out-Null

Invoke-CapturedCommand `
    -Command "git diff --cached --no-ext-diff" `
    -OutputFile (Join-Path $EvidenceDir "GIT_DIFF_STAGED.patch") | Out-Null

Invoke-CapturedCommand `
    -Command "git diff --no-ext-diff" `
    -OutputFile (Join-Path $EvidenceDir "GIT_DIFF_UNSTAGED.patch") | Out-Null

Invoke-CapturedCommand `
    -Command "git diff --check" `
    -OutputFile (Join-Path $EvidenceDir "GIT_DIFF_CHECK.txt") | Out-Null

$ChangedTracked = @(
    & git -c core.quotepath=false diff HEAD --name-only --diff-filter=ACMRTUXB
) | Where-Object { $_ -and $_.Trim() }

$Untracked = @(
    & git -c core.quotepath=false ls-files --others --exclude-standard
) | Where-Object { $_ -and $_.Trim() }

$AllFiles = @(
    $ChangedTracked
    $Untracked
) |
    Sort-Object -Unique

$Included = New-Object System.Collections.Generic.List[string]
$Skipped = New-Object System.Collections.Generic.List[string]
$Manifest = New-Object System.Collections.Generic.List[string]

foreach ($RelativePath in $AllFiles) {
    if (Test-ExcludedPath $RelativePath) {
        $Skipped.Add("$RelativePath`tEXCLUDED")
        continue
    }

    $SourcePath = Join-Path $ProjectRoot $RelativePath

    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        $Skipped.Add("$RelativePath`tNOT_PRESENT_OR_DELETED")
        continue
    }

    $FileInfo = Get-Item -LiteralPath $SourcePath

    if ($FileInfo.Length -gt $MaxFileSizeBytes) {
        $Skipped.Add("$RelativePath`tTOO_LARGE`t$($FileInfo.Length)")
        continue
    }

    $DestinationPath = Join-Path $FilesDir $RelativePath
    $DestinationParent = Split-Path $DestinationPath -Parent

    New-Item -ItemType Directory -Path $DestinationParent -Force | Out-Null
    Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force

    $Hash = (Get-FileHash -LiteralPath $SourcePath -Algorithm SHA256).Hash

    $Included.Add($RelativePath)
    $Manifest.Add(
        "$RelativePath`t$($FileInfo.Length)`t$Hash"
    )
}

@(
    "PROJECT_ROOT: $ProjectRoot"
    "BRANCH: $Branch"
    "HEAD: $Head"
    "CREATED_AT: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')"
    ""
    "INCLUDED_FILES:"
    $Included
) | Set-Content (Join-Path $EvidenceDir "REVIEW_INFO.txt") -Encoding UTF8

$Manifest |
    Set-Content (Join-Path $EvidenceDir "FILE_MANIFEST_SHA256.txt") -Encoding UTF8

$Skipped |
    Set-Content (Join-Path $EvidenceDir "SKIPPED_FILES.txt") -Encoding UTF8

if ((Test-Path "pyproject.toml") -and (Test-Path "uv.lock")) {
    $UvRelevant = $AllFiles | Where-Object {
        $_ -eq "pyproject.toml" -or $_ -eq "uv.lock"
    }

    if ($UvRelevant) {
        Invoke-CapturedCommand `
            -Command "uv lock --check" `
            -OutputFile (Join-Path $EvidenceDir "UV_LOCK_CHECK.txt") `
            -AllowFailure | Out-Null
    }
}

Compress-Archive `
    -Path (Join-Path $BuildDir "*") `
    -DestinationPath $ZipPath `
    -CompressionLevel Optimal `
    -Force

$ZipInfo = Get-Item $ZipPath

Write-Host ""
Write-Host "REVIEW BUNDLE READY"
Write-Host $ZipInfo.FullName
Write-Host "Size: $($ZipInfo.Length) bytes"
Write-Host "Files included: $($Included.Count)"
Write-Host "Files skipped: $($Skipped.Count)"