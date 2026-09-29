#!/usr/bin/env bash
# Sync the working tree (with a freshly built UI) from the dev Mac to the desk Mac.
#   scripts/deploy.sh user@desk-mac.local [~/jarvis]
# Optional extras to install on the target (default: voice + faster-whisper):
#   JARVIS_EXTRAS="voice stt-cpp" scripts/deploy.sh user@desk-mac.local
set -euo pipefail

TARGET="${1:?usage: scripts/deploy.sh user@host [remote_dir]}"
REMOTE_DIR="${2:-~/jarvis}"
EXTRAS="${JARVIS_EXTRAS-voice stt-faster}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

EXTRA_FLAGS=""
for extra in $EXTRAS; do
  EXTRA_FLAGS="$EXTRA_FLAGS --extra $extra"
done

echo "▸ building UI"
(cd "$ROOT/ui" && npm run build)

echo "▸ syncing to $TARGET:$REMOTE_DIR"
rsync -az --delete \
  --exclude '.git/' --exclude '.venv/' --exclude '.check-venv/' --exclude '.bench/' \
  --exclude 'ui/node_modules/' --exclude '__pycache__/' \
  --exclude '.env' --exclude 'config.yaml' \
  "$ROOT/" "$TARGET:$REMOTE_DIR/"

echo "▸ installing Python deps on target (extras:${EXTRA_FLAGS:- none})"
ssh "$TARGET" "cd $REMOTE_DIR && { ~/.local/bin/uv sync --no-dev $EXTRA_FLAGS || uv sync --no-dev $EXTRA_FLAGS; }"
echo "✓ done. On the desk Mac: cd $REMOTE_DIR && uv run jarvis"
