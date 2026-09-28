/* Loads the "sudo" PAM configuration the way sudo does; exits non-zero if it is broken. */
#include <stdio.h>
#include <security/pam_appl.h>
#include <security/openpam.h>

int main(int argc, char **argv) {
    if (argc != 2)
        return 2;
    struct pam_conv conv = {openpam_nullconv, NULL};
    pam_handle_t *h = NULL;
    int r = pam_start("sudo", argv[1], &conv, &h);
    if (r != PAM_SUCCESS) {
        fprintf(stderr, "pam_start failed: %s\n", pam_strerror(h, r));
        return 1;
    }
    pam_end(h, PAM_SUCCESS);
    return 0;
}
