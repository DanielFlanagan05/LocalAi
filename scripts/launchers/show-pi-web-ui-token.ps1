$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
$cipherPath = 'C:\Users\danfl\dev\LocalAI\config\pi-web-ui\auth-token.dpapi'
if (-not (Test-Path -LiteralPath $cipherPath)) {
    throw "Pi Web UI token file is missing: $cipherPath"
}
$cipher = (Get-Content -LiteralPath $cipherPath -Raw).Trim()
if ($cipher -notmatch '^[0-9A-Fa-f]+$' -or ($cipher.Length % 2) -ne 0) {
    throw 'The DPAPI token file is not valid hexadecimal data.'
}
$protectedBytes = New-Object byte[] ($cipher.Length / 2)
for ($i = 0; $i -lt $cipher.Length; $i += 2) {
    $protectedBytes[$i / 2] = [Convert]::ToByte($cipher.Substring($i, 2), 16)
}
$clearBytes = [System.Security.Cryptography.ProtectedData]::Unprotect(
    $protectedBytes,
    $null,
    [System.Security.Cryptography.DataProtectionScope]::CurrentUser
)
try { [Text.Encoding]::Unicode.GetString($clearBytes) }
finally {
    [Array]::Clear($protectedBytes, 0, $protectedBytes.Length)
    [Array]::Clear($clearBytes, 0, $clearBytes.Length)
}
