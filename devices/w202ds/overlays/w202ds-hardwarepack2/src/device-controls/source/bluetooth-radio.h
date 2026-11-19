/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef W202_BLUETOOTH_RADIO_H
#define W202_BLUETOOTH_RADIO_H
/* Restore only this HCI controller. Never unblock GPS, Wi-Fi, another
 * adapter, or a hardware switch while restoring a saved BlueZ preference. */
static int bluetooth_unblock(const char *adapter)
{
    const char prefix[] = "/org/bluez/";
    if (strncmp(adapter, prefix, sizeof(prefix) - 1)) return -1;
    const char *name = adapter + sizeof(prefix) - 1;
    if (strncmp(name, "hci", 3) || !isdigit((unsigned char)name[3]))
        return -1;
    for (const char *p = name + 3; *p; p++)
        if (!isdigit((unsigned char)*p)) return -1;
    char *pattern = path_join(sysroot(), "class/rfkill/rfkill*");
    glob_t matches = {0};
    int result = 0, found = glob(pattern, 0, NULL, &matches);
    free(pattern);
    if (found && found != GLOB_NOMATCH) result = -1;
    for (size_t i = 0; i < matches.gl_pathc; i++) {
        char *path = path_join(matches.gl_pathv[i], "name");
        char *label = read_text(path); free(path);
        path = path_join(matches.gl_pathv[i], "type");
        char *type = read_text(path); free(path);
        bool selected = label && type && !strcmp(label, name) && !strcmp(type, "bluetooth");
        free(label); free(type);
        if (!selected) continue;
        path = path_join(matches.gl_pathv[i], "hard");
        char *hard = read_text(path); free(path);
        if (!hard || strcmp(hard, "0")) result = -1;
        else {
            path = path_join(matches.gl_pathv[i], "soft");
            char *soft = read_text(path);
            if (!soft || (strcmp(soft, "0") && strcmp(soft, "1"))) result = -1;
            else if (!strcmp(soft, "1") && write_text(path, "0")) result = -1;
            free(soft); free(path);
        }
        free(hard);
    }
    globfree(&matches);
    return result;
}
#endif
