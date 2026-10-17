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
const key = 'strata/qwen3.6-35b-a3b-ud-q4_k_xl';
const ws = new WebSocket('ws://127.0.0.1:8787/ws', { headers: { Authorization: `Bearer ${token}`, Origin: 'http://127.0.0.1:8787' } });
const timer = setTimeout(() => { ws.terminate(); process.exitCode = 1; }, 30000);
let sent = false;
ws.on('open', () => ws.send(JSON.stringify({ type: 'hello', clientId: prior.clientId })));
ws.on('error', e => { console.error(e.message); process.exitCode = 1; });
ws.on('message', raw => {
  const msg = JSON.parse(raw);
  if (msg.type === 'settings_state') {
    if (sent && msg.settings?.softCapByModel?.[key] === 80000 && msg.settings?.retryMaxAttempts === 0) {
      const result = { softCapByModel: msg.settings.softCapByModel, retryMaxAttempts: msg.settings.retryMaxAttempts };
      writeFileSync(`${out}/web-settings-verified.json`, JSON.stringify(result, null, 2));
      console.log(JSON.stringify(result)); ws.close();
    } else if (!sent) {
      sent = true;
      ws.send(JSON.stringify({ type: 'set_settings', softCapByModel: { ...msg.settings.softCapByModel, [key]: 80000 }, retryMaxAttempts: 0 }));
    }
  }
});
ws.on('close', () => clearTimeout(timer));
