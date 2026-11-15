/* SPDX-License-Identifier: GPL-2.0-only */
#include "native.h"
#define HELPER "/usr/libexec/w202-usb-control"
struct settings {char mode[8];int enabled,mask;};
static bool valid(struct settings *s){return (!strcmp(s->mode,"auto")||!strcmp(s->mode,"device")||!strcmp(s->mode,"host"))&&(s->enabled==0||s->enabled==1)&&s->mask>=1&&s->mask<=3;}
static const char *directory(void){
#ifdef W202_TESTING
const char *v=getenv("W202_CONFIG_ROOT");if(v)return v;
#endif
return "/var/lib/reimuks";
}
static int load(struct settings *s){*s=(struct settings){"auto",1,3};char *p=path_join(directory(),"usb.conf");int fd=open(p,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);free(p);if(fd<0)return errno==ENOENT?0:-1;struct stat st;char text[80]={0};int n=fstat(fd,&st)?-1:read(fd,text,sizeof(text)-1);close(fd);char extra;if(n<=0||!S_ISREG(st.st_mode)||sscanf(text,"%7s %d %d %c",s->mode,&s->enabled,&s->mask,&extra)!=3||!valid(s))return -1;return 1;}
static int save(struct settings *s){char *p=path_join(directory(),"usb.conf"),*tmp=path_join(directory(),"usb.conf.new");int fd=open(tmp,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0644);if(fd<0){free(p);free(tmp);return -1;}char line[40];int n=snprintf(line,sizeof(line),"%s %d %d\n",s->mode,s->enabled,s->mask);bool bad=write(fd,line,n)!=n||fsync(fd);if(close(fd))bad=true;if(!bad&&rename(tmp,p))bad=true;if(bad)unlink(tmp);free(p);free(tmp);return bad?-1:0;}
static int status(void){struct settings s;int loaded=load(&s);char *actual=helper_status(HELPER);printf("{\"ok\":true,\"configuration_valid\":%s,\"requested_mode\":",loaded<0?"false":"true");json_string(stdout,loaded<0?NULL:s.mode);printf(",\"enabled\":%s,\"acm\":%s,\"ncm\":%s,\"actual\":%s}\n",loaded<0?"null":s.enabled?"true":"false",loaded<0?"null":s.mask&1?"true":"false",loaded<0?"null":s.mask&2?"true":"false",actual?actual:"{}");free(actual);return 0;}
int main(int argc,char **argv){if(argc!=2)return json_error("Expected USB action");if(!strcmp(argv[1],"status"))return status();bool reapply=!strcmp(argv[1],"reapply");struct settings s;char trailing;
    if(!reapply&&(sscanf(argv[1],"usb-%7[^-]-%d-%d%c",s.mode,&s.enabled,&s.mask,&trailing)!=3||!valid(&s)))return json_error("Invalid USB settings");if(!native_root())return json_error("Root required");
    if(mkdir(directory(),0755)&&errno!=EEXIST)return json_error("USB state directory unavailable");struct stat st;if(lstat(directory(),&st)||!S_ISDIR(st.st_mode)||st.st_uid!=geteuid()||(st.st_mode&0022))return json_error("Unsafe USB state directory");char *p=path_join(runtime_root(),"w202-usb-settings.lock");int fd=open(p,O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC,0600);free(p);if(fd<0||flock(fd,LOCK_EX)){if(fd>=0)close(fd);return json_error("USB settings busy");}
    int r;if(reapply){int loaded=load(&s);if(loaded<0){close(fd);return json_error("Invalid saved USB configuration");}if(!loaded){char *a[]={"/usr/libexec/w202-usb-gadget","start",NULL};r=run_command(a,40,NULL);close(fd);return r?json_error("Default gadget setup failed"):status();}}
    /* Save intent first. Actual readback remains separate after failure/negotiation. */
    else if(save(&s)){close(fd);return json_error("Could not save USB settings");}
    char *a[]={HELPER,reapply?"rebind":"apply",s.mode,s.enabled?"1":"0",s.mask==1?"acm":s.mask==2?"ncm":"acm,ncm",NULL};r=run_command(a,65,NULL);close(fd);return r?json_error("USB settings saved but not applied; inspect actual mode"):status();}
