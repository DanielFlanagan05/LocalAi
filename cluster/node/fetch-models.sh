#!/usr/bin/env bash
# Downloads pinned model files from Hugging Face and verifies their SHA-256.
# Usage: fetch-models.sh <models.tsv> <dest-dir> <model> [model...]
set -euo pipefail

manifest="$1"; dest="$2"; shift 2
mkdir -p "$dest"

# Hash from stdin: given a path, sha256sum may prefix the digest with "\" (e.g. Git Bash).
sha256_of() {
  if command -v sha256sum >/dev/null; then sha256sum <"$1" | cut -d' ' -f1
  else shasum -a 256 <"$1" | cut -d' ' -f1
  fi
}

for want in "$@"; do
  found=0
  while IFS=$'\t' read -r model _role repo revision file size sha; do
    [[ "$model" == "$want" ]] || continue
    found=1
    target="$dest/$file"
    if [[ -f "$target" ]] && [[ "$(wc -c <"$target" | tr -d ' ')" == "$size" ]]; then
      echo "ok      $file (already present)"
    else
      echo "fetch   $file from $repo@${revision:0:8}"
      curl -fL --retry 5 -C - -o "$target.part" "https://huggingface.co/$repo/resolve/$revision/$file"
      mv "$target.part" "$target"
    fi
    actual="$(sha256_of "$target")"
    if [[ "$actual" != "$sha" ]]; then
      echo "SHA-256 mismatch for $file (got $actual). Moved it to $file.bad; re-run to download again." >&2
      mv -f "$target" "$target.bad"
      exit 1
    fi
    echo "verified $file"
  done < <(grep -v '^#' "$manifest")
  if [[ $found -eq 0 ]]; then
    echo "Unknown model '$want' (not in $manifest)" >&2
    exit 1
  fi
done
