/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef W202_SESSION_H
#define W202_SESSION_H
#include "bus.h"

/* DE adapters forward hardware actions and add only their session state. */
static char *session_device_request(const char *action)
{
    char *args[] = {"/usr/libexec/w202-device-controls", (char *)action, NULL};
    char *response = NULL;
    if (run_command(args, 150, &response)) {
        free(response);
        return NULL;
    }
    return response;
}

static bool session_field(const struct json *json, int key)
{
    return jeq(json, key, "rotation") || jeq(json, key, "tablet") ||
           jeq(json, key, "keyboard");
}

static int session_status(const char *response, int rotation, int tablet,
                          int keyboard, const char *rotation_json)
{
    struct json core = {0}, detail = {0};
    if (!response || !jparse(&core, response) ||
        jbool(&core, jget(&core, 0, "ok")) != 1) {
        free(core.v);
        return json_error("Invalid device response");
    }
    int states = jget(&core, 0, "states"), caps = jget(&core, 0, "capabilities");
    if (states < 0 || caps < 0 || core.v[states].type != '{' || core.v[caps].type != '{') {
        free(core.v);
        return json_error("Invalid control schema");
    }
    if (!rotation_json || !jparse(&detail, rotation_json) || detail.v[0].type != '{')
        rotation_json = "{}";
    free(detail.v);
    const char *names[] = {"rotation", "tablet", "keyboard"};
    int values[] = {rotation, tablet, keyboard};
    fputc('{', stdout);
    for (int i = 1; i < core.v[0].next;) {
        int value = i + 1;
        if (jeq(&core, i, "rotation")) {
            i = core.v[value].next;
            continue;
        }
        jraw(stdout, &core, i);
        fputc(':', stdout);
        if (value == states || value == caps) {
            fputc('{', stdout);
            for (int key = value + 1; key < core.v[value].next;) {
                int v = key + 1;
                if (!session_field(&core, key)) {
                    jraw(stdout, &core, key);
                    fputc(':', stdout);
                    jraw(stdout, &core, v);
                    fputc(',', stdout);
                }
                key = core.v[v].next;
            }
            for (int n = 0; n < 3; n++) {
                if (n) fputc(',', stdout);
                json_string(stdout, names[n]);
                if (value == states)
                    printf(":%s", truth(values[n]));
                else
                    printf(":{\"available\":%s,\"reason\":%s}",
                           values[n] < 0 ? "false" : "true",
                           values[n] < 0 ? "\"session-backend-unavailable\"" : "null");
            }
            fputc('}', stdout);
        } else {
            jraw(stdout, &core, value);
        }
        fputc(',', stdout);
        i = core.v[value].next;
    }
    printf("\"rotation\":%s}\n", rotation_json);
    free(core.v);
    return 0;
}
#endif
