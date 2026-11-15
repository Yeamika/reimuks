/* SPDX-License-Identifier: MIT */
#define main storage_program_main
#include "w202-modem-storage.c"
#undef main
int main(int argc,char **argv){if(argc!=4)return 2;return validate_nv(argv[1],strtoul(argv[2],NULL,10),strtoul(argv[3],NULL,10))?1:0;}
