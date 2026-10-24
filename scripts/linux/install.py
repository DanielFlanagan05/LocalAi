#!/usr/bin/env python3
"""Idempotent user-level installation. Run individual stages or --all."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import time

from localai import ROOT, paths, profiles, profile_display_name, memory, http, read_json, save_json, update_json, sha256, download

GUFO_REV = 'a7ca5f0fc143203219dc71e079683d16642c6f15'
KYOJIN_REV = '30b0e3ab91cf25b4ccb5b6d044ef4946907c6259'

def run(*args, cwd=None, env=None):
    print('+', shlex.join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], cwd=cwd, env=env, check=True)

def locked(key, producer):
    path = paths()['state'] / 'runtime-lock.json'
    lock = read_json(path, {})
    if key not in lock:
        lock = update_json(path, key, producer())
    return lock[key]

def fetch(url, digest=None):
    destination = paths()['cache'] / 'downloads' / url.rsplit('/', 1)[-1]
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and digest and sha256(destination) == digest.removeprefix('sha256:'):
        return destination
    partial = destination.with_suffix(destination.suffix + '.partial')
    run('curl', '--fail', '--location', '--silent', '--show-error', '--retry', '5', '--retry-delay', '2',
        '--continue-at', '-', '--output', partial, url)
    if digest and sha256(partial) != digest.removeprefix('sha256:'):
        raise RuntimeError(f'Checksum mismatch: {destination.name}')
    partial.replace(destination)
    return destination

def extract(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as handle: handle.extractall(destination, filter='data')

def clone(repository, revision, destination):
    if not (destination / '.git').exists():
        destination.mkdir(parents=True, exist_ok=True)
        run('git', 'init', destination)
        run('git', '-C', destination, 'remote', 'add', 'origin', f'https://github.com/{repository}.git')
    head = subprocess.run(['git', '-C', str(destination), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    if head != revision:
        dirty = subprocess.run(['git', '-C', str(destination), 'status', '--porcelain'], capture_output=True, text=True, check=True).stdout
        if dirty: raise RuntimeError(f'Refusing to change modified runtime checkout: {destination}')
        run('git', '-C', destination, 'fetch', '--depth', '1', 'origin', revision)
        run('git', '-C', destination, 'checkout', '--detach', 'FETCH_HEAD')

def tooling():
    p = paths()
    # User runtimes avoid requiring changes to the distro Python or Node packages.
    version = 'v24.22.0'
    node_dir = p['data'] / 'toolchains' / f'node-{version}-linux-x64'
    if not (node_dir / 'bin/node').exists():
        base = f'https://nodejs.org/dist/{version}/'
        checksums = fetch(base + 'SHASUMS256.txt')
        filename = f'node-{version}-linux-x64.tar.xz'
        expected = next(line.split()[0] for line in checksums.read_text().splitlines() if line.endswith('  ' + filename))
        extract(fetch(base + filename, expected), node_dir.parent)
    uv_dir = p['data'] / 'toolchains/uv-x86_64-unknown-linux-gnu'
    if not (uv_dir / 'uv').exists():
        archive = fetch('https://github.com/astral-sh/uv/releases/download/0.13.4/uv-x86_64-unknown-linux-gnu.tar.gz',
                        '2b428396f12572d4429cf210ca234dd599a33b3af0958a4d5ed569d63e3f344f')
        extract(archive, uv_dir.parent)
    for name, target in {'node': node_dir / 'bin/node', 'npm': node_dir / 'bin/npm', 'npx': node_dir / 'bin/npx',
                         'uv': uv_dir / 'uv', 'uvx': uv_dir / 'uvx'}.items():
        link = p['bin'] / name
        if link.is_symlink(): link.unlink()
        if not link.exists(): link.symlink_to(target)
    os.environ['PATH'] = str(p['bin']) + os.pathsep + os.environ['PATH']
    run(p['bin'] / 'uv', 'python', 'install', '3.12', '3.11')
    env = p['apps'] / 'support'
    if not (env / 'bin/python').exists(): run(p['bin'] / 'uv', 'venv', '--python', '3.12', env)
    versions = locked('support_packages', lambda: {
        package: http(f'https://pypi.org/pypi/{package}/json')['info']['version']
        for package in ('huggingface-hub', 'jsonschema', 'pillow', 'reportlab', 'ninja')})
    run(p['bin'] / 'uv', 'pip', 'install', '--python', env / 'bin/python', *[f'{k}=={v}' for k, v in versions.items()])
    ninja = p['bin'] / 'ninja'
    if not ninja.exists(): ninja.symlink_to(env / 'bin/ninja')
    write_configuration()

def shell_launcher(name, body):
    path = paths()['bin'] / name
    if path.exists() and not path.is_symlink() and '# LocalAi managed launcher' not in path.read_text(errors='replace'):
        raise RuntimeError(f'Refusing to overwrite an unmanaged command: {path}')
    path.write_text('#!/usr/bin/env bash\n# LocalAi managed launcher\nset -euo pipefail\n' + body + '\n')
    path.chmod(0o755)

def desktop(name, command, terminal=False):
    directory = Path.home() / '.local/share/applications'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f'localai-{name.lower().replace(" ", "-")}.desktop').write_text(
        f'[Desktop Entry]\nType=Application\nName={name}\nExec={command}\nTerminal={str(terminal).lower()}\nCategories=Development;\n')

def write_configuration():
    p = paths()
    default_profile = 'coding-reference' if memory()['system_total_bytes'] < 100 * 1024**3 else 'coding-concurrent'
    save_json(p['config'] / 'defaults.json', {'coding_profile': default_profile,
        'reason': 'Firmware UMA reservation requires Vulkan reference until reduced' if default_profile == 'coding-reference' else 'Gufo native-context concurrent profile'})
    localai = p['bin'] / 'localai'
    shell_launcher('localai', f'exec /usr/bin/python {shlex.quote(str(ROOT / "scripts/linux/localai.py"))} "$@"')
    shared_env = p['config'] / 'env.sh'
    shared_env.write_text('\n'.join([
        '# Shared model paths; source this from any project.',
        f'export PATH={shlex.quote(str(p["bin"]))}:"$PATH"',
        f'export LOCALAI_MODEL_DIR={shlex.quote(str(p["models"]))}',
        f'export LOCALAI_REPO={shlex.quote(str(ROOT))}',
        f'export HF_HOME={shlex.quote(str(p["cache"] / "huggingface"))}',
        f'export UV_CACHE_DIR={shlex.quote(str(p["cache"] / "uv"))}',
        'export LOCALAI_BASE_URL=http://127.0.0.1:8080/v1', '']) )
    environment = Path.home() / '.config/environment.d'
    environment.mkdir(parents=True, exist_ok=True)
    (environment / '60-localai.conf').write_text(f'PATH={p["bin"]}:${{PATH}}\nLOCALAI_MODEL_DIR={p["models"]}\n')
    fish = Path.home() / '.config/fish/conf.d'
    fish.mkdir(parents=True, exist_ok=True)
    (fish / 'localai.fish').write_text(f'fish_add_path {shlex.quote(str(p["bin"]))}\nset -gx LOCALAI_MODEL_DIR {shlex.quote(str(p["models"]))}\n')
    for name in ('.bashrc', '.zshrc'):
        startup = Path.home() / name
        existing = startup.read_text() if startup.exists() else ''
        marker = '# LocalAi shared user commands'
        if marker not in existing:
            if startup.exists(): shutil.copy2(startup, p['state'] / (name.lstrip('.') + '.before-localai'))
            with startup.open('a') as stream:
                stream.write(f'\n{marker}\nexport PATH={shlex.quote(str(p["bin"]))}:"$PATH"\n')
    # Each tool gets separate private state, shared across project directories.
    for tool in ('pi', 'hermes', 'claude', 'opencode', 'comfyui'):
        (p['state'] / tool).mkdir(parents=True, exist_ok=True, mode=0o700)
    pi_extensions = p['state'] / 'pi/extensions'
    pi_extensions.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'config/pi/extensions/localai-exit.ts', pi_extensions / 'localai-exit.ts')
    models = [{'id': name, 'name': profile_display_name(name, definition), 'reasoning': definition['model'] != 'vision-small',
               'input': ['text', 'image'] if definition.get('vision') else ['text'],
               'contextWindow': definition['context'], 'maxTokens': definition.get('max_output_tokens', 4096 if name == 'vision-clearcase' else 32768),
               'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}}
              for name, definition in profiles().items() if definition['engine'] != 'comfyui']
    save_json(p['state'] / 'pi/models.json', {'providers': {'localai': {
        'baseUrl': 'http://127.0.0.1:8080/v1', 'api': 'openai-completions', 'apiKey': 'local-only', 'models': models}}})
    save_json(p['state'] / 'pi/settings.json', {'defaultProvider': 'localai', 'defaultModel': default_profile, 'defaultThinkingLevel': 'medium',
        'compaction': {'enabled': True, 'reserveTokens': 36864, 'keepRecentTokens': 12000,
                       'modelOverrides': {'localai/vision-clearcase': {'reserveTokens': 4096, 'keepRecentTokens': 2048},
                                          'localai/mimo-text': {'reserveTokens': 24576, 'keepRecentTokens': 12000}}}})
    save_json(p['config'] / 'opencode.json', {'$schema': 'https://opencode.ai/config.json',
        'model': 'localai/' + default_profile, 'small_model': 'localai/' + default_profile,
        'provider': {'localai': {'npm': '@ai-sdk/openai-compatible', 'name': 'Shared Local AI',
            'options': {'baseURL': 'http://127.0.0.1:8080/v1', 'apiKey': 'local-only'},
            'models': {m['id']: {'name': m['name'], 'limit': {'context': m['contextWindow'], 'output': m['maxTokens']},
                       'modalities': {'input': m['input'], 'output': ['text']}} for m in models}}}})
    # No saved subscription credentials are used by the local Claude wrapper.
    save_json(p['state'] / 'claude/settings.json', {'model': 'messages-compatible',
        'env': {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8080', 'ANTHROPIC_AUTH_TOKEN': 'local-only',
                'ANTHROPIC_MODEL': 'messages-compatible', 'ANTHROPIC_DEFAULT_SONNET_MODEL': 'messages-compatible',
                'ANTHROPIC_DEFAULT_OPUS_MODEL': 'messages-compatible', 'ANTHROPIC_DEFAULT_HAIKU_MODEL': 'messages-compatible',
                'ANTHROPIC_DEFAULT_FABLE_MODEL': 'messages-compatible',
                'CLAUDE_CODE_SUBAGENT_MODEL': 'messages-compatible', 'CLAUDE_CODE_MAX_CONTEXT_TOKENS': '262144',
                'CLAUDE_CODE_AUTO_COMPACT_WINDOW': '225280', 'CLAUDE_CODE_MAX_OUTPUT_TOKENS': '32768',
                'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1', 'DISABLE_TELEMETRY': '1'}})
    (p['state'] / 'hermes/config.yaml').write_text(
        f'model:\n  default: {default_profile}\n  provider: custom\n  base_url: http://127.0.0.1:8080/v1\n  context_length: 262144\n'
        'compression:\n  enabled: true\n  threshold: 0.86\n'
        f'auxiliary:\n  compression:\n    provider: custom\n    base_url: http://127.0.0.1:8080/v1\n    model: {default_profile}\n')
    # Helper/title/compression calls must follow the explicitly selected alias.
    opencode_base = read_json(p['config'] / 'opencode.json')
    claude_base = read_json(p['state'] / 'claude/settings.json')
    for model in models:
        name = model['id']
        save_json(p['config'] / f'opencode-{name}.json',
                  {**opencode_base, 'model': 'localai/' + name, 'small_model': 'localai/' + name})
        claude_env = dict(claude_base['env'])
        for variable in ('ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL',
                         'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_DEFAULT_FABLE_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL'):
            claude_env[variable] = name
        claude_env['CLAUDE_CODE_MAX_CONTEXT_TOKENS'] = str(model['contextWindow'])
        claude_env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = str(model['maxTokens'])
        claude_env['CLAUDE_CODE_AUTO_COMPACT_WINDOW'] = str(max(8192, model['contextWindow'] - model['maxTokens'] - 4096))
        save_json(p['state'] / f'claude-profiles/{name}/settings.json',
                  {**claude_base, 'model': name, 'env': claude_env})
        hermes_home = p['state'] / 'hermes-profiles' / name
        hermes_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        (hermes_home / 'config.yaml').write_text(
            f'model:\n  default: {name}\n  provider: custom\n  base_url: http://127.0.0.1:8080/v1\n  context_length: {model["contextWindow"]}\n'
            f'compression:\n  enabled: true\n  threshold: {0.90 if name == "mimo-text" else 0.86}\n'
            f'auxiliary:\n  compression:\n    provider: custom\n    base_url: http://127.0.0.1:8080/v1\n    model: {name}\n')
    common = f'source {shlex.quote(str(shared_env))}\nexport LOCALAI_PROFILE="${{LOCALAI_PROFILE:-{default_profile}}}"\n'
    node_apps = p['apps'] / 'node/bin'
    launchers = {
        'pi-local': ('coding-concurrent', f'export PI_CODING_AGENT_DIR={shlex.quote(str(p["state"] / "pi"))}\nexec {shlex.quote(str(node_apps / "pi"))} --provider localai --model "${{LOCALAI_PROFILE:-coding-concurrent}}" "$@"'),
        'opencode-local': ('coding-concurrent', f'export OPENCODE_CONFIG={shlex.quote(str(p["config"]))}/"opencode-${{LOCALAI_PROFILE}}.json"\nexec {shlex.quote(str(p["apps"] / "opencode/opencode"))} --model "localai/${{LOCALAI_PROFILE:-coding-concurrent}}" "$@"'),
        'hermes-local': ('coding-concurrent', f'export HERMES_HOME={shlex.quote(str(p["state"] / "hermes"))}\nif [[ "$LOCALAI_PROFILE" != {shlex.quote(default_profile)} ]]; then export HERMES_HOME={shlex.quote(str(p["state"] / "hermes-profiles"))}/"$LOCALAI_PROFILE"; fi\nexport OPENAI_API_KEY=local-only\nexport OPENAI_BASE_URL=http://127.0.0.1:8080/v1\nexec {shlex.quote(str(p["apps"] / "hermes/.venv/bin/hermes"))} chat --provider custom --base-url http://127.0.0.1:8080/v1 --api-key local-only --model "${{LOCALAI_PROFILE:-coding-concurrent}}" "$@"'),
        'claude-local': ('messages-compatible', f'export CLAUDE_CONFIG_DIR={shlex.quote(str(p["state"] / "claude"))}\nif [[ "${{LOCALAI_PROFILE:-messages-compatible}}" != messages-compatible ]]; then export CLAUDE_CONFIG_DIR={shlex.quote(str(p["state"] / "claude-profiles"))}/"$LOCALAI_PROFILE"; fi\nunset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN\nexec {shlex.quote(str(node_apps / "claude"))} "$@"'),
        'comfyui-local': ('comfyui', 'exec xdg-open http://127.0.0.1:8188')}
    for name, (profile, body) in launchers.items():
        prefix = common if name not in ('claude-local', 'comfyui-local') else f'source {shlex.quote(str(shared_env))}\n'
        launch = 'localai start comfyui\n' if name == 'comfyui-local' else f'localai start "${{LOCALAI_PROFILE:-{profile}}}"\n'
        shell_launcher(name, prefix + launch + body)
        desktop(name.removesuffix('-local').title() + ' Local', str(p['bin'] / name), name != 'comfyui-local')
    shutil.copy2(ROOT / 'scripts/linux/run-comfyui.sh', p['bin'] / 'run-comfyui')
    (p['bin'] / 'run-comfyui').chmod(0o755)
    shell_launcher('stop-comfyui', f'exec /usr/bin/python {shlex.quote(str(ROOT / "scripts/linux/comfy_session.py"))} --stop "$@"')
    for name in ('pi', 'hermes'):
        raw = p['apps'] / ('node/bin/pi' if name == 'pi' else 'hermes/.venv/bin/hermes')
        shell_launcher(name, f'source {shlex.quote(str(shared_env))}\n'
            f'if [[ "${{1:-}}" == --help || "${{1:-}}" == --version ]]; then exec {shlex.quote(str(raw))} "$@"; fi\n'
            'export LOCALAI_PROFILE="${LOCALAI_PROFILE:-coding-quality}"\n'
            f'exec {shlex.quote(str(p["bin"] / (name + "-local")))} "$@"')
        desktop(name.title() + ' Quality', str(p['bin'] / name), True)
        shell_launcher(name + '-gufo', f'source {shlex.quote(str(shared_env))}\n'
            'export LOCALAI_PROFILE="${LOCALAI_PROFILE:-gufo-flash}"\n'
            f'exec {shlex.quote(str(p["bin"] / (name + "-local")))} "$@"')
        desktop(name.title() + ' Gufo Flash', str(p['bin'] / (name + '-gufo')), True)
    desktop_app = p['apps'] / 'opencode-desktop/squashfs-root/AppRun'
    if desktop_app.exists():
        shell_launcher('opencode-desktop-local', common +
            f'export OPENCODE_CONFIG={shlex.quote(str(p["config"]))}/"opencode-${{LOCALAI_PROFILE}}.json"\n'
            'localai start "$LOCALAI_PROFILE"\n' + f'exec {shlex.quote(str(desktop_app))} "$@"')
        desktop('OpenCode Desktop Local', str(p['bin'] / 'opencode-desktop-local'))
    # Comfy's extra search paths share one canonical model store, not symlinks in Git.
    media_roots = [p['models'] / 'Comfy-Org/Qwen-Image-2.1',
                   p['models'] / 'Comfy-Org/MiniMax-H3',
                   p['models'] / 'Comfy-Org/z_image_turbo/split_files']
    text = f'shared_canonical:\n  base_path: {json.dumps(str(p["data"] / "comfy-models"))}\n'
    for kind in ('diffusion_models', 'text_encoders', 'vae', 'loras', 'model_patches', 'latent_upscale_models', 'checkpoints'):
        text += f'  {kind}: {kind}\n'
    for i, base in enumerate(media_roots):
        text += f'shared_{i}:\n  base_path: {json.dumps(str(base))}\n'
        for kind in ('diffusion_models', 'text_encoders', 'vae', 'loras', 'model_patches', 'latent_upscale_models', 'checkpoints'):
            text += f'  {kind}: {kind}\n'
    text += f'wan_aio:\n  base_path: {json.dumps(str(p["models"] / "Phr00t/WAN2.2-14B-Rapid-AllInOne"))}\n  checkpoints: Mega-v12\n'
    (p['config'] / 'comfy-model-paths.yaml').write_text(text)
    unitdir = Path.home() / '.config/systemd/user'
    unitdir.mkdir(parents=True, exist_ok=True)
    (unitdir / 'localai@.service').write_text(
        '[Unit]\nDescription=Local AI profile %i\n[Service]\nType=simple\n'
        f'ExecStart={localai} serve %i\nEnvironment=PATH={p["bin"]}:/usr/local/bin:/usr/bin\n'
        'KillMode=control-group\nTimeoutStopSec=45\nRestart=no\n[Install]\nWantedBy=default.target\n')

def npm_version(package): return locked('npm:' + package, lambda: http(f'https://registry.npmjs.org/{package}/latest')['version'])

def harnesses():
    p = paths()
    os.environ['PATH'] = str(p['bin']) + os.pathsep + os.environ['PATH']
    for package in ('@earendil-works/pi-coding-agent', '@anthropic-ai/claude-code'):
        run(p['bin'] / 'npm', 'install', '--global', '--prefix', p['apps'] / 'node', package + '@' + npm_version(package))
    from configure_pi_labels import patch_picker
    patch_picker()
    release = locked('opencode_release', lambda: http('https://api.github.com/repos/anomalyco/opencode/releases/tags/v1.19.3'))
    asset = next(a for a in release['assets'] if a['name'] == 'opencode-linux-x64.tar.gz')
    extract(fetch(asset['browser_download_url'], asset['digest']), p['apps'] / 'opencode')
    # Extract AppImage without requiring FUSE or a system package install.
    asset = next(a for a in release['assets'] if a['name'] == 'opencode-desktop-linux-x86_64.AppImage')
    appimage = fetch(asset['browser_download_url'], asset['digest']); appimage.chmod(0o755)
    desktop_dir = p['apps'] / 'opencode-desktop'; desktop_dir.mkdir(exist_ok=True)
    run(appimage, '--appimage-extract', cwd=desktop_dir)
    write_configuration()
    hermes()
    write_configuration()

def hermes():
    p = paths()
    revision = locked('hermes_revision', lambda: http('https://api.github.com/repos/NousResearch/hermes-agent/commits/main')['sha'])
    dest = p['apps'] / 'hermes'
    clone('NousResearch/hermes-agent', revision, dest)
    run(p['bin'] / 'uv', 'python', 'install', '3.14')
    current = subprocess.run([str(dest / '.venv/bin/python'), '-c', 'import sys; print(sys.version_info.minor)'],
                             capture_output=True, text=True).stdout.strip() if (dest / '.venv/bin/python').exists() else ''
    if current != '14': run(p['bin'] / 'uv', 'venv', '--clear', '--python', '3.14', dest / '.venv')
    run(p['bin'] / 'uv', 'pip', 'install', '--python', dest / '.venv/bin/python', '-e', str(dest) + '[web]')
    write_configuration()

def engines(selected=('llama', 'gufo', 'kyojin')):
    p = paths()
    os.environ['PATH'] = str(p['bin']) + os.pathsep + os.environ['PATH']
    errors = []
    for engine in selected:
        try:
            if engine == 'llama':
                rev = locked('llama_revision', lambda: http('https://api.github.com/repos/ggml-org/llama.cpp/commits/master')['sha'])
                dest = p['apps'] / 'llama.cpp'; clone('ggml-org/llama.cpp', rev, dest)
                # Header-only prerequisite is not pulled by Arch's vulkan-headers.
                prefix = p['data'] / 'toolchains/vulkan-headers-prefix'
                if not Path('/usr/share/cmake/SPIRV-Headers').exists() and not (prefix / 'share/cmake/SPIRV-Headers').exists():
                    spirv = p['apps'] / 'SPIRV-Headers'
                    spirv_rev = locked('spirv_headers_revision', lambda: http('https://api.github.com/repos/KhronosGroup/SPIRV-Headers/commits/main')['sha'])
                    clone('KhronosGroup/SPIRV-Headers', spirv_rev, spirv)
                    run('cmake', '-S', spirv, '-B', spirv / 'build', '-DCMAKE_INSTALL_PREFIX=' + str(prefix))
                    run('cmake', '--install', spirv / 'build')
                # Vulkan is an independent GPU reference while Gufo/Kyojin use HIP.
                run('cmake', '-S', dest, '-B', dest / 'build', '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
                    '-DGGML_VULKAN=ON', '-DLLAMA_CURL=OFF', '-DLLAMA_BUILD_TESTS=OFF', '-DLLAMA_BUILD_EXAMPLES=ON',
                    '-DCMAKE_PREFIX_PATH=' + str(prefix), '-DCMAKE_CXX_FLAGS=-isystem ' + str(prefix / 'include'))
                run('cmake', '--build', dest / 'build', '--target', 'llama-server', 'llama-bench', '--parallel', '8')
                run(p['bin'] / 'uv', 'pip', 'install', '--python', p['apps'] / 'support/bin/python', '-e', dest / 'gguf-py')
            elif engine == 'gufo-native':
                dest = p['apps'] / 'gufo-source'
                clone('gufo-org/gufo', GUFO_REV, dest)
                # ROCm 7.2's host __noinline__ macro conflicts with GCC 16's
                # <format> attribute; parse the standard header before HIP.
                run('cmake', '--preset', 'release', '-DCMAKE_INSTALL_PREFIX=' + str(p['apps'] / 'gufo'),
                    '-DCMAKE_HIP_COMPILER=/opt/rocm/llvm/bin/clang++', '-DCMAKE_CXX_FLAGS=-include format', cwd=dest)
                run('cmake', '--build', '--preset', 'release', '--parallel', '4', cwd=dest)
                run('cmake', '--install', dest / 'build/release')
            elif engine == 'gufo':
                if not shutil.which('podman'): raise RuntimeError('podman missing; run install-system.sh')
                image = 'ghcr.io/gufo-org/toolboxes/gufo-runtime:latest'
                run('podman', 'pull', image)
                inspect = json.loads(subprocess.check_output(['podman', 'image', 'inspect', image]))[0]
                digest = inspect['RepoDigests'][0]
                locked('gufo_image', lambda: digest)
                clone('gufo-org/gufo', GUFO_REV, p['apps'] / 'gufo-source')
            else:
                dest = p['apps'] / 'kyojin'; clone('Yamz-Labs/kyojin', KYOJIN_REV, dest)
                if not (dest / '.venv/bin/python').exists(): run(p['bin'] / 'uv', 'venv', '--python', '3.12', dest / '.venv')
                run(p['bin'] / 'uv', 'pip', 'install', '--python', dest / '.venv/bin/python', '--pre', 'torch', 'rocm-sdk-devel',
                    '--index-url', 'https://rocm.nightlies.amd.com/v2/gfx1151/')
                run(p['bin'] / 'uv', 'pip', 'install', '--python', dest / '.venv/bin/python', '-r', dest / 'requirements.txt')
                run(p['bin'] / 'uv', 'pip', 'install', '--python', dest / '.venv/bin/python', 'pip', 'wheel', 'ninja')
                run('bash', '-c', 'source .venv/bin/activate; rocm-sdk init; export EXL3_ROCM_SDK=$(rocm-sdk path --root); source tools/strix_halo/env.sh; ./build.sh', cwd=dest)
            update_json(p['state'] / 'engine-installation.json', engine,
                        {'status': 'installed', 'time': time.time()})
        except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
            update_json(p['state'] / 'engine-installation.json', engine,
                        {'status': 'failed', 'error': str(error), 'time': time.time()})
            errors.append(f'{engine}: {error}'); print(errors[-1], file=sys.stderr, flush=True)
    if errors: raise RuntimeError('\n'.join(errors))

def media():
    p = paths()
    dest = p['apps'] / 'ComfyUI'
    revision = locked('comfy_revision', lambda: http('https://api.github.com/repos/Comfy-Org/ComfyUI/git/ref/tags/v0.42.1')['object']['sha'])
    clone('Comfy-Org/ComfyUI', revision, dest)
    env = p['apps'] / 'comfyui-env'
    if not (env / 'bin/python').exists(): run(p['bin'] / 'uv', 'venv', '--python', '3.12', env)
    run(p['bin'] / 'uv', 'pip', 'install', '--python', env / 'bin/python', '--pre', 'torch', 'torchvision', 'torchaudio',
        '--index-url', 'https://rocm.nightlies.amd.com/v2/gfx1151/')
    run(p['bin'] / 'uv', 'pip', 'install', '--python', env / 'bin/python', '-r', dest / 'requirements.txt')
    clone('Yasei-no-otoko/ComfyUI-RDNA35-Attention',
          '1314839f00937936a0ff9dc248e95703e69206f6', dest / 'custom_nodes/ComfyUI-RDNA35-Attention')
    write_configuration()
    workflows = p['state'] / 'comfyui/default/workflows'
    workflows.mkdir(parents=True, exist_ok=True)
    curated = ROOT / 'workflows/linux/ready'
    ready = workflows / 'Ready-to-use'
    ready.mkdir(exist_ok=True)
    for source in curated.glob('*.json'): shutil.copy2(source, ready / source.name)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for stage in ('tooling', 'harnesses', 'hermes', 'engines', 'media', 'all'): parser.add_argument('--' + stage, action='store_true')
    parser.add_argument('--models', nargs='+')
    parser.add_argument('--engine', choices=['llama', 'gufo', 'gufo-native', 'kyojin'], nargs='+', default=['llama', 'gufo', 'kyojin'])
    args = parser.parse_args()
    os.umask(0o077)
    for path in paths().values(): path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.environ['PATH'] = str(paths()['bin']) + os.pathsep + os.environ['PATH']
    os.environ['UV_CACHE_DIR'] = str(paths()['cache'] / 'uv')
    os.environ['HF_HOME'] = str(paths()['cache'] / 'huggingface')
    results = read_json(paths()['state'] / 'installation.json', {})
    actions = [(name, action) for name, action in [('tooling', tooling), ('harnesses', harnesses), ('engines', lambda: engines(args.engine)), ('media', media)] if args.all or getattr(args, name)]
    if args.models: actions.append(('models', lambda: download(args.models)))
    if args.hermes: actions.append(('hermes', hermes))
    if not actions: parser.error('Select --tooling, --harnesses, --engines, --media, --models GROUP, or --all')
    failed = False
    for name, action in actions:
        try:
            action(); results[name] = {'status': 'installed', 'time': time.time()}
        except Exception as error:
            failed = True
            results[name] = {'status': 'failed', 'error': str(error), 'time': time.time()}
            print(f'{name}: {error}', file=sys.stderr, flush=True)
        results = update_json(paths()['state'] / 'installation.json', name, results[name])
    print(json.dumps(results, indent=2))
    return int(failed)

if __name__ == '__main__': sys.exit(main())
