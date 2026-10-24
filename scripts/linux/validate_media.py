#!/usr/bin/env python3
"""Validate ready graphs against installed node/model schemas on CPU."""
import asyncio
import json
import sys
from localai import ROOT, paths, save_json

def main():
    p=paths(); audit=p['state']/'comfyui-audit';audit.mkdir(parents=True,exist_ok=True)
    sys.argv=['validate-media','--cpu','--user-directory',str(audit)]
    sys.path.insert(0,str(p['apps']/'ComfyUI'))
    from utils.extra_config import load_extra_path_config
    load_extra_path_config(str(p['config']/'comfy-model-paths.yaml'))
    import nodes
    import execution
    async def validate():
        from server import PromptServer
        from app.assets.manager import NoAssets
        from comfy.cli_args import args
        PromptServer(asyncio.get_running_loop(),NoAssets(args))
        await nodes.init_extra_nodes(init_custom_nodes=True,init_api_nodes=False)
        rows=[]
        for path in sorted((ROOT/'workflows/linux/ready-api').glob('*.json')):
            result=await execution.validate_prompt('localai-ready-schema',json.loads(path.read_text()),None)
            rows.append({'model':path.stem,'passed':result[0],'error':result[1],'node_errors':result[3]})
        return rows
    rows=asyncio.run(validate())
    report={'status':'passed' if {r['model'] for r in rows} == {'chroma', 'h3', 'h3-euler-beta', 'qwen-image', 'wan-aio'} and all(r['passed'] for r in rows) else 'failed',
            'graphs':rows,'limitations':'Ready API graphs validated against installed node/model schemas on CPU, including the explicit custom attention node when present. This does not verify visual layout or frontend serialization. No model loading, generation or new quality testing.'}
    destination=p['state']/'ready-workflow-validation.json';save_json(destination,report)
    print(json.dumps({'status':report['status'],'report':str(destination)}))
    return int(report['status']!='passed')

if __name__=='__main__':raise SystemExit(main())
