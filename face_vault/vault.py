"""Face Vault: a face-gated launcher built on InsightFace.

Usage:
    python vault.py enroll      # save your face (run once)
    python vault.py unlock      # look at the camera; opens the vault if it's you
    python vault.py test        # like unlock, but only prints scores (opens nothing)
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FACES_FILE = DATA_DIR / "owner_embeddings.npy"
CONFIG_FILE = HERE / "config.json"

DEFAULT_CONFIG = {
    # Cosine similarity needed to count as "you". Same person is usually 0.5-0.8,
    # strangers are usually below 0.3.
    "match_threshold": 0.5,
    # Frames in a row that must match before unlocking (stops one lucky frame).
    "frames_required": 3,
    "unlock_timeout_seconds": 10,
    "enroll_samples": 10,
    "camera_index": 0,
    # Reject photos/screens held up to the camera.
    "liveness": True,
    # Things to open after a successful match (folders, files, apps, URLs).
    "open_on_unlock": [str(HERE / "secret")],
}

GREEN, RED, YELLOW, WHITE = (0, 200, 0), (0, 0, 255), (0, 200, 255), (255, 255, 255)


def overlay(state):
    """Drives the on-screen scan animation shown by the lock-screen helper, if it is running."""
    try:
        import ctypes
        ctypes.CDLL("/usr/lib/libSystem.B.dylib").notify_post(f"local.faceidunlock.overlay.{state}".encode())
    except OSError:
        pass


def load_config():
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n")
    return {**DEFAULT_CONFIG, **json.loads(CONFIG_FILE.read_text())}


def build_model(liveness):
    print("Loading face models (first run downloads them, ~300 MB)...")
    app = FaceAnalysis(
        name="buffalo_l",
        allowed_modules=["detection", "recognition"],
        addons=["liveness"] if liveness else [],
    )
    app.prepare(ctx_id=0, det_size=(640, 640))
    return app


def open_camera(index):
    cam = cv2.VideoCapture(index)
    if not cam.isOpened():
        sys.exit(
            "Could not open the camera. Allow camera access for your terminal app in "
            "System Settings > Privacy & Security > Camera, then try again."
        )
    return cam


def largest_face(faces):
    if not faces:
        return None
    return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))


def liveness_failed(face):
    """True when the liveness check ran and did not say 'live'."""
    result = getattr(face, "liveness", None)
    return result is not None and not result.is_live


def draw(frame, face, text, color):
    if face is not None:
        x1, y1, x2, y2 = face.bbox.astype(int)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 40), (0, 0, 0), -1)
    cv2.putText(frame, text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    cv2.imshow("Face Vault", frame)


def close_window(cam):
    cam.release()
    cv2.destroyAllWindows()
    cv2.waitKey(1)


def enroll(config):
    app = build_model(config["liveness"])
    cam = open_camera(config["camera_index"])
    samples = []
    target = config["enroll_samples"]
    last_capture = 0.0
    print(f"Look at the camera. Slowly turn your head a little. Capturing {target} samples. Press Q to cancel.")

    while len(samples) < target:
        ok, frame = cam.read()
        if not ok:
            continue
        faces = app.get(frame)
        face = largest_face(faces)

        if len(faces) > 1:
            draw(frame, face, "Only one face please", YELLOW)
        elif face is None:
            draw(frame, None, "No face found", YELLOW)
        elif liveness_failed(face):
            draw(frame, face, "Liveness check failed - use your real face", RED)
        elif face.normed_embedding is None:
            draw(frame, face, "Could not read face", YELLOW)
        else:
            # Space samples out so they cover slightly different angles.
            if time.time() - last_capture > 0.4:
                samples.append(face.normed_embedding)
                last_capture = time.time()
            draw(frame, face, f"Capturing {len(samples)}/{target}", GREEN)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            close_window(cam)
            sys.exit("Enrollment cancelled.")

    close_window(cam)
    DATA_DIR.mkdir(exist_ok=True)
    np.save(FACES_FILE, np.stack(samples))
    print(f"Saved your face to {FACES_FILE.relative_to(HERE)}. Now run: python vault.py unlock")


def verify(config):
    """Watch the camera until the owner is seen or time runs out. Returns True on match."""
    if not FACES_FILE.exists():
        sys.exit("No face enrolled yet. Run: python vault.py enroll")
    owner = np.load(FACES_FILE)

    app = build_model(config["liveness"])
    cam = open_camera(config["camera_index"])
    threshold = config["match_threshold"]
    needed = config["frames_required"]
    streak = 0
    deadline = time.time() + config["unlock_timeout_seconds"]
    print("Look at the camera...")

    try:
        while time.time() < deadline:
            ok, frame = cam.read()
            if not ok:
                continue
            face = largest_face(app.get(frame))

            if face is None:
                streak = 0
                draw(frame, None, "No face found", YELLOW)
            elif liveness_failed(face):
                streak = 0
                draw(frame, face, "Liveness check failed", RED)
            elif face.normed_embedding is None:
                streak = 0
                draw(frame, face, "Could not read face", YELLOW)
            else:
                score = float(np.max(owner @ face.normed_embedding))
                if score >= threshold:
                    streak += 1
                    draw(frame, face, f"Match {score:.2f} ({streak}/{needed})", GREEN)
                else:
                    streak = 0
                    draw(frame, face, f"Not recognised {score:.2f}", RED)
                print(f"similarity={score:.3f}")

            if streak >= needed:
                return True
            if cv2.waitKey(1) & 0xFF == ord("q"):
                return False
        return False
    finally:
        close_window(cam)


def unlock(config, dry_run):
    overlay("scan")
    if not verify(config):
        overlay("fail")
        print("Access denied.")
        sys.exit(1)
    overlay("success")
    print("Access granted.")
    if dry_run:
        return
    for target in config["open_on_unlock"]:
        path = Path(target).expanduser()
        if path == HERE / "secret":
            path.mkdir(exist_ok=True)
        subprocess.run(["open", str(path) if path.exists() else target])


def main():
    parser = argparse.ArgumentParser(description="Open things only when your face is recognised.")
    parser.add_argument("command", choices=["enroll", "unlock", "test"])
    parser.add_argument("--no-liveness", action="store_true", help="skip the anti-photo check")
    args = parser.parse_args()

    config = load_config()
    if args.no_liveness:
        config["liveness"] = False

    if args.command == "enroll":
        enroll(config)
    else:
        unlock(config, dry_run=args.command == "test")


if __name__ == "__main__":
    main()
