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
ifeq ($(BR2_AML_C3_PRODUCT_MODE),y)
define ROOTFS_CPIO_ADD_INIT
        if [ ! -e $(TARGET_DIR)/init ]; then \
                $(INSTALL) -m 0755 $(BR2_AML_C3_PRODUCTION_MODE_PATH)/init $(TARGET_DIR)/init; \
        fi
        mkdir -p $(TARGET_DIR)/dev
        mknod -m 0622 $(TARGET_DIR)/dev/console c 5 1
endef
else
define ROOTFS_CPIO_ADD_INIT
        if [ ! -e $(TARGET_DIR)/init ]; then \
                $(INSTALL) -m 0755 $(BR2_TARGET_CPIO_INIT_PATH)/init $(TARGET_DIR)/init; \
        fi
        mkdir -p $(TARGET_DIR)/dev
        mknod -m 0622 $(TARGET_DIR)/dev/console c 5 1
endef

endif
endif # BR2_ROOTFS_DEVICE_CREATION_STATIC

ROOTFS_CPIO_PRE_GEN_HOOKS += ROOTFS_CPIO_ADD_INIT

# --reproducible option was introduced in cpio v2.12, which may not be
# available in some old distributions, so we build host-cpio
ifeq ($(BR2_REPRODUCIBLE),y)
ROOTFS_CPIO_DEPENDENCIES += host-cpio
ROOTFS_CPIO_OPTS += --reproducible
endif

# if use dm-verity, make rootfs-cpio build at last.
# this dependency is used to ensure this sequence.
ifeq ($(BR2_AML_USE_DM_VERITY),y)
ROOTFS_CPIO_DEPENDENCIES += avb-verity
ifeq ($(BR2_TARGET_ROOTFS_EXT2),y)
ROOTFS_CPIO_DEPENDENCIES += rootfs-ext2
endif
ifeq ($(BR2_TARGET_ROOTFS_SQUASHFS),y)
ROOTFS_CPIO_DEPENDENCIES += rootfs-squashfs
endif
ifeq ($(BR2_TARGET_ROOTFS_EROFS),y)
ROOTFS_CPIO_DEPENDENCIES += rootfs-erofs
endif
endif

ENV_FILE:=$(BINARIES_DIR)/../target/etc/system-dm-verity.env

# if use dm-verity to check rootfs verity
ifeq ($(BR2_AML_USE_DM_VERITY),y)
define ROOTFS_GEN_ROOT_HASH_ENV
	HASH_OFFSET=$$(stat -c%s $(ROOTFS_FILE)); \
	$(HOST_DIR)/sbin/veritysetup --debug --data-block-size=4096 --hash-offset=$${HASH_OFFSET} \
	format $(ROOTFS_FILE) $(ROOTFS_FILE) | tee $(ENV_FILE)
endef
else
define ROOTFS_GEN_ROOT_HASH_ENV
endef
endif # BR2_AML_USE_DM_VERITY

# process different file system
ifeq ($(BR2_TARGET_ROOTFS_EXT2),y)
	ROOTFS_FILE:=$(BINARIES_DIR)/rootfs.ext2
	ROOTFS_EXT2_POST_GEN_HOOKS += ROOTFS_GEN_ROOT_HASH_ENV
endif
ifeq ($(BR2_TARGET_ROOTFS_SQUASHFS),y)
	ROOTFS_FILE:=$(BINARIES_DIR)/rootfs.squashfs
	ROOTFS_SQUASHFS_POST_GEN_HOOKS += ROOTFS_GEN_ROOT_HASH_ENV
endif
ifeq ($(BR2_TARGET_ROOTFS_EROFS),y)
	ROOTFS_FILE:=$(BINARIES_DIR)/rootfs.erofs
	ROOTFS_EROFS_POST_GEN_HOOKS += ROOTFS_GEN_ROOT_HASH_ENV
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
endif #RECOVERY_OTA_RAMDISK_DIR
define ROOTFS_CPIO_CMD
	test -f $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) || (echo "Missing $(BR2_TARGET_ROOTFS_INITRAMFS_LIST)"; exit 1)
	$(call USE_MINI_BUSYBOX)
	if [ -d $(TARGET_DIR)/amlogic/modules/ramdisk ]; then
		cp $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) $(HOST_DIR)/bin/ramfslist-tmp
		cd $(TARGET_DIR) && find ./amlogic/modules/ramdisk/*.ko >> $(HOST_DIR)/bin/ramfslist-tmp && cd -
		cd $(TARGET_DIR) && cat $(HOST_DIR)/bin/ramfslist-tmp | grep -v "^#" | cpio --quiet -o -H newc > $@
		cd -
	else
	cd $(TARGET_DIR) && cat $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) | grep -v "^#" | cpio --quiet -o -H newc > $@
	cd -
	fi

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
	if [ -f $(BR2_TARGET_RECOVERY_INITRAMFS_NEED_64) ]; then
		cat $(TOPDIR)/$(BR2_TARGET_RECOVERY_INITRAMFS_NEED_64) >> $(HOST_DIR)/bin/ramfslist-recovery
	else
		cat $(RECOVERY_OTA_DIR)/ramfslist-recovery-need >> $(HOST_DIR)/bin/ramfslist-recovery
	fi
	if [ -d $(TARGET_DIR)/amlogic/modules/ramdisk ]; then
		cd $(TARGET_DIR)
		find ./amlogic/modules/ramdisk/*.ko >> $(HOST_DIR)/bin/ramfslist-recovery
		cd -
	fi
	$(call RECOVER_BLACKLIST_ENABLE)
	cd $(TARGET_DIR)_recovery && cat $(HOST_DIR)/bin/ramfslist-recovery | grep -v "^#" | cpio --quiet -o -H newc > $(BINARIES_DIR)/recovery.cpio
endef
endif #RECOVERY_OTA_DIR
else
define ROOTFS_CPIO_CMD
	test -f $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) || (echo "Missing $(BR2_TARGET_ROOTFS_INITRAMFS_LIST)"; exit 1)
	$(call USE_MINI_BUSYBOX)
	if [ -d $(TARGET_DIR)/amlogic/modules/ramdisk ]; then
		cp $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) $(HOST_DIR)/bin/ramfslist-tmp
		cd $(TARGET_DIR) && find ./amlogic/modules/ramdisk/*.ko >> $(HOST_DIR)/bin/ramfslist-tmp && cd -
		cd $(TARGET_DIR) && cat $(HOST_DIR)/bin/ramfslist-tmp | grep -v "^#" | cpio --quiet -o -H newc > $@
		cd -
	else
		cd $(TARGET_DIR) && cat $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) | grep -v "^#" | cpio --quiet -o -H newc > $@
		cd -
	fi
	$(call RECOVER_BUSYBOX)
endef
endif #BR2_PACKAGE_SWUPDATE_AB_SUPPORT
else
define ROOTFS_CPIO_CMD
	test -f $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) || (echo "Missing $(BR2_TARGET_ROOTFS_INITRAMFS_LIST)"; exit 1)
	$(call USE_MINI_BUSYBOX)
	cd $(TARGET_DIR) && cat $(TOPDIR)/$(BR2_TARGET_ROOTFS_INITRAMFS_LIST) | grep -v "^#" | cpio --quiet -o -H newc > $@
	$(call RECOVER_BUSYBOX)
endef
endif #BR2_PACKAGE_SWUPDATE
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

ifndef SPEAKER_FIRMWARE_VERSION
	SPEAKER_FIRMWARE_VERSION = $(shell date "+0.%m.%d")
endif
KERNEL_BOOTARGS += firmware_version=$(SPEAKER_FIRMWARE_VERSION)

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

# these env should be used by aml_upgrade_pkg_gen.sh
# so export them
export BR2_AML_USE_AVB
export BR2_AML_BOOT_PARTITION_SIZE
export BR2_AML_RECOVERY_PARTITION_SIZE

DEVICE_DIR := $(patsubst "%",%,$(BR2_ROOTFS_OVERLAY))
UPGRADE_DIR := $(patsubst "%",%,$(BR2_ROOTFS_UPGRADE_DIR))
UPGRADE_DIR_OVERLAY := $(patsubst "%",%,$(BR2_ROOTFS_UPGRADE_DIR_OVERLAY))
ifeq ($(BR2_TARGET_USBTOOL_AMLOGIC),y)
ifeq ($(filter y,$(BR2_TARGET_UBOOT_AMLOGIC_2015) $(BR2_TARGET_UBOOT_AMLOGIC_REPO) $(BR2_TARGET_UBOOT_AMLOGIC_M8B)),y)
ifneq ($(UPGRADE_DIR_OVERLAY),)
define ROOTFS-USB-IMAGE-PACK
	cp -rfL $(UPGRADE_DIR)/* $(BINARIES_DIR)
	cp -rfL $(UPGRADE_DIR_OVERLAY)/* $(BINARIES_DIR)
	BINARIES_DIR=$(BINARIES_DIR) \
	TOOL_DIR=$(HOST_DIR)/bin \
	BR2_AML_UPGRADE_CONF_FILE=$(BR2_AML_UPGRADE_CONF_FILE) \
	$(HOST_DIR)/bin/aml_upgrade_pkg_gen.sh \
	$(BR2_TARGET_UBOOT_PLATFORM) $(BR2_TARGET_UBOOT_ENCRYPTION) $(BR2_PACKAGE_SWUPDATE_AB_SUPPORT)
endef
else
define ROOTFS-USB-IMAGE-PACK
	cp -rfL $(UPGRADE_DIR)/* $(BINARIES_DIR)
	BINARIES_DIR=$(BINARIES_DIR) \
	TOOL_DIR=$(HOST_DIR)/bin \
	BR2_AML_UPGRADE_CONF_FILE=$(BR2_AML_UPGRADE_CONF_FILE) \
	$(HOST_DIR)/bin/aml_upgrade_pkg_gen.sh \
	$(BR2_TARGET_UBOOT_PLATFORM) $(BR2_TARGET_UBOOT_ENCRYPTION) $(BR2_PACKAGE_SWUPDATE_AB_SUPPORT)
endef
endif

else #BR2_TARGET_UBOOT_AMLOGIC_2015
define ROOTFS-USB-IMAGE-PACK
	cp -rfL $(UPGRADE_DIR)/* $(BINARIES_DIR)
	$(HOST_DIR)/bin/aml_image_v2_packer_new -r $(BINARIES_DIR)/aml_upgrade_package.conf $(BINARIES_DIR)/ $(BINARIES_DIR)/aml_upgrade_package.img
endef
endif #BR2_TARGET_UBOOT_AMLOGIC_2015
# rootfs-cpio is build after all other rootfs are built.
# so add this to post rootfs-cpio is ok.
ifeq ($(BR2_AML_USE_DM_VERITY),y)
ROOTFS_CPIO_POST_GEN_HOOKS += ROOTFS-USB-IMAGE-PACK
endif

endif #BR2_TARGET_USBTOOL_AMLOGIC


RECOVERY_OTA_DIR := $(patsubst "%",%,$(BR2_RECOVERY_OTA_DIR))
ifneq ($(RECOVERY_OTA_DIR),)
ifeq ($(BR2_TARGET_UBOOT_ENCRYPTION),y)
	RECOVERY_ENC_FLAG="-enc"
endif
define ROOTFS-OTA-SWU-PACK
	$(INSTALL) -m 0755 $(RECOVERY_OTA_DIR)/../swu/* $(BINARIES_DIR)
	$(INSTALL) -m 0644 $(RECOVERY_OTA_DIR)/$(BR2_AML_SW_DESC_CONF_FILE)$(RECOVERY_ENC_FLAG) $(BINARIES_DIR)/sw-description
	$(INSTALL) -m 0644 $(RECOVERY_OTA_DIR)/$(BR2_AML_SW_DESC_INC_CONF_FILE)$(RECOVERY_ENC_FLAG) $(BINARIES_DIR)/sw-description-increment
	$(INSTALL) -m 0644 $(RECOVERY_OTA_DIR)/$(BR2_AML_OTA_FILE_LIST_FILE)$(RECOVERY_ENC_FLAG) $(BINARIES_DIR)/ota-package-filelist
	$(BINARIES_DIR)/ota_package_create.sh
endef
ifeq ($(BR2_AML_USE_DM_VERITY),y)
ROOTFS_CPIO_POST_GEN_HOOKS += ROOTFS-OTA-SWU-PACK
endif

endif

$(eval $(rootfs))
