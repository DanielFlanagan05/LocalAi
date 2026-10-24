#!/usr/bin/env python3
"""Real harness cancellation, compaction and persistent-session recovery probes."""
import argparse
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from localai import ROOT, paths, profiles, save_json, start, running, validation_metadata
from recovery_history import HISTORY

TRACE_PATH = None

def new_stream_event(event, session_id, previous_id):
    properties = event.get('properties', {})
    if properties.get('sessionID') != session_id: return False
    if event.get('type') == 'message.part.delta':
        return bool(properties.get('messageID') and properties['messageID'] != previous_id and properties.get('delta'))
    # A posted USER prompt also emits part.updated with text and a fresh ID.
    # Only generation deltas establish that inference streamed before abort.
    return False

def trace(value):
    if TRACE_PATH:
        with TRACE_PATH.open('a') as stream: stream.write(json.dumps({'time': time.time(), **value}) + '\n')

def api(base, route, body=None):
    begin = time.monotonic()
    trace({'event': 'api_start', 'route': route, 'method': 'GET' if body is None else 'POST'})
    request = urllib.request.Request(base + route, data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=600) as response:
            raw = response.read()
            trace({'event': 'api_finished', 'route': route, 'seconds': time.monotonic()-begin, 'status': response.status})
            return json.loads(raw) if raw else None
    except Exception as error:
        trace({'event': 'api_error', 'route': route, 'seconds': time.monotonic()-begin, 'error': repr(error)})
        raise

def opencode(p, directory, profile):
    global TRACE_PATH
    TRACE_PATH = directory / 'api-trace.jsonl'
    # A unique loopback server; no other OpenCode process is signalled.
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    env = {**os.environ, 'OPENCODE_CONFIG': str(p['config'] / f'opencode-{profile}.json')}
    stream = (directory / 'server.log').open('w')
    process = subprocess.Popen([str(p['apps'] / 'opencode/opencode'), 'serve', '--hostname', '127.0.0.1', '--port', str(port)],
        cwd=directory, env=env, stdout=stream, stderr=subprocess.STDOUT)
    base = f'http://127.0.0.1:{port}'
    query = '?directory=' + urllib.parse.quote(str(directory), safe='')
    checks = {}
    try:
        deadline = time.monotonic() + 60
        while True:
            try: api(base, '/global/health'); break
            except OSError:
                if process.poll() is not None or time.monotonic() > deadline: raise
                time.sleep(.25)
        session = api(base, '/session' + query, {'title': 'Local synthetic lifecycle acceptance'})
        sid = session['id']; route = '/session/' + sid
        def message(text, **extra):
            return {'model': {'providerID': 'localai', 'modelID': profile}, 'parts': [{'type': 'text', 'text': text}], **extra}
        def text(result): return ''.join(v.get('text', '') for v in result.get('parts', []) if v.get('type') == 'text').strip()
        api(base, route + '/message' + query, message('We are developing a synthetic Python CSV parser. Its public project label is CEDAR-OPENCODE-71923. Keep this public label in any session handoff. Confirm the identifier in your reply.'))
        previous = api(base, route + '/message' + query)
        previous_id = previous[-1]['info']['id'] if previous else None
        stream_seen = threading.Event()
        subscriber_ready = threading.Event()
        def subscribe():
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(base + '/event' + query, timeout=150) as response:
                    subscriber_ready.set()
                    for raw in response:
                        if not raw.startswith(b'data:'): continue
                        event = json.loads(raw[5:].strip())
                        if new_stream_event(event, sid, previous_id):
                            save_json(directory / 'stream-observed.json', event)
                            stream_seen.set(); return
            except (OSError, ValueError): pass
        subscriber = threading.Thread(target=subscribe, daemon=True)
        subscriber.start()
        if not subscriber_ready.wait(10): raise RuntimeError('Native OpenCode event subscriber did not connect')
        api(base, route + '/prompt_async' + query, message('Explain in detail how to implement a robust Python CSV parser, including quoted newlines, escaped quotes, streaming, validation and test cases. Include Python examples.'))
        # Database snapshots may buffer partial text; subscribe to the same live
        # delta events that the native UI uses instead of polling saved messages.
        streamed = stream_seen.wait(120)
        api(base, route + '/abort' + query, {})
        checks['stream_seen_before_abort'] = streamed
        answer = api(base, route + '/message' + query, message('Cancel the previous explanation. For a project status reply, return only the public project label verbatim, without markdown or commentary.'))
        checks['recovery'] = text(answer) == 'CEDAR-OPENCODE-71923'
        for prompt in HISTORY:
            api(base, route + '/message' + query, message(prompt))
        api(base, route + '/summarize' + query, {'providerID': 'localai', 'modelID': profile, 'auto': False})
        messages = api(base, route + '/message' + query)
        save_json(directory / 'native-messages.json', messages)
        checks['compaction_record'] = any(part.get('type') == 'compaction' for m in messages for part in m.get('parts', []))
        # Restart the harness server, then retrieve and continue the same persisted session.
        process.terminate(); process.wait(15)
        # Use OpenCode's ordinary saved-session CLI path for a process restart.
        # The legacy HTTP resume endpoint can hang after a server restart.
        with (directory / 'resume.log').open('w') as out:
            resumed = subprocess.run([str(p['apps'] / 'opencode/opencode'), 'run', '--session', sid,
                '--model', 'localai/' + profile,
                'Return exactly the public project label saved in the handoff and nothing else.'],
                cwd=directory, env=env, stdout=out, stderr=subprocess.STDOUT, timeout=300)
        output = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', (directory / 'resume.log').read_text())
        checks['persistent_resume'] = resumed.returncode == 0 and any(line.strip() == 'CEDAR-OPENCODE-71923' for line in output.splitlines())
        return {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks, 'session_id': sid,
            'limitations': 'Native server API abort, manual short-history compaction and restart/resume; not terminal key handling or natural 225K auto-compaction.'}
    finally:
        save_json(directory / 'checks.json', checks)
        if process.poll() is None:
            process.terminate()
            try: process.wait(15)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        stream.close()

def claude(p, directory, profile):
    settings = p['state'] / ('claude' if profile == 'messages-compatible' else f'claude-profiles/{profile}')
    env = {**os.environ, 'CLAUDE_CONFIG_DIR': str(settings), 'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8080',
        'ANTHROPIC_AUTH_TOKEN': 'local-only', 'ANTHROPIC_MODEL': profile, 'DISABLE_TELEMETRY': '1',
        'CLAUDE_CODE_MAX_CONTEXT_TOKENS': str(profiles()[profile]['context']),
        'CLAUDE_CODE_AUTO_COMPACT_WINDOW': str(profiles()[profile]['context']-36864)}
    for key in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN'): env.pop(key, None)
    command = [str(p['apps'] / 'node/bin/claude'), '--print', '--verbose', '--output-format', 'stream-json', '--include-partial-messages', '--model', profile,
        '--permission-mode', 'acceptEdits', '--allowedTools', 'Read,Write,Edit', '--tools', 'Read,Write,Edit']
    sid = str(uuid.uuid4())
    def turn(label, prompt, resume=True):
        with (directory / (label + '.jsonl')).open('w') as out:
            result = subprocess.run(command + (['--resume', sid] if resume else ['--session-id', sid]) + [prompt],
                cwd=directory, env=env, stdout=out, stderr=subprocess.STDOUT, timeout=600)
        rows = []
        for line in (directory / (label + '.jsonl')).read_text().splitlines():
            try: rows.append(json.loads(line))
            except ValueError: pass
        return result.returncode, rows
    initial_code, initial = turn('initial', 'We are developing a synthetic Python CSV parser. Its public project label is CEDAR-CLAUDE-71923. Keep this public label in any session handoff. Confirm the identifier in your reply.', False)
    if initial_code or not any(r.get('type') == 'result' and not r.get('is_error') for r in initial):
        raise RuntimeError('Claude initial session failed; inspect initial.jsonl before testing recovery.')
    windows = [r.get('modelUsage', {}).get(profile, {}).get('contextWindow') for r in initial if r.get('type') == 'result']
    reported_window = max((v for v in windows if isinstance(v, int)), default=0)
    out = (directory / 'interrupted.jsonl').open('w')
    process = subprocess.Popen(command + ['--resume', sid, 'Explain in detail how to implement a robust Python CSV parser, including quoted newlines, escaped quotes, streaming, validation and test cases. Include Python examples.'],
        cwd=directory, env=env, stdout=out, stderr=subprocess.STDOUT)
    observed = False
    try:
        deadline = time.monotonic() + 180
        while process.poll() is None and time.monotonic() < deadline:
            data = (directory / 'interrupted.jsonl').read_text()
            if 'content_block_delta' in data:
                observed = True; break
            time.sleep(.1)
        process.send_signal(signal.SIGINT)
        try: process.wait(30)
        except subprocess.TimeoutExpired: process.terminate(); process.wait(15)
    finally:
        if process.poll() is None: process.kill(); process.wait()
        out.close()
    code, recovered = turn('recovery', 'Cancel the previous explanation. For a project status reply, return only the public project label verbatim, without markdown or commentary.')
    def exact(rows): return any(r.get('type') == 'result' and r.get('result', '').strip() == 'CEDAR-CLAUDE-71923' and not r.get('is_error') for r in rows)
    for i, prompt in enumerate(HISTORY): turn(f'history-{i}', prompt)
    compact_exit, compact = turn('compact', '/compact Preserve the public project label CEDAR-CLAUDE-71923.')
    code2, resumed = turn('resumed', 'Return exactly the public project label saved in the handoff and nothing else.')
    transcripts = [path for path in settings.glob(f'projects/**/{sid}.jsonl') if path.is_file()]
    boundary = any('compact_boundary' in path.read_text() for path in transcripts)
    checks = {'client_context_window': reported_window >= profiles()[profile]['context'],
        'stream_seen_before_sigint': observed, 'recovery': code == 0 and exact(recovered),
        'compaction_record': compact_exit == 0 and boundary, 'persistent_resume': code2 == 0 and exact(resumed)}
    return {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks, 'session_id': sid,
        'reported_client_context_window': reported_window,
        'limitations': 'Print-mode SIGINT, manual short-history compaction and saved-session resume; not interactive key handling or natural 225K auto-compaction.'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=profiles(), default='coding-concurrent')
    parser.add_argument('--harness', choices=['pi', 'opencode', 'hermes', 'claude'], nargs='+', default=['pi', 'opencode', 'hermes'])
    parser.add_argument('--reuse-passes', type=Path, action='append', default=[], help='Retain passing harness checks from earlier reports; repeat for multiple reports.')
    args = parser.parse_args()
    start(args.profile); p = paths()
    directory = p['state'] / 'harness-recovery' / str(int(time.time()))
    directory.mkdir(parents=True, mode=0o700)
    report = {'profile': args.profile, **validation_metadata(args.profile), 'results': []}
    reused = set()
    for source in args.reuse_passes:
        previous = json.loads(source.read_text())
        if previous.get('profile') != args.profile: parser.error('Earlier report uses a different profile')
        for result in previous.get('results', []):
            if result['harness'] in args.harness and result['harness'] not in reused and result.get('status') == 'passed':
                report['results'].append({**result, 'reused_from': str(source)})
                reused.add(result['harness'])
    for name in args.harness:
        if name in reused: continue
        workspace = directory / name; workspace.mkdir()
        begin = time.monotonic()
        owner = running()
        try:
            if name in ('pi', 'hermes'):
                destination = workspace / 'native-report.json'
                request = workspace / 'request.json'
                save_json(request, {'apps': str(p['apps']), 'agentDir': str(p['state'] / 'pi'),
                    'hermes': str(p['apps'] / 'hermes'), 'profile': args.profile, 'operation': 'recovery',
                    'workspace': str(workspace), 'report': str(destination)})
                executable = p['bin'] / 'node' if name == 'pi' else p['apps'] / 'hermes/.venv/bin/python'
                script = ROOT / 'scripts/linux' / ('pi_acceptance.mjs' if name == 'pi' else 'hermes_recovery.py')
                env = {**os.environ, 'HERMES_HOME': str(p['state'] / 'hermes'), 'OPENAI_API_KEY': 'local-only', 'OPENAI_BASE_URL': 'http://127.0.0.1:8080/v1'}
                with (workspace / 'native.log').open('w') as stream:
                    done = subprocess.run([str(executable), str(script), str(request)], cwd=workspace, env=env,
                        stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
                result = json.loads(destination.read_text()) if destination.exists() else {'status': 'failed', 'exit_code': done.returncode}
            else: result = (opencode if name == 'opencode' else claude)(p, workspace, args.profile)
        except Exception as error: result = {'status': 'failed', 'error': repr(error)}
        current = running()
        result['same_model_runtime'] = bool(owner and current and (owner['pid'], owner['identity']) == (current['pid'], current['identity']))
        if not result['same_model_runtime']: result['status'] = 'failed'
        report['results'].append({'harness': name, 'seconds': time.monotonic() - begin, **result})
        report['status'] = 'running'
        save_json(directory / 'results.json', report)
    report['status'] = 'passed' if all(r['status'] == 'passed' for r in report['results']) else 'failed'
    save_json(directory / 'results.json', report)
    print(json.dumps({'status': report['status'], 'report': str(directory / 'results.json')}))
    return int(report['status'] != 'passed')

if __name__ == '__main__': raise SystemExit(main())
