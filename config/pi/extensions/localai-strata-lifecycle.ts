import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdirSync, readFileSync, readdirSync, unlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const root = 'C:\\Users\\danfl\\dev\\LocalAI';
const runtime = join(root, 'config', 'strata', 'runtime');
const python = join(root, 'apps', 'Strata', '.venv', 'Scripts', 'python.exe');
const guard = join(root, 'scripts', 'strata-guard.py');
const ports: Record<string, number> = { iq2xs: 8081, qwen36: 8080 };
const providers: Record<string, string> = { strata: 'qwen36', 'strata-iq2xs': 'iq2xs' };
const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

async function api(key: string, path = '/health', method = 'GET', timeout = 1500) {
  try {
    const response = await fetch(`http://127.0.0.1:${ports[key]}${path}`, {
      method, headers: { 'Content-Type': 'application/json' },
      body: method === 'POST' ? '{}' : undefined, signal: AbortSignal.timeout(timeout),
    });
    if (!response.ok) return null;
    return await response.json();
  } catch { return null; }
}

function status(key: string) {
  try { return JSON.parse(readFileSync(join(runtime, `${key}.status.json`), 'utf8')); }
  catch { return null; }
}

function livePeers(key: string, own: string) {
  return readdirSync(runtime).filter(name => {
    if (!name.startsWith(`${key}.lease.`) || !name.endsWith('.json') || name === own) return false;
    try {
      const lease = JSON.parse(readFileSync(join(runtime, name), 'utf8'));
      process.kill(lease.pid, 0);
      return true;
    } catch { return false; }
  });
}

export default function (pi: ExtensionAPI) {
  const id = randomUUID();
  const used = new Set<string>();
  let closing = false;
  const leaseName = (key: string) => `${key}.lease.${id}.json`;

  async function release(key: string) {
    used.delete(key);
    try { unlinkSync(join(runtime, leaseName(key))); } catch {}
    if (livePeers(key, leaseName(key)).length) return;
    const result = await api(key, '/unload?wait=3', 'POST', 4500);
    // Leave a manually launched server alive but empty. Pi-owned servers end after
    // their final live lease disappears; the supervisor also detects abrupt Pi death.
    if (result && status(key)?.pi_owned) writeFileSync(join(runtime, `${key}.stop`), 'last Pi session closed');
  }

  async function ensureBackend(ctx: any) {
    const key = providers[String(ctx.model?.provider ?? '')];
    for (const previous of [...used]) if (previous !== key) {
      await release(previous);
      for (let i = 0; i < 20 && status(previous)?.state === 'running'; i++) await sleep(250);
    }
    if (!key || closing) return;
    // Keep LM Studio's small writing model mutually exclusive with large Strata
    // weights. Its manager refuses to interrupt a live writer request.
    try {
      const response = await fetch('http://127.0.0.1:1234/api/v0/models', { signal: AbortSignal.timeout(1500) });
      const studio = response.ok ? await response.json() as any : null;
      if (studio?.data?.some((model: any) => model.id === 'dirty-shirley-9b-q4' && model.state === 'loaded')) {
        await new Promise<void>((resolve, reject) => {
          const child = spawn('powershell.exe', ['-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',join(root,'scripts','manage-writer.ps1'),'-Action','Unload'], { windowsHide: true });
          let error = '';
          child.stderr.on('data', data => { error += data.toString(); });
          child.on('error', reject);
          child.on('exit', code => code === 0 ? resolve() : reject(new Error(error || 'Writer model could not unload safely.')));
        });
      }
    } catch (error: any) {
      // A stopped LM Studio server is normal. An unload refusal is not.
      if (error?.message && !/fetch failed|timeout|aborted/i.test(error.message)) throw error;
    }
    mkdirSync(runtime, { recursive: true });
    used.add(key);
    writeFileSync(join(runtime, leaseName(key)), JSON.stringify({ pid: process.pid, session: id, provider: ctx.model?.provider }));
    let health = await api(key);
    if (!health) {
      ctx.ui.notify('Starting Strata with desktop memory protection. Model loads on the first request.', 'info');
      const child = spawn(python, [guard, '--model', key, '--pi-owned'], {
        cwd: root, detached: true, stdio: 'ignore', windowsHide: true,
      });
      child.on('error', error => ctx.ui.notify(`Strata start failed: ${error.message}`, 'error'));
      child.unref();
      for (let i = 0; i < 40 && !health; i++) { await sleep(250); health = await api(key); }
    }
    if (!health || status(key)?.state !== 'running') {
      ctx.ui.notify('No guarded Strata server is ready. Close a legacy/other Strata server, or run stop-strata before retrying.', 'error');
      ctx.abort();
    }
  }

  pi.on('before_agent_start', async (_event, ctx) => ensureBackend(ctx));
  // Compaction can run before before_agent_start, including after resuming an
  // old conversation. Its summary request needs the same lazy backend startup.
  pi.on('session_before_compact', async (_event, ctx) => {
    await ensureBackend(ctx);
  });

  pi.on('before_provider_request', (event, ctx) => {
    if (ctx.model?.provider !== 'strata') return;
    const payload = event.payload as Record<string, any>;
    if (!payload || !Array.isArray(payload.messages)) return;
    // Qwen's template otherwise removes empty thinking delimiters from older
    // assistant turns. Its recurrent state cannot rewind across that change,
    // which forces a full prompt reread on every ordinary follow-up.
    return {
      ...payload,
      reasoning_effort: 'none',
      chat_template_kwargs: { ...payload.chat_template_kwargs, preserve_thinking: true },
    };
  });

  pi.on('agent_end', async (event, ctx) => {
    const last = [...event.messages].reverse().find((message: any) => message.role === 'assistant') as any;
    if (last?.stopReason === 'error') for (const key of [...used]) {
      const stopped = status(key);
      if (stopped?.state === 'stopped' && stopped?.reason) {
        ctx.ui.notify(`Strata ${key} stopped: ${stopped.reason}. The saved conversation is retained.`, 'error');
      }
      await release(key);
    }
  });

  pi.on('session_shutdown', async () => {
    closing = true;
    for (const key of [...used]) await release(key);
  });

  pi.registerCommand('exit', {
    description: 'Exit Pi cleanly, including session shutdown and Strata cleanup.',
    handler: async (_args, ctx) => {
      ctx.shutdown();
    },
  });

  pi.registerCommand('localai-unload', {
    description: 'Unload this Pi session’s Strata model, retaining its conversation.',
    handler: async (_args, ctx) => {
      for (const key of [...used]) await release(key);
      ctx.ui.notify('Released this session’s Strata lease. Other active Pi sessions are preserved.', 'info');
    },
  });
  pi.registerCommand('localai-status', {
    description: 'Show managed Strata resource-guard status.',
    handler: async (_args, ctx) => {
      for (const key of Object.keys(ports)) {
        const health = await api(key);
        const s = status(key);
        ctx.ui.notify(`${key}: ${health ? (health.loaded ? 'loaded' : 'unloaded') : 'stopped'}; guard ${s?.state ?? 'not started'}${s?.reason ? ` (${s.reason})` : ''}`, 'info');
      }
    },
  });
}
