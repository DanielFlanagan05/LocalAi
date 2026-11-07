# Hermes from your phone (ScarfGo over Tailscale)

[Scarf](https://github.com/awizemann/scarf) is a Mac/iOS client for Hermes. Its iPhone app,
**ScarfGo**, connects over plain SSH and runs `hermes` on this machine. No extra server process
is involved. A checkout of Scarf is at `~/dev/scarf` for reference; the Linux host side needs no
build.

## What is set up on the Z13

| Piece | Value |
|---|---|
| Model | huihui-ai Qwen3.8-Flash-Next abliterated v2, Unsloth UD-IQ4_XS (3 shards, ~94 GB) |
| LocalAi profile | `flash-abliterated` (catalog key `qwen-flash-abliterated`), llama.cpp Vulkan; stock Gufo rejects the pack's IQ3_S expert tensors |
| ACP | `agent-client-protocol==0.9.0` installed into the Hermes venv (Hermes's `acp` extra); `hermes pm install --extra acp` stopped on a tool-version check |
| Hermes home Scarf reads | `~/.hermes` (default profile), model `flash-abliterated` on `127.0.0.1:8080` |
| Binary for Scarf | `/home/danfl/.local/bin/hermes-scarf` |
| SSH | `sshd` on port 22, key-only, allowed on `tailscale0` by UFW |
| Address | The Z13's Tailscale IP (`tailscale ip -4`) |

`~/.local/bin/hermes` is a LocalAi launcher that always runs `hermes chat`, so Scarf must not use
it. `hermes-scarf` passes every subcommand (`acp`, `sessions`, `config`, ...) to the real Hermes
CLI. For `acp` and `chat` it first runs `localai start flash-abliterated`, so the model loads
when a phone chat starts. A cold load takes about 20 seconds plus first-prompt prefill; run `localai start flash-abliterated`
beforehand to avoid the wait. If another LocalAi model is running, the start is refused: stop that
model with `localai stop` first.

## Connect from the iPhone

1. Open Tailscale on the iPhone and turn it on.
2. Install **ScarfGo** from the App Store.
3. Tap **Add Server** and enter:
   - Host: the Z13's Tailscale IP (`tailscale ip -4` on the Z13)
   - User: `danfl`
   - Port: `22`
   - Hermes binary hint: `/home/danfl/.local/bin/hermes-scarf`
4. Choose **Generate a new key**, then tap **Copy public key**.
5. On the Z13, append that line to `~/.ssh/authorized_keys` (one line per device).
6. Tap **Test connection**, then open **Chat**.

## Troubleshooting

- Connection refused or timeout: check `tailscale status` on both devices; the phone must be
  online in the tailnet.
- Chat starts but never answers: run `localai status`. If another profile is loaded, run
  `localai stop` and retry.
- Model logs: `~/.local/state/localai/flash-abliterated.log`.
