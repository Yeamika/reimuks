/* SPDX-License-Identifier: GPL-2.0-only */
#include "controls.h"
#define POWER "/usr/libexec/w202-power-control"
#define GNSS_HELPER "/usr/libexec/w202-gnss-control"
#define TORCH_HELPER "/usr/libexec/w202-torch-control"
char *controls_status(void){struct controls c={.state={-1,-1,-1,-1,-1,-1,-1}};network_status(&c);char *gnss=helper_status(GNSS_HELPER);struct json j;
    if(gnss){if(jparse(&j,gnss))c.state[GNSS]=jbool(&j,jget(&j,0,"power_requested"));free(j.v);free(gnss);}
    c.power=helper_status(POWER);if(c.power){if(jparse(&j,c.power)){int a=jget(&j,0,"available");if(jbool(&j,jget(&j,a,"fast_charge"))==1)c.state[FAST]=jbool(&j,jget(&j,0,"fast_charge"));if(jbool(&j,jget(&j,a,"charging"))==1)c.state[SEPARATION]=jbool(&j,jget(&j,0,"separation"));}free(j.v);}
    c.torch=helper_status(TORCH_HELPER);if(c.torch){int64_t v;if(jparse(&j,c.torch)&&jlong(&j,jget(&j,0,"brightness"),&v)&&v>=0)c.state[TORCH]=v>0;free(j.v);}
    char *out=NULL;size_t size=0;FILE *f=open_memstream(&out,&size);fputs("{\"schema\":1,\"ok\":true,\"states\":{",f);for(int i=0;i<CONTROL_COUNT;i++){if(i)fputc(',',f);json_string(f,names[i]);fprintf(f,":%s",truth(c.state[i]));}fputs("},\"capabilities\":{",f);
    for(int i=0;i<CONTROL_COUNT;i++){if(i)fputc(',',f);json_string(f,names[i]);fprintf(f,":{\"available\":%s,\"reason\":%s}",c.state[i]<0?"false":"true",c.state[i]<0?"\"backend-unavailable\"":"null");}
    fprintf(f,"},\"power\":%s,\"torch\":%s,\"protocol\":",c.power?c.power:"{}",c.torch?c.torch:"{}");char *protocol=NULL;if(c.power){if(jparse(&j,c.power))protocol=jtext(&j,jget(&j,0,"protocol"));free(j.v);}json_string(f,protocol?protocol:"");char *usb=helper_status("/usr/libexec/w202-usb-settings");fprintf(f,",\"usb\":%s}",usb?usb:"{}");free(usb);fclose(f);free(protocol);free(c.power);free(c.torch);return out;
}
int controls_change(const char *action){
    if(!strncmp(action,"usb-",4)){char mode[8],extra;int on,mask;if(sscanf(action,"usb-%7[^-]-%d-%d%c",mode,&on,&mask,&extra)!=3||(strcmp(mode,"auto")&&strcmp(mode,"device")&&strcmp(mode,"host"))||(on!=0&&on!=1)||mask<1||mask>3)return -1;char *a[]={"/usr/bin/pkexec","/usr/libexec/w202-usb-settings",(char*)action,NULL};return run_command(a,90,NULL);}

    const char *mode[]={"mode-auto","mode-pps","mode-pd5v","mode-pd9v"};for(int i=0;i<4;i++)if(!strcmp(action,mode[i])){char *a[]={"/usr/bin/pkexec",POWER,(char*)action,NULL};return run_command(a,75,NULL);}
    if(!strncmp(action,"torch-",6)&&strlen(action)==7&&action[6]>='0'&&action[6]<='8'){char *a[]={"/usr/bin/pkexec",TORCH_HELPER,(char*)action+6,NULL};return run_command(a,30,NULL);}
    for(int i=0;i<CONTROL_COUNT;i++)for(int on=0;on<=1;on++){char expected[40];snprintf(expected,sizeof(expected),"%s-%s",names[i],on?"on":"off");if(strcmp(action,expected))continue;
        if(i<=BLUETOOTH)return network_change(names[i],on);const char *helper=i==GNSS?GNSS_HELPER:i==TORCH?TORCH_HELPER:POWER;
        const char *command=i==GNSS?(on?"start":"stop"):i==FAST?(on?"fast-on":"fast-off"):i==SEPARATION?(on?"charge-inhibit":"charge-auto"):(on?"1":"0");char *a[]={"/usr/bin/pkexec",(char*)helper,(char*)command,NULL};return run_command(a,75,NULL);
    }return -1;
}
int main(int argc,char **argv){if(argc!=2)return json_error("Expected one action");if(strcmp(argv[1],"status")&&controls_change(argv[1]))return json_error("Unsupported action, operation failed or authorization cancelled");char *s=controls_status();puts(s);free(s);return 0;}
