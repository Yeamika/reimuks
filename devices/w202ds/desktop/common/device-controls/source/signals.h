/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef W202_SIGNALS_H
#define W202_SIGNALS_H
/* Only opaque handles from libsystemd's stable public sd-bus API are used.
 * Normal builds use the distro headers. The ABI-only declarations also permit
 * reduced cross toolchains without copying any private systemd structures. */
#if __has_include(<systemd/sd-bus.h>)
#include <systemd/sd-bus.h>
#else
typedef struct sd_bus sd_bus;
typedef struct sd_bus_message sd_bus_message;
typedef struct sd_bus_slot sd_bus_slot;
typedef struct sd_bus_error sd_bus_error;
typedef int (*sd_bus_message_handler_t)(sd_bus_message *,void *,sd_bus_error *);
extern int sd_bus_open_system(sd_bus **);
extern int sd_bus_open_user(sd_bus **);
extern sd_bus *sd_bus_unref(sd_bus *);
extern int sd_bus_add_match(sd_bus *,sd_bus_slot **,const char *,sd_bus_message_handler_t,void *);
extern int sd_bus_process(sd_bus *,sd_bus_message **);
extern int sd_bus_wait(sd_bus *,uint64_t);
extern int sd_bus_message_read(sd_bus_message *,const char *,...);
extern int sd_bus_message_skip(sd_bus_message *,const char *);
extern int sd_bus_message_enter_container(sd_bus_message *,char,const char *);
extern int sd_bus_message_exit_container(sd_bus_message *);
extern const char *sd_bus_message_get_member(sd_bus_message *);
extern const char *sd_bus_message_get_interface(sd_bus_message *);
#endif
static int changed_boolean(sd_bus_message *m,const char *interface,const char *key,int *value){const char *iface,*name;if(sd_bus_message_read(m,"s",&iface)<0||strcmp(iface,interface))return 0;if(sd_bus_message_enter_container(m,'a',"{sv}")<0)return 0;
    while(sd_bus_message_enter_container(m,'e',"sv")>0){if(sd_bus_message_read(m,"s",&name)<0)return 0;if(!strcmp(name,key)){if(sd_bus_message_enter_container(m,'v',"b")<0||sd_bus_message_read(m,"b",value)<0)return 0;return 1;}if(sd_bus_message_skip(m,"v")<0||sd_bus_message_exit_container(m)<0)return 0;}return 0;
}
#endif
