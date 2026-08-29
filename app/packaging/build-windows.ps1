[CmdletBinding()]
param(
    [string]$Repository = $env:GITHUB_REPOSITORY,
    [switch]$WithModels,
    [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Run Install.bat first: .venv\Scripts\python.exe was not found.'
}

if (-not $Repository) {
    $remote = (& git -C $RepoRoot remote get-url origin 2>$null)
    if ($remote -match 'github\.com[/:]([^/]+/[^/.]+)(?:\.git)?$') { $Repository = $Matches[1] }
}
if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw 'Pass -Repository owner/repository so the release can update from its own fork.'
}

& $Python -m pip install --disable-pip-version-check -r (Join-Path $RepoRoot 'app\requirements-build.txt')
if ($LASTEXITCODE) { throw 'Could not install the build tool.' }

if (-not $SkipTests) {
    $env:PYTHONUTF8 = '1'
    Push-Location (Join-Path $RepoRoot 'app')
    try {
        foreach ($Suite in @('test_pipeline.py','test_delivery.py','test_cli.py','test_video_colors.py','test_packaging.py')) {
            & $Python (Join-Path 'tests' $Suite)
            if ($LASTEXITCODE) { throw "$Suite failed; release not built." }
        }
    } finally { Pop-Location }
}

if ($WithModels) {
    & $Python -c "import whisper; whisper.load_model('small')"
    if ($LASTEXITCODE) { throw 'Could not cache the Whisper small model.' }
    # Demucs downloads its model when it first sees audio.  A tiny silent WAV
    # makes that happen during release creation rather than on the user's PC.
    $Probe = Join-Path $RepoRoot 'build\model-probe.wav'
    New-Item -ItemType Directory -Force (Split-Path $Probe) | Out-Null
    & $Python -c "import wave,sys; w=wave.open(sys.argv[1],'wb'); w.setparams((2,2,44100,44100,'NONE','')); w.writeframes(b'\0'*(44100*4)); w.close()" $Probe
    foreach ($Separator in @('htdemucs', 'htdemucs_ft')) {
        & $Python -m demucs -n $Separator --two-stems vocals --segment 7 -j 1 -o (Join-Path $RepoRoot 'build\model-probe') $Probe
        if ($LASTEXITCODE) { throw "Could not cache the Demucs model $Separator." }
    }
}
$env:KARAOKE_BUNDLE_MODELS = if ($WithModels) { '1' } else { '0' }

$Version = (& $Python -c "import sys; sys.path.insert(0, r'$RepoRoot\app'); import kstudio; print(kstudio.__version__)").Trim()
$BuildDir = Join-Path $RepoRoot 'build'
New-Item -ItemType Directory -Force $BuildDir | Out-Null
@{ repository=$Repository; version=$Version; built=(Get-Date).ToUniversalTime().ToString('o') } |
    # Windows PowerShell's "utf8" writes a BOM.  Python's plain utf-8 JSON
    # reader rejects that marker, silently disabling update checks in the EXE.
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $BuildDir 'build-info.json') -Encoding ascii

& $Python -m PyInstaller --noconfirm --clean --distpath (Join-Path $BuildDir 'updater-dist') --workpath (Join-Path $BuildDir 'updater-work') (Join-Path $RepoRoot 'app\packaging\KaraokeUpdater.spec')
if ($LASTEXITCODE) { throw 'Updater build failed.' }
# Never assemble over the copy a user may currently be testing.  Windows locks
# a running EXE; a staging dist lets us produce the next ZIP without killing
# the old Studio or risking its current session.
$ReleaseRoot = Join-Path $BuildDir 'release-dist'
& $Python -m PyInstaller --noconfirm --clean --distpath $ReleaseRoot --workpath (Join-Path $BuildDir 'studio-work') (Join-Path $RepoRoot 'app\packaging\KaraokeStudio.spec')
if ($LASTEXITCODE) { throw 'Studio build failed.' }

$Dist = Join-Path $ReleaseRoot 'KaraokeStudio'
Copy-Item -LiteralPath (Join-Path $BuildDir 'updater-dist\KaraokeUpdater.exe') -Destination $Dist -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot 'LICENSE') -Destination $Dist -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot 'README.ru.md') -Destination $Dist -Force
Copy-Item -LiteralPath (Join-Path $BuildDir 'build-info.json') -Destination $Dist -Force

# The video renderer is loaded dynamically from tools/video.py, and the MP3
# export relies on the ffmpeg binary's libmp3lame encoder. Exercise both inside
# the finished EXE before publishing anything.
$SmokeError = Join-Path $Dist 'package-smoke-error.txt'
if (Test-Path -LiteralPath $SmokeError) { Remove-Item -LiteralPath $SmokeError -Force }
$PackageSmoke = Start-Process -FilePath (Join-Path $Dist 'KaraokeStudio.exe') -ArgumentList '--internal-package-smoke' -Wait -PassThru -WindowStyle Hidden
if ($PackageSmoke.ExitCode) {
    if (Test-Path -LiteralPath $SmokeError) { Get-Content -LiteralPath $SmokeError }
    throw 'Packaged media dependencies are incomplete.'
}

# A smoke launch catches missing dynamic imports without opening a browser.
$Smoke = Start-Process -FilePath (Join-Path $Dist 'KaraokeStudio.exe') -ArgumentList '--no-browser','--port','18770' -PassThru -WindowStyle Hidden
try {
    $Ready = $false
    foreach ($n in 1..40) {
        Start-Sleep -Milliseconds 250
        try { $State = Invoke-RestMethod 'http://127.0.0.1:18770/api/state' -TimeoutSec 2; $Ready = $true; break } catch {}
        if ($Smoke.HasExited) { break }
    }
    if (-not $Ready) { throw 'Packaged Studio did not answer its smoke test.' }
} finally {
    if (-not $Smoke.HasExited) { Stop-Process -Id $Smoke.Id -Force }
}

$PublicDist = Join-Path $RepoRoot 'dist'
New-Item -ItemType Directory -Force $PublicDist | Out-Null
$Archive = Join-Path $PublicDist 'KaraokeStudio-windows-x64.zip'
if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($Dist, $Archive, [System.IO.Compression.CompressionLevel]::Optimal, $true)
$Hash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
"$Hash  KaraokeStudio-windows-x64.zip" | Set-Content -LiteralPath ($Archive + '.sha256') -Encoding ascii
Write-Host "Ready: $Archive"
