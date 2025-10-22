################################################################################
#
# broadcom wifi
#
################################################################################

BROADCOM_VERSION = 0.1
BROADCOM_SITE = $(TOPDIR)/package/broadcom
BROADCOM_SITE_METHOD = local
BROADCOM_DEPENDENCIES = linux

BROADCOM_DRIVER_INSTALL_DIR = $(TARGET_DIR)/lib/modules/$(LINUX_VERSION_PROBED)/kernel/broadcom/wifi
BROADCOM_KCONFIGS = KCPPFLAGS='-DCONFIG_BCMDHD_FW_PATH=\"/etc/wifi/fw_bcmdhd.bin\" -DCONFIG_BCMDHD_NVRAM_PATH=\"/etc/wifi/nvram.txt\"'

define BROADCOM_BUILD_CMDS
	$(TARGET_CONFIGURE_OPTS) $(MAKE) -C $(LINUX_DIR) M=$(@D)/drivers/ap6xxx/bcmdhd.101.10.361.x ARCH=$(KERNEL_ARCH) \
		CROSS_COMPILE=$(TARGET_KERNEL_CROSS) $(BROADCOM_KCONFIGS) CONFIG_BCMDHD_SDIO=y modules
endef


define BROADCOM_INSTALL_TARGET_CMDS
	mkdir -p $(TARGET_DIR)/etc/wifi/6212
	$(INSTALL) -D -m 0644 $(@D)/config/6212/config.txt $(TARGET_DIR)/etc/wifi/6212/config.txt
	$(INSTALL) -D -m 0644 $(@D)/config/6212/fw_bcm43438a0.bin $(TARGET_DIR)/etc/wifi/6212/fw_bcm43438a0.bin
	$(INSTALL) -D -m 0644 $(@D)/config/6212/fw_bcm43438a0_apsta.bin $(TARGET_DIR)/etc/wifi/6212/fw_bcm43438a0_apsta.bin
	$(INSTALL) -D -m 0644 $(@D)/config/6212/fw_bcm43438a0_p2p.bin $(TARGET_DIR)/etc/wifi/6212/fw_bcm43438a0_p2p.bin
	$(INSTALL) -D -m 0644 $(@D)/config/6212/fw_bcm43438a1.bin $(TARGET_DIR)/etc/wifi/6212/fw_bcm43438a1.bin
	$(INSTALL) -D -m 0644 $(@D)/config/6212/fw_bcm43438a1_apsta.bin $(TARGET_DIR)/etc/wifi/6212/fw_bcm43438a1_apsta.bin
	$(INSTALL) -D -m 0644 $(@D)/config/6212/nvram.txt $(TARGET_DIR)/etc/wifi/6212/nvram.txt
	$(INSTALL) -D -m 0644 $(@D)/config/6212/nvram_ap6212a.txt $(TARGET_DIR)/etc/wifi/6212/nvram_ap6212a.txt
	$(INSTALL) -D -m 0644 $(@D)/config/6212/BT/bcm43438a0.hcd $(TARGET_DIR)/etc/bluetooth/bcm43430a0.hcd
	$(INSTALL) -D -m 0644 $(@D)/config/6212/BT/bcm43438a1.hcd $(TARGET_DIR)/etc/bluetooth/bcm43430a1.hcd

	mkdir -p $(BROADCOM_DRIVER_INSTALL_DIR)
	$(INSTALL) -m 0666 $(@D)/drivers/ap6xxx/bcmdhd.101.10.361.x/dhd.ko $(BROADCOM_DRIVER_INSTALL_DIR)/dhd.ko
	echo $(BROADCOM_DRIVER_INSTALL_DIR)/dhd.ko: >> $(TARGET_DIR)/lib/modules/$(LINUX_VERSION_PROBED)/modules.dep
endef

$(eval $(generic-package))
