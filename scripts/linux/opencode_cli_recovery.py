#!/usr/bin/env python3
"""Test ordinary CLI-created OpenCode session resume, separately from the API probe."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from localai import paths, profiles, running, save_json, start, stop, validation_metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=profiles(), default='coding-concurrent')
    args = parser.parse_args()
    p = paths()
    directory = p['state'] / 'harness-recovery' / f'opencode-cli-{int(time.time())}'
    directory.mkdir(parents=True, mode=0o700)
    report = {'profile': args.profile, 'status': 'running',
              'limitations': 'Two real CLI processes sharing a persisted CLI-created session. Does not repeat the earlier API-created session, stream cancellation or compaction probe.'}
    owner = None
    previous = running(args.profile)
    def cancel(*_): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, cancel)
    def turn(label, prompt, session=None):
        command = [str(p['apps'] / 'opencode/opencode'), 'run', '--format', 'json',
                   '--model', 'localai/' + args.profile]
        if session: command += ['--session', session]
        command += [prompt]
        env = {**os.environ, 'OPENCODE_CONFIG': str(p['config'] / f'opencode-{args.profile}.json'),
               'OPENCODE_DISABLE_AUTOUPDATE': '1'}
        destination = directory / (label + '.jsonl')
        with destination.open('w') as stream:
            child = subprocess.Popen(command, cwd=directory, env=env, stdout=stream,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            try: child.wait(timeout=300)
            except BaseException:
                os.killpg(child.pid, signal.SIGTERM)
                try: child.wait(timeout=15)
                except subprocess.TimeoutExpired: os.killpg(child.pid, signal.SIGKILL); child.wait()
                raise
        rows = []
        for line in destination.read_text().splitlines():
            try: rows.append(json.loads(line))
            except ValueError: pass
        text = ''.join(r.get('part', {}).get('text', '') for r in rows if r.get('type') == 'text').strip()
        sid = next((r['sessionID'] for r in rows if r.get('sessionID')), None)
        return {'exit_code': child.returncode, 'text': text, 'session_id': sid}
    try:
        owner = start(args.profile)
        report.update(validation_metadata(args.profile))
        save_json(directory / 'results.json', report)
        code = 'CEDAR-CLI-RESUME-71923'
        first = turn('initial', f'The public project label for this synthetic session is {code}. Remember it. Reply with only that exact label.')
        report['initial'] = first
        if first['exit_code'] or first['text'] != code or not first['session_id']:
            raise RuntimeError('Initial CLI session did not establish an exact label and saved session ID.')
        resumed = turn('resumed', 'Return only the exact public project label given earlier in this session. No commentary.', first['session_id'])
        report['resumed'] = resumed
        report['checks'] = {'initial_exact': first['text'] == code,
                            'same_session': resumed['session_id'] == first['session_id'],
                            'persistent_resume': resumed['exit_code'] == 0 and resumed['text'] == code}
        report['status'] = 'passed' if all(report['checks'].values()) else 'failed'
    except KeyboardInterrupt: report['status'] = 'cancelled'
    except Exception as error: report.update(status='failed', error=repr(error))
    finally:
        current = running(args.profile)
        if not previous and owner and current and (current['pid'], current['identity']) == (owner['pid'], owner['identity']):
            stop(args.profile)
        save_json(directory / 'results.json', report)
    print(json.dumps({'status': report['status'], 'report': str(directory / 'results.json')}), flush=True)
    return int(report['status'] != 'passed')


if __name__ == '__main__': raise SystemExit(main())
