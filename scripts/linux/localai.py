#!/usr/bin/env python3
"""Shared local inference controller. Standard library only; no private state in Git."""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
GIB = 1024 ** 3
SYSTEM_PREFIX = '''{%- set localai = namespace(system=[], conversation=[]) -%}
{%- for message in messages -%}
  {%- if message.role in ['system', 'developer'] -%}
    {%- set localai.system = localai.system + [message] -%}
  {%- else -%}
    {%- set localai.conversation = localai.conversation + [message] -%}
  {%- endif -%}
{%- endfor -%}
{%- set messages = localai.system + localai.conversation -%}
'''

def paths():
    home = Path.home()
    data = Path(os.environ.get('XDG_DATA_HOME', home / '.local/share')) / 'localai'
    state = Path(os.environ.get('XDG_STATE_HOME', home / '.local/state')) / 'localai'
    cache = Path(os.environ.get('XDG_CACHE_HOME', home / '.cache')) / 'localai'
    return {'data': data, 'state': state, 'cache': cache,
            'models': Path(os.environ.get('LOCALAI_MODEL_DIR', data / 'models')),
            'apps': data / 'apps', 'bin': home / '.local/bin',
            'config': Path(os.environ.get('XDG_CONFIG_HOME', home / '.config')) / 'localai'}

def read_json(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).is_file() else default

def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)

def update_json(path, key, value):
    """Merge state safely when independent installation stages run together."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.with_suffix('.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        data = read_json(path, {})
        data[key] = value
        save_json(path, data)
    return data

def catalog(): return read_json(ROOT / 'config/linux/catalog.json')
def profiles(): return read_json(ROOT / 'config/linux/profiles.json')

def profile_display_name(name, definition):
    model = catalog()['models'].get(definition.get('model'), {})
    fallback = model.get('repository', definition.get('model', name)).rsplit('/', 1)[-1]
    return definition.get('display_name', fallback)

def http(url, body=None, timeout=30):
    headers = {'User-Agent': 'LocalAi-device-setup/1', 'Content-Type': 'application/json'}
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as r:
        return json.load(r)

def error_detail(error):
    detail = str(error)
    if isinstance(error, urllib.error.HTTPError):
        with contextlib.suppress(OSError):
            detail += ': ' + error.read(1000).decode('utf-8', errors='replace')
    return detail[:1200]

def model_directory(key):
    definition = catalog()['models'][key]
    return paths()['models'] / definition['repository']

def artifact(key, field='model'):
    d = catalog()['models'][key]
    result = model_directory(key) / d[field]
    if field == 'runtime_model':
        artifact(key, 'model')  # The original download must still be verified.
        record = read_json(paths()['state'] / 'derived-models.json', {}).get(key, {})
        if (not result.is_file() or record.get('revision') != d['revision']
                or record.get('path') != str(result)
                or record.get('template_sha256') != d.get('runtime_template_sha256')
                or record.get('source_sha256') != d.get('sha256', {}).get(d['model'])
                or record.get('all_tensors_identical') is not True
                or record.get('size') != result.stat().st_size):
            raise RuntimeError(f'{key}: prepare the verified Gufo compatibility copy first.')
        return result
    if not result.exists():
        raise RuntimeError(f'Missing {key}/{d[field]}. Run localai download {key}.')
    verified = read_json(paths()['state'] / 'verified-models.json', {}).get(key)
    if not verified:
        raise RuntimeError(f'{key} has not finished verification. Wait for its download or run localai verify {key}.')
    if d['revision'] != 'main' and verified['revision'] != d['revision']:
        raise RuntimeError(f'{key}: verified revision differs from the catalog; download and verify the selected revision.')
    if result.is_file():
        entry = next((f for f in verified['files'] if f['path'] == d[field]), None)
        if not entry or result.stat().st_size != entry['size']:
            raise RuntimeError(f'{key}: artifact no longer matches its verified size; run localai verify {key}.')
    else:
        for entry in verified['files']:
            part = model_directory(key) / entry['path']
            if not part.is_file() or part.stat().st_size != entry['size']:
                raise RuntimeError(f'{key}: pack no longer matches its verified files; run localai verify {key}.')
    return result

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(16 * 1024 * 1024), b''): h.update(block)
    return h.hexdigest()

def directory_bytes(root):
    seen = set()
    total = 0
    for base, _, files in os.walk(root):
        for name in files:
            p = Path(base) / name
            if p.is_symlink(): continue
            st = p.stat()
            identity = (st.st_dev, st.st_ino)
            if identity not in seen:
                total += st.st_size
                seen.add(identity)
    return total

def resolve_model(key):
    d = catalog()['models'][key]
    lockpath = paths()['state'] / 'models.lock.json'
    lock = read_json(lockpath, {})
    if key in lock and lock[key]['repository'] == d['repository'] and (d['revision'] == 'main' or lock[key]['revision'] == d['revision']):
        return lock[key]
    metadata = http(f"https://huggingface.co/api/models/{d['repository']}/revision/{d['revision']}?blobs=true")
    selected = []
    for item in metadata.get('siblings', []):
        name = item['rfilename']
        if not any(fnmatch.fnmatchcase(name, pattern) for pattern in d['include']): continue
        lfs = item.get('lfs') or {}
        selected.append({'path': name, 'size': item.get('size', lfs.get('size', 0)),
                         'sha256': d.get('sha256', {}).get(name, lfs.get('sha256'))})
    for pattern in d['include']:
        if not any(fnmatch.fnmatchcase(f['path'], pattern) for f in selected):
            # Some model packs have no SHA256SUMS or no optional .st companions.
            if not any(char in pattern for char in '*?') and pattern != 'SHA256SUMS':
                raise RuntimeError(f'{key}: required artifact absent: {pattern}')
    if not selected: raise RuntimeError(f'{key}: model selection is empty')
    resolved = {'repository': d['repository'], 'revision': metadata['sha'], 'files': selected}
    update_json(lockpath, key, resolved)
    return resolved

def projected_storage_bytes():
    """Include concurrent resolved downloads, without counting shared files twice."""
    p = paths()
    usage = directory_bytes(p['data']) + directory_bytes(p['cache'])
    if not p['models'].is_relative_to(p['data']):
        usage += directory_bytes(p['models'])
    repositories = {}
    for model in read_json(p['state'] / 'models.lock.json', {}).values():
        files = repositories.setdefault(model['repository'], {})
        for entry in model['files']: files[entry['path']] = entry['size']
    for repository, files in repositories.items():
        # Incomplete HF files are already in directory_bytes; reserve only the
        # remaining space to the final repository footprint.
        directory = p['models'] / repository
        usage += max(0, sum(files.values()) - directory_bytes(directory))
    return usage

def download(keys, verify_only=False):
    selected = []
    c = catalog()
    for key in keys:
        selected.extend(c['groups'].get(key, [key]))
    for key in dict.fromkeys(selected):
        if key not in c['models']: raise RuntimeError(f'Unknown model/group: {key}')
        resolved = resolve_model(key)
        destination = model_directory(key)
        incoming = sum(f['size'] for f in resolved['files'] if not (destination / f['path']).exists())
        if projected_storage_bytes() > c.get('storage_limit_bytes', c['storage_limit_gib'] * GIB):
            raise RuntimeError(f'{c["storage_limit_gib"]} GiB installation budget exceeded; rotate an experimental model first.')
        if shutil.disk_usage(paths()['data'].parent).free < incoming + 40 * GIB:
            raise RuntimeError('Download would leave less than 40 GiB disk headroom.')
        if not verify_only:
            vpython = paths()['apps'] / 'support/bin/python'
            if not vpython.exists(): raise RuntimeError('Run scripts/linux/install.py --tooling first.')
            command = [str(vpython), '-c',
                'from huggingface_hub import snapshot_download; import sys; '
                'snapshot_download(repo_id=sys.argv[1],revision=sys.argv[2],local_dir=sys.argv[3],allow_patterns=sys.argv[4:])',
                resolved['repository'], resolved['revision'], str(destination), *[f['path'] for f in resolved['files']],
                'README.md', 'LICENSE*', 'license*', 'NOTICE*']
            subprocess.run(command, check=True)
        for entry in resolved['files']:
            path = destination / entry['path']
            if not path.is_file() or path.stat().st_size != entry['size']:
                raise RuntimeError(f'{key}: missing or wrong-size artifact: {entry["path"]}')
            if entry['sha256'] and sha256(path) != entry['sha256']:
                raise RuntimeError(f'{key}: SHA-256 mismatch: {entry["path"]}')
        update_json(paths()['state'] / 'verified-models.json', key,
                    {'revision': resolved['revision'], 'verified_at': time.time(), 'files': resolved['files']})
        kinds = {'diffusion_models', 'text_encoders', 'vae', 'loras', 'model_patches', 'latent_upscale_models', 'checkpoints'}
        for entry in resolved['files']:
            relative = entry['path']
            target = c['models'][key].get('comfy_links', {}).get(relative)
            if not target:
                components = Path(relative).parts
                index = next((i for i, part in enumerate(components) if part in kinds), None)
                if index is not None: target = str(Path(*components[index:]))
            if target:
                link = paths()['data'] / 'comfy-models' / target
                link.parent.mkdir(parents=True, exist_ok=True)
                source = destination / relative
                if link.is_symlink() and link.resolve() == source.resolve(): continue
                if link.exists() or link.is_symlink():
                    raise RuntimeError(f'Comfy model name already points elsewhere: {link}')
                link.symlink_to(source)
        print(f'Verified {key}: {destination}', flush=True)

def memory():
    m = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        m[key] = int(value.split()[0]) * 1024
    devices = []
    for dev in Path('/sys/class/drm').glob('card[0-9]*/device'):
        try:
            total = int((dev / 'mem_info_vram_total').read_text())
            used = int((dev / 'mem_info_vram_used').read_text())
            devices.append({'vram_bytes': total, 'vram_used_bytes': used,
                            'gtt_bytes': int((dev / 'mem_info_gtt_total').read_text())})
        except (OSError, ValueError): pass
    gpu = max(devices, key=lambda d: d['vram_bytes'], default={})
    # Fixed firmware carve-out is not included in MemTotal. Dynamic GTT is;
    # never add GTT to system RAM or to available memory.
    fixed_free = max(0, gpu.get('vram_bytes', 0) - gpu.get('vram_used_bytes', 0))
    return {'system_total_bytes': m['MemTotal'], 'system_available_bytes': m['MemAvailable'],
            'swap_total_bytes': m.get('SwapTotal', 0), 'swap_used_bytes': m.get('SwapTotal', 0) - m.get('SwapFree', 0),
            'unified_available_bytes': m['MemAvailable'] + fixed_free, **gpu}

def process_identity(pid):
    try:
        text = Path(f'/proc/{pid}/stat').read_text()
        fields = text[text.rfind(')') + 2:].split()
        if fields[0] in ('Z', 'X'): return None
        return fields[19]
    except (OSError, IndexError): return None

def is_comfy(name):
    return profiles()[name]['engine'] == 'comfyui'

def state_path(name):
    return paths()['state'] / ('comfy-server.json' if is_comfy(name) else 'server.json')

def running_all():
    result = []
    for filename in ('server.json', 'comfy-server.json'):
        state = read_json(paths()['state'] / filename, {})
        if state and process_identity(state['pid']) == state.get('identity'):
            result.append(state)
    return result

def running(name=None):
    """Select a runtime slot; legacy callers prefer inference, then ComfyUI."""
    active = running_all()
    if name is not None:
        return next((s for s in active if is_comfy(s['profile']) == is_comfy(name)), None)
    return next((s for s in active if not is_comfy(s['profile'])), active[0] if active else None)

def check_start(name, warn=False):
    for current in running_all():
        if current['profile'] == name:
            continue
        if is_comfy(current['profile']) == is_comfy(name):
            raise RuntimeError(f'{current["profile"]} is already using this runtime slot. Stop it with localai stop {current["profile"]} before switching to {name}.')
        if current['port'] == profiles()[name].get('port', 8080):
            raise RuntimeError(f'{name}: port {current["port"]} is already used by {current["profile"]}.')
        if warn:
            print(f'Warning: starting {name} alongside {current["profile"]}; they share GPU compute and unified memory. '
                  'Generation may slow down, and memory pressure may stop a runtime.', file=sys.stderr, flush=True)

def validation_metadata(name):
    owner = running(name)
    active = owner if owner and owner['profile'] == name else {}
    definition = active.get('profile_settings', profiles()[name])
    verified = read_json(paths()['state'] / 'verified-models.json', {})
    return {'profile_settings': definition,
            'runtime_command': active.get('command'),
            'launcher_scripts': active.get('launcher_scripts', {}),
            'runtime_tuning': active.get('runtime_tuning', {}),
            'model_revisions': {key: verified.get(key, {}).get('revision')
                for key in dict.fromkeys(definition.get(field) for field in ('model', 'projector_model', 'draft')) if key}}

@contextlib.contextmanager
def lock():
    path = paths()['state'] / 'controller.lock'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield

def engine_command(name, profile):
    p = paths()
    engine = profile['engine']
    port = profile.get('port', 8080)
    if engine == 'comfyui':
        cache = ['--cache-ram', str(profile['node_cache_headroom_gib'])] if profile.get('node_cache_headroom_gib') else ['--cache-none']
        return [str(p['apps'] / 'comfyui-env/bin/python'), str(p['apps'] / 'ComfyUI/main.py'),
                '--listen', '127.0.0.1', '--port', str(port), '--extra-model-paths-config',
                str(p['config'] / 'comfy-model-paths.yaml'), '--output-directory', str(p['data'] / 'outputs'),
                '--user-directory', str(p['state'] / 'comfyui'), '--preview-method', 'none',
                *cache, '--reserve-vram', str(profile['minimum_free_gib'])]
    key = profile['model']
    model = artifact(key, 'runtime_model') if catalog()['models'][key].get('runtime_model') else artifact(key)
    context = profile['context']
    if engine == 'llama':
        # With a 96 GiB firmware carve-out the desktop and all host-side
        # snapshots share only 31 GiB. Keep this temporary fallback bounded.
        cache_gib = profile.get('cache_gib', 8)
        if memory()['system_total_bytes'] < 100 * GIB:
            cache_gib = min(cache_gib, 1)
        cmd = [str(p['apps'] / 'llama.cpp/build/bin/llama-server'), '-m', str(model),
               '--host', '127.0.0.1', '--port', str(port), '--alias', name, '--jinja',
               '-ngl', '999', '-fa', 'on', '-c', str(context * profile['sessions']),
               '--parallel', str(profile['sessions']), '--metrics', '--no-context-shift',
               '-ctk', 'q8_0', '-ctv', 'q8_0', '--cache-ram', str(cache_gib * 1024),
               '--threads', '8', '--threads-batch', '16']
        if profile.get('vision'):
            cmd += ['--mmproj', str(artifact(profile.get('projector_model', key), 'projector')),
                    '--image-min-tokens', '1024', '--image-max-tokens', '4096']
        if profile.get('experimental_yarn'):
            cmd += ['--rope-scaling', 'yarn', '--rope-scale', str(context / 262144), '--yarn-orig-ctx', '262144']
        if profile.get('normalize_system_messages'):
            # Claude can insert later system updates. Keep their instruction
            # priority and order, while satisfying Qwen's leading-system rule.
            raw = subprocess.check_output([str(p['apps'] / 'support/bin/python'), '-c',
                'import json,sys; from gguf import GGUFReader; '
                'print(json.dumps(GGUFReader(sys.argv[1]).fields["tokenizer.chat_template"].contents()))', str(model)], text=True)
            original = json.loads(raw)
            template = p['config'] / 'claude-qwen.jinja'
            template.write_text(SYSTEM_PREFIX + original)
            cmd += ['--chat-template-file', str(template)]
        return cmd
    if engine == 'gufo':
        native = p['apps'] / 'gufo/bin/gufo'
        image = profile.get('runtime_image') or read_json(p['state'] / 'runtime-lock.json', {}).get('gufo_image')
        if not image and not native.exists(): raise RuntimeError('Gufo is not installed. Run install.py --engines after system prerequisites.')
        # Same absolute model/cache paths are mounted, avoiding per-repository copies.
        cmd = ['podman', 'run', '--rm', '--name', 'localai-gufo', '--network', 'host',
               '--userns=keep-id', '--device', '/dev/kfd', '--device', '/dev/dri',
               '--group-add', 'keep-groups', '--ulimit', 'memlock=-1',
               '-v', f'{p["models"]}:{p["models"]}:ro', '-v', f'{p["cache"]}:{p["cache"]}',
               image, 'gufo', 'serve', '--host', '127.0.0.1', '--port', str(port),
               '--max-request-bytes', '33554432', 'llm', '--model', str(model),
               '--served-model-name', name, '--sessions', str(profile['sessions']),
               '--context', str(context), '--max-tokens', '32768',
               '--cache-ram-bytes', str(profile['cache_gib'] * GIB),
               '--cache-disk', str(p['cache'] / name), '--cache-disk-bytes', str(profile.get('disk_cache_gib', 8) * GIB),
               '--think', 'on', '--preserve-thinking', 'on', '--reasoning-effort', 'medium']
        for setting in ('temperature', 'top_p', 'top_k', 'min_p'):
            if setting in profile.get('sampling', {}):
                cmd += ['--' + setting.replace('_', '-'), str(profile['sampling'][setting])]
        if profile.get('disk_staging_gib'):
            cmd += ['--cache-disk-staging-bytes', str(profile['disk_staging_gib'] * GIB)]
        if profile.get('speculative') is False:
            cmd += ['--speculative', 'off']
        elif key in ('qwen-flash', 'qwen-flash-q3'):
            cmd += ['--speculative', 'mtp', '--mtp-model', str(artifact(key, 'draft')), '--draft-tokens', '7']
        elif profile.get('draft'):
            cmd += ['--speculative', 'dflash2', '--dflash-model', str(artifact(profile['draft']))]
        if profile.get('vision'):
            cmd += ['--mmproj', str(artifact(profile.get('projector_model', key), 'projector'))]
        if native.exists() and (not image or os.environ.get('LOCALAI_GUFO_NATIVE') == '1'):
            cmd = [str(native), *cmd[cmd.index('gufo') + 1:]]
        return cmd
    if engine.startswith('kyojin-'):
        family = engine.split('-')[1]
        cmd = [str(p['apps'] / 'kyojin/.venv/bin/python'), str(p['apps'] / f'kyojin/tools/{family}/serve.py'),
               '--model', str(model), '--model-id', name, '--host', '127.0.0.1', '--port', str(port), '-c', str(context),
               '--slot-save-path', str(p['cache'] / name / 'slots')]
        if family == 'mimo':
            cmd[1] = str(ROOT / 'scripts/linux/serve_mimo.py')
            cmd += ['--cache-bits', str(profile.get('cache_bits', 8))]
            if profile.get('speculative') is False: cmd += ['--no-dflash']
        if family == 'glm': cmd += ['--num-draft', '2', '--image-cache-mb', str(profile.get('image_cache_mb', 256))]
        if family == 'qwen' and context > 262144: cmd += ['--cache-bits', '8']
        if family == 'qwen' and profile.get('speculative') is False: cmd += ['--draft-policy', 'off', '--ndt', '1']
        if not profile.get('vision'): cmd += ['--no-vision']
        # Vendor env.sh selects the matching ROCm SDK/HSA library before serving.
        return ['bash', str(ROOT / 'scripts/linux/run-kyojin.sh'), *cmd]
    raise RuntimeError(f'Unknown engine: {engine}')

SOFT_PRESSURE_GRACE_S = 60

def memory_snapshot(sample=None):
    sample = sample or memory()
    top = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit(): continue
        with contextlib.suppress(OSError, ValueError, IndexError):
            rss = int((entry / 'statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
            top.append((rss, entry.name, (entry / 'comm').read_text().strip()))
    return {'system_available_gib': round(sample['system_available_bytes'] / GIB, 1),
            'unified_available_gib': round(sample['unified_available_bytes'] / GIB, 1),
            'swap_used_gib': round(sample['swap_used_bytes'] / GIB, 1),
            'top_rss': [{'pid': int(pid), 'name': comm, 'gib': round(rss / GIB, 1)} for rss, pid, comm in sorted(top, reverse=True)[:6]]}

def log_stop_event(state_dir, name, reason, exit_code, requested):
    """Append one JSON line per runtime stop. `natural` is true only for a clean exit nobody forced."""
    natural = reason == 'runtime exited' and exit_code == 0 and not requested
    if requested and reason == 'runtime exited': cause = 'stop requested (signal)'
    elif natural: cause = 'runtime exited cleanly'
    elif reason != 'runtime exited': cause = reason
    elif exit_code is not None and exit_code < 0: cause = f'runtime killed by signal {-exit_code}'
    else: cause = f'runtime exited with code {exit_code}'
    event = {'time': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'profile': name, 'natural': natural or requested,
             'cause': cause, 'exit_code': exit_code}
    if not (natural or requested):
        with contextlib.suppress(Exception): event['memory'] = memory_snapshot()
    with contextlib.suppress(OSError):
        state_dir.mkdir(parents=True, exist_ok=True)
        with (state_dir / 'stop-events.jsonl').open('a') as stream: stream.write(json.dumps(event) + '\n')

def serve(name):
    profile = profiles()[name]
    p = paths()
    with lock():
        check_start(name)
        if running(name): raise RuntimeError(f'{name}: a runtime is already active in this slot.')
        # Move pre-concurrency ComfyUI state without interrupting its process.
        legacy = read_json(p['state'] / 'server.json', {})
        if (legacy and is_comfy(legacy['profile'])
                and process_identity(legacy['pid']) == legacy.get('identity')):
            save_json(p['state'] / 'comfy-server.json', legacy)
            (p['state'] / 'server.json').unlink()
        record = state_path(name)
        mem = memory()
        if profile['engine'] == 'gufo' and mem['system_total_bytes'] < 100 * GIB:
            raise RuntimeError('Gufo host-memory loading is blocked by the large firmware UMA reservation. Reduce it and reboot; coding-reference provides the same model/context through Vulkan meanwhile.')
        if mem['unified_available_bytes'] < (profile['estimated_gib'] + profile['minimum_free_gib']) * GIB:
            raise RuntimeError(f'{name}: insufficient unified-memory headroom; need approximately {profile["estimated_gib"]} GiB plus {profile["minimum_free_gib"]} GiB reserve. Check localai doctor / BIOS UMA.')
        cmd = engine_command(name, profile)
        if not shutil.which(cmd[0]): raise RuntimeError(f'Runtime missing: {cmd[0]}')
        environment = {**os.environ, **profile.get('environment', {})}
        if profile['engine'].startswith('kyojin'):
            environment.setdefault('KYOJIN_SSE_PING_S', '10')
        launcher_scripts = {str(Path(item).relative_to(ROOT)): sha256(Path(item)) for item in cmd
            if Path(item).is_absolute() and Path(item).is_relative_to(ROOT / 'scripts') and Path(item).is_file()}
        child = subprocess.Popen(cmd, start_new_session=True,
            env=environment,
            cwd=p['apps'] / 'kyojin' if profile['engine'].startswith('kyojin') else p['data'])
        state = {'profile': name, 'pid': child.pid, 'identity': process_identity(child.pid),
                 'command': cmd, 'profile_settings': profile,
                 'launcher_scripts': launcher_scripts,
                 'runtime_tuning': {k:v for k,v in environment.items() if k.startswith(('EXL3_', 'KYOJIN_'))},
                 'supervisor_pid': os.getpid(), 'port': profile.get('port', 8080), 'started': time.time()}
        save_json(record, state)
    requested = []
    def stop_child(*args):
        if args: requested.append(True)  # a signal handler call, not an internal stop
        if child.poll() is None:
            with contextlib.suppress(ProcessLookupError): os.killpg(child.pid, signal.SIGTERM)
    signal.signal(signal.SIGTERM, stop_child)
    signal.signal(signal.SIGINT, stop_child)
    # The model's own memory is already resident, so `minimum_free_gib` is headroom
    # that other apps (browsers, VMs) can eat into. Only stop the model for it when
    # the squeeze persists; below the hard floor the host is at risk, so stop fast.
    soft_since = hard_since = None
    soft_logged = False
    stop_reason = 'runtime exited'
    try:
        while child.poll() is None:
            sample = memory()
            now = time.monotonic()
            soft = sample['unified_available_bytes'] < profile['minimum_free_gib'] * GIB
            hard = sample['system_available_bytes'] < 3 * GIB
            soft_since = (soft_since or now) if soft else None
            hard_since = (hard_since or now) if hard else None
            if soft_since is not None and not soft_logged:
                soft_logged = True
                print(f'Memory below the {profile["minimum_free_gib"]} GiB reserve; stopping in {SOFT_PRESSURE_GRACE_S}s if it does not recover. {json.dumps(memory_snapshot(sample))}', file=sys.stderr, flush=True)
            elif soft_since is None: soft_logged = False
            if (hard_since is not None and now - hard_since > 3) or (soft_since is not None and now - soft_since > SOFT_PRESSURE_GRACE_S):
                stop_reason = 'memory reserve exhausted'
                print('Memory reserve exhausted; stopping this runtime. Saved harness transcripts remain intact.', file=sys.stderr, flush=True)
                stop_child()
                break
            time.sleep(1)
        try: return child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            return child.wait()
    finally:
        stop_child()
        save_json(p['state'] / ('last-comfy-server.json' if is_comfy(name) else 'last-server.json'), {**state, 'exit_code': child.poll(), 'reason': stop_reason, 'ended': time.time()})
        log_stop_event(p['state'], name, stop_reason, child.poll(), bool(requested))
        print(f'Runtime ended: profile={name}, exit_code={child.poll()}, reason={stop_reason}', flush=True)
        with lock():
            if read_json(record, {}).get('pid') == child.pid:
                record.unlink(missing_ok=True)

def start(name):
    check_start(name, warn=True)
    current = running(name)
    p = paths()
    log = p['state'] / f'{name}.log'
    log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    process = None
    if not current:
        with log.open('a') as stream:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'serve', name],
                                       stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 1800
    port = profiles()[name].get('port', 8080)
    health = '/system_stats' if profiles()[name]['engine'] == 'comfyui' else ('/ready' if profiles()[name]['engine'] == 'gufo' else '/health')
    while time.monotonic() < deadline:
        if (process is not None and process.poll() is not None) or (current and not running(name)):
            raise RuntimeError(f'{name} exited during startup; inspect {log}')
        try:
            http(f'http://127.0.0.1:{port}{health}', timeout=2)
            owned = running(name)
            if owned and owned['profile'] == name:
                return owned
        except (OSError, ValueError): time.sleep(2)
    raise RuntimeError(f'Startup exceeded 30 minutes; inspect {log}')

def stop(name=None):
    with lock():
        state = running(name)
        if name is not None and state and state["profile"] != name: return
        if not state: return
        # Only terminate the exact owned PID, never a process found by name/port.
        os.kill(state['pid'], signal.SIGTERM)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and process_identity(state['pid']) == state['identity']: time.sleep(.25)
    if process_identity(state['pid']) == state['identity']: raise RuntimeError('Runtime has not stopped; inspect its log before retrying.')

def doctor():
    p = paths()
    result = {'paths': {k: str(v) for k, v in p.items()}, 'memory': memory(), 'running': running(), 'runtimes': running_all(),
              'tools': {t: shutil.which(t) for t in ('node', 'npm', 'uv', 'podman', 'crun', 'cmake', 'ninja', 'ffmpeg', 'rocminfo')},
              'gpu_devices': {d: os.access(d, os.R_OK | os.W_OK) for d in ('/dev/kfd', '/dev/dri/renderD128')},
              'verified_models': list(read_json(p['state'] / 'verified-models.json', {}))}
    if result['memory']['system_total_bytes'] < 100 * GIB:
        result['memory_note'] = 'Large BIOS UMA reservation detected. Reduce to 512 MiB/minimum before enabling 112 GiB dynamic TTM.'
    print(json.dumps(result, indent=2))

def main():
    forwarded = {'video-test': 'video_performance.py', 'prefill-test': 'prefill_acceptance.py', 'cancel-test': 'cancel_probe.py', 'campaign': 'campaign.py', 'bench': 'benchmark.py', 'clearcase': 'clearcase_benchmark.py',
                 'harness-test': 'harness_smoke.py', 'media-test': 'media_probe.py', 'media-validate': 'validate_media.py', 'coding-test': 'coding_benchmark.py',
                 'recovery-test': 'harness_recovery.py', 'cache-restart-test': 'cache_restart.py',
                 'reliability-test': 'reliability.py', 'acceptance': 'remaining_acceptance.py'}
    if len(sys.argv) > 1 and sys.argv[1] in forwarded:
        script = forwarded[sys.argv[1]]
        environment = 'comfyui-env' if sys.argv[1] in ('media-validate', 'video-test') else 'support'
        return subprocess.call([str(paths()['apps'] / environment / 'bin/python'),
                                str(ROOT / 'scripts/linux' / script), *sys.argv[2:]])
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('doctor', 'status', 'models-path', 'configure'): sub.add_parser(command)
    sub.add_parser('stop').add_argument('profile', nargs='?', choices=profiles())
    for command in ('start', 'serve'):
        sub.add_parser(command).add_argument('profile', choices=profiles())
    sub.add_parser('profiles')
    for command in ('download', 'verify'):
        sub.add_parser(command).add_argument('models', nargs='+')
    p = sub.add_parser('bench'); p.add_argument('args', nargs=argparse.REMAINDER)
    p = sub.add_parser('clearcase'); p.add_argument('args', nargs=argparse.REMAINDER)
    for command in ('harness-test', 'media-test', 'coding-test'):
        sub.add_parser(command).add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    for key, path in paths().items():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.command == 'doctor': doctor()
    elif args.command == 'configure':
        from install import write_configuration
        write_configuration()
    elif args.command == 'status':
        state = {**(running() or {'state': 'stopped'}), 'runtimes': [
            {k: v for k, v in item.items() if k not in ('command', 'profile_settings')} for item in running_all()]}
        print(json.dumps({k: v for k, v in state.items() if k not in ('command', 'profile_settings')}, indent=2))
    elif args.command == 'profiles': print(json.dumps(profiles(), indent=2))
    elif args.command == 'models-path': print(paths()['models'])
    elif args.command == 'start':
        state = start(args.profile)
        print(json.dumps({k: v for k, v in state.items() if k not in ('command', 'profile_settings')}, indent=2))
    elif args.command == 'serve': return serve(args.profile)
    elif args.command == 'stop': stop(args.profile)
    elif args.command in ('download', 'verify'): download(args.models, args.command == 'verify')
    elif args.command in ('bench', 'clearcase'):
        script = 'benchmark.py' if args.command == 'bench' else 'clearcase_benchmark.py'
        python = paths()['apps'] / 'support/bin/python'
        return subprocess.call([str(python), str(ROOT / 'scripts/linux' / script), *args.args])
    return 0

if __name__ == '__main__':
    try: sys.exit(main())
    except (RuntimeError, OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f'localai: {error}', file=sys.stderr)
        sys.exit(1)
