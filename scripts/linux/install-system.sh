#!/usr/bin/env bash
set -euo pipefail
if [[ $(id -u) != 0 ]]; then
  echo "Run: sudo bash $0 [--memory]" >&2
  exit 1
fi
if [[ ${1:-} == --memory ]]; then
  # Firmware carve-out must be lowered first; do not strand Linux with 31 GiB.
  mem_kib=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
  if (( mem_kib < 110000000 )); then
    echo 'First reduce BIOS UMA/frame-buffer reservation to 512 MiB (or its minimum), reboot, then rerun with --memory.' >&2
    exit 1
  fi
  config=/etc/modprobe.d/99-localai-ttm.conf
  if [[ -e $config && ! -e $config.before-localai ]]; then cp -a "$config" "$config.before-localai"; fi
  printf '%s\n' '# LocalAI: 112 GiB dynamic GPU mapping ceiling, not additional RAM.' 'options ttm pages_limit=29360128' > "$config"
  mkinitcpio -P
  echo 'TTM configuration written. Reboot when convenient. Roll back by removing /etc/modprobe.d/99-localai-ttm.conf and running sudo mkinitcpio -P.'
  exit 0
fi
# Full upgrades avoid unsupported Arch partial upgrades. No firmware/boot changes.
pacman -Syu --needed base-devel cmake ninja pkgconf git curl jq python uv nodejs-lts-krypton npm wl-clipboard \
  podman crun fuse-overlayfs slirp4netns vulkan-headers spirv-headers shaderc vulkan-tools \
  hipblas hipblaslt rocblas hipcub rocprim rocwmma ffmpeg \
  gtk3 nss libxss alsa-lib libnotify xdg-utils desktop-file-utils
echo 'System dependencies installed. Rootless Podman also requires subordinate UID/GID ranges; verify with podman info.'
