#!/usr/bin/env bash
# Tear down the local mini-Slurm stack: bring containers down (removing
# anonymous volumes), strip the guarded ~/.ssh/config block, and remove
# the known_hosts file so a future setup starts clean.
set -euo pipefail

DOCKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_CONFIG="$HOME/.ssh/config"
MARK_START="# >>> alphaex-slurm"
MARK_END="# <<< alphaex-slurm"

docker compose -f "$DOCKER_DIR/docker-compose.yml" down -v || true

if [ -f "$SSH_CONFIG" ] && grep -qF "$MARK_START" "$SSH_CONFIG"; then
    # macOS and GNU sed differ; use awk for portability.
    tmp=$(mktemp)
    awk -v start="$MARK_START" -v end="$MARK_END" '
        $0 == start {skip=1; next}
        $0 == end   {skip=0; next}
        !skip
    ' "$SSH_CONFIG" > "$tmp"
    mv "$tmp" "$SSH_CONFIG"
    chmod 600 "$SSH_CONFIG"
fi

rm -f "$DOCKER_DIR/keys/known_hosts"

echo "[teardown] stack stopped and ~/.ssh/config block removed"
