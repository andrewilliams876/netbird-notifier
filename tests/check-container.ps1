$ErrorActionPreference = 'Stop'
# Run from the repository root. These credentials are synthetic and never sent.
$dockerExe = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $dockerExe) { $dockerExe = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe" }
if (-not (Test-Path -LiteralPath $dockerExe)) { throw 'Docker CLI not found' }
$projectName = 'notifier-smoke-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$healthContainer = $projectName + '-health'
New-Item -ItemType Directory -Path './artifacts' -Force | Out-Null
Set-Content -LiteralPath './artifacts/smoke-token.txt' -Value 'synthetic-token' -NoNewline
Set-Content -LiteralPath './artifacts/smoke-password.txt' -Value 'synthetic-password' -NoNewline
$composeArgs = @('compose', '--project-name', $projectName, '-f', 'compose.yaml', '-f', 'tests/compose.smoke.yaml')
function Invoke-CheckedDocker([string[]]$Arguments) {
    & $dockerExe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker check failed: exit $LASTEXITCODE" }
}
function Wait-Health([string]$Expected) {
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $observed = & $dockerExe inspect --format '{{.State.Health.Status}}' $healthContainer
        if ($LASTEXITCODE -eq 0 -and $observed -eq $Expected) { return }
        Start-Sleep -Seconds 1
    }
    throw "Container did not become $Expected"
}
try {
    Invoke-CheckedDocker ($composeArgs + @('config', '--quiet'))
    Invoke-CheckedDocker ($composeArgs + @('run', '--rm', 'notifier', '--check-config'))
    # Two separate containers use the same newly created test volume.
    foreach ($iteration in 1..2) {
        Invoke-CheckedDocker ($composeArgs + @('run', '--rm', '--entrypoint', 'python', 'notifier', '/tests/container_smoke.py'))
    }
    Invoke-CheckedDocker ($composeArgs + @('run', '--rm', 'notifier', '--healthcheck'))
    Invoke-CheckedDocker ($composeArgs + @('run', '--detach', '--name', $healthContainer, '--entrypoint', 'python', 'notifier', '-c', 'import time; time.sleep(120)'))
    Wait-Health 'healthy'
    Invoke-CheckedDocker @('exec', $healthContainer, 'python', '/tests/expire_health.py')
    Wait-Health 'unhealthy'
    Invoke-CheckedDocker ($composeArgs + @('run', '--rm', '--entrypoint', 'python', 'notifier', '/tests/container_smoke.py'))
    Wait-Health 'healthy'
    Write-Host 'PASS Docker health status: healthy -> unhealthy -> healthy'
} finally {
    # Deletes only this invocation's uniquely named synthetic-test resources.
    & $dockerExe inspect $healthContainer 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { & $dockerExe rm --force $healthContainer | Out-Null }
    & $dockerExe @composeArgs down --volumes
}
