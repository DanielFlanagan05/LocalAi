# Starts the desktop's qwen3-vl-8b llama-server on the RX 7900 XT (port 9101).
# Uses the llama.cpp build ClearCase pins (b11216, Vulkan) and ClearCase's verified model files.
param(
    [int]$Port = 9101,
    [int]$Parallel = 4,
    [int]$SlotContext = 16384,
    # Vulkan0 is the RX 7900 XT; Vulkan1 is the Ryzen iGPU and must not be used.
    [string]$Device = 'Vulkan0',
    [string]$ModelDir = (Join-Path $env:LOCALAPPDATA 'ClearCase\models\00e7d63528e65d7b64e80e1293a8360b4af6a594'),
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\lib\cluster-common.ps1')

$llamaServer = Join-Path $LocalAiRoot 'tools\llama-b11216-vulkan\llama-server.exe'
$archive = 'C:\Users\danfl\dev\ClearCase\tmp\local-ai-artifacts\llama-b11216-bin-win-vulkan-x64.zip'
if (-not (Test-Path -LiteralPath $llamaServer)) {
    if (-not (Test-Path -LiteralPath $archive)) {
        throw "llama.cpp b11216 Vulkan is missing. Download llama-b11216-bin-win-vulkan-x64.zip from https://github.com/ggml-org/llama.cpp/releases/tag/b11216 and extract it to $(Split-Path $llamaServer)"
    }
    Expand-Archive -LiteralPath $archive -DestinationPath (Split-Path $llamaServer) -Force
}

$model = Join-Path $ModelDir 'Qwen3VL-8B-Instruct-Q4_K_M.gguf'
$mmproj = Join-Path $ModelDir 'mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf'
foreach ($file in $model, $mmproj) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Model file not found: $file. Install the default model from ClearCase first, or pass -ModelDir."
    }
}

if (Test-HttpOk "http://127.0.0.1:$Port/health") {
    Write-Host "The desktop vision node is already running on port $Port."
    return
}
# Strata's models fill the 7900 XT's VRAM; loading both would push one of them onto system RAM.
$strataPorts = 8080, 8081 | Where-Object { Test-HttpOk "http://127.0.0.1:$_/health" }
if ($strataPorts -and -not $Force) {
    throw "Strata is running on port(s) $($strataPorts -join ', '). Stop it (bin\stop-strata.cmd) or pass -Force. The gateway routes around this node while it is off."
}

Import-ClusterEnv
New-Item -ItemType Directory -Force -Path $ClusterStateDir | Out-Null
$keyFile = Join-Path $ClusterStateDir 'vision-node.key'
Set-Content -LiteralPath $keyFile -Value $env:CLUSTER_API_KEY -Encoding ascii

$arguments = @(
    '--host', '0.0.0.0', '--port', $Port,
    '-m', "`"$model`"", '--mmproj', "`"$mmproj`"", '--alias', 'qwen3-vl-8b',
    '-dev', $Device, '-ngl', '999', '-fa', 'on', '-ctk', 'q8_0', '-ctv', 'q8_0',
    '-np', $Parallel, '-c', ($Parallel * $SlotContext), '--no-kv-unified',
    '--temp', '0', '--jinja',
    '--image-min-tokens', '1024', '--image-max-tokens', '4096',
    '--api-key-file', "`"$keyFile`"", '--metrics'
)
Start-ClusterProcess 'vision-node' $llamaServer $arguments | Out-Null

foreach ($attempt in 1..120) {
    if (Test-HttpOk "http://127.0.0.1:$Port/health") {
        Write-Host "Desktop vision node ready on port $Port ($Parallel slots x $SlotContext context)."
        return
    }
    Start-Sleep -Seconds 1
}
throw "The desktop vision node did not become ready. See $ClusterLogDir\vision-node.log.err"
