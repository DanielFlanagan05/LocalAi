#!/usr/bin/env python3
"""Resume only the installed primary model's unfinished concurrent context steps."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from localai import ROOT, paths, profiles, running, running_all, save_json, start, stop, validation_metadata
from telemetry import sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--profile', choices=[k for k,v in profiles().items()
                                            if v['engine']=='gufo' and v.get('sessions',1)>=2],
                        default='coding-concurrent')
    parser.add_argument('--tokens', nargs='+', type=int, default=[65536, 131072, 200000, 225280])
    args = parser.parse_args()
    if any(n < 1 or n + 3072 > profiles()[args.profile]['context'] for n in args.tokens): parser.error('Context step does not fit.')
    args.directory.mkdir(parents=True, exist_ok=True)
    destination = args.directory / 'concurrent-results.json'
    if destination.exists(): parser.error('Choose a new ledger; preserve completed evidence.')
    report = {'status': 'running', 'profile': args.profile, 'workers': 2,
              'started': time.time(), 'steps': [], 'requested_input_tokens': args.tokens,
              'coordinator_pid': os.getpid(),
              'limitations': 'Exact recall/isolation plus warm continuation, not coding quality. Caches are not purged: inspect actual cached-token counts. Earlier single-session evidence is retained separately.'}
    owner = child = None
    def cancel(*_): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, cancel)
    save_json(destination, report)
    try:
        if running_all(): raise RuntimeError('Another local runtime is active.')
        if not sample()['ac_online']: raise RuntimeError('AC power is required.')
        owner = start(args.profile)
        report.update(validation_metadata(args.profile))
        for tokens in args.tokens:
            log = args.directory / f'concurrent-{tokens}.log'
            report['current'] = {'input_tokens': tokens, 'started': time.time(), 'log': str(log)}
            save_json(destination, report)
            command = [str(paths()['apps'] / 'support/bin/python'), str(ROOT / 'scripts/linux/benchmark.py'),
                       args.profile, '--no-start', '--input-tokens', str(tokens),
                       '--workers', '2', '--repeats', '1']
            begin = time.monotonic()
            with log.open('w') as output:
                child = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                report['current']['child_pid'] = child.pid
                while child.poll() is None:
                    observed = sample()
                    if not observed['ac_online']: raise RuntimeError('AC power disconnected.')
                    active = running_all()
                    if len(active) != 1 or (active[0]['pid'], active[0]['identity']) != (owner['pid'], owner['identity']):
                        raise RuntimeError('The isolated runtime changed; stop without touching another owner.')
                    if time.monotonic() - begin > 7200: raise RuntimeError('Two-hour context-step timeout.')
                    report['current'].update(elapsed_seconds=time.monotonic()-begin,
                                             available_bytes=observed['unified_available_bytes'])
                    save_json(destination, report)
                    time.sleep(5)
            row = {'input_tokens': tokens, 'seconds': time.monotonic()-begin, 'exit_code': child.returncode}
            try: row.update(json.loads(log.read_text()))
            except ValueError: row.update(status='failed', error='No final benchmark report; inspect the log.')
            if child.returncode: row['status'] = 'failed'
            if row.get('report'):
                raw = json.loads(Path(row['report']).read_text())
                row['recall_status'] = row['status']
                row['maximum_runtime_swap_bytes'] = max((s.get('runtime_process',{}).get('VmSwap',0)
                    for s in raw.get('telemetry',{}).get('samples',[])), default=0)
                runs = [r for worker in raw.get('results',[]) for r in worker.get('runs',[])]
                row['warm_cache_reused'] = bool(runs) and all(
                    r['warm_usage'].get('cached_tokens',r['warm_usage'].get('prompt_tokens_details',{}).get('cached_tokens',0))
                    >= r['actual_input_tokens'] for r in runs)
                if row['maximum_runtime_swap_bytes'] > 64*2**20 or not row['warm_cache_reused']:
                    row.update(status='failed', acceptance_error='Runtime swap exceeded 64 MiB or warm history was not fully reused.')
            report['steps'].append(row)
            save_json(destination, report)
            if row['status'] != 'passed': raise RuntimeError(f'Concurrent {tokens} step failed.')
        report.update(status='passed', current=None)
    except KeyboardInterrupt: report['status'] = 'cancelled'
    except Exception as error: report.update(status='failed', error=repr(error))
    finally:
        if child and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try: child.wait(timeout=15)
            except subprocess.TimeoutExpired: os.killpg(child.pid, signal.SIGKILL); child.wait()
        current = running(args.profile)
        startup_interrupted = not owner and current and current['started'] >= report['started']
        if startup_interrupted or owner and current and (owner['pid'], owner['identity']) == (current['pid'], current['identity']):
            stop(args.profile)
        report['finished'] = time.time()
        save_json(destination, report)
    print(json.dumps({'status': report['status'], 'report': str(destination)}), flush=True)
    return int(report['status'] != 'passed')


if __name__ == '__main__': raise SystemExit(main())
