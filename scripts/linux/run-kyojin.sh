#!/usr/bin/env bash
set -euo pipefail
root="${XDG_DATA_HOME:-$HOME/.local/share}/localai/apps/kyojin"
cd "$root"
source .venv/bin/activate
export EXL3_ROCM_SDK
EXL3_ROCM_SDK=$(rocm-sdk path --root)
source tools/strix_halo/env.sh
# Keep Node/HTTP clients alive while a large prompt is being read silently.
export KYOJIN_SSE_PING_S="${KYOJIN_SSE_PING_S:-10}"
exec "$@"
