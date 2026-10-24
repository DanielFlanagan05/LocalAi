#!/usr/bin/env python3
"""Run installed-model recovery follow-ups serially with isolated runtime cleanup."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from localai import ROOT, paths, running_all, save_json, start, stop
from telemetry import sample
from render_acceptance import main as render_report

JOBS = [
    ('Primary 200K disk restart', 'coding-concurrent', 'cache_restart.py', ['--input-tokens', '200000'], 5400),
    ('Primary Pi and Hermes lifecycle', 'coding-concurrent', 'harness_recovery.py', ['--harness', 'pi', 'hermes'], 5400),
    ('OpenCode CLI session persistence', 'coding-concurrent', 'opencode_cli_recovery.py', [], 1200),
    ('Claude corrected context and lifecycle', 'messages-compatible', 'harness_recovery.py', ['--harness', 'claude'], 5400),
    ('Flash-Next 200K disk restart', 'gufo-flash', 'cache_restart.py', ['--input-tokens', '200000'], 3600),
    ('Hauhau 200K context and disk restart', 'gufo-hauhau', 'cache_restart.py', ['--input-tokens', '200000'], 5400),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--after-concurrent', type=Path,
                        help='Wait for this existing concurrent ledger to pass before starting any runtime.')
    parser.add_argument('--concurrent-profile', default='coding-concurrent',
                        help='Accepted profile to use for the ordinary OpenCode CLI check.')
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    destination = args.directory / 'followup-results.json'
    if destination.exists(): parser.error('Preserve prior evidence; select a new directory.')
    ledger = {'status': 'running', 'results': [], 'coordinator_pid': os.getpid()}
    def cancel(*_): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, cancel)
    save_json(destination, ledger)
    try:
        if args.after_concurrent:
            deadline = time.monotonic() + 6 * 3600
            ledger.update(status='waiting', prerequisite=str(args.after_concurrent))
            save_json(destination, ledger)
            while True:
                prerequisite = json.loads(args.after_concurrent.read_text())
                if prerequisite['status'] == 'passed': break
                if prerequisite['status'] != 'running':
                    raise RuntimeError('Concurrent prerequisite did not pass; recovery was not started.')
                if time.monotonic() > deadline: raise TimeoutError('Concurrent prerequisite exceeded six hours.')
                time.sleep(5)
            ledger['status'] = 'running'
            save_json(destination, ledger)
        if args.concurrent_profile != 'coding-concurrent':
            # Register the accepted candidate without changing either harness's
            # current default; native lifecycle tests need its real model ID.
            done = subprocess.run([str(paths()['apps'] / 'support/bin/python'),
                str(ROOT / 'scripts/linux/register_profile.py'), args.concurrent_profile,
                '--suffix', 'gufo020'], capture_output=True, text=True, timeout=30, check=True)
            ledger['candidate_registration'] = done.stdout.strip()
            save_json(destination, ledger)
        for index, (label, profile, script, extra, timeout) in enumerate(JOBS):
            if profile == 'coding-concurrent': profile = args.concurrent_profile
            if running_all(): raise RuntimeError('Another runtime is active; isolated recovery must wait.')
            if not sample()['ac_online']: raise RuntimeError('AC power is required.')
            began = time.monotonic()
            started = time.time()
            child = owner = None
            owned_identities = set()
            def owns(current):
                identity = (current['pid'], current['identity'])
                if identity in owned_identities: return True
                if current['profile'] != profile: return False
                # A restart probe launches its own detached runtime supervisor.
                # Prove its parentage while the probe is alive, then retain the
                # exact process identity for cleanup after the probe exits.
                try:
                    stat = Path(f"/proc/{current['supervisor_pid']}/stat").read_text()
                    parent = int(stat[stat.rfind(')') + 2:].split()[1])
                except (OSError, ValueError, KeyError): return False
                parents = {os.getpid()}
                if child and child.poll() is None: parents.add(child.pid)
                if parent not in parents: return False
                owned_identities.add(identity)
                return True
            log = args.directory / f'followup-{index}.log'
            row = {'label': label, 'profile': profile, 'status': 'running', 'log': str(log)}
            ledger['results'].append(row)
            save_json(destination, ledger)
            try:
                owner = start(profile)
                owned_identities.add((owner['pid'], owner['identity']))
                arguments = ['--profile', profile] if script != 'cache_restart.py' else [profile]
                command = [str(paths()['apps'] / 'support/bin/python'),
                           str(ROOT / 'scripts/linux' / script), *arguments, *extra]
                with log.open('w') as stream:
                    child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                             start_new_session=True)
                    while child.poll() is None:
                        if not sample()['ac_online']: raise RuntimeError('AC power disconnected.')
                        active = running_all()
                        if any(not owns(s) for s in active):
                            raise RuntimeError('Another runtime appeared; cancelling isolated recovery.')
                        if time.monotonic() - began > timeout: raise TimeoutError('Recovery step deadline exceeded.')
                        row['elapsed_seconds'] = time.monotonic() - began
                        save_json(destination, ledger)
                        time.sleep(5)
                # Startup can print diagnostics; the final JSON object identifies evidence.
                result = next((json.loads(line) for line in reversed(log.read_text().splitlines())
                               if line.startswith('{') and '"report"' in line), None)
                if not result: raise RuntimeError('No final report; inspect private log.')
                row.update(result, exit_code=child.returncode)
                if child.returncode: row['status'] = 'failed'
            except KeyboardInterrupt:
                row['status'] = 'cancelled'
                raise
            except Exception as error:
                row.update(status='failed', error=repr(error))
            finally:
                if child and child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try: child.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                # Stop only identities whose ownership was established above.
                for current in running_all():
                    if owns(current):
                        stop(profile)
                row['elapsed_seconds'] = time.monotonic() - began
                save_json(destination, ledger)
                render_report()
        ledger['status'] = 'passed' if all(r['status'] == 'passed' for r in ledger['results']) else 'failed'
    except KeyboardInterrupt: ledger['status'] = 'cancelled'
    except Exception as error: ledger.update(status='failed', error=repr(error))
    finally:
        save_json(destination, ledger)
        render_report()
    print(json.dumps({'status': ledger['status'], 'report': str(destination)}), flush=True)
    return int(ledger['status'] != 'passed')


if __name__ == '__main__': raise SystemExit(main())
