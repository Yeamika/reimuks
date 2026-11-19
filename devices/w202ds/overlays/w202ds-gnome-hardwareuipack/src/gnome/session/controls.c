/* SPDX-License-Identifier: GPL-2.0-only */
#include "session.h"

#define ROTATION_SCHEMA "org.gnome.settings-daemon.peripherals.touchscreen"
#define KEYBOARD_SCHEMA "org.gnome.desktop.a11y.applications"

static int setting_bool(const char *operation, const char *schema, const char *key)
{
    char *args[] = {"/usr/bin/gsettings", (char *)operation,
                    (char *)schema, (char *)key, NULL};
    char *text = NULL;
    int value = -1;
    if (!run_command(args, 5, &text) && text) {
        char *start = text;
        while (*start && isspace((unsigned char)*start)) start++;
        size_t length = strlen(start);
        while (length && isspace((unsigned char)start[length - 1])) start[--length] = 0;
        if (!strcmp(start, "true")) value = 1;
        if (!strcmp(start, "false")) value = 0;
    }
    free(text);
    return value;
}

static int set_bool(const char *schema, const char *key, bool value)
{
    if (setting_bool("writable", schema, key) != 1) return -1;
    char *args[] = {"/usr/bin/gsettings", "set", (char *)schema,
                    (char *)key, value ? "true" : "false", NULL};
    if (run_command(args, 5, NULL)) return -1;
    return setting_bool("get", schema, key) == (int)value ? 0 : -1;
}

int main(int argc, char **argv)
{
    if (argc != 2) return json_error("Expected one action");
    const char *action = argv[1];
    const char *schema = NULL, *key = NULL;
    bool value = false;
    if (!strcmp(action, "rotation-on") || !strcmp(action, "rotation-off")) {
        schema = ROTATION_SCHEMA;
        key = "orientation-lock";
        value = !strcmp(action, "rotation-off");
    } else if (!strcmp(action, "keyboard-on") || !strcmp(action, "keyboard-off")) {
        schema = KEYBOARD_SCHEMA;
        key = "screen-keyboard-enabled";
        value = !strcmp(action, "keyboard-on");
    } else if (!strcmp(action, "tablet-on") || !strcmp(action, "tablet-off")) {
        return json_error("Manual tablet override is not provided by this GNOME adapter");
    }
    if (schema) {
        if (set_bool(schema, key, value)) return json_error("Cannot apply GNOME session setting");
        action = "status";
    }
    char *shared = session_device_request(action);
    if (!shared) return json_error("Device request failed");
    int locked = setting_bool("get", ROTATION_SCHEMA, "orientation-lock");
    int enabled = locked < 0 ? -1 : !locked;
    int keyboard = setting_bool("get", KEYBOARD_SCHEMA, "screen-keyboard-enabled");
    char rotation[96];
    snprintf(rotation, sizeof(rotation), "{\"enabled\":%s,\"locked\":%s}",
             truth(enabled), truth(locked));
    int result = session_status(shared, enabled, -1, keyboard, rotation);
    free(shared);
    return result;
}
