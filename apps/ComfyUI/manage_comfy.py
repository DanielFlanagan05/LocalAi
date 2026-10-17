"""Open the GPU server once, or cancel its queue and stop this installation."""
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parent))
from share_gpu import request, release_strata

root = Path(__file__).resolve().parent

def own_processes():
    script = "$items=Get-CimInstance Win32_Process -Filter \"Name='python.exe'\"; @($items | Select-Object ProcessId,ExecutablePath,CommandLine) | ConvertTo-Json -Compress"
    result = subprocess.check_output(["powershell.exe", "-NoProfile", "-Command", script], text=True)
    processes = json.loads(result or "[]")
    if isinstance(processes, dict):
        processes = [processes]
    python = str(root / "python_embeded/python.exe").lower()
    return [p for p in processes if (p.get("ExecutablePath") or "").lower() == python and any(name in (p.get("CommandLine") or "") for name in ["start_gpu.py", "check_gpu.py", str(root / "ComfyUI/main.py"), str(root / "ComfyUI/main.py").replace("\\", "/")])]

def ready():
    try:
        stats = request(8188, "/system_stats")
    except urllib.error.URLError:
        return False
    if not any(device["type"] == "cuda" for device in stats["devices"]):
        raise RuntimeError("The server on port 8188 is using CPU. Stop it and reopen with this launcher.")
    return True

def start():
    if not ready():
        release_strata()
        process = None
        if own_processes():
            print("ComfyUI is already starting. Waiting for it...", flush=True)
        else:
            print("Starting ComfyUI on your GPU. Startup logs: comfyui.stderr.log", flush=True)
            with (root / "comfyui.stdout.log").open("w") as out, (root / "comfyui.stderr.log").open("w") as err:
                process = subprocess.Popen([sys.executable, "-s", str(root / "start_gpu.py")], cwd=root, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(180):
            if process is not None and process.poll() is not None:
                detail = (root / "comfyui.stderr.log").read_text(errors="replace")
                raise RuntimeError("Startup failed. See comfyui.stderr.log.\n" + "\n".join(detail.splitlines()[-8:]))
            if ready():
                break
            time.sleep(1)
        else:
            raise RuntimeError("Startup is taking longer than expected. Check comfyui.stderr.log before launching again.")
    webbrowser.open("http://127.0.0.1:8188")
    print("Choose a saved Image or Video workflow, edit the form, and click Run.")

def stop():
    # Identify only this checkout's launcher and server before terminating anything.
    matches = own_processes()
    if not matches:
        print("This ComfyUI installation is already stopped.")
        return
    try:
        request(8188, "/queue", {"clear": True})
        request(8188, "/interrupt", {})
    except urllib.error.URLError:
        pass
    for process in matches:
        subprocess.run(["taskkill", "/PID", str(process["ProcessId"]), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("ComfyUI stopped. Saved images and videos are preserved.")

if __name__ == "__main__":
    try:
        {"start": start, "stop": stop}[sys.argv[1]]()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
