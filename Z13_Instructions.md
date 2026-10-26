# Z13: Set up Claude Code Remote Control

Paste the prompt below into Claude Code on the Z13. It sets up Remote Control so the Z13 is always available from the Claude mobile app, with no interaction after boot.

```text
Set up Claude Code Remote Control on this machine so it's always available from my phone, with no interaction after boot.

1. Check that the Claude Code CLI is installed and up to date (`claude --version`). Install or update it if not. Remote Control needs a recent version, and `claude remote-control --help` should work.
2. Check `claude auth status`. If I'm not logged in, tell me to run `claude auth login` myself (it needs my browser and claude.ai account), and wait for me.
3. Add `"remoteControlAtStartup": true` to ~/.claude/settings.json, keeping any existing keys.
4. Make a persistent service that runs `claude remote-control --spawn worktree --name z13` in my main projects folder and starts at boot, with no one logged in if possible:
   - Linux: a systemd user service with `loginctl enable-linger $USER`, Restart=always, and a working directory that is a git repo. Enable it and start it.
   - Windows: a scheduled task at logon that calls a wrapper script. Don't hardcode a CLI version path.
5. Use the default permission mode, so tool approvals come to my phone.
6. Check that the service is running and survives a restart of the service. Show me `systemctl --user status` (or the task state) and the last log lines. Then tell me exactly what name should appear in the Code tab of the Claude mobile app.
7. Don't change power or sleep settings without asking. Tell me what sleep behavior would drop the connection.

Tell me about anything you couldn't verify.
```

Notes:

- Step 2 stops and asks you to run `claude auth login` yourself. Claude can't sign in for you.
- The name `z13` keeps this machine easy to tell apart from `danfl-pc` in the mobile app.
- On Linux, `enable-linger` is what lets the service start at boot without anyone logging in.

## Cleanup (do this once setup is complete)

Once Remote Control is working on the Z13 and the machine shows up in the Claude mobile app, delete this file so it doesn't linger in the repo:

```bash
git rm Z13_Instructions.md
git commit -m "Remove Z13 setup instructions"
git push
```

If you're a Claude Code session reading this file: after the user confirms the setup works, run the commands above to delete this file, and tell the user you did.
