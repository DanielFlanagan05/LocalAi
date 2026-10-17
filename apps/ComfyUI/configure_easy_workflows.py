"""Build ComfyUI App Mode forms around the verified native workflows."""
import copy
import json
from pathlib import Path
import shutil
import uuid

root = Path(__file__).resolve().parent
target = root / "ready_workflows"
backup = root / "backups/before-app-mode"
backup.mkdir(parents=True, exist_ok=True)
for file in target.glob("*.json"):
    if not (backup / file.name).exists():
        shutil.copy2(file, backup / file.name)

def node(workflow, identifier):
    return next(n for n in workflow["nodes"] if n["id"] == identifier)

def form(workflow, name, inputs, output):
    labels = {"prompt": "Prompt", "image": "Starting image", "resolution": "Resolution", "steps": "Steps", "seed": "Seed", "noise_seed": "Seed", "width": "Width", "height": "Height", "length": "Duration (frames)"}
    for identifier, widget, description in inputs:
        if widget == "control_after_generate":
            continue
        owner = node(workflow, identifier)
        label = owner.get("title", "Prompt") if widget == "text" else labels[widget]
        socket = next((value for value in owner.setdefault("inputs", []) if value.get("widget", {}).get("name") == widget), None)
        if socket is None:
            socket = {"name": widget, "type": "STRING" if widget in {"text", "prompt"} else "COMBO" if widget == "image" else "INT", "widget": {"name": widget}, "link": None}
            owner["inputs"].append(socket)
        socket["label"] = label
    workflow["id"] = str(uuid.uuid4())
    workflow.setdefault("extra", {}).update({
        "workflowName": name, "frontendVersion": "1.53.10", "linearMode": True,
        "linearData": {"inputs": [[i, widget, {"description": description}] for i, widget, description in inputs if widget != "control_after_generate"], "outputs": [output]},
    })
    (target / (name + ".app.json")).write_text(json.dumps(workflow, indent=2), encoding="utf-8")

def load_image(workflow, identifier, consumer, input_name):
    link_id = max(link[0] for link in workflow["links"]) + 1
    socket = next(i for i, value in enumerate(node(workflow, consumer)["inputs"]) if value["name"] == input_name)
    node(workflow, consumer)["inputs"][socket]["link"] = link_id
    workflow["links"].append([link_id, identifier, 0, consumer, socket, "IMAGE"])
    workflow["nodes"].append({
        "id": identifier, "type": "LoadImage", "pos": [20, 700], "size": [350, 400],
        "flags": {}, "order": 0, "mode": 0, "title": "Upload your starting image",
        "inputs": [], "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [link_id]}, {"name": "MASK", "type": "MASK", "links": []}],
        "properties": {"Node name for S&R": "LoadImage"}, "widgets_values": ["Example - Woodland Fox.png", "image"],
    })
    workflow["last_node_id"] = max(workflow.get("last_node_id", 0), identifier)
    workflow["last_link_id"] = link_id

shutil.copy2(root / "outputs/images/Qwen-Image-2.1_00003_.png", root / "ComfyUI/input/Example - Woodland Fox.png")
image = json.loads((backup / "Image Generation - Qwen Image 2.1.json").read_text())
image_inputs = [
    (5, "prompt", "Describe the image you want. Qwen excels at detailed instructions and text in images."),
    (5, "resolution", "1024 is the verified default. Lower resolution uses less memory."),
    (6, "steps", "25 is the verified quality setting; fewer steps are faster."),
    (6, "seed", "The seed randomizes after each run. Switch control to fixed to repeat an image."),
    (6, "control_after_generate", "Randomize for variety; fixed to reproduce the same result."),
]
form(image, "Image Generation - Qwen Image 2.1", image_inputs, 8)
edit = copy.deepcopy(image)
load_image(edit, 10, 5, "images.image_1")
vae_link = edit["last_link_id"] + 1
socket = next(i for i, value in enumerate(node(edit, 5)["inputs"]) if value["name"] == "vae")
node(edit, 5)["inputs"][socket]["link"] = vae_link
node(edit, 3)["outputs"][0]["links"].append(vae_link)
edit["links"].append([vae_link, 3, 0, 5, socket, "VAE"])
edit["last_link_id"] = vae_link
node(edit, 5)["title"] = "Describe the change to your image"
node(edit, 5)["widgets_values"][0] = "Keep the fox and composition. Change the setting to a snowy winter forest, with soft falling snow and warm evening light."
node(edit, 5)["widgets_values"][2] = 768
node(edit, 4)["widgets_values"] = ["off", "default"]
node(edit, 8)["widgets_values"] = ["images/Qwen-Image-Edit"]
edit_inputs = image_inputs.copy()
edit_inputs[0] = (5, "prompt", "Describe what to change and what to preserve in your uploaded image.")
edit_inputs[1] = (5, "resolution", "768 is the edit default; the output follows your reference image's aspect ratio.")
form(edit, "Image Editing - Qwen Image 2.1", [(10, "image", "Upload your image here. The woodland fox is a ready-to-run example.")] + edit_inputs, 8)

video = json.loads((backup / "Video Generation - Wan 2.2 5B.json").read_text())
node(video, 59)["widgets_values"] = ["Describe movement, subject and camera. Default: 832 x 480, 49 frames at 24 fps, 20 steps. Use Video Animation to animate an uploaded image without wiring nodes. Output: outputs/video."]
video_inputs = [
    (6, "text", "Describe the scene, movement and camera. Keep motion simple for a short clip."),
    (55, "width", "832 is the verified landscape width. Use multiples of 32."),
    (55, "height", "480 is the verified landscape height. Use multiples of 32."),
    (55, "length", "Frames: 49 = about 2 seconds; 81 = about 3.4 seconds; 121 = about 5 seconds at 24 fps. Longer clips need more memory and time. Use 4n+1 frames."),
    (3, "steps", "20 is the verified default; fewer steps preview motion faster."),
    (3, "seed", "The seed randomizes after each run."),
    (3, "control_after_generate", "Randomize for variety; fixed to reproduce the same clip."),
]
form(video, "Video Generation - Wan 2.2 5B", video_inputs, 58)
animation = copy.deepcopy(video)
load_image(animation, 60, 55, "start_image")
node(animation, 6)["widgets_values"] = ["The fox gently turns its head and flicks its ears, its tail swaying slowly. A few autumn leaves drift past. Steady camera, subtle natural motion. Preserve the original subject and style."]
node(animation, 58)["widgets_values"] = ["video/Wan-Image-Animation", "mp4", "h264"]
form(animation, "Video Animation - Wan 2.2 5B", [(60, "image", "Upload the image to animate. The example fox is already connected.")] + video_inputs, 58)

template = root / "python_embeded/Lib/site-packages/comfyui_workflow_templates_json/templates/image_chroma_text_to_image.json"
chroma = json.loads(template.read_text(encoding="utf-8"))
node(chroma, 743)["widgets_values"] = ["Chroma1-HD FP8 and its text encoder and VAE are installed. Edit the prompt and Run. Default: 1024 x 1024, 26 steps. Images are saved in outputs/images. See GPU_WORKFLOWS.md for model choices and memory sharing with Strata."]
node(chroma, 748)["title"] = "Image prompt"
node(chroma, 748)["widgets_values"] = ["A cinematic photograph of a red fox in a misty autumn forest beside a woodland stream. Natural warm light, detailed fur, soft background, beautiful composition."]
node(chroma, 749)["title"] = "Avoid in the image"
node(chroma, 749)["widgets_values"] = ["blurry, low quality, deformed, artifacts, watermark"]
node(chroma, 740)["widgets_values"] = ["images/Chroma1-HD"]
form(chroma, "Image Generation - Chroma1 HD", [
    (748, "text", "Describe your image. Chroma1-HD is the Apache 2.0 model whose authors state it has no specific safety alignment."),
    (749, "text", "Optional: things to avoid in the image."),
    (737, "width", "1024 is the default. Use multiples of 64."),
    (737, "height", "1024 is the default. Use multiples of 64."),
    (734, "steps", "26 steps follows ComfyUI's official template."),
    (718, "noise_seed", "The seed randomizes after each run."),
    (718, "control_after_generate", "Randomize for variety; fixed to reproduce an image."),
], 740)
print("Configured five workflow forms with preconnected models and image inputs.")
