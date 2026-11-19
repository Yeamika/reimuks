/* SPDX-License-Identifier: GPL-2.0-only */
#include "controls.h"
static char *adapters(void){const char *a[]={"call","org.bluez","/","org.freedesktop.DBus.ObjectManager","GetManagedObjects",NULL};return bus_run(false,a);}
void network_status(struct controls *c){
    c->state[WIFI]=bus_bool(false,NM,"/org/freedesktop/NetworkManager",NM,"WirelessHardwareEnabled")==1?bus_bool(false,NM,"/org/freedesktop/NetworkManager",NM,"WirelessEnabled"):-1;
    c->state[CELLULAR]=bus_bool(false,NM,"/org/freedesktop/NetworkManager",NM,"WwanHardwareEnabled")==1?bus_bool(false,NM,"/org/freedesktop/NetworkManager",NM,"WwanEnabled"):-1;
    char *s=adapters();if(!s)return;struct json j;if(jparse(&j,s)){int root=jidx(&j,jget(&j,0,"data"),0);if(root>=0&&j.v[root].type=='{')for(int i=root+1;i<j.v[root].next;){int interfaces=i+1;int a=jget(&j,interfaces,"org.bluez.Adapter1"),b=jbool(&j,jget(&j,jget(&j,a,"Powered"),"data"));if(b>=0)c->state[BLUETOOTH]=c->state[BLUETOOTH]==1||b; i=j.v[interfaces].next;}}free(j.v);free(s);
}
int network_change(const char *kind,bool enabled){
    if(!strcmp(kind,"wifi")||!strcmp(kind,"cellular"))return bus_set(false,NM,"/org/freedesktop/NetworkManager",NM,!strcmp(kind,"wifi")?"WirelessEnabled":"WwanEnabled",enabled);
    if(strcmp(kind,"bluetooth"))return -1;char *s=adapters();if(!s)return -1;struct json j;int count=0,result=0;if(jparse(&j,s)){int root=jidx(&j,jget(&j,0,"data"),0);if(root>=0&&j.v[root].type=='{')for(int i=root+1;i<j.v[root].next;){int v=i+1;if(jget(&j,v,"org.bluez.Adapter1")>=0){char *path=jtext(&j,i);if(!path||bus_set(false,"org.bluez",path,"org.bluez.Adapter1","Powered",enabled))result=-1;free(path);count++;}i=j.v[v].next;}}free(j.v);free(s);return count?result:-1;
}
