/* App bundle entry point: runs app.py in an embedded Python so macOS treats the process
 * as "Face ID Unlock" (Dock name, icon, and camera permission prompt). Paths are baked in
 * by build_app.sh. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <CoreFoundation/CoreFoundation.h>
#include <fcntl.h>
#include <unistd.h>

/* The project lives in a macOS-protected folder (e.g. Documents). Opening a file there shows
 * the "access files" prompt; if it was declined, explain instead of quitting silently. */
static int project_readable(void) {
    int fd = open(APP_SCRIPT, O_RDONLY);
    if (fd >= 0) {
        close(fd);
        return 1;
    }
    CFUserNotificationDisplayAlert(
        0, kCFUserNotificationStopAlertLevel, NULL, NULL, NULL,
        CFSTR("Face ID Unlock can't open its files"),
        CFSTR("macOS is blocking access to the project folder. Open System Settings > Privacy & "
              "Security > Files and Folders, turn on Documents for Face ID Unlock, then open the app again."),
        CFSTR("OK"), NULL, NULL, NULL);
    return 0;
}

int main(int argc, char **argv) {
    (void)argc;
    if (!isatty(STDERR_FILENO)) {
        /* Launched from Finder: keep errors somewhere readable. */
        char log[1024];
        snprintf(log, sizeof(log), "%s/Library/Logs/FaceIDUnlock.log", getenv("HOME") ? getenv("HOME") : "/tmp");
        freopen(log, "a", stderr);
        freopen(log, "a", stdout);
    }

    if (!project_readable())
        return 1;

    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    char *args[] = {argv[0], APP_SCRIPT};
    PyStatus status = PyConfig_SetBytesString(&config, &config.executable, VENV_PYTHON);
    if (!PyStatus_Exception(status))
        status = PyConfig_SetBytesArgv(&config, 2, args);
    if (!PyStatus_Exception(status))
        status = PyConfig_SetBytesString(&config, &config.run_filename, APP_SCRIPT);
    if (!PyStatus_Exception(status))
        status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status))
        Py_ExitStatusException(status);
    return Py_RunMain();
}
