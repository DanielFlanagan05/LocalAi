# Shared helpers for the desktop side of the vision cluster. Dot-source this file.

$script:LocalAiRoot = 'C:\Users\danfl\dev\LocalAI'
$script:ClusterRoot = Join-Path $LocalAiRoot 'cluster'
$script:ClusterEnvPath = Join-Path $ClusterRoot '.env'
$script:ClusterLogDir = Join-Path $LocalAiRoot 'logs'
$script:ClusterStateDir = Join-Path $LocalAiRoot 'temp'

function New-ClusterSecret {
    $bytes = [byte[]]::new(32)
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return ([Convert]::ToBase64String($bytes) -replace '[+/=]', '')
}

# Creates cluster/.env with fresh keys on first use, then loads it into this process.
function Import-ClusterEnv {
    if (-not (Test-Path -LiteralPath $ClusterEnvPath)) {
        @(
            "CLUSTER_API_KEY=$(New-ClusterSecret)"
            "LITELLM_MASTER_KEY=sk-$(New-ClusterSecret)"
        ) | Set-Content -LiteralPath $ClusterEnvPath -Encoding ascii
        Write-Host "Created $ClusterEnvPath with new cluster keys. Copy CLUSTER_API_KEY to the Z13 and Mac installers."
    }
    foreach ($line in Get-Content -LiteralPath $ClusterEnvPath) {
        if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim(), 'Process')
        }
    }
}

function Test-HttpOk([string]$Url, [hashtable]$Headers = @{}) {
    try {
        Invoke-RestMethod -Uri $Url -Headers $Headers -TimeoutSec 2 | Out-Null
        return $true
    }
    catch { return $false }
}

function Start-ClusterProcess([string]$Name, [string]$FilePath, [string[]]$Arguments) {
    New-Item -ItemType Directory -Force -Path $ClusterLogDir, $ClusterStateDir | Out-Null
    $log = Join-Path $ClusterLogDir "$Name.log"
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    Set-Content -LiteralPath (Join-Path $ClusterStateDir "$Name.pid") -Value $process.Id
    Write-Host "Started $Name (PID $($process.Id)). Logs: $log"
    return $process
}

function Stop-ClusterProcess([string]$Name) {
    $pidFile = Join-Path $ClusterStateDir "$Name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) {
        Write-Host "$Name is not running (no PID file)."
        return
    }
    $processId = [int](Get-Content -LiteralPath $pidFile)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        # taskkill /T also stops child processes (LiteLLM runs under a Python launcher).
        taskkill.exe /PID $processId /T /F | Out-Null
        Write-Host "Stopped $Name (PID $processId)."
    }
    else {
        Write-Host "$Name was not running."
    }
    Remove-Item -LiteralPath $pidFile -Force
}
