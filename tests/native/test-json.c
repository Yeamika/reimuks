/* SPDX-License-Identifier: GPL-2.0-only */
#include "native.h"
#include <assert.h>
int main(int argc,char **argv){if(argc==2){struct json j;bool valid=jparse(&j,argv[1]);free(j.v);return valid?0:1;}
    const char *bad[]={"", "{", "[1,]", "{\"x\":}", "{\"x\":1,}", "01", "-", "1.", "1e", "true false", "\"\\q\"", "\"\\u0\""};for(size_t i=0;i<sizeof(bad)/sizeof(*bad);i++){struct json j;assert(!jparse(&j,bad[i]));free(j.v);}
    struct json j;assert(jparse(&j,"{\"nested\":{\"x\":[true,false,null]},\"value\":-42}"));assert(jbool(&j,jidx(&j,jget(&j,jget(&j,0,"nested"),"x"),0))==1);assert(jbool(&j,jidx(&j,jget(&j,jget(&j,0,"nested"),"x"),1))==0);int64_t n;assert(jlong(&j,jget(&j,0,"value"),&n)&&n==-42);free(j.v);
    char *out=NULL;char *sleep[]={"/bin/sleep","10",NULL};int64_t started=mono_ms();assert(run_command(sleep,1,&out));free(out);assert(mono_ms()-started<3000);puts("JSON validation and bounded child cleanup pass");return 0;
}
