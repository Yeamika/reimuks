/* SPDX-License-Identifier: GPL-2.0-only */
#include "native.h"
struct state {int power;char *service;};
static struct state status(void){struct state s={-1,NULL};char *pattern=path_join(sysroot(),"class/rfkill/rfkill*");glob_t g={0};glob(pattern,0,NULL,&g);free(pattern);int count=0;for(size_t i=0;i<g.gl_pathc;i++){char *p=path_join(g.gl_pathv[i],"name"),*name=read_text(p);free(p);if(name&&!strcmp(name,"w202ds-gnss")){p=path_join(g.gl_pathv[i],"soft");char *v=read_text(p);free(p);s.power=v&&!strcmp(v,"0")?1:v&&!strcmp(v,"1")?0:-1;free(v);count++;}free(name);}globfree(&g);if(count!=1)s.power=-1;
    char *args[]={"/usr/bin/systemctl","show","w202-gnss.service","--property=ActiveState","--value",NULL};if(run_command(args,30,&s.service)){free(s.service);s.service=NULL;}else {size_t n=strlen(s.service);while(n&&isspace((unsigned char)s.service[n-1]))s.service[--n]=0;}return s;
}
int main(int argc,char **argv){if(argc!=2||(strcmp(argv[1],"status")&&strcmp(argv[1],"start")&&strcmp(argv[1],"stop")))return json_error("Expected status, start or stop");struct state before=status();if(!before.service)return json_error("GNSS service unavailable");
    bool start=!strcmp(argv[1],"start"),stop=!strcmp(argv[1],"stop");if(start||stop){if(!native_root())return json_error("Administrator authorization required");if(start&&strcmp(before.service,"active")&&strcmp(before.service,"activating")&&before.power!=0)return json_error("GNSS unavailable or owned by another session");
        if(stop||(strcmp(before.service,"active")&&strcmp(before.service,"activating"))){char *a[]={"/usr/bin/systemctl",start?"start":"stop","w202-gnss.service",NULL};if(run_command(a,30,NULL))return json_error("GNSS service request failed");}}
    free(before.service);struct state after=status();if(!after.service)return json_error("GNSS status unavailable");if(stop&&after.power!=0)return json_error("GNSS power release not confirmed");fputs("{\"service\":",stdout);json_string(stdout,after.service);printf(",\"power_requested\":%s}\n",after.power<0?"null":after.power?"true":"false");free(after.service);return 0;
}
