// SPDX-License-Identifier: GPL-2.0-only
// Console backlight policy; evdev readers never grab or inject input events.
// VT_UPDATE notifications wake poll; no periodic console or touch reads.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <linux/input.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define BACKLIGHT "/sys/class/backlight/w202-backlight/"
#define CONTROL "/run/w202-screen/control"
#define MAX_INPUTS 32
#define CONSOLE "/dev/vcsa"
#define MAX_CONSOLE_BYTES (16 * 1024 * 1024)

static volatile sig_atomic_t stopping;
static bool screen_on;
static bool explicit_off;
static bool watch_lid, lid_closed;
static int restore_brightness = 180, idle_seconds = 300;
static int64_t last_activity;
static int lock_fd = -1;
static int console_fd = -1;
static unsigned char *console_previous, *console_current;
static size_t console_capacity, console_length;
static uint64_t console_changes;
static bool watch_console = true;
static struct input_device {
    int fd; dev_t device; ino_t inode;
    bool lid, closed, dropped;
} inputs[MAX_INPUTS];

static int64_t milliseconds(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) { perror("clock_gettime"); exit(1); }
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static int read_value(const char *name)
{
    char path[256];
    snprintf(path, sizeof(path), "%s%s", BACKLIGHT, name);
    FILE *stream = fopen(path, "r");
    int value = -1;
    if (stream) { if (fscanf(stream, "%d", &value) != 1) value = -1; fclose(stream); }
    return value;
}

static int write_value(const char *name, int value)
{
    char path[256], text[32];
    snprintf(path, sizeof(path), "%s%s", BACKLIGHT, name);
    int fd = open(path, O_WRONLY | O_CLOEXEC);
    if (fd < 0) { perror(path); return -1; }
    int length = snprintf(text, sizeof(text), "%d\n", value);
    ssize_t result = write(fd, text, (size_t)length);
    if (result != length) perror(path);
    close(fd);
    return result == length ? 0 : -1;
}

static int set_screen(bool on, const char *reason)
{
    if (on && lid_closed) return -1;
    if (screen_on == on) return 0;
    int result;
    if (on) {
        int tty = open("/dev/tty1", O_RDWR | O_CLOEXEC);
        if (tty >= 0) { char unblank = 4; ioctl(tty, TIOCLINUX, &unblank); close(tty); }
        result = write_value("brightness", restore_brightness);
        if (!result) result = write_value("bl_power", 0);
    } else {
        int current = read_value("brightness");
        if (current > 0) restore_brightness = current;
        result = write_value("brightness", 0);
        if (!result) result = write_value("bl_power", 4);
    }
    if (result) return -1;
    screen_on = on;
    printf("screen=%s reason=%s brightness=%d\n", on ? "on" : "off", reason, on ? restore_brightness : 0);
    fflush(stdout);
    return 0;
}

static void input_event(const struct input_event *event)
{
    if (lid_closed) return;
    if (event->type == EV_KEY && event->code == KEY_POWER) {
        if (event->value == 1) {
            last_activity = milliseconds();
            bool on = !screen_on;
            if (!set_screen(on, "power-key")) explicit_off = !on;
        }
        return;
    }
    if (event->type == EV_KEY || (event->type == EV_REL && event->value) || event->type == EV_ABS) {
        last_activity = milliseconds();
        explicit_off = false;
        if (!screen_on) set_screen(true, "local-input");
    }
}

static void update_lid(void)
{
    bool closed = false;
    for (int i = 0; i < MAX_INPUTS; i++)
        if (inputs[i].fd >= 0 && inputs[i].lid && inputs[i].closed) closed = true;
    if (closed == lid_closed) return;
    lid_closed = closed;
    last_activity = milliseconds();
    explicit_off = false;
    set_screen(!closed, closed ? "lid-closed" : "lid-open");
}

static void device_event(struct input_device *input, const struct input_event *event)
{
    if (event->type == EV_SYN && event->code == SYN_DROPPED) {
        input->dropped = true;
        return;
    }
    if (input->dropped) {
        if (event->type == EV_SYN && event->code == SYN_REPORT) {
            input->dropped = false;
            unsigned long switches = 0;
            if (input->lid && ioctl(input->fd, EVIOCGSW(sizeof(switches)), &switches) >= 0) {
                input->closed = !!(switches & (1UL << SW_LID));
                update_lid();
            }
        }
        return;
    }
    if (input->lid && event->type == EV_SW && event->code == SW_LID) {
        input->closed = event->value != 0;
        update_lid();
        return;
    }
    input_event(event);
}

static void close_console(void)
{
    if (console_fd >= 0) close(console_fd);
    console_fd = -1;
    free(console_previous); free(console_current);
    console_previous = console_current = NULL;
    console_capacity = console_length = 0;
}

static int console_snapshot(bool baseline)
{
    off_t length = lseek(console_fd, 0, SEEK_END);
    if (length < 4 || length > MAX_CONSOLE_BYTES) return -1;
    size_t size = (size_t)length;
    if (size > console_capacity) {
        unsigned char *previous = malloc(size), *current = malloc(size);
        if (!previous || !current) { free(previous); free(current); return -1; }
        if (console_length) memcpy(previous, console_previous, console_length);
        free(console_previous); free(console_current);
        console_previous = previous; console_current = current;
        console_capacity = size;
    }
    // One read consumes the VT_UPDATE notification before copying the screen.
    // A later update remains pending, including changes made during this read.
    ssize_t count;
    do { count = pread(console_fd, console_current, size, 0); } while (count < 0 && errno == EINTR);
    if (count != length) return -1;
    // Geometry, glyphs and attributes matter; cursor position/blinking does not.
    console_current[2] = console_current[3] = 0;
    bool changed = console_length && (console_length != size ||
                   memcmp(console_previous, console_current, size));
    unsigned char *swap = console_previous;
    console_previous = console_current; console_current = swap;
    console_length = size;
    if (!baseline && changed) {
        console_changes++;
        last_activity = milliseconds();
        if (!screen_on && !explicit_off) set_screen(true, "console-change");
    }
    return 0;
}

static void open_console(void)
{
    if (!watch_console || console_fd >= 0) return;
    console_fd = open(CONSOLE, O_RDONLY | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW);
    if (console_fd < 0) return;
    // Register the notifier before taking the initial snapshot.
    struct pollfd probe = {.fd = console_fd, .events = POLLPRI};
    if (poll(&probe, 1, 0) < 0 || !(probe.revents & POLLPRI) || console_snapshot(true)) {
        fputs("console-watch unavailable\n", stderr);
        close_console();
        return;
    }
    puts("watching=" CONSOLE " mode=VT_UPDATE cursor=ignored");
    fflush(stdout);
}

static void scan_inputs(void)
{
    glob_t paths = {0};
    if (glob("/dev/input/event*", 0, NULL, &paths)) { globfree(&paths); return; }
    for (size_t i = 0; i < paths.gl_pathc; i++) {
        struct stat st;
        if (stat(paths.gl_pathv[i], &st) || !S_ISCHR(st.st_mode)) continue;
        int slot = -1;
        bool present = false;
        for (int j = 0; j < MAX_INPUTS; j++) {
            if (inputs[j].fd >= 0 && inputs[j].device == st.st_rdev && inputs[j].inode == st.st_ino) present = true;
            if (inputs[j].fd < 0 && slot < 0) slot = j;
        }
        if (present || slot < 0) continue;
        int fd = open(paths.gl_pathv[i], O_RDONLY | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW);
        if (fd < 0) continue;
        unsigned long types = 0, switches = 0;
        if (ioctl(fd, EVIOCGBIT(0, sizeof(types)), &types) < 0) { close(fd); continue; }
        bool lid = watch_lid && (types & (1UL << EV_SW)) &&
                   ioctl(fd, EVIOCGBIT(EV_SW, sizeof(switches)), &switches) >= 0 &&
                   (switches & (1UL << SW_LID));
        if (!lid && !(types & ((1UL << EV_KEY) | (1UL << EV_REL) | (1UL << EV_ABS)))) { close(fd); continue; }
        switches = 0;
        if (lid && ioctl(fd, EVIOCGSW(sizeof(switches)), &switches) < 0) { close(fd); continue; }
        char name[128] = {0};
        if (ioctl(fd, EVIOCGNAME(sizeof(name) - 1), name) < 0) strcpy(name, "unknown");
        inputs[slot] = (struct input_device){.fd = fd, .device = st.st_rdev, .inode = st.st_ino,
                                            .lid = lid, .closed = !!(switches & (1UL << SW_LID))};
        printf("watching=%s name=%s\n", paths.gl_pathv[i], name);
        if (lid) update_lid();
    }
    globfree(&paths);
    fflush(stdout);
}

static int parse_seconds(const char *text)
{
    char *end;
    errno = 0;
    long value = strtol(text, &end, 10);
    if (errno || !*text || *end || value < 0 || value > 86400) return -1;
    return (int)value;
}

static int make_socket(void)
{
    int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    if (fd < 0) return -1;
    struct sockaddr_un address = {.sun_family = AF_UNIX};
    strcpy(address.sun_path, CONTROL);
    if (mkdir("/run/w202-screen", 0755) && errno != EEXIST) { close(fd); return -1; }
    lock_fd = open("/run/w202-screen/lock", O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (lock_fd < 0 || flock(lock_fd, LOCK_EX | LOCK_NB)) { close(fd); return -1; }
    if (unlink(CONTROL) && errno != ENOENT) { close(fd); return -1; }
    mode_t old = umask(0077);
    int result = bind(fd, (struct sockaddr *)&address, sizeof(address));
    umask(old);
    if (result || listen(fd, 4)) { close(fd); return -1; }
    return fd;
}

static void control_request(int listener)
{
    int fd = accept4(listener, NULL, NULL, SOCK_CLOEXEC);
    if (fd < 0) return;
    struct timeval limit = {.tv_sec = 1};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &limit, sizeof(limit));
    char command[64], reply[256];
    ssize_t count = recv(fd, command, sizeof(command) - 1, 0);
    bool ok = true;
    if (count <= 0) { close(fd); return; }
    command[count] = 0;
    if (!strcmp(command, "on") || !strcmp(command, "off") || !strcmp(command, "toggle")) {
        last_activity = milliseconds();
        bool on = !strcmp(command, "on") || (!strcmp(command, "toggle") && !screen_on);
        ok = set_screen(on, "control") == 0;
        if (ok) explicit_off = !on;
    } else if (!strncmp(command, "timeout ", 8)) {
        int seconds = parse_seconds(command + 8);
        if (seconds < 0) ok = false;
        else { idle_seconds = seconds; last_activity = milliseconds(); }
    } else if (strcmp(command, "status")) ok = false;
    int total = 0;
    for (int i = 0; i < MAX_INPUTS; i++) total += inputs[i].fd >= 0;
    snprintf(reply, sizeof(reply), "%s screen=%s idle_seconds=%d idle_for=%lld brightness=%d input_devices=%d console_watch=%s console_changes=%llu lid=%s\n",
             ok ? "OK" : "ERROR", screen_on ? "on" : "off", idle_seconds,
             (long long)((milliseconds() - last_activity) / 1000), read_value("brightness"), total,
             console_fd >= 0 ? "events" : watch_console ? "unavailable" : "disabled",
             (unsigned long long)console_changes, watch_lid ? (lid_closed ? "closed" : "open") : "ignored");
    send(fd, reply, strlen(reply), MSG_NOSIGNAL);
    close(fd);
}

static int client(const char *command)
{
    int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
    if (fd < 0) { perror("socket"); return 1; }
    struct sockaddr_un address = {.sun_family = AF_UNIX};
    strcpy(address.sun_path, CONTROL);
    struct timeval limit = {.tv_sec = 3};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &limit, sizeof(limit));
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) ||
        send(fd, command, strlen(command), MSG_NOSIGNAL) < 0) { perror(CONTROL); close(fd); return 1; }
    char reply[256];
    ssize_t count = recv(fd, reply, sizeof(reply) - 1, 0);
    close(fd);
    if (count <= 0) { perror("screen reply"); return 1; }
    reply[count] = 0;
    fputs(reply, stdout);
    return strncmp(reply, "OK ", 3) != 0;
}

static void stop_handler(int signal_number) { (void)signal_number; stopping = 1; }

int main(int argc, char **argv)
{
    if (argc > 1) {
        for (int i = 0; i < 4; i++) {
            const char *actions[] = {"status", "on", "off", "toggle"};
            if (argc == 2 && !strncmp(argv[1], "--", 2) && !strcmp(argv[1] + 2, actions[i])) return client(actions[i]);
        }
        if (argc == 3 && !strcmp(argv[1], "--timeout") && parse_seconds(argv[2]) >= 0) {
            char command[64]; snprintf(command, sizeof(command), "timeout %s", argv[2]); return client(command);
        }
        fprintf(stderr, "Usage: w202-screen [--status|--on|--off|--toggle|--timeout SECONDS]\n");
        return argc == 2 && !strcmp(argv[1], "--help") ? 0 : 2;
    }
    const char *configured = getenv("W202_SCREEN_IDLE_SECONDS");
    if (configured && (idle_seconds = parse_seconds(configured)) < 0) { fputs("Invalid W202_SCREEN_IDLE_SECONDS\n", stderr); return 1; }
    configured = getenv("W202_SCREEN_WATCH_CONSOLE");
    if (configured) {
        if (strcmp(configured, "0") && strcmp(configured, "1")) {
            fputs("Invalid W202_SCREEN_WATCH_CONSOLE\n", stderr); return 1;
        }
        watch_console = !strcmp(configured, "1");
    }
    configured = getenv("W202_SCREEN_WATCH_LID");
    if (configured) {
        if (strcmp(configured, "0") && strcmp(configured, "1")) {
            fputs("Invalid W202_SCREEN_WATCH_LID\n", stderr); return 1;
        }
        watch_lid = !strcmp(configured, "1");
    }
    int brightness = read_value("brightness");
    if (brightness < 0) { perror(BACKLIGHT); return 1; }
    if (brightness > 0) restore_brightness = brightness;
    screen_on = brightness > 0 && read_value("bl_power") == 0;
    for (int i = 0; i < MAX_INPUTS; i++) inputs[i].fd = -1;
    struct sigaction action = {.sa_handler = stop_handler};
    sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, NULL); sigaction(SIGINT, &action, NULL);
    int listener = make_socket();
    if (listener < 0) { perror(CONTROL); return 1; }
    last_activity = milliseconds();
    int64_t scanned = 0;
    while (!stopping) {
        int64_t now = milliseconds();
        if (now - scanned >= 2000) { scan_inputs(); open_console(); scanned = now; }
        struct pollfd fds[MAX_INPUTS + 2] = {{.fd = listener, .events = POLLIN}};
        for (int i = 0; i < MAX_INPUTS; i++) fds[i + 1] = (struct pollfd){.fd = inputs[i].fd, .events = POLLIN};
        fds[MAX_INPUTS + 1] = (struct pollfd){.fd = console_fd, .events = POLLPRI};
        int result = poll(fds, MAX_INPUTS + 2, 1000);
        if (result < 0) { if (errno == EINTR) continue; perror("poll"); break; }
        if (fds[0].revents & POLLIN) control_request(listener);
        if (fds[MAX_INPUTS + 1].revents & POLLPRI) {
            if (console_snapshot(false)) close_console();
        }
        if (fds[MAX_INPUTS + 1].revents & (POLLHUP | POLLERR | POLLNVAL)) close_console();
        for (int i = 0; i < MAX_INPUTS; i++) {
            if (fds[i + 1].revents & POLLIN) {
                struct input_event events[64];
                ssize_t bytes;
                while ((bytes = read(inputs[i].fd, events, sizeof(events))) > 0)
                    for (size_t j = 0; j < (size_t)bytes / sizeof(events[0]); j++) device_event(&inputs[i], &events[j]);
            }
            if (fds[i + 1].revents & (POLLHUP | POLLERR | POLLNVAL)) {
                close(inputs[i].fd); inputs[i].fd = -1; update_lid();
            }
        }
        if (screen_on && idle_seconds && milliseconds() - last_activity >= (int64_t)idle_seconds * 1000)
            set_screen(false, "idle-timeout");
    }
    set_screen(true, "service-stop");
    close(listener); unlink(CONTROL); close(lock_fd);
    for (int i = 0; i < MAX_INPUTS; i++) if (inputs[i].fd >= 0) close(inputs[i].fd);
    close_console();
    return stopping ? 0 : 1;
}
