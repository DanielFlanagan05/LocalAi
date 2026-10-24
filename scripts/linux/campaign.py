#!/usr/bin/env python3
"""Run the reproducible short acceptance campaign for one installed profile."""
import argparse
import json
import subprocess
import time
from pathlib import Path
from localai import ROOT, paths, profiles, running, save_json, start

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=[k for k, v in profiles().items() if v['context'] >= 262144])
    parser.add_argument('--tokens', type=int, nargs='+', default=[8192, 32768, 65536, 131072, 200000, 225280])
    parser.add_argument('--harnesses', nargs='+', choices=['pi', 'opencode', 'hermes', 'claude'], default=['pi', 'opencode', 'hermes'])
    parser.add_argument('--repeats', type=int, default=3, choices=range(1, 21))
    parser.add_argument('--context-only', action='store_true', help='Retry the context/memory ladder without repeating unchanged harness and coding checks.')
    parser.add_argument('--directory', type=Path, help='New private report directory; must be empty.')
    args = parser.parse_args()
    p = paths()
    owner = running()
    if owner and owner['profile'] != args.profile:
        parser.error('Another profile owns the GPU. Finish its work and explicitly stop it first.')
    if any(n < 1 or n + 2304 > profiles()[args.profile]['context'] for n in args.tokens):
        parser.error('Every requested input must fit with output/template headroom.')
    start(args.profile)
    directory = args.directory or p['state'] / 'campaigns' / f'{args.profile}-{int(time.time())}'
    if directory.exists() and any(directory.iterdir()): parser.error('Report directory must be empty')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    jobs = [('harnesses', 'harness_smoke.py', ['--no-start', '--profile', args.profile, '--harness', *args.harnesses]),
            ('coding', 'coding_benchmark.py', [args.profile, '--no-start'])]
    if args.context_only: jobs = []
    for workers in sorted({1, profiles()[args.profile]['sessions']}):
        for count in args.tokens:
            jobs.append((f'context-{count}-workers-{workers}', 'benchmark.py',
                [args.profile, '--no-start', '--input-tokens', str(count), '--workers', str(workers), '--repeats', str(args.repeats)]))
    results = []
    for label, script, options in jobs:
        begin = time.monotonic()
        print('Running ' + label, flush=True)
        with (directory / (label + '.log')).open('w') as stream:
            completed = subprocess.run([str(p['apps'] / 'support/bin/python'),
                str(ROOT / 'scripts/linux' / script), *options], stdout=stream, stderr=subprocess.STDOUT)
        results.append({'check': label, 'exit_code': completed.returncode, 'seconds': time.monotonic() - begin})
        save_json(directory / 'results.json', {'profile': args.profile, 'results': results,
            'context_only': args.context_only,
            'status': 'running' if completed.returncode == 0 else 'failed',
            'limitations': 'Short acceptance checks; excludes media, ClearCase document accuracy, cancellation/recovery, two-hour soak and overnight continuation.'})
        if completed.returncode: break
    report = json.loads((directory / 'results.json').read_text())
    report['status'] = 'passed' if len(results) == len(jobs) and all(r['exit_code'] == 0 for r in results) else 'failed'
    save_json(directory / 'results.json', report)
    print(json.dumps({'report': str(directory / 'results.json'), 'status': report['status']}, indent=2))
    return int(report['status'] != 'passed')

if __name__ == '__main__': raise SystemExit(main())
