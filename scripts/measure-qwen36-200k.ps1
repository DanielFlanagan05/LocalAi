param([int]$Seconds = 180, [string]$TestDirectory = 'C:\Users\danfl\dev\LocalAI\logs\qwen36-200k-check')
$ErrorActionPreference = 'Stop'
$testRoot = $TestDirectory
New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class DesktopMemoryProbe {
  [StructLayout(LayoutKind.Sequential)]
  public struct MemoryStatus {
    public uint Length, Load;
    public ulong TotalPhysical, AvailablePhysical, TotalPageFile, AvailablePageFile, TotalVirtual, AvailableVirtual, Extended;
  }
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool GlobalMemoryStatusEx(ref MemoryStatus status);
  [DllImport("user32.dll")]
  public static extern IntPtr GetShellWindow();
  [DllImport("user32.dll", SetLastError=true)]
  public static extern IntPtr SendMessageTimeout(IntPtr window, uint msg, UIntPtr wparam, IntPtr lparam, uint flags, uint timeout, out UIntPtr result);
}
'@
$samplePath = Join-Path $testRoot 'memory-samples.jsonl'
$writer = [IO.StreamWriter]::new($samplePath, $false, [Text.UTF8Encoding]::new($false))
$writer.AutoFlush = $true
$clock = [Diagnostics.Stopwatch]::StartNew()
$counterPaths = @('\GPU Adapter Memory(*)\Dedicated Usage', '\GPU Adapter Memory(*)\Shared Usage',
                  '\GPU Process Memory(*)\Dedicated Usage', '\GPU Process Memory(*)\Shared Usage')
try {
  while ($clock.Elapsed.TotalSeconds -lt $Seconds) {
    $sampleClock = [Diagnostics.Stopwatch]::StartNew()
    $memory = [DesktopMemoryProbe+MemoryStatus]::new()
    $memory.Length = [Runtime.InteropServices.Marshal]::SizeOf($memory)
    if (-not [DesktopMemoryProbe]::GlobalMemoryStatusEx([ref]$memory)) { throw 'Physical memory telemetry failed.' }
    $engine = @(Get-Process -Name strata,strata-desktop -ErrorAction SilentlyContinue)
    $engineIds = @($engine | ForEach-Object { $_.Id })
    $counters = @((Get-Counter -Counter $counterPaths -ErrorAction SilentlyContinue).CounterSamples)
    $gpuAdapter = @($counters | Where-Object { $_.Path -match '\\gpu adapter memory\(' })
    $gpuProcess = @($counters | Where-Object {
      if ($_.InstanceName -match '^pid_(\d+)_') { $engineIds -contains [int]$Matches[1] } else { $false }
    })
    $adapterDedicated = [double](($gpuAdapter | Where-Object { $_.Path -match '\\dedicated usage$' } | Measure-Object CookedValue -Sum).Sum)
    $adapterShared = [double](($gpuAdapter | Where-Object { $_.Path -match '\\shared usage$' } | Measure-Object CookedValue -Sum).Sum)
    $engineDedicated = [double](($gpuProcess | Where-Object { $_.Path -match '\\dedicated usage$' } | Measure-Object CookedValue -Sum).Sum)
    $engineShared = [double](($gpuProcess | Where-Object { $_.Path -match '\\shared usage$' } | Measure-Object CookedValue -Sum).Sum)
    $shellResult = [UIntPtr]::Zero
    $shellClock = [Diagnostics.Stopwatch]::StartNew()
    $shellWindow = [DesktopMemoryProbe]::GetShellWindow()
    $shellOk = $shellWindow -ne [IntPtr]::Zero -and [DesktopMemoryProbe]::SendMessageTimeout($shellWindow, 0, [UIntPtr]::Zero, [IntPtr]::Zero, 2, 1000, [ref]$shellResult) -ne [IntPtr]::Zero
    $shellClock.Stop()
    $guard = $null
    try { $guard = Get-Content -LiteralPath 'C:\Users\danfl\dev\LocalAI\config\strata\runtime\qwen36.status.json' -Raw | ConvertFrom-Json } catch {}
    $row = [ordered]@{
      time=(Get-Date).ToString('o'); elapsed_seconds=[math]::Round($clock.Elapsed.TotalSeconds,3)
      system_ram_total_bytes=$memory.TotalPhysical; system_ram_available_bytes=$memory.AvailablePhysical
      system_ram_used_bytes=($memory.TotalPhysical-$memory.AvailablePhysical)
      system_commit_used_bytes=($memory.TotalPageFile-$memory.AvailablePageFile)
      all_adapters_dedicated_gpu_bytes=[long]$adapterDedicated; all_adapters_shared_gpu_bytes=[long]$adapterShared
      engine_pids=$engineIds; engine_working_set_bytes=[long](($engine | Measure-Object WorkingSet64 -Sum).Sum)
      engine_private_commit_bytes=[long](($engine | Measure-Object PrivateMemorySize64 -Sum).Sum)
      engine_dedicated_gpu_bytes=[long]$engineDedicated; engine_shared_gpu_bytes=[long]$engineShared
      shell_responded=$shellOk; shell_response_ms=[math]::Round($shellClock.Elapsed.TotalMilliseconds,3)
      guard_state=$guard.state; guard_reason=$guard.reason
    }
    $writer.WriteLine(($row | ConvertTo-Json -Depth 4 -Compress))
    if (-not (Test-Path -LiteralPath (Join-Path $testRoot 'monitor.ready'))) {
      New-Item -ItemType File -Path (Join-Path $testRoot 'monitor.ready') -Force | Out-Null
    }
    if (Test-Path -LiteralPath (Join-Path $testRoot 'monitor.stop')) { break }
    $remainingMs = 500 - $sampleClock.Elapsed.TotalMilliseconds
    if ($remainingMs -gt 0) { Start-Sleep -Milliseconds ([int]$remainingMs) }
  }
}
finally { $writer.Dispose() }
