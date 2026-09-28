# Face sudo

Approve `sudo` in Terminal with your face. The password still works as a fallback.
It does **not** change the lock screen or login.

## Install / remove

Enroll first with `face_vault` (`vault.py enroll`), then in Terminal:

```bash
cd "face_sudo"
sudo ./install.sh     # asks for your password one last time
sudo ./uninstall.sh   # undo everything
```

Or use the **Face ID Unlock** app's sudo tab. Both call `facectl.sh`
(`install | enable | disable | sync | uninstall`).

After changing your enrolled face or `config.json`, run `sudo ./install.sh` again. It copies
everything into root-owned folders, so edits in this folder do nothing until reinstalled.

## How it works

`/etc/pam.d/sudo_local` (Apple's supported file for sudo add-ons, kept across macOS updates) gets:

    auth  sufficient  /usr/local/lib/pam/pam_face.so user=<you> timeout=9

`sufficient` means a face match lets you in, and anything else falls through to the normal password.
The module (`pam_face.c`) skips the camera and goes straight to the password when:
- the sudo user isn't you,
- you aren't the user logged in at the screen,
- the request comes over SSH.

Otherwise it runs `/usr/local/lib/face-sudo/run-check` (`check_face.py`). It needs exactly one face,
passing liveness, matching 3 frames in a row within 6 seconds.

| Installed file | Purpose |
|---|---|
| `/usr/local/lib/pam/pam_face.so` | PAM module |
| `/usr/local/lib/face-sudo/` | Python, models, your face embeddings, checker, config |
| `/etc/pam.d/sudo_local` | Turns it on |

## If sudo ever breaks

This works without sudo because it uses a different authentication path:

```bash
osascript -e 'do shell script "rm -f /etc/pam.d/sudo_local" with administrator privileges'
```
