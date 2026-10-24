#!/usr/bin/env bash
# Start the supervised local ComfyUI server from any working directory.
set -euo pipefail
source "${XDG_CONFIG_HOME:-$HOME/.config}/localai/env.sh"
exec /usr/bin/python "${LOCALAI_REPO}/scripts/linux/comfy_session.py" "$@"
