#!/usr/bin/env python3
"""Check server-side stream cancellation and recovery on an otherwise idle runtime."""
import argparse
import json
import re
import time
import urllib.request
from benchmark import completion
from localai import paths, profiles, running, save_json, start

def active_requests(opener, base):
    with opener.open(base.removesuffix('/v1') + '/metrics', timeout=5) as response:
        metrics = response.read().decode()
    match = re.search(r'^llamacpp:requests_processing\s+(\d+)', metrics, re.MULTILINE)
    if not match: raise RuntimeError('Runtime does not expose the required active-request metric.')
    return int(match[1])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=profiles(), default='coding-concurrent', nargs='?')
    args = parser.parse_args()
    start(args.profile)
    owner = running()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = 'http://127.0.0.1:8080/v1'
    if active_requests(opener, base):
        parser.error('Wait for other requests to finish before running this cancellation test.')
    payload = {'model': args.profile, 'stream': True, 'max_tokens': 4096, 'temperature': 0,
        'chat_template_kwargs': {'enable_thinking': False},
        'messages': [{'role': 'user', 'content': 'Write a long numbered list of the integers from 1 to 1000. Include every integer.'}]}
    request = urllib.request.Request(base + '/chat/completions', json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer local-only'})
    seen = False
    with opener.open(request, timeout=120) as response:
        for line in response:
            if not line.startswith(b'data:'): continue
            raw = line[5:].strip()
            if raw == b'[DONE]': break
            item = json.loads(raw)
            if any(c.get('delta', {}).get('content') for c in item.get('choices', [])):
                seen = True
                break
    cancelled = time.monotonic()
    # Closing the stream should stop inference, rather than just hide its output.
    remaining = active_requests(opener, base)
    while remaining and time.monotonic() - cancelled < 30:
        time.sleep(.25)
        remaining = active_requests(opener, base)
    cancel_wait = time.monotonic() - cancelled
    recovery, seconds = completion(base, args.profile, [{'role': 'user', 'content': 'Return exactly CEDAR-CANCEL-48271 and no other text.'}], 64)
    answer = recovery['choices'][0]['message'].get('content') or ''
    current = running()
    same_process = bool(current and owner and current['pid'] == owner['pid'] and current['identity'] == owner['identity'])
    passed = seen and remaining == 0 and same_process and answer.strip() == 'CEDAR-CANCEL-48271'
    report = {'profile': args.profile, 'status': 'passed' if passed else 'failed', 'first_content_seen': seen,
        'active_requests_after_cancel': remaining, 'cancel_wait_seconds': cancel_wait,
        'same_runtime_process': same_process, 'recovery_seconds': seconds, 'recovery_exact_reply': answer.strip() == 'CEDAR-CANCEL-48271',
        'limitations': 'API stream disconnect and recovery only; does not test harness UI cancellation, transcript restoration or compaction.'}
    destination = paths()['state'] / 'benchmarks' / f'cancel-{args.profile}-{int(time.time())}.json'
    save_json(destination, report)
    print(json.dumps({'status': report['status'], 'report': str(destination)}, indent=2))
    return int(not passed)

if __name__ == '__main__': raise SystemExit(main())
