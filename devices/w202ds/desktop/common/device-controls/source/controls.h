/* SPDX-License-Identifier: GPL-2.0-only */
#include "bus.h"
enum control_id {WIFI,CELLULAR,BLUETOOTH,GNSS,FAST,SEPARATION,TORCH,CONTROL_COUNT};
static const char *const names[]={"wifi","cellular","bluetooth","gnss","fast","separation","torch"};
struct controls {int state[CONTROL_COUNT];char *power,*torch;};
void network_status(struct controls *c);
int network_change(const char *kind,bool enabled);
char *controls_status(void);
int controls_change(const char *action);
