#!/usr/bin/env python3
"""Exercise real harness read/write tools in isolated synthetic workspaces."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from localai import paths, profiles, save_json, start

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=profiles(), default='coding-concurrent')
    parser.add_argument('--harness', choices=['pi', 'opencode', 'hermes', 'claude'], nargs='+', default=['pi', 'opencode', 'hermes'])
    parser.add_argument('--no-start', action='store_true')
    parser.add_argument('--launchers', action='store_true', help='Exercise the installed global commands rather than invoking binaries directly.')
    args = parser.parse_args()
    p = paths()
    if not args.no_start: start(args.profile)
    base = p['state'] / 'harness-checks' / str(int(time.time()))
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = os.environ.copy()
    env.update(PATH=str(p['bin']) + os.pathsep + env['PATH'],
        LOCALAI_PROFILE=args.profile,
        PI_CODING_AGENT_DIR=str(p['state'] / 'pi'), OPENCODE_CONFIG=str(p['config'] / 'opencode.json'),
        HERMES_HOME=str(p['state'] / 'hermes'), CLAUDE_CONFIG_DIR=str(p['state'] / 'claude'),
        OPENAI_API_KEY='local-only', OPENAI_BASE_URL='http://127.0.0.1:8080/v1')
    # Titles/compression/helper calls must use the same loaded model, too.
    opencode = json.loads((p['config'] / 'opencode.json').read_text())
    opencode['small_model'] = 'localai/' + args.profile
    save_json(base / 'opencode.json', opencode)
    env['OPENCODE_CONFIG'] = str(base / 'opencode.json')
    env.update(ANTHROPIC_BASE_URL='http://127.0.0.1:8080', ANTHROPIC_AUTH_TOKEN='local-only',
               ANTHROPIC_DEFAULT_HAIKU_MODEL=args.profile, ANTHROPIC_DEFAULT_SONNET_MODEL=args.profile,
               ANTHROPIC_DEFAULT_OPUS_MODEL=args.profile, ANTHROPIC_DEFAULT_FABLE_MODEL=args.profile,
               CLAUDE_CODE_SUBAGENT_MODEL=args.profile)
    commands = {
        'pi': [str(p['apps'] / 'node/bin/pi'), '--provider', 'localai', '--model', args.profile, '--print'],
        'opencode': [str(p['apps'] / 'opencode/opencode'), 'run', '--model', 'localai/' + args.profile],
        'hermes': [str(p['apps'] / 'hermes/.venv/bin/hermes'), 'chat', '--provider', 'custom', '--model', args.profile,
                   '--base-url', 'http://127.0.0.1:8080/v1', '--api-key', 'local-only', '-q'],
        'claude': [str(p['apps'] / 'node/bin/claude'), '--model', args.profile, '--permission-mode', 'acceptEdits',
                   '--allowedTools', 'Read,Write,Edit', '--print']}
    if args.launchers:
        commands = {
            'pi': [str(p['bin'] / 'pi-local'), '--print'],
            'opencode': [str(p['bin'] / 'opencode-local'), 'run'],
            'hermes': [str(p['bin'] / 'hermes-local'), '-q'],
            'claude': [str(p['bin'] / 'claude-local'), '--permission-mode', 'acceptEdits',
                       '--allowedTools', 'Read,Write,Edit', '--print']}
    results = []
    for name in args.harness:
        workspace = base / name
        workspace.mkdir()
        expected = f'CEDAR-{name.upper()}-48271'
        (workspace / 'input.txt').write_text(expected + '\n')
        prompt = 'Use your file tools to read input.txt in the current directory, then create result.txt containing exactly its contents. Do not modify any other file. This is a synthetic tool integration test.'
        begin = time.monotonic()
        try:
            with (workspace / 'stdout.log').open('w') as out, (workspace / 'stderr.log').open('w') as err:
                done = subprocess.run([*commands[name], prompt], cwd=workspace,
                                      env={**env, 'PWD': str(workspace)}, stdout=out, stderr=err, timeout=600)
            result = workspace / 'result.txt'
            passed = done.returncode == 0 and result.exists() and result.read_text().strip() == expected
            results.append({'harness': name, 'exit_code': done.returncode, 'passed': passed, 'seconds': time.monotonic() - begin})
        except subprocess.TimeoutExpired:
            results.append({'harness': name, 'passed': False, 'error': 'timeout', 'seconds': time.monotonic() - begin})
        save_json(base / 'results.json', {'profile': args.profile, 'entrypoint': 'global-launchers' if args.launchers else 'binaries', 'results': results,
            'limitations': 'Synthetic file-tool smoke tests only; not coding accuracy, sandbox enforcement, or long-context acceptance.'})
    save_json(base / 'results.json', {'profile': args.profile, 'entrypoint': 'global-launchers' if args.launchers else 'binaries', 'results': results,
        'limitations': 'Synthetic file-tool smoke tests only; not coding accuracy, sandbox enforcement, or long-context acceptance.'})
    print(json.dumps({'report': str(base / 'results.json'), 'results': results}, indent=2))
    return int(not all(r['passed'] for r in results))

if __name__ == '__main__': raise SystemExit(main())
