/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef REIMUKS_POWERKEY_STATE_H
#define REIMUKS_POWERKEY_STATE_H
#include <stdbool.h>
#include <stdint.h>

struct reimuks_powerkey_state {
    bool pressed;
    uint64_t started;
};

enum reimuks_powerkey_event_result {
    REIMUKS_POWERKEY_NO_ACTION,
    REIMUKS_POWERKEY_SHORT_PRESS,
    REIMUKS_POWERKEY_LONG_PRESS,
};

static inline enum reimuks_powerkey_event_result
reimuks_powerkey_event(struct reimuks_powerkey_state *state, int value,
                       uint64_t time_ms, uint64_t short_press_ms)
{
    if (value == 1 && !state->pressed) {
        state->pressed = true;
        state->started = time_ms;
    } else if (value == 0 && state->pressed) {
        state->pressed = false;
        if (time_ms < state->started)
            return REIMUKS_POWERKEY_NO_ACTION;
        return time_ms - state->started < short_press_ms ?
            REIMUKS_POWERKEY_SHORT_PRESS : REIMUKS_POWERKEY_LONG_PRESS;
    }
    return REIMUKS_POWERKEY_NO_ACTION;
}

#endif
