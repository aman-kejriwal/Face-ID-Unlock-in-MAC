# Face Vault

Opens a folder (or any apps/files you choose) only when the camera recognises your face.
Built on the InsightFace clone in `../insightface`.

## Use it

Run these from this `face_vault` folder, **not** the project root (the `insightface/` clone
there would shadow the installed package).

```bash
cd "face_vault"
../.venv/bin/python vault.py enroll   # once: saves your face (look at the camera, turn your head slightly)
../.venv/bin/python vault.py test     # check it: prints similarity scores, opens nothing
../.venv/bin/python vault.py unlock   # opens everything in "open_on_unlock" if it's you
```

The first run asks for camera permission for your terminal app
(System Settings > Privacy & Security > Camera). Press **Q** in the camera window to cancel.

## Settings (`config.json`)

| Setting | Meaning |
|---|---|
| `match_threshold` | How similar a face must be (0–1). Raise to be stricter, lower if it rejects you. |
| `frames_required` | Frames in a row that must match before unlocking. |
| `unlock_timeout_seconds` | Give up after this long. |
| `liveness` | Reject photos/screens held up to the camera. Use `--no-liveness` to test without it. |
| `open_on_unlock` | Paths, apps (e.g. `/Applications/Notes.app`) or URLs to open on success. |

Re-run `enroll` any time (e.g. new glasses, different lighting) to replace your saved face.

## Limits

This is a convenience gate, not encryption: the `secret/` folder is a normal folder that anyone
using your Mac account can still open in Finder. A webcam can also be fooled more easily than
Apple's Face ID depth camera.
