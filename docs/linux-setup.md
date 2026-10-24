# Linux setup and operation

**Current operational guide:** [getting-started.html](getting-started.html). The October 21 cleanup retained only the selected model families and four native ComfyUI workflows. Historical installation groups and experiments below may no longer exist in the active catalog; do not use them to reinstall removed models. The current ceiling is 600 GB decimal.

## Files and privacy

| Data | Default location |
|---|---|
| Shared weights | `~/.local/share/localai/models/<publisher>/<repository>/` |
| Runtime checkouts/environments | `~/.local/share/localai/apps/` |
| Global commands | `~/.local/bin/` |
| Public endpoint/path settings | `~/.config/localai/` |
| Harness sessions, transcripts and reports | `~/.local/state/localai/` |
| Download, GPU and context caches | `~/.cache/localai/` |
| Generated media | `~/.local/share/localai/outputs/` |

XDG overrides are supported. Set `LOCALAI_MODEL_DIR` before installation to put weights on another shared disk. Other repositories can use those absolute paths or the same loopback API; there is no repository access restriction. Source `~/.config/localai/env.sh` from Bash/Zsh to export the model path. Fish and new terminal command paths are configured by the installer. Existing Windows files are preserved.

The model catalog is tracked; the resolved download locks, hashes, installation status and runtime state are private local files. Inspect `~/.local/state/localai/installation.json`, `runtime-lock.json`, `models.lock.json`, and `verified-models.json` for actual installation/verification status. Re-run a failed installation stage after fixing its prerequisite. Never force-add ignored session/weight files.

## Install in stages

```sh
python scripts/linux/install.py --tooling --harnesses
sudo bash scripts/linux/install-system.sh
python scripts/linux/install.py --engines --media
python scripts/linux/install.py --models baseline
python scripts/linux/install.py --models coding
```

`baseline` installs the concurrent 27B Q4/draft and bundled 8B vision model. `coding` installs the tested quality Qwen EXL3 pack; `glm` and `mimo` install the separate large challengers. `coding-experiments` retains the 27B Q8 and larger Unsloth Q4/Gufo downloads, and `quality-q3` selects the Vulkan fallback. These groups share identical repository files rather than duplicating weights.

Additional model groups for the comparison campaign:

```sh
python scripts/linux/install.py --models glm mimo
python scripts/linux/install.py --models media-images media-flux media-video media-ltx
```

The system script performs a normal CachyOS/Arch full upgrade and installs dependencies; its interactive package prompts require the user. It does not change firmware, disable IOMMU, or reboot. The user installer uses pinned Node and uv archives, isolated Python environments, official harness packages and selected upstream engines. Runtime repositories and build output live outside this checkout.

To retry just the reference/container engines:

```sh
python scripts/linux/install.py --engines --engine llama gufo
```

Rootless Podman requires `crun`, host GPU device access, and subordinate UID/GID mappings. Check `podman info` before launching Gufo. No privileged container is used.

After reducing BIOS UMA to its minimum and rebooting, configure dynamic memory:

```sh
sudo bash scripts/linux/install-system.sh --memory
```

Reboot manually, then run `localai doctor`. Roll back by removing `/etc/modprobe.d/99-localai-ttm.conf`, restoring its backup if present, running `sudo mkinitcpio -P`, and rebooting. The 112 GiB ceiling is a mapping allowance, not a promise every 112 GiB allocation will fit beside the desktop.

## Launch and switch

`pi-local`, `opencode-local`, `opencode-desktop-local`, `hermes-local`, `claude-local` and `comfyui-local` retain your working directory. Desktop entries are installed. `localai profiles` lists full settings. Finish active work and use `localai stop` before switching profiles; automatic switches cannot kill another conversation. The stop command explicitly cancels the owned runtime and keeps transcripts.

Choose an alternate model from any repository with, for example, `localai stop` followed by `LOCALAI_PROFILE=coding-quality pi-local` (or `opencode-local`, `opencode-desktop-local`, `hermes-local`). `coding-quality` and `vision-quality` use the tested Kyojin Qwen EXL3 configuration; `vision-max` selects GLM. The original Unsloth Q4/Gufo candidates remain under the explicit `*-q4-gufo-experimental` names. `coding-quality-q3` is the Vulkan fallback. Selected profiles also determine helper/title/compression models. Alternate Hermes/Claude profiles keep separate private state; the default homes retain existing history. `claude-local` defaults to its tested Messages-compatible profile; other engines remain experimental for that harness. ComfyUI always starts its own media profile.

`localai start PROFILE` runs a detached supervised process with a private log. Alternatively run `systemctl --user daemon-reload` and `systemctl --user start localai@PROFILE` to use the installed service template. Do not start both. Only one profile owns the compute device at a time; engine-side sessions share its weights. No cloud fallback is configured.

On this device's initial 96 GiB firmware reservation, launchers select `coding-reference` (Vulkan), and its host snapshot cache is capped at 1 GiB. Gufo loading is blocked until the reservation is reduced. The small cache can cause expensive prompt re-evaluation at long context; it is a temporary operating profile. After the firmware change and TTM setup, run `localai configure` to select Gufo and regenerate settings.

Measured 27B Gufo snapshots at 200K require about 13.4 GB each. After the original 32 GiB cache exhausted the memory reserve during an accumulated-context campaign, the concurrent profiles now use a 26 GiB RAM cache, 40 GiB disk cache, and 16 GiB disk staging ceiling; the previous 8 GiB disk default rejected them. The staging value is a transfer/queue limit for this model, not an extra eager allocation. Flash profiles use a separate 16 GiB disk cache. Large-checkpoint restart restoration must be verified independently of live warm continuations.

## ClearCase and context checks

```sh
localai start vision-clearcase
localai clearcase --repo /home/danfl/dev/ClearCase --workers 2
localai clearcase --workers 4
localai stop
localai start vision-small
localai bench vision-small --input-tokens 200000 --workers 2
```

The ClearCase runner imports the real transcription prompt, creates synthetic pages, validates its transcription schema, and saves aggregate score/timing metadata in the result. Synthetic images and parsed visible JSON responses remain in private state for auditing and re-scoring. It is not the Windows production app and does not read existing case inputs. Engines lacking structured-output support can be compared using `--prompt-only-schema`, with that limitation recorded.

For a larger model, download its group and select `vision-quality` or `vision-max`. Use one worker and `--prompt-only-schema` for those Kyojin profiles. Most general chat/vision profiles use 262144 context; `vision-clearcase` deliberately matches ClearCase's independent 16384-token page requests. Test long-context vision separately with image attachments as well as text-history recall.

`vision-balanced` uses the already shared 27B Q8 weights and Q4 repository's matching projector through Vulkan. It is the intermediate document-quality comparison. `messages-compatible` derives its template from the verified Qwen model and moves later system/developer updates ahead of conversation turns, preserving their order and priority. This avoids Qwen's rejection of interleaved system updates; changing those instructions can still invalidate prompt caching.

```sh
localai bench coding-concurrent --input-tokens 8192 --workers 2 --repeats 3
localai bench coding-concurrent --input-tokens 200000 --workers 2 --repeats 3
```

The serving probe records actual server input usage, recall and warm-continuation time. It fails if usage cannot be verified. It is not a coding-quality score or a substitute for the complete campaign in the device plan.

Kyojin launchers enable ten-second SSE keepalive comments (`KYOJIN_SSE_PING_S=10`) so long silent prefills do not exceed clients' idle-stream timeouts. These comments do not count as generated tokens or time to first token. Large Kyojin profiles use bounded prefill chunks: 2048 for GLM and 1024 for the Qwen/MiMo memory experiments. `mimo-text` tests 225280 context with its vision tower and speculative drafter disabled; `mimo-experimental` retains both at 262144. The text fallback allows 16384 output tokens and sets tool-specific compaction thresholds to preserve about 200K input tokens. The MiMo adapter selects ExLlama's 8-bit KV cache without editing the vendor checkout.

`qwen-exl3-512k-plain` and `qwen-exl3-384k-plain` disable MTP and reduce its history budget, retaining 8-bit KV at extended context. They trade decode acceleration for memory headroom. The 512K profile passed one 500081-input-token recall request and cached continuation; sustained extended-context coding remains unaccepted. The 384K fallback has not been tested. See the validation record for memory and swap observations.

After the memory configuration is ready, run `localai campaign coding-concurrent` for harness/tool checks, ten coding tasks, and the 8K–225K context ladder with one and two workers. It stops on failure and saves partial results outside Git. Run it without other clients for comparable timing. Two-hour/overnight, cancellation/recovery, media and document-accuracy campaigns remain separate acceptance work.

`localai cancel-test coding-concurrent` checks stream disconnect cancellation, the active-request counter returning to zero, and an exact follow-up reply from the same runtime process. It refuses to start while other requests are active. This is an API check; harness UI cancellation, transcript restoration and compaction still require separate tests.

## Development checks

```sh
~/.local/share/localai/apps/support/bin/python -m unittest discover -s scripts/linux -p 'test_*.py' -v
python -m py_compile scripts/linux/*.py
bash -n scripts/linux/*.sh
```

Keep reports honest: record unsupported CLI flags, missing packages, model failures, memory refusals, untested media and incomplete soak tests. Do not mark those as passed based on installation success.

## Media validation

`localai media-test --model z-image` generates a small image; `qwen-image`, `chroma` and `flux2` select the other installed image families. Video smoke tests use `--model h3 --frames 22 --steps 8`, `--model wan-aio --frames 17 --steps 4`, or `--model ltx --frames 17 --steps 8`. The default 320×192 clips test loading, execution and encoding; they do not establish quality at the models' trained resolutions. Reports include ffprobe metadata and stay outside Git. H3 requires a 17k+5 frame count, Wan uses 4k+1, and LTX uses 8k+1 with the baseline's fixed eight-step distilled schedule.

Load the `baseline_*_api.json` files in `workflows/linux/baselines/` through ComfyUI's Open/Load dialog or drag them into its canvas. The installed frontend imports API JSON as an editable graph. Copies are installed in the private ComfyUI workflow directory. These seven baselines use the shared installed models and omit optional prompt-enhancement add-ons. Image defaults are 1024 pixels; video defaults are about five seconds at 832×480. The LTX baseline is a single distilled pass with native audio; the advanced native template retains its additional upscaling stage. For Wan image-to-video, replace the labelled placeholder first-frame node with a Load Image node and choose your image. Regenerate exports after changing the graph builders with `python scripts/linux/export_media_baselines.py`.

The imported advanced Qwen templates also reference optional Qwen3.5 prompt enhancers; the LTX template references an optional Gemma prompt-enhancement LoRA. Those add-ons are not part of the baseline download. The separate Wan FP16/turbo-LoRA template requires the optional `media-wan` group and its acceleration LoRAs; use the installed Wan AIO route for the baseline comparison. All nine templates' node types were verified against the installed ComfyUI node catalog; model availability and successful generation are separate checks.

The remaining acceptance coordinator is `scripts/linux/remaining_acceptance.py`. It writes resumable progress and each job's output to a private `--directory`, never runs two GPU jobs together, observes the 40 GiB free-disk floor, and records failures without claiming acceptance. Do not launch a second coordinator or another inference workload while it runs. Its final eight-hour reliability job requires the primary short checks and large-checkpoint restart to pass first. The first two hours mix real synthetic file edits, hidden assertions and harness calls; later requests check continuation over the remaining elapsed interval. Actual wall time determines milestones. New telemetry resolves the Gufo container's host PID so model-process swap is visible separately from global swap activity.

Native recovery probes are available as `localai recovery-test`; large Gufo checkpoint restoration is `localai cache-restart-test`, and timed reliability is `localai reliability-test`. `localai coding-test PROFILE --input-tokens 485000` uses the real Pi SDK to attach calibrated synthetic history, checks the reported input count on every model turn, and limits each reply to 8192 tokens with a 16384-token compaction reserve for this test. It does not change the installed harness defaults. ClearCase's `--variants low high rotated crop` evaluates synthetic page rendering changes, with constrained versus prompt-only schema modes labelled separately. Media comparisons accept `--prompt` for a common scene and `--reference` for Qwen/FLUX editing or Wan I2V; seven baseline and three reference graphs pass offline schema validation. Reference files, hashes and submitted workflows stay private. 720p and 1080p tests use padded 1280×736 and 1920×1088 dimensions to satisfy the model frame grids.

ComfyUI uses `--cache-none` and an 8 GiB GPU reserve. Both the initial defaults and a 24/48 GiB cache-headroom configuration retained enough data across large model families to trigger the supervisor's RAM guard while loading Wan after H3. Disabling output caching trades repeat-run speed for lower retention; the shared model store remains intact. Treat successful generation from a fresh server and successful switching between families as separate acceptance checks.

Claude Code now defaults to the custom model ID `messages-compatible`. The earlier `claude-compatible` profile is retained for historical comparisons, but its `claude-` prefix prevents the context override from applying with compaction enabled. The custom ID allows `CLAUDE_CODE_MAX_CONTEXT_TOKENS=262144` and the 225280-token compaction window to apply together; see [Claude Code's custom-ID rules](https://code.claude.com/docs/en/model-config#which-ids-claude_code_max_context_tokens-applies-to). Do not disable compaction to work around the old ID.

Extended coding fixtures use calibrated numeric CSV reference data. Pi estimates fresh imported messages at 3.5 characters/token before receiving a measured usage anchor; the previous prose padding made it overestimate the context and clamp replies to one token. Every scored coding turn must still report at least the requested actual input-token count. An API/transport failure now stops the coding suite and receives an infrastructure-failure status rather than generating a misleading ten-task quality score.

## Pi model labels

Readable labels live in `config/linux/profiles.json` as `display_name`. Pi stores these as model names while retaining its API IDs. This Pi version displays IDs in picker rows, so `scripts/linux/configure_pi_labels.py` also applies a narrow local UI patch (localai rows only) to the source and bundled renderer. Original files are backed up under `~/.local/state/localai/pi-label-backups/`. The harness installer reapplies the patch after installing Pi. If Pi is upgraded manually, rerun `~/.local/share/localai/apps/support/bin/python scripts/linux/configure_pi_labels.py` and restart Pi. It updates only labels, not defaults or sessions.

### Running ComfyUI alongside inference

`run-comfyui` can run alongside an inference model such as `gufo-hauhau`. The controller warns that they share GPU compute and unified memory; it checks current available memory against the requested profile's estimate and reserve, rather than treating the GPU as exclusively owned. Both runtime supervisors still stop their own process if the memory reserve is exhausted. Actual workflow peaks and inference cache growth can exceed initial usage.

`localai status` and `localai doctor` include a `runtimes` list. `stop-comfyui` and ComfyUI's Ctrl-C stop only ComfyUI. `localai stop gufo-hauhau` targets that inference profile; bare `localai stop` stops inference when present, otherwise ComfyUI. Switching between inference profiles or between normal and cached ComfyUI still requires stopping the current occupant of that slot first.

## Wayland clipboard

Pi uses `wl-copy` on Wayland. wl-clipboard 2.3.0 is installed user-locally under `~/.local/share/localai/apps/wl-clipboard/`, with commands in `~/.local/bin/`. The CachyOS package was downloaded using its trusted sync-database URL and verified against its SHA-256; the installation manifest is in that app directory. This user installation is not registered in pacman. Future system dependency installation also includes `wl-clipboard`. Ctrl+X copies Pi’s last assistant response; Konsole’s Ctrl+Shift+C copies terminal-selected text. Clipboard access was verified without replacing the user’s existing clipboard content.

## Pi exit alias

`/exit` is registered by `config/pi/extensions/localai-exit.ts` and installed in the shared Pi extensions directory. It calls Pi’s orderly `ctx.shutdown()` API, using the same shutdown path as `/quit`. Reload extensions with `/reload`, or restart Pi. The installer preserves this extension on future setup runs. Verified in a real no-session Pi process: `/exit` exited cleanly with status0 without model inference.
