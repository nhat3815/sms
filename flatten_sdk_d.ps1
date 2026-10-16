$ErrorActionPreference = 'Stop'

$jobs = @(
    @{ Root = 'D:\Android\Sdk\build-tools\36.0.0'; Inner = 'D:\Android\Sdk\build-tools\36.0.0\android-16' },
    @{ Root = 'D:\Android\Sdk\platforms\android-36'; Inner = 'D:\Android\Sdk\platforms\android-36\android-36' }
)

foreach ($job in $jobs) {
    if (Test-Path $job.Inner) {
        Get-ChildItem $job.Inner -Force | ForEach-Object {
            Move-Item -Force $_.FullName $job.Root
        }
        Remove-Item -Recurse -Force $job.Inner
    }
}

Write-Host 'SDK flattened'
