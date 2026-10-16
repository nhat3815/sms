$ErrorActionPreference = 'Stop'

$sdkRoot = 'D:\Android\Sdk'
New-Item -ItemType Directory -Force -Path $sdkRoot | Out-Null

$packages = @(
    @{
        Name = 'platform-tools'
        Url = 'https://dl.google.com/android/repository/platform-tools_r37.0.1-win.zip'
        Zip = Join-Path $env:TEMP 'platform-tools_r37.0.1-win.zip'
        Dest = Join-Path $sdkRoot 'platform-tools'
    },
    @{
        Name = 'build-tools-36.0.0'
        Url = 'https://dl.google.com/android/repository/build-tools_r36_windows.zip'
        Zip = Join-Path $env:TEMP 'build-tools_r36_windows.zip'
        Dest = Join-Path $sdkRoot 'build-tools\36.0.0'
    },
    @{
        Name = 'platforms-android-36'
        Url = 'https://dl.google.com/android/repository/platform-36_r02.zip'
        Zip = Join-Path $env:TEMP 'platform-36_r02.zip'
        Dest = Join-Path $sdkRoot 'platforms\android-36'
    }
)

foreach ($pkg in $packages) {
    if (Test-Path $pkg.Zip) { Remove-Item -Force $pkg.Zip }
    if (Test-Path $pkg.Dest) { Remove-Item -Recurse -Force $pkg.Dest }
    New-Item -ItemType Directory -Force -Path $pkg.Dest | Out-Null
    & curl.exe -L --fail --silent --show-error $pkg.Url -o $pkg.Zip
    if (-not (Test-Path $pkg.Zip) -or (Get-Item $pkg.Zip).Length -le 0) {
        throw "Download failed for $($pkg.Name)"
    }
    Expand-Archive -Path $pkg.Zip -DestinationPath $pkg.Dest -Force
}

Write-Host "SDK packages installed to $sdkRoot"
