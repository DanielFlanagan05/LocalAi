# Flow Z13 validation status — 2026-10-21

## Active LLM acceptance continuation — October 21 evening

**Paused by the user.** Candidate 32K passed; candidate 200K was interrupted, 225K and new recovery checks remain untested. Both coordinators and their model were stopped. Do not resume until explicitly instructed; historical in-progress descriptions below describe the work before this pause.

The user explicitly selected the unfinished long-context, concurrent-session and recovery work. This supersedes the earlier testing pause for installed LLMs only. See [the current concise results](llm-validation-resumed.html); historical results below remain dated evidence.

On the unchanged pinned `coding-concurrent` Gufo runtime and 26 GiB RAM / 40 GiB disk / 16 GiB staging budget, the resumed two-session ladder passed 32K, 64K and 131K per session. Actual 131K inputs were 131185 tokens each; both warm turns reused 131195 tokens and processed only 24 fresh tokens. Warm replies took 11.50 / 2.37 seconds; the whole step took 744.9 seconds. Minimum sampled available memory was 18.47 GiB, sampled runtime-process swap zero. These are exact recall/isolation and cache-reuse checks, not coding-quality or fresh-prefill benchmarks. Two logical sessions sometimes use Gufo's serial fallback rather than simultaneous physical GPU execution.

The 200K pair reached 200113 actual tokens each, passed isolated recall, and reused 200123 tokens each on continuation (24 fresh tokens). Warm replies took 14.97 / 15.06s; the whole step took 1479.8s. **No-swap acceptance failed:** runtime-process swap peaked at 6089125888 bytes (5.67 GiB), with 8.70 GiB minimum available memory. The spike occurred during the final warm snapshot phase. The 225K step was stopped rather than accepting a recall-only result. Raw evidence: `benchmarks/coding-concurrent-1792632194.json`.

A separate candidate `coding-concurrent-gufo020` uses the already installed Gufo 0.20 image and a 16 GiB RAM cache; production settings remain unchanged. Its two-session 32K / 200K / 225K checks must pass recall, full warm reuse and the 64 MiB runtime-swap tolerance. This combined engine/cache change cannot isolate which change caused any difference. Corrected Claude / ordinary CLI-created OpenCode recovery and Flash / Hauhau 200K disk-restart checks wait behind candidate acceptance. Halogen, media, removed-model downloads and the original superseded broad queue are deferred. The original complete acceptance plan is not yet finished.

Private ledger: `~/.local/state/localai/acceptance-resume-20261021/`; retained continuation context: `/home/danfl/dev/AgentContext/LocalAI-LLM-Resume-2026-10-21/`.

## Hauhau uncensored LLM installation — later October 21, 2026

User requested `HauhauCS/Qwen3.5-27B-Uncensored-HauhauCS-Aggressive` on Gufo, with reproducible steps. Installed Q4_K_M (16.54 GB) and matching F16 projector (0.93 GB), revision `ba23816347e0f24d82efbd2397278ff32743b75c`; verified publisher SHA-256 hashes. Stock Gufo rejected the F16 projector and unrecognized chat-template hash. Preserved both original files and generated a separate 16.54 GB GGUF with only chat-template metadata adapted to the pinned supported Unsloth template. All 851 tensors and all other metadata were verified identical. This is **text-only adapted support**, not native publisher-template or vision acceptance.

Ready commands: `pi-hauhau`, `hermes-hauhau`; profile `gufo-hauhau`, pinned Gufo 0.20, one 262144 context session, target-only, temperature 0.6, top-p 0.95, top-k 20, min-p 0. RAM cache 26 GiB, disk cache 40 GiB, staging 16 GiB, free-memory reserve 8 GiB. No borrowed speculative draft. Long-context occupancy and model-quality/uncensored-behavior tests were not run. Startup, short text, tool-call/result and real Pi/Hermes one-turn chats from `/tmp` passed. Existing defaults and model files preserved. The test LLM stopped; the user's previously idle `comfyui-cached` server was restored.

See [the installation and reproduction guide](hauhau-gufo-setup.html). Recreate with `localai download qwen35-hauhau-q4`, then run `scripts/linux/prepare_hauhau.py` and `scripts/linux/register_profile.py gufo-hauhau --suffix hauhau` using `~/.local/share/localai/apps/support/bin/python`. The existing `qwen27-q4` pack supplies the pinned supported chat template. Originals, derived files, manifests and sessions remain outside Git. Added model footprint is about 34.0 GB plus future caches. Raw evidence is in `~/.local/state/localai/hauhau-*` and `derived-models.json`. Deferred Halogen testing remains deferred.


## Video follow-up — completed October 21, 2026

The user separately authorized installed video-model performance tests and optimization research. See [the concise video report](video-performance.html). Both ready 832×480 presets passed: H3 INT8 / eight-step turbo, 124 frames / 5.17s with audio, **434.2s**; Wan Rapid Mega AIO / four steps, 81 frames / 5.06s silent, **559.4s**. These are single cold-graph runs, not a general quality ranking. AC, firmware Performance, GPU auto; minimum available memory 51.5 GiB.

Short 512×288 repeat tests improved from 57.9s to 33.9s for H3 and 57.6s to 42.9s for Wan with node caching. `run-comfyui --cached` is opt-in **single-family** mode: stop/restart before changing families. Its `--cache-ram 16` is a free-RAM headroom threshold, not a cache-size cap. A mixed-family cached run exhausted the memory reserve and was stopped by the supervisor; the failed evidence is retained. Ordinary `run-comfyui` keeps `--cache-none` and supports family switching.

The exact-semantics H3 gfx1151 packing node was reviewed, pinned and tested. An isolated forced-flash attention call improved 2.65×, but full H3 took **444.7s**, offering no gain over 434.2s. Installed ComfyUI already contains gfx1151 contiguous-KV handling. Full encoded video differed slightly (PSNR 44.20dB), audio matched. **Do not enable the extra node in the ready workflow.** All four ready graph schemas passed; cached foreground Ctrl-C shutdown passed; inference servers stopped. No model weights downloaded or removed.

Alternative engines were researched, not installed/tested: h3-hip.c needs a different ~134 GiB original checkpoint and its fast settings change quality/steps; Gufo H3 has no comparable qualified complete-video matrix; FastVideo's custom Wan AIO/gfx1151 compatibility remains unverified. Retain ComfyUI for media. Future work, only when requested: 720p/1080p, broader motion/identity/audio-quality fixtures, and matched alternate-engine trials with compatible weights. No broad historical acceptance campaign was resumed. Detailed evidence is in `~/.local/state/localai/video-performance/` and the saved handoff at `/home/danfl/dev/AgentContext/LocalAI-Video-2026-10-21/`.


This is an installation/acceptance record, not a model leaderboard. Detailed reports, synthetic inputs, transcripts and telemetry live under `~/.local/state/localai/` and are excluded from Git.

## Later targeted Gufo qualification

The user's later request authorized the new tests and extra download while retaining EXL3 and all other selected models. See [Gufo Flash-Next results](gufo-flash-results.html). Gufo 0.20 / Unsloth UD-Q4_K_XL, AC / firmware Performance / GPU auto: AR medians 1,346 / 1,387 / 1,390 tok/s at fresh 2K / 8K / 32K. MTP medians 1,325 / 1,364 / 1,357; single fresh 131K / 200K runs 1,311 / 1,266. All rows are cache-disabled exact recall passes with actual fresh-token accounting. Initial cache was 1 GiB.

The final 12 GiB RAM / 16 GiB disk configuration passed an 8K median of 1,450 and fresh 200K at 1,290 tok/s. Live continuation reused 200,125 tokens and passed recall in 0.386s, first output 0.213s. Minimum free unified memory 12.7 GiB; sampled runtime-process swap zero. Disk-restart recovery, new coding-quality acceptance and full 262K occupancy were not tested. The runtime stopped cleanly. The later temporary high GPU policy comparison did not establish a gain: medians 1,392 / 1,383 / 1,353 at 2K / 8K / 32K; fresh 200K 1,187 tok/s. All rows stayed on high and passed recall/fresh-token checks. Live continuation took 0.392s; minimum free memory 13.6 GiB, runtime-process swap zero. The model stopped cleanly. The better auto configuration still clears 1,200. The user chose to continue with Gufo and add Halogen testing to the plan for a later session; no Halogen installation or test is authorized for the current video work. The 1,500 goal remains unconfirmed. NPU offload is not part of the production Flash path.

Evidence: `prefill-acceptance/gufo-flash-ar-1792605978.json`, `prefill-acceptance/gufo-flash-1792606666.json`, `prefill-acceptance/gufo-flash-1792607242.json`, `prefill-acceptance/gufo-flash-1792608191.json`; private journal `gufo-flash-optimization-20261021.json`. Seventeen implementation tests pass. Earlier records below retain their historical defaults and scope.

**Resumed validation completed on October 21.** Draft-free Qwen passed 500081 input tokens and a cached continuation. LTX schema validation and video/audio generation passed. The default `coding-concurrent` Gufo profile is restored. The completed progress record is `~/.local/state/localai/validation-resumed-20261021.json`; the earlier user-requested cancellation remains preserved.

**Testing stopped at the user's request.** The concise wrap-up is [local-ai-findings.html](local-ai-findings.html). With the revised 26 GiB RAM cache, the single-session ladder passed 8K through 225393 actual input tokens. The two-worker repeat passed 8K and was stopped during the next step; the remaining jobs and reliability acceptance are incomplete. The private ladder record is `acceptance-20261021/context-campaign-1792585506/results.json`; the coordinator ledger is `acceptance-20261021/results.json`. No inference runtime remains active.

The original accumulated-cache Gufo campaign passed the three harness checks, 10/10 coding tasks and single-session 8K through 200K probes, then exhausted its memory reserve before the 225K request. Its report is `campaigns/coding-concurrent-1792557980/results.json`. That failure motivated reducing the RAM snapshot budget from 32 to 26 GiB.

Native Pi cancellation, exact same-session recovery, forced automatic compaction and disk-session reopening now pass (`harness-recovery/1792583854/results.json`). Hermes passed native interruption, exact recovery, manual compression and saved-session resume with the revised 26 GiB budget (`harness-recovery/1792585164/results.json`). Its retry exposed a test observer that waited only for final text while reasoning was already streaming; watching both native stream indicators corrected that test.

The Hermes retry's manual compression reduced 14 messages to 12, but its displayed request-size estimate increased from roughly 4209 to 5220 tokens. This verifies the native compression path, not useful context savings or natural long-session compaction. Exact recall after saved-session resume also passed.

OpenCode's native SSE probe observed an actual assistant delta, aborted and recovered, and completed manual compaction. Resuming that API-created session through `opencode run --session` then timed out with empty CLI output despite healthy model generation (`harness-recovery/1792584382/results.json`). This API-to-CLI lifecycle path is rejected; it does not establish whether a session created and resumed entirely through the CLI has the same problem. The unchanged failed probe is retained rather than rerun. Claude's old alias imposed a 200K client window; its default is now `messages-compatible`, with the native recovery retry still pending.

The initial 485K coding run was stopped after repeated transport errors and one-token replies. It is not a coding-quality score. Kyojin's ten-second SSE keepalive is now enabled, and the imported reference fixture uses calibrated numeric CSV data to avoid Pi's conservative character-count estimate exhausting the response budget. The corrected extended coding run remains pending.


| Check | Observed result |
|---|---|
| Firmware and Linux memory | 0.5 GiB firmware reservation, approximately 125 GiB visible to Linux, 112 GiB dynamic GTT limit active |
| Primary runtime | Pinned Gufo container, two 262144-token Qwen3.8-27B Q4 sessions, DFlash2 and vision projector loaded |
| Pi / OpenCode / Hermes | All passed read/write tool integration through Gufo, including the installed global launchers from isolated work directories |
| Coding suite | Latest Gufo run passed 10/10 isolated Python tasks through Pi |
| Vulkan reference | Earlier 200113-token recall plus warm continuation passed; concurrent workloads and the old firmware reservation make its timings unsuitable for ranking engines |
| Gufo long context | Two 200113-input-token requests passed needle recall; warm continuations reused 200123 cached tokens and took 5.85–6.39 seconds. Exploratory initial run: 40 minutes, Balanced mode, downloads overlapped |
| Claude Code | Global launcher read/write tool test passed through the Messages API after system-update template normalization |
| ClearCase 8B / 27B | Exact pinned bundled 8B weights verified; four concurrent pages read all 16 target values but failed unsupported blank-field/issuer/date interpretations. The serial 27B Q8 read all values but inferred a date order |
| ComfyUI | Four image families and H3 video/audio smoke generation passed. With output caching disabled, Wan → H3 → Wan all passed in one server process. LTX video/audio smoke generation also passed; all seven standalone baseline graphs validate |
| Native media templates | All nine use installed node types; optional prompt enhancers and optional Wan FP16/LoRA choices remain additional downloads |
| Larger candidates | GLM passed 200098-input-token recall, 4/4 synthetic document pages and 10/10 coding tasks. Q3 Vulkan passed 200113 input tokens and 4/4 document pages. EXL3 Qwen passed 200113 input tokens, 4/4 pages and, after reducing prefill chunks, 10/10 coding tasks |
| Additional downloads | All 19 staged packs, including Kyojin Qwen, verified. MiMo passed 200098 input tokens in its 225280-context text-only fallback; its subsequent coding run hit the memory guard during task three. Speculative Qwen 500K hit the memory guard again; the resumed draft-free retry passed 500081 input tokens and cached continuation |
| API cancellation | Stream cancellation and exact follow-up from the same Gufo process passed |
| Extended acceptance | Pi and Hermes passed short native lifecycle checks. OpenCode and the corrected Claude alias, long-context coding, 1M experiments, two-hour soak and overnight continuation remain unaccepted |

Measured full snapshots exceeded the original 8 GiB disk-cache budget; concurrent profiles now specify 40 GiB disk / 16 GiB staging. Large-checkpoint restart restoration passed: a 200149-token continuation reused 200107 tokens from disk and took 12.82 seconds after restarting Gufo. A 32K pilot also passed (2.75 seconds after restart). Those measurements used the earlier 32 GiB RAM budget.

The revised 26 GiB budget passed both restart checks. The 32K pilot restored 32875 of 32917 input tokens from disk and answered in 2.62 seconds. The 200K retry restored 200107 of 200149 input tokens in 11.31 seconds, with exact recall before and after a real engine restart. Initial requests also reused existing disk checkpoints, so these are restoration measurements rather than fresh-prefill measurements. The accumulated-context ladder's single-session portion also passed through 225K before testing ended.

The 900 GiB staging budget includes runtime/cache files and reserved pending downloads. The independent 40 GiB free-disk floor remains enforced. No existing model pack was deleted to stage the Q3 fallback.

Useful commands: `localai doctor`, `localai status`, `localai campaign coding-concurrent`, `localai media-validate`. Stop a profile explicitly before selecting another; the controller does not cancel another conversation to switch models.

Everyday aliases: `coding-concurrent` is Gufo 27B; `coding-quality` and `vision-quality` alias the tested Qwen EXL3 configuration; `vision-max` is GLM. The high-memory Unsloth Q4/Gufo candidates have explicit `*-q4-gufo-experimental` names. The individual `coding-quality-exl3` name remains available for comparison with its existing reports.

GLM used the reduced 2048-token prefill chunk, disabled n-gram lookup, and a 256 MiB image-cache ceiling. Its 200K serving probe took 577 seconds including calibration, with a 2.16-second warm continuation. Minimum sampled available memory was 8.95 GiB; system-wide swap movement was observed, so this is context feasibility evidence rather than a completed no-swap/soak acceptance.

Q3 Vulkan's measured initial 200113-token request took 963 seconds (208 prompt tokens/second reported by the engine); its warm continuation took 1.67 seconds with 200123 cached tokens. Minimum sampled available memory was 11.15 GiB. These are small recall responses, not sustained code-generation throughput.

MiMo's text-only fallback uses 8-bit KV, no vision tower or DFlash drafter, 225280 total context, and a 16384-token tool output allowance. Its 200098-token initial request took 1922 seconds (104 prompt tokens/second reported by the engine); the 7.76-second continuation reused 199936 tokens. Minimum available memory was 8.89 GiB. Process swap grew to 1.29 GiB and system-wide swap moved; no-swap/soak acceptance remains open. This profile demonstrates capacity, with substantially higher initial-read latency than the tested Qwen EXL3 setup.

MiMo is not accepted for sustained coding: two tasks completed, the third file fix passed its assertions but the runtime stopped before the harness finished, and the remaining attempts failed on transport. These infrastructure failures are not a meaningful model-quality score. Its full 262144-context vision/draft profile also failed memory admission/startup checks under the current desktop workload.

Those two MiMo configurations are rejected for everyday use under the measured desktop workload; their experimental profiles and failure evidence remain available. Passing a text-only capacity probe does not override the sustained-workload failure.

Draft-free Qwen uses the `qwen-exl3-512k-plain` profile with a 524288-token capacity, 8-bit KV, no vision tower and no speculative drafter. Its 500081-input-token exact-recall request passed in 809 seconds, with 619 prompt tokens/second reported by the engine. The warm request reused 500091 tokens and completed in 1.14 seconds. Minimum sampled available memory was 11.52 GiB; process swap grew to 0.84 GiB and system-wide swap moved. This establishes a single long-context serving probe, not sustained 512K coding or no-swap acceptance. The 384K fallback was not needed and remains untested.

LTX's eight-step distilled baseline generated a 320×192 clip in about 63 seconds: 17 H.264 frames at 25 fps plus AAC audio. A decoded frame shows a coherent red boat, mast and reflection. This is execution/encoding evidence, not full-resolution quality acceptance. All seven baseline graphs validate offline using the real ComfyUI server registries without starting an HTTP listener or loading models.

The first successful Wan smoke output has 17 frames at 320×192, 16 fps, H.264. A decoded middle frame visibly depicts the requested red sailboat and reflection. The one-second clip establishes basic execution and encoding, not full-resolution or long-duration quality.

## Evidence locations

Paths below are relative to `~/.local/state/localai/`. They identify private local reports, not files to add to this repository.

| Evidence | Report |
|---|---|
| Gufo 32K / 200K checkpoint restart | `benchmarks/cache-restart-coding-concurrent-1792561658.json`, `benchmarks/cache-restart-coding-concurrent-1792561796.json` |
| Gufo 26 GiB budget, 32K restart | `benchmarks/cache-restart-coding-concurrent-1792585392.json` |
| Gufo 26 GiB budget, 200K restart | `benchmarks/cache-restart-coding-concurrent-1792585440.json` |
| Pi native lifecycle retry | `harness-recovery/1792583854/results.json` |
| Hermes native lifecycle, 26 GiB cache | `harness-recovery/1792585164/results.json` |
| OpenCode API-to-CLI lifecycle failure | `harness-recovery/1792584382/results.json` |
| Two Gufo 200K sessions | `benchmarks/coding-concurrent-1792526819.json` |
| Gufo ten-task coding suite | `coding-checks/coding-concurrent-1792522180/results.json` |
| Global Pi/OpenCode/Hermes | `harness-checks/1792531247/results.json` |
| Global Claude launcher | `harness-checks/1792531404/results.json` |
| GLM 200K / document / coding | `benchmarks/vision-max-1792529342.json`, `clearcase/1792529342/results.json`, `coding-checks/vision-max-1792532044/results.json` |
| Q3 200K / document | `benchmarks/coding-quality-q3-1792530471.json`, `clearcase/1792530471/results.json` |
| EXL3 Qwen 200K / document | `benchmarks/coding-quality-exl3-1792533595.json`, `clearcase/1792534020/results.json` |
| EXL3 Qwen coding retry | `coding-checks/coding-quality-exl3-1792548013/results.json` |
| Draft-free Qwen 500K | `benchmarks/qwen-exl3-512k-plain-1792556955.json` |
| LTX video/audio | `benchmarks/media-ltx-1792556966.json` |
| Seven baseline schemas | `media-graph-validation.json` |
| Resumed run | `validation-resumed-20261021.json` and `resumed-20261021/` |
| MiMo text-only 200K | `benchmarks/mimo-text-1792551510.json` |
| MiMo interrupted coding | `coding-checks/mimo-text-1792551510/results.json` |
| Final small / intermediate document comparison | `clearcase/1792530769/results.json`, `clearcase/1792530834/results.json` |
| Wan → H3 → Wan retry | `validation-retry-progress.json` and `retry-validation/` |

Earlier failed attempts are retained. A passing retry does not erase its predecessors or establish overnight reliability.
