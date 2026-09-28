/*
 * pam_face.so - authenticate sudo by running a face-check program.
 *
 * Use as "sufficient" in /etc/pam.d/sudo_local so the password still works:
 *   auth sufficient /usr/local/lib/pam/pam_face.so user=NAME [checker=PATH] [timeout=SECONDS]
 *
 * Returns PAM_SUCCESS only when the checker exits 0. Returns PAM_IGNORE (fall back to
 * the password) when the user is not NAME, the user is not at the console, or the
 * request came over SSH.
 */

#include <errno.h>
#include <fcntl.h>
#include <pwd.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define PAM_SM_AUTH
#include <security/pam_appl.h>
#include <security/pam_modules.h>

#define DEFAULT_CHECKER "/usr/local/lib/face-sudo/run-check"
#define DEFAULT_TIMEOUT 8

static void info(pam_handle_t *pamh, const char *msg) {
    const struct pam_conv *conv = NULL;
    if (pam_get_item(pamh, PAM_CONV, (const void **)&conv) != PAM_SUCCESS || !conv || !conv->conv)
        return;
    struct pam_message m = {PAM_TEXT_INFO, (char *)msg};
    const struct pam_message *mp = &m;
    struct pam_response *resp = NULL;
    conv->conv(1, &mp, &resp, conv->appdata_ptr);
    if (resp) {
        free(resp->resp);
        free(resp);
    }
}

/* True if any ancestor of this process is sshd. */
static int via_ssh(void) {
    pid_t pid = getpid();
    for (int depth = 0; pid > 1 && depth < 64; depth++) {
        struct kinfo_proc kp;
        size_t len = sizeof(kp);
        int mib[4] = {CTL_KERN, KERN_PROC, KERN_PROC_PID, pid};
        if (sysctl(mib, 4, &kp, &len, NULL, 0) != 0 || len == 0)
            return 1; /* can't tell: treat as remote */
        if (strncmp(kp.kp_proc.p_comm, "sshd", 4) == 0)
            return 1;
        pid = kp.kp_eproc.e_ppid;
    }
    return 0;
}

/* Run the checker with a clean environment; returns its exit code or -1. */
static int run_checker(const char *checker, int timeout) {
    pid_t child = fork();
    if (child < 0)
        return -1;
    if (child == 0) {
        int devnull = open("/dev/null", O_RDWR);
        if (devnull >= 0) {
            dup2(devnull, STDIN_FILENO);
            dup2(devnull, STDOUT_FILENO);
            dup2(devnull, STDERR_FILENO);
        }
        setsid();
        /* sudo authenticates with real uid = user, effective uid = root; /bin/sh would
         * drop back to the user, who cannot read the root-only models. Become fully root. */
        if (setgid(0) != 0 || setuid(0) != 0)
            _exit(126);
        char *const argv[] = {(char *)checker, NULL};
        char *const envp[] = {"PATH=/usr/bin:/bin", "HOME=/var/root", NULL};
        execve(checker, argv, envp);
        _exit(127);
    }

    time_t deadline = time(NULL) + timeout;
    int status;
    for (;;) {
        pid_t r = waitpid(child, &status, WNOHANG);
        if (r == child)
            return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
        if (r < 0 && errno != EINTR)
            return -1;
        if (time(NULL) >= deadline) {
            kill(-child, SIGKILL);
            kill(child, SIGKILL);
            waitpid(child, &status, 0);
            return -1;
        }
        usleep(50000);
    }
}

PAM_EXTERN int pam_sm_authenticate(pam_handle_t *pamh, int flags, int argc, const char **argv) {
    (void)flags;
    const char *owner = NULL, *checker = DEFAULT_CHECKER;
    int timeout = DEFAULT_TIMEOUT;
    for (int i = 0; i < argc; i++) {
        if (strncmp(argv[i], "user=", 5) == 0)
            owner = argv[i] + 5;
        else if (strncmp(argv[i], "checker=", 8) == 0)
            checker = argv[i] + 8;
        else if (strncmp(argv[i], "timeout=", 8) == 0)
            timeout = atoi(argv[i] + 8);
    }
    if (!owner || timeout <= 0)
        return PAM_IGNORE;

    const char *user = NULL;
    if (pam_get_user(pamh, &user, NULL) != PAM_SUCCESS || !user || strcmp(user, owner) != 0)
        return PAM_IGNORE;

    struct passwd *pw = getpwnam(user);
    struct stat console;
    if (!pw || stat("/dev/console", &console) != 0 || console.st_uid != pw->pw_uid)
        return PAM_IGNORE;
    if (via_ssh())
        return PAM_IGNORE;

    info(pamh, "Face ID: look at the camera...");
    if (run_checker(checker, timeout) == 0)
        return PAM_SUCCESS;
    info(pamh, "Face not verified.");
    return PAM_AUTH_ERR;
}

PAM_EXTERN int pam_sm_setcred(pam_handle_t *pamh, int flags, int argc, const char **argv) {
    (void)pamh; (void)flags; (void)argc; (void)argv;
    return PAM_SUCCESS;
}
