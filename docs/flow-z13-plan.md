# Flow Z13 local AI implementation and evaluation plan

## Resumed LLM acceptance — October 21, evening

**PAUSED at the user's explicit request.** Current candidate context test and queued recovery coordinator were cancelled; do not restart tests or models until instructed. Gufo 0.20 / 16 GiB candidate has passed two-session 32K only. Its 200K step was interrupted and is unqualified; 225K and all new recovery jobs remain untested. The older baseline's 200K process-swap failure remains rejected. Resume from the retained checkpoint in `/home/danfl/dev/AgentContext/LocalAI-LLM-Resume-2026-10-21/` after explicit authorization.

**Latest completed result:** the unchanged older Gufo / 26 GiB-cache profile passed two-session exact recall and full warm reuse through 200113 tokens each, but peaked at **6089125888 bytes (5.67 GiB) runtime-process swap** during warm snapshot handling. This rejects its no-swap acceptance. The 225K step was deliberately stopped; no reliability run is authorized by a passing-recall result alone. A separate installed-Gufo-0.20 / 16 GiB-cache candidate, `coding-concurrent-gufo020`, was being checked at 32K, 200K and 225K before the pause above. It keeps the same model/draft, context, disk/staging budgets and memory reserve; the production profile is preserved. This is a combined engine/cache candidate, not an isolated engine performance comparison. Ledger: `acceptance-resume-20261021/gufo020/concurrent-results.json`. Future recovery must wait for successful candidate acceptance. Reject more than 64 MiB of runtime-process swap or failure to reuse a full warm history before advancing the ladder.

The user explicitly requested stopping active local AI and resuming **existing LLM validation: long context, concurrent sessions and recovery**. All local servers and old coordinators were stopped/checked before resuming. This authorizes the unfinished installed-model LLM checks below; Halogen and higher-resolution media remain deferred. No removed model is to be redownloaded.

Resume at the incomplete revised-cache Qwen 27B two-worker ladder: 32K, 64K, 131K, 200K and 225K, one measured repeat with a warm continuation per worker. Preserve prior passed single-session rows and failed/cancelled evidence. Use the existing exact runtime/profile/cache budgets first; don't silently combine results from a new engine version. Stop each owned runtime on completion/cancellation, observe AC and the memory guard, and stop the isolated test if another runtime appears. Current private ledger: `~/.local/state/localai/acceptance-resume-20261021/`. After context acceptance, resolve the remaining corrected-Claude and ordinary OpenCode CLI recovery checks, then gate any reliability work on the short tests. No claim of full acceptance until all required tests finish.

Pi usability update: model selection now shows role + actual model + quantization/engine/context. Internal API IDs are preserved. Verified picker rendering and original-ID selection without model inference; restart Pi to load the new labels. Configuration/install helpers preserve these labels.

Later workflow addition: **05 Video with audio - H3 Euler Beta** duplicates the ready H3 preset with `euler` / `beta`, retaining its eight-step turbo LoRA, resolution, duration and audio. Installed in ComfyUI; all five ready API schemas passed. No generation or quality comparison was run for this variant; the original tested preset remains available.

## Hauhau uncensored LLM installation — later October 21, 2026

User requested `HauhauCS/Qwen3.5-27B-Uncensored-HauhauCS-Aggressive` on Gufo, with reproducible steps. Installed Q4_K_M (16.54 GB) and matching F16 projector (0.93 GB), revision `ba23816347e0f24d82efbd2397278ff32743b75c`; verified publisher SHA-256 hashes. Stock Gufo rejected the F16 projector and unrecognized chat-template hash. Preserved both original files and generated a separate 16.54 GB GGUF with only chat-template metadata adapted to the pinned supported Unsloth template. All 851 tensors and all other metadata were verified identical. This is **text-only adapted support**, not native publisher-template or vision acceptance.

Ready commands: `pi-hauhau`, `hermes-hauhau`; profile `gufo-hauhau`, pinned Gufo 0.20, one 262144 context session, target-only, temperature 0.6, top-p 0.95, top-k 20, min-p 0. RAM cache 26 GiB, disk cache 40 GiB, staging 16 GiB, free-memory reserve 8 GiB. No borrowed speculative draft. Long-context occupancy and model-quality/uncensored-behavior tests were not run. Startup, short text, tool-call/result and real Pi/Hermes one-turn chats from `/tmp` passed. Existing defaults and model files preserved. The test LLM stopped; the user's previously idle `comfyui-cached` server was restored.

See [the installation and reproduction guide](hauhau-gufo-setup.html). Recreate with `localai download qwen35-hauhau-q4`, then run `scripts/linux/prepare_hauhau.py` and `scripts/linux/register_profile.py gufo-hauhau --suffix hauhau` using `~/.local/share/localai/apps/support/bin/python`. The existing `qwen27-q4` pack supplies the pinned supported chat template. Originals, derived files, manifests and sessions remain outside Git. Added model footprint is about 34.0 GB plus future caches. Raw evidence is in `~/.local/state/localai/hauhau-*` and `derived-models.json`. Deferred Halogen testing remains deferred.


## Planned follow-up: Halogen comparison — deferred by user

**Decision, October 21:** continue using Gufo for now. Keep Halogen in this plan for a future user-requested test; do not install or benchmark it during the current video work. Retain all existing Qwen and media packs.

- Review the then-current official Halogen deployment guide and pin the runtime image and checkpoint revisions. Current candidate: Halogen 0.18.13 with its default v2 HGN checkpoint and separate n-gram table, about **118 GB decimal** plus runtime/cache storage. Recheck versions and storage before installation. Do not download every optional/obsolete quantization.
- Use the shared model store, the existing memory reserve and a single GPU owner. Check GGUF compatibility explicitly; do not assume the installed Unsloth Q4_K_XL loads directly in Halogen. Preserve Gufo as the working fallback and keep weights, caches and session context outside Git.
- Compare with the accepted **Gufo auto-policy baseline**, not the slower high-policy experiment: identical prompts, actual token counts, AC / firmware Performance / GPU auto, matched context/output budgets, and no concurrent model work. Measure fresh 2K, 8K, 32K, 131K and 200K input, with repeats at short sizes. Verify Halogen's own cache-disable controls and timing fields before reporting fresh prefill.
- Record cold loading, prefill, first output, sustained decode on separate sufficiently long outputs, exact recall/tool behavior, peak memory/swap and thermals. Test warm 200K continuation separately; do not count cached input as fresh work. Target **1,500+ prefill tok/s**, with **1,200** the requested minimum.
- Keep 200K+ usable chat context, with output/tool headroom. Add Pi/Hermes launch profiles only after compatibility and memory checks pass. Publish the result and updated complete model/storage inventory, then retain the better practical setup. Approximate/experimental attention or NPU paths require separate quality evidence.

## Video follow-up — completed October 21, 2026

The user separately authorized installed video-model performance tests and optimization research. See [the concise video report](video-performance.html). Both ready 832×480 presets passed: H3 INT8 / eight-step turbo, 124 frames / 5.17s with audio, **434.2s**; Wan Rapid Mega AIO / four steps, 81 frames / 5.06s silent, **559.4s**. These are single cold-graph runs, not a general quality ranking. AC, firmware Performance, GPU auto; minimum available memory 51.5 GiB.

Short 512×288 repeat tests improved from 57.9s to 33.9s for H3 and 57.6s to 42.9s for Wan with node caching. `run-comfyui --cached` is opt-in **single-family** mode: stop/restart before changing families. Its `--cache-ram 16` is a free-RAM headroom threshold, not a cache-size cap. A mixed-family cached run exhausted the memory reserve and was stopped by the supervisor; the failed evidence is retained. Ordinary `run-comfyui` keeps `--cache-none` and supports family switching.

The exact-semantics H3 gfx1151 packing node was reviewed, pinned and tested. An isolated forced-flash attention call improved 2.65×, but full H3 took **444.7s**, offering no gain over 434.2s. Installed ComfyUI already contains gfx1151 contiguous-KV handling. Full encoded video differed slightly (PSNR 44.20dB), audio matched. **Do not enable the extra node in the ready workflow.** All four ready graph schemas passed; cached foreground Ctrl-C shutdown passed; inference servers stopped. No model weights downloaded or removed.

Alternative engines were researched, not installed/tested: h3-hip.c needs a different ~134 GiB original checkpoint and its fast settings change quality/steps; Gufo H3 has no comparable qualified complete-video matrix; FastVideo's custom Wan AIO/gfx1151 compatibility remains unverified. Retain ComfyUI for media. Future work, only when requested: 720p/1080p, broader motion/identity/audio-quality fixtures, and matched alternate-engine trials with compatible weights. No broad historical acceptance campaign was resumed. Detailed evidence is in `~/.local/state/localai/video-performance/` and the saved handoff at `/home/danfl/dev/AgentContext/LocalAI-Video-2026-10-21/`.

## Targeted Gufo follow-up — October 21, 2026, afternoon

The user subsequently authorized targeted Flash-Next Gufo performance testing, Halogen **only if Gufo remains below 1,200 fresh prefill tok/s**, and exceeding 600 GB to add a Qwen variant while preserving all retained models. This overrides the testing pause only for that focused work. The official Gufo 0.20 image and exact supported Unsloth Q4/MTP pack are installed; the previous EXL3 remains. Fresh-input tests passed through 200K, and the ready 12 GiB RAM / 16 GiB disk cache passed a live 200K continuation in 0.39s with 12.7 GiB minimum free memory. Launch with `pi-gufo` or `hermes-gufo`. Plain Pi/Hermes defaults are unchanged.

See [current Gufo results and complete installed inventory](gufo-flash-results.html). Best repeated 8K median is 1,450 tok/s; 200K is 1,290. **1,500 is not yet demonstrated.** Halogen's gate has not triggered. Production Gufo is GPU/HIP-only; the NPU proposal is unmerged and unnecessary for the published GPU baseline. The user enabled the temporary high GPU policy helper. Its medians were 1,392 / 1,383 / 1,353 at 2K / 8K / 32K, and its fresh 200K result was 1,187 tok/s. Recall, zero-cache fresh-work and warm continuation checks passed, but high did not demonstrate a benefit. Retain auto; automatic restoration to auto is confirmed. The user subsequently chose to keep Gufo for now and retain Halogen testing as a deferred plan item above. No Halogen installation has occurred. Firmware Performance remains enabled by the user. Benchmarks stop their owned runtime on exit. No unrelated reliability/media campaign is resumed.

## Current operational checkpoint — October 21, 2026

A later user request authorized cleanup to 600 GB, ready Pi/Hermes agents and ComfyUI repairs, with **no new model testing**. The selected installation is approximately 427 GB; see [getting-started.html](getting-started.html) and [Gufo diagnosis](gufo-performance-diagnosis.md). Plain `pi` / `hermes` now choose Qwen EXL3 / Kyojin. Removed models and obsolete acceptance jobs below are historical scope, not instructions to reinstall or resume. Four native workflows replace the broken API/sidebar and optional-model templates. `run-comfyui` is foreground with Ctrl-C; `stop-comfyui` is explicit stop.

## Retained testing checkpoint — October 21, 2026

**Testing ended at the user's request; do not resume automatically.** Installation and substantial short acceptance work are complete, but the full acceptance plan is not complete. The definitive results so far are [the concise HTML findings](local-ai-findings.html) and [the detailed validation record](validation-status.md). This document retains the original scope and historical starting settings below; current settings are in `config/linux/profiles.json`.

The latest 26 GiB-cache Gufo run passed all single-session ladder steps through **225393 actual input tokens**. The two-worker repeat passed 8K, then was stopped during the 32K step. Earlier two-worker 200K recall passed with the previous settings; it is not a completed revised-cache concurrent acceptance. Both 32K and 200K disk-cache restart tests passed under the revised budget. Pi and Hermes native recovery passed; OpenCode's API-to-CLI resume failed; Claude's corrected custom model ID is configured but awaits its lifecycle/context retry.

Current defaults: Gufo Qwen3.8-27B Q4 for concurrent coding; Kyojin Qwen3.8-Flash-Next 4-bit EXL3 for large coding/vision; GLM for the largest tested vision challenger; Vulkan Qwen 27B Q4 for Claude Code. The current concurrent snapshot budget is **26 GiB RAM / 40 GiB disk / 16 GiB staging**, replacing the historical 32 GiB RAM starting point below. Qwen EXL3 passed 500K recall with its drafter disabled, but sustained 500K coding did not achieve acceptance. MiMo's sustained coding failed memory protection. Full-resolution media and reliability tests remain unfinished.

The stopped private ledger is `~/.local/state/localai/acceptance-20261021/results.json`; the partial ladder is `acceptance-20261021/context-campaign-1792585506/results.json`. No inference runtime remains active. A durable plan, findings and implementation snapshot is retained at `/home/danfl/dev/AgentContext/LocalAI-Flow-Z13-2026-10-21/`; begin with its `HANDOFF.md` before any future work.

## Device, scope, and shared storage

Target: CachyOS Linux on ASUS ROG Flow Z13 GZ302EA, Ryzen AI Max+ 395 / Radeon 8060S (`gfx1151`), 128 GB unified memory. Initial inspection found kernel 7.2.10, ROCm 7.2.4, a 96 GiB firmware GPU reservation, approximately 31 GiB Linux RAM, and 929 GiB free disk.

Reuse this repository's launch/workflow/test concepts while preserving its Windows configuration. Install models under the per-user XDG shared model store, with absolute paths, so ClearCase and other repositories do not depend on the LocalAi checkout. Never store weights, transcripts, extracted document contents, session context, KV caches, credentials, or generated outputs in Git. Pin model revisions and verify file sizes and SHA-256 values. Allow 900 GiB total and rotate large experiments rather than copying whole model repositories.

## Memory and engines

ASUS documents a 96 GB firmware carve-out maximum. Linux TTM/GTT is a dynamic mapping limit, not extra RAM or a second independent memory bank. Reduce the firmware reservation to its minimum (preferably 512 MiB); after reboot configure 112 GiB TTM (`pages_limit=29360128` with 4 KiB pages). The administrator script refuses to apply that setting while the large carve-out is still present. Save rollback instructions; never automatically reboot the machine. Measure actual allocation capacity with at least 8 GiB free unified memory; distinguish the mapping ceiling from the largest stable working set.

Use upstream Linux Gufo for Qwen, Kyojin/ExLlamaV3 for the large Yamz packs, llama.cpp Vulkan as a compatibility/reference engine, and ROCm ComfyUI for media. Install isolated user Python/Node runtimes, native build and GPU dependencies, and rootless Podman. Pin working software revisions and environments. Keep IOMMU and normal power-management behavior unless separate measured experiments justify a change. Run performance campaigns on AC power with consistent ASUS power/cooling settings.

## Coding, chat, and harnesses

- Quality candidate: Unsloth Qwen3.8-Flash-Next UD-Q4_K_XL, shared Q8 MTP, matching BF16 vision projector, one 262144-token session. The pinned UD-Q3_K_XL fallback uses llama.cpp Vulkan: its IQ3_XXS expert tensors are rejected by the pinned Gufo build. Loading, accuracy and long-context acceptance are required before recommendation.
- Implemented quality choice after short tests: Kyojin Qwen EXL3 under `coding-quality` / `vision-quality`, with the Unsloth Q4/Gufo configurations retained under explicit experimental names. See the validation record for measurements and remaining acceptance limits.
- Concurrent candidate: Qwen3.8-27B UD-Q4_K_XL and UD-Q8_K_XL, matching projector, Q4 DFlash2 draft. Share model weights across two independent 262144-token executor sessions.
- Large challengers: Yamz GLM-5.3-Flash EXL3 (~100 GB) and MiMo-V2.6-Flash-MOPD EXL3 (~107 GB including companions), one at a time. Explicitly request 262144 context; MiMo's default is 128K. Test Kyojin Qwen EXL3 and GLM at 524288 only if memory admission permits.
- Start Gufo snapshot budgets at 16 GiB for Flash and 32 GiB for concurrent 27B, request limit 32 MiB, 32768 output tokens, medium reasoning, preserved reasoning, and adaptive MTP/DFlash2. Validate actual flags against the pinned binary. Measure cache snapshots rather than assuming a Windows-fork setting transfers directly.
- Configure each general chat/vision profile for at least 200K context, normally native 262144. Input, tool definitions, images, reasoning and answer share that budget. Reserve output room and compact near 225K input, not an inherited 8K/16K harness default.
- Extended-context experiments: one 27B session at 524288 and 1000000 through a compatible YaRN engine, plus Kyojin's supported extended routes. Keep these separate from supported native-context profiles and validate recall and coding correctness independently of successful allocation.
- Install Pi, OpenCode CLI and Linux desktop, Hermes, and Claude Code with global launchers retaining the invoking project directory. Keep local configuration and transcripts separate from cloud credentials. Claude Code's non-Claude-model route is experimental; use llama.cpp's Messages API initially because Gufo documents repeated full-prefill behavior with Claude Code's changing system messages.

## ClearCase vision-to-text addition

Read-only inspection confirmed ClearCase's pinned default: `Qwen/Qwen3-VL-8B-Instruct-GGUF` revision `00e7d63528e65d7b64e80e1293a8360b4af6a594`, Q4_K_M weights plus Q8 projector, 5,780,074,528 bytes. Copy its reviewed artifact hashes into the shared catalog, not its private case/session data.

Test the following lanes:

1. **Small/page parity:** the exact bundled 8B model, 16384 context per request, 4096 output, two then four concurrent page reads. This is ClearCase's fresh-context document request, not a chat profile.
2. **Small/long-context vision:** the same 8B model with two then four independent 262144-token sessions. Measure memory, latency and cross-session isolation at 200K+ actual input.
3. **Vision quality:** Qwen3.8-Flash-Next Q4 with its BF16 projector at native context. Compare Qwen3.8-27B vision as the intermediate candidate.
4. **Largest vision candidate:** GLM-5.3-Flash, a 320B-total MoE with bundled vision tower, one 262144-token session on Kyojin. Include MiMo vision after its memory/serving checks. Select by document accuracy, not parameter count.

Reuse ClearCase's `accuracy_pipeline.transcription_prompt` dynamically and match its strict transcription JSON contract. Test exact names/numbers, blank surnames, multiple people and roles, ambiguous dates, image regions, and unsupported-value abstention. Begin with generated synthetic pages; keep reports and any later user-supplied case data outside both repositories. Report schema-constrained and prompt-only JSON separately. Test low/high resolution, rotations and native crops in the later real-document campaign.

ClearCase's production Local AI path requires Windows AppContainer isolation and uses fresh 16K requests. The Linux evaluation adapter does not remove that requirement, replace its renderer, or establish production end-to-end accuracy. No changes to its production application or AWS services are part of this setup.

## ComfyUI model campaign

Compare Qwen-Image-2.1 BF16, FLUX.2-dev FP8 with local encoder, Z-Image-Turbo BF16, and Chroma1-HD BF16 for photorealistic people and editing. Chroma is the initial less-restricted image baseline. Compare MiniMax H3 with native audio, LTX-2.3 dev/distilled, and Wan2.2 I2V-A14B; use the selected Phr00t Rapid-AllInOne MEGA v12.1 variant as the less-restricted video challenger. Install matching encoders, VAEs, drafts/LoRAs and required native workflows. Do not assume CUDA-only precision/kernels work on AMD.

Begin at 1024-pixel images and approximately five-second 480p video, then measure 720p and 1080p. Use model-specific frame grids and text-encoder limits, not 200K chat windows. Compare faces, anatomy, identity consistency, editing, motion and audio; inspect frames and verify metadata with ffprobe. Treat "uncensored" as a behavioral claim, not a quality guarantee. Personal experimentation is the selected usage; retain each model's license.

## Acceptance and reports

- Validate all model files and global launchers from another repository, and confirm `git check-ignore` plus a tracked-file scan excludes private artifacts.
- Test all harnesses for read/edit/test tool loops, streaming, cancellation, recovery, compaction and correct context accounting.
- Measure cold/warm requests at 8K, 32K, 64K, 128K, 200K and approximately 225K input, including two simultaneous full-length sessions. Record actual token counts and cache reuse.
- Compare ten isolated code tasks with hidden acceptance checks; rank correctness first, then latency. A needle-recall serving probe is not a coding-quality benchmark.
- Capture prefill, TTFT, decode, warm continuation, memory, swap, power and thermals; separate first-use compilation/tuning from steady-state results.
- Complete a two-hour mixed coding soak and overnight continuation test only after short tests pass. Reject unstable/OOM/swap-dependent configurations.
- Publish factual installation and benchmark status. A downloaded model, successful build, or passing unit test does not imply the hardware/model acceptance campaign passed.

Primary sources: [AMD shared-memory guidance](https://rocm.docs.amd.com/en/docs-7.2.0/how-to/system-optimization/strixhalo.html), [Gufo](https://github.com/gufo-org/gufo), [Kyojin](https://github.com/Yamz-Labs/kyojin), [llama.cpp](https://github.com/ggml-org/llama.cpp), [ComfyUI](https://github.com/Comfy-Org/ComfyUI). ClearCase's local manifests and source remain the authority for its bundled model, prompt and validation contract.
