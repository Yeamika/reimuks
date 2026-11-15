/* SPDX-License-Identifier: GPL-2.0-only */
#define main gnss_program_main
#include "w202ds-gnss.c"
#undef main
#include <assert.h>
int main(void){
    const unsigned char wake[]={0x7e,0x7e,0x7e,0x7e,4,1,0,2,0xfe,0xff,1,0,0xfe,0xff};
    const unsigned char boot[]={0x7e,0x7e,0x7e,0x7e,3,7,0,0,0xff,0xfb,0,0};
    unsigned char encoded[2050],payload[]={1,0};assert(encode(encoded,4,1,payload,2)==sizeof(wake));assert(!memcmp(encoded,wake,sizeof(wake)));assert(encode(encoded,3,7,NULL,0)==sizeof(boot));assert(!memcmp(encoded,boot,sizeof(boot)));
    for(size_t split=0;split<=sizeof(wake);split++){struct parser p={0};struct frame f;memcpy(p.data,wake,split);p.used=split;int first=packet(&p,&f);if(split<sizeof(wake)){assert(!first);memcpy(p.data+p.used,wake+split,sizeof(wake)-split);p.used+=sizeof(wake)-split;assert(packet(&p,&f));}else assert(first);assert(f.kind==4&&f.sub==1&&f.len==2&&f.payload[0]==1);assert(!packet(&p,&f));}
    struct parser p={0};struct frame f;memcpy(p.data,"noise",5);memcpy(p.data+5,wake,sizeof(wake));p.data[15]^=1;memcpy(p.data+5+sizeof(wake),boot,sizeof(boot));p.used=5+sizeof(wake)+sizeof(boot);assert(packet(&p,&f));assert(f.kind==3&&f.sub==7);assert(p.bad_payload==1);assert(p.discarded>=5);
    FILE *null=fopen("/dev/null","w");assert(null);int saved=dup(1);assert(dup2(fileno(null),1)>=0);const unsigned char line[]="$GPGSV,1,1,1,7,1,,33*4E\r\n";for(size_t split=0;split<sizeof(line);split++){struct session s={0};nmea(&s,line,split);nmea(&s,line+split,sizeof(line)-1-split);assert(s.nmea_count==1);}struct session s={0};nmea(&s,(const unsigned char*)"$GPGSV,1,1,1,7,1,,33*00\r\n",26);assert(!s.nmea_count);fflush(stdout);dup2(saved,1);close(saved);fclose(null);puts("GNSS framing, split packets, CRC recovery and NMEA checks pass");return 0;
}
