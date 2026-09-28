#!/bin/bash
# Installs face authentication for sudo. Run from Terminal:  sudo ./install.sh
set -euo pipefail
if [[ $EUID -ne 0 || -z "${SUDO_USER:-}" ]]; then
    echo "Run this with sudo from your own account:  sudo ./install.sh" >&2
    exit 1
fi
exec "$(dirname "$0")/facectl.sh" install "$SUDO_USER"
