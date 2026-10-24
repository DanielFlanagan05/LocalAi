#!/usr/bin/env python3
"""Register one existing profile in Pi/Hermes without regenerating defaults."""
import argparse
import re
import shlex
import shutil
import time

from localai import paths, profiles, profile_display_name, read_json, save_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=profiles())
    parser.add_argument('--suffix', required=True, help='Creates pi-SUFFIX and hermes-SUFFIX.')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', args.suffix):
        parser.error('suffix must contain lowercase letters, digits or hyphens')
    definition = profiles()[args.profile]
    if definition['engine'] == 'comfyui': parser.error('Choose an LLM profile.')
    p = paths()
    backup = p['state'] / 'profile-registration' / str(time.time_ns())

    def preserve(path):
        if path.is_file():
            backup.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(path, backup / path.name)

    registry = p['state'] / 'pi/models.json'
    data = read_json(registry, {'providers': {}})
    provider = data.setdefault('providers', {}).setdefault('localai', {
        'baseUrl': 'http://127.0.0.1:8080/v1', 'api': 'openai-completions', 'apiKey': 'local-only'})
    entry = {'id': args.profile, 'name': profile_display_name(args.profile, definition), 'reasoning': True,
             'input': ['text', 'image'] if definition.get('vision') else ['text'],
             'contextWindow': definition['context'], 'maxTokens': definition.get('max_output_tokens', 32768),
             'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}}
    provider['models'] = [m for m in provider.get('models', []) if m['id'] != args.profile] + [entry]
    preserve(registry)
    save_json(registry, data)

    hermes = p['state'] / 'hermes-profiles' / args.profile / 'config.yaml'
    hermes.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    text = (f'model:\n  default: {args.profile}\n  provider: custom\n'
            f'  base_url: http://127.0.0.1:8080/v1\n  context_length: {definition["context"]}\n'
            'compression:\n  enabled: true\n  threshold: 0.86\n'
            'auxiliary:\n  compression:\n    provider: custom\n'
            f'    base_url: http://127.0.0.1:8080/v1\n    model: {args.profile}\n')
    # Existing user preferences remain editable and are never replaced here.
    if not hermes.exists():
        hermes.write_text(text)
        hermes.chmod(0o600)

    for harness in ('pi', 'hermes'):
        destination = p['bin'] / f'{harness}-{args.suffix}'
        text = ('#!/usr/bin/env bash\nset -euo pipefail\n'
                f'export LOCALAI_PROFILE={shlex.quote(args.profile)}\n'
                f'exec {shlex.quote(str(p["bin"] / (harness + "-local")))} "$@"\n')
        preserve(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text)
        destination.chmod(0o755)
        print(f'Ready: {destination.name}')
    print('Existing defaults/settings preserved. Backups:', backup)


if __name__ == '__main__': main()
