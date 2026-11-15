/* SPDX-License-Identifier: GPL-2.0-only */
#include "bus.h"
int main(int argc,char **argv){if(argc!=2)return json_error("Expected one action");const char *action=argv[1];bool session=false;for(int i=0;i<4;i++){const char *a[]={"tablet-on","tablet-off","rotation-on","rotation-off"};if(!strcmp(action,a[i]))session=true;}
    if(!strcmp(action,"keyboard-on")||!strcmp(action,"keyboard-off")){
        bool on=!strcmp(action,"keyboard-on");
        if(bus_bool(true,"org.kde.KWin","/VirtualKeyboard","org.kde.kwin.VirtualKeyboard","available")!=1)return json_error("Virtual keyboard unavailable");
        if(bus_set(true,"org.kde.KWin","/VirtualKeyboard","org.kde.kwin.VirtualKeyboard","enabled",on))return json_error("Cannot set virtual keyboard state");
        action="status";
    }
    if(session){bool tablet=!strncmp(action,"tablet-",7);char *a[]={tablet?"/usr/libexec/w202-tablet-mode":"/usr/bin/w202-rotation",(char*)strrchr(action,'-')+1,NULL};if(run_command(a,15,NULL))return json_error("Session request failed");action="status";}
    char *a[]={"/usr/libexec/w202-device-controls",(char*)action,NULL},*shared=NULL;if(run_command(a,150,&shared)){free(shared);return json_error("Device request failed");}struct json core;if(!jparse(&core,shared)||jbool(&core,jget(&core,0,"ok"))!=1){free(core.v);free(shared);return json_error("Invalid device response");}
    char *rotation=helper_status("/usr/bin/w202-rotation");struct json r={0};int enabled=-1,tablet=-1;if(rotation&&jparse(&r,rotation)){enabled=jbool(&r,jget(&r,0,"enabled"));tablet=jbool(&r,jget(&r,0,"tablet_mode"));}
    int keyboardAvailable=bus_bool(true,"org.kde.KWin","/VirtualKeyboard","org.kde.kwin.VirtualKeyboard","available");
    int keyboard=keyboardAvailable==1?bus_bool(true,"org.kde.KWin","/VirtualKeyboard","org.kde.kwin.VirtualKeyboard","enabled"):-1;
    /* Preserve existing fields without introducing duplicate JSON keys. */
    int states=jget(&core,0,"states"),caps=jget(&core,0,"capabilities");if(states<0||caps<0||core.v[states].type!='{'||core.v[caps].type!='{'){free(core.v);free(r.v);free(shared);free(rotation);return json_error("Invalid control schema");}
    fputc('{',stdout);for(int i=1;i<core.v[0].next;){int value=i+1;if(jeq(&core,i,"rotation")){i=core.v[value].next;continue;}jraw(stdout,&core,i);fputc(':',stdout);
        if(value==states||value==caps){fputc('{',stdout);for(int k=value+1;k<core.v[value].next;){int v=k+1;if(!jeq(&core,k,"rotation")&&!jeq(&core,k,"tablet")&&!jeq(&core,k,"keyboard")){jraw(stdout,&core,k);fputc(':',stdout);jraw(stdout,&core,v);fputc(',',stdout);}k=core.v[v].next;}
            if(value==states)printf("\"rotation\":%s,\"tablet\":%s,\"keyboard\":%s}",truth(enabled),truth(tablet),truth(keyboard));else printf("\"rotation\":{\"available\":%s,\"reason\":%s},\"tablet\":{\"available\":%s,\"reason\":%s},\"keyboard\":{\"available\":%s,\"reason\":%s}}",enabled<0?"false":"true",enabled<0?"\"session-backend-unavailable\"":"null",tablet<0?"false":"true",tablet<0?"\"session-backend-unavailable\"":"null",keyboard<0?"false":"true",keyboard<0?"\"session-backend-unavailable\"":"null");
        }else jraw(stdout,&core,value);fputc(',',stdout);i=core.v[value].next;}
    printf("\"rotation\":%s}\n",rotation?rotation:"{}");free(core.v);free(r.v);free(shared);free(rotation);return 0;
}
