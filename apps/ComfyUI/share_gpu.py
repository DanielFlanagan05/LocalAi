"""Release idle local models before switching between Strata and ComfyUI."""
import json
import sys
import time
import urllib.error
import urllib.request

def request(port, path, data=None):
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        body = response.read()
        return json.loads(body) if body else {}

def release_strata():
    try:
        health = request(8080, "/health")
    except urllib.error.URLError as error:
        if isinstance(error.reason, ConnectionRefusedError) or getattr(error.reason, "winerror", None) == 10061:
            return
        raise RuntimeError("Strata is not responding. Stop its model or wait for its current request before starting ComfyUI.") from error
    if health.get("service") != "strata":
        return
    try:
        result = request(8080, "/unload", {})
    except urllib.error.HTTPError as error:
        if error.code == 409:
            raise RuntimeError("Strata is busy. Finish the text request before generating images or video.") from error
        raise
    if result.get("status") == "busy" or result.get("state") == "busy":
        raise RuntimeError("Strata is busy. Finish the text request before generating images or video.")
    if request(8080, "/health").get("loaded"):
        raise RuntimeError("Strata's model is still loaded. Wait for the current text request to finish.")

def release_comfy():
    try:
        queue = request(8188, "/queue")
    except urllib.error.URLError as error:
        if isinstance(error.reason, ConnectionRefusedError) or getattr(error.reason, "winerror", None) == 10061:
            return
        raise
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise RuntimeError("ComfyUI is generating. Finish or cancel its queue before loading Strata.")
    request(8188, "/free", {"unload_models": True, "free_memory": True})
    time.sleep(2)  # ComfyUI processes its free-memory flag in the queue worker.

if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--comfy"]:
            release_comfy()
        else:
            release_strata()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
