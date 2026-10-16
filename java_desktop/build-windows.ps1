$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $project

if (-not (Get-Command java -ErrorAction SilentlyContinue)) { throw 'Cần cài JDK 17 hoặc mới hơn.' }
if (-not (Get-Command gradle -ErrorAction SilentlyContinue)) { throw 'Cần cài Gradle 8 hoặc mới hơn.' }

gradle clean installDist
$input = Join-Path $project 'build\install\SmsSenderTool\lib'
$output = Join-Path $project 'release\windows'
New-Item -ItemType Directory -Force -Path $output | Out-Null

jpackage --type exe --name SmsSenderTool --app-version 2.0.0 --input $input --main-jar SmsSenderTool-2.0.0.jar --main-class vn.smsbridge.desktop.SmsSenderDesktop --dest $output --win-dir-chooser --win-menu --win-shortcut
Write-Host "Built: $output\SmsSenderTool-2.0.0.exe"
