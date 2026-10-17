import json
from pathlib import Path
import uuid


root = Path(__file__).resolve().parent
source = root / "backups" / "before-gpu-workflow-fix"
target = root / "ready_workflows"
target.mkdir(exist_ok=True)

image = json.loads((source / "Qwen-Image-2.1-ready.json").read_text(encoding="utf-8-sig"))
image["id"] = str(uuid.uuid4())
image["extra"]["workflowName"] = "Image Generation - Qwen Image 2.1"
image["extra"]["frontendVersion"] = "1.53.10"
for node in image["nodes"]:
    if node["type"] == "UNETLoader":
        node["widgets_values"] = ["qwen_image_2.1_fp8_e4m3fn.safetensors", "fp8_e4m3fn"]
        node["properties"]["models"] = [{"name": "qwen_image_2.1_fp8_e4m3fn.safetensors", "directory": "diffusion_models"}]
    elif node["type"] == "SaveImage":
        node["widgets_values"] = ["images/Qwen-Image-2.1"]
        node["size"] = [430, 450]
    elif node["type"] == "TextEncodeQwenImage21":
        node["title"] = "Image prompt and resolution"

video = json.loads((source / "Wan-2.2-5B-video-test.json").read_text(encoding="utf-8-sig"))
video["id"] = str(uuid.uuid4())
video["extra"]["workflowName"] = "Video Generation - Wan 2.2 5B"
video["extra"]["frontendVersion"] = "1.53.10"
video["nodes"] = [node for node in video["nodes"] if node["type"] != "LoadImage"]
video["links"] = [link for link in video["links"] if link[0] != 106]
video["groups"] = [group for group in video["groups"] if "For i2v" not in group.get("title", "")]
group_titles = {"Step1 - Load models": "Models", "Step3 - Prompt": "Video prompt", "Video Size & length": "Video size and duration"}
for group in video["groups"]:
    group["title"] = group_titles.get(group["title"], group["title"])
for node in video["nodes"]:
    if node["type"] == "VAEDecode":
        node["type"] = "VAEDecodeTiled"
        node["title"] = "Decode video with bounded GPU memory"
        node["properties"]["Node name for S&R"] = "VAEDecodeTiled"
        node["widgets_values"] = [256, 64, 16, 4]
        node["size"] = [320, 170]
        node["pos"] = [1190, 50]
    elif node["type"] == "Wan22ImageToVideoLatent":
        next(i for i in node["inputs"] if i["name"] == "start_image")["link"] = None
        node["title"] = "Video size and duration (optional start image)"
    elif node["type"] == "CLIPLoader":
        node["widgets_values"] = ["umt5_xxl_fp8_e4m3fn_scaled.safetensors", "wan", "default"]
    elif node["type"] == "CLIPTextEncode" and node["id"] == 6:
        node["title"] = "Video prompt"
        node["widgets_values"] = ["A small red fox beside a woodland stream in golden autumn light, gently turning its head and swaying its tail. Water ripples and leaves drift past. Cinematic watercolor animation, steady camera, smooth natural movement."]
    elif node["type"] == "CLIPTextEncode":
        node["title"] = "Negative prompt"
        node["widgets_values"] = ["flicker, jitter, warped anatomy, extra limbs, text, watermark, low quality, unnatural motion, static frame"]
    elif node["type"] == "KSampler":
        node["widgets_values"][1] = "randomize"
        node["widgets_values"][4] = "dpmpp_2m"
    elif node["type"] == "SaveVideo":
        node["widgets_values"] = ["video/Wan-2.2-5B", "mp4", "h264"]
        node["pos"] = [1190, 430]
    elif node["type"] == "CreateVideo":
        node["pos"] = [1190, 280]
    elif node["type"] == "MarkdownNote":
        node["widgets_values"] = ["# Video Generation - Wan 2.2 5B\n\nEdit the Video prompt and click Run. All models are installed locally.\n\nDefault: 832 x 480, 49 frames at 24 fps (about 2 seconds), 20 sampling steps. Increase length in multiples of 4 plus 1: 49, 81, 121. Longer or larger clips take more VRAM and time.\n\nFor image-to-video, add a Load Image node, upload an image, and connect IMAGE to start_image. Without that connection this is text-to-video.\n\nOutputs: outputs/video/Wan-2.2-5B_*.mp4 (H.264). Keep the text encoder type set to wan and its device at default for GPU use."]

for name, workflow in [("Image Generation - Qwen Image 2.1", image), ("Video Generation - Wan 2.2 5B", video)]:
    nodes = {node["id"]: node for node in workflow["nodes"]}
    for link_id, src, src_slot, dst, dst_slot, kind in workflow["links"]:
        assert nodes[dst]["inputs"][dst_slot]["link"] == link_id
        assert link_id in nodes[src]["outputs"][src_slot]["links"]
    (target / f"{name}.json").write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")
    print(name, len(nodes), "nodes; links verified")
