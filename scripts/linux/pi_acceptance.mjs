// Exercise the installed Pi lifecycle implementation against a real local model.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';

const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const sdk = await import(pathToFileURL(join(input.apps, 'node/lib/node_modules/@earendil-works/pi-coding-agent/dist/index.js')).href);
const { createAgentSession, SessionManager, SettingsManager, ModelRuntime } = sdk;
const agentDir = input.agentDir;
process.env.PI_CODING_AGENT_DIR = agentDir;
const runtime = await ModelRuntime.create({ modelsPath: join(agentDir, 'models.json'), authPath: join(agentDir, 'auth.json'), allowModelNetwork: false });
const model = runtime.getAllModels('localai').find(m => m.id === input.profile);
if (!model) throw new Error('Profile missing from installed Pi model catalog');
mkdirSync(input.workspace, { recursive: true, mode: 0o700 });
const events = [];
const usage = [];
let session;
const report = { profile: input.profile, operation: input.operation, status: 'running', events, usage };
const save = () => writeFileSync(input.report, JSON.stringify(report, null, 2) + '\n', {mode: 0o600});
const longCoding = input.operation === 'coding' && input.paddingFile;
const testModel = { ...model, maxTokens: longCoding ? 8192 : 2048 };
report.testMaximumOutputTokens = testModel.maxTokens;
const settings = SettingsManager.inMemory({ packages: [], compaction: { enabled: true, reserveTokens: longCoding ? 16384 : 36864, keepRecentTokens: 12000 } });
async function open(manager, extra = {}) {
  const result = await createAgentSession({ cwd: input.workspace, agentDir, modelRuntime: runtime, model: testModel,
    thinkingLevel: 'off', sessionManager: manager, settingsManager: settings,
    ...(input.operation === 'coding' ? {} : { noTools: 'all' }), ...extra });
  session = result.session;
  session.subscribe(e => {
    if (e.type.includes('compaction')) events.push(e);
    if (e.type === 'message_end' && e.message?.role === 'assistant') usage.push(e.message.usage);
    if (input.operation !== 'coding' && e.type === 'message_update' && e.assistantMessageEvent?.type?.endsWith('_delta')) {
      report.lastDeltaPreview = String(e.assistantMessageEvent.delta || '').slice(-120);
      report.lastProgressAt = Date.now();
      if (!report.lastSavedAt || Date.now()-report.lastSavedAt>1000) { report.lastSavedAt=Date.now(); save(); }
    }
  });
  return session;
}
function exact(expected) {
  const text = session.getLastAssistantText()?.trim();
  if (text !== expected) throw new Error(`Expected exact ${expected}, received ${text?.slice(0, 300)}`);
  return text;
}
async function turn(text, phase) {
  report.phase=phase; save();
  let expired=false;
  const timer=setTimeout(()=>{ expired=true; session.abort(); }, longCoding ? 3600000 : 180000);
  try { await session.prompt(text); }
  finally { clearTimeout(timer); }
  if (expired) throw new Error(`Timed out during ${phase}`);
}
const watchdog = setTimeout(() => { save(); process.exit(124); }, input.timeoutMs || 1800000);
try {
  let manager = SessionManager.create(input.workspace, join(input.workspace, 'sessions'));
  if (input.operation === 'coding') {
    if (input.paddingFile) manager.appendMessage({ role: 'user', content: readFileSync(input.paddingFile, 'utf8'), timestamp: Date.now() });
    await open(manager);
    await session.prompt(input.prompt);
    report.text = session.getLastAssistantText();
    report.contextUsage = session.getContextUsage();
    report.sessionFile = manager.getSessionFile();
    const assistants = manager.getEntries().filter(e => e.type === 'message' && e.message.role === 'assistant');
    report.modelErrors = assistants.filter(e => ['error', 'aborted'].includes(e.message.stopReason)).map(e => ({stopReason:e.message.stopReason,errorMessage:e.message.errorMessage}));
    if (report.modelErrors.length) throw new Error('Agent recorded a model/transport error');
  } else {
    await open(manager);
    let abortIssued = false;
    let abortPromise;
    const unsubscribe = session.subscribe(e => {
      if (!abortIssued && e.type === 'message_update' && ['text_delta', 'thinking_delta'].includes(e.assistantMessageEvent?.type) && e.assistantMessageEvent.delta) {
        abortIssued = true;
        setTimeout(() => { abortPromise=session.abort(); }, 0);
      }
    });
    await turn('Explain in detail how to implement a robust Python CSV parser, including quoted newlines, escaped quotes, streaming, validation and test cases. Include Python examples.', 'stream-cancellation');
    await abortPromise;
    unsubscribe();
    report.abortIssued = abortIssued;
    if (!abortIssued) throw new Error('No streaming event observed before cancellation');
    await turn('Cancel the previous explanation. For a synthetic project status reply, return exactly CEDAR-RECOVERY-48271 and nothing else.', 'same-session-recovery');
    report.recovery = exact('CEDAR-RECOVERY-48271');
    const file = manager.getSessionFile();
    session.dispose();
    manager = SessionManager.open(file);
    for (let i=0; i<6; i++) manager.appendMessage({ role: 'user', content:
      `Historical planning note ${i}. Public project label: CEDAR-COMPACT-71923. Preserve this in any handoff.\n` +
      'The project retains public interfaces, validates inputs, and records completed work.\n'.repeat(100), timestamp: Date.now() });
    const forced = SettingsManager.inMemory({ packages: [], compaction: { enabled: true, reserveTokens: model.contextWindow - 1000, keepRecentTokens: 250 } });
    await open(manager, { settingsManager: forced });
    await turn('After any necessary summary, return exactly the public project label and nothing else.', 'automatic-compaction');
    report.afterCompaction = exact('CEDAR-COMPACT-71923');
    report.compactions = manager.getEntries().filter(e => e.type === 'compaction').length;
    if (!report.compactions) throw new Error('Forced automatic compaction did not persist a record');
    session.dispose();
    manager = SessionManager.open(file);
    await open(manager);
    await turn('Return exactly the public project label saved in the handoff, and nothing else.', 'persistent-resume');
    report.afterReopen = exact('CEDAR-COMPACT-71923');
    report.sessionFile = file;
    report.limitations = 'Native SDK stream abort, same-session recovery, forced low-threshold automatic compaction and disk-session reopening. Does not establish natural 225K compaction or terminal key handling.';
  }
  report.status = 'passed';
} catch (error) {
  report.status = 'failed'; report.error = String(error.stack || error);
  process.exitCode = 1;
} finally {
  session?.dispose(); clearTimeout(watchdog); save();
}
console.log(JSON.stringify({status: report.status, report: input.report}));
