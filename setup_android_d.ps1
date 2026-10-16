$ErrorActionPreference = 'Stop'

$base = 'D:\Android'
$sdk = Join-Path $base 'Sdk'
$toolsRoot = Join-Path $base 'cmdline-tools'
$toolsLatest = Join-Path $toolsRoot 'latest'

New-Item -ItemType Directory -Force -Path $sdk, $toolsRoot, $toolsLatest | Out-Null

$url = 'https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip'
$zip = Join-Path $env:TEMP 'cmdline-tools.zip'

if (Test-Path $zip) {
    Remove-Item -Force $zip
}
& curl.exe -L --fail --silent --show-error $url -o $zip
if ((Get-Item $zip).Length -le 0) {
    throw 'cmdline-tools zip download failed.'
}

$extractRoot = Join-Path $env:TEMP 'cmdline-tools-extract'
if (Test-Path $extractRoot) {
    Remove-Item -Recurse -Force $extractRoot
}
New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null
Expand-Archive -Path $zip -DestinationPath $extractRoot -Force

$inner = Join-Path $extractRoot 'cmdline-tools'
if (-not (Test-Path $inner)) {
    throw 'Unexpected cmdline-tools archive layout.'
}

Copy-Item -Recurse -Force (Join-Path $inner '*') $toolsLatest

$env:ANDROID_SDK_ROOT = $sdk
$env:ANDROID_HOME = $sdk
$env:PATH = (Join-Path $toolsLatest 'bin') + ';' + $env:PATH

$sdkmanager = Join-Path $toolsLatest 'bin\sdkmanager.bat'
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
$env:PATH = (Join-Path $env:JAVA_HOME 'bin') + ';' + $env:PATH
$packages = @(
    'platform-tools',
    'platforms;android-36',
    'build-tools;36.0.0',
    'cmdline-tools;latest'
)

& cmd.exe /c "echo y|`"$sdkmanager`" --sdk_root=`"$sdk`" $($packages -join ' ')"

Write-Host "SDK installed to: $sdk"
