#!/usr/bin/env bash
# Runs one llama-server vision instance. Used by the Z13 systemd units and the Mac LaunchAgents.
# Usage: run-llama-vision.sh <common.env> <model.env>
#   common.env: LLAMA_SERVER, MODEL_DIR, API_KEY_FILE, optional HOST and EXTRA_ARGS
#   model.env:  MODEL_ALIAS, MODEL_FILE, MMPROJ_FILE, PORT, NP, optional SLOT_CTX and EXTRA_ARGS
set -euo pipefail

set -a
for env_file in "$@"; do
  # shellcheck disable=SC1090
  source "$env_file"
done
set +a

: "${LLAMA_SERVER:?}" "${MODEL_DIR:?}" "${API_KEY_FILE:?}"
: "${MODEL_ALIAS:?}" "${MODEL_FILE:?}" "${MMPROJ_FILE:?}" "${PORT:?}"
NP="${NP:-2}"
SLOT_CTX="${SLOT_CTX:-16384}"  # ClearCase runs every inference with -c 16384

# shellcheck disable=SC2086  # EXTRA_ARGS is intentionally word-split
exec "$LLAMA_SERVER" \
  --host "${HOST:-0.0.0.0}" --port "$PORT" \
  -m "$MODEL_DIR/$MODEL_FILE" --mmproj "$MODEL_DIR/$MMPROJ_FILE" --alias "$MODEL_ALIAS" \
  -ngl 999 -fa on -ctk q8_0 -ctv q8_0 \
  -np "$NP" -c $((NP * SLOT_CTX)) --no-kv-unified \
  --temp 0 --jinja \
  --image-min-tokens 1024 --image-max-tokens 4096 \
  --api-key-file "$API_KEY_FILE" --metrics \
  ${EXTRA_ARGS:-}
