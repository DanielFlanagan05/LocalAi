import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdirSync, unlinkSync, writeFileSync } from 'node:fs';
const root = 'C:\\Users\\danfl\\dev\\LocalAI';
const runtime = `${root}\\config\\strata\\runtime`;
const script = `${root}\\scripts\\manage-writer.ps1`;
const isWriter = (ctx: any) => ctx.model?.provider === 'lmstudio' && ctx.model?.id === 'dirty-shirley-9b-q4';
function manage(action: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn('powershell.exe', ['-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',script,'-Action',action], { windowsHide: true });
    let output = '';
    child.stdout.on('data', data => { output += data.toString(); });
    child.stderr.on('data', data => { output += data.toString(); });
    child.on('error', reject);
    child.on('exit', code => code === 0 ? resolve() : reject(new Error(output.slice(-3000))));
  });
}
export default function(pi: ExtensionAPI) {
  const active = `${runtime}\\writer.active.${randomUUID()}.json`;
  const clear = () => { try { unlinkSync(active); } catch {} };
  let previousTools: string[] | undefined;
  let used = false;
  const configure = (writer: boolean) => {
    if (writer) { previousTools ??= pi.getActiveTools(); pi.setActiveTools([]); }
    else if (previousTools) { pi.setActiveTools(previousTools); previousTools = undefined; }
  };
  pi.on('session_start', (_event, ctx) => configure(isWriter(ctx)));
  pi.on('model_select', (_event, ctx) => configure(isWriter(ctx)));
  pi.on('before_agent_start', async (_event, ctx) => {
    if (!isWriter(ctx)) return;
    configure(true);
    try {
      await manage('Load');
      used = true;
      mkdirSync(runtime, { recursive: true });
      writeFileSync(active, JSON.stringify({pid:process.pid, started:Date.now()}));
    } catch (error) { clear(); ctx.abort(); throw error; }
    return { systemPrompt: 'You are a creative writing and conversation assistant. Follow the user\'s writing instructions. You have no computer, file, or web tools. Do not claim to have executed actions.' };
  });
  pi.on('session_before_compact', async (_event, ctx) => { if (isWriter(ctx)) { await manage('Load'); used = true; } });
  pi.on('before_provider_request', (event, ctx) => {
    if (!isWriter(ctx)) return;
    const payload = event.payload as any;
    if (!Array.isArray(payload?.messages)) return;
    // Gemma 2's shipped template rejects system roles and does not implement tools.
    // Folding the small writing instruction into the first user message also keeps
    // Pi Web UI's 19K coding-tool preamble out of this model's native 8K window.
    const messages: any[] = [];
    let instruction = 'You are a creative writing and conversation assistant. You have no tools. Follow the user\'s writing instructions.';
    for (const message of payload.messages) {
      if (message.role === 'system' || message.role === 'developer') continue;
      if (message.role !== 'user' && message.role !== 'assistant') continue;
      const copy = { role: message.role, content: message.content ?? '' };
      if (message.tool_calls?.length) continue;
      if (copy.role === 'user' && instruction) {
        copy.content = `${instruction}\n\n${typeof copy.content === 'string' ? copy.content : JSON.stringify(copy.content)}`;
        instruction = '';
      }
      const previous = messages.at(-1);
      if (previous?.role === copy.role) previous.content = `${previous.content}\n\n${copy.content}`;
      else messages.push(copy);
    }
    const {tools, tool_choice, parallel_tool_calls, reasoning_effort, max_completion_tokens, ...rest} = payload;
    // The coding harness may reserve the entire small context before its large
    // coding prompt is replaced. Use this model's bounded output allowance.
    return {...rest, messages, max_tokens: 2048};
  });
  pi.on('agent_end', () => clear());
  pi.on('session_shutdown', async () => {
    clear();
    if (used) { try { await manage('Unload'); } catch {} } // An active peer keeps its model; idle TTL remains a fallback.
  });
  pi.registerCommand('writer-unload', {
    description: 'Unload the LM Studio writer model without deleting its conversations.',
    handler: async (_args, ctx) => {
      await manage('Unload');
      ctx.ui.notify('Writer model unloaded. Its next prompt reloads it automatically.', 'info');
    },
  });
}
