"""Face ID Unlock: one window to manage your face, Face Vault and Face ID for sudo."""

import json
import os
import plistlib
import pwd
import site
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
site.addsitedir(str(PROJECT / ".venv/lib/python3.11/site-packages"))
sys.path.insert(0, str(PROJECT / "face_vault"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal  # noqa: E402
from PySide6.QtGui import QDesktopServices, QIcon, QImage, QPixmap  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton,
    QSizePolicy, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

import vault  # noqa: E402

SUDO_DIR = PROJECT / "face_sudo"
SUDO_CONFIG = SUDO_DIR / "config.json"
FACECTL = SUDO_DIR / "facectl.sh"
INSTALLED = Path("/usr/local/lib/face-sudo")
PAM_MODULE = Path("/usr/local/lib/pam/pam_face.so")
SUDO_LOCAL = Path("/etc/pam.d/sudo_local")
USER = pwd.getpwuid(os.getuid()).pw_name

UNLOCK_DIR = PROJECT / "face_unlock"
UNLOCK_CONFIG = UNLOCK_DIR / "config.json"
HELPER_BIN = UNLOCK_DIR / "Face ID Unlock Helper.app/Contents/MacOS/FaceIDUnlockHelper"
HELPER_LABEL = "local.faceidunlock.helper"
HELPER_PLIST = Path.home() / "Library/LaunchAgents" / f"{HELPER_LABEL}.plist"
HELPER_STATUS = Path.home() / "Library/Application Support/FaceIDUnlock/status.json"
GUI_DOMAIN = f"gui/{os.getuid()}"

GREY, GREEN, YELLOW, RED = "#8e8e93", "#30a14e", "#c98a00", "#d93025"
BGR = {GREEN: (78, 161, 48), YELLOW: (0, 138, 201), RED: (37, 48, 217), GREY: (147, 142, 142)}

CAMERA_HELP = (
    "Could not open the camera. Allow camera access for Face ID Unlock in "
    "System Settings > Privacy & Security > Camera, then try again."
)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


def sudo_state():
    installed = PAM_MODULE.exists() and (INSTALLED / "run-check").exists()
    try:
        enabled = any(
            "pam_face.so" in line and not line.lstrip().startswith("#")
            for line in SUDO_LOCAL.read_text().splitlines()
        )
    except OSError:
        enabled = False
    try:
        face_current = (INSTALLED / "owner_embeddings.npy").read_bytes() == vault.FACES_FILE.read_bytes()
    except OSError:
        face_current = False
    return {
        "installed": installed,
        "enabled": enabled,
        "face_current": face_current,
        "config": read_json(INSTALLED / "config.json"),
    }


class CameraWorker(QThread):
    """Runs one camera session: 'enroll', 'test' (until stopped) or 'unlock'."""

    frame = Signal(QImage)
    status = Signal(str, str)
    failed = Signal(str)
    enrolled = Signal(object)
    unlocked = Signal(bool)

    def __init__(self, mode, config):
        super().__init__()
        self.mode = mode
        self.config = config
        self.running = True
        self.owner = np.load(vault.FACES_FILE) if mode != "enroll" else None

    def stop(self):
        self.running = False
        self.wait()

    def run(self):
        self.status.emit("Loading face models...", GREY)
        try:
            from insightface.app import FaceAnalysis

            app = FaceAnalysis(
                name="buffalo_l",
                allowed_modules=["detection", "recognition"],
                addons=["liveness"],
                liveness_mode="observe",
                providers=["CPUExecutionProvider"],
            )
            app.prepare(ctx_id=-1, det_size=(640, 640))
        except Exception as exc:  # model download or load problems
            self.failed.emit(f"Could not load the face models: {exc}")
            return

        cam = cv2.VideoCapture(self.config.get("camera_index", 0))
        if not cam.isOpened():
            self.failed.emit(CAMERA_HELP)
            return

        self.samples, self.streak, self.last_capture = [], 0, 0.0
        self.deadline = time.time() + self.config.get("unlock_timeout_seconds", 10)
        try:
            while self.running:
                ok, frame = cam.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                self.process(app, frame)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, _ = rgb.shape
                self.frame.emit(QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy())
        finally:
            cam.release()

    def process(self, app, frame):
        faces = app.get(frame)
        face = vault.largest_face(faces)
        needs_live = self.config.get("liveness", True)

        if len(faces) > 1:
            text, color = "Only one face please", YELLOW
        elif face is None:
            text, color = "No face found", YELLOW
        elif needs_live and vault.liveness_failed(face):
            text, color = "Liveness check failed - use your real face", RED
        elif face.normed_embedding is None:
            text, color = "Could not read face", YELLOW
        elif self.mode == "enroll":
            text, color = self.enroll_step(face)
        else:
            text, color = self.match_step(face)

        if color != GREEN:
            self.streak = 0
        if face is not None:
            x1, y1, x2, y2 = face.bbox.astype(int)
            cv2.rectangle(frame, (x1, y1), (x2, y2), BGR[color], 3)
        self.status.emit(text, color)

        if self.mode == "unlock" and self.running and time.time() > self.deadline:
            self.running = False
            self.unlocked.emit(False)

    def enroll_step(self, face):
        target = self.config.get("enroll_samples", 10)
        # Space samples out so they cover slightly different angles.
        if time.time() - self.last_capture > 0.4:
            self.samples.append(face.normed_embedding)
            self.last_capture = time.time()
        if len(self.samples) >= target:
            self.running = False
            self.enrolled.emit(np.stack(self.samples))
        return f"Capturing {len(self.samples)}/{target} - move your head slightly", GREEN

    def match_step(self, face):
        score = float(np.max(self.owner @ face.normed_embedding))
        threshold = self.config.get("match_threshold", 0.5)
        if score < threshold:
            return f"Not recognised (similarity {score:.2f}, need {threshold:.2f})", RED
        self.streak += 1
        needed = self.config.get("frames_required", 3)
        if self.mode == "unlock" and self.streak >= needed:
            self.running = False
            self.unlocked.emit(True)
        return f"Recognised - similarity {score:.2f} ({min(self.streak, needed)}/{needed})", GREEN


class AdminTask(QThread):
    """Runs facectl.sh as root through the standard macOS password dialog."""

    done = Signal(bool, str)

    SCRIPT = """
on run argv
    set cmd to ""
    repeat with a in argv
        set cmd to cmd & quoted form of (a as text) & " "
    end repeat
    do shell script cmd with prompt "Face ID Unlock wants to change Face ID for sudo." with administrator privileges
end run
"""

    def __init__(self, *args):
        super().__init__()
        self.args = ["/bin/bash", str(FACECTL), *args]

    def run(self):
        result = subprocess.run(["osascript", "-e", self.SCRIPT, *self.args], capture_output=True, text=True)
        if result.returncode == 0:
            self.done.emit(True, result.stdout.strip())
        elif "-128" in result.stderr:
            self.done.emit(False, "Cancelled.")
        else:
            self.done.emit(False, result.stderr.strip() or "Failed.")


def spin(minimum, maximum, value, step=1.0, decimals=None):
    box = QDoubleSpinBox() if decimals else QSpinBox()
    if decimals:
        box.setDecimals(decimals)
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setValue(value)
    return box


class VaultTab(QWidget):
    def __init__(self):
        super().__init__()
        self.config = vault.load_config()
        c = self.config

        self.liveness = QCheckBox("Liveness check (reject photos and screens)")
        self.liveness.setChecked(c["liveness"])
        self.threshold = spin(0.30, 0.95, c["match_threshold"], 0.05, decimals=2)
        self.frames = spin(1, 10, c["frames_required"])
        self.timeout = spin(3, 60, c["unlock_timeout_seconds"])
        self.samples = spin(3, 30, c["enroll_samples"])

        form = QFormLayout()
        form.addRow(self.liveness)
        form.addRow("Match threshold", self.threshold)
        form.addRow("Matching frames needed", self.frames)
        form.addRow("Give up after (seconds)", self.timeout)
        form.addRow("Photos when updating face", self.samples)
        security = QGroupBox("Recognition")
        security.setLayout(form)

        self.targets = QListWidget()
        self.targets.addItems(c["open_on_unlock"])
        add_folder = QPushButton("Add folder…")
        add_file = QPushButton("Add file or app…")
        remove = QPushButton("Remove")
        add_folder.clicked.connect(self.add_folder)
        add_file.clicked.connect(self.add_file)
        remove.clicked.connect(self.remove_target)
        buttons = QHBoxLayout()
        for b in (add_folder, add_file, remove):
            buttons.addWidget(b)
        buttons.addStretch()
        targets_box = QGroupBox("Open these when the vault unlocks")
        targets_layout = QVBoxLayout(targets_box)
        targets_layout.addWidget(self.targets)
        targets_layout.addLayout(buttons)

        self.saved = QLabel("")
        self.saved.setStyleSheet(f"color: {GREY}")
        layout = QVBoxLayout(self)
        layout.addWidget(security)
        layout.addWidget(targets_box)
        layout.addWidget(self.saved)

        for w in (self.threshold, self.frames, self.timeout, self.samples):
            w.valueChanged.connect(self.save)
        self.liveness.toggled.connect(self.save)

    def add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Choose a folder", str(Path.home()))
        if path:
            self.targets.addItem(path)
            self.save()

    def add_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a file or app", "/Applications")
        if path:
            self.targets.addItem(path)
            self.save()

    def remove_target(self):
        for item in self.targets.selectedItems():
            self.targets.takeItem(self.targets.row(item))
        self.save()

    def save(self):
        self.config.update(
            liveness=self.liveness.isChecked(),
            match_threshold=round(self.threshold.value(), 2),
            frames_required=self.frames.value(),
            unlock_timeout_seconds=self.timeout.value(),
            enroll_samples=self.samples.value(),
            open_on_unlock=[self.targets.item(i).text() for i in range(self.targets.count())],
        )
        write_json(vault.CONFIG_FILE, self.config)
        self.saved.setText("Settings saved.")


class SudoTab(QWidget):
    def __init__(self):
        super().__init__()
        self.task = None

        self.state_label = QLabel()
        self.state_label.setWordWrap(True)
        self.face_label = QLabel()
        self.face_label.setWordWrap(True)
        self.toggle = QPushButton()
        self.toggle.clicked.connect(self.on_toggle)
        self.update_face = QPushButton("Update protected face copy")
        self.update_face.clicked.connect(lambda: self.run_admin("sync", USER))

        status_box = QGroupBox("Face ID for sudo")
        s = QVBoxLayout(status_box)
        s.addWidget(self.state_label)
        s.addWidget(self.face_label)
        row = QHBoxLayout()
        row.addWidget(self.toggle)
        row.addWidget(self.update_face)
        row.addStretch()
        s.addLayout(row)

        cfg = read_json(SUDO_CONFIG, {})
        self.liveness = QCheckBox("Liveness check (reject photos and screens)")
        self.liveness.setChecked(cfg.get("liveness", True))
        self.threshold = spin(0.30, 0.95, cfg.get("match_threshold", 0.6), 0.05, decimals=2)
        self.frames = spin(1, 10, cfg.get("frames_required", 3))
        # pam_face.so kills the check after 9 s, so keep this below that.
        self.timeout = spin(3, 8, cfg.get("timeout_seconds", 6))
        self.apply = QPushButton("Apply settings to sudo")
        self.apply.clicked.connect(self.apply_settings)
        form = QFormLayout()
        form.addRow(self.liveness)
        form.addRow("Match threshold", self.threshold)
        form.addRow("Matching frames needed", self.frames)
        form.addRow("Give up after (seconds)", self.timeout)
        form.addRow(self.apply)
        settings_box = QGroupBox("sudo settings")
        settings_box.setLayout(form)
        for w in (self.threshold, self.frames, self.timeout):
            w.valueChanged.connect(self.refresh)
        self.liveness.toggled.connect(self.refresh)

        self.remove = QPushButton("Remove completely")
        self.remove.clicked.connect(self.on_remove)
        self.busy = QLabel("")
        self.busy.setWordWrap(True)
        note = QLabel(
            "Only affects sudo in Terminal. The lock screen and login are unchanged, "
            "and your password always works if your face isn't recognised."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {GREY}")

        layout = QVBoxLayout(self)
        layout.addWidget(status_box)
        layout.addWidget(settings_box)
        bottom = QHBoxLayout()
        bottom.addWidget(self.remove)
        bottom.addStretch()
        layout.addLayout(bottom)
        layout.addWidget(self.busy)
        layout.addStretch()
        layout.addWidget(note)
        self.refresh()

    def form_config(self):
        return {
            "match_threshold": round(self.threshold.value(), 2),
            "frames_required": self.frames.value(),
            "timeout_seconds": self.timeout.value(),
            "camera_index": 0,
            "liveness": self.liveness.isChecked(),
        }

    def refresh(self):
        st = sudo_state()
        self.state = st
        working = self.task is not None
        if not st["installed"]:
            self.state_label.setText("<b>Not installed.</b> Turning it on sets it up (takes about a minute).")
        elif st["enabled"]:
            self.state_label.setText(f"<b style='color:{GREEN}'>ON</b> — sudo checks your face before asking for a password.")
        else:
            self.state_label.setText(f"<b style='color:{GREY}'>OFF</b> — sudo asks for your password as normal.")
        self.toggle.setText("Turn off" if st["enabled"] else "Turn on")
        self.toggle.setEnabled(not working and vault.FACES_FILE.exists())

        if st["installed"]:
            self.face_label.setText(
                "Protected face copy is up to date." if st["face_current"]
                else f"<span style='color:{YELLOW}'>sudo still uses your previous face. Update the protected copy.</span>"
            )
        else:
            self.face_label.setText("")
        self.update_face.setVisible(st["installed"] and not st["face_current"])
        self.update_face.setEnabled(not working)
        self.apply.setEnabled(not working and st["installed"] and self.form_config() != st["config"])
        self.remove.setEnabled(not working and st["installed"])

    def on_toggle(self):
        if self.state["enabled"]:
            self.run_admin("disable")
        else:
            self.run_admin("enable", USER)

    def apply_settings(self):
        write_json(SUDO_CONFIG, self.form_config())
        self.run_admin("sync", USER)

    def on_remove(self):
        answer = QMessageBox.question(self, "Remove Face ID for sudo?",
                                      "This turns it off and deletes the installed files.")
        if answer == QMessageBox.StandardButton.Yes:
            self.run_admin("uninstall")

    def run_admin(self, *args):
        self.busy.setText("Working… enter your password in the macOS dialog."
                          + (" First setup takes about a minute." if not self.state["installed"] else ""))
        self.task = AdminTask(*args)
        self.task.done.connect(self.admin_done)
        self.task.start()
        self.refresh()

    def admin_done(self, ok, message):
        self.task = None
        self.busy.setText(message.splitlines()[-1] if ok and message else message)
        self.busy.setStyleSheet(f"color: {GREEN if ok else RED}")
        self.refresh()


def helper_running():
    return subprocess.run(["launchctl", "print", f"{GUI_DOMAIN}/{HELPER_LABEL}"],
                          capture_output=True).returncode == 0


def start_helper_at_login():
    """Registers the helper as a login item (LaunchAgent) and starts it now."""
    HELPER_PLIST.parent.mkdir(parents=True, exist_ok=True)
    with open(HELPER_PLIST, "wb") as f:
        plistlib.dump({
            "Label": HELPER_LABEL,
            "ProgramArguments": [str(HELPER_BIN), "run"],
            "RunAtLoad": True,
            "KeepAlive": True,
            "LimitLoadToSessionType": "Aqua",
            "ProcessType": "Interactive",
        }, f)
    subprocess.run(["launchctl", "bootout", f"{GUI_DOMAIN}/{HELPER_LABEL}"], capture_output=True)
    result = subprocess.run(["launchctl", "bootstrap", GUI_DOMAIN, str(HELPER_PLIST)],
                            capture_output=True, text=True)
    return result.returncode == 0, result.stderr.strip()


def stop_helper_at_login():
    subprocess.run(["launchctl", "bootout", f"{GUI_DOMAIN}/{HELPER_LABEL}"], capture_output=True)
    HELPER_PLIST.unlink(missing_ok=True)


def run_helper(*args, stdin=None):
    result = subprocess.run([str(HELPER_BIN), *args], input=stdin, capture_output=True, text=True)
    return result.returncode, result.stdout.strip()


class LockScreenTab(QWidget):
    def __init__(self):
        super().__init__()
        self.config = read_json(UNLOCK_CONFIG, {})

        self.state_label = QLabel()
        self.state_label.setWordWrap(True)
        self.checks = QLabel()
        self.last = QLabel()
        self.last.setWordWrap(True)
        self.last.setStyleSheet(f"color: {GREY}")
        self.toggle = QPushButton()
        self.toggle.clicked.connect(self.on_toggle)
        self.message = QLabel("")
        self.message.setWordWrap(True)

        status_box = QGroupBox("Unlock my Mac with my face when I open the lid")
        s = QVBoxLayout(status_box)
        s.addWidget(self.state_label)
        s.addWidget(self.checks)
        s.addWidget(self.last)
        row = QHBoxLayout()
        row.addWidget(self.toggle)
        for text, pane in (("Accessibility settings", "Privacy_Accessibility"), ("Camera settings", "Privacy_Camera")):
            b = QPushButton(text)
            url = f"x-apple.systempreferences:com.apple.preference.security?{pane}"
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            row.addWidget(b)
        row.addStretch()
        s.addLayout(row)
        s.addWidget(self.message)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Your Mac login password")
        self.password.returnPressed.connect(self.save_password)
        save = QPushButton("Save")
        save.clicked.connect(self.save_password)
        self.forget = QPushButton("Remove")
        self.forget.clicked.connect(self.remove_password)
        pw_box = QGroupBox("Mac password (checked, then kept in your Keychain)")
        pw_row = QHBoxLayout(pw_box)
        pw_row.addWidget(self.password, 1)
        pw_row.addWidget(save)
        pw_row.addWidget(self.forget)

        c = self.config
        self.liveness = QCheckBox("Liveness check (reject photos and screens)")
        self.liveness.setChecked(c.get("liveness", True))
        self.threshold = spin(0.30, 0.95, c.get("match_threshold", 0.6), 0.05, decimals=2)
        self.frames = spin(1, 10, c.get("frames_required", 3))
        self.timeout = spin(3, 15, c.get("timeout_seconds", 8))
        form = QFormLayout()
        form.addRow(self.liveness)
        form.addRow("Match threshold", self.threshold)
        form.addRow("Matching frames needed", self.frames)
        form.addRow("Give up after (seconds)", self.timeout)
        settings_box = QGroupBox("Recognition")
        settings_box.setLayout(form)
        for w in (self.threshold, self.frames, self.timeout):
            w.valueChanged.connect(self.save_config)
        self.liveness.toggled.connect(self.save_config)

        warning = QLabel(
            "While this is on, anyone who can fool the camera can unlock your Mac after sleep. "
            "It only works when waking from sleep; after a restart macOS always asks for the password."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(f"color: {YELLOW}")

        layout = QVBoxLayout(self)
        layout.addWidget(status_box)
        layout.addWidget(pw_box)
        layout.addWidget(settings_box)
        layout.addStretch()
        layout.addWidget(warning)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)
        self.refresh()

    def save_config(self):
        self.config.update(
            liveness=self.liveness.isChecked(),
            match_threshold=round(self.threshold.value(), 2),
            frames_required=self.frames.value(),
            timeout_seconds=self.timeout.value(),
        )
        write_json(UNLOCK_CONFIG, self.config)

    def refresh(self):
        built = HELPER_BIN.exists()
        running = built and helper_running()
        enabled = self.config.get("enabled", False) and running
        saved = built and '"password_saved": true' in run_helper("status")[1]
        status = read_json(HELPER_STATUS, {}) if running else {}

        if not built:
            self.state_label.setText("<b>Helper not built.</b> Run face_unlock/build_helper.sh first.")
        elif enabled:
            self.state_label.setText(f"<b style='color:{GREEN}'>ON</b> — opening the lid checks your face and unlocks the Mac.")
        else:
            self.state_label.setText(f"<b style='color:{GREY}'>OFF</b> — the lock screen works as normal.")

        def mark(ok, text):
            return f"<span style='color:{GREEN if ok else RED}'>{'✓' if ok else '✗'}</span> {text}"

        items = [mark(vault.FACES_FILE.exists(), "Face saved"), mark(saved, "Password saved")]
        if running:
            items += [mark(status.get("camera", False), "Camera allowed"),
                      mark(status.get("accessibility", False), "Accessibility allowed")]
        self.checks.setText("&nbsp;&nbsp;&nbsp;".join(items))
        if status.get("time"):
            when = datetime.fromisoformat(status["time"].replace("Z", "+00:00")).astimezone()
            self.last.setText(f"Last: {status.get('result', '')} ({when:%d %b %H:%M})")
        else:
            self.last.setText("")

        self.toggle.setText("Turn off" if enabled else "Turn on")
        self.toggle.setEnabled(built and (enabled or (saved and vault.FACES_FILE.exists())))
        self.forget.setEnabled(saved)
        self.enabled = enabled

    def on_toggle(self):
        if self.enabled:
            self.config["enabled"] = False
            write_json(UNLOCK_CONFIG, self.config)
            stop_helper_at_login()
            self.show_message("Turned off. The helper no longer runs.", GREEN)
        else:
            self.config["enabled"] = True
            write_json(UNLOCK_CONFIG, self.config)
            ok, error = start_helper_at_login()
            if ok:
                self.show_message("Turned on. If macOS asks, allow Camera and Accessibility for "
                                  "“Face ID Unlock Helper”, then close the lid to try it.", GREEN)
            else:
                self.config["enabled"] = False
                write_json(UNLOCK_CONFIG, self.config)
                self.show_message(f"Could not start the helper: {error}", RED)
        self.refresh()

    def save_password(self):
        password = self.password.text()
        self.password.clear()
        if not password:
            return
        code, output = run_helper("set-password", stdin=password + "\n")
        self.show_message(output, GREEN if code == 0 else RED)
        if code == 0 and helper_running():
            # Restart so a pause after a wrong password is lifted.
            subprocess.run(["launchctl", "kickstart", "-k", f"{GUI_DOMAIN}/{HELPER_LABEL}"], capture_output=True)
        self.refresh()

    def remove_password(self):
        _, output = run_helper("clear-password")
        self.show_message(output, GREEN)
        self.refresh()

    def show_message(self, text, color):
        self.message.setText(text)
        self.message.setStyleSheet(f"color: {color}")


class PermissionsTab(QWidget):
    PANES = [
        ("Camera", "Face ID Unlock needs the camera to see you. For sudo, the terminal app "
                   "you use (e.g. Terminal) needs it too.",
         "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera"),
        ("Administer your computer", "Face ID Unlock (or Terminal) asks once before it can change "
                                     "sudo's settings file. Review or revoke it here.",
         "x-apple.systempreferences:com.apple.preference.security"),
    ]

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        intro = QLabel(
            "macOS only lets you grant or remove privacy permissions yourself in System Settings; "
            "apps can't switch them. These buttons open the right page."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        for title, text, url in self.PANES:
            box = QGroupBox(title)
            row = QHBoxLayout(box)
            label = QLabel(text)
            label.setWordWrap(True)
            button = QPushButton("Open Settings")
            button.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            row.addWidget(label, 1)
            row.addWidget(button)
            layout.addWidget(box)
        layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Face ID Unlock")
        self.worker = None

        self.preview = QLabel("Camera off")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(560, 420)
        self.preview.setStyleSheet("background: #1c1c1e; color: #8e8e93; border-radius: 10px;")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.face_info = QLabel()
        self.face_info.setStyleSheet(f"color: {GREY}")

        self.enroll_btn = QPushButton("Update my face")
        self.add_btn = QPushButton("Add more samples")
        self.add_btn.setToolTip("Keep your saved face and add photos in the current lighting "
                                "(e.g. a dim room), so recognition works there too.")
        self.test_btn = QPushButton("Test recognition")
        self.unlock_btn = QPushButton("Unlock vault")
        self.stop_btn = QPushButton("Stop")
        self.enroll_btn.clicked.connect(lambda: self.start_camera("enroll"))
        self.add_btn.clicked.connect(lambda: self.start_camera("enroll", append=True))
        self.test_btn.clicked.connect(lambda: self.start_camera("test"))
        self.unlock_btn.clicked.connect(lambda: self.start_camera("unlock"))
        self.stop_btn.clicked.connect(self.stop_camera)
        buttons = QHBoxLayout()
        for b in (self.enroll_btn, self.add_btn, self.test_btn, self.unlock_btn, self.stop_btn):
            buttons.addWidget(b)

        left = QVBoxLayout()
        left.addWidget(self.preview)
        left.addWidget(self.status)
        left.addLayout(buttons)
        left.addWidget(self.face_info)
        left.addStretch()

        self.vault_tab = VaultTab()
        self.sudo_tab = SudoTab()
        tabs = QTabWidget()
        tabs.addTab(self.vault_tab, "Face Vault")
        tabs.addTab(self.sudo_tab, "sudo")
        tabs.addTab(LockScreenTab(), "Lock screen")
        tabs.addTab(PermissionsTab(), "Permissions")
        tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QHBoxLayout()
        root.addLayout(left)
        root.addWidget(tabs, 1)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self.resize(1120, 600)
        self.update_buttons()

    def update_buttons(self):
        running = self.worker is not None
        has_face = vault.FACES_FILE.exists()
        self.enroll_btn.setEnabled(not running)
        self.add_btn.setEnabled(not running and has_face)
        self.test_btn.setEnabled(not running and has_face)
        self.unlock_btn.setEnabled(not running and has_face)
        self.stop_btn.setEnabled(running)
        if has_face:
            saved = datetime.fromtimestamp(vault.FACES_FILE.stat().st_mtime).strftime("%d %b %Y, %H:%M")
            count = len(np.load(vault.FACES_FILE))
            self.face_info.setText(f"Your face: saved {saved} ({count} samples)")
        else:
            self.face_info.setText("No face saved yet. Click “Update my face”.")

    def set_status(self, text, color):
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; font-weight: 600;")

    def start_camera(self, mode, append=False):
        self.appending = append
        self.overlay_pending = mode == "unlock"
        if self.overlay_pending:
            vault.overlay("scan")
        self.worker = CameraWorker(mode, dict(self.vault_tab.config))
        self.worker.frame.connect(self.show_frame)
        self.worker.status.connect(self.set_status)
        self.worker.failed.connect(self.camera_failed)
        self.worker.enrolled.connect(self.save_face)
        self.worker.unlocked.connect(self.unlock_finished)
        self.worker.finished.connect(self.camera_finished)
        self.worker.start()
        self.update_buttons()

    def stop_camera(self):
        if self.worker:
            self.worker.stop()

    def camera_finished(self):
        if getattr(self, "overlay_pending", False):
            vault.overlay("hide")  # stopped before a result
            self.overlay_pending = False
        self.worker = None
        self.preview.setPixmap(QPixmap())
        self.preview.setText("Camera off")
        self.update_buttons()

    def show_frame(self, image):
        pix = QPixmap.fromImage(image).scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pix)

    def camera_failed(self, message):
        self.set_status(message, RED)

    def save_face(self, samples):
        vault.DATA_DIR.mkdir(exist_ok=True)
        if self.appending and vault.FACES_FILE.exists():
            # Keep the newest 60 so old lighting conditions don't pile up forever.
            samples = np.concatenate([np.load(vault.FACES_FILE), samples])[-60:]
            message = f"Added samples - {len(samples)} saved in total."
        else:
            message = "Your face was updated."
        np.save(vault.FACES_FILE, samples)
        self.set_status(message, GREEN)
        self.update_buttons()
        self.sudo_tab.refresh()
        st = self.sudo_tab.state
        if st["installed"] and not st["face_current"]:
            answer = QMessageBox.question(
                self, "Update sudo too?",
                "sudo uses a protected copy of your face. Update it now? (asks for your password)")
            if answer == QMessageBox.StandardButton.Yes:
                self.sudo_tab.run_admin("sync", USER)

    def unlock_finished(self, ok):
        self.overlay_pending = False
        vault.overlay("success" if ok else "fail")
        if not ok:
            self.set_status("Access denied.", RED)
            return
        self.set_status("Access granted.", GREEN)
        for target in self.vault_tab.config["open_on_unlock"]:
            path = Path(target).expanduser()
            if path == vault.HERE / "secret":
                path.mkdir(exist_ok=True)
            subprocess.run(["open", str(path) if path.exists() else target])

    def closeEvent(self, event):
        self.stop_camera()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Face ID Unlock")
    icon = Path(__file__).with_name("AppIcon.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
