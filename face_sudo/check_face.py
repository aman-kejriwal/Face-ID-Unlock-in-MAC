"""Headless face check used by pam_face.so for sudo and by the lock-screen helper.

Exit code 0 = the enrolled owner was seen, anything else = not verified.
For sudo it runs as root with its files next to it, all root-owned (see facectl.sh).
The lock-screen helper passes --config/--faces/--models to use the user's own files.
"""

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=HERE / "config.json", type=Path)
    parser.add_argument("--faces", default=HERE / "owner_embeddings.npy", type=Path)
    parser.add_argument("--models", default=HERE / "insightface", type=Path)
    args = parser.parse_args()

    config = json.loads(args.config.read_text())
    deadline = time.time() + config["timeout_seconds"]

    import cv2
    import numpy as np
    from insightface.app import FaceAnalysis

    owner = np.load(args.faces)
    app = FaceAnalysis(
        name="buffalo_l",
        root=str(args.models),
        allowed_modules=["detection", "recognition"],
        addons=["liveness"] if config["liveness"] else [],
        # CPU starts in ~1s; CoreML takes ~8s to load, too slow for a sudo prompt.
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_size=(640, 640))

    cam = cv2.VideoCapture(config["camera_index"])
    if not cam.isOpened():
        return 2
    try:
        streak = 0
        while time.time() < deadline:
            ok, frame = cam.read()
            if not ok:
                continue
            faces = app.get(frame)
            if len(faces) != 1:
                streak = 0
                continue
            face = faces[0]
            liveness = getattr(face, "liveness", None)
            if (liveness is not None and not liveness.is_live) or face.normed_embedding is None:
                streak = 0
                continue
            score = float(np.max(owner @ face.normed_embedding))
            print(f"similarity={score:.3f}", file=sys.stderr)
            streak = streak + 1 if score >= config["match_threshold"] else 0
            if streak >= config["frames_required"]:
                return 0
        return 1
    finally:
        cam.release()


if __name__ == "__main__":
    sys.exit(main())
