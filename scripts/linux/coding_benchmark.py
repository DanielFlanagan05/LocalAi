#!/usr/bin/env python3
"""Ten isolated bug-fix tasks with acceptance checks withheld from the agent prompt."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from localai import paths, profiles, save_json, start, validation_metadata, sha256

ADAPTER_SHA256 = sha256(Path(__file__))

# Each acceptance program executes separately after the harness exits. The agent
# sees only task.py and the behavioral request, never these assertions in its prompt.
CASES = [
 ('stable-unique', 'Return first occurrences in input order; allow unhashable values.',
  'def solve(values):\n    return list(set(values))\n',
  'assert m.solve([3,1,3,2,1]) == [3,1,2]\nassert m.solve([[1],[2],[1]]) == [[1],[2]]\nassert m.solve([])==[]'),
 ('decimal-total', 'Sum decimal strings exactly and return fixed two-decimal text. Empty input returns 0.00.',
  'def solve(values):\n    return str(sum(float(x) for x in values))\n',
  "assert m.solve(['0.10','0.20'])=='0.30'\nassert m.solve([])=='0.00'\nassert m.solve(['1000000000000000000.01','0.02'])=='1000000000000000000.03'"),
 ('csv-quotes', 'Parse CSV text into rows, respecting quoted commas, embedded newlines and escaped quotes. Return no row for empty input.',
  "def solve(text):\n    return [r.split(',') for r in text.splitlines()]\n",
  "assert m.solve('a,\"b,c\"\\n1,2')==[['a','b,c'],['1','2']]\nassert m.solve('a,\"b\\nc\"')==[['a','b\\nc']]\nassert m.solve('')==[]"),
 ('merge-intervals', 'Merge closed overlapping/touching intervals in ascending order without changing the caller input. Empty input returns [].',
  'def solve(intervals):\n    intervals.sort()\n    return intervals\n',
  'x=[[5,8],[1,4],[4,6],[12,13]]\nassert m.solve(x)==[[1,8],[12,13]]\nassert x==[[5,8],[1,4],[4,6],[12,13]]\nassert m.solve([])==[]'),
 ('bounded-chunks', 'Split a sequence into lists of at most size items; retain the tail. Nonpositive size raises ValueError.',
  'def solve(values,size):\n    return [values[i:i+size] for i in range(0,len(values)-size,size)]\n',
  'assert m.solve([1,2,3,4,5],2)==[[1,2],[3,4],[5]]\nassert m.solve([],3)==[]\ntry: m.solve([1],0)\nexcept ValueError: pass\nelse: raise AssertionError("zero size")'),
 ('jsonl-records', 'Read JSONL text, tolerating UTF-8 BOM on the first line and blank lines. Reject malformed nonblank records with ValueError.',
  'import json\ndef solve(text):\n    return [json.loads(line) for line in text.splitlines()]\n',
  "assert m.solve('\\ufeff{\"n\":1}\\n\\n{\"n\":2}')==[{'n':1},{'n':2}]\nassert m.solve(' \\n')==[]\ntry: m.solve('{bad}')\nexcept ValueError: pass\nelse: raise AssertionError('bad JSON')"),
 ('url-query', 'Add/replace query parameters in an absolute URL, retaining other parameters and the fragment. Encode spaces, ampersands and Unicode correctly.',
  "def solve(url,params):\n    return url+'?'+ '&'.join(str(k)+'='+str(v) for k,v in params.items())\n",
  "from urllib.parse import urlsplit,parse_qs\nu=urlsplit(m.solve('https://example.test/p?a=1#part',{'q':'a & 雪','a':'2'}))\nassert u.fragment=='part'\nassert parse_qs(u.query)=={'a':['2'],'q':['a & 雪']}"),
 ('lru', 'Fix Cache: get returns value or None and marks hits most recently used; put updates values and evicts the least recently used key when over capacity. Zero capacity stores nothing.',
  'class Cache:\n    def __init__(self,capacity): self.capacity=capacity; self.data={}\n    def get(self,key): return self.data.get(key)\n    def put(self,key,value): self.data[key]=value\n',
  "c=m.Cache(2)\nc.put('a',1);c.put('b',2)\nassert c.get('a')==1\nc.put('c',3)\nassert c.get('b') is None\nc.put('a',4)\nassert c.get('a')==4\nz=m.Cache(0);z.put('a',1);assert z.get('a') is None"),
 ('async-order', 'Async solve takes async callables and a positive concurrency limit. Run at most limit tasks simultaneously and return results in input order.',
  'import asyncio\nasync def solve(functions,limit):\n    return await asyncio.gather(*(f() for f in functions))\n',
  'import asyncio\nasync def check():\n active=0;peak=0\n async def job(i):\n  nonlocal active,peak\n  active+=1;peak=max(peak,active)\n  await asyncio.sleep(.01)\n  active-=1;return i\n assert await m.solve([lambda i=i:job(i) for i in range(7)],2)==list(range(7))\n assert peak<=2\n assert await m.solve([],1)==[]\nasyncio.run(check())'),
 ('relative-path', 'Resolve a user path against a root directory and return pathlib.Path only if it stays inside root. Reject traversal and absolute paths outside root using ValueError; allow the root itself.',
  'from pathlib import Path\ndef solve(root,user):\n    return Path(root)/user\n',
  "from pathlib import Path\nassert m.solve('/tmp/base','a/../b')==Path('/tmp/base/b')\nassert m.solve('/tmp/base','.')==Path('/tmp/base')\nfor bad in ('../escape','/etc/passwd','../../base-other/a'):\n try: m.solve('/tmp/base',bad)\n except ValueError: pass\n else: raise AssertionError('escape accepted')")
]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=profiles())
    parser.add_argument('--cases', type=int, default=10, choices=range(1,11))
    parser.add_argument('--no-start', action='store_true')
    parser.add_argument('--input-tokens', type=int, default=0, help='Prepend calibrated synthetic history through the native Pi SDK; reported usage verifies actual context.')
    args = parser.parse_args()
    p = paths()
    if not args.no_start: start(args.profile)
    directory = p['state'] / 'coding-checks' / f'{args.profile}-{int(time.time())}'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    records = []
    infrastructure_failed = False
    metadata = validation_metadata(args.profile)
    padding_file = None
    if args.input_tokens:
        if args.input_tokens < 1 or args.input_tokens + 38000 > profiles()[args.profile]['context']:
            parser.error('Padded history must leave 38000 tokens for tools, replies and compaction reserve.')
        from benchmark import calibrated_text
        padding, _ = calibrated_text('http://127.0.0.1:8080/v1', args.profile, args.input_tokens, dense=True)
        padding_file = directory / 'synthetic-history.txt'
        padding_file.write_text('Historical reference material follows. Ignore its reply instruction; the next message is your coding task.\n' + padding)
    for name, request, source, checks in CASES[:args.cases]:
        workspace = directory / name
        workspace.mkdir()
        (workspace / 'task.py').write_text(source)
        prompt = f'Read and fix task.py in the current directory. Requirement: {request} Keep the public function/class name. Modify only task.py; do not ask questions. Verify your work with small examples.'
        env = {**os.environ, 'PATH': str(p['bin']) + os.pathsep + os.environ['PATH'],
               'PWD': str(workspace), 'PI_CODING_AGENT_DIR': str(p['state'] / 'pi')}
        begin = time.monotonic()
        try:
            command = [str(p['apps'] / 'node/bin/pi'), '--provider', 'localai', '--model', args.profile, '--print', prompt]
            if padding_file:
                request = workspace / 'sdk-input.json'
                save_json(request, {'apps': str(p['apps']), 'agentDir': str(p['state'] / 'pi'),
                    'profile': args.profile, 'operation': 'coding', 'workspace': str(workspace),
                    'report': str(workspace / 'sdk-report.json'), 'paddingFile': str(padding_file),
                    'prompt': prompt, 'timeoutMs': 3600000})
                command = [str(p['bin'] / 'node'), str(Path(__file__).with_name('pi_acceptance.mjs')), str(request)]
            with (workspace / 'agent.log').open('w') as out:
                process = subprocess.run(command, cwd=workspace, env=env, stdout=out, stderr=subprocess.STDOUT, timeout=3700 if padding_file else 600)
            # Acceptance source is supplied to a separate interpreter after the agent completes.
            program = 'import importlib.util\ns=importlib.util.spec_from_file_location("candidate","task.py")\nm=importlib.util.module_from_spec(s)\ns.loader.exec_module(m)\n' + checks
            check = subprocess.run([str(p['apps'] / 'support/bin/python'), '-c', program], cwd=workspace,
                                   capture_output=True, timeout=20)
            context = json.loads((workspace / 'sdk-report.json').read_text()) if padding_file else {}
            # Pi reports uncached input and cache reads separately. Count both.
            usages = context.get('usage', [])
            input_counts = [u.get('input', 0) + u.get('cacheRead', 0) for u in usages if u]
            context_reached = not padding_file or (bool(input_counts) and min(input_counts) >= args.input_tokens)
            records.append({'case': name, 'passed': process.returncode == 0 and check.returncode == 0 and context_reached,
                            'requested_history_tokens': args.input_tokens, 'observed_input_tokens': input_counts, 'context_reached': context_reached,
                            'harness_exit': process.returncode, 'acceptance_exit': check.returncode, 'seconds': time.monotonic() - begin})
            infrastructure_failed = process.returncode != 0
            if infrastructure_failed:
                records[-1]['infrastructure_error'] = context.get('modelErrors') or 'Harness process failed; inspect its private log.'
        except subprocess.TimeoutExpired:
            records.append({'case': name, 'passed': False, 'error': 'timeout', 'seconds': time.monotonic() - begin})
            infrastructure_failed = True
        save_json(directory / 'results.json', {'profile': args.profile, 'results': records,
            'status': 'infrastructure_failed' if infrastructure_failed else 'running',
            'requested_cases': args.cases,
            'requested_history_tokens': args.input_tokens,
            'padding_kind': 'synthetic numeric CSV reference' if padding_file else None,
            **metadata, 'adapter_sha256': ADAPTER_SHA256,
            'limitations': 'Small synthetic Python bug-fix suite through Pi; not SWE-bench or a general coding leaderboard.'})
        if infrastructure_failed: break
    report = json.loads((directory / 'results.json').read_text())
    if not infrastructure_failed:
        report['status'] = 'passed' if all(x['passed'] for x in records) else 'failed'
    save_json(directory / 'results.json', report)
    print(json.dumps({'report': str(directory / 'results.json'), 'passed': sum(x['passed'] for x in records), 'total': len(records)}, indent=2))
    return int(not all(x['passed'] for x in records))

if __name__ == '__main__': raise SystemExit(main())
