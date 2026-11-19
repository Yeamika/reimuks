// SPDX-License-Identifier: GPL-2.0-only
/* Server policy consumes the shared, debounced SW_LID interface. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <linux/input.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

static const char *blank_path = "/sys/class/graphics/fb0/blank";
static volatile sig_atomic_t stopping;

struct lid_policy {
    int desired, applied;
    bool dropped;
};

static int sync_lid(int fd, struct lid_policy *policy)
{
    unsigned long state = 0;
    if (ioctl(fd, EVIOCGSW(sizeof(state)), &state) < 0)
        return -1;
    policy->desired = !!(state & (1UL << SW_LID));
    return 0;
}

static int consume_event(int fd, struct lid_policy *policy,
                         const struct input_event *event)
{
    if (event->type == EV_SYN && event->code == SYN_DROPPED) {
        policy->dropped = true;
    } else if (policy->dropped) {
        if (event->type == EV_SYN && event->code == SYN_REPORT) {
            if (sync_lid(fd, policy))
                return -1;
            policy->dropped = false;
        }
    } else if (event->type == EV_SW && event->code == SW_LID &&
               (event->value == 0 || event->value == 1)) {
        policy->desired = event->value;
    }
    return 0;
}

static int present_lid(struct lid_policy *policy)
{
    char text[16] = {0};
    int current, rc = -1;
    /* While open, leave subsequent idle/power-key choices to their owner. */
    if (policy->desired < 0 || policy->dropped ||
        (!policy->desired && policy->applied == 0))
        return 0;
    int fd = open(blank_path, O_RDWR | O_CLOEXEC);
    if (fd < 0)
        return -1;
    if (read(fd, text, sizeof(text) - 1) <= 0 ||
        sscanf(text, "%d", &current) != 1 || current < 0 || current > 4) {
        errno = EINVAL;
        goto done;
    }
    int target = policy->desired ? 4 : 0;
    /* fbcon may report FB_BLANK_NORMAL after DRM powers the panel down. */
    bool matches = policy->desired ? current != 0 : current == 0;
    if (!matches) {
        const char *value = policy->desired ? "4\n" : "0\n";
        if (lseek(fd, 0, SEEK_SET) < 0 || write(fd, value, 2) != 2)
            goto done;
    }
    if (policy->applied != policy->desired || !matches)
        printf("lid=%s display=%s\n", policy->desired ? "closed" : "open",
               target ? "off" : "on");
    policy->applied = policy->desired;
    rc = 0;
done:
    close(fd);
    return rc;
}

static int open_lid(void)
{
    glob_t paths = {0};
    int selected = -1;
    if (glob("/dev/input/event*", 0, NULL, &paths)) {
        globfree(&paths);
        return -1;
    }
    for (size_t i = 0; i < paths.gl_pathc; ++i) {
        char name[128] = {0};
        unsigned long switches = 0;
        int fd = open(paths.gl_pathv[i], O_RDONLY | O_NONBLOCK | O_CLOEXEC);
        if (fd < 0)
            continue;
        if (ioctl(fd, EVIOCGNAME(sizeof(name) - 1), name) >= 0 &&
            !strcmp(name, "REIMUKS Lid Switch") &&
            ioctl(fd, EVIOCGBIT(EV_SW, sizeof(switches)), &switches) >= 0 &&
            (switches & (1UL << SW_LID))) {
            printf("watching %s (%s)\n", paths.gl_pathv[i], name);
            selected = fd;
            break;
        }
        close(fd);
    }
    globfree(&paths);
    return selected;
}

static void stop_handler(int number)
{
    (void)number;
    stopping = 1;
}

int main(int argc, char **argv)
{
    if (argc == 3 && !strcmp(argv[1], "--blank"))
        blank_path = argv[2];
    else if (argc != 1) {
        fputs("Usage: w202-server-hall [--blank /sys/class/graphics/fbN/blank]\n", stderr);
        return argc == 2 && !strcmp(argv[1], "--help") ? 0 : 2;
    }
    struct sigaction action = {.sa_handler = stop_handler};
    sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGINT, &action, NULL);
    setvbuf(stdout, NULL, _IOLBF, 0);
    int fd = -1;
    struct lid_policy policy = {.desired = -1, .applied = -1};
    while (!stopping) {
        if (fd < 0) {
            fd = open_lid();
            if (fd < 0) {
                poll(NULL, 0, 1000);
                continue;
            }
            policy = (struct lid_policy){.desired = -1, .applied = -1};
            if (sync_lid(fd, &policy))
                goto reconnect;
        }
        if (present_lid(&policy))
            perror("apply Server lid display policy");
        struct pollfd pending = {.fd = fd, .events = POLLIN};
        int rc = poll(&pending, 1, 1000);
        if (rc < 0 && errno == EINTR)
            continue;
        if (rc < 0 || pending.revents & (POLLERR | POLLHUP | POLLNVAL))
            goto reconnect;
        if (pending.revents & POLLIN) {
            struct input_event events[32];
            ssize_t size = read(fd, events, sizeof(events));
            if (size < 0 && (errno == EAGAIN || errno == EINTR))
                continue;
            if (size <= 0 || size % sizeof(*events))
                goto reconnect;
            for (size_t i = 0; i < (size_t)size / sizeof(*events); ++i)
                if (consume_event(fd, &policy, &events[i]))
                    goto reconnect;
        }
        continue;
reconnect:
        close(fd);
        fd = -1;
        poll(NULL, 0, 1000);
    }
    if (fd >= 0)
        close(fd);
    return 0;
}
