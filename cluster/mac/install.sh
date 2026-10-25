#!/usr/bin/env bash
# Sets up the MacBook Pro (M4 Max) as a vision-cluster node.
# Run from a copy of the LocalAI/cluster folder:
#
#   CLUSTER_API_KEY=<value from desktop cluster/.env> ./mac/install.sh [--skip-models]
#
# Prerequisites: Xcode Command Line Tools (xcode-select --install), Homebrew, and Tailscale
# signed in to the same tailnet with this machine named "macbook".
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
cluster="$(dirname "$here")"
root="$HOME/llama-vision"
models=(qwen3-vl-8b gemma3-12b)
skip_models=0
[[ "${1:-}" == "--skip-models" ]] && skip_models=1
: "${CLUSTER_API_KEY:?Set CLUSTER_API_KEY to the value of CLUSTER_API_KEY from LocalAI/cluster/.env on the desktop}"

echo "==> Tools"
brew install cmake git

echo "==> llama.cpp (Metal)"
bash "$cluster/node/build-llama.sh" "$root/llama.cpp-b11216" metal

echo "==> Files"
mkdir -p "$root/env" "$root/models" "$root/logs"
install -m 755 "$cluster/node/run-llama-vision.sh" "$root/run-llama-vision.sh"
cp "$here"/env/*.env "$root/env/"
cat > "$root/env/common.env" <<EOF
LLAMA_SERVER=$root/llama.cpp-b11216/bin/llama-server
MODEL_DIR=$root/models
API_KEY_FILE=$root/api-key
EOF
umask 077
printf '%s\n' "$CLUSTER_API_KEY" > "$root/api-key"
umask 022

if [[ $skip_models -eq 0 ]]; then
  echo "==> Models"
  bash "$cluster/node/fetch-models.sh" "$cluster/models.tsv" "$root/models" "${models[@]}"
fi

echo "==> GPU wired-memory limit (asks for your password)"
sudo install -m 644 -o root -g wheel "$here/com.localai.gpu-wired-limit.plist" /Library/LaunchDaemons/
sudo launchctl bootout system /Library/LaunchDaemons/com.localai.gpu-wired-limit.plist 2>/dev/null || true
sudo launchctl bootstrap system /Library/LaunchDaemons/com.localai.gpu-wired-limit.plist
sysctl iogpu.wired_limit_mb

echo "==> LaunchAgents"
for model in "${models[@]}"; do
  plist="$HOME/Library/LaunchAgents/com.localai.llama-vision.$model.plist"
  sed -e "s|__ROOT__|$root|g" -e "s|__MODEL__|$model|g" "$here/com.localai.llama-vision.plist.template" > "$plist"
  launchctl bootout "gui/$(id -u)" "$plist" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
done

for model in "${models[@]}"; do
  port=$(grep '^PORT=' "$root/env/$model.env" | cut -d= -f2)
  printf 'waiting for %-14s' "$model"
  for _ in $(seq 1 150); do
    curl -sf "http://127.0.0.1:$port/health" >/dev/null && { echo " ready on :$port"; continue 2; }
    sleep 2
  done
  echo " NOT READY - see $root/logs/$model.log" >&2
done
echo "If macOS asks whether llama-server may accept incoming connections, choose Allow."
