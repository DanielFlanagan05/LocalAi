#!/usr/bin/env python3
"""Render the resumed acceptance ledger into a concise local HTML report."""
from datetime import datetime
from html import escape
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from localai import ROOT, paths, read_json


def main():
    folder = paths()['state'] / 'acceptance-resume-20261021'
    ledger = read_json(folder / 'concurrent-results.json', {})
    candidate = read_json(folder / 'gufo020/concurrent-results.json', {})
    rows = []
    first = folder / '32k.log'
    if first.exists() and first.read_text().strip():
        try: rows.append({'input_tokens': 32768, **json.loads(first.read_text())})
        except ValueError: pass
    rows += ledger.get('steps', [])
    rows += [{**r, 'candidate': True} for r in candidate.get('steps', [])]
    body = []
    for row in rows:
        raw = read_json(row.get('report', '/nonexistent'), {})
        samples = raw.get('telemetry', {}).get('samples', [])
        swap = max((s.get('runtime_process', {}).get('VmSwap', 0) for s in samples), default=0) / 2**20
        minimum = raw.get('telemetry', {}).get('minimum_available_bytes')
        runs = [r for worker in raw.get('results', []) for r in worker.get('runs', [])]
        inputs = ' / '.join(str(r['actual_input_tokens']) for r in runs)
        warm = ' / '.join(f"{r['warm_seconds']:.2f}s" for r in runs)
        fresh = []
        for run in runs:
            usage = run['warm_usage']
            cached = usage.get('prompt_tokens_details', {}).get('cached_tokens', usage.get('cached_tokens'))
            fresh.append(str(usage['prompt_tokens'] - cached) if cached is not None else 'not reported')
        checks = row.get('status', 'unknown')
        if swap > 64:
            checks += ' recall; REJECTED for swap'
        label = 'Gufo 0.20 / 16 GiB' if row.get('candidate') else 'Older pin / 26 GiB'
        body.append(f"<tr><td>{label}<br>{row['input_tokens']:,}</td><td>{escape(checks)}</td><td>{inputs}</td>"
                    f"<td>{raw.get('elapsed_seconds', 0):.1f}s</td><td>{warm}</td><td>{' / '.join(fresh)}</td>"
                    f"<td>{minimum/2**30 if minimum else 0:.1f} GiB</td><td>{swap:.1f} MiB</td></tr>")
    current = ledger.get('current')
    progress = f"{ledger.get('status', 'pending')}"
    if current:
        progress += f" — two sessions at {current['input_tokens']:,} tokens; elapsed {current.get('elapsed_seconds', 0)/60:.1f} minutes"
    if ledger.get('acceptance_status') == 'rejected':
        progress = 'Older pin / 26 GiB rejected for process swap at 200K; 225K stopped.'
    if candidate:
        progress += ' Candidate Gufo 0.20 / 16 GiB: ' + candidate['status']
        if candidate.get('current'):
            step = candidate['current']
            progress += f" — {step['input_tokens']:,} tokens per session, {step.get('elapsed_seconds',0)/60:.1f} minutes"
        if candidate.get('paused_by_user'):
            progress = 'PAUSED by user. No runtime or queued recovery remains active. ' + progress + ' (interrupted step is unqualified).'
    followups = read_json(folder / 'followup-results.json', {})
    followup_rows = []
    for row in followups.get('results', []):
        raw = read_json(row.get('report','/nonexistent'), {})
        notes = []
        if 'restored_seconds' in raw:
            usage = raw.get('restored_usage', {})
            cached = usage.get('cached_tokens', usage.get('prompt_tokens_details',{}).get('cached_tokens',0))
            notes.append(f"restart reply {raw['restored_seconds']:.2f}s, {cached:,} cached tokens")
        items = [raw, *raw.get('results', [])]
        for item in items:
            if item.get('reported_client_context_window'):
                notes.append(f"client context {item['reported_client_context_window']:,}")
            failed = [k for k,v in item.get('checks',{}).items() if v is False]
            if failed: notes.append('failed checks: ' + ', '.join(failed))
        suffix = ' — ' + '; '.join(notes) if notes else ''
        followup_rows.append(f"<li>{escape(row['label'])}: <b>{escape(row['status'])}</b>{escape(suffix)}</li>")
    followup_html = ''.join(followup_rows) or ('<li>Recovery queue cancelled before model jobs; wait for explicit resume.</li>'
        if followups.get('paused_by_user') else '<li>Harness and disk-restart follow-ups pending behind candidate acceptance.</li>')
    now = datetime.now(ZoneInfo('America/Detroit')).strftime('%B %d, %Y, %I:%M %p %Z')
    text = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Resumed LLM validation</title><style>body{{font:15px/1.6 system-ui,sans-serif;max-width:1100px;margin:30px auto;padding:0 22px;color:#18343c}}h1{{line-height:1.2}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:9px;text-align:left;border-bottom:1px solid #ddd}}th{{background:#edf5f3}}a{{color:#137568}}code{{overflow-wrap:anywhere}}.table{{overflow:auto}}</style></head><body>
<small>Updated {escape(now)}</small><h1>Existing LLM validation: resumed</h1>
<p><b>{escape(progress)}</b>. This report is a saved snapshot; reload after it is regenerated.</p>
<p>Qwen3.8-27B Q4 / Gufo, two independent sessions, 262144 total tokens each. Baseline: older pinned runtime and 26 GiB RAM cache. Candidate: installed Gufo 0.20 and 16 GiB RAM cache. Both use 40 GiB disk / 16 GiB staging. Production profile is preserved; candidate is separately named. This combined engine/cache change is not an isolated causal comparison. AC, firmware Performance, GPU auto. Each worker must recall only its own code and pass its warm continuation. Earlier single-session acceptance through 225K remains separate dated evidence.</p>
<div class="table"><table><thead><tr><th>Target / session</th><th>Result</th><th>Actual input, both sessions</th><th>Whole step</th><th>Warm replies</th><th>Warm fresh tokens</th><th>Min. available</th><th>Peak process swap</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>
<p>One repeat per worker. These are recall/isolation tests, not coding-quality or fresh-prefill benchmarks. Existing caches are not purged; inspect raw cached-token counts before comparing throughput. Two-second memory samples may miss peaks. Passing recall does not establish no-swap acceptance: the saved tolerance is 64 MiB of runtime-process swap. Larger values are rejected even if recall passes.</p>
<h2>Recovery follow-ups</h2><ul>{followup_html}</ul>
<p>Existing Pi/Hermes lifecycle passes are retained. OpenCode's ordinary CLI-created/resumed path is tested separately from its earlier failed API-to-CLI probe. Claude must report its declared client context window as well as pass recovery; see <a href="https://code.claude.com/docs/en/model-config#correct-the-window-for-a-gateway-or-custom-model-id">official custom-model context guidance</a>.</p>
<p>Long reliability tests remain gated on short acceptance. Halogen, media and removed-model downloads remain deferred. This is <b>not a claim that the complete original plan is finished</b>.</p>
<p>Private raw evidence: <code>{escape(str(folder))}</code> and <code>{escape(str(paths()['state'] / 'benchmarks'))}</code>.</p>
<p><a href="getting-started.html">Ready commands</a> · <a href="validation-status.md">Detailed history</a> · <a href="flow-z13-plan.md">Retained plan</a></p></body></html>'''
    destination = ROOT / 'docs/llm-validation-resumed.html'
    destination.write_text(text)
    print(destination)


if __name__ == '__main__': main()
