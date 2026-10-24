#!/usr/bin/env python3
"""Show model names in Pi's picker, retaining API IDs and existing defaults."""
from pathlib import Path
import shutil
import time

from localai import paths, profiles, profile_display_name, read_json, save_json


def backup_file(path, folder):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copy2(path, folder / path.name)


def patch_picker():
    p = paths()
    dist = p['apps'] / 'node/lib/node_modules/@earendil-works/pi-coding-agent/dist'
    source_old = 'const modelText = isSelected ? theme.fg("accent", item.id) : item.id;'
    source_new = ('const modelLabel = item.provider === "localai" ? (item.model.name || item.id) : item.id;\n'
                  '            const modelText = isSelected ? theme.fg("accent", modelLabel) : modelLabel;')
    bundle_old = 'modelText=isSelected?theme.fg("accent",item.id):item.id,providerBadge='
    bundle_new = ('modelLabel=item.provider==="localai"?(item.model.name||item.id):item.id,'
                  'modelText=isSelected?theme.fg("accent",modelLabel):modelLabel,providerBadge=')
    targets = [(dist / 'modes/interactive/components/model-selector.js', source_old, source_new)]
    targets.extend((f, bundle_old, bundle_new) for f in (dist / 'bundle/chunks').glob('*.js')
                   if 'Model Name:' in f.read_text())
    if len(targets) != 2:
        raise RuntimeError('Pi packaging changed; inspect the picker before adapting this patch.')
    pending = []
    for file, old, new in targets:
        text = file.read_text()
        if new in text: continue
        if text.count(old) != 1:
            raise RuntimeError(f'Pi picker changed: expected one label expression in {file}')
        pending.append((file, text.replace(old, new)))
    backup = p['state'] / 'pi-label-backups' / str(time.time_ns())
    for file, text in pending:
        backup_file(file, backup)
        file.write_text(text)
    print(f'Pi picker: model-name labels ready ({len(pending)} files updated).')


def main():
    p = paths()
    registry = p['state'] / 'pi/models.json'
    data = read_json(registry)
    if not data: raise RuntimeError('Pi model registry is missing; install the harness first.')
    definitions = profiles()
    models = data['providers']['localai']['models']
    for model in models:
        if model['id'] in definitions:
            model['name'] = profile_display_name(model['id'], definitions[model['id']])
    # Validate/prepare both UI forms before updating the private registry.
    patch_picker()
    backup_file(registry, p['state'] / 'pi-label-backups' / str(time.time_ns()))
    save_json(registry, data)
    print(f'Updated {len(models)} local model labels; API IDs and settings unchanged.')


if __name__ == '__main__': main()
