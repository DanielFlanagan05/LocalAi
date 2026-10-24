#!/usr/bin/env python3
"""Time the installed ready-to-use video graphs and record node-level wall times."""
import argparse
import asyncio
import copy
import json
from pathlib import Path
import signal
import subprocess
import time
import uuid

import aiohttp
from localai import ROOT, paths, running, save_json, start, stop, validation_metadata
from telemetry import Monitor


async def generate(session, graph, destination, label):
    client = str(uuid.uuid4())
    async with session.ws_connect('http://127.0.0.1:8188/ws?clientId=' + client) as ws:
        begin = time.perf_counter()
        async with session.post('http://127.0.0.1:8188/prompt', json={'prompt': graph, 'client_id': client}) as response:
            accepted = await response.json()
            if response.status != 200: raise RuntimeError(str(accepted))
        prompt_id = accepted['prompt_id']
        result = {'label': label, 'status': 'running', 'prompt_id': prompt_id, 'node_seconds': {}, 'cached_nodes': []}
        save_json(destination, result)
        previous = None
        since = begin
        while True:
            message = await asyncio.wait_for(ws.receive(), timeout=1800)
            if message.type != aiohttp.WSMsgType.TEXT:
                if message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    raise RuntimeError('ComfyUI WebSocket closed before completion')
                continue
            event = json.loads(message.data)
            data = event.get('data', {})
            if data.get('prompt_id') != prompt_id: continue
            if event['type'] in ('execution_error', 'execution_interrupted'):
                raise RuntimeError(str(data)[:3000])
            if event['type'] == 'execution_cached': result['cached_nodes'] = data['nodes']
            if event['type'] != 'executing': continue
            now = time.perf_counter()
            if previous is not None:
                result['node_seconds'][previous] = now - since
                print(json.dumps({'run': label, 'node': graph[previous]['class_type'], 'seconds': round(now-since, 2)}), flush=True)
            previous = data['node']
            since = now
            if previous is None: break
        result['generation_seconds'] = time.perf_counter() - begin
        async with session.get('http://127.0.0.1:8188/history/' + prompt_id) as response:
            record = (await response.json())[prompt_id]
        if record.get('status', {}).get('status_str') != 'success': raise RuntimeError(str(record.get('status')))
        videos = []
        for output in record.get('outputs', {}).values():
            for key in ('images', 'gifs', 'videos'):
                for item in output.get(key, []):
                    path = paths()['data'] / 'outputs' / item.get('subfolder', '') / item['filename']
                    if path.suffix.lower() not in ('.mp4', '.webm', '.mkv'): continue
                    metadata = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],text=True))
                    stream = next(s for s in metadata['streams'] if s['codec_type'] == 'video')
                    expected = graph['5']['inputs']
                    assert stream['width'] == expected['width'] and stream['height'] == expected['height']
                    assert int(stream['nb_frames']) == expected['length']
                    if graph['5']['class_type'] == 'MiniMaxH3ImageToVideo':
                        assert any(s['codec_type'] == 'audio' for s in metadata['streams']), 'H3 audio stream missing'
                    sheet = destination.with_suffix('.contact.png')
                    count = int(stream['nb_frames'])
                    subprocess.run(['ffmpeg','-v','error','-y','-i',str(path),'-vf',f'select=eq(n\\,0)+eq(n\\,{count//2})+eq(n\\,{count-1}),scale=384:-1,tile=3x1','-frames:v','1',str(sheet)],check=True)
                    videos.append({'path': str(path), 'metadata': metadata, 'contact_sheet': str(sheet)})
        if not videos: raise RuntimeError('No video output found')
        result.update(status='passed', videos=videos)
        save_json(destination, result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', nargs='+', choices=['h3','wan-aio'], default=['h3','wan-aio'])
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--width', type=int, default=512)
    parser.add_argument('--height', type=int, default=288)
    parser.add_argument('--phase', default='baseline')
    parser.add_argument('--ready-size', action='store_true', help='Use each ready workflow’s full default resolution and duration.')
    parser.add_argument('--h3-pack', action='store_true', help='Test the reviewed exact H3 attention-layout node.')
    parser.add_argument('--cached', action='store_true', help='Test the opt-in single-family RAM cache.')
    args = parser.parse_args()
    if running(): parser.error('Finish active work and stop the existing runtime first.')
    if args.cached and len(args.models)>1: parser.error('Cached mode requires one model family per server lifetime.')
    if not 1 <= args.repeats <= 3: parser.error('repeats must be 1..3')
    if args.width % 32 or args.height % 32: parser.error('dimensions must be multiples of32')
    folder = paths()['state'] / 'video-performance' / f'{args.phase}-{int(time.time())}'
    report = {'phase':args.phase,'status':'running','runs':[], 'started':time.time(),
              'limitations':'Client-observed node durations include loading, synchronization and transfers. Synthetic clips, not a general quality ranking. Different seeds are used for repeat runs.'}
    save_json(folder/'results.json',report)
    owner = None
    def interrupt(*_): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    async def work():
        async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=3600)) as session:
            for model in args.models:
                graph = json.loads((ROOT/f'workflows/linux/ready-api/{model}.json').read_text())
                # Keep the control unpatched if the ready workflow later adopts
                # the validated layout node. --h3-pack is the explicit test arm.
                if model == 'h3':
                    for key in list(graph):
                        if graph[key]['class_type'] == 'RDNA35PatchMiniMaxH3GFX1151Attention': del graph[key]
                    graph['7']['inputs']['model'] = ['6',0]
                    graph['8']['inputs']['model'] = ['6',0]
                if not args.ready_size:
                    graph['5']['inputs'].update(width=args.width,height=args.height,length=39 if model=='h3' else 33)
                if model == 'h3' and args.h3_pack:
                    graph['pack'] = {'class_type':'RDNA35PatchMiniMaxH3GFX1151Attention',
                                     'inputs':{'model':['6',0],'enabled':True,'verbose_fallbacks':True}}
                    graph['7']['inputs']['model'] = ['pack',0]
                    graph['8']['inputs']['model'] = ['pack',0]
                output = '15' if model == 'h3' else '10'
                for repeat in range(args.repeats):
                    task = copy.deepcopy(graph)
                    task['10' if model=='h3' else '7']['inputs']['noise_seed' if model=='h3' else 'seed'] = 48271+repeat
                    task[output]['inputs']['filename_prefix'] = f'LocalAI/performance/{args.phase}-{model}-{repeat}'
                    label = f'{model}-{repeat}'
                    save_json(folder/f'{label}.workflow.json',task)
                    row = await generate(session,task,folder/f'{label}.json',label)
                    row.update(model=model,repeat=repeat,workflow=task)
                    report['runs'].append(row)
                    save_json(folder/'results.json',report)
                    print(json.dumps({'run':label,'generation_seconds':row['generation_seconds'],'status':row['status']}),flush=True)
    with Monitor() as monitor:
        try:
            profile = 'comfyui-cached' if args.cached else 'comfyui'
            owner = start(profile)
            report.update(validation_metadata(profile))
            asyncio.run(work())
            report['status'] = 'passed'
        except KeyboardInterrupt: report['status'] = 'cancelled'
        except Exception as error: report.update(status='failed',error=repr(error))
        finally:
            current = running()
            if owner and current and current['identity'] == owner['identity']: stop()
    report.update(telemetry=monitor.report(),finished=time.time())
    save_json(folder/'results.json',report)
    print(json.dumps({'report':str(folder/'results.json'),'status':report['status'],'error':report.get('error')}),flush=True)
    return int(report['status']!='passed')


if __name__ == '__main__': raise SystemExit(main())
