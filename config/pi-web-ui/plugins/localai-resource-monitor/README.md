# LocalAI compute guard

Pi Web UI keeps multiple named conversations. This plugin limits active model runs to two and only permits a second when Windows reports at least 12 GiB free RAM, at least 6 GiB free RX 7900 XT VRAM, and peak RX GPU-engine utilization below 85%. If telemetry is unavailable or headroom is insufficient, it interrupts the oldest active Pi run; Pi's transcript and partial answer remain available for continuation. It never deletes a session or unloads a model server.

The Windows helper discovers the RX 7900 XT via DXGI on every sample, matching its vendor/device ID and description. Its Windows LUID and dedicated memory size are discovered, not hardcoded, so reboot-induced LUID changes do not break telemetry. `GPU Adapter Memory\Total Committed` is used conservatively against the dedicated-memory total. RAM availability comes from Node's Windows OS memory query. WMI AdapterRAM is not used.

October 15 repair: run identity includes both browser client and conversation ID. The local Pi Web UI routing patch selects that exact owner instead of an arbitrary browser client; ambiguous legacy IDs fail closed. Removed owners are treated as already stopped. Interruption errors retain the active record, expose the underlying error, and notify only once per unchanged error rather than spamming every monitor tick. This never deletes conversation files. The local app patch must be reviewed/preserved when upgrading Pi Web UI.

Use the **Compute status** composer action to display current readings. If Windows refuses GPU performance counters, the monitor reports that and enforces one active run. Run the UI as the normal Windows user; do not elevate the agent to work around counter permissions.

Pause means aborting the active generation, not freezing its KV cache. The prompt and partial response are retained in the Pi transcript; resuming later reconstructs context from that transcript and requires a fresh model request. Model weights can remain resident in LM Studio or Strata after a Pi run is interrupted.

Run unit tests with the bundled Node runtime:

```powershell
& C:\Users\danfl\dev\LocalAI\apps\PiHarness\runtime\node-v22.19.0-win-x64\node.exe --test C:\Users\danfl\dev\LocalAI\config\pi-web-ui\plugins\localai-resource-monitor\index.test.mjs
```
