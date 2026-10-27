# Windows PowerShell 5.1: tests -> PyInstaller -> hidden smoke test -> SHA256
param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) { throw 'Python is required. Install Python 3.10+ with tkinter.' }
$pythonExe = $pythonCommand.Source
$versionCode = @'
import pathlib, re
text = pathlib.Path('workspace_ui.py').read_text(encoding='utf-8')
print(re.search(r"^VERSION = '([^']+)'", text, re.M).group(1))
'@
$version = ($versionCode | & $pythonExe -).Trim()
if ($LASTEXITCODE -ne 0 -or -not $version) { throw 'Cannot read version.' }
if (-not $SkipTests) {
    & $pythonExe -m unittest discover -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; build stopped.' }
}
& $pythonExe -m PyInstaller --noconfirm --clean opendesign.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
$exePath = Join-Path $PSScriptRoot "dist\WindowCapture_$version.exe"
if (-not (Test-Path -LiteralPath $exePath)) { throw "Missing executable: $exePath" }
$smokeRoot = Join-Path $env:TEMP ('wtc-smoke-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $smokeRoot
$reportPath = Join-Path $smokeRoot 'smoke.json'
$outputPath = Join-Path $smokeRoot 'output'
$arguments = '--smoke-test --smoke-report "{0}" --output "{1}"' -f $reportPath, $outputPath
$process = Start-Process -FilePath $exePath -ArgumentList $arguments -WindowStyle Hidden -PassThru
if (-not $process.WaitForExit(60000)) {
    $process.Kill()
    throw 'Smoke test timed out.'
}
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $reportPath)) { throw 'Smoke test failed.' }
$smoke = Get-Content -Raw -Encoding UTF8 -LiteralPath $reportPath | ConvertFrom-Json
if (-not $smoke.gui_created -or -not $smoke.reader_exists -or $smoke.version -ne $version) { throw 'Invalid smoke report.' }
Get-FileHash -LiteralPath $exePath -Algorithm SHA256
Write-Host "Smoke report: $reportPath"
Write-Host "Package with: python tools/package_release.py --exe dist/WindowCapture_$version.exe"
