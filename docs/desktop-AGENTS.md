# Agent instructions for the desktop dev folder

This file belongs in the **parent folder of the LocalAi checkout on the desktop** (`Daniels-Desktop`,
Windows 11, Radeon 7900 XT with 20 GB VRAM). The source copy is `LocalAi/docs/desktop-AGENTS.md`;
update it there and copy it again after a pull. Claude Code loads `CLAUDE.md`, so the dev folder
also needs a `CLAUDE.md` with the single line `@AGENTS.md`.

## The Flow Z13 accepts remote work

The ASUS ROG Flow Z13 (`flowz13`, CachyOS, Strix Halo, 128 GB unified memory with about 112 GiB
usable as GPU memory) is set up to take tasks from this desktop over Tailscale:

- **SSH:** `ssh flowz13` (user `danfl`, key-only, `flowz13.tail632a33.ts.net`). Claude Code is on
  the PATH there (`/home/danfl/.local/bin/claude`) and logged in.
- **Remote Control:** an always-on session named **z13** in the Code tab of claude.ai/code and the
  Claude app, for interactive work the user wants to watch or steer.
- **Default working folder:** `/home/danfl/dev/LocalAi`. Its local models, the `pi` / `hermes`
  launchers and the `localai` CLI live there; see that repo's `README.md` and `docs/`.

## When to route a request to the Z13

Route to the Z13 **without asking** when the user:

- says to route, send, run or do it "on the z13" or "on flowz13";
- asks for **Qwen Flash-Next** (also written "Qwen 3.8 Flash Next", "Flash-Next", `pi`, `hermes`,
  `pi-gufo`, `hermes-gufo`) or another model that only fits on the Z13 (see below);
- says the job needs a "big model", "lots of VRAM", "more memory than the desktop has" or long
  context (100K+ tokens);
- says to "offload" a job or run it "in the background" on the other machine.

**Ask first** when the user asks for local AI in general ("run it locally", "use local AI",
"use a local model", "keep this offline") and the model they want fits on both machines. Ask
in one short question: desktop or Z13. Don't route all local AI to the Z13 by default.

### Which models only fit on the Z13

A model belongs on the Z13 when its weights plus KV cache won't fit in the desktop's 20 GB VRAM
(roughly, anything over about 16 GB on disk, or long-context runs of smaller models). This
covers Qwen Flash-Next (every quant), the Qwen 27B and HauhauCS 27B models (`pi-local`,
`pi-hauhau`), `qwen3-vl-30b-a3b` (the vision cluster's `cc-judge`), and 30B+ models in general.
Small models like `qwen3-vl-8b` run on both machines, so for those you ask first.
When unsure, check the file size in the Z13's model store (`ssh flowz13 localai models-path`).

## How to route

Send the task to the Z13's Claude Code over SSH and have it do the work there. Pipe the prompt in
on stdin so no quoting gets mangled between PowerShell and the Z13's fish shell:

```powershell
"<the user's task, with any context it needs>" | ssh flowz13 "cd ~/dev/LocalAi && claude -p"
```

- The Z13 session can't see this conversation. Put everything it needs in the prompt: file paths
  on the Z13, the model to use, and what to return.
- `claude -p` can't ask for tool approvals, so tools that need approval are refused. For a task
  that has to edit files or run commands, ask the user before adding `--permission-mode
  acceptEdits` (or a broader mode), or suggest the **z13** Remote Control session instead, where
  approvals reach their phone.
- Long jobs: run the SSH command in the background and tell the user it is running on the Z13.
- Report the Z13's answer back, and say clearly that it came from the Z13.

If `ssh flowz13` fails, the Z13 is probably asleep or off Tailscale. Tell the user, and don't
fall back to running a Z13-only model on the desktop.
