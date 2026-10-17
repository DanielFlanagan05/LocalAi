param([ValidateSet('Load','Unload','Status')][string]$Action = 'Load')
$ErrorActionPreference = 'Stop'
$lms = 'C:\Users\danfl\.lmstudio\bin\lms.exe'
$id = 'dirty-shirley-9b-q4'
$runtime = 'C:\Users\danfl\dev\LocalAI\config\strata\runtime'
function Invoke-Lms([string[]]$Arguments) {
    & $lms @Arguments
    if ($LASTEXITCODE -ne 0) { throw "LM Studio command failed: $($Arguments -join ' ')" }
}
function Get-LocalJson([string]$Uri) {
    try { Invoke-RestMethod -Uri $Uri -TimeoutSec 3 } catch { $null }
}
$mutex = [Threading.Mutex]::new($false, 'Local\LocalAI-Writer-Load')
$locked = $false
try {
    try { $locked = $mutex.WaitOne(120000) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw 'Another model-switch operation is still running.' }
    if ($Action -eq 'Status') { Invoke-Lms @('ps','--json'); return }
    $models = Get-LocalJson 'http://127.0.0.1:1234/api/v0/models'
    $loaded = @($models.data | Where-Object state -eq 'loaded')
    if ($Action -eq 'Unload') {
        # Never interrupt a writer request owned by another live Pi session.
        foreach ($file in Get-ChildItem -LiteralPath $runtime -Filter 'writer.active.*.json' -ErrorAction SilentlyContinue) {
            $owner = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
            if (Get-Process -Id $owner.pid -ErrorAction SilentlyContinue) { throw 'A Pi writer request is active. Stop it or wait before switching models.' }
        }
        if ($loaded | Where-Object id -eq $id) { Invoke-Lms @('unload',$id) }
        return
    }
    if ($loaded | Where-Object id -eq $id) { Write-Output 'Writer model already loaded.'; return }
    if ($loaded.Count) { throw 'Another LM Studio model is loaded. Unload it before starting the writer model.' }
    foreach ($port in @(8080,8081)) {
        $health = Get-LocalJson "http://127.0.0.1:$port/health"
        if (-not $health.loaded) { continue }
        $metrics = Get-LocalJson "http://127.0.0.1:$port/metrics"
        if (-not $metrics -or $metrics.live.queued -gt 0 -or $metrics.live.state -notin @('idle','ready','unloaded')) {
            throw "Strata on port $port may be busy. Finish or stop its request before switching."
        }
        Invoke-RestMethod -Uri "http://127.0.0.1:$port/unload?wait=10" -Method Post -ContentType application/json -Body '{}' -TimeoutSec 15 | Out-Null
        if ((Get-LocalJson "http://127.0.0.1:$port/health").loaded) { throw 'Strata did not unload; refusing a second model load.' }
    }
    $os = Get-CimInstance Win32_OperatingSystem
    if ([double]$os.FreePhysicalMemory * 1024 -lt 10GB) { throw 'Need at least 10 GiB available RAM before loading the writer model.' }
    if (-not $models) { Invoke-Lms @('server','start','--bind','127.0.0.1','--port','1234') }
    Invoke-Lms @('load','dirty-shirley-writer-v4-9b-uncensored','--context-length','8192','--gpu','max','--parallel','1','--ttl','300','--identifier',$id,'--yes')
}
finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
