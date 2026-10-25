"""Concurrent vision requests through the gateway, using a synthetic form image.

Never uses real documents. Examples (run with the gateway venv python):
  vision-smoke-test.py --model cc-extract --concurrency 12 --requests 24
  vision-smoke-test.py --model cc-extract,cc-verify-a,cc-verify-b,cc-judge
"""
import argparse
import base64
import io
import json
import random
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CLUSTER = Path(__file__).resolve().parent.parent

SCHEMA = {
    'type': 'object',
    'properties': {
        'family_name': {'type': 'string'},
        'given_name': {'type': 'string'},
        'date_of_birth': {'type': 'string', 'description': 'MM/DD/YYYY'},
        'a_number': {'type': 'string', 'description': 'A-Number digits only'},
        'country_of_birth': {'type': 'string'},
    },
    'required': ['family_name', 'given_name', 'date_of_birth', 'a_number', 'country_of_birth'],
    'additionalProperties': False,
}


def load_master_key():
    for line in (CLUSTER / '.env').read_text().splitlines():
        if line.startswith('LITELLM_MASTER_KEY='):
            return line.split('=', 1)[1].strip()
    raise SystemExit('LITELLM_MASTER_KEY missing from cluster/.env; run the gateway setup first.')


def make_form(seed):
    rng = random.Random(seed)
    truth = {
        'family_name': rng.choice(['ALVAREZ', 'NGUYEN', 'OKAFOR', 'KOWALSKI', 'HASSAN']),
        'given_name': rng.choice(['MARIA', 'THANH', 'CHIDI', 'PIOTR', 'LAYLA']),
        'date_of_birth': f'{rng.randint(1, 12):02d}/{rng.randint(1, 28):02d}/{rng.randint(1960, 2005)}',
        'a_number': ''.join(str(rng.randint(0, 9)) for _ in range(9)),
        'country_of_birth': rng.choice(['MEXICO', 'VIETNAM', 'NIGERIA', 'POLAND', 'EGYPT']),
    }
    image = Image.new('RGB', (1700, 1100), 'white')
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype('arial.ttf', 34)
        small = ImageFont.truetype('arial.ttf', 24)
    except OSError:
        font = ImageFont.load_default(size=34)
        small = ImageFont.load_default(size=24)
    draw.text((80, 50), 'SAMPLE APPLICATION FORM (SYNTHETIC TEST DATA)', fill='black', font=font)
    labels = [('1.a. Family Name (Last Name)', 'family_name'), ('1.b. Given Name (First Name)', 'given_name'),
              ('2. Date of Birth (mm/dd/yyyy)', 'date_of_birth'), ('3. Alien Registration Number (A-Number)', 'a_number'),
              ('4. Country of Birth', 'country_of_birth')]
    for index, (label, key) in enumerate(labels):
        top = 170 + index * 170
        draw.text((80, top), label, fill='black', font=small)
        draw.rectangle((80, top + 40, 1620, top + 110), outline='black', width=3)
        value = f'A-{truth[key]}' if key == 'a_number' else truth[key]
        draw.text((100, top + 55), value, fill=(20, 20, 120), font=font)
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=90)
    return truth, base64.b64encode(buffer.getvalue()).decode()


def normalize(field, value):
    value = str(value).strip().upper()
    # The form prints "A-123456789"; models may or may not keep the prefix.
    return ''.join(ch for ch in value if ch.isdigit()) if field == 'a_number' else value


def call(gateway, key, model, image_b64, timeout):
    body = {
        'model': model,
        'temperature': 0,
        'max_tokens': 512,
        'response_format': {'type': 'json_schema', 'json_schema': {'name': 'form_fields', 'strict': True, 'schema': SCHEMA}},
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'Transcribe the form fields exactly as printed. Return JSON only.'},
            {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{image_b64}'}},
        ]}],
    }
    request = urllib.request.Request(f'{gateway}/v1/chat/completions', data=json.dumps(body).encode(),
                                     headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
            deployment = response.headers.get('x-litellm-model-id', '?')
    except urllib.error.HTTPError as error:
        return {'model': model, 'node': 'error', 'seconds': time.perf_counter() - started,
                'error': f'HTTP {error.code}: {error.read()[:300].decode(errors="replace")}'}
    except (urllib.error.URLError, TimeoutError) as error:
        return {'model': model, 'node': 'error', 'seconds': time.perf_counter() - started, 'error': str(error)}
    result = {'model': model, 'node': deployment, 'seconds': time.perf_counter() - started,
              'completion_tokens': payload.get('usage', {}).get('completion_tokens', 0)}
    try:
        result['fields'] = json.loads(payload['choices'][0]['message']['content'])
    except (KeyError, ValueError) as error:
        result['error'] = f'invalid JSON: {error}'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--gateway', default='http://127.0.0.1:4000')
    parser.add_argument('--model', default='cc-extract', help='comma-separated model names or aliases')
    parser.add_argument('--requests', type=int, default=0, help='requests per model (default: concurrency)')
    parser.add_argument('--concurrency', type=int, default=4)
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()

    key = load_master_key()
    models = [model.strip() for model in args.model.split(',') if model.strip()]
    per_model = args.requests or args.concurrency
    jobs = []
    for index in range(per_model):
        truth, image_b64 = make_form(seed=index)
        jobs.extend((model, truth, image_b64) for model in models)

    print(f'{len(jobs)} requests ({per_model} per model x {len(models)} model(s)), concurrency {args.concurrency}')
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda job: (call(args.gateway, key, job[0], job[2], args.timeout), job[1]), jobs))
    wall = time.perf_counter() - started

    print(f"\n{'model':<18} {'node':<24} {'secs':>6}  result")
    for result, truth in results:
        if 'error' in result:
            outcome = result['error']
        else:
            wrong = [field for field, value in truth.items() if normalize(field, result['fields'].get(field, '')) != value]
            outcome = 'all fields correct' if not wrong else f'mismatch: {", ".join(wrong)}'
            result['correct'] = not wrong
        print(f"{result['model']:<18} {result['node']:<24} {result['seconds']:>6.1f}  {outcome}")

    ok = [result for result, _ in results if 'error' not in result]
    serial = sum(result['seconds'] for result, _ in results)
    print(f'\nwall time {wall:.1f}s; sum of request times {serial:.1f}s; effective speedup {serial / wall:.1f}x')
    print(f'{len(ok)}/{len(results)} succeeded, {sum(1 for r in ok if r.get("correct"))} fully correct')
    print('requests per deployment: ' + ', '.join(f'{node}={count}' for node, count in
                                                  Counter(result['node'] for result, _ in results).most_common()))
    if len(models) > 1:
        # Agreement across models on the same image is what ClearCase's cross-checks will rely on.
        by_image = {}
        for result, truth in results:
            if 'fields' in result:
                by_image.setdefault(json.dumps(truth, sort_keys=True), []).append(json.dumps(result['fields'], sort_keys=True))
        agreeing = sum(1 for answers in by_image.values() if len(set(answers)) == 1 and len(answers) == len(models))
        print(f'images where all {len(models)} models agree exactly: {agreeing}/{per_model}')


if __name__ == '__main__':
    main()
