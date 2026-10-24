#!/usr/bin/env python3
"""Create a Gufo-compatible chat-template copy; preserve every model tensor."""
import hashlib
from pathlib import Path
import subprocess
import sys

from gguf import GGUFReader
from localai import artifact, catalog, model_directory, paths, read_json, sha256, update_json

KEY = 'qwen35-hauhau-q4'


def main():
    definition = catalog()['models'][KEY]
    original = artifact(KEY)
    original_hash = sha256(original)
    if original_hash != definition['sha256'][definition['model']]:
        raise RuntimeError('Original model SHA-256 does not match the publisher artifact.')
    output = model_directory(KEY) / definition['runtime_model']
    output.parent.mkdir(parents=True, exist_ok=True)
    assert output != original
    reference = artifact('qwen27-q4')
    template = GGUFReader(str(reference)).fields['tokenizer.chat_template'].contents()
    template_hash = hashlib.sha256(template.encode()).hexdigest()
    if template_hash != definition['runtime_template_sha256']:
        raise RuntimeError('Reference chat template differs from the pinned Gufo-supported template.')
    manifest = paths()['state'] / 'derived-models.json'
    previous = read_json(manifest, {}).get(KEY, {})
    if (output.is_file() and previous.get('revision') == definition['revision']
            and previous.get('template_sha256') == template_hash
            and previous.get('sha256') == sha256(output)):
        print('Verified existing compatibility copy:', output)
        return
    template_file = output.parent / 'gufo-chat-template.jinja'
    template_file.write_text(template)
    temporary = output.with_suffix('.partial.gguf')
    subprocess.run([sys.executable, '-m', 'gguf.scripts.gguf_new_metadata',
                    str(original), str(temporary), '--chat-template-file', str(template_file), '--force'], check=True)
    source, adapted = GGUFReader(str(original)), GGUFReader(str(temporary))
    assert source.fields.keys() == adapted.fields.keys(), 'Metadata fields changed'
    for key in source.fields:
        if key != 'tokenizer.chat_template':
            assert repr(source.fields[key].contents()) == repr(adapted.fields[key].contents()), key
    assert len(source.tensors) == len(adapted.tensors)
    fingerprint = hashlib.sha256()
    for before, after in zip(source.tensors, adapted.tensors):
        assert (before.name, before.tensor_type, before.shape.tolist()) == (after.name, after.tensor_type, after.shape.tolist())
        digest = hashlib.sha256(before.data).hexdigest()
        assert digest == hashlib.sha256(after.data).hexdigest(), before.name
        fingerprint.update((before.name + ':' + digest + '\n').encode())
    assert adapted.fields['tokenizer.chat_template'].contents() == template
    temporary.replace(output)
    record = {'revision': definition['revision'], 'path': str(output), 'size': output.stat().st_size,
              'sha256': sha256(output), 'source_sha256': original_hash,
              'template_sha256': template_hash, 'template_source': str(reference),
              'tensor_count': len(source.tensors), 'tensor_fingerprint_sha256': fingerprint.hexdigest(),
              'all_tensors_identical': True, 'only_metadata_changed': 'tokenizer.chat_template'}
    update_json(manifest, KEY, record)
    print('Verified metadata-only compatibility copy:', output, flush=True)


if __name__ == '__main__': main()
