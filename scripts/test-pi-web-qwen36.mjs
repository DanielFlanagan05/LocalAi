import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import { mkdirSync, appendFileSync, writeFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
const root = 'C:/Users/danfl/dev/LocalAI';
const require = createRequire(`${root}/apps/PiWebUI/node_modules/pi-web-ui/package.json`);
const WebSocket = require('ws');
const out = `${root}/logs/pi-qwen36-functional`;
mkdirSync(out, { recursive: true });
// Decrypt the existing secret into process memory only; never log it.
const decrypt = `Add-Type -AssemblyName System.Security; $h=[IO.File]::ReadAllText('${root}/config/pi-web-ui/auth-token.dpapi').Trim(); $b=New-Object byte[] ($h.Length/2); for($i=0;$i -lt $h.Length;$i+=2){$b[$i/2]=[Convert]::ToByte($h.Substring($i,2),16)}; [Text.Encoding]::Unicode.GetString([Security.Cryptography.ProtectedData]::Unprotect($b,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser))`;
const token = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', decrypt], { encoding: 'utf8', windowsHide: true }).stdout.trim();
if (!token) throw new Error('No web login token available');
const headers = { Authorization: `Bearer ${token}` };
const unauth = await fetch('http://127.0.0.1:8787/');
const index = await fetch('http://127.0.0.1:8787/', { headers });
if (!index.ok) throw new Error(`Authenticated UI returned ${index.status}`);
const html = await index.text();
const assets = [...html.matchAll(/(?:src|href)="([^"]+\.(?:js|css))"/g)].map(m => m[1]);
for (const asset of assets) {
  const r = await fetch(new URL(asset, 'http://127.0.0.1:8787/'), { headers });
  if (!r.ok) throw new Error(`UI asset failed ${asset}: ${r.status}`);
}
const health = await (await fetch('http://127.0.0.1:8787/api/health', { headers })).json();
writeFileSync(`${out}/web-health.json`, JSON.stringify({ health, unauthenticatedStatus: unauth.status, authenticatedStatus: index.status, assets }, null, 2));
const clientId = `localai-functional-${randomUUID()}`;
const ws = new WebSocket('ws://127.0.0.1:8787/ws', { headers: { ...headers, Origin: 'http://127.0.0.1:8787' } });
let state;
let sent = false;
let originalConversation;
let newChatRequested = false;
let assistantStartCount = 0;
let phase = 0;
let followUpStarted;
const answers = [];
let lastChange = Date.now();
const start = Date.now();
const timer = setTimeout(() => { console.error('Web prompt timed out'); ws.terminate(); process.exitCode = 1; }, 720000);
ws.on('open', () => ws.send(JSON.stringify({ type: 'hello', clientId })));
ws.on('error', e => { clearTimeout(timer); console.error(e.message); process.exitCode = 1; });
ws.on('message', raw => {
  const msg = JSON.parse(raw);
  appendFileSync(`${out}/web-events.jsonl`, JSON.stringify(msg) + '\n');
  if (msg.type === 'notice') console.log('notice:', msg.textEn || msg.text);
  if (msg.type === 'snapshot') {
    state = msg.state;
    writeFileSync(`${out}/web-last-snapshot.json`, JSON.stringify(state, null, 2));
    if (!newChatRequested) {
      originalConversation = state.conversationId;
      newChatRequested = true;
      ws.send(JSON.stringify({ type: 'new_chat' }));
      return;
    }
    if (!sent && state.conversationId === originalConversation) return;
    if (!sent) {
      console.log('Web session model:', JSON.stringify(state.model));
      if (state.model?.provider !== 'strata' || state.model?.id !== 'qwen3.6-35b-a3b-ud-q4_k_xl') {
        console.error('Wrong model selected in web session'); process.exitCode = 1; ws.close(); return;
      }
      sent = true;
      assistantStartCount = state.messages?.filter(m => m.role === 'assistant').length ?? 0;
      ws.send(JSON.stringify({ type: 'prompt', text: 'Remember the codeword WEB-482. Do not use tools. Reply exactly: WEB-QWEN36-OK' }));
    }
    const expected = phase === 0 ? 'WEB-QWEN36-OK' : 'WEB-482';
    const found = state.messages?.filter(m => m.role === 'assistant').slice(assistantStartCount).some(m => JSON.stringify(m).includes(expected));
    if (found && !state.isStreaming && !state.streaming) {
      if (phase === 0) {
        answers.push({ phase: 'first-response', elapsedSeconds: (Date.now()-start)/1000 });
        phase = 1; followUpStarted = Date.now();
        assistantStartCount = state.messages.filter(m => m.role === 'assistant').length;
        ws.send(JSON.stringify({ type: 'prompt', text: 'What is the codeword I asked you to remember? Reply with only that codeword.' }));
        return;
      }
      answers.push({ phase: 'follow-up', seconds: (Date.now()-followUpStarted)/1000 });
      writeFileSync(`${out}/web-result.json`, JSON.stringify({ success: true, elapsedSeconds: (Date.now()-start)/1000, answers, model: state.model, messages: state.messages }, null, 2));
      console.log('PASS: authenticated Pi Web UI -> Strata -> Qwen3.6 Q4 response.');
      clearTimeout(timer); ws.close();
    }
  }
});
const poll = setInterval(() => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'get_state' })); }, 3000);
ws.on('close', () => { clearInterval(poll); clearTimeout(timer); });
