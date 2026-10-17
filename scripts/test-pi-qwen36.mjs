// End-to-end Pi SDK checks. Test-only compaction settings do not change production.
import { mkdirSync, appendFileSync, writeFileSync, readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const root = 'C:/Users/danfl/dev/LocalAI';
process.env.PI_CODING_AGENT_DIR = `${root}/config/pi`;
process.env.PI_CODING_AGENT_SESSION_DIR = `${root}/config/pi/sessions`;
const sdk = await import(pathToFileURL(`${root}/apps/PiHarness/runtime/pi-1.2.0/node_modules/@earendil-works/pi-coding-agent/dist/index.js`).href);
const { createAgentSession, SessionManager, SettingsManager, ModelRuntime } = sdk;
const out = `${root}/logs/pi-qwen36-functional`;
mkdirSync(out, { recursive: true });
const agentDir = `${root}/config/pi`;
const cwd = `${root}/workspaces/pi-qwen36-check`;
mkdirSync(cwd, { recursive: true });
const runtime = await ModelRuntime.create({ modelsPath: `${agentDir}/models.json`, authPath: `${agentDir}/auth.json` });
const model = runtime.getAllModels('strata').find(m => m.id === 'qwen3.6-35b-a3b-ud-q4_k_xl');
if (!model) throw new Error('Configured Qwen3.6 model not found');
const settings = JSON.parse(readFileSync(`${agentDir}/settings.json`, 'utf8'));
const results = [];
function observe(session, phase) {
  session.subscribe(event => {
    if (event.type === 'message_update') return;
    appendFileSync(`${out}/events.jsonl`, JSON.stringify({ phase, at: new Date().toISOString(), event }) + '\n');
    if (event.type.includes('compaction')) console.log(phase, event.type);
  });
}
async function ask(session, phase, prompt) {
  const start = performance.now();
  await session.prompt(prompt);
  const message = [...session.messages].reverse().find(m => m.role === 'assistant');
  const result = { phase, seconds: (performance.now() - start) / 1000, text: session.getLastAssistantText(), usage: message?.usage, stopReason: message?.stopReason, error: message?.errorMessage };
  results.push(result); console.log(JSON.stringify(result));
  writeFileSync(`${out}/results.json`, JSON.stringify(results, null, 2));
  if (message?.stopReason === 'error' || !result.text) throw new Error(`Pi ${phase} failed: ${JSON.stringify(result)}`);
}
const manager = SessionManager.create(cwd, `${out}/sessions`);
let session;
try {
  ({ session } = await createAgentSession({ cwd, agentDir, modelRuntime: runtime, model, thinkingLevel: 'off', sessionManager: manager }));
  observe(session, 'normal');
  await ask(session, 'normal', 'Remember the project codeword CEDAR-482. Reply with that codeword and a one-line C# Hello World. Do not use tools.');
  await ask(session, 'read-tool', 'Use the read tool to open README.md in this working directory. State the project codeword found in that file.');
  // Inject benign historical chat entries into this isolated test session, not a user session.
  // A lowered threshold proves automatic triggering without making the user wait for 80K tokens.
  await session.dispose();
  const historicalText = ('We are building a C# console viewer. Retain the project codeword CEDAR-482. The UI should show standard output and errors. ').repeat(45);
  for (let i = 0; i < 3; i++) manager.appendMessage({ role: 'user', content: `Background note ${i}: ${historicalText}`, timestamp: Date.now() });
  const compactSettings = SettingsManager.inMemory({ ...settings, compaction: { enabled: true, reserveTokens: model.contextWindow - 3000, keepRecentTokens: 1000 }, packages: [] });
  ({ session } = await createAgentSession({ cwd, agentDir, modelRuntime: runtime, model, thinkingLevel: 'off', settingsManager: compactSettings, sessionManager: manager, noTools: 'all' }));
  observe(session, 'automatic-compaction');
  await ask(session, 'automatic-compaction', 'What is our project codeword? Reply in one sentence.');
  const entries = manager.getEntries();
  const compactions = entries.filter(e => e.type === 'compaction');
  writeFileSync(`${out}/compactions.json`, JSON.stringify(compactions, null, 2));
  if (!compactions.length) throw new Error('Automatic compaction did not occur');
  const path = manager.getSessionFile();
  await session.dispose(); session = null;
  const restored = SessionManager.open(path);
  ({ session } = await createAgentSession({ cwd, agentDir, modelRuntime: runtime, model, thinkingLevel: 'off', sessionManager: restored, noTools: 'all' }));
  observe(session, 'resume');
  await ask(session, 'resume', 'After restoring this conversation, what is the project codeword? Reply in one sentence.');
  if (!session.getLastAssistantText().includes('CEDAR-482')) throw new Error('Resume lost the codeword');
  await ask(session, 'cached-follow-up', 'Reply with only the project codeword.');
  console.log('PASS: normal Pi response, automatic compaction, and persisted conversation resume.');
} finally {
  if (session) await session.dispose();
}
