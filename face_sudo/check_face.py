"""Headless face check used by pam_face.so for sudo and by the lock-screen helper.

Exit code 0 = the enrolled owner was seen, anything else = not verified.
For sudo it runs as root with its files next to it, all root-owned (see facectl.sh).
The lock-screen helper passes --config/--faces/--models to use the user's own files.

LiveFaceGate (also used by face_unlock/face_server.py) decides whether the owner is really
in front of the camera: the face must match and pass the liveness model, and - if
"require_blink" is set - prove it is not a flat picture, either by blinking or (with
"depth_check") by the 3D parallax of natural head movement, which a photo cannot show.
"""

import argparse
import json
import sys
import time
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent

# iBUG 68-point landmark indices for each eye, in eye-aspect-ratio order (p1..p6).
LEFT_EYE = [36, 37, 38, 39, 40, 41]
RIGHT_EYE = [42, 43, 44, 45, 46, 47]


def overlay(state):
    """Drives the on-screen scan animation shown by the lock-screen helper, if it is running."""
    try:
        import ctypes
        ctypes.CDLL("/usr/lib/libSystem.B.dylib").notify_post(f"local.faceidunlock.overlay.{state}".encode())
    except OSError:
        pass


def landmarks_2d(face):
    marks = getattr(face, "landmark_3d_68", None)
    return None if marks is None else marks[:, :2].astype("float32")


def eye_openness(face):
    """Eye aspect ratio averaged over both eyes (~0.3 open, <0.2 closed); None if unavailable."""
    import numpy as np

    marks = getattr(face, "landmark_3d_68", None)
    if marks is None:
        return None
    pts = marks[:, :2]

    def ratio(idx):
        p = pts[idx]
        vertical = np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4])
        return vertical / (2 * np.linalg.norm(p[0] - p[3]) + 1e-6)

    return (ratio(LEFT_EYE) + ratio(RIGHT_EYE)) / 2


class LiveFaceGate:
    """Feed it every frame's faces; it says when the owner is verified as really present.

    Forgiving of noise, strict about spoofs: frames that are merely imperfect (a borderline
    match, no face, a second face, liveness unsure) are skipped without losing progress, but
    a frame the liveness model calls fake wipes everything, and progress only counts on
    frames that match the owner. A photo cannot pass because it cannot blink.
    """

    FAKE_BELOW = 0.5     # liveness score that counts as a detected spoof
    GONE_AFTER = 1.0     # seconds without a matching frame before starting over
    BLINK_WITHIN = 1.2   # seconds from eyes closed to eyes open again
    DEPTH_WINDOW = 1.0   # seconds of landmark history compared for parallax
    DEPTH_MIN_GAP = 0.15  # compare frames at least this far apart
    MIN_MOTION = 0.015   # head must move at least this much (fraction of eye distance)

    def __init__(self, owner, config):
        self.owner = owner
        self.threshold = config.get("match_threshold", 0.6)
        self.needed = config.get("frames_required", 3)
        self.need_live = config.get("liveness", True)
        self.live_threshold = config.get("liveness_threshold", 0.9)
        self.need_blink = config.get("require_blink", False)
        self.depth_check = config.get("depth_check", False)
        self.depth_threshold = config.get("depth_threshold", 0.03)
        self.max_parallax = 0.0
        self.max_motion = 0.0
        self.proved_by = None
        self.stats = {"frames": 0, "no_face": 0, "several": 0, "low": 0, "unsure": 0, "fake": 0}
        self.best = 0.0
        self.live_scores = []
        self.last_match = None
        self.reset()

    def reset(self):
        self.matches = 0
        self.live_frames = 0
        self.open_ref = 0.0
        self.closed_at = None
        self.blinked = False
        self.depth_ok = False
        self.track = deque()

    def update(self, faces, adjusted=False):
        """Returns True once verified.

        `adjusted` marks a frame that was brightened for detection: it can count as a face
        match and a blink, but never as a liveness pass (brightening changes what the
        liveness model sees)."""
        import numpy as np

        now = time.time()
        self.stats["frames"] += 1
        if self.last_match is not None and now - self.last_match > self.GONE_AFTER:
            self.reset()  # the face has been away too long: start over
            self.last_match = None

        if not faces or faces[0].normed_embedding is None:
            self.stats["no_face"] += 1
            return False
        if len(faces) != 1:
            self.stats["several"] += 1
            return False
        face = faces[0]
        score = float(np.max(self.owner @ face.normed_embedding))
        self.best = max(self.best, score)
        if score < self.threshold:
            self.stats["low"] += 1
            return False
        self.last_match = now
        self.matches += 1

        # Blink: eyes clearly closed relative to the most open they have been, then open again
        # soon after - all on frames that match the owner.
        ear = eye_openness(face)
        eyes_open = True
        if ear is not None:
            self.open_ref = max(self.open_ref, ear)
            if self.open_ref > 0.18 and ear < 0.72 * self.open_ref:
                self.closed_at = now
                eyes_open = False
            elif self.closed_at is not None and ear > 0.85 * self.open_ref:
                if now - self.closed_at <= self.BLINK_WITHIN:
                    self.blinked = True
                self.closed_at = None

        if self.depth_check:
            self._check_depth(face, now)

        # Liveness, judged on open-eye, unbrightened frames.
        if self.need_live and eyes_open and not adjusted:
            result = getattr(face, "liveness", None)
            live_score = getattr(result, "live_score", None) if result is not None else None
            if live_score is not None:
                self.live_scores.append(live_score)
            if live_score is not None and live_score < self.FAKE_BELOW:
                self.stats["fake"] += 1
                self.reset()  # a detected spoof: throw away all progress
                return False
            if live_score is None or live_score < self.live_threshold:
                self.stats["unsure"] += 1
            else:
                self.live_frames += 1

        enough_live = not self.need_live or self.live_frames >= self.needed
        not_flat = not self.need_blink or self.blinked or self.depth_ok
        verified = self.matches >= self.needed and enough_live and not_flat
        if verified and self.need_blink:
            self.proved_by = "3D motion" if self.depth_ok else "blink"
        return verified

    def _check_depth(self, face, now):
        """Sets depth_ok once the landmarks move in a way no flat picture can.

        Every view of a flat photo or screen - however it is tilted or moved - is an exact
        homography of any other view. A real face is 3D: as the head turns even slightly,
        the nose shifts against the cheeks and jaw, and no homography fits. The leftover
        error, relative to the distance between the eyes, is the parallax."""
        import cv2
        import numpy as np

        pts = landmarks_2d(face)
        if pts is None:
            return
        eye_gap = float(np.linalg.norm(pts[36:42].mean(0) - pts[42:48].mean(0)))
        if eye_gap < 5:
            return
        while self.track and now - self.track[0][0] > self.DEPTH_WINDOW:
            self.track.popleft()
        for then, old in self.track:
            if now - then < self.DEPTH_MIN_GAP:
                break
            homography, _ = cv2.findHomography(old, pts, 0)
            if homography is None:
                continue
            fitted = cv2.perspectiveTransform(old.reshape(-1, 1, 2), homography).reshape(-1, 2)
            parallax = float(np.sqrt(((fitted - pts) ** 2).sum(1).mean())) / eye_gap
            motion = float(np.linalg.norm(pts - old, axis=1).mean()) / eye_gap
            self.max_motion = max(self.max_motion, motion)
            if motion >= self.MIN_MOTION:
                self.max_parallax = max(self.max_parallax, parallax)
                if parallax >= self.depth_threshold:
                    self.depth_ok = True
        self.track.append((now, pts))

    def summary(self):
        s = self.stats
        live = (f"live score min {min(self.live_scores):.2f} max {max(self.live_scores):.2f}"
                if self.live_scores else "live score n/a")
        return (f"frames {s['frames']}: no face {s['no_face']}, several faces {s['several']}, "
                f"low score {s['low']}, liveness unsure {s['unsure']}, fake {s['fake']}, "
                f"best {self.best:.2f}, {live}, blink {'yes' if self.blinked else 'no'}, "
                f"eye openness max {self.open_ref:.2f}, parallax max {self.max_parallax:.3f} "
                f"(motion max {self.max_motion:.3f}, needs {self.depth_threshold}), "
                f"proved by {self.proved_by or '-'}")


def build_app(models_root, config, providers=None):
    from insightface.app import FaceAnalysis

    modules = ["detection", "recognition"]
    if config.get("require_blink"):
        modules.append("landmark_3d_68")  # eye landmarks for blink detection
    kwargs = {"providers": providers} if providers else {}
    return FaceAnalysis(
        name="buffalo_l",
        root=str(models_root),
        allowed_modules=modules,
        addons=["liveness"] if config.get("liveness", True) else [],
        liveness_mode="observe",  # LiveFaceGate applies its own, stricter threshold
        **kwargs,
    )


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

    # CPU starts in ~1s; CoreML takes ~8s to load, too slow for a sudo prompt.
    app = build_app(args.models, config, providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    gate = LiveFaceGate(np.load(args.faces), config)

    cam = cv2.VideoCapture(config["camera_index"])
    if not cam.isOpened():
        return 2
    overlay("scan")
    matched = False
    try:
        while time.time() < deadline:
            ok, frame = cam.read()
            if not ok:
                continue
            if gate.update(app.get(frame)):
                matched = True
                return 0
        return 1
    finally:
        cam.release()
        overlay("success" if matched else "fail")
        print(gate.summary(), file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
