#!/usr/bin/env bash
# Scans the working tree (tracked and untracked files) for patterns listed in a
# private file kept outside the repository, so the list itself is never published.
# Usage: scripts/check-provenance.sh [patterns-file]
set -euo pipefail
motifs="${1:-$HOME/.config/mindyard/provenance-motifs}"
if [ ! -f "$motifs" ]; then
  echo "check-provenance: $motifs not found, nothing checked" >&2
  exit 0
fi
pattern="$(grep -vE '^\s*(#|$)' "$motifs" | paste -sd'|')"
cd "$(git rev-parse --show-toplevel)"
hits="$(git ls-files -z --cached --others --exclude-standard \
  | grep -zvE '^(uv\.lock|LICENSE)$|\.png$' \
  | xargs -0 grep -nIiE "$pattern" -- 2>/dev/null || true)"
if [ -n "$hits" ]; then
  echo "check-provenance: forbidden pattern found" >&2
  echo "$hits" | head -20 >&2
  exit 1
fi
echo "check-provenance: clean"
