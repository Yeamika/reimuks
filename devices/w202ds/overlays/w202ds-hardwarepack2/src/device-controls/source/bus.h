/* SPDX-License-Identifier: GPL-2.0-only */
#include "native.h"
#define NM "org.freedesktop.NetworkManager"
#define PROPS "org.freedesktop.DBus.Properties"
static char *bus_run(bool user,const char *const args[]){char *a[40]={"/usr/bin/busctl",user?"--user":"--system","--json=short","--timeout=4s"};int n=4;for(int i=0;args[i]&&n<39;i++)a[n++]=(char*)args[i];a[n]=NULL;char *out=NULL;if(run_command(a,6,&out)){free(out);return NULL;}return out;}
static char *bus_property(bool user,const char *service,const char *path,const char *interface,const char *key){const char *a[]={"get-property",service,path,interface,key,NULL};return bus_run(user,a);}
/* get-property serializes a single value directly; method replies use arrays. */
static int bus_boolean_json(const char *s){if(!s)return -1;struct json j;int r=-1;if(jparse(&j,s)&&jeq(&j,jget(&j,0,"type"),"b"))r=jbool(&j,jget(&j,0,"data"));free(j.v);return r;}
static int bus_bool(bool user,const char *service,const char *path,const char *interface,const char *key){char *s=bus_property(user,service,path,interface,key);int r=bus_boolean_json(s);free(s);return r;}
static int bus_set(bool user,const char *service,const char *path,const char *interface,const char *key,bool enabled){const char *a[]={"call",service,path,PROPS,"Set","ssv",interface,key,"b",enabled?"true":"false",NULL};char *s=bus_run(user,a);if(!s)return -1;free(s);return 0;}
static const char *truth(int value){return value<0?"null":value?"true":"false";}
