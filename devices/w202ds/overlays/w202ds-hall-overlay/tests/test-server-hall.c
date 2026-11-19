// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#undef NDEBUG
#include <stdarg.h>
#include <sys/ioctl.h>
static int hall_test_ioctl(int fd, unsigned long request, ...);
#define ioctl hall_test_ioctl
#define main hall_program_main
#include "../src/hall/hall.c"
#undef main
#undef ioctl
#include <assert.h>

static int source_lid, source_error;

static int hall_test_ioctl(int fd, unsigned long request, ...)
{
    (void)fd;
    assert(request == EVIOCGSW(sizeof(unsigned long)));
    if (source_error) {
        errno = EIO;
        return -1;
    }
    va_list args;
    va_start(args, request);
    unsigned long *bits = va_arg(args, unsigned long *);
    *bits = source_lid ? (1UL << SW_LID) : 0;
    va_end(args);
    return 0;
}

static void write_blank(int value)
{
    FILE *f = fopen(blank_path, "w");
    assert(f);
    fprintf(f, "%d\n", value);
    assert(!fclose(f));
}

static int read_blank(void)
{
    int value = -1;
    FILE *f = fopen(blank_path, "r");
    assert(f && fscanf(f, "%d", &value) == 1);
    fclose(f);
    return value;
}

static void event(struct lid_policy *p, int type, int code, int value)
{
    struct input_event e = {.type = type, .code = code, .value = value};
    assert(!consume_event(123, p, &e));
}

int main(void)
{
    char path[] = "/tmp/reimuks-hall-test-XXXXXX";
    int fd = mkstemp(path);
    assert(fd >= 0);
    close(fd);
    blank_path = path;
    struct lid_policy p = {.desired = -1, .applied = -1};
    write_blank(4);
    assert(!sync_lid(123, &p) && !present_lid(&p));
    assert(read_blank() == 0); /* Initial open restores an already blank console. */
    write_blank(4);
    assert(!present_lid(&p) && read_blank() == 4); /* Preserve later manual off. */
    event(&p, EV_KEY, KEY_POWER, 1);
    assert(p.desired == 0); /* This overlay does not consume power-key policy. */
    event(&p, EV_SW, SW_TABLET_MODE, 1);
    assert(p.desired == 0);
    event(&p, EV_SW, SW_LID, 1);
    assert(!present_lid(&p) && read_blank() == 4);
    write_blank(1);
    assert(!present_lid(&p) && read_blank() == 1); /* fbcon normal-blank is already off. */
    write_blank(0);
    assert(!present_lid(&p) && read_blank() == 4); /* Hold closed across stray wake. */
    event(&p, EV_SYN, SYN_DROPPED, 0);
    event(&p, EV_SW, SW_LID, 0);
    assert(p.desired == 1 && p.dropped);
    assert(!present_lid(&p) && read_blank() == 4);
    source_lid = 0;
    event(&p, EV_SYN, SYN_REPORT, 0);
    assert(!p.dropped && !present_lid(&p) && read_blank() == 0);
    event(&p, EV_SW, SW_LID, 1);
    blank_path = "/no-such-reimuks-test-directory/blank";
    assert(present_lid(&p) < 0 && p.applied == 0);
    blank_path = path;
    assert(!present_lid(&p) && read_blank() == 4); /* Retry failed sysfs update. */
    event(&p, EV_SYN, SYN_DROPPED, 0);
    source_error = 1;
    struct input_event report = {.type = EV_SYN, .code = SYN_REPORT};
    assert(consume_event(123, &p, &report) < 0);
    assert(p.dropped && read_blank() == 4); /* Failed resync must not invent open. */
    source_error = 0;
    source_lid = 1;
    p = (struct lid_policy){.desired = -1, .applied = -1};
    write_blank(0);
    assert(!sync_lid(123, &p) && !present_lid(&p) && read_blank() == 4);
    unlink(path);
    puts("server Hall policy scenarios passed");
    return 0;
}
