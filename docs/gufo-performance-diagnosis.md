# Gufo prefill: diagnosis from existing evidence

October 21, 2026. No new model inference or benchmarks were run for this investigation. The retained engines were not upgraded or experimentally retuned.

## Finding

We have not demonstrated a single Gufo fault that explains the whole gap. The comparisons mixed different models, context depths, output lengths and cache states. Existing telemetry also shows a genuine constrained power/memory workload. The missing matched control prevents assigning a precise percentage to each cause.

### 1. The Reddit example is a different workload

The supplied Reddit post uses **Qwen3.8-Flash-Next MoE, MTP and prompt lookup on a Windows fork**. Our accepted Gufo measurements use **dense Qwen3.8-27B with DFlash2 on Linux**, with two configured execution sessions. The Flash-Next Q4/Gufo candidate failed memory acceptance; we never obtained a comparable successful throughput measurement for it. Our successful large Flash-Next measurements came from **Kyojin**, at about 716 prefill tokens/s at 200K and 619 at 500K without its drafter.

The Reddit headline of ~60 tokens/s describes generated output. **Prefill** means reading input. **Decode** means generating output. Cache-hit continuation time measures neither cold full-history prefill nor steady decode throughput alone. Comparing 60 decode tokens/s to 185 prefill tokens/s is invalid. The Windows fork is specifically Flash-Next-oriented ([upstream project](https://github.com/thomas9120/gufo-windows)).

### 2. Depth explains much of the headline prefill discrepancy

The [official 27B benchmark](https://github.com/gufo-org/gufo/blob/main/docs/models/qwen3.8-27b/BENCHMARKS.md) separates approximately 2K new-token prefill at cached depths from short-context peaks. Its Q4 DFlash2 prefill falls from 580 tokens/s at zero depth to 339 at 65K and 247 at 131K. Our observed long-request rates were 307 at 65K, 239 at 131K, and 185–191 at 200–225K. The 131K numbers are close, but the requests are not identical.

Our 8K request was still slower than upstream's short-depth best figures: about 392 tokens/s. A residual gap remains; it cannot be dismissed entirely as context length. Upstream's DFlash2 figures select the highest result across text types, whereas ours were synthetic recall probes. See that source for its greedy/thinking-off and mixed/repetitive-output conditions. Our recall requests also explicitly disabled thinking, despite the server's thinking-on default.

### 3. Existing telemetry shows power and memory pressure

All sampled runs used ASUS **Balanced**, not a separately controlled performance mode:

| Existing run | Median AMDGPU PPT sensor | Maximum recorded model-process swap |
|---|---:|---:|
| 8K | 52.1 W | 0 |
| 65K | 52.0 W | 0 |
| 200K | 49.4 W | 201 MiB |
| 225K | 49.0 W | 215 MiB |

GPU edge temperatures were generally ~80–84°C in the longer probes. This supports power/memory pressure as plausible contributors, but does **not** prove thermal throttling or establish a watt-for-watt comparison to the Reddit laptop. The power field is an AMDGPU sensor, not whole-device wall power. System swap activity includes other applications.

### 4. Concurrency and caching affected wall time, but do not explain away all kernel time

The earlier dual-200K run had two physical execution lanes, a recorded shared-prefix wait of ~171 seconds for one request, downloads overlapping, and ~40-minute wall times. It is unsuitable as a single-user engine-speed benchmark.

The latest 200K probe instead reported physical width **one** and `serial-fallback`: ~813 seconds were in actual prefill, versus ~3 seconds restoring cache and <1 second snapshotting. Its 200K cache hit already retained a 50K prefix. Therefore disk restoration or simply having two configured sessions does **not** explain the bulk of that particular slow request.

Normal warm continuation reused ~200K tokens and took ~7 seconds. Restoring a 200K disk checkpoint after restart took 11.31 seconds. The useful cache path is working; this is not evidence of every turn re-reading the entire conversation. The former 32 GiB RAM-cache budget exceeded our memory reserve; the retained 26 GiB setting favors headroom. Increasing it blindly would risk repeating that failure.

### 5. Decode headline gains need a different measurement

Our recall outputs were only around ten tokens, over three or four draft rounds. One 200K result accepted six of eleven draft proposals. These are poor estimates of sustained speculative coding throughput. Highly repetitive code output can accept more speculative tokens than an exact identifier response; prompt lookup also exploits repeated text. We cannot claim our model should reproduce the supplied Reddit run from these probes.

### 6. The binary is pinned, but does not match the benchmark revision

Container label: Gufo **0.19.0**, engine revision `7b2784517f5652860e03c4ff0c61f2d8940139db`, built October 19 at 10:18 UTC. The upstream table names `11813e51` with wave64 verification attention. The local source checkout is a separate revision and is not proof of the running container's kernels. Revision/kernel differences are a candidate for the remaining gap, not a demonstrated prefill regression. The upstream note says the wave64 refresh improved verification/decode; it does not itself prove a prefill fix.

## Practical decision

Use the already accepted **Kyojin Qwen EXL3** for default Pi/Hermes quality work. Retain **Gufo 27B Q4** for the smaller/two-session lane. Keep the known working container pinned. No firmware, power profile, driver, cache-size or kernel change was applied during this investigation.

If the user later authorizes targeted tests, the smallest useful next step is one matched 27B Q4 single-session test: identical prompt, context depth, actual new-token count, sampling, warm/cold state and 128+ output tokens; compare the pinned and benchmark revisions at a recorded power profile. Separate prefill, decode, queue wait, cache restore, GPU clocks/PPT and process swap. This would test the residual gap without downloading another large model. **No such test has been started.**

Evidence: private `benchmarks/coding-concurrent-{1792585529,1792585810,1792586295,1792587120,1792588294,1792526819}.json`, `runtime-lock.json`, and read-only Podman image labels under `~/.local/state/localai` / the local image store. Historical reports remain intact after model cleanup.
