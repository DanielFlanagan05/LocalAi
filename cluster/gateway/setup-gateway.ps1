# One-time setup: Python venv with the LiteLLM proxy and the tooling used by cluster/scripts.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\lib\cluster-common.ps1')

$venv = Join-Path $PSScriptRoot '.venv'
if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) {
    python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the gateway venv.' }
}
$python = Join-Path $venv 'Scripts\python.exe'
& $python -m pip install --upgrade pip
& $python -m pip install 'litellm[proxy]' pyyaml pillow
if ($LASTEXITCODE -ne 0) { throw 'Failed to install gateway packages.' }

Import-ClusterEnv
& $python -m pip freeze | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'requirements.lock.txt') -Encoding ascii
Write-Host 'Gateway environment ready. Start it with bin\start-vision-gateway.cmd'
