#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/argus}"
BIN_DIR="/usr/local/bin"
SUDOERS_DIR="/etc/sudoers.d"
OPS_INSTALLER="$BIN_DIR/argus-install-ops.sh"

cd "$PROJECT_DIR"

for required in deploy/systemd deploy/scripts deploy/sudoers; do
    if [[ ! -d "$required" ]]; then
        echo "ERROR: $required not found. Pull the latest repository version first." >&2
        exit 1
    fi
done

if [[ ! -f deploy/scripts/argus-install-ops.sh ]]; then
    echo "ERROR: deploy/scripts/argus-install-ops.sh not found." >&2
    exit 1
fi

# Bootstrap the only privileged helper and its exact sudoers rule. After this
# first install, normal auto-deploys can synchronize the ops layer themselves.
sudo install -o root -g argus -m 0750     deploy/scripts/argus-install-ops.sh     "$OPS_INSTALLER"

sudo install -o root -g root -m 0440     deploy/sudoers/argus-auto-deploy     "$SUDOERS_DIR/argus-auto-deploy"

sudo visudo -cf "$SUDOERS_DIR/argus-auto-deploy"

sudo -n "$OPS_INSTALLER"

echo
echo "Installed Argus privileged ops helper and synchronized production ops."
echo "Future auto-deploys will update the ops layer automatically."
echo "Run: /usr/local/bin/argus-doctor.sh"
