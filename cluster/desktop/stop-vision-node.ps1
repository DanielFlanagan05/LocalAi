$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\lib\cluster-common.ps1')
Stop-ClusterProcess 'vision-node'
