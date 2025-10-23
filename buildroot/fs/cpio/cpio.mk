################################################################################
#
# cpio to archive target filesystem
#
################################################################################

ifeq ($(BR2_ROOTFS_DEVICE_CREATION_STATIC),y)

define ROOTFS_CPIO_ADD_INIT
	if [ ! -e $(TARGET_DIR)/init ]; then \
		ln -sf sbin/init $(TARGET_DIR)/init; \
	fi
endef

else
# devtmpfs does not get automounted when initramfs is used.
# Add a pre-init script to mount it before running init
# We must have /dev/console very early, even before /init runs,
# for stdin/stdout/stderr
define ROOTFS_CPIO_ADD_INIT
	if [ ! -e $(TARGET_DIR)/init ]; then \
		$(INSTALL) -m 0755 $(BR2_TARGET_CPIO_INIT_PATH)/init $(TARGET_DIR)/init; \
	fi
	mkdir -p $(TARGET_DIR)/dev
	mknod -m 0622 $(TARGET_DIR)/dev/console c 5 1
endef

endif # BR2_ROOTFS_DEVICE_CREATION_STATIC

ROOTFS_CPIO_PRE_GEN_HOOKS += ROOTFS_CPIO_ADD_INIT

# --reproducible option was introduced in cpio v2.12, which may not be
# available in some old distributions, so we build host-cpio
ifeq ($(BR2_REPRODUCIBLE),y)
ROOTFS_CPIO_DEPENDENCIES += host-cpio
ROOTFS_CPIO_OPTS += --reproducible
endif

define RECOVER_BLACKLIST_ENABLE
	if [ -f $(TOPDIR)/$(BR2_TARGET_RECOVERY_BLACK_LIST) ]; then
		sed -i 's/^[ ]*//' $(TOPDIR)/$(BR2_TARGET_RECOVERY_BLACK_LIST)
		sed -i 's/[ ]*$$//' $(TOPDIR)/$(BR2_TARGET_RECOVERY_BLACK_LIST)
		grep -v -x -f $(TOPDIR)/$(BR2_TARGET_RECOVERY_BLACK_LIST) $(HOST_DIR)/bin/ramfslist-recovery > $(HOST_DIR)/bin/ramfslist-recovery-temp
		mv $(HOST_DIR)/bin/ramfslist-recovery-temp $(HOST_DIR)/bin/ramfslist-recovery
	fi
endef

define USE_MINI_BUSYBOX
	if [ -f $(TARGET_DIR)/bin/busybox.mini ]; then
		mv $(TARGET_DIR)/bin/busybox $(TARGET_DIR)/bin/busybox.full
		mv $(TARGET_DIR)/bin/busybox.mini $(TARGET_DIR)/bin/busybox
	fi
endef

define RECOVER_BUSYBOX
	if [ -f $(TARGET_DIR)/bin/busybox.full ]; then
		mv $(TARGET_DIR)/bin/busybox.full $(TARGET_DIR)/bin/busybox
	fi
endef

RECOVERY_OTA_DIR := $(patsubst "%",%,$(BR2_RECOVERY_OTA_DIR))
ifneq ($(BR2_TARGET_ROOTFS_INITRAMFS_LIST),"")
ifeq ($(BR2_PACKAGE_SWUPDATE),y)
ifneq ($(BR2_PACKAGE_SWUPDATE_AB_SUPPORT),"absystem")
ifneq ($(RECOVERY_OTA_DIR),)
RECOVERY_OTA_RAMDISK_DIR := $(patsubst "%",%,$(BR2_RECOVERY_OTA_RAMDISK_DIR))
ifeq ($(RECOVERY_OTA_RAMDISK_DIR),)
RECOVERY_OTA_RAMDISK_DIR=$(RECOVERY_OTA_DIR)/../ramdisk/
endif
define ROOTFS_CPIO_CMD
	test -f $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) || (echo "Missing $(BR2_TARGET_ROOTFS_INITRAMFS_LIST)"; exit 1)
	$(call USE_MINI_BUSYBOX)
	cd $(TARGET_DIR) && cat $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) | grep -v "^#" | cpio --quiet -o -H newc > $@
	cd -

	$(call RECOVER_BUSYBOX)
	rm $(TARGET_DIR)_recovery -fr
	rm $(TARGET_DIR)_ota -fr
	cp $(TARGET_DIR) $(TARGET_DIR)_recovery -fr
	cp $(TARGET_DIR) $(TARGET_DIR)_ota -fr
	cp -rf $(RECOVERY_OTA_RAMDISK_DIR)/* $(TARGET_DIR)_recovery
	if [ -f $(BR2_TARGET_RECOVERY_INITRAMFS_LIST) ]; then
		cp $(TOPDIR)/$(BR2_TARGET_RECOVERY_INITRAMFS_LIST) $(HOST_DIR)/bin/ramfslist-recovery
	else
		cp $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) $(HOST_DIR)/bin/ramfslist-recovery
	fi
	cat $(RECOVERY_OTA_DIR)/ramfslist-recovery-need >> $(HOST_DIR)/bin/ramfslist-recovery
	$(call RECOVER_BLACKLIST_ENABLE)
	cd $(TARGET_DIR)_recovery && cat $(HOST_DIR)/bin/ramfslist-recovery | grep -v "^#" | cpio --quiet -o -H newc > $(BINARIES_DIR)/recovery.cpio
endef
endif
else
define ROOTFS_CPIO_CMD
	test -f $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) || (echo "Missing $(BR2_TARGET_ROOTFS_INITRAMFS_LIST)"; exit 1)
	$(call USE_MINI_BUSYBOX)
	cd $(TARGET_DIR) && cat $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) | grep -v "^#" | cpio --quiet -o -H newc > $@
	$(call RECOVER_BUSYBOX)
endef
endif
else
define ROOTFS_CPIO_CMD
	test -f $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) || (echo "Missing $(BR2_TARGET_ROOTFS_INITRAMFS_LIST)"; exit 1)
	$(call USE_MINI_BUSYBOX)
	cd $(TARGET_DIR) && cat $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) | grep -v "^#" | cpio --quiet -o -H newc > $@
	$(call RECOVER_BUSYBOX)
endef
endif
else
define ROOTFS_CPIO_CMD
	$(call USE_MINI_BUSYBOX)
	cd $(TARGET_DIR) && find . | cpio $(ROOTFS_CPIO_OPTS) --quiet -o -H newc > $@
	$(call RECOVER_BUSYBOX)
endef
endif # BR2_TARGET_ROOTFS_INITRAMFS_LIST

ifeq ($(BR2_TARGET_ROOTFS_CPIO_GZIP),y)
	ROOTFS_CPIO = rootfs.cpio.gz
else ifeq ($(BR2_TARGET_ROOTFS_CPIO_LZ4),y)
	ROOTFS_CPIO = rootfs.cpio.lz4
else ifeq ($(BR2_TARGET_ROOTFS_CPIO_LZO),y)
	ROOTFS_CPIO = rootfs.cpio.lzo
else ifeq ($(BR2_TARGET_ROOTFS_CPIO_XZ),y)
	ROOTFS_CPIO = rootfs.cpio.xz
else ifeq ($(BR2_TARGET_ROOTFS_CPIO_LZMA),y)
	ROOTFS_CPIO = rootfs.cpio.lzma
else
	ROOTFS_CPIO = rootfs.cpio
endif

ifeq ($(BR2_TARGET_RECOVERY_CPIO_XZ),y)
	RECOVERY_CPIO = recovery.cpio.xz
else
	RECOVERY_CPIO = recovery.cpio.gz
endif

LINUX_KERNEL_BOOTIMAGE_OFFSET = $(call qstrip,$(BR2_LINUX_KERNEL_BOOTIMAGE_OFFSET))
ifeq ($(LINUX_KERNEL_BOOTIMAGE_OFFSET),)
LINUX_KERNEL_BOOTIMAGE_OFFSET = 0x1080000
endif

ifneq ($(BR2_TARGET_ROOTFS_INITRAMFS),y)
WORD_NUMBER := $(words $(BR2_LINUX_KERNEL_INTREE_DTS_NAME))
KERNEL_BOOTARGS = $(call qstrip,$(BR2_TARGET_UBOOT_AMLOGIC_BOOTARGS))

ifndef VERSION_SPEAKER_WIFI_FIRMWARE
	VERSION_SPEAKER_WIFI_FIRMWARE   = $(shell date "+00.%m.%d")
endif
KERNEL_BOOTARGS += firmware_version=$(VERSION_SPEAKER_WIFI_FIRMWARE)

ifeq ($(WORD_NUMBER),1)
#mkbootimg: $(BINARIES_DIR)/$(LINUX_IMAGE_NAME) $(BINARIES_DIR)/$(ROOTFS_CPIO)
#	@$(call MESSAGE,"Generating boot image")
#	linux/mkbootimg --kernel $(LINUX_IMAGE_PATH) --base 0x0 --kernel_offset $(LINUX_KERNEL_BOOTIMAGE_OFFSET) --cmdline "$(KERNEL_BOOTARGS)" --ramdisk $(BINARIES_DIR)/$(ROOTFS_CPIO) --second $(BINARIES_DIR)/$(KERNEL_DTBS) --output $(BINARIES_DIR)/boot.img
#	cp $(BINARIES_DIR)/$(KERNEL_DTBS) $(BINARIES_DIR)/dtb.img -rf
#ifeq ($(BR2_PACKAGE_SWUPDATE),y)
#ifneq ($(BR2_PACKAGE_SWUPDATE_AB_SUPPORT),"absystem")
#	gzip -9 -c $(BINARIES_DIR)/recovery.cpio > $(BINARIES_DIR)/recovery.cpio.gz
#	linux/mkbootimg --kernel $(LINUX_IMAGE_PATH) --base 0x0 --kernel_offset $(LINUX_KERNEL_BOOTIMAGE_OFFSET) --cmdline "$(KERNEL_BOOTARGS)" --ramdisk  $(BINARIES_DIR)/recovery.cpio.gz --second $(BINARIES_DIR)/dtb.img --output $(BINARIES_DIR)/recovery.img
#endif
#endif
AML_DTBS=$(patsubst amlogic/%,%,$(LINUX_DTBS))
define AML_MKBOOTIMG
	@$(call MESSAGE,"Generating boot image")
	linux/mkbootimg --kernel $(LINUX_IMAGE_PATH) --base 0x0 --kernel_offset $(LINUX_KERNEL_BOOTIMAGE_OFFSET) --cmdline "$(KERNEL_BOOTARGS)" --ramdisk $(BINARIES_DIR)/$(ROOTFS_CPIO) --second $(BINARIES_DIR)/$(AML_DTBS) --output $(BINARIES_DIR)/boot.img
	echo "buildroot/linux/mkbootimg --kernel $(LINUX_IMAGE_PATH) --base 0x0 --kernel_offset $(LINUX_KERNEL_BOOTIMAGE_OFFSET) --cmdline \"$(KERNEL_BOOTARGS)\" --ramdisk $(BINARIES_DIR)/$(ROOTFS_CPIO) --second $(BINARIES_DIR)/$(AML_DTBS) --output $(BINARIES_DIR)/boot.img" > $(BINARIES_DIR)/mk_bootimg.sh
	sed -i '1s/^/#!\/bin\/sh\n\n/' $(BINARIES_DIR)/mk_bootimg.sh
	chmod a+x $(BINARIES_DIR)/mk_bootimg.sh
	cp $(BINARIES_DIR)/$(AML_DTBS) $(BINARIES_DIR)/dtb.img -rf
	if [ "$(BR2_PACKAGE_SWUPDATE)" = "y" ] && [ "$(BR2_PACKAGE_SWUPDATE_AB_SUPPORT)" != "absystem" ]; then  \
		if [ "$(BR2_TARGET_RECOVERY_CPIO_XZ)" != "y" ]; then \
			gzip -9 -c $(BINARIES_DIR)/recovery.cpio > $(BINARIES_DIR)/$(RECOVERY_CPIO); \
		else \
			xz -9 -C crc32 -z -k -c $(BINARIES_DIR)/recovery.cpio > $(BINARIES_DIR)/$(RECOVERY_CPIO); \
		fi; \
		linux/mkbootimg --kernel $(LINUX_IMAGE_PATH) --base 0x0 --kernel_offset $(LINUX_KERNEL_BOOTIMAGE_OFFSET) --cmdline "$(KERNEL_BOOTARGS)" --ramdisk  $(BINARIES_DIR)/$(RECOVERY_CPIO) --second $(BINARIES_DIR)/dtb.img --output $(BINARIES_DIR)/recovery.img; \
	fi
endef
else
#mkbootimg: $(BINARIES_DIR)/$(LINUX_IMAGE_NAME) $(BINARIES_DIR)/$(ROOTFS_CPIO)
#	@$(call MESSAGE,"Generating boot image")
#	linux/dtbTool -o $(BINARIES_DIR)/dtb.img -p $(LINUX_DIR)/scripts/dtc/ $(BINARIES_DIR)/
#	gzip $(BINARIES_DIR)/dtb.img
#	mv $(BINARIES_DIR)/dtb.img.gz $(BINARIES_DIR)/dtb.img
#	linux/mkbootimg --kernel $(LINUX_IMAGE_PATH) --base 0x0 --kernel_offset $(LINUX_KERNEL_BOOTIMAGE_OFFSET) --cmdline "$(KERNEL_BOOTARGS)" --ramdisk  $(BINARIES_DIR)/$(ROOTFS_CPIO) --second $(BINARIES_DIR)/dtb.img --output $(BINARIES_DIR)/boot.img
#ifeq ($(BR2_PACKAGE_SWUPDATE),y)
#ifneq ($(BR2_PACKAGE_SWUPDATE_AB_SUPPORT),"absystem")
#	gzip -9 -c $(BINARIES_DIR)/recovery.cpio > $(BINARIES_DIR)/recovery.cpio.gz
#	linux/mkbootimg --kernel $(LINUX_IMAGE_PATH) --base 0x0 --kernel_offset $(LINUX_KERNEL_BOOTIMAGE_OFFSET) --cmdline "$(KERNEL_BOOTARGS)" --ramdisk  $(BINARIES_DIR)/recovery.cpio.gz --second $(BINARIES_DIR)/dtb.img --output $(BINARIES_DIR)/recovery.img
#endif
#endif
define AML_MKBOOTIMG
	@$(call MESSAGE,"Generating boot image")
	linux/dtbTool -o $(BINARIES_DIR)/dtb.img -p $(LINUX_DIR)/scripts/dtc/ $(BINARIES_DIR)/
	gzip $(BINARIES_DIR)/dtb.img
	mv $(BINARIES_DIR)/dtb.img.gz $(BINARIES_DIR)/dtb.img
	linux/mkbootimg --kernel $(LINUX_IMAGE_PATH) --base 0x0 --kernel_offset $(LINUX_KERNEL_BOOTIMAGE_OFFSET) --cmdline "$(KERNEL_BOOTARGS)" --ramdisk  $(BINARIES_DIR)/$(ROOTFS_CPIO) --second $(BINARIES_DIR)/dtb.img --output $(BINARIES_DIR)/boot.img
	echo "buildroot/linux/mkbootimg --kernel $(LINUX_IMAGE_PATH) --base 0x0 --kernel_offset $(LINUX_KERNEL_BOOTIMAGE_OFFSET) --cmdline \"$(KERNEL_BOOTARGS)\" --ramdisk  $(BINARIES_DIR)/$(ROOTFS_CPIO) --second $(BINARIES_DIR)/dtb.img --output $(BINARIES_DIR)/boot.img" > $(BINARIES_DIR)/mk_bootimg.sh
	sed -i '1s/^/#!\/bin\/sh\n\n/' $(BINARIES_DIR)/mk_bootimg.sh
	chmod a+x $(BINARIES_DIR)/mk_bootimg.sh
	if [ "$(BR2_PACKAGE_SWUPDATE)" = "y" ] && [ "$(BR2_PACKAGE_SWUPDATE_AB_SUPPORT)" != "absystem" ]; then  \
	gzip -9 -c $(BINARIES_DIR)/recovery.cpio > $(BINARIES_DIR)/recovery.cpio.gz; \
	linux/mkbootimg --kernel $(LINUX_IMAGE_PATH) --base 0x0 --kernel_offset $(LINUX_KERNEL_BOOTIMAGE_OFFSET) --cmdline "$(KERNEL_BOOTARGS)" --ramdisk  $(BINARIES_DIR)/recovery.cpio.gz --second $(BINARIES_DIR)/dtb.img --output $(BINARIES_DIR)/recovery.img; \
	fi
endef
endif

else
mkbootimg:
endif

ifeq ($(BR2_LINUX_KERNEL_ANDROID_FORMAT),y)
#ROOTFS_CPIO_POST_TARGETS += mkbootimg
ROOTFS_CPIO_POST_GEN_HOOKS += AML_MKBOOTIMG
endif

ifeq ($(BR2_TARGET_ROOTFS_CPIO_UIMAGE),y)
ROOTFS_CPIO_DEPENDENCIES += host-uboot-tools
define ROOTFS_CPIO_UBOOT_MKIMAGE
	$(MKIMAGE) -A $(MKIMAGE_ARCH) -T ramdisk \
		-C none -d $@$(ROOTFS_CPIO_COMPRESS_EXT) $@.uboot
endef
ROOTFS_CPIO_POST_GEN_HOOKS += ROOTFS_CPIO_UBOOT_MKIMAGE
endif

#$(TARGET_DIR)/uInitrd: $(BINARIES_DIR)/rootfs.cpio.uboot
#	install -m 0644 -D $(BINARIES_DIR)/rootfs.cpio.uboot $(TARGET_DIR)/boot/uInitrd
define $(TARGET_DIR)/UINITRD
	install -m 0644 -D $(BINARIES_DIR)/rootfs.cpio.uboot $(TARGET_DIR)/boot/uInitrd
endef

ifeq ($(BR2_TARGET_ROOTFS_CPIO_UIMAGE_INSTALL),y)
#ROOTFS_CPIO_POST_TARGETS += $(TARGET_DIR)/uInitrd
ROOTFS_CPIO_POST_GEN_HOOKS += $(TARGET_DIR)/UINITRD
endif

#$(TARGET_DIR)/boot.img: mkbootimg
#	install -m 0644 -D $(BINARIES_DIR)/boot.img $(TARGET_DIR)/boot.img
define $(TARGET_DIR)/BOOT.IMG
	install -m 0644 -D $(BINARIES_DIR)/boot.img $(TARGET_DIR)/boot.img
endef

ifeq ($(BR2_LINUX_KERNEL_INSTALL_TARGET)$(BR2_LINUX_KERNEL_ANDROID_FORMAT),yy)
#ROOTFS_CPIO_POST_TARGETS += $(TARGET_DIR)/boot.img
ROOTFS_CPIO_POST_GEN_HOOKS += $(TARGET_DIR)/BOOT.IMG
endif

$(eval $(rootfs))
