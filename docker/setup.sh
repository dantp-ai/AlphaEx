#!/usr/bin/env bash
# Bootstrap the local mini-Slurm stack: generate a dedicated SSH keypair,
# inject Host entries into ~/.ssh/config (under a guarded marker block),
# bring up the two cluster containers, and wait for sshd to accept logins.
#
# Idempotent: rerunning is safe.
set -euo pipefail

DOCKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$DOCKER_DIR/.." && pwd)"
KEYS_DIR="$DOCKER_DIR/keys"
KEY_PATH="$KEYS_DIR/id_alphaex_slurm"
KNOWN_HOSTS="$KEYS_DIR/known_hosts"
SSH_CONFIG="$HOME/.ssh/config"
MARK_START="# >>> alphaex-slurm"
MARK_END="# <<< alphaex-slurm"

mkdir -p "$KEYS_DIR"
if [ ! -f "$KEY_PATH" ]; then
    ssh-keygen -t ed25519 -f "$KEY_PATH" -N "" -q -C alphaex-mini-slurm
fi
cp "$KEY_PATH.pub" "$KEYS_DIR/authorized_keys"

mkdir -p "$HOME/.ssh"
touch "$SSH_CONFIG"
chmod 600 "$SSH_CONFIG"
if ! grep -qF "$MARK_START" "$SSH_CONFIG"; then
    cat >> "$SSH_CONFIG" <<EOF

$MARK_START
Host cluster-a
    HostName localhost
    Port 2221
    User alphaex
    IdentityFile $KEY_PATH
    UserKnownHostsFile $KNOWN_HOSTS
    StrictHostKeyChecking accept-new
    IdentitiesOnly yes
Host cluster-b
    HostName localhost
    Port 2222
    User alphaex
    IdentityFile $KEY_PATH
    UserKnownHostsFile $KNOWN_HOSTS
    StrictHostKeyChecking accept-new
    IdentitiesOnly yes
$MARK_END
EOF
fi

echo "[setup] starting the mini-slurm stack..."
# Export the host user's UID so the image's `alphaex` user owns bind-mounted
# writes natively (see docker-compose.yml's build.args and Dockerfile.slurm).
# Named ALPHAEX_UID (not UID) because bash's built-in UID is a readonly
# special variable that can't be reassigned or re-exported.
export ALPHAEX_UID=$(id -u)
# CI's `local-slurm` job pre-builds the image via buildx + the GHA cache,
# then exports ALPHAEX_PREBUILT_IMAGE=1 so we skip the redundant compose
# build pass here. Local devs leave it unset and get the normal build.
if [ "${ALPHAEX_PREBUILT_IMAGE:-}" = "1" ]; then
    docker compose -f "$DOCKER_DIR/docker-compose.yml" up -d
else
    docker compose -f "$DOCKER_DIR/docker-compose.yml" up -d --build
fi

wait_for_ssh() {
    local host=$1
    local i
    for i in $(seq 1 30); do
        if ssh -o BatchMode=yes -o ConnectTimeout=2 "$host" true 2>/dev/null; then
            echo "[setup] $host is ready"
            return 0
        fi
        sleep 1
    done
    echo "[setup] $host did not accept ssh within 30s" >&2
    docker compose -f "$DOCKER_DIR/docker-compose.yml" logs "$host" >&2 || true
    return 1
}

wait_for_ssh cluster-a
wait_for_ssh cluster-b

echo
echo "Mini-slurm is ready. Try:"
echo "  ssh cluster-a sinfo"
echo "  ALPHAEX_LOCAL_SLURM=1 uv run pytest test/test_submitter_local.py -v"
echo
echo "Tear down with: bash docker/teardown.sh"
