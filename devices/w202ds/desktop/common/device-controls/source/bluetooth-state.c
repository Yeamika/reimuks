/* SPDX-License-Identifier: GPL-2.0-only */
#include "bus.h"
#include "signals.h"
#define STATE "/var/lib/reimuks/bluetooth-power.json"
struct adapter {char *address,*path;int saved,current;int64_t restore;bool seen;};
static struct adapter entries[32];static int count;static volatile sig_atomic_t stopping;
static void stop(int s){stopping=s;}
static void save(void){char tmp[128];snprintf(tmp,sizeof(tmp),STATE".tmp.%ld",(long)getpid());int fd=open(tmp,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);if(fd<0)return;FILE *f=fdopen(fd,"w");fputc('{',f);for(int i=0;i<count;i++){if(i)fputc(',',f);json_string(f,entries[i].address);fprintf(f,":%s",truth(entries[i].saved));}fputs("}\n",f);bool bad=fflush(f)||fsync(fd);if(fclose(f))bad=true;if(bad||rename(tmp,STATE))unlink(tmp);}
static void load(void){char *text=read_text(STATE);if(!text)return;struct json j;if(jparse(&j,text)&&j.v[0].type=='{')for(int i=1;i<j.v[0].next&&count<32;){int value=i+1;char *address=jtext(&j,i);int state=jbool(&j,value);if(address&&strlen(address)==17&&state>=0)entries[count++]=(struct adapter){.address=address,.saved=state,.current=-1};else free(address);i=j.v[value].next;}free(j.v);free(text);}
static int refresh(void){const char *a[]={"call","org.bluez","/","org.freedesktop.DBus.ObjectManager","GetManagedObjects",NULL};char *text=bus_run(false,a);if(!text)return -1;struct json j;bool valid=jparse(&j,text);if(!valid){free(j.v);free(text);return -1;}int root=jidx(&j,jget(&j,0,"data"),0);if(root<0||j.v[root].type!='{'){free(j.v);free(text);return -1;}for(int i=0;i<count;i++)entries[i].seen=false;
    for(int i=root+1;i<j.v[root].next;){int value=i+1,a=jget(&j,value,"org.bluez.Adapter1");if(a>=0){char *address=jtext(&j,jget(&j,jget(&j,a,"Address"),"data")),*path=jtext(&j,i);int current=jbool(&j,jget(&j,jget(&j,a,"Powered"),"data"));if(address&&path&&current>=0){int slot=-1;for(int k=0;k<count;k++)if(!strcmp(entries[k].address,address))slot=k;
        if(slot<0&&count<32){slot=count++;entries[slot]=(struct adapter){.address=strdup(address),.saved=current,.current=-1};save();}
        if(slot>=0){struct adapter *e=&entries[slot];e->seen=true;if(!e->path||strcmp(e->path,path)){free(e->path);e->path=strdup(path);e->restore=mono_ms()+1500;}else if(!e->restore&&e->saved!=current){e->saved=current;save();}e->current=current;}}
        free(address);free(path);}i=j.v[value].next;}
    for(int i=0;i<count;i++)if(!entries[i].seen){free(entries[i].path);entries[i].path=NULL;entries[i].restore=0;}free(j.v);free(text);return 0;
}
static bool refresh_pending;
static int changed(sd_bus_message *m,void *data,sd_bus_error *error){(void)data;(void)error;const char *member=sd_bus_message_get_member(m);if(member&&!strcmp(member,"NameOwnerChanged")){for(int i=0;i<count;i++){free(entries[i].path);entries[i].path=NULL;entries[i].restore=0;}}if(member&&(!strcmp(member,"PropertiesChanged")||!strcmp(member,"InterfacesAdded")||!strcmp(member,"InterfacesRemoved")||!strcmp(member,"NameOwnerChanged")))refresh_pending=true;return 0;}
int main(void){signal(SIGINT,stop);signal(SIGTERM,stop);umask(0077);load();sd_bus *bus=NULL;if(sd_bus_open_system(&bus)<0)return 1;if(sd_bus_add_match(bus,NULL,"type='signal',sender='org.bluez'",changed,NULL)<0||sd_bus_add_match(bus,NULL,"type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0='org.bluez'",changed,NULL)<0){sd_bus_unref(bus);return 1;}int result=0;int64_t retry=0;
    while(!stopping&&!result){int r=sd_bus_process(bus,NULL);if(r<0){result=1;break;}if(r>0)continue;
        if(refresh_pending||mono_ms()>=retry){refresh_pending=false;int failed=refresh();retry=mono_ms()+(failed?2000:5000);if(failed){for(int i=0;i<count;i++){free(entries[i].path);entries[i].path=NULL;entries[i].restore=0;}}}
        for(int i=0;i<count;i++){struct adapter *e=&entries[i];if(e->path&&e->restore&&mono_ms()>=e->restore){if(bus_set(false,"org.bluez",e->path,"org.bluez.Adapter1","Powered",e->saved)){fputs("Bluetooth restore deferred\n",stderr);e->restore=mono_ms()+2000;}else e->restore=0;}}sd_bus_wait(bus,100000);
    }sd_bus_unref(bus);for(int i=0;i<count;i++){free(entries[i].address);free(entries[i].path);}return stopping?0:result;
}
