import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import time
import unittest
from unittest.mock import patch

import localai
from clearcase_benchmark import schema, score
import benchmark
import install
from harness_recovery import new_stream_event

class LocalAiTests(unittest.TestCase):
    def test_comfy_node_cache_preserves_memory_headroom(self):
        profile = dict(localai.profiles()['comfyui'], node_cache_headroom_gib=16)
        command = localai.engine_command('comfyui', profile)
        self.assertEqual(command[command.index('--cache-ram')+1], '16')
        self.assertNotIn('--cache-none', command)
        self.assertEqual(command[command.index('--reserve-vram')+1], str(profile['minimum_free_gib']))

    def test_stop_comfy_stops_cached_server_but_leaves_coding_server(self):
        from comfy_session import main
        for profile, expected in [('comfyui-cached', True), ('coding-quality', False)]:
            with self.subTest(profile=profile), patch('sys.argv', ['stop-comfyui','--stop']), \
                 patch('comfy_session.running', return_value={'profile':profile}), \
                 patch('comfy_session.stop') as stop, patch('builtins.print'):
                main()
                self.assertEqual(stop.called, expected)

    def test_comfy_and_inference_have_independent_state_and_stop(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('localai.paths', return_value={'state': Path(directory)}):
            inference = {'profile': 'gufo-hauhau', 'pid': 101, 'identity': 'llm', 'port': 8080}
            comfy = {'profile': 'comfyui', 'pid': 202, 'identity': 'comfy', 'port': 8188}
            localai.save_json(localai.state_path('gufo-hauhau'), inference)
            localai.save_json(localai.state_path('comfyui'), comfy)
            live = {101: 'llm', 202: 'comfy'}
            with patch('localai.process_identity', side_effect=lambda pid: live.get(pid)), \
                 patch('localai.os.kill', side_effect=lambda pid, sig: live.pop(pid)) as kill:
                self.assertEqual(localai.running(), inference)
                self.assertEqual(localai.running('comfyui'), comfy)
                self.assertEqual(localai.running('comfyui-cached'), comfy)
                self.assertEqual(len(localai.running_all()), 2)
                localai.stop('comfyui-cached')  # Exact profile required for termination.
                kill.assert_not_called()
                localai.stop('comfyui')
                kill.assert_called_once_with(202, localai.signal.SIGTERM)
                self.assertEqual(localai.running(), inference)
                self.assertIsNone(localai.running('comfyui'))
                localai.stop()
                self.assertEqual(kill.call_count, 2)
                self.assertEqual(localai.running_all(), [])

    def test_concurrent_start_warns_but_still_checks_slots_and_ports(self):
        inference = {'profile': 'gufo-hauhau', 'port': 8080}
        comfy = {'profile': 'comfyui', 'port': 8188}
        with patch('localai.running_all', return_value=[inference]), \
             patch('builtins.print') as warning:
            localai.check_start('comfyui', warn=True)
            self.assertIn('share GPU compute and unified memory', warning.call_args.args[0])
            with self.assertRaisesRegex(RuntimeError, 'runtime slot'):
                localai.check_start('coding-quality')
        with patch('localai.running_all', return_value=[comfy]):
            localai.check_start('gufo-hauhau')
            with self.assertRaisesRegex(RuntimeError, 'runtime slot'):
                localai.check_start('comfyui-cached')
        with patch('localai.running_all', return_value=[dict(inference, port=8188)]):
            with self.assertRaisesRegex(RuntimeError, 'port 8188'):
                localai.check_start('comfyui')

    def test_comfy_start_waits_for_its_own_health_and_process(self):
        from unittest.mock import Mock
        inference = {'profile': 'gufo-hauhau', 'port': 8080}
        comfy = {'profile': 'comfyui', 'port': 8188, 'pid': 202, 'identity': 'comfy'}
        with tempfile.TemporaryDirectory() as directory, \
             patch('localai.paths', return_value={'state': Path(directory)}), \
             patch('localai.running_all', return_value=[inference]), \
             patch('localai.running', side_effect=[None, comfy]) as lookup, \
             patch('localai.subprocess.Popen', return_value=Mock(poll=lambda: None)), \
             patch('localai.http') as health, patch('builtins.print'):
            self.assertEqual(localai.start('comfyui'), comfy)
            health.assert_called_once_with('http://127.0.0.1:8188/system_stats', timeout=2)
            self.assertTrue(all(call.args == ('comfyui',) for call in lookup.call_args_list))

    def test_concurrent_comfy_start_still_requires_memory_headroom(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('localai.paths', return_value={'state': Path(directory)}), \
             patch('localai.memory', return_value={'unified_available_bytes': 67 * localai.GIB}), \
             patch('localai.subprocess.Popen') as spawn:
            localai.save_json(Path(directory) / 'server.json', {
                'profile': 'gufo-hauhau', 'pid': os.getpid(),
                'identity': localai.process_identity(os.getpid()), 'port': 8080})
            with self.assertRaisesRegex(RuntimeError, 'insufficient unified-memory headroom'):
                localai.serve('comfyui')
            spawn.assert_not_called()

    def test_supervisors_coexist_and_cleanup_only_their_own_runtime(self):
        # Real child processes and state files, with no GPU/model allocation.
        runner = """
import sys
from pathlib import Path
import localai
root = Path(sys.argv[1])
localai.paths = lambda: {'state': root, 'data': root, 'apps': root}
localai.memory = lambda: {'system_total_bytes': 128 * localai.GIB,
                         'unified_available_bytes': 120 * localai.GIB,
                         'system_available_bytes': 120 * localai.GIB}
localai.engine_command = lambda *_: [sys.executable, '-c', 'import time; time.sleep(60)']
sys.exit(localai.serve(sys.argv[2]))
"""
        for first, second in [('gufo-hauhau', 'comfyui'), ('comfyui', 'gufo-hauhau')]:
            with self.subTest(first=first), tempfile.TemporaryDirectory() as directory, \
                 patch('localai.paths', return_value={'state': Path(directory)}):
                children = []
                def launch(name):
                    child = subprocess.Popen([sys.executable, '-c', runner, directory, name],
                        cwd=localai.ROOT / 'scripts/linux', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    children.append(child)
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if child.poll() is not None: self.fail(f'{name} supervisor exited: {child.returncode}')
                        if localai.running(name): return
                        time.sleep(.02)
                    self.fail(f'{name} did not publish state')
                try:
                    launch(first)
                    if first == 'comfyui':
                        # Exercise an existing ComfyUI record from the old controller.
                        localai.state_path(first).replace(Path(directory) / 'server.json')
                    launch(second)
                    self.assertEqual(len(localai.running_all()), 2)
                    localai.stop('comfyui')
                    self.assertIsNone(localai.running('comfyui'))
                    self.assertEqual(localai.running()['profile'], 'gufo-hauhau')
                    localai.stop('gufo-hauhau')
                    for child in children: self.assertEqual(child.wait(timeout=5), (-localai.signal.SIGTERM) % 256)
                    self.assertEqual(localai.running_all(), [])
                finally:
                    for name in ('comfyui', 'gufo-hauhau'):
                        localai.stop(name)
                    for child in children:
                        if child.poll() is None: child.terminate()
                        child.wait(timeout=5)

    def test_native_cancel_probe_requires_the_new_sessions_actual_delta(self):
        event = {'type':'message.part.updated','properties':{'sessionID':'s1','part':{'type':'text','text':'old reply'}}}
        self.assertFalse(new_stream_event(event,'s1','m1'))
        event['properties']['part']['messageID']='m1'
        self.assertFalse(new_stream_event(event,'s1','m1'))
        event['properties']['part']['messageID']='m2'
        self.assertFalse(new_stream_event(event,'s1','m1'), 'posted user text is not generated output')
        self.assertFalse(new_stream_event(event,'s2','m1'))
        event={'type':'message.part.delta','properties':{'sessionID':'s1','messageID':'m2','delta':'hello'}}
        self.assertTrue(new_stream_event(event,'s1','m1'))
        event['properties']['delta']=''
        self.assertFalse(new_stream_event(event,'s1','m1'))

    def test_kyojin_dense_calibration_uses_actual_token_counts_without_inference(self):
        counts = iter([2050, 20050])
        def tokenizer(url, body):
            self.assertTrue(url.endswith('/tokenize'))
            if 'content' in body: raise OSError('Kyojin expects prompt/messages')
            return {'count': next(counts)}
        with patch('benchmark.http', side_effect=tokenizer), patch('benchmark.completion') as generate:
            text, _ = benchmark.calibrated_text('http://127.0.0.1:8080/v1', 'test', 485000, dense=True)
        generate.assert_not_called()
        # Pi uses 3.5 characters/token before it has a measured usage anchor.
        # This reference must not make Pi clamp a valid large request to one output token.
        self.assertLess(len(text) / 3.5 + 8192 + 4096, 524288)

    def test_exited_unreaped_process_is_not_a_live_runtime(self):
        child = subprocess.Popen([sys.executable, '-c', 'pass'])
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                stat = Path(f'/proc/{child.pid}/stat').read_text()
                if stat[stat.rfind(')') + 2:].split()[0] == 'Z': break
                time.sleep(.01)
            else: self.fail('Child did not exit within five seconds')
            self.assertIsNone(localai.process_identity(child.pid))
        finally: child.wait(timeout=5)

    def test_alternate_profile_routes_all_helpers_to_the_loaded_model(self):
        with tempfile.TemporaryDirectory() as home:
            with patch.dict(os.environ, {'HOME': home, 'XDG_DATA_HOME': home + '/share', 'XDG_STATE_HOME': home + '/state',
                                         'XDG_CACHE_HOME': home + '/cache', 'XDG_CONFIG_HOME': home + '/config'}, clear=True), \
                 patch('install.memory', return_value={'system_total_bytes': 125 * localai.GIB}):
                p = localai.paths()
                for directory in p.values(): directory.mkdir(parents=True, exist_ok=True)
                desktop = p['apps'] / 'opencode-desktop/squashfs-root/AppRun'
                desktop.parent.mkdir(parents=True); desktop.write_text('test fixture')
                install.write_configuration()
                name = 'coding-quality'
                oc = localai.read_json(p['config'] / f'opencode-{name}.json')
                self.assertEqual(oc['model'], 'localai/' + name)
                self.assertEqual(oc['small_model'], oc['model'])
                claude = localai.read_json(p['state'] / f'claude-profiles/{name}/settings.json')
                self.assertEqual(claude['env']['ANTHROPIC_DEFAULT_HAIKU_MODEL'], name)
                self.assertEqual(claude['env']['CLAUDE_CODE_MAX_CONTEXT_TOKENS'], '262144')
                hermes = (p['state'] / f'hermes-profiles/{name}/config.yaml').read_text()
                self.assertIn('default: ' + name, hermes)
                self.assertIn('    model: ' + name, hermes)
                desktop_launcher = (p['bin'] / 'opencode-desktop-local').read_text()
                self.assertIn('LOCALAI_PROFILE:-coding-concurrent', desktop_launcher)
                self.assertIn('opencode-${LOCALAI_PROFILE}.json', desktop_launcher)

    def test_shared_store_is_independent_of_working_directory(self):
        with tempfile.TemporaryDirectory() as home:
            with patch.dict(os.environ, {'HOME': home, 'XDG_DATA_HOME': home + '/share', 'XDG_STATE_HOME': home + '/state',
                                         'XDG_CACHE_HOME': home + '/cache', 'XDG_CONFIG_HOME': home + '/config'}, clear=True):
                before = localai.paths()['models']
                with patch('pathlib.Path.cwd', return_value=Path('/tmp/another-repo')):
                    self.assertEqual(localai.paths()['models'], before)
                self.assertNotIn(str(localai.ROOT), str(before))

    def test_coding_and_general_vision_contexts_are_per_session(self):
        for name, profile in localai.profiles().items():
            if name != 'vision-clearcase' and profile['engine'] != 'comfyui':
                self.assertGreaterEqual(profile['context'], 200000, name)
        self.assertEqual(localai.profiles()['vision-clearcase']['context'], 16384)
        with patch('localai.artifact', return_value=Path('/shared/model.gguf')):
            cmd = localai.engine_command('vision-small-four', localai.profiles()['vision-small-four'])
        self.assertEqual(cmd[cmd.index('-c') + 1], str(4 * 262144))
        self.assertEqual(cmd[cmd.index('--parallel') + 1], '4')

    def test_selected_models_fit_the_storage_policy(self):
        c = localai.catalog()
        self.assertEqual(c['storage_limit_bytes'], 850_000_000_000)
        self.assertIn('qwen-exl3', c['models'])
        self.assertIn('qwen-flash', c['models'])
        self.assertNotIn('qwen27-q8', c['models'])
        self.assertEqual(c['models']['chroma-vae']['include'], ['split_files/vae/ae.safetensors'])
        self.assertTrue(all(p.get('model', 'comfyui') in c['models'] or p['engine']=='comfyui'
                            for p in localai.profiles().values()))

    def test_catalog_revision_change_refreshes_download_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            localai.save_json(state / 'models.lock.json', {'x': {'repository': 'org/test', 'revision': 'old', 'files': []}})
            definition = {'models': {'x': {'repository': 'org/test', 'revision': 'new', 'include': ['model.gguf']}}}
            metadata = {'sha': 'new', 'siblings': [{'rfilename': 'model.gguf', 'size': 12}]}
            with patch('localai.paths', return_value={'state': state}), patch('localai.catalog', return_value=definition), patch('localai.http', return_value=metadata) as fetch:
                self.assertEqual(localai.resolve_model('x')['revision'], 'new')
                fetch.assert_called_once()

    def test_gufo_calibration_counts_tokens_without_generation(self):
        counts = iter([1647, 16047])
        def tokenizer(url, body):
            if url.endswith('/tokenize'): raise OSError('unsupported endpoint')
            self.assertTrue(url.endswith('/v1/messages/count_tokens'))
            return {'input_tokens': next(counts)}
        answer = {'choices': [{'message': {'role': 'assistant', 'content': 'CEDAR-0-48271'}, 'finish_reason': 'stop'}],
                  'usage': {'prompt_tokens': 8500}, 'transport': {'first_token_seconds': 1}}
        with patch('benchmark.http', side_effect=tokenizer), patch('benchmark.completion', return_value=(answer, 2)) as generate:
            result = benchmark.worker('http://127.0.0.1:8080/v1', 'coding-concurrent', 8192, 0, 32, 1)
        self.assertEqual(generate.call_count, 2, 'only the target request and its continuation should generate')
        self.assertTrue(result['runs'][0]['recall_passed'])
        answer['choices'][0]['message']['content'] = 'CEDAR-0-48271 CEDAR-1-48271'
        # A response mixing both workers' codes must never pass recall.
        with patch('benchmark.http', side_effect=[{'tokens': list(range(100))}, {'tokens': list(range(1000))}]), \
             patch('benchmark.completion', return_value=(answer, 2)):
            result = benchmark.worker('http://127.0.0.1:8080/v1', 'coding-concurrent', 8192, 0, 32, 1)
        self.assertFalse(result['runs'][0]['recall_passed'])

    def test_firmware_fallback_caps_host_snapshots(self):
        with patch('localai.artifact', return_value=Path('/shared/model.gguf')), \
             patch('localai.memory', return_value={'system_total_bytes': 31 * localai.GIB}):
            cmd = localai.engine_command('coding-reference', localai.profiles()['coding-reference'])
        self.assertEqual(cmd[cmd.index('--cache-ram') + 1], '1024')

    def test_storage_reserves_concurrent_downloads_and_deduplicates_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            p = {'data': root / 'data', 'cache': root / 'cache',
                 'models': root / 'data/models', 'state': root / 'state'}
            p['data'].mkdir(); p['cache'].mkdir()
            (p['data'] / 'runtime').write_bytes(b'x' * 20)
            (p['cache'] / 'download').write_bytes(b'x' * 10)
            model = {'repository': 'org/model', 'files': [{'path': 'weight', 'size': 100}]}
            with patch('localai.paths', return_value=p), patch('localai.read_json', return_value={'a': model, 'b': model}):
                self.assertEqual(localai.projected_storage_bytes(), 130)

    def test_concurrent_state_updates_do_not_drop_other_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(lambda n: localai.update_json(path, str(n), n), range(30)))
            self.assertEqual(len(localai.read_json(path)), 30)

    def test_process_identity_prevents_stale_pid_ownership(self):
        self.assertIsNotNone(localai.process_identity(os.getpid()))
        with patch('localai.read_json', return_value={'pid': os.getpid(), 'identity': 'invalid'}):
            self.assertIsNone(localai.running())

    def test_memory_does_not_add_dynamic_gtt(self):
        mem = localai.memory()
        fixed = max(0, mem.get('vram_bytes', 0) - mem.get('vram_used_bytes', 0))
        self.assertEqual(mem['unified_available_bytes'], mem['system_available_bytes'] + fixed)

    def test_git_ignores_models_and_all_harness_session_context(self):
        names = ['models/model.gguf', 'weights/mtp_eh_proj.st', 'config/pi/sessions/chat.jsonl', '.hermes/sessions/session.json',
                 '.claude/conversations/chat.json', '.pi/sessions/session.json', 'data/context-cache/snapshot.json',
                 'nested/transcripts/chat.json', 'nested/checkpoints/cache.bin', '.opencode/sessions/session.json']
        for name in names:
            result = subprocess.run(['git', 'check-ignore', '--quiet', name], cwd=localai.ROOT)
            self.assertEqual(result.returncode, 0, name)
        tracked = subprocess.check_output(['git', 'ls-files'], cwd=localai.ROOT, text=True).splitlines()
        self.assertFalse(any(p.endswith(('.gguf', '.safetensors', '.st', '.jsonl', '.sqlite')) for p in tracked))

    def test_clearcase_rejects_invalid_or_unsubstantiated_output(self):
        answer = {'document_type': 'unknown', 'issuing_country': '', 'date_order': 'unknown', 'date_order_evidence': '',
            'people': [{'id': 'person1', 'role': 'unknown', 'role_evidence': ''}],
            'entries': [{'label': 'Name', 'value': 'CEDAR', 'evidence': 'Name: CEDAR', 'subject': 'unknown',
                         'person_id': 'person1', 'region': [0, 0, 1, 1], 'context': 'identity'}]}
        self.assertEqual(score(answer, {'Name': 'CEDAR'})['unsupported_values'], 0)
        answer['issuing_country'] = 'EXAMPLELAND'
        self.assertTrue(score(answer, {'Name': 'CEDAR'}, ['Nationality: EXAMPLELAND'])['unsupported_issuer'])
        answer['issuing_country'] = 'unknown'
        self.assertFalse(score(answer, {'Name': 'CEDAR'})['unsupported_issuer'])
        answer['issuing_country'] = ''
        answer['entries'][0]['value'] = 'PASSPORT'
        self.assertEqual(score(answer, {'Name': 'CEDAR'}, ['SYNTHETIC TEST PASSPORT'])['unsupported_values'], 0)
        answer['entries'][0]['value'] = 'INVENTED'
        self.assertEqual(score(answer, {'Name': 'CEDAR'})['unsupported_values'], 1)
        answer['entries'][0]['region'] = [0, 0, 500, 600]
        self.assertFalse(score(answer, {'Name': 'CEDAR'})['schema_passed'])

    def test_clearcase_schema_matches_required_top_level_contract(self):
        expected = {'document_type', 'issuing_country', 'date_order', 'date_order_evidence', 'people', 'entries'}
        self.assertEqual(set(schema()['required']), expected)
        self.assertFalse(schema()['additionalProperties'])

if __name__ == '__main__': unittest.main()
