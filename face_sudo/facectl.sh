#!/bin/bash
# Root-side control for face authentication in sudo. Must run as root.
#
#   facectl.sh install   OWNER   build + copy everything and turn it on
#   facectl.sh enable    OWNER   turn on (installs first if needed)
#   facectl.sh disable           turn off, keep the installed files
#   facectl.sh sync      OWNER   copy the enrolled face and config.json into the root copy
#   facectl.sh uninstall         turn off and delete everything
#
# Everything the check uses is copied into root-owned folders, because sudo runs it as
# root: if it used files you can edit, any program running as you could fake a match.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "facectl.sh must run as root" >&2; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(dirname "$HERE")"
DEST=/usr/local/lib/face-sudo
MODULE=/usr/local/lib/pam/pam_face.so
SUDO_LOCAL=/etc/pam.d/sudo_local
ACTION="${1:-}"
OWNER="${2:-}"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

need_owner() {
    [[ -n "$OWNER" ]] && id "$OWNER" >/dev/null 2>&1 || { echo "Usage: facectl.sh $ACTION USER" >&2; exit 1; }
    OWNER_HOME=$(dscl . -read "/Users/$OWNER" NFSHomeDirectory | awk '{print $2}')
}

write_sudo_local() {  # $1 = line to add, or empty to only remove ours
    local backup=""
    if [[ -f "$SUDO_LOCAL" ]]; then
        backup="$WORK/sudo_local.bak"
        cp -p "$SUDO_LOCAL" "$backup"
        grep -v "pam_face.so" "$backup" > "$WORK/sudo_local.new" || true
    else
        : > "$WORK/sudo_local.new"
    fi
    [[ -n "$1" ]] && echo "$1" >> "$WORK/sudo_local.new"

    if grep -qvE '^[[:space:]]*(#|$)' "$WORK/sudo_local.new"; then
        install -o root -g wheel -m 444 "$WORK/sudo_local.new" "$SUDO_LOCAL"
    else
        rm -f "$SUDO_LOCAL"   # nothing but comments left
    fi

    clang -O2 -o "$WORK/pam_selftest" "$HERE/pam_selftest.c" -lpam
    if ! "$WORK/pam_selftest" root; then
        echo "!! PAM self-test failed - restoring the previous sudo setup." >&2
        if [[ -n "$backup" ]]; then install -o root -g wheel -m 444 "$backup" "$SUDO_LOCAL"; else rm -f "$SUDO_LOCAL"; fi
        exit 1
    fi
}

sync_data() {
    local face="$PROJECT/face_vault/data/owner_embeddings.npy"
    [[ -f "$face" ]] || { echo "No enrolled face at $face" >&2; exit 1; }
    install -o root -g wheel -m 644 "$face" "$DEST/owner_embeddings.npy"
    "$DEST/venv/bin/python" -I -c "import json,sys; json.load(open(sys.argv[1]))" "$HERE/config.json"
    install -o root -g wheel -m 644 "$HERE/config.json" "$DEST/config.json"
}

do_install() {
    need_owner
    local uv="$OWNER_HOME/.local/bin/uv"
    for f in "$PROJECT/face_vault/data/owner_embeddings.npy" \
             "$OWNER_HOME/.insightface/models/buffalo_l" \
             "$OWNER_HOME/.insightface/addons/liveness.onnx" "$uv"; do
        [[ -e "$f" ]] || { echo "Missing $f - enroll your face first." >&2; exit 1; }
    done

    echo "==> Building PAM module"
    clang -O2 -arch arm64 -bundle -o "$WORK/pam_face.so" "$HERE/pam_face.c" -lpam

    echo "==> Creating root-owned Python environment in $DEST (takes a minute)"
    rm -rf "$DEST"
    mkdir -p "$DEST"
    export UV_PYTHON_INSTALL_DIR="$DEST/python" UV_CACHE_DIR="$WORK/uv-cache" \
           UV_PYTHON_PREFERENCE=only-managed UV_NO_CONFIG=1
    "$uv" venv --quiet --python 3.11 "$DEST/venv"
    # Build from a copy so no root-owned build files end up in the project folder.
    cp -R "$PROJECT/insightface/python-package" "$WORK/src"
    "$uv" pip install --quiet --python "$DEST/venv/bin/python" "$WORK/src"

    echo "==> Copying models, the enrolled face and the checker"
    mkdir -p "$DEST/insightface/models" "$DEST/insightface/addons"
    cp -R "$OWNER_HOME/.insightface/models/buffalo_l" "$DEST/insightface/models/"
    cp "$OWNER_HOME/.insightface/addons/liveness.onnx" "$DEST/insightface/addons/"
    cp "$HERE/check_face.py" "$HERE/run-check" "$DEST/"
    chown -R root:wheel "$DEST"
    chmod -R go-w "$DEST"
    chmod 755 "$DEST/run-check"
    sync_data
    "$DEST/venv/bin/python" -I -c "import cv2, numpy, insightface.app" >/dev/null

    echo "==> Installing $MODULE"
    mkdir -p "$(dirname "$MODULE")"
    install -o root -g wheel -m 444 "$WORK/pam_face.so" "$MODULE"

    do_enable
}

do_enable() {
    need_owner
    if [[ ! -f "$MODULE" || ! -x "$DEST/run-check" ]]; then
        do_install
        return
    fi
    write_sudo_local "auth       sufficient     $MODULE user=$OWNER timeout=9"
    echo "Face authentication for sudo is ON."
}

case "$ACTION" in
    install)   do_install ;;
    enable)    do_enable ;;
    disable)   write_sudo_local ""; echo "Face authentication for sudo is OFF." ;;
    sync)      need_owner; [[ -d "$DEST" ]] || { echo "Not installed." >&2; exit 1; }; sync_data; echo "Updated." ;;
    uninstall) write_sudo_local ""; rm -f "$MODULE"; rm -rf "$DEST"; echo "Face authentication for sudo removed." ;;
    *)         sed -n '2,9p' "$0" >&2; exit 1 ;;
esac
