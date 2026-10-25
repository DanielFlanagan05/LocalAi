# Starts the LiteLLM gateway on 127.0.0.1:4000 in the background.
param(
    [int]$Port = 4000
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\lib\cluster-common.ps1')

$litellm = Join-Path $PSScriptRoot '.venv\Scripts\litellm.exe'
if (-not (Test-Path -LiteralPath $litellm)) {
    throw 'The gateway is not set up yet. Run cluster\gateway\setup-gateway.ps1 first.'
}
if (Test-HttpOk "http://127.0.0.1:$Port/health/liveliness") {
    Write-Host "The vision gateway is already running at http://127.0.0.1:$Port/v1"
    return
}

Import-ClusterEnv
$env:PYTHONIOENCODING = 'utf-8'
$config = Join-Path $PSScriptRoot 'litellm-config.yaml'
Start-ClusterProcess 'vision-gateway' $litellm @('--config', "`"$config`"", '--host', '127.0.0.1', '--port', $Port) | Out-Null

foreach ($attempt in 1..60) {
    if (Test-HttpOk "http://127.0.0.1:$Port/health/liveliness") {
        Write-Host "Vision gateway ready at http://127.0.0.1:$Port/v1 (key: LITELLM_MASTER_KEY in cluster\.env)"
        return
    }
    Start-Sleep -Seconds 1
}
throw "The vision gateway did not become ready. See $ClusterLogDir\vision-gateway.log"
