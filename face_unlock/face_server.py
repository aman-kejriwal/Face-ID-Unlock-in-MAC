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
from insightface.app import FaceAnalysis
from insightface.data import get_image

HERE = Path(__file__).resolve().parent
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
    app = FaceAnalysis(
        name="buffalo_l",
        allowed_modules=["detection", "recognition"],
        addons=["liveness"],
        liveness_mode="observe",  # decide per check, from config.json
    )
    # Your face is close to the camera, so a small detection size is enough and ~2x faster.
    app.prepare(ctx_id=0, det_size=(320, 320))
    app.get(get_image("t1"))  # first run compiles the CoreML models; do it now, not at wake
    return app


def check(app, lines):
    start = time.time()
    config = json.loads(CONFIG.read_text())
    owner = np.load(FACES)  # re-read each time so "Update my face" applies immediately
    deadline = start + config.get("timeout_seconds", 8)
    threshold = config.get("match_threshold", 0.6)
    needed = config.get("frames_required", 3)
    need_live = config.get("liveness", True)
    # Liveness can wobble on a single frame while exposure settles, so it must pass on all
    # but one of the matching frames rather than every one. It is never skipped.
    lives_needed = max(1, needed - 1) if need_live else 0

    # Asking for 640x480 at open time avoids a camera restart that setting it afterwards causes.
    cam = cv2.VideoCapture(config.get("camera_index", 0), cv2.CAP_AVFOUNDATION,
                           [cv2.CAP_PROP_FRAME_WIDTH, 640, cv2.CAP_PROP_FRAME_HEIGHT, 480])
    if not cam.isOpened():
        return "nocamera"
    stats = {"frames": 0, "no_face": 0, "low": 0, "not_live": 0, "brightened": 0}
    marks = {"camera open": time.time() - start}
    best, result = 0.0, "nomatch"
    matches = lives = 0
    try:
        while time.time() < deadline:
            if lines.poll(0) == "cancel":
                result = "cancelled"
                break
            ok, frame = cam.read()
            if not ok:
                continue
            marks.setdefault("first frame", time.time() - start)
            stats["frames"] += 1
            bright = brighten(frame)
            stats["brightened"] += bright is not frame
            faces = app.get(bright)
            if len(faces) != 1 or faces[0].normed_embedding is None:
                stats["no_face"] += 1
                matches = lives = 0
                continue
            face = faces[0]
            marks.setdefault("first face", time.time() - start)
            score = float(np.max(owner @ face.normed_embedding))
            best = max(best, score)
            if score < threshold:
                stats["low"] += 1
                matches = lives = 0
                continue
            marks.setdefault("first match", time.time() - start)
            matches += 1
            if face.liveness is not None and face.liveness.is_live:
                lives += 1
            else:
                stats["not_live"] += 1
            if matches >= needed:
                if lives >= lives_needed:
                    result = "match"
                    break
                # Enough matching frames but too few live ones: slide the window forward.
                matches, lives = needed - 1, min(lives, needed - 1)
        return result
    finally:
        cam.release()
        timings = ", ".join(f"{k} {v:.2f}s" for k, v in marks.items())
        print(f"{time.strftime('%H:%M:%S')} {result} in {time.time() - start:.2f}s | {timings} | "
              f"frames {stats['frames']} (brightened {stats['brightened']}): no face {stats['no_face']}, "
              f"low score {stats['low']}, not live {stats['not_live']}, best {best:.2f}",
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
