/* SPDX-License-Identifier: GPL-2.0-only */
#include "native.h"
#include "signals.h"
#include <assert.h>
extern int sd_bus_request_name(sd_bus *,const char *,uint64_t);
extern int sd_bus_emit_signal(sd_bus *,const char *,const char *,const char *,const char *,...);
extern int sd_bus_flush(sd_bus *);
static int observed=-1;
static int changed(sd_bus_message *m,void *data,sd_bus_error *error){(void)data;(void)error;int value;if(changed_boolean(m,"org.freedesktop.UPower","LidIsClosed",&value))observed=value;return 0;}
int main(void){sd_bus *watch=NULL,*sender=NULL;assert(sd_bus_open_user(&watch)>=0);assert(sd_bus_open_user(&sender)>=0);assert(sd_bus_request_name(sender,"org.reimuks.NativeTest",0)>=0);assert(sd_bus_add_match(watch,NULL,"type='signal',sender='org.reimuks.NativeTest',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged'",changed,NULL)>=0);
    assert(sd_bus_emit_signal(sender,"/test","org.freedesktop.DBus.Properties","PropertiesChanged","sa{sv}as","org.freedesktop.UPower",2,"Unrelated","s","ignore","LidIsClosed","b",1,0)>=0);assert(sd_bus_flush(sender)>=0);int64_t end=mono_ms()+2000;while(observed<0&&mono_ms()<end){assert(sd_bus_process(watch,NULL)>=0);sd_bus_wait(watch,10000);}assert(observed==1);
    assert(sd_bus_emit_signal(sender,"/test","org.freedesktop.DBus.Properties","PropertiesChanged","sa{sv}as","org.freedesktop.UPower",1,"LidIsClosed","b",0,0)>=0);assert(sd_bus_flush(sender)>=0);end=mono_ms()+2000;while(observed!=0&&mono_ms()<end){assert(sd_bus_process(watch,NULL)>=0);sd_bus_wait(watch,10000);}assert(observed==0);sd_bus_unref(watch);sd_bus_unref(sender);puts("Native unprivileged D-Bus subscription and typed properties pass");return 0;
}
