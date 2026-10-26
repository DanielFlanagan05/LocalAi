# Z13: Enable SSH so the desktop can forward Claude Code tasks

The desktop (`Daniels-Desktop`, Windows 11) will SSH into this machine over Tailscale (`flowz13.tail632a33.ts.net`) and run Claude Code tasks here. Right now port 22 on this machine refuses connections, so it needs an SSH server and the desktop's public key.

Paste the prompt below into Claude Code on the Z13.

```text
Set up SSH access on this machine (CachyOS) so my Windows desktop can connect over Tailscale and run `claude -p` tasks here. Do these steps, and tell me about anything you could not verify.

1. Check whether sshd is installed and running (`systemctl status sshd`). If not, install `openssh` with pacman, then `sudo systemctl enable --now sshd`.
2. Check that sshd is listening on port 22 and that no firewall (ufw, firewalld, nftables) blocks it on the Tailscale interface (tailscale0). Open it for tailscale0 only, not for the LAN or the internet. Tell me what you changed.
3. Harden sshd without locking me out: key-only login. Set `PasswordAuthentication no` and `PermitRootLogin no` in a drop-in file under /etc/ssh/sshd_config.d/, run `sudo sshd -t`, and only then reload sshd. Do not do this until step 4 is finished and the key is installed.
4. Add this public key to ~/.ssh/authorized_keys for my user (create ~/.ssh with mode 700 and the file with mode 600 if needed, and do not duplicate the line):

   ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFRm3yAabbu8fh4IKt02PPorwbPnRy5n0gBQ5ogn06MK daniels-desktop->flowz13

5. Check that Claude Code works non-interactively for this user. Run `claude --version` and `claude auth status`, and check that `claude` is on the PATH of a non-interactive SSH session (for example `ssh localhost 'command -v claude'`). If not, tell me the full path to the binary, or add it to ~/.bashrc or ~/.profile in a way that applies to non-interactive shells.
6. Report back, in this format:
   - Linux username:
   - Tailscale hostname: (output of `tailscale status --self` or `hostname`)
   - Path to claude:
   - sshd status:
   - Firewall changes:
   - Which repo folder I should use as the default working directory for forwarded tasks:

Do not change power or sleep settings.
```

When the Z13 session reports back, give the report to the desktop's Claude. It will add an SSH config entry (`Host flowz13`), run a test (`ssh flowz13 "claude -p 'say hi'"`), and set up the forwarding.

## Cleanup (do this once setup is complete)

When the desktop confirms that `ssh flowz13` works with no password prompt, delete this file:

```bash
git rm Z13_SSH_Setup.md
git commit -m "Remove Z13 SSH setup instructions"
git push
```

If you are a Claude Code session reading this file: after the user confirms SSH works, run the commands above to delete this file, and tell the user you did.
