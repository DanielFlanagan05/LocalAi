# Run once from an elevated PowerShell. Lets the desktop vision node (port 9101) accept
# connections from the tailnet and the home LAN only. The gateway (port 4000) stays on
# 127.0.0.1 and needs no rule.
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$name = 'LocalAI vision node (9101)'
Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort 9101 `
    -RemoteAddress '100.64.0.0/10', '192.168.4.0/24' -Profile Any | Out-Null
Write-Host "Added firewall rule '$name'."
