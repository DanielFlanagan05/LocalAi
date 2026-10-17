# ComfyUI GPU and workflows

Start ComfyUI with `run_amd_gpu.bat` or your existing LocalAI launcher. Both now use the bundled ROCm Python environment, check GPU memory access and a GPU calculation, and select the GPU with the most VRAM. GPU failures stop startup with an error instead of launching a CPU session. The AMD configuration uses conventional GPU memory management, split attention, and full-precision GPU VAE decoding. Dynamic VRAM is disabled to avoid the corruption seen during verification.

Pinned memory, asynchronous offloading, and intermediate node caching are disabled to reduce Windows memory allocation pressure. Eager model unloading and 8 GB VRAM headroom prevent retained allocations and the desktop's other GPU apps from starving later runs. Models may reload between runs. During verification, other desktop apps occupied about 7–8 GB of dedicated VRAM; larger models may offload some weights to RAM while computation stays on the GPU.

Double-click **Open ComfyUI.bat**. It starts the GPU server in the background and opens your browser, or opens the existing GPU server without starting another copy. **Stop ComfyUI.bat** cancels queued work and stops this installation. Startup logs are `comfyui.stdout.log` and `comfyui.stderr.log`.

Click **Apps** in ComfyUI and choose a saved app. Each opens as a form with its models already selected. Edit the prompt, optionally upload an image, and click **Run**. The seed's Randomize control chooses a new result each run; choose Fixed there to repeat a result. Outputs appear in the app and are saved locally.

- **Image Generation - Chroma1 HD**: the permissive Apache 2.0 image choice. Default: 1024 x 1024, 26 steps. Uses ComfyUI's official mixed FP8 checkpoint and scaled FP8 T5 encoder. PNG files go to `outputs/images`.

- **Image Generation - Qwen Image 2.1**: edit the image prompt and Run. Default: 1024 x 1024, 25 steps. Uses a locally prepared FP8 model to reduce memory requirements; the original BF16 model is preserved. FP8 can slightly affect image quality. PNG files go to `outputs/images`.
- **Image Editing - Qwen Image 2.1**: upload an image and describe what to change and preserve. The example fox is already connected. Default: 768-pixel reference resolution, 25 steps, preserving aspect ratio. Experimental prefix caching is disabled for this editing path after an AMD runtime crash.
- **Video Generation - Wan 2.2 5B**: edit the video prompt and Run. Default: 832 x 480, 49 frames, 24 fps, 20 steps. Uses DPM++ 2M sampling and tiled GPU VAE decoding. H.264 MP4 files go to `outputs/video`.
- **Video Animation - Wan 2.2 5B**: upload an image and describe its motion. The starting image is already connected; the example fox runs as-is. Uses the same video defaults.

Video length is entered in frames: 49 is about 2 seconds; 81 is about 3.4 seconds; 121 is about 5 seconds at 24 fps. Keep the default size and duration for your first run. Longer or larger videos need more memory and time. Generate one job at a time on this hardware.

The saved workflows are in `C:\Users\danfl\dev\LocalAI\config\comfyui\default\workflows`. Original files are backed up under `backups/before-gpu-workflow-fix` in this installation.

Apps use the native `.app.json` format. The earlier graph versions and Strata config are also backed up under `backups/before-app-mode`. Use the Graph button if you want to inspect their nodes; no rewiring is needed for ordinary generation.

## Model choices for this machine

My installed choices are [Chroma1-HD](https://huggingface.co/lodestones/Chroma1-HD) for permissive image generation and [Wan 2.2 TI2V 5B](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B) for practical text-to-video and image-to-video. Both use Apache 2.0. Chroma's authors explicitly say it has not been aligned with a specific safety filter; its training dataset was still filtered. These workflows add no moderation node or remote filtering service. Model training still affects what each can generate.

[Qwen Image 2.1](https://huggingface.co/Qwen/Qwen-Image-2.1) is retained for instruction-following, text rendering and editing. It uses the Qwen Research License, with noncommercial use terms, rather than Apache 2.0. See its [license](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE).

[Z-Image-Turbo](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo) is an optional faster Apache 2.0 image alternative: 6B parameters and about 8 inference steps. It is not installed or tested here, and its authors do not make Chroma's explicit safety-alignment claim. [HunyuanVideo 1.5](https://huggingface.co/tencent/HunyuanVideo-1.5) is an optional video experiment: its published minimum is 14 GB VRAM with offloading, but its Tencent license is different and AMD Windows compatibility and total RAM use have not been verified here. Wan 14B variants impose much greater offloading pressure on 32 GB RAM; they are not the default.

## Sharing hardware with Strata

[Strata](https://github.com/Niko1221/Strata) serves a text language model. It can help draft prompts; it does not execute ComfyUI diffusion models or combine your RAM with VRAM as a new rendering backend. ComfyUI already offloads weights to RAM when needed. This machine cannot comfortably keep Strata's large model and the diffusion models resident together: Strata reported 30.7 GB RAM used during this setup.

The GPU launcher and each UI Run request use Strata's supported `/unload` endpoint. It releases only an idle model, keeps the text service available, and refuses while Strata is busy. API clients that submit directly to ComfyUI should run `python_embeded/python.exe -s share_gpu.py` first.

The existing `Strata/strata-iq2_xs.json` now loads on demand, unloads after 90 idle seconds, and runs a local ComfyUI memory-release hook before loading. These Strata settings apply on its next start. The hook refuses to load Strata while ComfyUI has running or queued generation jobs. Use Strata to write a prompt, then generate in ComfyUI; finish generation before asking Strata another question. Model reloads take time, but avoid memory contention.

This machine has an AMD Radeon RX 7900 XT with 20 GB VRAM. ROCm exposes it as `cuda:0`; that label is expected for AMD PyTorch. CPU activity during model loading, memory offloading, and MP4 encoding is normal. The startup log should show `Device: cuda:0 AMD Radeon RX 7900 XT`, and VAE/text encoder load devices should be `cuda:0`. Large models may use system RAM while computation stays on the GPU.

Verification passed for the default 1024 x 1024 image and 832 x 480 / 49-frame H.264 video, plus a consecutive full-size video memory check using four sampling steps. Output images and video frames were visually inspected. The final video sampling ran at about 3 seconds per step with the desktop apps still open. Loading and full-precision tiled decoding add several minutes.

The App Mode upgrade also passed full 1024 x 1024 Chroma generation (26 steps) and 768 x 768 Qwen editing (25 steps, cache off). Both output images were visually inspected. Chroma sampling took about 95 seconds. Verification records and previews are kept alongside this guide.

The image-animation workflow passed at 832 x 480, 49 frames, 24 fps, 20 steps. Its MP4 decoded as H.264 with all 49 frames; first and last frames were inspected. A full 1024 x 1024 Qwen image also passed through the actual App Mode Run button, with the completed result visible in the browser. All five saved apps have consistent links and exposed controls. Results are in `app-workflow-verification-results.json`; the existing text-to-video verification is in `workflow-verification-results.json`.
