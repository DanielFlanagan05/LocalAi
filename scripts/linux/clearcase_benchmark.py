#!/usr/bin/env python3
"""ClearCase-compatible local vision evaluation, without changing its Windows sandbox."""
from __future__ import annotations
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import sys
import time

from localai import http, paths, profiles, save_json, start, sha256, error_detail, validation_metadata
ADAPTER_SHA256 = sha256(Path(__file__))

CONTEXTS = ['identity', 'current', 'former', 'at_birth', 'last_arrival', 'marriage_event', 'unknown']
ROLES = ['applicant', 'spouse', 'father', 'mother', 'parent', 'child', 'beneficiary', 'attorney', 'representative', 'interpreter', 'preparer', 'employer', 'unknown']
def obj(properties): return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}
def text(maximum=500, minimum=0): return {'type': 'string', 'minLength': minimum, 'maxLength': maximum}
def enum(values): return {'type': 'string', 'enum': values}
def schema():
    person = {'type': 'string', 'pattern': '^(person[0-9]{1,2}|unknown)$', 'minLength': 1, 'maxLength': 20}
    return obj({'document_type': enum(['passport', 'birth_certificate', 'marriage_certificate', 'immigration_record', 'address_record', 'employment_record', 'unknown']),
        'issuing_country': text(100), 'date_order': enum(['DMY', 'MDY', 'ISO', 'unknown']), 'date_order_evidence': text(100),
        'people': {'type': 'array', 'minItems': 1, 'maxItems': 30, 'items': obj({'id': person, 'role': enum(ROLES), 'role_evidence': text()})},
        'entries': {'type': 'array', 'maxItems': 100, 'items': obj({'label': text(500, 1), 'value': text(500, 1), 'evidence': text(500, 1),
            'subject': enum(['unknown']), 'person_id': person,
            'region': {'type': 'array', 'minItems': 4, 'maxItems': 4, 'items': {'type': 'number', 'minimum': 0, 'maximum': 1}},
            'context': enum(CONTEXTS)})}})

def normalize(value): return re.sub(r'[^a-z0-9]', '', str(value).casefold())

def score(answer, expected, visible_lines=()):
    from jsonschema import validate, ValidationError
    try: validate(answer, schema())
    except ValidationError: return {'schema_passed': False, 'exact_values': 0, 'expected_values': len(expected), 'unsupported_values': None}
    values = {normalize(e['value']) for e in answer['entries']}
    wanted = {normalize(v) for v in expected.values()}
    printed = [normalize(line) for line in visible_lines]
    unsupported = {value for value in values - wanted if not value or not any(value in line for line in printed)}
    return {'schema_passed': True, 'exact_values': len(values & wanted), 'expected_values': len(wanted),
            'unsupported_values': len(unsupported),
            # These fixtures intentionally print nationality, not an issuer.
            'unsupported_issuer': normalize(answer['issuing_country']) not in ('', 'unknown', 'none', 'na', 'notprinted', 'notavailable'),
            'unsupported_date_order': answer['date_order'] != 'unknown' or bool(answer['date_order_evidence'].strip()),
            'inferred_applicant_roles': sum(p['role'] == 'applicant' and not p['role_evidence'] for p in answer['people'])}

def fixtures(directory):
    from PIL import Image, ImageDraw, ImageFont
    font_path = Path('/usr/share/fonts/TTF/DejaVuSans.ttf')
    if not font_path.exists():
        font_path = next(iter(Path('/usr/share/fonts').rglob('DejaVuSans.ttf')), None)
    font = ImageFont.truetype(str(font_path), 44) if font_path else ImageFont.load_default(size=40)
    records = [
        {'name': 'passport-synthetic', 'title': 'SYNTHETIC TEST PASSPORT', 'values': {'Given Names': 'CEDAR AVERY', 'Surname': 'RIVER', 'Passport Number': 'TEST482710', 'Date of Birth': '17/09/1992', 'Nationality': 'EXAMPLELAND'}},
        {'name': 'blank-surname', 'title': 'SYNTHETIC TEST IDENTITY RECORD', 'values': {'Given Names': 'CEDAR AVERY', 'Document Number': 'TEST738291', 'Date of Birth': '07/11/1992'}, 'blank_surname': True},
        {'name': 'mixed-roles', 'title': 'SYNTHETIC FAMILY RECORD', 'values': {'Applicant': 'CEDAR RIVER', 'Spouse': 'MAPLE STONE', 'Father': 'ALDER RIVER', 'Reference Number': 'TEST928173'}},
        {'name': 'address-contexts', 'title': 'SYNTHETIC ADDRESS RECORD', 'values': {'Name': 'CEDAR RIVER', 'Current Address': '123 CEDAR ROAD', 'Former Address': '987 MAPLE LANE', 'Reference Number': 'TEST192837'}}]
    result = []
    for record in records:
        image = Image.new('RGB', (1800, 1600), 'white')
        draw = ImageDraw.Draw(image)
        draw.text((90, 80), record['title'], fill='black', font=font)
        y = 250
        for label, value in record['values'].items():
            draw.text((100, y), f'{label}: {value}', fill='black', font=font); y += 160
        if record.get('blank_surname'): draw.text((100, y), 'Surname:', fill='black', font=font)
        file = directory / f'{record["name"]}.png'
        image.save(file)
        result.append({**record, 'image': file})
    return result

def infer(base, model, fixture, prompt, structured):
    data = base64.b64encode(fixture['image'].read_bytes()).decode()
    payload = {'model': model, 'temperature': 0, 'max_tokens': 4096, 'stream': False, 'cache_prompt': False,
        'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': prompt},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + data}}]}],
        'chat_template_kwargs': {'enable_thinking': False, 'preserve_thinking': True}}
    if structured:
        payload['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'clearcase_page', 'strict': True, 'schema': schema()}}
    begin = time.perf_counter()
    response = http(base + '/chat/completions', payload, timeout=1800)
    content = response['choices'][0]['message'].get('content') or ''
    # Refuse explanatory prose or truncated JSON instead of extracting plausible fragments.
    content = content.strip()
    if content.startswith('```json') and content.endswith('```'): content = content[7:-3].strip()
    visible = [fixture['title'], *[f'{label}: {value}' for label, value in fixture['values'].items()]]
    if fixture.get('blank_surname'): visible.append('Surname:')
    try:
        parsed = json.loads(content)
        # Only the generated synthetic pages are accepted by this runner.
        # Keep their visible JSON answers private for auditing/re-scoring.
        save_json(fixture['image'].with_suffix('.response.json'), parsed)
        result = score(parsed, fixture['values'], visible)
    except (ValueError, TypeError): result = {'schema_passed': False, 'exact_values': 0, 'expected_values': len(fixture['values']), 'unsupported_values': None}
    return {'fixture': fixture['name'], 'seconds': time.perf_counter() - begin, 'usage': response.get('usage', {}),
            'finish_reason': response['choices'][0].get('finish_reason'), **result}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'dev/ClearCase')
    parser.add_argument('--profile', choices=profiles(), default='vision-clearcase')
    parser.add_argument('--workers', type=int, choices=[1, 2, 4], default=2)
    parser.add_argument('--base-url', default='http://127.0.0.1:8080/v1')
    parser.add_argument('--no-start', action='store_true')
    parser.add_argument('--prompt-only-schema', action='store_true', help='For engines without constrained JSON; report is labelled accordingly.')
    parser.add_argument('--variants', nargs='+', choices=['original', 'low', 'high', 'rotated', 'crop'], default=['original'])
    args = parser.parse_args()
    if not profiles()[args.profile].get('vision'): parser.error('Select a vision-enabled profile')
    if args.workers > profiles()[args.profile]['sessions']: parser.error('workers exceed profile session capacity')
    tools = args.repo / 'tools/i485-inventory'
    if not (tools / 'accuracy_pipeline.py').is_file(): parser.error('ClearCase repository not found')
    sys.path.insert(0, str(tools))
    sys.dont_write_bytecode = True  # Observation must not create files in ClearCase.
    from accuracy_pipeline import transcription_prompt
    prompt = transcription_prompt(1, 1, 1)
    if not args.no_start: start(args.profile)
    destination = paths()['state'] / 'clearcase' / str(int(time.time()))
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    cases = fixtures(destination)
    from PIL import Image
    expanded = []
    for case in cases:
        for variant in dict.fromkeys(args.variants):
            if variant == 'original':
                expanded.append({**case, 'render_variant': variant}); continue
            with Image.open(case['image']) as original:
                if variant == 'low': bitmap = original.resize((900, 800), Image.Resampling.LANCZOS)
                elif variant == 'high': bitmap = original.resize((3600, 3200), Image.Resampling.LANCZOS)
                elif variant == 'rotated': bitmap = original.rotate(90, expand=True, fillcolor='white')
                else:
                    from PIL import ImageChops
                    bounds = ImageChops.difference(original, Image.new('RGB', original.size, 'white')).getbbox()
                    bitmap = original.crop((max(0,bounds[0]-40),max(0,bounds[1]-40),min(original.width,bounds[2]+40),min(original.height,bounds[3]+40)))
                path = destination / f'{case["name"]}-{variant}.png'
                bitmap.save(path)
            expanded.append({**case, 'name': case['name'] + '-' + variant, 'image': path, 'render_variant': variant})
    cases = expanded
    report = {'status': 'running', 'profile': args.profile, 'workers': args.workers,
        **validation_metadata(args.profile),
        'adapter_sha256': ADAPTER_SHA256,
        'schema_mode': 'prompt-only' if args.prompt_only_schema else 'constrained', 'render_variants': args.variants,
        'clearcase_revision': __import__('subprocess').check_output(['git', '-C', str(args.repo), 'rev-parse', 'HEAD'], text=True).strip(),
        'results': [], 'limitations': 'Synthetic page transcription only. Does not validate real-document accuracy, form mapping, crop/OCR rereading, or the Windows AppContainer production path.'}
    save_json(destination / 'results.json', report)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(infer, args.base_url, args.profile, case, prompt, not args.prompt_only_schema) for case in cases]
        results = []
        for case, future in zip(cases, futures):
            try: results.append(future.result())
            except Exception as error: results.append({'fixture': case['name'], 'error_type': type(error).__name__, 'error': error_detail(error)})
            report['results'] = results
            save_json(destination / 'results.json', report)
    passed = all(r.get('schema_passed') and r['exact_values'] == r['expected_values'] and r['unsupported_values'] == 0 and
                 not r.get('unsupported_issuer') and not r.get('unsupported_date_order') and r.get('inferred_applicant_roles', 0) == 0 for r in results)
    report['status'] = 'passed' if passed else 'failed'
    save_json(destination / 'results.json', report)
    print(json.dumps({'status': report['status'], 'report': str(destination / 'results.json')}, indent=2))
    return int(not passed)

if __name__ == '__main__': raise SystemExit(main())
