#!/usr/bin/env python3
"""Install curated native UI workflows; API graphs stay out of the UI sidebar."""
import shutil
from localai import ROOT, paths

def main():
    target = paths()['state'] / 'comfyui/default/workflows/Ready-to-use'
    target.mkdir(parents=True, exist_ok=True)
    sources = sorted((ROOT / 'workflows/linux/ready').glob('*.json'))
    if len(sources) != 4: raise RuntimeError('Four curated native workflows are required')
    for source in sources: shutil.copy2(source, target / source.name)
    print('Installed four curated native UI workflows.')

if __name__ == '__main__': main()
