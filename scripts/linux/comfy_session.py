#!/usr/bin/env python3
"""Foreground ComfyUI session with ownership-aware Ctrl-C and explicit stop."""
import argparse
import signal
import subprocess
import time
from localai import running, start, stop, profiles

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--detach', action='store_true', help='Leave ComfyUI running after this command exits.')
    parser.add_argument('--cached', action='store_true', help='Faster single-model repeats; restart ComfyUI before switching model families.')
    args = parser.parse_args()
    if args.stop:
        current = running('comfyui')
        if current and profiles()[current['profile']]['engine'] == 'comfyui': stop(current['profile']); print('ComfyUI stopped.')
        else: print('ComfyUI is already stopped; other model servers were left alone.')
        return
    owner = None
    profile = 'comfyui-cached' if args.cached else 'comfyui'
    began = time.time()
    def interrupt(*_): raise KeyboardInterrupt
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    try:
        owner = start(profile)
        if args.cached:
            print('Cached mode: restart ComfyUI before switching model families to release retained weights.', flush=True)
        print('ComfyUI: http://127.0.0.1:8188\nWorkflows → Ready-to-use → choose a workflow → edit prompt → Run.', flush=True)
        if not args.no_browser:
            subprocess.Popen(['xdg-open', 'http://127.0.0.1:8188'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if args.detach:
            print('Detached. Stop later with: stop-comfyui', flush=True)
            return
        print('Keep this terminal open. Ctrl-C stops ComfyUI; stop-comfyui works from any other terminal.', flush=True)
        while True:
            current = running('comfyui')
            if not current or (current['pid'], current['identity']) != (owner['pid'], owner['identity']): break
            time.sleep(.4)
    except KeyboardInterrupt:
        print('\nStopping ComfyUI…', flush=True)
    finally:
        if not args.detach:
            current = running('comfyui')
            same_owner = current and owner and (current['pid'], current['identity']) == (owner['pid'], owner['identity'])
            startup_interrupted = current and not owner and current['profile'] == profile and current['started'] >= began
            if same_owner or startup_interrupted: stop(current['profile'])

if __name__ == '__main__': main()
