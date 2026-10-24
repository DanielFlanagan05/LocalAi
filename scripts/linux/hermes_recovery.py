"""Run with Hermes' own interpreter: native CLI abort/compress/resume acceptance."""
import json
import sys
import threading
import time
from pathlib import Path

request = json.loads(Path(sys.argv[1]).read_text())
sys.path.insert(0, request['hermes'])
from cli import HermesCLI
from agent.interrupt_compat import request_hard_interrupt
from recovery_history import HISTORY

report = {'harness': 'hermes', 'status': 'running', 'checks': {}}
def save(): Path(request['report']).write_text(json.dumps(report, indent=2) + '\n')
def phase(name):
    report.update(phase=name, updated=time.time())
    save()
def make(resume=None):
    return HermesCLI(model=request['profile'], provider='custom', api_key='local-only',
        base_url='http://127.0.0.1:8080/v1', toolsets=[], resume=resume, verbose=False)
try:
    phase('initial-turn')
    cli = make()
    # Start from a real, durably saved turn so interruption can be resumed.
    answer = cli.chat('We are developing a synthetic Python CSV parser. Its public project label is CEDAR-HERMES-71923. Keep this public label in any session handoff. Confirm the identifier in your reply.')
    if not answer: raise RuntimeError('Initial Hermes chat returned no answer')
    stop = threading.Event()
    observed = []
    cli._streamed_text_this_turn = ''
    cli._reasoning_shown_this_turn = False
    def cancel():
        deadline = time.monotonic() + 120
        while not stop.wait(.1) and time.monotonic() < deadline:
            # Hermes exposes reasoning before final text. Both flags are set
            # by its stream callbacks, so either proves real generated output.
            if (getattr(cli, '_streamed_text_this_turn', '') or
                    getattr(cli, '_reasoning_shown_this_turn', False)) and cli.agent:
                observed.append(request_hard_interrupt(cli.agent, 'Synthetic acceptance stop'))
                return
    phase('stream-and-native-abort')
    thread = threading.Thread(target=cancel, daemon=True)
    thread.start()
    cli.chat('Explain in detail how to implement a robust Python CSV parser, including quoted newlines, escaped quotes, streaming, validation and test cases. Include Python examples.')
    stop.set(); thread.join(2)
    report['checks']['native_abort_requested_after_stream'] = bool(observed and observed[0])
    phase('recovery')
    answer = cli.chat('Cancel the previous explanation. For a project status reply, return only the public project label verbatim, without markdown or commentary.')
    report['checks']['recovery'] = (answer or '').strip() == 'CEDAR-HERMES-71923'
    phase('build-compaction-history')
    for prompt in HISTORY:
        cli.chat(prompt)
    before = len(cli.conversation_history)
    phase('native-compression')
    cli._manual_compress('/compress Preserve the public project label CEDAR-HERMES-71923.')
    report['before_messages'] = before
    report['after_messages'] = len(cli.conversation_history)
    report['checks']['compaction'] = report['after_messages'] < before
    report['session_id'] = cli.session_id
    phase('persistent-resume')
    restored = make(cli.session_id)
    answer = restored.chat('Return exactly the public project label saved in the handoff and nothing else.')
    report['checks']['persistent_resume'] = (answer or '').strip() == 'CEDAR-HERMES-71923'
    report['status'] = 'passed' if all(report['checks'].values()) else 'failed'
except Exception as error:
    report.update(status='failed', error=repr(error))
finally:
    report['limitations'] = 'Native CLI methods and saved-session resume, with manual compression of short synthetic history. Compaction checks message-count reduction, not token savings: a summary can expand a short history. Not natural 225K compaction or terminal key handling.'
    save()
print(json.dumps({'status': report['status'], 'report': request['report']}))
raise SystemExit(report['status'] != 'passed')
