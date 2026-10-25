#!/usr/bin/env bash
# Sets up the Flow Z13 (CachyOS, headless) as a vision-cluster node.
# Run as your normal user from a copy of the LocalAI/cluster folder; it uses sudo where needed.
#
#   CLUSTER_API_KEY=<value from desktop cluster/.env> ./z13/install.sh [--configure-gtt] [--rocm] [--skip-models]
#
#   --configure-gtt  let the iGPU map ~112 GiB of RAM (needs a reboot; set UMA to 512MB in BIOS first)
#   --rocm           also build the ROCm/HIP backend so it can be benchmarked against Vulkan
#   --skip-models    don't download model files (~58 GB)
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
cluster="$(dirname "$here")"
models=(qwen3-vl-8b internvl3-14b gemma3-12b qwen3-vl-30b-a3b)
configure_gtt=0; rocm=0; skip_models=0
for arg in "$@"; do
  case "$arg" in
    --configure-gtt) configure_gtt=1 ;;
    --rocm) rocm=1 ;;
    --skip-models) skip_models=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done
: "${CLUSTER_API_KEY:?Set CLUSTER_API_KEY to the value of CLUSTER_API_KEY from LocalAI/cluster/.env on the desktop}"

echo "==> Packages"
pkgs=(base-devel cmake git curl vulkan-headers vulkan-icd-loader vulkan-radeon shaderc)
[[ $rocm -eq 1 ]] && pkgs+=(rocm-hip-sdk)
sudo pacman -S --needed --noconfirm "${pkgs[@]}"

echo "==> llama.cpp"
sudo install -d -o "$USER" /opt/llama.cpp
bash "$cluster/node/build-llama.sh" /opt/llama.cpp/b11216-vulkan vulkan
[[ $rocm -eq 1 ]] && bash "$cluster/node/build-llama.sh" /opt/llama.cpp/b11216-rocm rocm

echo "==> Service account and files"
id llamavision &>/dev/null || sudo useradd --system --home-dir /var/lib/llama-vision --shell /usr/bin/nologin \
  --groups video,render llamavision
sudo install -d -o "$USER" -g llamavision -m 755 /srv/models
sudo install -d -m 755 /opt/llama-vision /etc/llama-vision
sudo install -m 755 "$cluster/node/run-llama-vision.sh" /opt/llama-vision/run-llama-vision.sh
sudo install -m 644 "$here"/env/*.env /etc/llama-vision/
printf '%s\n' "$CLUSTER_API_KEY" | sudo install -m 640 -g llamavision /dev/stdin /etc/llama-vision/api-key
sudo install -m 644 "$here/llama-vision@.service" /etc/systemd/system/llama-vision@.service

if [[ $skip_models -eq 0 ]]; then
  echo "==> Models"
  bash "$cluster/node/fetch-models.sh" "$cluster/models.tsv" /srv/models "${models[@]}"
fi

echo "==> Firewall (tailnet + home LAN only)"
if command -v ufw &>/dev/null && sudo ufw status | grep -q active; then
  for src in 100.64.0.0/10 192.168.4.0/24; do
    sudo ufw allow from "$src" to any port 9101:9104 proto tcp comment 'llama-vision'
  done
elif command -v firewall-cmd &>/dev/null && sudo firewall-cmd --state &>/dev/null; then
  for src in 100.64.0.0/10 192.168.4.0/24; do
    sudo firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=$src port port=9101-9104 protocol=tcp accept"
  done
  sudo firewall-cmd --reload
else
  echo "No active ufw/firewalld; ports 9101-9104 are protected only by the API key."
fi

if [[ $configure_gtt -eq 1 ]]; then
  echo "==> GPU memory (GTT) limit"
  # 112 GiB: gttsize in MiB, pages_limit in 4 KiB pages. Leaves ~16 GiB for the OS.
  sudo tee /etc/modprobe.d/llama-vision-gtt.conf >/dev/null <<'EOF'
options amdgpu gttsize=114688
options ttm pages_limit=29360128 page_pool_size=29360128
EOF
  if command -v mkinitcpio &>/dev/null; then sudo mkinitcpio -P
  elif command -v dracut &>/dev/null; then sudo dracut --regenerate-all --force
  fi
  echo "GTT configured. Reboot, then run this script again without --configure-gtt to start the services."
  exit 0
fi

gtt_mib=$(( $(cat /sys/class/drm/card*/device/mem_info_gtt_total 2>/dev/null | sort -n | tail -1 || echo 0) / 1048576 ))
echo "Current GPU-mappable memory (GTT): ${gtt_mib} MiB"
if (( gtt_mib < 100000 )); then
  echo "GTT is below ~100 GiB, so all four models will not fit. Run with --configure-gtt and reboot." >&2
  exit 1
fi

echo "==> Services"
sudo systemctl daemon-reload
for model in "${models[@]}"; do
  sudo systemctl enable --now "llama-vision@$model"
done
for model in "${models[@]}"; do
  port=$(grep '^PORT=' "/etc/llama-vision/$model.env" | cut -d= -f2)
  printf 'waiting for %-18s' "$model"
  for _ in $(seq 1 300); do
    curl -sf "http://127.0.0.1:$port/health" >/dev/null && { echo " ready on :$port"; continue 2; }
    sleep 2
  done
  echo " NOT READY - journalctl -u llama-vision@$model" >&2
done
