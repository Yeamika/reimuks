#include <assert.h>
#include <stdio.h>
#include "../../../overlays/services/powerkey/src/powerkey-state.h"
#define power_key_event(state, value, time_ms) \
    reimuks_powerkey_event((state), (value), (time_ms), 750)
int main(void) {
    struct reimuks_powerkey_state s = {0};
    assert(power_key_event(&s, 0, 10) == REIMUKS_POWERKEY_NO_ACTION); /* orphan release */
    assert(power_key_event(&s, 1, 100) == REIMUKS_POWERKEY_NO_ACTION);
    assert(power_key_event(&s, 0, 150) == REIMUKS_POWERKEY_SHORT_PRESS);
    assert(power_key_event(&s, 1, 1000) == REIMUKS_POWERKEY_NO_ACTION);
    assert(power_key_event(&s, 0, 1749) == REIMUKS_POWERKEY_SHORT_PRESS);
    assert(power_key_event(&s, 1, 2000) == REIMUKS_POWERKEY_NO_ACTION);
    assert(power_key_event(&s, 0, 2750) == REIMUKS_POWERKEY_LONG_PRESS);
    assert(power_key_event(&s, 1, 3000) == REIMUKS_POWERKEY_NO_ACTION);
    assert(power_key_event(&s, 2, 3300) == REIMUKS_POWERKEY_NO_ACTION); /* repeat */
    assert(power_key_event(&s, 1, 3500) == REIMUKS_POWERKEY_NO_ACTION); /* duplicate */
    assert(power_key_event(&s, 0, 3900) == REIMUKS_POWERKEY_LONG_PRESS);
    assert(power_key_event(&s, 1, 4000) == REIMUKS_POWERKEY_NO_ACTION);
    assert(power_key_event(&s, 0, 3999) == REIMUKS_POWERKEY_NO_ACTION); /* invalid time */
    assert(power_key_event(&s, 1, 5000) == REIMUKS_POWERKEY_NO_ACTION);
    s.pressed = false; /* SYN_DROPPED resets an in-progress press */
    assert(power_key_event(&s, 0, 5100) == REIMUKS_POWERKEY_NO_ACTION);
    assert(power_key_event(&s, 1, 6000) == REIMUKS_POWERKEY_NO_ACTION);
    assert(power_key_event(&s, 0, 6100) == REIMUKS_POWERKEY_SHORT_PRESS);
    puts("power key short/long/repeat/dropped/orphan/timestamp checks passed");
}
