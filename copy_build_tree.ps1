$ErrorActionPreference = 'Stop'

$src = $PSScriptRoot
$dst = 'D:\sms_sender_tool_build'

if (Test-Path $dst) {
    Remove-Item -Recurse -Force $dst
}

New-Item -ItemType Directory -Force -Path $dst | Out-Null

$items = @(
    'android_sender',
    'android_transport.py',
    'gui.py',
    'launcher.py',
    'requirements.txt',
    'start.bat',
    'start.command',
    'test_android_transport.py',
    'test_launcher.py'
)

foreach ($item in $items) {
    Copy-Item -Recurse -Force (Join-Path $src $item) $dst
}

Write-Host "Copied to $dst"
