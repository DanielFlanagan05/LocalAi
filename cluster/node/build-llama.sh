#!/usr/bin/env bash
# Builds llama.cpp at the tag ClearCase pins, so every node runs the same server code.
# Usage: build-llama.sh <install-prefix> <backend: vulkan|rocm|metal>
set -euo pipefail

LLAMA_TAG="${LLAMA_TAG:-b11216}"
prefix="$1"; backend="$2"
src="${LLAMA_SRC:-$HOME/.cache/llama.cpp-src}"

if [[ -x "$prefix/bin/llama-server" ]]; then
  echo "llama.cpp $LLAMA_TAG ($backend) already built at $prefix"
  exit 0
fi

if [[ ! -d "$src/.git" ]]; then
  git clone --filter=blob:none https://github.com/ggml-org/llama.cpp "$src"
fi
git -C "$src" fetch --tags --quiet
git -C "$src" checkout --quiet "refs/tags/$LLAMA_TAG"

case "$backend" in
  vulkan) flags=(-DGGML_VULKAN=ON) ;;
  # Strix Halo's iGPU is gfx1151.
  rocm)   flags=(-DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1151 -DCMAKE_HIP_COMPILER="${HIPCXX:-/opt/rocm/llvm/bin/clang++}") ;;
  metal)  flags=(-DGGML_METAL=ON) ;;
  *) echo "Unknown backend: $backend" >&2; exit 1 ;;
esac

build="$src/build-$backend"
# Static build: the two binaries can be copied anywhere without their shared libraries.
cmake -S "$src" -B "$build" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DLLAMA_CURL=OFF "${flags[@]}"
cmake --build "$build" --config Release -j "$(getconf _NPROCESSORS_ONLN)" --target llama-server llama-bench
mkdir -p "$prefix/bin"
cp "$build/bin/llama-server" "$build/bin/llama-bench" "$prefix/bin/"
echo "Installed llama.cpp $LLAMA_TAG ($backend) to $prefix"
