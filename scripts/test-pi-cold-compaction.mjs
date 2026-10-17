import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const root = 'C:/Users/danfl/dev/LocalAI';
process.env.PI_CODING_AGENT_DIR = `${root}/config/pi`;
const { createAgentSession, SessionManager, SettingsManager, ModelRuntime } = await import(pathToFileURL(`${root}/apps/PiHarness/runtime/pi-1.2.0/node_modules/@earendil-works/pi-coding-agent/dist/index.js`).href);
const out = `${root}/logs/pi-qwen36-functional`;
const cwd = `${root}/workspaces/pi-qwen36-check`;
const agentDir = `${root}/config/pi`;
const cold = await fetch('http://127.0.0.1:8080/health').then(() => false).catch(() => true);
if (!cold) throw new Error('Test requires the old Pi-owned backend to have stopped');
const files = readdirSync(`${out}/sessions`).filter(n => n.endsWith('.jsonl')).map(n => `${out}/sessions/${n}`).sort((a,b) => statSync(b).mtimeMs-statSync(a).mtimeMs);
const manager = SessionManager.open(files[0]);
const before = manager.getEntries().filter(e => e.type === 'compaction').length;
// Ensure there is an older span to summarize; Pi correctly avoids re-compacting
// an already-short retained tail merely because a test threshold was lowered.
for (let i = 0; i < 3; i++) manager.appendMessage({ role: 'user', content: `Historical note ${i}: ` + ('Retain CEDAR-482. The C# viewer should show standard output and errors. ').repeat(40), timestamp: Date.now() });
const runtime = await ModelRuntime.create({ modelsPath: `${agentDir}/models.json`, authPath: `${agentDir}/auth.json` });
const model = runtime.getAllModels('strata').find(m => m.id === 'qwen3.6-35b-a3b-ud-q4_k_xl');
const settings = SettingsManager.inMemory({ ...JSON.parse(readFileSync(`${agentDir}/settings.json`, 'utf8')), packages: [], compaction: { enabled: true, reserveTokens: model.contextWindow-500, keepRecentTokens: 250 } });
const events = [];
const { session } = await createAgentSession({ cwd, agentDir, modelRuntime: runtime, model, thinkingLevel: 'off', sessionManager: manager, settingsManager: settings, noTools: 'all' });
console.log('Resolved test compaction:', JSON.stringify(session.settingsManager.getCompactionSettings(model)));
try {
  session.subscribe(e => { if (e.type.includes('compaction')) { events.push(e); console.log(e.type); } });
  await session.prompt('After your automatic summary, reply with the project codeword CEDAR-482.');
  const text = session.getLastAssistantText();
  const after = manager.getEntries().filter(e => e.type === 'compaction').length;
  const result = { coldBackendAtStart: cold, compactionsBefore: before, compactionsAfter: after, text, events };
  writeFileSync(`${out}/cold-compaction-result.json`, JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ coldBackendAtStart: cold, compactionsBefore: before, compactionsAfter: after, text }));
  if (after <= before || !text?.includes('CEDAR-482')) throw new Error('Cold compaction/resume failed');
} finally { session.dispose(); }
