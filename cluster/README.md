# Vision cluster

Always-on llama.cpp vision servers on three machines, behind one OpenAI-compatible gateway on
the desktop. Built to speed up ClearCase's local AI step: it currently runs about 32 vision
calls one at a time and reloads the model for every call. With the cluster, the servers stay
loaded, each one takes several requests at once, and cross-checks go to *different* models.

```
                     LiteLLM gateway  http://127.0.0.1:4000/v1   (desktop, localhost only)
                    /                 |                          \
 desktop (7900 XT, Vulkan)    flowz13 (Strix Halo, 112 GiB GTT)    macbook (M4 Max, Metal)
 :9101 qwen3-vl-8b  x4        :9101 qwen3-vl-8b       x4           :9101 qwen3-vl-8b x4
                              :9102 internvl3-14b     x2           :9103 gemma3-12b  x1
                              :9103 gemma3-12b        x2
                              :9104 qwen3-vl-30b-a3b  x2  (Q8_0)
```
`xN` = parallel slots, each with 16K context (ClearCase's `-c 16384`). Nodes are reached by
Tailscale MagicDNS (`*.tail632a33.ts.net`), which uses the LAN directly when it can.

| Gateway name | Group | Purpose |
|---|---|---|
| `cc-extract` | `qwen3-vl-8b` (desktop, Z13, Mac; least-busy) | page/crop transcription fan-out |
| `cc-verify-a` | `internvl3-14b` (Z13) | independent second read |
| `cc-verify-b` | `gemma3-12b` (Z13, Mac) | independent third read |
| `cc-judge` | `qwen3-vl-30b-a3b` (Z13) | tie-breaker when reads disagree |

Every server uses the llama.cpp version ClearCase pins (b11216), `--temp 0`,
`--image-min-tokens 1024 --image-max-tokens 4096`, a q8_0 KV cache and `response_format`
JSON-schema support. Models are pinned to the revisions and SHA-256 values in `models.tsv`.
A node that is offline is benched for 60 s after one failure, so the gateway routes around it.

## Keys
`cluster/.env` (git-ignored) is created on the first gateway setup:
- `CLUSTER_API_KEY`: shared by every llama-server. Pass it to the Z13 and Mac installers.
- `LITELLM_MASTER_KEY`: what clients send to the gateway as `Authorization: Bearer ...`.

## Setup
Recommended order: Z13 first (it is useful on its own), then the gateway, then the desktop and
Mac nodes.

### 1. Gateway (desktop)
```powershell
powershell -ExecutionPolicy Bypass -File cluster\gateway\setup-gateway.ps1
bin\start-vision-gateway.cmd
```

### 2. Z13 (CachyOS)
Copy this `cluster` folder to the Z13 (for example `scp -r cluster flowz13:~/`). Then:
```bash
# Once: set UMA frame buffer to 512MB in BIOS, then let the iGPU map ~112 GiB and reboot.
CLUSTER_API_KEY=... ./cluster/z13/install.sh --configure-gtt --skip-models
sudo reboot
# Build, download (~58 GB), and start the four services.
CLUSTER_API_KEY=... ./cluster/z13/install.sh            # add --rocm to also build ROCm
```
Operations: `systemctl status 'llama-vision@*'`, `journalctl -u llama-vision@qwen3-vl-8b -f`.
To try ROCm, benchmark both builds, then set `LLAMA_SERVER` in `/etc/llama-vision/common.env`
and run `sudo systemctl restart 'llama-vision@*'`.

### 3. Desktop node (7900 XT)
```powershell
# Elevated, once:
powershell -ExecutionPolicy Bypass -File cluster\desktop\add-firewall-rule.ps1
bin\start-vision-node.cmd        # refuses while Strata is running; -Force overrides
bin\stop-vision-node.cmd
```
This uses ClearCase's verified Qwen3-VL-8B files in `%LOCALAPPDATA%\ClearCase\models` and the
b11216 Vulkan build in `tools\llama-b11216-vulkan`, pinned to `Vulkan0` (the 7900 XT, not the
iGPU).

### 4. MacBook
Rename the machine to `macbook` in the Tailscale admin console. Copy this folder over, then:
```bash
CLUSTER_API_KEY=... ./cluster/mac/install.sh
```
Logs: `~/llama-vision/logs/`. Stop a model with
`launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.localai.llama-vision.<model>.plist`.

## Verify
```powershell
bin\vision-cluster-health.cmd
$py = 'cluster\gateway\.venv\Scripts\python.exe'
& $py cluster\scripts\vision-smoke-test.py --model cc-extract --concurrency 12 --requests 24
& $py cluster\scripts\vision-smoke-test.py --model cc-extract,cc-verify-a,cc-verify-b,cc-judge
```
The first run should spread its requests across every online `*/qwen3-vl-8b` deployment and
show a speedup well above 1x. The second checks that every model returns schema-valid JSON and
reports how often the models agree. Stop any one node and run it again: requests should still
succeed.

## Benchmarks
Record `llama-bench` and smoke-test numbers here once the nodes are up.

| Node | Model | pp t/s | tg t/s | Smoke test (24 req) |
|---|---|---|---|---|
| desktop | qwen3-vl-8b | | | |
| z13 | qwen3-vl-8b | | | |
| mac | qwen3-vl-8b | | | |

## Later: ClearCase integration (not done)
- Replace the per-call `llama-mtmd-cli` launches with HTTP calls to the gateway, sending the
  same JSON schemas through `response_format`.
- Send pages and crops concurrently, up to the total slot count (about 12).
- Send the second identity read and crop re-reads to `cc-verify-a` / `cc-verify-b`, and
  disagreements to `cc-judge`.
- Send JPEG (quality about 90) instead of 4096 px PNG to keep uploads small.
