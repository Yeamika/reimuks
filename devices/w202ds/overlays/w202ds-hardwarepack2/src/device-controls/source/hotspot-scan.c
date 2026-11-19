/* SPDX-License-Identifier: GPL-2.0-only */
#include "native.h"
static bool uuid(const char *s){if(!s||strlen(s)!=36)return false;for(int i=0;i<36;i++){bool dash=i==8||i==13||i==18||i==23;if(dash?s[i]!='-':!isxdigit((unsigned char)s[i]))return false;}return true;}
static bool response(char *const a[],const char *expected){char *out=NULL;int r=run_command(a,5,&out);if(r){free(out);return false;}size_t n=strlen(out);while(n&&isspace((unsigned char)out[n-1]))out[--n]=0;bool ok=!strcmp(out,expected);free(out);return ok;}
int main(int argc,char **argv){const char *id=getenv("CONNECTION_UUID");if(argc!=3||strcmp(argv[1],"wlan0")||strcmp(argv[2],"up")||!uuid(id))return 0;
    char *a[]={"/usr/bin/nmcli","-g","GENERAL.CON-UUID","device","show","wlan0",NULL};if(!response(a,id))return 0;char *b[]={"/usr/bin/nmcli","-g","802-11-wireless.mode","connection","show","uuid",(char*)id,NULL};if(!response(b,"ap"))return 0;char *c[]={"/usr/sbin/wpa_cli","-i","wlan0","scan","TYPE=ONLY",NULL};if(!response(c,"OK"))return 1;puts("W202DS hotspot scan drain completed");return 0;
}
