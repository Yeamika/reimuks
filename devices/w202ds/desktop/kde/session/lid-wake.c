/* SPDX-License-Identifier: GPL-2.0-only */
#include "bus.h"
#include "signals.h"
static volatile sig_atomic_t stopping;static int closed=-1;static int64_t pending;
static void stop(int s){stopping=s;}
static void wake(void){if(closed!=0)return;setenv("QT_QPA_PLATFORM","wayland",1);char *a[]={"/usr/bin/kscreen-doctor","--dpms","on",NULL};if(run_command(a,5,NULL))fputs("Lid DPMS restore failed\n",stderr);}
static bool screen_only(void){const char *a[]={"call","org.kde.Solid.PowerManagement","/org/kde/Solid/PowerManagement/Actions/HandleButtonEvents","org.kde.Solid.PowerManagement.Actions.HandleButtonEvents","lidAction",NULL};char *text=bus_run(true,a);if(!text)return false;struct json j;int64_t v;bool ok=jparse(&j,text)&&jlong(&j,jidx(&j,jget(&j,0,"data"),0),&v)&&v==64;free(j.v);free(text);return ok;}
static int changed(sd_bus_message *m,void *data,sd_bus_error *error){(void)data;(void)error;int next;if(changed_boolean(m,"org.freedesktop.UPower","LidIsClosed",&next)){int old=closed;closed=next;pending=0;if(old==1&&closed==0&&screen_only()){wake();pending=mono_ms()+1000;}}return 0;}
int main(void){signal(SIGINT,stop);signal(SIGTERM,stop);sd_bus *bus=NULL;if(sd_bus_open_system(&bus)<0)return 1;if(sd_bus_add_match(bus,NULL,"type='signal',sender='org.freedesktop.UPower',path='/org/freedesktop/UPower',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged'",changed,NULL)<0){sd_bus_unref(bus);return 1;}
    closed=bus_bool(false,"org.freedesktop.UPower","/org/freedesktop/UPower","org.freedesktop.UPower","LidIsClosed");int result=0;while(!stopping){int r=sd_bus_process(bus,NULL);if(r<0){result=1;break;}if(r>0)continue;if(pending&&mono_ms()>=pending){pending=0;wake();}sd_bus_wait(bus,100000);}sd_bus_unref(bus);return result;
}
