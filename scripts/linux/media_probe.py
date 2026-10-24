#!/usr/bin/env python3
"""Run a minimal local image graph and verify its output decodes."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.request
from localai import http, paths, save_json, start, running, read_json, error_detail, sha256, validation_metadata

def attach_reference(graph, family, filename):
    node = {'class_type': 'LoadImage', 'inputs': {'image': filename}}
    if family == 'wan-aio': graph['4'] = node
    elif family == 'qwen-image':
        graph['reference'] = node
        graph['4']['inputs']['images'] = {'image_1': ['reference', 0]}
        graph['8']['inputs']['latent_image'] = ['4', 2]
    elif family == 'flux2':
        graph['reference'] = node
        graph['reference-latent'] = {'class_type': 'VAEEncode', 'inputs': {'pixels': ['reference', 0], 'vae': ['3', 0]}}
        graph['reference-conditioning'] = {'class_type': 'ReferenceLatent', 'inputs': {'conditioning': ['5', 0], 'latent': ['reference-latent', 0]}}
        graph['7']['inputs']['conditioning'] = ['reference-conditioning', 0]
    else: raise ValueError('Reference baseline supports Qwen Image, FLUX.2 and Wan I2V')

def upload_reference(base, path):
    boundary = 'localai-reference-upload-48271'
    name = 'localai-reference-' + sha256(path)[:20] + path.suffix.lower()
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
            + path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode())
    request = urllib.request.Request(base + '/upload/image', data=body, headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=60) as response: uploaded = json.load(response)
    return '/'.join(v for v in (uploaded.get('subfolder'), uploaded['name']) if v)

def image_graph(family, size, steps, seed):
    if family == 'flux2':
        return {
            '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'flux2_dev_fp8mixed.safetensors', 'weight_dtype': 'default'}},
            '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'mistral_3_small_flux2_fp8.safetensors', 'type': 'flux2', 'device': 'default'}},
            '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'flux2-vae.safetensors'}},
            '4': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': 'A red toy sailboat on a calm pond, soft daylight, realistic reflections, detailed photograph.'}},
            '5': {'class_type': 'FluxGuidance', 'inputs': {'conditioning': ['4', 0], 'guidance': 4.0}},
            '6': {'class_type': 'EmptyFlux2LatentImage', 'inputs': {'width': size, 'height': size, 'batch_size': 1}},
            '7': {'class_type': 'BasicGuider', 'inputs': {'model': ['1', 0], 'conditioning': ['5', 0]}},
            '8': {'class_type': 'Flux2Scheduler', 'inputs': {'steps': steps, 'width': size, 'height': size}},
            '9': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'euler'}},
            '10': {'class_type': 'RandomNoise', 'inputs': {'noise_seed': seed}},
            '11': {'class_type': 'SamplerCustomAdvanced', 'inputs': {'noise': ['10', 0], 'guider': ['7', 0], 'sampler': ['9', 0], 'sigmas': ['8', 0], 'latent_image': ['6', 0]}},
            '12': {'class_type': 'VAEDecode', 'inputs': {'samples': ['11', 0], 'vae': ['3', 0]}},
            '13': {'class_type': 'SaveImage', 'inputs': {'images': ['12', 0], 'filename_prefix': 'localai-probe/flux2'}}}
    definitions = {
        'z-image': ('z_image_turbo_bf16.safetensors', 'qwen_3_4b.safetensors', 'ae.safetensors', 'lumina2', 3.0, 1.0, 'simple'),
        'qwen-image': ('qwen_image_2.1_bf16.safetensors', 'qwen3vl_8b_bf16.safetensors', 'qwen_image_2.1_vae_bf16.safetensors', 'qwen_image', 3.0, 1.0, 'simple'),
        'chroma': ('Chroma1-HD.safetensors', 't5xxl_fp8_e4m3fn_scaled.safetensors', 'ae.safetensors', 'chroma', 1.0, 3.5, 'beta')}
    unet, clip, vae, clip_type, shift, cfg, scheduler = definitions[family]
    graph = {
        '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': unet, 'weight_dtype': 'default'}},
        '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': clip, 'type': clip_type, 'device': 'default'}},
        '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': vae}},
        '4': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'A studio photograph of a fictional 40-year-old person wearing a blue linen jacket, natural skin texture, neutral grey background, soft window lighting, detailed hands resting on a wooden table.', 'clip': ['2', 0]}},
        '5': {'class_type': 'ConditioningZeroOut', 'inputs': {'conditioning': ['4', 0]}},
        '6': {'class_type': 'EmptySD3LatentImage', 'inputs': {'width': size, 'height': size, 'batch_size': 1}},
        '7': {'class_type': 'ModelSamplingAuraFlow', 'inputs': {'model': ['1', 0], 'shift': shift}},
        '8': {'class_type': 'KSampler', 'inputs': {'model': ['7', 0], 'seed': seed, 'steps': steps, 'cfg': cfg,
                'sampler_name': 'euler', 'scheduler': scheduler, 'positive': ['4', 0], 'negative': ['5', 0], 'latent_image': ['6', 0], 'denoise': 1.0}},
        '9': {'class_type': 'VAEDecode', 'inputs': {'samples': ['8', 0], 'vae': ['3', 0]}},
        '10': {'class_type': 'SaveImage', 'inputs': {'images': ['9', 0], 'filename_prefix': 'localai-probe/' + family}}}
    if family == 'qwen-image':
        graph['4'] = {'class_type': 'TextEncodeQwenImage21', 'inputs': {
            'clip': ['2', 0], 'prompt': graph['4']['inputs']['text'], 'negative_prompt': '', 'resolution': size,
            'images': {}, 'vae': ['3', 0]}}
        graph['8']['inputs']['negative'] = ['4', 1]
        graph['6']['class_type'] = 'EmptyLatentImage'
        del graph['5']
    elif family == 'chroma':
        graph['11'] = {'class_type': 'T5TokenizerOptions', 'inputs': {'clip': ['2', 0], 'min_padding': 0, 'min_length': 0}}
        graph['4']['inputs']['clip'] = ['11', 0]
    return graph

def video_graph(family, steps, frames, width, height):
    prompt = 'A red toy sailboat gently rocking on a calm pond, soft daylight, a slow steady camera, realistic reflections.'
    if family == 'ltx':
        if steps != 8: raise ValueError('The LTX baseline uses its eight-step distilled sigma schedule')
        checkpoint = 'ltx-2.3-22b-dev.safetensors'
        return {
            '1': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': checkpoint}},
            '2': {'class_type': 'LTXAVTextEncoderLoader', 'inputs': {'text_encoder': 'gemma_3_12B_it_fp8_scaled.safetensors', 'ckpt_name': checkpoint, 'device': 'default'}},
            '3': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': prompt + ' Gentle water sounds, no speech.'}},
            '4': {'class_type': 'ConditioningZeroOut', 'inputs': {'conditioning': ['3', 0]}},
            '5': {'class_type': 'LTXVConditioning', 'inputs': {'positive': ['3', 0], 'negative': ['4', 0], 'frame_rate': 25.0}},
            '6': {'class_type': 'EmptyLTXVLatentVideo', 'inputs': {'width': width, 'height': height, 'length': frames, 'batch_size': 1}},
            '7': {'class_type': 'LTXVAudioVAELoader', 'inputs': {'ckpt_name': checkpoint}},
            '8': {'class_type': 'LTXVEmptyLatentAudio', 'inputs': {'frames_number': frames, 'frame_rate': 25, 'batch_size': 1, 'audio_vae': ['7', 0]}},
            '9': {'class_type': 'LTXVConcatAVLatent', 'inputs': {'video_latent': ['6', 0], 'audio_latent': ['8', 0]}},
            '10': {'class_type': 'LoraLoaderModelOnly', 'inputs': {'model': ['1', 0], 'lora_name': 'ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors', 'strength_model': 0.5}},
            '11': {'class_type': 'CFGGuider', 'inputs': {'model': ['10', 0], 'positive': ['5', 0], 'negative': ['5', 1], 'cfg': 1.0}},
            '12': {'class_type': 'RandomNoise', 'inputs': {'noise_seed': 48271}},
            '13': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'euler'}},
            '14': {'class_type': 'ManualSigmas', 'inputs': {'sigmas': '1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0'}},
            '15': {'class_type': 'SamplerCustomAdvanced', 'inputs': {'noise': ['12', 0], 'guider': ['11', 0], 'sampler': ['13', 0], 'sigmas': ['14', 0], 'latent_image': ['9', 0]}},
            '16': {'class_type': 'LTXVSeparateAVLatent', 'inputs': {'av_latent': ['15', 0]}},
            '17': {'class_type': 'VAEDecodeTiled', 'inputs': {'samples': ['16', 0], 'vae': ['1', 2], 'tile_size': 512, 'overlap': 64, 'temporal_size': 64, 'temporal_overlap': 8}},
            '18': {'class_type': 'LTXVAudioVAEDecode', 'inputs': {'samples': ['16', 1], 'audio_vae': ['7', 0]}},
            '19': {'class_type': 'CreateVideo', 'inputs': {'images': ['17', 0], 'audio': ['18', 0], 'fps': 25.0}},
            '20': {'class_type': 'SaveVideo', 'inputs': {'video': ['19', 0], 'filename_prefix': 'localai-probe/ltx', 'format': 'mp4', 'format.codec': 'h264'}}}
    if family == 'h3':
        return {
            '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'minimax_h3_fl2va_pruned_int8_convrot.safetensors', 'weight_dtype': 'default'}},
            '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'qwen3vl_32b_minimax_h3_int8_convrot.safetensors', 'type': 'minimax', 'device': 'default'}},
            '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'minimax_h3_video_vae_fp16.safetensors'}},
            '4': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'minimax_h3_audio_vae_fp32.safetensors'}},
            '5': {'class_type': 'MiniMaxH3ImageToVideo', 'inputs': {'clip': ['2', 0], 'vae': ['3', 0], 'prompt': prompt, 'width': width, 'height': height, 'length': frames}},
            '6': {'class_type': 'LoraLoaderModelOnly', 'inputs': {'model': ['1', 0], 'lora_name': 'minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors', 'strength_model': 1.0}},
            '7': {'class_type': 'BasicGuider', 'inputs': {'model': ['6', 0], 'conditioning': ['5', 0]}},
            '8': {'class_type': 'BasicScheduler', 'inputs': {'model': ['6', 0], 'scheduler': 'simple', 'steps': steps, 'denoise': 1.0}},
            '9': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'res_multistep'}},
            '10': {'class_type': 'RandomNoise', 'inputs': {'noise_seed': 48271}},
            '11': {'class_type': 'SamplerCustomAdvanced', 'inputs': {'noise': ['10', 0], 'guider': ['7', 0], 'sampler': ['9', 0], 'sigmas': ['8', 0], 'latent_image': ['5', 1]}},
            '12': {'class_type': 'VAEDecode', 'inputs': {'samples': ['11', 0], 'vae': ['3', 0]}},
            '13': {'class_type': 'VAEDecodeAudio', 'inputs': {'samples': ['11', 0], 'vae': ['4', 0]}},
            '14': {'class_type': 'CreateVideo', 'inputs': {'images': ['12', 0], 'audio': ['13', 0], 'fps': 24.0}},
            '15': {'class_type': 'SaveVideo', 'inputs': {'video': ['14', 0], 'filename_prefix': 'localai-probe/h3', 'format': 'mp4', 'format.codec': 'h264'}}}
    return {
        '1': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': 'wan2.2-rapid-mega-aio-nsfw-v12.1.safetensors'}},
        '2': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['1', 1], 'text': prompt}},
        '3': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['1', 1], 'text': 'blurry, distorted, static'}},
        '4': {'class_type': 'EmptyImage', 'inputs': {'width': width, 'height': height, 'batch_size': 1, 'color': 8421504}},
        '5': {'class_type': 'WanImageToVideo', 'inputs': {'positive': ['2', 0], 'negative': ['3', 0], 'vae': ['1', 2], 'width': width, 'height': height, 'length': frames, 'batch_size': 1, 'start_image': ['4', 0]}},
        '6': {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['1', 0], 'shift': 5.0}},
        '7': {'class_type': 'KSampler', 'inputs': {'model': ['6', 0], 'seed': 48271, 'steps': steps, 'cfg': 1.0, 'sampler_name': 'euler', 'scheduler': 'simple', 'positive': ['5', 0], 'negative': ['5', 1], 'latent_image': ['5', 2], 'denoise': 1.0}},
        '8': {'class_type': 'VAEDecode', 'inputs': {'samples': ['7', 0], 'vae': ['1', 2]}},
        '9': {'class_type': 'CreateVideo', 'inputs': {'images': ['8', 0], 'fps': 16.0}},
        '10': {'class_type': 'SaveVideo', 'inputs': {'video': ['9', 0], 'filename_prefix': 'localai-probe/wan-aio', 'format': 'mp4', 'format.codec': 'h264'}}}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=['qwen-image', 'chroma', 'h3', 'wan-aio'], default='qwen-image')
    parser.add_argument('--size', type=int, choices=[512, 1024], default=512)
    parser.add_argument('--steps', type=int, default=8)
    parser.add_argument('--frames', type=int, default=22)
    parser.add_argument('--width', type=int, default=320)
    parser.add_argument('--height', type=int, default=192)
    parser.add_argument('--prompt', help='Use the same synthetic scene across model comparisons.')
    parser.add_argument('--reference', type=Path, help='Generated PNG/JPEG reference for Qwen/FLUX editing or Wan I2V.')
    args = parser.parse_args()
    base = 'http://127.0.0.1:8188'
    begin = time.monotonic()
    video = args.model in ('h3', 'wan-aio', 'ltx')
    if args.steps < 1 or args.steps > 100: parser.error('steps must be 1..100')
    if video and (args.width % 32 or args.height % 32 or min(args.width, args.height) < 128): parser.error('video dimensions must be multiples of 32 and at least 128')
    grid = {'h3': (5, 17), 'wan-aio': (1, 4), 'ltx': (1, 8)}
    if video and (args.frames < 5 or (args.frames - grid[args.model][0]) % grid[args.model][1]):
        parser.error('H3 requires 17k+5 frames; Wan requires 4k+1; LTX requires 8k+1')
    if args.model == 'ltx' and args.steps != 8: parser.error('LTX baseline requires eight steps')
    if args.reference and (args.model not in ('qwen-image','flux2','wan-aio') or not args.reference.is_file() or args.reference.suffix.lower() not in ('.png','.jpg','.jpeg') or args.reference.stat().st_size > 20*1024*1024):
        parser.error('Reference must be a PNG/JPEG up to 20 MiB for Qwen Image, FLUX.2 or Wan')
    start('comfyui')
    graph = video_graph(args.model, args.steps, args.frames, args.width, args.height) if video else image_graph(args.model, args.size, args.steps, 48271)
    if args.prompt:
        # Positive prompt node differs by family; leave negative conditioning alone.
        node = graph['3' if args.model == 'ltx' else '5' if args.model == 'h3' else '2' if args.model == 'wan-aio' else '4']
        node['inputs']['prompt' if args.model in ('h3', 'qwen-image') else 'text'] = args.prompt
    if args.reference: attach_reference(graph, args.model, upload_reference(base, args.reference))
    destination = paths()['state'] / 'benchmarks' / f'media-{args.model}-{int(time.time())}.json'
    workflow = destination.with_suffix('.workflow.json')
    save_json(workflow, graph)
    metadata = {'model': args.model, 'parameters': {**vars(args), 'reference': str(args.reference) if args.reference else None},
                'reference_sha256': sha256(args.reference) if args.reference else None, 'workflow': str(workflow),
                'workflow_sha256': sha256(workflow),
                'adapter_sha256': sha256(Path(__file__)), **validation_metadata('comfyui')}
    try:
        response = http(base + '/prompt', {'prompt': graph, 'client_id': 'localai-synthetic-probe'})
        prompt_id = response['prompt_id']
    except (OSError, ValueError, KeyError) as error:
        save_json(destination, {**metadata, 'status': 'submission_failed', 'error': error_detail(error)})
        raise
    save_json(destination, {**metadata, 'status': 'submitted', 'prompt_id': prompt_id,
        'limitations': 'Generation submitted; not yet accepted. Inspect ComfyUI history by prompt_id after an interruption.'})
    deadline = time.monotonic() + 3600
    record = None
    while time.monotonic() < deadline:
        try:
            history = http(base + '/history/' + prompt_id, timeout=10)
        except (OSError, ValueError) as error:
            owner = running()
            if owner and owner['profile'] == 'comfyui':
                time.sleep(2)
                continue
            last = read_json(paths()['state'] / 'last-server.json', {})
            save_json(destination, {**metadata, 'status': 'interrupted', 'prompt_id': prompt_id,
                'error': error_detail(error), 'runtime_exit': last if last.get('profile') == 'comfyui' else None})
            raise RuntimeError('ComfyUI stopped during generation; inspect its supervisor log.') from error
        if prompt_id in history:
            record = history[prompt_id]
            break
        time.sleep(2)
    if record is None:
        save_json(destination, {**metadata, 'status': 'timed_out', 'prompt_id': prompt_id,
            'limitations': 'Client wait expired; the ComfyUI job may still be active. Inspect its queue/history.'})
        raise RuntimeError('Media probe timed out; inspect ComfyUI queue/log')
    from PIL import Image, ImageStat
    images = []
    videos = []
    for output in record.get('outputs', {}).values():
        for image in output.get('images', []):
            path = paths()['data'] / 'outputs' / image.get('subfolder', '') / image['filename']
            if path.suffix.lower() in ('.mp4', '.webm', '.mkv'): continue
            with Image.open(path) as bitmap:
                bitmap.load()
                variance = sum(ImageStat.Stat(bitmap.convert('RGB')).var)
                images.append({'path': str(path), 'width': bitmap.width, 'height': bitmap.height, 'pixel_variance': variance})
        for item in output.get('images', []) + output.get('gifs', []) + output.get('videos', []):
            path = paths()['data'] / 'outputs' / item.get('subfolder', '') / item['filename']
            if path.suffix.lower() not in ('.mp4', '.webm', '.mkv'): continue
            probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], text=True))
            videos.append({'path': str(path), 'metadata': probe})
    passed = (bool(videos) and all(any(s['codec_type'] == 'video' and s['width'] == args.width and s['height'] == args.height for s in v['metadata']['streams']) for v in videos)) if video else (bool(images) and all(i['width'] == args.size and i['height'] == args.size and i['pixel_variance'] > 1 for i in images))
    report = {**metadata, 'status': 'passed' if passed else 'failed', 'seconds': time.monotonic() - begin, 'prompt_id': prompt_id,
              'images': images, 'videos': videos, 'comfy_status': record.get('status'), 'limitations': 'Small synthetic media smoke test. Decode/shape/metadata checks only; visual quality and trained-resolution video require separate inspection.'}
    save_json(destination, report)
    print(json.dumps(report, indent=2))
    return int(not passed)

if __name__ == '__main__': raise SystemExit(main())
