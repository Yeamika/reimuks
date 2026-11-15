/* SPDX-License-Identifier: GPL-2.0-only */
#define main hall_program_main
#include "w202-hall-input.c"
#undef main
#include <assert.h>
int main(void){struct debounce d={0};assert(!update(&d,true,0,2000));assert(!update(&d,true,1999,2000));assert(update(&d,true,2000,2000));assert(!update(&d,false,2001,2000));assert(!update(&d,true,3000,2000));assert(!update(&d,false,4999,2000));assert(!update(&d,true,5000,2000));assert(!update(&d,true,6999,2000));assert(update(&d,true,7000,2000));assert(!update(&d,false,7001,2000));assert(update(&d,true,7002,0));puts("Hall debounce and immediate reopen pass");return 0;}
