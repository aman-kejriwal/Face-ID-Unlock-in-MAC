# Face ID Unlock (Mac app)

One window for everything: update your face, test recognition, unlock the Face Vault,
turn Face ID for sudo on/off and change its settings, and jump to the macOS permission pages.

Open `Face ID Unlock.app` in the project folder (drag it to the Dock to keep it handy).

| Part | What it does |
|---|---|
| Left panel | Live camera: **Update my face**, **Test recognition**, **Unlock vault** |
| Face Vault tab | Recognition settings (saved instantly) and what opens on unlock |
| sudo tab | Turn on/off, settings, update the protected face copy, remove (macOS asks for your password) |
| Permissions tab | Opens System Settings for Camera and admin permissions |

## Rebuild

The app runs `app.py` from this folder using the project's `.venv`, with those paths built in.
After editing `app.py`, just reopen the app. After moving the project folder, rebuild:

```bash
face_app/build_app.sh
```

Errors are logged to `~/Library/Logs/FaceIDUnlock.log`.
