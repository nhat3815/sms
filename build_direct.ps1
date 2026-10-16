$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$toolsDir = 'C:\AndroidTools'
$sdkRoot = 'C:\Android\Sdk'
$buildTools = "$sdkRoot\build-tools\36.0.0"
$platformJar = "$sdkRoot\platforms\android-36\android.jar"
$kotlinc = "$toolsDir\kotlinc\bin\kotlinc.bat"
$aapt2 = "$buildTools\aapt2.exe"
$d8 = "$buildTools\d8.bat"
$zipalign = "$buildTools\zipalign.exe"
$apksigner = "$buildTools\apksigner.bat"
$adb = "$sdkRoot\platform-tools\adb.exe"
$keytool = "$toolsDir\jdk-21\bin\keytool.exe"

$env:JAVA_HOME = "$toolsDir\jdk-21"
$env:PATH = "$toolsDir\jdk-21\bin;$buildTools;$sdkRoot\platform-tools;$env:PATH"

$projectDir = Join-Path $PSScriptRoot 'android_sender'
$appDir = Join-Path $projectDir 'app'
$srcMain = Join-Path $appDir 'src\main'
$manifest = Join-Path $srcMain 'AndroidManifest.xml'
$resDir = Join-Path $srcMain 'res'
$javaSrc = Join-Path $srcMain 'java'

$workDir = Join-Path $appDir 'direct_build'
if (Test-Path $workDir) { Remove-Item -Recurse -Force $workDir }
New-Item -ItemType Directory -Force -Path $workDir | Out-Null
$resCompiled = Join-Path $workDir 'res_compiled'
$genDir = Join-Path $workDir 'gen'
$classesDir = Join-Path $workDir 'classes'
$dexDir = Join-Path $workDir 'dex'
New-Item -ItemType Directory -Force -Path $resCompiled | Out-Null
New-Item -ItemType Directory -Force -Path $genDir | Out-Null
New-Item -ItemType Directory -Force -Path $classesDir | Out-Null
New-Item -ItemType Directory -Force -Path $dexDir | Out-Null

Write-Host ">>> [1/6] Compile Resources voi AAPT2..."
$compiledResZip = Join-Path $resCompiled 'resources.zip'
& $aapt2 compile --dir $resDir -o $compiledResZip

Write-Host ">>> [2/6] Link Resources voi AAPT2..."
$baseApk = Join-Path $workDir 'base.apk'
& $aapt2 link -I $platformJar --manifest $manifest -o $baseApk --java $genDir --auto-add-overlay --min-sdk-version 23 --target-sdk-version 34 --version-code 1 --version-name "1.0.0" $compiledResZip

Write-Host ">>> [3/6] Compile Kotlin & Java sources voi kotlinc..."
$ktFiles = (Get-ChildItem -Recurse -File -Filter "*.kt" $javaSrc | ForEach-Object { $_.FullName })
$genJavaFiles = (Get-ChildItem -Recurse -File -Filter "*.java" $genDir | ForEach-Object { $_.FullName })
$allSources = $ktFiles + $genJavaFiles

& $kotlinc -jvm-target 17 -classpath $platformJar -d $classesDir $allSources

Write-Host ">>> [4/6] Convert sang DEX voi D8..."
$classFiles = (Get-ChildItem -Recurse -File -Filter "*.class" $classesDir | ForEach-Object { $_.FullName })
$stdlibJar = "$toolsDir\kotlinc\lib\kotlin-stdlib.jar"

& $d8 --min-api 23 --output $dexDir --lib $platformJar ($classFiles + @($stdlibJar))

Write-Host ">>> [5/6] Dong goi & Ky APK..."
$unsignedApk = Join-Path $workDir 'unsigned.apk'
Copy-Item -Force $baseApk $unsignedApk

# Them classes.dex vao unsigned.apk bang python zipfile
$dexFile = Join-Path $dexDir 'classes.dex'
& python -c "import zipfile, sys; z = zipfile.ZipFile(sys.argv[1], 'a'); z.write(sys.argv[2], 'classes.dex'); z.close()" $unsignedApk $dexFile

# Tao keystore debug neu chua co (luu o projectDir de tai su dung)
$keystore = Join-Path $projectDir 'debug.keystore'
if (-not (Test-Path $keystore)) {
    & $keytool -genkey -v -keystore $keystore -storepass android -alias androiddebugkey -keypass android -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Android Debug,O=Android,C=US"
}

$alignedApk = Join-Path $workDir 'aligned.apk'
& $zipalign -f -p 4 $unsignedApk $alignedApk

$finalApk = Join-Path $projectDir 'SmsBridgeSender-debug.apk'
& $apksigner sign --ks $keystore --ks-pass pass:android --ks-key-alias androiddebugkey --key-pass pass:android --out $finalApk $alignedApk
Copy-Item -Force $finalApk (Join-Path $appDir 'SmsBridgeSender-debug.apk')

Write-Host "BUILD APK THANH CONG: $finalApk"

$target = $env:ADB_TARGET
if (-not $target) {
    Write-Host "Bo qua cai dat APK: dat bien ADB_TARGET=IP:PORT neu muon cai len dien thoai."
    exit 0
}

Write-Host ">>> [6/6] Cai dat APK len dien thoai $target..."
& $adb disconnect $target | Out-Null
Start-Sleep -Milliseconds 500
& $adb connect $target | Out-Null
Start-Sleep -Milliseconds 500

$installRes = & $adb -s $target install -r -t -d $finalApk 2>&1 | Out-String
if ($installRes -match "INSTALL_FAILED_UPDATE_INCOMPATIBLE|INSTALL_FAILED_VERSION_DOWNGRADE") {
    Write-Host "Dang go cai dat ban cu do khac chu ky..."
    & $adb -s $target uninstall vn.smsbridge.sender
    & $adb -s $target install -r -t -d $finalApk
}

& $adb -s $target shell pm grant vn.smsbridge.sender android.permission.SEND_SMS 2>$null
& $adb -s $target shell pm grant vn.smsbridge.sender android.permission.READ_SMS 2>$null
& $adb -s $target shell pm grant vn.smsbridge.sender android.permission.RECEIVE_SMS 2>$null
& $adb -s $target shell pm grant vn.smsbridge.sender android.permission.READ_PHONE_STATE 2>$null

& $adb -s $target shell am force-stop vn.smsbridge.sender
& $adb -s $target shell am start -n vn.smsbridge.sender/.MainActivity
Write-Host "Da khoi chay App tren dien thoai!"
