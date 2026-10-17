import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
const root = 'C:/Users/danfl/dev/LocalAI';
const out = `${root}/logs/pi-qwen36-functional`;
const prior = JSON.parse(readFileSync(`${out}/web-last-snapshot.json`, 'utf8'));
const require = createRequire(`${root}/apps/PiWebUI/node_modules/pi-web-ui/package.json`);
const WebSocket = require('ws');
const decrypt = `Add-Type -AssemblyName System.Security; $h=[IO.File]::ReadAllText('${root}/config/pi-web-ui/auth-token.dpapi').Trim(); $b=New-Object byte[] ($h.Length/2); for($i=0;$i -lt $h.Length;$i+=2){$b[$i/2]=[Convert]::ToByte($h.Substring($i,2),16)}; [Text.Encoding]::Unicode.GetString([Security.Cryptography.ProtectedData]::Unprotect($b,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser))`;
const token = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', decrypt], { encoding: 'utf8', windowsHide: true }).stdout.trim();
if (!token) throw new Error('No web token');
const base = 'https://daniels-desktop.tail632a33.ts.net';
const headers = { Authorization: `Bearer ${token}` };
const unauth = await fetch(`${base}/`);
const page = await fetch(`${base}/`, { headers });
if (page.status !== 200 || unauth.status !== 401) throw new Error(`Unexpected authentication status ${unauth.status}/${page.status}`);
const html = await page.text();
const assets = [...html.matchAll(/(?:src|href)="([^"]+\.(?:js|css))"/g)].map(m => m[1]);
for (const asset of assets) {
  const r = await fetch(new URL(asset, base), { headers });
  if (!r.ok) throw new Error(`Remote asset failed: ${asset}`);
}
const start = Date.now();
const ws = new WebSocket(`${base.replace('https:', 'wss:')}/ws`, { headers: { ...headers, Origin: base } });
let sent = false, oldCount = 0;
const timer = setTimeout(() => { ws.terminate(); process.exitCode = 1; console.error('Remote prompt timed out'); }, 720000);
const poll = setInterval(() => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'get_state' })); }, 2500);
ws.on('open', () => ws.send(JSON.stringify({ type: 'hello', clientId: prior.clientId })));
ws.on('error', e => { console.error(e.message); process.exitCode = 1; });
ws.on('message', raw => {
  const msg = JSON.parse(raw);
  if (msg.type === 'notice') console.log('notice:', msg.textEn || msg.text);
  if (msg.type !== 'snapshot') return;
  const state = msg.state;
  if (!sent) {
    if (state.sessionId !== prior.sessionId || state.model?.provider !== 'strata') {
      console.error('Remote connection did not restore the local web conversation'); process.exitCode = 1; ws.close(); return;
    }
    oldCount = state.messages.filter(m => m.role === 'assistant').length;
    sent = true;
    ws.send(JSON.stringify({ type: 'prompt', text: 'What is our remembered codeword? Reply with only that codeword.' }));
    return;
  }
  const fresh = state.messages.filter(m => m.role === 'assistant').slice(oldCount);
  if (!state.isStreaming && fresh.some(m => m.stopReason === 'stop' && JSON.stringify(m.content).includes('WEB-482'))) {
    const result = { success: true, base, unauthenticatedStatus: unauth.status, authenticatedStatus: page.status, assetsChecked: assets.length, restoredSameSession: true, model: state.model, elapsedSeconds: (Date.now()-start)/1000, replies: fresh };
    writeFileSync(`${out}/tailscale-result.json`, JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result)); ws.close();
  }
});
ws.on('close', () => { clearInterval(poll); clearTimeout(timer); });
