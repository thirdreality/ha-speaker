/* SPDX-License-Identifier: (GPL-2.0+ OR MIT) */
/*
 * drivers/usb/gadget/v3_burning/aml_v3_burning.c
 *
 * Copyright (C) 2020 Amlogic, Inc. All rights reserved.
 *
 */

#include "include/v3_tool_def.h"
#include <mmc.h>
#include <asm/cpu_id.h>
DECLARE_GLOBAL_DATA_PTR;

#ifndef BOOT_DEVICE_USB
#define BOOT_DEVICE_SD                  4
#define BOOT_DEVICE_USB                 5
#endif// #ifndef BOOT_DEVICE_USB
extern void serial_initialize(void);

extern void board_init_mem(void);

#ifndef MESON_CPU_MAJOR_ID_C1
#define MESON_CPU_MAJOR_ID_C1		0x30
#endif//#ifndef MESON_CPU_MAJOR_ID_C1
#ifndef MESON_CPU_MAJOR_ID_SC2
#define MESON_CPU_MAJOR_ID_SC2		0x32
#endif//#ifndef MESON_CPU_MAJOR_ID_SC2
#ifndef MESON_CPU_MAJOR_ID_C2
#define MESON_CPU_MAJOR_ID_C2		0x33
#endif//#ifndef MESON_CPU_MAJOR_ID_C2

static unsigned _get_romcode_boot_id(void)
{
	const cpu_id_t cpuid = get_cpu_id();
	const int familyId	 = cpuid.family_id;

    unsigned boot_id = 0;
#ifdef SYSCTRL_SEC_STATUS_REG2
	if (MESON_CPU_MAJOR_ID_SC2 == familyId) {
		boot_id = readl(SYSCTRL_SEC_STATUS_REG2);
        FB_DBG("boot_id 0x%x\n", boot_id);
		boot_id = (boot_id>>4) & 0xf;
	}
	FB_DBG("boot_id 1x%x\n", boot_id);
#endif// #ifdef SYSCTRL_SEC_STATUS_REG2

#if defined(P_AO_SEC_GP_CFG0)
    if (MESON_CPU_MAJOR_ID_SC2 != familyId) {
		FB_DBG("cfg0 0x%08x\n", readl(P_AO_SEC_GP_CFG0));
		boot_id = readl(P_AO_SEC_GP_CFG0) & 0xf;
	}
#endif// #if defined(P_AO_SEC_GP_CFG0)

    return boot_id;
}

static int is_boot_device_usb(void)
{
    return BOOT_DEVICE_USB == _get_romcode_boot_id();
}

#if 0
static int is_bl1_usb_protocol_DNL(void)
{
#ifdef SYSCTRL_SEC_STATUS_REG1
    const unsigned cfg9 = readl(SYSCTRL_SEC_STATUS_REG1);
    FB_DBG("SYSCTRL_SEC_STATUS_REG1 0x%x\n", cfg9);
    return !(cfg9 & (1U<<12));
#else
    const unsigned cfg9 = readl(P_AO_SEC_SD_CFG9);
    FB_DBG("cfg9 0x%x\n", cfg9);
    return cfg9 & (1U<<15);
#endif// #ifdef SYSCTRL_SEC_STATUS_REG1
}
#endif

int aml_v3_factory_usb_burning(int flag, bd_t* bis)
{
    if (!is_boot_device_usb()) return 1;

    bis = bis;//avoid compiling warning
    if ( !flag ) {
#ifdef CONFIG_GENERIC_MMC
        puts("MMC init for dnl\n");
        mmc_initialize(bis);
#endif
        set_default_env("usb temp env");
    }
#ifdef CONFIG_SILENT_CONSOLE
    /* enable console output */
    gd->flags &= ~GD_FLG_SILENT;
#endif
    //pull down and sleep in bl2-->tpl,
    //to improve pc compatibility
    f_dwc_otg_pullup(0);
    udelay(2*1000*1000);

    v3tool_work_mode_set(V3TOOL_WORK_MODE_USB_PRODUCE);
    optimus_clear_ovd_register();
    return run_command("adnl", 0);
}

