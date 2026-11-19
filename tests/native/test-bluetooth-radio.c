/* SPDX-License-Identifier: GPL-2.0-only */
#include "native.h"
#include "bluetooth-radio.h"
int main(int argc, char **argv)
{
    return argc == 2 && !bluetooth_unblock(argv[1]) ? 0 : 1;
}
