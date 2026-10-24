#!/usr/bin/env python3
"""Import pinned public native workflows, adapting weight formats for AMD."""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
from localai import ROOT, paths, save_json

REVISION = '46e060ea88eb07adecf07197ec384c54a70e030c'
NAMES = ['image_chroma_text_to_image', 'image_qwen_image_2_1_t2i', 'image_qwen_image_2_1_image_edit',
         'image_z_image_turbo', 'image_flux2_fp8', 'video_minimax_h3_t2v', 'video_minimax_h3_i2v',
         'video_ltx2_3_t2v', 'video_wan2_2_14B_i2v']
REPLACEMENTS = {
    'Chroma1-HD-fp8mixed.safetensors': 'Chroma1-HD.safetensors',
    'qwen_image_2.1_int8_convrot.safetensors': 'qwen_image_2.1_bf16.safetensors',
    'qwen3vl_8b_int8_convrot.safetensors': 'qwen3vl_8b_bf16.safetensors',
    'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors': 'qwen3vl_32b_minimax_h3_int8_convrot.safetensors',
    'minimax_h3_video_vae_int8_convrot.safetensors': 'minimax_h3_video_vae_fp16.safetensors',
    'ltx-2.3-22b-dev-fp8.safetensors': 'ltx-2.3-22b-dev.safetensors',
    'gemma_3_12B_it_fp4_mixed.safetensors': 'gemma_3_12B_it_fp8_scaled.safetensors',
    'wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors': 'wan2.2_i2v_low_noise_14B_fp16.safetensors',
    'wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors': 'wan2.2_i2v_high_noise_14B_fp16.safetensors'}

def transform(value):
    if isinstance(value, str):
        for old, new in REPLACEMENTS.items(): value = value.replace(old, new)
        return value
    if isinstance(value, list): return [transform(x) for x in value]
    if isinstance(value, dict): return {k: transform(v) for k, v in value.items()}
    return value

def main():
    target = ROOT / 'workflows/linux'
    target.mkdir(parents=True, exist_ok=True)
    sources = []
    for name in NAMES:
        url = f'https://raw.githubusercontent.com/Comfy-Org/workflow_templates/{REVISION}/templates/{name}.json'
        raw = urllib.request.urlopen(url, timeout=45).read()
        value = transform(json.loads(raw))
        (target / f'{name}.json').write_text(json.dumps(value, indent=2) + '\n')
        sources.append({'name': name, 'source': url, 'source_sha256': hashlib.sha256(raw).hexdigest()})
    (target / 'SOURCES.json').write_text(json.dumps({'repository': 'Comfy-Org/workflow_templates', 'revision': REVISION,
        'license': 'MIT', 'sources': sources, 'model_format_replacements': REPLACEMENTS}, indent=2) + '\n')
    license_url = f'https://raw.githubusercontent.com/Comfy-Org/workflow_templates/{REVISION}/LICENSE'
    (target / 'LICENSE.upstream').write_bytes(urllib.request.urlopen(license_url, timeout=30).read())
    installed = paths()['state'] / 'comfyui/default/workflows'
    installed.mkdir(parents=True, exist_ok=True)
    for source in target.glob('*.json'):
        if source.name != 'SOURCES.json': shutil.copy2(source, installed / source.name)
    print(f'Prepared {len(NAMES)} native workflows. They still require model/node validation against the running server.')

if __name__ == '__main__': main()
