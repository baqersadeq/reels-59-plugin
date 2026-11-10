# Builds the animated logo overlays and outro into a folder on the Desktop.
# Run from PowerShell:
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/baqersadeq/reels-59-plugin/main/tools/logo-anim/run.ps1 | iex"
$ErrorActionPreference = 'Stop'
$base = 'https://raw.githubusercontent.com/baqersadeq/reels-59-plugin/main/tools/logo-anim'

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) { return ,@('py', '-3') }
    $exe = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($exe) { return ,@($exe.FullName) }
    return $null
}

function Find-Ffmpeg {
    $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $link = "$env:LOCALAPPDATA\Microsoft\WinGet\Links\ffmpeg.exe"
    if (Test-Path $link) { return $link }
    $pkg = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin\ffmpeg.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($pkg) { return $pkg.FullName }
    return $null
}

Write-Host '[1/5] Checking Python...'
$py = Find-Python
if (-not $py) {
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    $py = Find-Python
    if (-not $py) { throw 'Python was installed but not found. Close PowerShell, open it again and rerun the command.' }
}
$pyExe = $py[0]; $pyArgs = @($py | Select-Object -Skip 1)

Write-Host '[2/5] Installing numpy and pillow...'
& $pyExe @pyArgs -m pip install --user --quiet --disable-pip-version-check numpy pillow
if ($LASTEXITCODE -ne 0) { throw 'pip install failed.' }

Write-Host '[3/5] Checking FFmpeg...'
$ff = Find-Ffmpeg
if (-not $ff) {
    winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
    $ff = Find-Ffmpeg
    if (-not $ff) { throw 'FFmpeg was installed but not found. Close PowerShell, open it again and rerun the command.' }
}

Write-Host '[4/5] Choose the logo image (the 2000x1611 gold logo on white)...'
Add-Type -AssemblyName System.Windows.Forms
$dlg = New-Object System.Windows.Forms.OpenFileDialog
$dlg.Title = 'Choose the logo image'
$dlg.Filter = 'Images (*.jpg;*.jpeg;*.png)|*.jpg;*.jpeg;*.png'
if ($dlg.ShowDialog() -ne 'OK') { throw 'No logo selected.' }
$logo = $dlg.FileName

Write-Host '[5/5] Rendering (a few minutes)...'
$script = Join-Path $env:TEMP 'make_logo_anim.py'
Invoke-WebRequest "$base/make_logo_anim.py" -OutFile $script -UseBasicParsing
$out = Join-Path ([Environment]::GetFolderPath('Desktop')) 'AlAnwar-Logo-Animations'
& $pyExe @pyArgs $script $logo $out --ffmpeg $ff
if ($LASTEXITCODE -ne 0) { throw 'Rendering failed; see the messages above.' }

Write-Host "Done. Files are in: $out"
Start-Process explorer.exe $out
