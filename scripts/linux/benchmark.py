#!/usr/bin/env python3
"""Measure actual API context usage, recall, concurrency, and warm continuations."""
from __future__ import annotations
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

from localai import http, paths, profiles, save_json, start, memory, sha256, error_detail, validation_metadata
from telemetry import Monitor
ADAPTER_SHA256 = sha256(Path(__file__))

def completion(base, model, messages, maximum=256, *, cache_prompt=None):
    begin = time.perf_counter()
    payload = {'model': model, 'messages': messages, 'stream': True, 'stream_options': {'include_usage': True},
        'max_tokens': maximum, 'temperature': 0,
        'chat_template_kwargs': {'enable_thinking': False, 'preserve_thinking': True}}
    if cache_prompt is not None: payload['cache_prompt'] = cache_prompt
    request = urllib.request.Request(base + '/chat/completions', data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer local-only'})
    answer = {'choices': [{'message': {'role': 'assistant', 'content': ''}, 'finish_reason': None}], 'usage': {}}
    first_token = None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=7200) as response:
        for raw in response:
            if not raw.startswith(b'data:'): continue
            content = raw[5:].strip()
            if content == b'[DONE]': break
            part = json.loads(content)
            if part.get('error'): raise RuntimeError('Server SSE error: ' + str(part['error'])[:1000])
            if part.get('usage'): answer['usage'] = part['usage']
            if part.get('timings'): answer['timings'] = part['timings']
            for choice in part.get('choices', []):
                delta = choice.get('delta', {})
                for key in ('content', 'reasoning_content'):
                    value = delta.get(key)
                    if value:
                        if first_token is None: first_token = time.perf_counter() - begin
                        answer['choices'][0]['message'][key] = answer['choices'][0]['message'].get(key, '') + value
                if choice.get('finish_reason'): answer['choices'][0]['finish_reason'] = choice['finish_reason']
    answer['transport'] = {'first_token_seconds': first_token}
    return answer, time.perf_counter() - begin

def prompt(repetitions, worker, dense=False):
    unit = ('000,111,222,333,444,555,666,777,888,999\n' if dense else
            'Reference material: cedar systems contain stable records; revisions preserve existing public interfaces.\n')
    blocks = [unit * max(1, repetitions // 4) for _ in range(4)]
    code = f'CEDAR-{worker}-48271'
    return (f'Find and retain the exact project code in this document.\n{blocks[0]}\n'
            f'Project code: {code}\n{blocks[1]}\n{blocks[2]}\n{blocks[3]}\n'
            'Return only the exact project code, with no explanation.'), code

def calibrated_text(base, model, target, index=0, dense=False):
    sample, _ = prompt(100, index, dense)
    larger, _ = prompt(1000, index, dense)
    try:
        count = len(http(base.removesuffix('/v1') + '/tokenize', {'content': sample})['tokens'])
        larger_count = len(http(base.removesuffix('/v1') + '/tokenize', {'content': larger})['tokens'])
    except (OSError, ValueError, KeyError):
        try:
            # Kyojin uses the vLLM prompt/messages tokenizer request shape.
            count = http(base.removesuffix('/v1') + '/tokenize', {'model': model, 'messages': [{'role':'user','content':sample}]})['count']
            larger_count = http(base.removesuffix('/v1') + '/tokenize', {'model': model, 'messages': [{'role':'user','content':larger}]})['count']
        except (OSError, ValueError, KeyError):
            count = larger_count = None
        try:
            # Gufo exposes Messages counting, rather than llama's /tokenize.
            # Counting must not evict live conversations with calibration chats.
            endpoint = base.removesuffix('/v1') + '/v1/messages/count_tokens'
            if count is None:
                count = http(endpoint, {'model': model, 'messages': [{'role': 'user', 'content': sample}], 'max_tokens': 32})['input_tokens']
                larger_count = http(endpoint, {'model': model, 'messages': [{'role': 'user', 'content': larger}], 'max_tokens': 32})['input_tokens']
        except (OSError, ValueError, KeyError):
            probe, _ = completion(base, model, [{'role': 'user', 'content': sample}], 32)
            count = probe.get('usage', {}).get('prompt_tokens')
            if not count: raise RuntimeError('Server supplies neither tokenization nor prompt usage; context cannot be verified.')
            probe, _ = completion(base, model, [{'role': 'user', 'content': larger}], 32)
            larger_count = probe.get('usage', {}).get('prompt_tokens')
            if not larger_count: raise RuntimeError('Server did not report calibrated prompt usage.')
    slope = (larger_count - count) / 900
    if slope <= 0: raise RuntimeError('Invalid tokenizer calibration')
    intercept = count - 100 * slope
    repetitions = max(4, int((target - intercept) / slope) + 8)
    text, expected = prompt(repetitions, index, dense)
    return text, expected

def worker(base, model, target, index, maximum, repeats, image_path=None):
    text, expected = calibrated_text(base, model, target, index)
    results = []
    for repeat in range(repeats):
        content = text
        if image_path:
            mime = 'image/png' if image_path.suffix.lower() == '.png' else 'image/jpeg'
            encoded = base64.b64encode(image_path.read_bytes()).decode()
            content = [{'type': 'text', 'text': text}, {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{encoded}'}}]
        messages = [{'role': 'user', 'content': content}]
        cold, seconds = completion(base, model, messages, maximum)
        msg = cold['choices'][0]['message']
        used = cold.get('usage', {})
        content = msg.get('content') or ''
        actual = used.get('prompt_tokens', 0)
        messages += [msg, {'role': 'user', 'content': 'Repeat that exact project code. No other text.'}]
        warm, warm_seconds = completion(base, model, messages, maximum)
        warm_usage = warm.get('usage', {})
        results.append({'repeat': repeat, 'actual_input_tokens': actual, 'target_input_tokens': target,
            'target_reached': actual >= target, 'recall_passed': content.strip() == expected,
            'warm_recall_passed': (warm['choices'][0]['message'].get('content') or '').strip() == expected,
            'cold_seconds': seconds, 'warm_seconds': warm_seconds,
            'cold_first_token_seconds': cold['transport']['first_token_seconds'],
            'warm_first_token_seconds': warm['transport']['first_token_seconds'],
            'cold_engine_timings': cold.get('timings'), 'warm_engine_timings': warm.get('timings'),
            'cold_usage': used, 'warm_usage': warm_usage,
            'finish_reason': cold['choices'][0].get('finish_reason')})
    return {'worker': index, 'runs': results}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=profiles())
    parser.add_argument('--input-tokens', type=int, default=8192)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--max-tokens', type=int, default=1024)
    parser.add_argument('--base-url', default='http://127.0.0.1:8080/v1')
    parser.add_argument('--no-start', action='store_true')
    parser.add_argument('--image', type=Path, help='Optional image attachment for long-context vision serving tests.')
    args = parser.parse_args()
    profile = profiles()[args.profile]
    if args.image and (not args.image.is_file() or args.image.stat().st_size > 16 * 1024 * 1024):
        parser.error('image must be an existing PNG/JPEG no larger than 16 MiB')
    if args.workers < 1 or args.workers > profile['sessions']:
        parser.error('workers must fit the profile session count')
    if not 1 <= args.repeats <= 20: parser.error('repeats must be between 1 and 20')
    if args.input_tokens < 1 or args.max_tokens < 1 or args.input_tokens + args.max_tokens + 2048 > profile['context']:
        parser.error('input and output must fit the per-session context with 2048 tokens of template headroom')
    if not args.no_start: start(args.profile)
    metadata = validation_metadata(args.profile)
    before = memory()
    begin = time.perf_counter()
    with Monitor() as monitor, ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(worker, args.base_url, args.profile, args.input_tokens, i,
                                   args.max_tokens, args.repeats, args.image) for i in range(args.workers)]
        runs = []
        for i, future in enumerate(futures):
            try: runs.append(future.result())
            except Exception as error: runs.append({'worker': i, 'error_type': type(error).__name__, 'error': error_detail(error)})
    passed = all('runs' in r and all(v['target_reached'] and v['recall_passed'] and v['warm_recall_passed'] for v in r['runs']) for r in runs)
    report = {'profile': args.profile, 'status': 'passed' if passed else 'failed',
        **metadata,
        'adapter_sha256': ADAPTER_SHA256,
        'requested_input_tokens': args.input_tokens, 'maximum_output_tokens': args.max_tokens, 'workers': args.workers,
        'elapsed_seconds': time.perf_counter() - begin, 'memory_before': before, 'memory_after': memory(), 'telemetry': monitor.report(), 'results': runs,
        'limitations': 'Exact needle recall/serving probe, not a coding-quality benchmark. Initial requests are labelled cold for compatibility but caches are not purged; inspect cached-token counts. Repeats and shared prefixes may reuse cache. Wall time includes queueing/reasoning/transport; it is not prefill or decode throughput.'}
    destination = paths()['state'] / 'benchmarks' / f'{args.profile}-{int(time.time())}.json'
    save_json(destination, report)
    print(json.dumps({'report': str(destination), 'status': report['status'], 'elapsed_seconds': report['elapsed_seconds']}, indent=2))
    return int(not passed)

if __name__ == '__main__': raise SystemExit(main())
