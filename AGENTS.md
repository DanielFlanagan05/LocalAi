# Agent instructions

## Routing work to the Flow Z13

The rules for when and how the desktop sends work to the Flow Z13 (SSH and Remote Control, and
which requests and models go there) are in [docs/desktop-AGENTS.md](docs/desktop-AGENTS.md).
That file is meant for the desktop's dev folder (the parent of this checkout). On the desktop,
copy it there as `AGENTS.md` and add a `CLAUDE.md` containing `@AGENTS.md` next to it.

If you are running on the Z13 itself (hostname `FlowZ13`), you are already the target: run
Z13 work locally, not over SSH.
