/* SPDX-License-Identifier: (GPL-2.0+ OR MIT) */
/*
 * arch/arm/cpu/armv8/t5d/usb.c
 *
 * Copyright (C) 2020 Amlogic, Inc. All rights reserved.
 *
 */

#include <asm/arch/usb-v2.h>
#include <asm/arch/romboot.h>
#include <amlogic/power_domain.h>

static struct amlogic_usb_config * g_usb_cfg[BOARD_USB_MODE_MAX][USB_PHY_PORT_MAX];

struct amlogic_usb_config * board_usb_start(int mode,int index)
{
	printf("USB3.0 XHCI init start\n");

	if (mode < 0 || mode >= BOARD_USB_MODE_MAX||!g_usb_cfg[mode][index])
		return 0;

	writel((1 << 2), P_RESET1_REGISTER);

	if (mode == BOARD_USB_MODE_HOST )
		if (g_usb_cfg[mode][index]->set_vbus_power)
			g_usb_cfg[mode][index]->set_vbus_power(1);

	return g_usb_cfg[mode][index];
}

int board_usb_stop(int mode,int index)
{
	printf("board_usb_stop cfg: %d\n",mode);

	return 0;
}

int usb_index = 0;
void board_usb_init(struct amlogic_usb_config * usb_cfg,int mode)
{
#ifdef CONFIG_USB_POWER
	power_domain_switch(PM_USB, PWR_ON);
#endif

	if (mode < 0 || mode >= BOARD_USB_MODE_MAX || !usb_cfg)
		return ;

	if (mode == BOARD_USB_MODE_HOST) {
		if (usb_index >= USB_PHY_PORT_MAX)
			return;
		g_usb_cfg[mode][usb_index] = usb_cfg;
		usb_index++;
	} else
		g_usb_cfg[mode][0] = usb_cfg;
	printf("register usb cfg[%d][%d] = %p\n",mode,(mode==BOARD_USB_MODE_HOST)?usb_index:0,usb_cfg);
}

static void usb_set_calibration_trim(uint32_t volatile *phy2_pll_base)
{
	uint32_t cali, value,i;
	uint8_t cali_en;

	cali = readl(AO_SEC_GP_CFG12);
	//printf("AO_SEC_GP_CFG12=0x%08x\n", cali);
	/*****if cali_en ==0, set 0x10 to the default value: 0x1700****/
	cali_en = (cali >> 12) & 0x1;
	cali = cali >> 8;
	if (cali_en) {
		cali =cali & 0xf;
		if (cali > 12)
			cali = 12;
	} else {
		cali = 0x7;
	}
	value = (*(volatile uint32_t *)(unsigned long)((unsigned long)phy2_pll_base + 0x10));
	value &= (~0xfff);
	for (i = 0; i < cali; i++)
		value |= (1 << i);

	(*(volatile uint32_t *)(unsigned long)((unsigned long)phy2_pll_base + 0x10))
		= value;
	printf("0x10 trim value=0x%08x\n", value);;
}

int get_usb_count(void)
{
    return  usb_index;
}

void set_usb_pll(uint32_t volatile *phy2_pll_base)
{
    (*(volatile uint32_t *)((unsigned long)phy2_pll_base + 0x40))
     = (USB_PHY2_PLL_PARAMETER_1 | USB_PHY2_RESET | USB_PHY2_ENABLE);
    (*(volatile uint32_t *)((unsigned long)phy2_pll_base + 0x44))
     =USB_PHY2_PLL_PARAMETER_2;
    (*(volatile uint32_t *)((unsigned long)phy2_pll_base + 0x48))
     =USB_PHY2_PLL_PARAMETER_3;
    udelay(100);
    (*(volatile uint32_t *)(unsigned long)((unsigned long)phy2_pll_base + 0x40))
     = (((USB_PHY2_PLL_PARAMETER_1) | (USB_PHY2_ENABLE))
     & (~(USB_PHY2_RESET)));

    (*(volatile uint32_t *)(unsigned long)((unsigned long)phy2_pll_base + 0x50))
     = 0xbe18;
    (*(volatile uint32_t *)(unsigned long)((unsigned long)phy2_pll_base + 0x54))
     = 0x2a;
    usb_set_calibration_trim(phy2_pll_base);
    (*(volatile uint32_t *)(unsigned long)((unsigned long)phy2_pll_base + 0xc))
     = 0x34;
    (*(volatile uint32_t *)(unsigned long)((unsigned long)phy2_pll_base + 0x34))
     = 0x78000;
}

void board_usb_pll_disable(struct amlogic_usb_config *cfg)
{
    int i = 0;

    *(volatile uint32_t *)P_RESET1_LEVEL |= (0x7 << 16);
    for (i = 0; i < cfg->u2_port_num; i++) {
        (*(volatile uint32_t *)(unsigned long)
            (cfg->usb_phy2_pll_base_addr[i] + 0x40))
            = ((USB_PHY2_PLL_PARAMETER_1 | USB_PHY2_RESET)
            & (~(USB_PHY2_ENABLE)));
    }
}

void set_usb_poweroff(void)
{
	/*reset usb phy*/
	 *(volatile uint32_t *)P_RESET1_LEVEL &= (~(0x7 << 16));
}

#ifdef CONFIG_USB_DEVICE_V2
#define USB_REG_A 0xFF636000
#define USB_REG_B 0xFF63A000

void set_usb_phy_tuning_1(int port)
{
#ifndef CONFIG_USB_AMLOGIC_PHY_V2
	unsigned long phy_reg_base;

	if (port > 2)
		return;

	if (port == 0 )
		phy_reg_base = USB_REG_A;
	else
		phy_reg_base = USB_REG_B;

	(*(volatile uint32_t *)(unsigned long)((unsigned long)phy_reg_base + 0x10))
		= 0xfff;
	(*(volatile uint32_t *)(unsigned long)((unsigned long)phy_reg_base + 0x50))
		= 0xfe18;
	(*(volatile uint32_t *)(unsigned long)((unsigned long)phy_reg_base + 0x38))
		= 0xe0004;
	(*(volatile uint32_t *)(unsigned long)((unsigned long)phy_reg_base + 0x34))
		= 0xc8000;
#endif
}
#endif
