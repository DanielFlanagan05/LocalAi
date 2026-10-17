param(
    [string]$WorkspacePath
)

$ErrorActionPreference = 'Stop'
try {
    $existing = Invoke-RestMethod -Uri 'http://127.0.0.1:8787/api/health' -TimeoutSec 2
    if ($existing.ok -and $existing.engine -eq 'pi' -and $existing.piVersion) {
        Write-Host 'Pi Web UI is already running at http://127.0.0.1:8787. Use its project selector to change folders.'
        return
    }
}
catch { } # No existing Pi server; continue with the normal authenticated launcher.
Add-Type -AssemblyName System.Security
$localAiRoot = 'C:\Users\danfl\dev\LocalAI'
$nodeExe = Join-Path $localAiRoot 'apps\PiHarness\runtime\node-v22.19.0-win-x64\node.exe'
$webUiCli = Join-Path $localAiRoot 'apps\PiWebUI\node_modules\pi-web-ui\bin\pi-web-ui.mjs'
$agentDir = Join-Path $localAiRoot 'config\pi'
$sessionDir = Join-Path $agentDir 'sessions'
$dataDir = Join-Path $localAiRoot 'config\pi-web-ui'
$cipherPath = Join-Path $dataDir 'auth-token.dpapi'
$webWorkspace = $localAiRoot

if ($PSBoundParameters.ContainsKey('WorkspacePath')) {
    if (-not (Test-Path -LiteralPath $WorkspacePath -PathType Container)) {
        throw "Pi Web UI workspace directory does not exist: $WorkspacePath"
    }
    $webWorkspace = (Resolve-Path -LiteralPath $WorkspacePath).ProviderPath
}

foreach ($requiredPath in @($nodeExe, $webUiCli, $agentDir, $sessionDir, $cipherPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required Pi Web UI path is missing: $requiredPath"
    }
}

$cipher = (Get-Content -LiteralPath $cipherPath -Raw).Trim()
if ($cipher -notmatch '^[0-9A-Fa-f]+$' -or ($cipher.Length % 2) -ne 0) {
    throw 'The DPAPI token file is not valid hexadecimal data.'
}
$protectedBytes = New-Object byte[] ($cipher.Length / 2)
for ($i = 0; $i -lt $cipher.Length; $i += 2) {
    $protectedBytes[$i / 2] = [Convert]::ToByte($cipher.Substring($i, 2), 16)
}
$clearBytes = $null
try {
    $clearBytes = [System.Security.Cryptography.ProtectedData]::Unprotect(
        $protectedBytes,
        $null,
        [System.Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    $env:PI_WEB_TOKEN = [Text.Encoding]::Unicode.GetString($clearBytes)
    [Array]::Clear($clearBytes, 0, $clearBytes.Length)
    $env:PI_CODING_AGENT_DIR = $agentDir
    $env:PI_CODING_AGENT_SESSION_DIR = $sessionDir
    $env:PI_COMPUTER_USE_WINDOWS_HELPER_PATH = Join-Path $agentDir 'helpers\pi-computer-use\windows-bridge.exe'
    $env:PI_WEB_DATA_DIR = $dataDir
    $env:PI_WEB_CWD = $webWorkspace
    $env:PI_WEB_HOST = '127.0.0.1'
    $env:PI_WEB_PORT = '8787'

    Write-Host 'Starting Pi Web UI on http://127.0.0.1:8787 (loopback only).'
    Write-Host "Workspace: $webWorkspace"
    Write-Host 'Keep this window open. Press Ctrl+C here to stop the web server.'
    & $nodeExe $webUiCli --no-browser --agent-dir $agentDir --cwd $webWorkspace --data-dir $dataDir --host 127.0.0.1 --port 8787
    exit $LASTEXITCODE
}
finally {
    Remove-Item Env:PI_WEB_TOKEN -ErrorAction SilentlyContinue
    [Array]::Clear($protectedBytes, 0, $protectedBytes.Length)
    if ($clearBytes) { [Array]::Clear($clearBytes, 0, $clearBytes.Length) }
}
