#!/usr/bin/env bash
# Sync the working tree (with a freshly built UI) from the dev Mac to the desk Mac.
#   scripts/deploy.sh user@desk-mac.local [~/jarvis]
set -euo pipefail

TARGET="${1:?usage: scripts/deploy.sh user@host [remote_dir]}"
REMOTE_DIR="${2:-~/jarvis}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "▸ building UI"
(cd "$ROOT/ui" && npm run build)

echo "▸ syncing to $TARGET:$REMOTE_DIR"
rsync -az --delete \
  --exclude '.git/' --exclude '.venv/' --exclude '.check-venv/' \
  --exclude 'ui/node_modules/' --exclude '__pycache__/' \
  --exclude '.env' --exclude 'config.yaml' \
  "$ROOT/" "$TARGET:$REMOTE_DIR/"

echo "▸ installing Python deps on target"
ssh "$TARGET" "cd $REMOTE_DIR && ~/.local/bin/uv sync --no-dev || uv sync --no-dev"
echo "✓ done. On the desk Mac: cd $REMOTE_DIR && uv run jarvis --mock"
