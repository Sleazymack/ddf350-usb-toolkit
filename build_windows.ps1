<#
Build a Windows x64 GUI executable without accessing a radio.
Run from PowerShell with a 64-bit Python 3.10+ installation that includes Tk.
The isolated build environment and all outputs default to a sibling directory.
Every release embeds the verified DDF-350 2.0.5 application used to generate dashboards.
PyInstaller reference: https://pyinstaller.org/en/stable/usage.html
#>
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$BuildRoot = '',
    [string]$OfficialFirmware = '',
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'Build this executable on Windows.' }
$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
if ([string]::IsNullOrWhiteSpace($OfficialFirmware)) {
    $OfficialFirmware = Join-Path $projectRoot 'firmware/DDF-2.0.5.bin'
}
if (-not (Test-Path -LiteralPath $OfficialFirmware -PathType Leaf)) {
    throw 'Missing required DDF-350 2.0.5 application firmware.'
}
if ([string]::IsNullOrWhiteSpace($BuildRoot)) {
    $BuildRoot = Join-Path (Split-Path -Parent $projectRoot) '.build-ddf350'
}
$buildRootPath = [System.IO.Path]::GetFullPath($BuildRoot)
$projectPrefix = $projectRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
if ($buildRootPath.Equals($projectRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $buildRootPath.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'BuildRoot must be outside the source repository.'
}
foreach ($required in @('app.py', 'wizard.py', 'installer.py', 'editor.py', 'patch_firmware.py', 'dashboard_six.py', 'dashboard_custom.py', 'pc/ddf350_hid.py')) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $required) -PathType Leaf)) {
        throw "Missing application source: $required"
    }
}

function Invoke-Python {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python command failed with exit code $LASTEXITCODE." }
}

New-Item -ItemType Directory -Path $buildRootPath -Force | Out-Null
$venvPath = Join-Path $buildRootPath 'venv'
$venvPython = Join-Path $venvPath 'Scripts/python.exe'
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Invoke-Python -Executable $Python -Arguments @('-m', 'venv', $venvPath)
}
Invoke-Python -Executable $venvPython -Arguments @('-c', "import struct,sys,tkinter; assert sys.version_info >= (3,10); assert struct.calcsize('P')==8, 'A 64-bit Python installation is required'; print('Windows x64 / Python', sys.version.split()[0], '/ Tk', tkinter.TkVersion)")
if (-not $SkipDependencyInstall) {
    Invoke-Python -Executable $venvPython -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', (Join-Path $projectRoot 'requirements-build.txt'))
}
Invoke-Python -Executable $venvPython -Arguments @('-c', "from importlib.metadata import version; assert version('pyinstaller')=='6.22.3'; assert version('pyinstaller-hooks-contrib')=='2026.9'; assert version('Pillow')=='12.3.0'; print('Pinned build dependencies verified')")
$pillowLicense = Invoke-Python -Executable $venvPython -Arguments @('-c', "from importlib.metadata import distribution; from pathlib import Path; p=Path(distribution('Pillow').locate_file('pillow-12.3.0.dist-info/licenses/LICENSE')); assert p.is_file(); print(p)")
$basePythonPrefix = Invoke-Python -Executable $venvPython -Arguments @('-c', 'import sys; print(sys.base_prefix)')
$pythonLicense = Join-Path $basePythonPrefix 'LICENSE.txt'
if (-not (Test-Path -LiteralPath $pythonLicense -PathType Leaf)) {
    throw 'The Python runtime LICENSE.txt is required for the executable bundle.'
}
$runtimeVersions = (Invoke-Python -Executable $venvPython -Arguments @('-c', "import json,tkinter; t=tkinter.Tcl(); print(json.dumps({'tcl':t.eval('info patchlevel'),'tk':str(tkinter.TkVersion)}))")) | ConvertFrom-Json
if ($runtimeVersions.tcl -notmatch '^\d+\.\d+\.\d+$' -or $runtimeVersions.tk -notmatch '^\d+\.\d+$') {
    throw 'Unsupported Tcl/Tk version format; verify runtime notices before packaging.'
}
$tkLicense = Join-Path $basePythonPrefix ('tcl/tk' + $runtimeVersions.tk + '/license.terms')
if (-not (Test-Path -LiteralPath $tkLicense -PathType Leaf)) {
    throw 'The Tk runtime license.terms is required for the executable bundle.'
}
$tclMinor = (($runtimeVersions.tcl -split '\.')[0..1] -join '.')
$tclLicense = Join-Path $basePythonPrefix ('tcl/tcl' + $tclMinor + '/license.terms')
if (-not (Test-Path -LiteralPath $tclLicense -PathType Leaf)) {
    # Some Windows Python distributions omit Tcl's license file. Obtain only
    # that notice from the matching official Tcl release, never runtime code.
    $noticeDirectory = Join-Path $buildRootPath 'notices'
    New-Item -ItemType Directory -Path $noticeDirectory -Force | Out-Null
    $tclLicense = Join-Path $noticeDirectory ('tcl-' + $runtimeVersions.tcl + '-license.terms')
    if (-not (Test-Path -LiteralPath $tclLicense -PathType Leaf)) {
        $tclTag = 'core-' + $runtimeVersions.tcl.Replace('.', '-')
        $licenseUri = 'https://raw.githubusercontent.com/tcltk/tcl/' + $tclTag + '/license.terms'
        $licenseText = (Invoke-WebRequest -Uri $licenseUri -UseBasicParsing -TimeoutSec 30).Content
        if ($licenseText.Length -lt 1000 -or $licenseText.Length -gt 12000 -or
            -not $licenseText.Contains('The authors hereby grant permission')) {
            throw 'The official Tcl license response was unexpected; packaging stopped.'
        }
        [System.IO.File]::WriteAllText($tclLicense, $licenseText, [System.Text.UTF8Encoding]::new($false))
    }
}

$runName = 'build-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$runRoot = Join-Path $buildRootPath $runName
$workPath = Join-Path $runRoot 'work'
$specPath = Join-Path $runRoot 'spec'
$distPath = Join-Path $runRoot 'dist'
foreach ($directory in @($runRoot, $workPath, $specPath, $distPath)) {
    New-Item -ItemType Directory -Path $directory | Out-Null
}
$firmwareDirectory=Join-Path $runRoot 'firmware'
New-Item -ItemType Directory -Path $firmwareDirectory | Out-Null
$firmwareStagingPath=Join-Path $firmwareDirectory 'DDF-2.0.5.bin'
$stageScript=@'
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import patch_firmware as p
content=p.read_regular_file(sys.argv[2])
p._require_original(content)
p.write_new_output(sys.argv[3],content,source=sys.argv[2])
print(json.dumps({"file":"firmware/DDF-2.0.5.bin","bytes":len(content),"sha256":hashlib.sha256(content).hexdigest()}))
'@
$firmwareBundle=(Invoke-Python -Executable $venvPython -Arguments @('-B','-c',$stageScript,$projectRoot,$OfficialFirmware,$firmwareStagingPath)) | ConvertFrom-Json
$oldConfigDirectory = $env:PYINSTALLER_CONFIG_DIR
$oldBytecodeSetting = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $runRoot 'cache'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $arguments = @(
        '-m', 'PyInstaller', '--onefile', '--windowed', '--noupx', '--clean', '--noconfirm',
        '--name', 'DDF350-USB-Toolkit', '--icon', 'NONE',
        '--workpath', $workPath, '--specpath', $specPath, '--distpath', $distPath,
        '--paths', $projectRoot,
        '--hidden-import', 'patch_firmware', '--hidden-import', 'dashboard_six',
        '--hidden-import', 'dashboard_custom', '--hidden-import', 'editor',
        '--hidden-import', 'dashboard_zones',
        '--hidden-import', 'dashboard_themes',
        '--hidden-import', 'dashboard_faces',
        '--hidden-import', 'dashboard_face_assets',
        '--hidden-import', 'dashboard_fullscreen', '--hidden-import', 'dashboard_lcd_assets',
        '--hidden-import', 'dashboard_signed_assets',
        '--hidden-import', 'dashboard_native_assets',
        '--hidden-import', 'PIL.ImageTk',
        '--hidden-import', 'startup_animation', '--hidden-import', 'startup_player_blob',
        '--hidden-import', 'startup_media', '--hidden-import', 'startup.convert_gif',
        '--hidden-import', 'PIL.ImageTk', '--hidden-import', 'PIL.GifImagePlugin',
        '--hidden-import', 'PIL.PngImagePlugin', '--hidden-import', 'PIL.JpegImagePlugin', '--hidden-import', 'PIL.BmpImagePlugin',
        '--hidden-import', 'startup_player_v1', '--hidden-import', 'ui_layout', '--hidden-import', 'ui_audit',
        '--hidden-import', 'wizard', '--hidden-import', 'installer', '--hidden-import', 'pc_startup', '--hidden-import', 'sync_tray',
        '--hidden-import', 'pc.ddf350_hid', '--hidden-import', 'i18n',
        '--add-data', ((Join-Path $projectRoot 'LICENSE') + ':.'),
        '--add-data', ($pythonLicense + ':third_party/python'),
        '--add-data', ($tclLicense + ':third_party/tcl'),
        '--add-data', ($tkLicense + ':third_party/tk'),
        '--add-data', ($pillowLicense + ':third_party/pillow'),
        '--add-data', ((Join-Path $projectRoot 'compatibility.json') + ':.')
    )
    $arguments += @('--add-data',($firmwareStagingPath+':firmware'))
    $arguments += (Join-Path $projectRoot 'app.py')
    Invoke-Python -Executable $venvPython -Arguments $arguments
    $executablePath = Join-Path $distPath 'DDF350-USB-Toolkit.exe'
    # Inspect the actual bundle, rather than trusting the build arguments alone.
    $auditScript = @'
import hashlib, json, sys
from PyInstaller.archive.readers import CArchiveReader
archive = CArchiveReader(sys.argv[1])
expected=sys.argv[2]
sys.path.insert(0, sys.argv[3])
media=[]
found=[]
for name in archive.toc:
    normalized = name.replace("\\", "/").lower()
    if normalized.endswith('.ddfa') or (normalized.endswith('.gif') and not normalized.startswith('_tk_data/')):
        raise SystemExit('Unexpected startup media resource: '+name)
    if normalized.startswith("firmware/") or normalized.endswith((".bin", ".dfu", ".hex", ".ips")):
        if normalized!='firmware/ddf-2.0.5.bin':
            raise SystemExit("Unexpected firmware resource in executable: " + name)
        payload=archive.extract(name)
        if len(payload)!=626956 or hashlib.sha256(payload).hexdigest()!=expected:
            raise SystemExit("Bundled official image differs")
        found.append(name)
if len(found)!=1:raise SystemExit("Verified firmware resource missing or duplicated")
print(json.dumps({"result": "PASS", "firmware_resources": found, "animation_resources":media,"archive_entries": len(archive.toc)}))
'@
    $expectedFirmwareHash=$firmwareBundle.sha256
    $firmwareAudit = (Invoke-Python -Executable $venvPython -Arguments @('-B', '-c', $auditScript, $executablePath, $expectedFirmwareHash, $projectRoot)) | ConvertFrom-Json
    $publicZip = (Invoke-Python -Executable $venvPython -Arguments @('-B',(Join-Path $projectRoot 'packaging/portable_release.py'),$executablePath)) | ConvertFrom-Json
    $report = [ordered]@{
        public_release_zip = $publicZip
        schema = 1
        target = 'Windows x64'
        pyinstaller_version = '6.22.3'
        pyinstaller_hooks_contrib_version = '2026.9'
        tcl_version = $runtimeVersions.tcl
        tk_version = $runtimeVersions.tk
        executable = [ordered]@{
            file = 'DDF350-USB-Toolkit.exe'
            bytes = (Get-Item -LiteralPath $executablePath).Length
            sha256 = (Get-FileHash -LiteralPath $executablePath -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        app_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'app.py') -Algorithm SHA256).Hash.ToLowerInvariant()
        editor_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'editor.py') -Algorithm SHA256).Hash.ToLowerInvariant()
        wizard_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'wizard.py') -Algorithm SHA256).Hash.ToLowerInvariant()
        pc_startup_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'pc_startup.py') -Algorithm SHA256).Hash.ToLowerInvariant()
        sync_tray_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'sync_tray.py') -Algorithm SHA256).Hash.ToLowerInvariant()
        installer_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'installer.py') -Algorithm SHA256).Hash.ToLowerInvariant()
        patcher_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'patch_firmware.py') -Algorithm SHA256).Hash.ToLowerInvariant()
        dashboard_six_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'dashboard_six.py') -Algorithm SHA256).Hash.ToLowerInvariant()
        dashboard_custom_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'dashboard_custom.py') -Algorithm SHA256).Hash.ToLowerInvariant()
        dashboard_themes_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'dashboard_themes.py') -Algorithm SHA256).Hash.ToLowerInvariant()
        startup_media_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'startup_media.py') -Algorithm SHA256).Hash.ToLowerInvariant()
        pc_reader_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'pc/ddf350_hid.py') -Algorithm SHA256).Hash.ToLowerInvariant()
        signed = $false
        firmware_included = $true
        firmware = $firmwareBundle
        startup_animation = $null
        startup_media_supported = $true
        pillow_version = '12.3.0'
        distribution = 'portable-only'
        startup_screen = 'original-native-by-default-user-media-optional'
        distribution_scope = 'public-release-with-official-firmware-no-preset'
        firmware_resource_audit = $firmwareAudit
        radio_accessed_by_build = $false
        scope = 'Packaging hashes only; compilation is not hardware validation or a GUI smoke test.'
    }
    [System.IO.File]::WriteAllText((Join-Path $distPath 'build-report.json'), ($report | ConvertTo-Json -Depth 6) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
} finally {
    $env:PYINSTALLER_CONFIG_DIR = $oldConfigDirectory
    $env:PYTHONDONTWRITEBYTECODE = $oldBytecodeSetting
}
Write-Host "Build complete: $distPath"
Write-Host 'Official DDF-350 2.0.5 firmware included and verified.'
Write-Host 'No radio was opened. The executable is unsigned.'
