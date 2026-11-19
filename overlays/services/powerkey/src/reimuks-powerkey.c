// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <linux/input.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>
#include "powerkey-state.h"

static const char *setting(const char *name)
{
    const char *value = getenv(name);
    return value && *value ? value : NULL;
}

static int open_power_key(const char *expected_name)
{
    glob_t paths = {0};
    int selected = -1;
    if (glob("/dev/input/event*", 0, NULL, &paths))
        return -1;
    for (size_t i = 0; i < paths.gl_pathc; ++i) {
        char name[128] = {0};
        int fd = open(paths.gl_pathv[i], O_RDONLY | O_CLOEXEC | O_NONBLOCK);
        if (fd < 0)
            continue;
        if (ioctl(fd, EVIOCGNAME(sizeof(name)), name) >= 0 &&
            !strcmp(name, expected_name)) {
            int clockid = CLOCK_MONOTONIC;
            if (ioctl(fd, EVIOCSCLOCKID, &clockid) == 0 &&
                ioctl(fd, EVIOCGRAB, 1) == 0) {
                printf("watching %s (%s)\n", paths.gl_pathv[i], name);
                selected = fd;
                break;
            }
            perror("configure power key");
        }
        close(fd);
    }
    globfree(&paths);
    return selected;
}

static uint64_t short_press_limit(void)
{
    const char *value = setting("REIMUKS_POWERKEY_SHORT_MS");
    char *end = NULL;
    unsigned long long parsed;
    if (!value)
        return 750;
    parsed = strtoull(value, &end, 10);
    if (!end || *end || !parsed || parsed > 60000)
        return 750;
    return (uint64_t)parsed;
}

static int run_action(const char *program, const char *argument)
{
    pid_t child = fork();
    if (child < 0)
        return -1;
    if (child == 0) {
        execl(program, program, argument, (char *)NULL);
        _exit(127);
    }
    int status;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR)
            return -1;
    }
    if (WIFEXITED(status) && WEXITSTATUS(status) == 0)
        return 0;
    errno = EIO;
    return -1;
}

static int dispatch_action(const char *action)
{
    if (!action || !strcmp(action, "poweroff") || !strcmp(action, "suspend"))
        return run_action("/usr/bin/systemctl", action ? action : "poweroff");
    if (!strcmp(action, "display-toggle"))
        return run_action("/usr/libexec/reimuks-display-toggle", NULL);
    if (!strcmp(action, "ignore"))
        return 0;
    fprintf(stderr, "unsupported power-key action: %s\n", action);
    return -1;
}

int main(void)
{
    const char *input_name = setting("REIMUKS_POWERKEY_INPUT_NAME");
    const char *short_action = setting("REIMUKS_POWERKEY_SHORT_ACTION");
    const char *long_action = setting("REIMUKS_POWERKEY_LONG_ACTION");
    struct reimuks_powerkey_state state = {0};
    struct input_event events[16];
    bool dropped = false;
    if (!input_name) {
        fputs("REIMUKS_POWERKEY_INPUT_NAME is required\n", stderr);
        return 2;
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    int fd = open_power_key(input_name);
    if (fd < 0) {
        fprintf(stderr, "power-key input unavailable: %s\n", input_name);
        return 1;
    }
    for (;;) {
        struct pollfd pending = {.fd = fd, .events = POLLIN};
        int rc = poll(&pending, 1, -1);
        if (rc < 0 && errno == EINTR)
            continue;
        if (rc < 0 || pending.revents & (POLLERR | POLLHUP | POLLNVAL))
            break;
        ssize_t size = read(fd, events, sizeof(events));
        if (size < 0 && (errno == EINTR || errno == EAGAIN))
            continue;
        if (size <= 0 || size % sizeof(*events))
            break;
        for (size_t i = 0; i < (size_t)size / sizeof(*events); ++i) {
            const struct input_event *event = &events[i];
            if (event->type == EV_SYN && event->code == SYN_DROPPED) {
                state.pressed = false;
                dropped = true;
            } else if (event->type == EV_SYN && event->code == SYN_REPORT) {
                dropped = false;
            } else if (!dropped && event->type == EV_KEY && event->code == KEY_POWER) {
                uint64_t ms = (uint64_t)event->input_event_sec * 1000 +
                              event->input_event_usec / 1000;
                enum reimuks_powerkey_event_result result =
                    reimuks_powerkey_event(&state, event->value, ms,
                                           short_press_limit());
                if ((result == REIMUKS_POWERKEY_SHORT_PRESS &&
                     dispatch_action(short_action ? short_action : "poweroff")) ||
                    (result == REIMUKS_POWERKEY_LONG_PRESS &&
                     dispatch_action(long_action ? long_action : "ignore")))
                    perror("power-key action");
            }
        }
    }
    close(fd);
    return 1;
}
