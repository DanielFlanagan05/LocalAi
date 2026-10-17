import json
from pathlib import Path
import sys
import urllib.request


root = Path(__file__).resolve().parent
url = "http://127.0.0.1:8188"
schemas = json.load(urllib.request.urlopen(url + "/object_info"))
queue = json.load(urllib.request.urlopen(url + "/queue"))
assert not queue["queue_running"] and not queue["queue_pending"], "Wait for the existing queue before verification"
widget_names = {
    "UNETLoader": ["unet_name", "weight_dtype"],
    "CLIPLoader": ["clip_name", "type", "device"],
    "VAELoader": ["vae_name"],
    "QwenImage21Cache": ["device", "dtype"],
    "TextEncodeQwenImage21": ["prompt", "negative_prompt", "resolution"],
    "KSampler": ["seed", None, "steps", "cfg", "sampler_name", "scheduler", "denoise"],
    "SaveImage": ["filename_prefix"],
    "CLIPTextEncode": ["text"],
    "ModelSamplingSD3": ["shift"],
    "Wan22ImageToVideoLatent": ["width", "height", "length", "batch_size"],
    "CreateVideo": ["fps"],
    "SaveVideo": ["filename_prefix", "format", "format.codec"],
    "VAEDecode": [],
    "VAEDecodeTiled": ["tile_size", "overlap", "temporal_size", "temporal_overlap"],
    "LoadImage": ["image", None],
    "CFGGuider": ["cfg"],
    "KSamplerSelect": ["sampler_name"],
    "ModelSamplingAuraFlow": ["shift"],
    "RandomNoise": ["noise_seed", None],
    "BasicScheduler": ["scheduler", "steps", "denoise"],
    "EmptySD3LatentImage": ["width", "height", "batch_size"],
    "T5TokenizerOptions": ["min_padding", "min_length"],
    "SamplerCustomAdvanced": [],
}
record = root / "workflow-verification.json"
submitted = json.loads(record.read_text(encoding="utf-8")) if record.exists() else {}
for file in sorted((root / "ready_workflows").glob("*.json")):
    name = file.stem.removesuffix(".app")
    if sys.argv[1:] and name not in sys.argv[1:]:
        continue
    workflow = json.loads(file.read_text(encoding="utf-8"))
    links = {link[0]: link for link in workflow["links"]}
    prompt = {}
    for node in workflow["nodes"]:
        kind = node["type"]
        if kind in {"MarkdownNote", "Note"}:
            continue
        assert kind in schemas, f"Missing node: {kind}"
        inputs = {key: value for key, value in zip(widget_names[kind], node.get("widgets_values", [])) if key is not None}
        for socket in node.get("inputs", []):
            if socket.get("link") is not None:
                link = links[socket["link"]]
                inputs[socket["name"]] = [str(link[1]), link[2]]
        prompt[str(node["id"])] = {"class_type": kind, "inputs": inputs}
    payload = {"prompt": prompt, "extra_data": {"extra_pnginfo": {"workflow": workflow}}}
    request = urllib.request.Request(url + "/prompt", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    result = json.load(urllib.request.urlopen(request))
    assert not result.get("node_errors"), result
    submitted[name] = result["prompt_id"]
    print(name, result, flush=True)
record.write_text(json.dumps(submitted, indent=2), encoding="utf-8")
