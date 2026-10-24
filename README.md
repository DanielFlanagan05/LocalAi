# Current ready-to-use setup — October 21, 2026

Use [getting-started.html](docs/getting-started.html) for the current commands and five curated ComfyUI workflows. Plain `pi` and `hermes` select Qwen Flash-Next EXL3/Kyojin; `pi-local` and `hermes-local` select Qwen 27B Q4/Gufo. New `pi-gufo` and `hermes-gufo` select Unsloth Flash-Next Q4/MTP on Gufo 0.20 with a qualified 200K live cache. See [the targeted Gufo results and installed inventory](docs/gufo-flash-results.html): fresh prefill clears 1,200 tok/s through 200K, but 1,500 remains unconfirmed. The user authorized this focused testing and an extra Qwen download without removing the current model, relaxing the earlier 600 GB budget (now an 850 GB installer ceiling). `run-comfyui` stays in the foreground and Ctrl-C stops it; `stop-comfyui` stops it from another terminal. Earlier reports describe historical tests and models that may have been removed. Do not resume unrelated acceptance campaigns without user permission.

Video follow-up: [timings, cache controls and optimization results](docs/video-performance.html). Full 480p clips took 7m 14s (H3 with audio) and 9m 19s (Wan AIO); opt-in caching improved short same-family repeats. The extra H3 attention node did not improve the full run and remains disabled. Halogen is retained as a deferred test in the plan.

Additional uncensored LLM: `pi-hauhau` / `hermes-hauhau` run HauhauCS Qwen3.5-27B Aggressive Q4_K_M on Gufo. See [installation and reproduction steps](docs/hauhau-gufo-setup.html); text-only with a verified metadata-only chat-template compatibility copy.

# LocalAI

Local launchers, Pi configuration and extensions, the local resource-monitor plugin, ComfyUI helper scripts, and saved workflows.

Machine-local state is intentionally excluded from Git. This includes model weights, chat sessions and logs, authentication material, downloaded runtimes, installed dependencies, generated outputs, caches, and test artifacts. Linux model files use the shared user-level store below; the original Windows configuration uses its machine-local model directory.

The original Windows launchers retain their machine-specific configuration. The Linux setup below is separate.

## Flow Z13 / CachyOS

See [the device plan](docs/flow-z13-plan.md), [Linux operation and verification](docs/linux-setup.md), and [measured validation results](docs/validation-status.md).

```sh
python scripts/linux/install.py --tooling --harnesses
sudo bash scripts/linux/install-system.sh
python scripts/linux/install.py --engines --media
python scripts/linux/install.py --models baseline coding
```

Models live at `$XDG_DATA_HOME/localai/models` (normally `~/.local/share/localai/models`), **outside this repository**. Any application or repository can read them directly. Set `LOCALAI_MODEL_DIR` to use another shared disk. `localai models-path` prints the actual location; `~/.config/localai/env.sh` exports it for other projects. ComfyUI uses the same store through extra model search paths.

Session transcripts, context/KV checkpoints, logs, private provider configuration, and generated media live under XDG state/cache/data directories outside Git. `.gitignore` also protects model weights and nested harness session/context directories if someone creates them in the checkout. Keep only scripts, public configuration, workflows, and synthetic test definitions in Git.

From any project directory:

```sh
pi-local                       # shared Qwen 27B / two-session Gufo profile
opencode-local                 # OpenCode CLI; desktop entry is also installed
hermes-local
claude-local                   # separate llama.cpp / Anthropic-compatible route
comfyui-local                  # starts ComfyUI and opens its browser
localai doctor
localai status
localai stop                   # finish active work before switching models
localai start vision-clearcase
localai clearcase --workers 2   # synthetic ClearCase page extraction
```

For a different Pi/OpenCode/Hermes profile, set `LOCALAI_PROFILE`, for example `LOCALAI_PROFILE=vision-small pi-local`. The controller refuses to replace a different running model automatically. Runtime installation alone does not establish model accuracy or long-context stability: retain the benchmark results and check their status.
