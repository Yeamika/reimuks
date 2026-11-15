/* SPDX-License-Identifier: GPL-2.0-only */
#include "../devices/w202ds/desktop/common/device-controls/source/bus.h"
#include <assert.h>
int main(void){
 assert(bus_boolean_json("{\"type\":\"b\",\"data\":true}")==1);
 assert(bus_boolean_json("{\"type\":\"b\",\"data\":false}")==0);
 assert(bus_boolean_json("{\"type\":\"b\",\"data\":[true]}")==-1);
 assert(bus_boolean_json("{\"type\":\"s\",\"data\":true}")==-1);
 assert(bus_boolean_json("{\"type\":\"b\"}")==-1);
 assert(bus_boolean_json("{\"type\":\"b\",\"data\":null}")==-1);
 assert(bus_boolean_json("invalid")==-1);
 assert(bus_boolean_json(NULL)==-1);
 puts("8 bus property boolean cases passed");return 0;
}
