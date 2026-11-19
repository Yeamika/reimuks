/* SPDX-License-Identifier: GPL-2.0-only */
#include "bus.h"

static char *object_reply(const char *reply)
{
    struct json json;
    char *path = NULL;
    if (jparse(&json, reply) && jeq(&json, jget(&json, 0, "type"), "o"))
        path = jtext(&json, jidx(&json, jget(&json, 0, "data"), 0));
    free(json.v);
    return path;
}

/* A failed nl80211 open can leave this cfg80211-only board on WEXT.
 * Recreate only that stale supplicant interface. NM retains all connection
 * policy, credentials and the user's radio switch. */
int main(void)
{
    if (bus_bool(false, NM, "/org/freedesktop/NetworkManager", NM,
                 "WirelessEnabled") != 1)
        return 0;
    const char *device[] = {"call", NM, "/org/freedesktop/NetworkManager", NM,
        "GetDeviceByIpIface", "s", "wlan0", NULL};
    char *reply = bus_run(false, device);
    if (!reply)
        return 0;
    char *path = object_reply(reply);
    free(reply);
    int managed = path ? bus_bool(false, NM, path,
        "org.freedesktop.NetworkManager.Device", "Managed") : -1;
    free(path);
    if (managed != 1)
        return 0;

    /* The service has a private /tmp; use the shared control directory for
     * the client's reply socket as well as the daemon socket. */
    char *command[] = {"/usr/sbin/wpa_cli", "-s", "/run/wpa_supplicant",
        "-i", "wlan0", "status", "driver", NULL};
    char *status = NULL;
    if (run_command(command, 4, &status)) {
        free(status);
        return 0;
    }
    /* Measured driver dumps: nl80211 identifies phyname; WEXT only supplies
     * the common ifindex/ifname/addr fields. Never act on an unknown reply. */
    bool stale = status && strstr(status, "ifname=wlan0\n") &&
                 !strstr(status, "phyname=");
    free(status);
    if (!stale)
        return 0;

    const char *get[] = {"call", "fi.w1.wpa_supplicant1",
        "/fi/w1/wpa_supplicant1", "fi.w1.wpa_supplicant1", "GetInterface",
        "s", "wlan0", NULL};
    reply = bus_run(false, get);
    if (!reply)
        return 0;
    path = object_reply(reply);
    free(reply);
    if (!path || strncmp(path, "/fi/w1/wpa_supplicant1/Interfaces/",
                         strlen("/fi/w1/wpa_supplicant1/Interfaces/"))) {
        free(path);
        return 0;
    }
    const char *remove[] = {"call", "fi.w1.wpa_supplicant1",
        "/fi/w1/wpa_supplicant1", "fi.w1.wpa_supplicant1", "RemoveInterface",
        "o", path, NULL};
    reply = bus_run(false, remove);
    free(path);
    if (!reply)
        return 1;
    free(reply);
    puts("Removed stale WEXT interface; NetworkManager will retry nl80211");
    return 0;
}
