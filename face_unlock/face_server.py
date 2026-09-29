"""Keeps the face models loaded for the lock-screen helper, so a check starts instantly.

Started by the helper. Loading with CoreML takes ~10 s once; after that a frame takes ~20 ms.
The camera is only opened during a check.

Protocol, one line each way:
  helper -> "check <id>"      server -> "<id> match|nomatch|nocamera|cancelled"
  helper -> "cancel"          stops the running check (e.g. the Mac woke up unlocked)
The server prints "ready" once the models are loaded.
"""

import json
import os
import select
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from insightface.data import get_image

HERE = Path(__file__).resolve().parent
# The strict "is it really you" logic is shared with the sudo checker.
sys.path.insert(0, str(HERE.parent / "face_sudo"))
from check_face import LiveFaceGate, build_app  # noqa: E402
CONFIG = HERE / "config.json"
FACES = HERE.parent / "face_vault" / "data" / "owner_embeddings.npy"

# Frames darker than this (mean 0-255) are brightened: the webcam starts dark and takes a
# moment to adjust its exposure, and dim rooms stay dark. Brightening lets the face be found
# in those frames instead of waiting.
DARK = 95
GAMMA_TABLES = {g: np.array([((i / 255.0) ** (1 / g)) * 255 for i in range(256)], np.uint8)
                for g in (1.4, 1.8, 2.2)}


class Lines:
    """Reads stdin lines without Python's buffering, so a check can poll for "cancel"."""

    def __init__(self):
        self.buffer = b""

    def poll(self, timeout):
        """Returns the next complete line, waiting up to `timeout` seconds (None = forever)."""
        while b"\n" not in self.buffer:
            ready, _, _ = select.select([0], [], [], timeout)
            if not ready:
                return None
            chunk = os.read(0, 4096)
            if not chunk:
                raise EOFError
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line.decode().strip()


def brighten(frame):
    mean = frame.mean()
    if mean >= DARK:
        return frame
    gamma = 2.2 if mean < 40 else 1.8 if mean < 70 else 1.4
    return cv2.LUT(frame, GAMMA_TABLES[gamma])


def load_models():
    # Always load the eye landmarks too, so "require_blink" can be switched without a restart.
    app = build_app(Path.home() / ".insightface", {"require_blink": True, "liveness": True})
    # Your face is close to the camera, so a small detection size is enough and ~2x faster.
    app.prepare(ctx_id=0, det_size=(320, 320))
    app.get(get_image("t1"))  # first run compiles the CoreML models; do it now, not at wake
    return app


def check(app, lines):
    start = time.time()
    config = json.loads(CONFIG.read_text())
    # Re-read each time so "Update my face" and setting changes apply immediately.
    gate = LiveFaceGate(np.load(FACES), config)
    deadline = start + config.get("timeout_seconds", 8)

    # Asking for 640x480 at open time avoids a camera restart that setting it afterwards causes.
    cam = cv2.VideoCapture(config.get("camera_index", 0), cv2.CAP_AVFOUNDATION,
                           [cv2.CAP_PROP_FRAME_WIDTH, 640, cv2.CAP_PROP_FRAME_HEIGHT, 480])
    if not cam.isOpened():
        return "nocamera"
    marks = {"camera open": time.time() - start}
    brightened = 0
    result = "nomatch"
    try:
        while time.time() < deadline:
            if lines.poll(0) == "cancel":
                result = "cancelled"
                break
            ok, frame = cam.read()
            if not ok:
                continue
            marks.setdefault("first frame", time.time() - start)
            bright = brighten(frame)
            adjusted = bright is not frame
            brightened += adjusted
            if gate.update(app.get(bright), adjusted=adjusted):
                result = "match"
                break
        return result
    finally:
        cam.release()
        timings = ", ".join(f"{k} {v:.2f}s" for k, v in marks.items())
        print(f"{time.strftime('%H:%M:%S')} {result} in {time.time() - start:.2f}s | {timings} | "
              f"brightened {brightened} | {gate.summary()} | "
              f"blink required: {gate.need_blink}, live threshold {gate.live_threshold}",
              file=sys.stderr, flush=True)


def main():
    app = load_models()
    print("ready", flush=True)
    lines = Lines()
    while True:
        try:
            line = lines.poll(None)
        except EOFError:
            return
        parts = (line or "").split()
        if len(parts) == 2 and parts[0] == "check":
            try:
                result = check(app, lines)
            except EOFError:
                return
            except Exception as exc:  # keep serving; the helper falls back to the password
                print(f"check failed: {exc}", file=sys.stderr, flush=True)
                result = "nomatch"
            print(f"{parts[1]} {result}", flush=True)


if __name__ == "__main__":
    main()
