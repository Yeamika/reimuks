/* SPDX-License-Identifier: GPL-2.0-only */
#include "native.h"
int main(int argc,char **argv){(void)argv;if(argc!=1||geteuid())return json_error("Expected privileged call without arguments");glob_t g={0};glob("/sys/class/input/event*",0,NULL,&g);char *event=NULL;int matches=0;
    for(size_t i=0;i<g.gl_pathc;i++){char *p=path_join(g.gl_pathv[i],"device/name"),*name=read_text(p);free(p);if(name&&!strcmp(name,"W202DS Tablet Mode")){matches++;free(event);event=realpath(g.gl_pathv[i],NULL);}free(name);}globfree(&g);if(matches!=1||!event||strncmp(event,"/sys/devices/platform/zsk_keyboard/",sizeof("/sys/devices/platform/zsk_keyboard/")-1)){free(event);return json_error("Unexpected tablet switch parent");}
    char *p=path_join(event,"device/capabilities/sw"),*sw=read_text(p),*end;free(p);errno=0;unsigned long value=sw?strtoul(sw,&end,16):0;bool valid=sw&&!errno&&end!=sw&&!*end&&value==2;free(sw);if(!valid){free(event);return json_error("Unexpected tablet switch capabilities");}
    char *remove[]={"/usr/bin/udevadm","trigger","--action=remove",event,NULL},*add[]={"/usr/bin/udevadm","trigger","--action=add",event,NULL};int r=run_command(remove,5,NULL)||run_command(add,5,NULL);free(event);return r?1:0;
}
