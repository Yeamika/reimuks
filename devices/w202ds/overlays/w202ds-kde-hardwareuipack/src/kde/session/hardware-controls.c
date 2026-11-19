/* SPDX-License-Identifier: GPL-2.0-only */
#include "session.h"
int main(int argc,char **argv){if(argc!=2)return json_error("Expected one action");const char *action=argv[1];bool session=false;for(int i=0;i<4;i++){const char *a[]={"tablet-on","tablet-off","rotation-on","rotation-off"};if(!strcmp(action,a[i]))session=true;}
    if(!strcmp(action,"keyboard-on")||!strcmp(action,"keyboard-off")){
        bool on=!strcmp(action,"keyboard-on");
        if(bus_bool(true,"org.kde.KWin","/VirtualKeyboard","org.kde.kwin.VirtualKeyboard","available")!=1)return json_error("Virtual keyboard unavailable");
        if(bus_set(true,"org.kde.KWin","/VirtualKeyboard","org.kde.kwin.VirtualKeyboard","enabled",on))return json_error("Cannot set virtual keyboard state");
        action="status";
    }
    if(session){bool tablet=!strncmp(action,"tablet-",7);char *a[]={tablet?"/usr/libexec/w202-tablet-mode":"/usr/bin/w202-rotation",(char*)strrchr(action,'-')+1,NULL};if(run_command(a,15,NULL))return json_error("Session request failed");action="status";}
    char *shared=session_device_request(action);if(!shared)return json_error("Device request failed");
    char *rotation=helper_status("/usr/bin/w202-rotation");struct json r={0};int enabled=-1,tablet=-1;if(rotation&&jparse(&r,rotation)){enabled=jbool(&r,jget(&r,0,"enabled"));tablet=jbool(&r,jget(&r,0,"tablet_mode"));}
    int keyboardAvailable=bus_bool(true,"org.kde.KWin","/VirtualKeyboard","org.kde.kwin.VirtualKeyboard","available");
    int keyboard=keyboardAvailable==1?bus_bool(true,"org.kde.KWin","/VirtualKeyboard","org.kde.kwin.VirtualKeyboard","enabled"):-1;
    int result=session_status(shared,enabled,tablet,keyboard,rotation);free(r.v);free(shared);free(rotation);return result;
}
