#!/bin/bash
# Removes face authentication for sudo. Run:  sudo ./uninstall.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo:  sudo ./uninstall.sh" >&2; exit 1; }
exec "$(dirname "$0")/facectl.sh" uninstall
