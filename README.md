# Face ID Unlock

Face recognition for a Mac, built on [InsightFace](https://github.com/deepinsight/insightface):

| Folder | What it does |
|---|---|
| `face_vault/` | Enroll your face; open a folder or apps only when the camera recognises you |
| `face_sudo/` | Approve `sudo` in Terminal with your face (password still works) |
| `face_unlock/` | Unlock the lock screen with your face when you open the lid |
| `face_app/` | **Face ID Unlock.app**, one window to manage all of the above |

Each folder has its own README with details.

## Setup

InsightFace is not part of this repository. Clone it into the project folder at the version
this project was built against:

```bash
git clone https://github.com/deepinsight/insightface.git
git -C insightface checkout 1480e705287bc5d59f923b46c260ec6e3e4150f6
```

Then create the Python environment (Python 3.11) and build the app:

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e ./insightface/python-package "PySide6-Essentials>=6.5"
face_app/build_app.sh
```

Run Python scripts from inside their folders (e.g. `cd face_vault`), not the project root:
the `insightface/` checkout there would shadow the installed package.

## Not in git

Your enrolled face (`face_vault/data/`), downloaded models (`~/.insightface/`), the virtual
environment, built `.app` bundles and logs are all ignored. The face models download
automatically on first use.
