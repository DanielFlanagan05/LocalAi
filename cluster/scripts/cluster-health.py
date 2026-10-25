"""Show the state of every vision-cluster node and the gateway.

Reads the deployment list from cluster/gateway/litellm-config.yaml so there is one source
of truth for the topology. Run with the gateway venv: bin\\vision-cluster-health.cmd
"""
import json
import urllib.error
import urllib.request
from pathlib import Path

import yaml

CLUSTER = Path(__file__).resolve().parent.parent
GATEWAY = 'http://127.0.0.1:4000'


def load_env():
    env = {}
    env_path = CLUSTER / '.env'
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip()
    return env


def get_json(url, key=None, timeout=3):
    request = urllib.request.Request(url, headers={'Authorization': f'Bearer {key}'} if key else {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def node_status(api_base, key):
    root = api_base.removesuffix('/v1')
    try:
        health = get_json(f'{root}/health').get('status', '?')
    except urllib.error.HTTPError as error:
        # llama-server answers 503 while the model is still loading.
        return 'loading' if error.code == 503 else f'HTTP {error.code}', '-'
    except (urllib.error.URLError, TimeoutError, OSError):
        return 'offline', '-'
    try:
        slots = get_json(f'{root}/slots', key)
        busy = sum(1 for slot in slots if slot.get('is_processing'))
        return health, f'{busy}/{len(slots)} busy'
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return health, 'unknown'


def main():
    env = load_env()
    config = yaml.safe_load((CLUSTER / 'gateway' / 'litellm-config.yaml').read_text())
    node_key = env.get('CLUSTER_API_KEY')

    rows = []
    for deployment in config['model_list']:
        api_base = deployment['litellm_params']['api_base']
        status, slots = node_status(api_base, node_key)
        rows.append((deployment['model_info']['id'], status, slots, api_base))

    width = max(len(row[0]) for row in rows)
    print(f"{'deployment':<{width}}  {'status':<8}  {'slots':<10}  endpoint")
    for deployment_id, status, slots, api_base in rows:
        print(f'{deployment_id:<{width}}  {status:<8}  {slots:<10}  {api_base}')

    try:
        get_json(f'{GATEWAY}/health/liveliness')
        gateway = 'running'
    except (urllib.error.URLError, TimeoutError, OSError):
        gateway = 'not running (bin\\start-vision-gateway.cmd)'
    print(f'\ngateway {GATEWAY}/v1: {gateway}')
    aliases = config['router_settings'].get('model_group_alias', {})
    print('aliases: ' + ', '.join(f'{alias} -> {group}' for alias, group in aliases.items()))


if __name__ == '__main__':
    main()
