$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$toolsDir = 'C:\AndroidTools'
New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null

# 1. Tải và giải nén JDK 21 nếu chưa có
$jdkDir = Join-Path $toolsDir 'jdk-21'
if (-not (Test-Path "$jdkDir\bin\java.exe")) {
    Write-Host ">>> [1/4] Dang tai OpenJDK 21..."
    $jdkZip = Join-Path $toolsDir 'openjdk-21.zip'
    $jdkUrl = 'https://aka.ms/download-jdk/microsoft-jdk-21.0.6-windows-x64.zip'
    & curl.exe -L --fail --show-error $jdkUrl -o $jdkZip
    Write-Host ">>> Giai nen OpenJDK 21..."
    Expand-Archive -Path $jdkZip -DestinationPath $toolsDir -Force
    $extractedJdk = Get-ChildItem -Path $toolsDir -Directory -Filter "jdk-21*" | Select-Object -First 1
    if ($extractedJdk -and $extractedJdk.FullName -ne $jdkDir) {
        Move-Item -Force $extractedJdk.FullName $jdkDir
    }
    Remove-Item -Force $jdkZip -ErrorAction SilentlyContinue
}
Write-Host "✅ JDK 21 da san sang: $jdkDir"

# 2. Tải và giải nén Gradle 8.11.1 nếu chưa có
$gradleDir = Join-Path $toolsDir 'gradle-8.11.1'
if (-not (Test-Path "$gradleDir\bin\gradle.bat")) {
    Write-Host ">>> [2/4] Dang tai Gradle 8.11.1..."
    $gradleZip = Join-Path $toolsDir 'gradle.zip'
    $gradleUrl = 'https://services.gradle.org/distributions/gradle-8.11.1-bin.zip'
    & curl.exe -L --fail --show-error $gradleUrl -o $gradleZip
    Write-Host ">>> Giai nen Gradle..."
    Expand-Archive -Path $gradleZip -DestinationPath $toolsDir -Force
    Remove-Item -Force $gradleZip -ErrorAction SilentlyContinue
}
Write-Host "✅ Gradle da san sang: $gradleDir"

# 3. Tải và cài đặt Android SDK packages nếu chưa có
$sdkRoot = 'C:\Android\Sdk'
New-Item -ItemType Directory -Force -Path $sdkRoot | Out-Null

$sdkPackages = @(
    @{
        Name = 'platforms-android-36'
        Url = 'https://dl.google.com/android/repository/platform-36_r02.zip'
        Zip = Join-Path $toolsDir 'platform-36_r02.zip'
        Dest = Join-Path $sdkRoot 'platforms\android-36'
        Check = Join-Path $sdkRoot 'platforms\android-36\android.jar'
    },
    @{
        Name = 'build-tools-36.0.0'
        Url = 'https://dl.google.com/android/repository/build-tools_r36_windows.zip'
        Zip = Join-Path $toolsDir 'build-tools_r36_windows.zip'
        Dest = Join-Path $sdkRoot 'build-tools\36.0.0'
        Check = Join-Path $sdkRoot 'build-tools\36.0.0\aapt2.exe'
    },
    @{
        Name = 'platform-tools'
        Url = 'https://dl.google.com/android/repository/platform-tools_r37.0.1-win.zip'
        Zip = Join-Path $toolsDir 'platform-tools_r37.0.1-win.zip'
        Dest = Join-Path $sdkRoot 'platform-tools'
        Check = Join-Path $sdkRoot 'platform-tools\adb.exe'
    }
)

Write-Host ">>> [3/4] Kiem tra Android SDK Packages..."
foreach ($pkg in $sdkPackages) {
    if (-not (Test-Path $pkg.Check)) {
        Write-Host "Dang tai $($pkg.Name)..."
        & curl.exe -L --fail --show-error $pkg.Url -o $pkg.Zip
        $tempExtract = Join-Path $toolsDir "temp_$($pkg.Name)"
        if (Test-Path $tempExtract) { Remove-Item -Recurse -Force $tempExtract }
        Expand-Archive -Path $pkg.Zip -DestinationPath $tempExtract -Force
        
        New-Item -ItemType Directory -Force -Path $pkg.Dest | Out-Null
        # Lay noi dung ben trong
        $innerDir = Get-ChildItem -Path $tempExtract -Directory | Select-Object -First 1
        if ($innerDir) {
            Get-ChildItem -Path $innerDir.FullName -Force | ForEach-Object {
                Move-Item -Force $_.FullName $pkg.Dest
            }
        } else {
            Get-ChildItem -Path $tempExtract -Force | ForEach-Object {
                Move-Item -Force $_.FullName $pkg.Dest
            }
        }
        Remove-Item -Recurse -Force $tempExtract -ErrorAction SilentlyContinue
        Remove-Item -Force $pkg.Zip -ErrorAction SilentlyContinue
    }
}
Write-Host "✅ Android SDK da san sang: $sdkRoot"

# 4. Thiet lap bien moi truong & build APK
Write-Host ">>> [4/4] Dang build APK..."
$env:JAVA_HOME = $jdkDir
$env:ANDROID_HOME = $sdkRoot
$env:ANDROID_SDK_ROOT = $sdkRoot
$env:PATH = "$jdkDir\bin;$gradleDir\bin;$sdkRoot\platform-tools;$env:PATH"

$projectDir = Join-Path $PSScriptRoot 'android_sender'

# Tao file local.properties neu chua co
$localProps = Join-Path $projectDir 'local.properties'
"sdk.dir=$($sdkRoot -replace '\\', '/')" | Set-Content -Path $localProps -Encoding ASCII

# Chay gradle assembleDebug
Push-Location $projectDir
try {
    & "$gradleDir\bin\gradle.bat" assembleDebug --stacktrace
} finally {
    Pop-Location
}

# Sao chep APK moi vao android_sender va android_sender/app
$builtApk = Join-Path $projectDir 'app\build\outputs\apk\debug\app-debug.apk'
if (Test-Path $builtApk) {
    Copy-Item -Force $builtApk (Join-Path $projectDir 'SmsBridgeSender-debug.apk')
    Copy-Item -Force $builtApk (Join-Path $projectDir 'app\SmsBridgeSender-debug.apk')
    Write-Host "🎉 BUILD APK THANH CONG!"
    Write-Host "File APK moi: $(Join-Path $projectDir 'SmsBridgeSender-debug.apk')"

    $adb = Join-Path $PSScriptRoot 'platform-tools\adb.exe'
    $target = $env:ADB_TARGET
    if ((Test-Path $adb) -and $target) {
        Write-Host ">>> Dang cai dat APK len thiet bi $target..."
        & $adb connect $target | Out-Null
        & $adb -s $target install -r -t -d $builtApk
        & $adb -s $target shell am force-stop vn.smsbridge.sender
        & $adb -s $target shell am start -n vn.smsbridge.sender/.MainActivity
    } elseif (-not $target) {
        Write-Host "Bo qua cai dat APK: dat bien ADB_TARGET=IP:PORT neu muon cai len dien thoai."
    }
} else {
    throw "Khong tim thay file APK sau khi build."
}
