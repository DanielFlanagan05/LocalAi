#!/usr/bin/env python3
"""Verify a large Gufo disk checkpoint survives a real engine restart."""
import argparse
import json
import time
from benchmark import calibrated_text, completion
from localai import paths, profiles, save_json, start, stop, running, validation_metadata
from telemetry import Monitor

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=[k for k,v in profiles().items() if v['engine']=='gufo'])
    parser.add_argument('--input-tokens', type=int, default=200000)
    args = parser.parse_args()
    start(args.profile)
    destination = paths()['state'] / 'benchmarks' / f'cache-restart-{args.profile}-{int(time.time())}.json'
    report = {'profile': args.profile, **validation_metadata(args.profile), 'status': 'running'}
    save_json(destination, report)
    with Monitor() as monitor:
        try:
            text, expected = calibrated_text('http://127.0.0.1:8080/v1', args.profile, args.input_tokens, 42)
            messages = [{'role':'user','content':text}]
            first, seconds = completion('http://127.0.0.1:8080/v1', args.profile, messages, 128)
            msg = first['choices'][0]['message']
            report.update(initial_usage=first['usage'],initial_seconds=seconds)
            if msg.get('content','').strip() != expected: raise RuntimeError('Initial exact recall failed')
            messages += [msg, {'role':'user','content':'Repeat that exact project code. No other text.'}]
            warm, seconds = completion('http://127.0.0.1:8080/v1', args.profile, messages, 128)
            report.update(warm_usage=warm['usage'],warm_seconds=seconds)
            # Let asynchronous checkpoint writes settle. No snapshot contents enter Git.
            cache = paths()['cache'] / args.profile
            previous = None; stable = 0; deadline = time.monotonic()+180
            while stable < 3 and time.monotonic()<deadline:
                # Older runtimes use top-level .kvc files; Gufo 0.20 stores
                # component snapshots and manifests in v2/**/*.bin.
                snapshot = []
                for f in cache.rglob('*'):
                    if f.suffix not in ('.kvc', '.bin'): continue
                    try: info = f.stat()
                    except FileNotFoundError: continue  # Asynchronous LRU eviction.
                    snapshot.append((str(f.relative_to(cache)),info.st_size,info.st_mtime_ns))
                snapshot.sort()
                stable = stable+1 if snapshot and snapshot==previous else 0
                previous = snapshot; time.sleep(2)
            report['disk_checkpoints'] = [{'file':n,'bytes':s} for n,s,_ in (previous or [])]
            report['disk_cache_settled_before_restart'] = stable >= 3
            old = running(args.profile); stop(args.profile); start(args.profile); new = running(args.profile)
            restored, seconds = completion('http://127.0.0.1:8080/v1',args.profile,messages,128)
            report.update(restored_usage=restored['usage'],restored_seconds=seconds,
                restored_timings=restored.get('timings'),runtime_restarted=old['identity']!=new['identity'])
            usage = restored['usage']
            cached = usage.get('prompt_tokens_details',{}).get('cached_tokens',0)
            report['checks']={'actual_input_reached':first['usage'].get('prompt_tokens',0)>=args.input_tokens,
                'initial_exact_recall':msg.get('content','').strip()==expected,
                'warm_exact_recall':warm['choices'][0]['message'].get('content','').strip()==expected,
                'restored_exact_recall':restored['choices'][0]['message'].get('content','').strip()==expected,
                'runtime_restarted':report['runtime_restarted'],'large_disk_cache_reused':cached>=args.input_tokens}
            report['status']='passed' if all(report['checks'].values()) else 'failed'
        except Exception as error: report.update(status='failed',error=repr(error))
    report['telemetry']=monitor.report()
    runtime_samples = [s['runtime_process'] for s in monitor.samples if 'runtime_process' in s]
    report['maximum_runtime_swap_bytes'] = max((s.get('VmSwap',0) for s in runtime_samples), default=0)
    swap_passed = bool(runtime_samples) and report['maximum_runtime_swap_bytes'] <= 64*2**20
    report.setdefault('checks', {})['runtime_swap_within_tolerance'] = swap_passed
    if not swap_passed:
        report.update(status='failed', swap_acceptance='Runtime swap exceeded 64 MiB or runtime telemetry was unavailable.')
    report['limitations']='One large conversation, graceful engine restart and cached-token accounting; not abrupt power-loss durability.'
    save_json(destination,report)
    print(json.dumps({'status':report['status'],'report':str(destination)}))
    return int(report['status']!='passed')

if __name__=='__main__': raise SystemExit(main())
