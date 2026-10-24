#!/usr/bin/env bash
# Temporary, driver-supported high DPM policy. No overclock or power-limit edits.
set -euo pipefail
if (( EUID != 0 )); then
  echo "Run with sudo bash $0; your password is required to write the GPU policy." >&2
  exit 1
fi
control=
for device in /sys/class/drm/card*/device; do
  if [[ -r "$device/vendor" && $(<"$device/vendor") == 0x1002 && -w "$device/power_dpm_force_performance_level" ]]; then
    control="$device/power_dpm_force_performance_level"
    break
  fi
done
[[ -n "$control" ]] || { echo 'No writable AMD GPU policy found.' >&2; exit 1; }
previous=$(<"$control")
restore() { printf '%s\n' "$previous" > "$control"; echo "Restored GPU policy: $previous"; }
trap restore EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
printf 'high\n' > "$control"
echo "GPU policy: $(<"$control"). It will restore to $previous in 10 minutes, or on Ctrl-C."
sleep 600
