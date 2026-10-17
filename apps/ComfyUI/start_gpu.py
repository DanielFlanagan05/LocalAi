import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from share_gpu import release_strata

root = Path(__file__).resolve().parent
localai = root.parent.parent
if "--cpu" in sys.argv or "--cpu-vae" in sys.argv:
    sys.exit("This launcher uses the GPU. Remove --cpu and --cpu-vae.")
release_strata()
check = subprocess.run([sys.executable, "-s", str(root / "check_gpu.py")], capture_output=True, text=True)
if check.returncode:
    sys.exit(check.stderr or check.stdout)
gpu = json.loads(check.stdout.splitlines()[-1])
print(f"GPU verified: {gpu['name']} ({gpu['vram'] / 1024**3:.1f} GB VRAM)", flush=True)
command = [
    sys.executable, "-s", str(root / "ComfyUI" / "main.py"),
    "--windows-standalone-build", "--listen", "127.0.0.1", "--port", "8188",
    "--cuda-device", str(gpu["device"]), "--disable-dynamic-vram", "--disable-auto-launch",
    "--use-split-cross-attention", "--fp32-vae",
    "--disable-pinned-memory", "--disable-async-offload", "--cache-none",
    "--disable-smart-memory", "--reserve-vram", "8",
    "--user-directory", str(localai / "config" / "comfyui"),
    "--models-directory", str(root / "ComfyUI" / "models"),
    "--output-directory", str(root / "outputs"),
    *sys.argv[1:],
]
sys.exit(subprocess.call(command, cwd=root))
