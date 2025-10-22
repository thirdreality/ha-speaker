################################################################################
#
# Build the squashfs root filesystem image
#
################################################################################

ROOTFS_SQUASHFS_DEPENDENCIES = host-squashfs

ROOTFS_SQUASHFS_ARGS = -noappend -processors $(PARALLEL_JOBS)

ifeq ($(BR2_TARGET_ROOTFS_SQUASHFS4_LZ4),y)
ROOTFS_SQUASHFS_ARGS += -comp lz4 -Xhc
else ifeq ($(BR2_TARGET_ROOTFS_SQUASHFS4_LZO),y)
ROOTFS_SQUASHFS_ARGS += -comp lzo
else ifeq ($(BR2_TARGET_ROOTFS_SQUASHFS4_LZMA),y)
ROOTFS_SQUASHFS_ARGS += -comp lzma
else ifeq ($(BR2_TARGET_ROOTFS_SQUASHFS4_XZ),y)
ROOTFS_SQUASHFS_ARGS += -comp xz
else ifeq ($(BR2_TARGET_ROOTFS_SQUASHFS4_ZSTD),y)
ROOTFS_SQUASHFS_ARGS += -comp zstd
else
ROOTFS_SQUASHFS_ARGS += -comp gzip
endif

define ROOTFS_SQUASHFS_CMD
	$(HOST_DIR)/bin/mksquashfs $(TARGET_DIR) $@ $(ROOTFS_SQUASHFS_ARGS)
endef

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
	$(HOST_DIR)/bin/aml_upgrade_pkg_gen.sh \
	$(BR2_TARGET_UBOOT_PLATFORM) $(BR2_TARGET_UBOOT_ENCRYPTION) $(BR2_PACKAGE_SWUPDATE_AB_SUPPORT)
endef
else
define ROOTFS-USB-IMAGE-PACK
	cp -rfL $(UPGRADE_DIR)/* $(BINARIES_DIR)
	BINARIES_DIR=$(BINARIES_DIR) \
	TOOL_DIR=$(HOST_DIR)/bin \
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
# if use dm-verity, do package in rootfs-cpio, not here
ifneq ($(BR2_AML_USE_DM_VERITY),y)
ROOTFS_SQUASHFS_POST_GEN_HOOKS += ROOTFS-USB-IMAGE-PACK
endif
endif #BR2_TARGET_USBTOOL_AMLOGIC


RECOVERY_OTA_DIR := $(patsubst "%",%,$(BR2_RECOVERY_OTA_DIR))
ifneq ($(RECOVERY_OTA_DIR),)
ifeq ($(BR2_TARGET_UBOOT_ENCRYPTION),y)
	RECOVERY_ENC_FLAG="-enc"
endif
define ROOTFS-OTA-SWU-PACK-SQUASHFS
	$(INSTALL) -m 0755 $(RECOVERY_OTA_DIR)/../swu/* $(BINARIES_DIR)
	if [[ "$(BR2_PACKAGE_MTD)" != "y" ]]; then \
		$(INSTALL) -m 0644 $(RECOVERY_OTA_DIR)/sw-description-emmc-squashfs$(RECOVERY_ENC_FLAG) $(BINARIES_DIR)/sw-description; \
		$(INSTALL) -m 0644 $(RECOVERY_OTA_DIR)/sw-description-emmc-increment$(RECOVERY_ENC_FLAG) $(BINARIES_DIR)/sw-description-increment; \
		$(INSTALL) -m 0644 $(RECOVERY_OTA_DIR)/ota-package-filelist-emmc-squashfs$(RECOVERY_ENC_FLAG) $(BINARIES_DIR)/ota-package-filelist; \
	else \
		$(INSTALL) -m 0644 $(RECOVERY_OTA_DIR)/sw-description-nand-squashfs$(RECOVERY_ENC_FLAG) $(BINARIES_DIR)/sw-description; \
		$(INSTALL) -m 0644 $(RECOVERY_OTA_DIR)/sw-description-nand-increment$(RECOVERY_ENC_FLAG) $(BINARIES_DIR)/sw-description-increment; \
		$(INSTALL) -m 0644 $(RECOVERY_OTA_DIR)/ota-package-filelist-nand-squashfs$(RECOVERY_ENC_FLAG) $(BINARIES_DIR)/ota-package-filelist; \
	fi
	$(BINARIES_DIR)/ota_package_create.sh
endef
# if use dm-verity, do package in rootfs-cpio, not here
ifneq ($(BR2_AML_USE_DM_VERITY),y)
ROOTFS_SQUASHFS_POST_GEN_HOOKS += ROOTFS-OTA-SWU-PACK-SQUASHFS
endif
endif



$(eval $(rootfs))
