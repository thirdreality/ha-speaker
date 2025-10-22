################################################################################
#
# Build the EROFS root filesystem image
#
################################################################################

ROOTFS_EROFS_DEPENDENCIES = host-erofs-utils

ifeq ($(BR2_TARGET_ROOTFS_EROFS_LZ4HC),y)
ROOTFS_EROFS_ARGS += -zlz4hc
endif

ifneq ($(BR2_TARGET_ROOTFS_EROFS_PCLUSTERSIZE),0)
ROOTFS_EROFS_ARGS += -C$(strip $(BR2_TARGET_ROOTFS_EROFS_PCLUSTERSIZE))
endif

define ROOTFS_EROFS_CMD
	$(HOST_DIR)/bin/mkfs.erofs $(ROOTFS_EROFS_ARGS) $@ $(TARGET_DIR)
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
ROOTFS_EROFS_POST_GEN_HOOKS += ROOTFS-USB-IMAGE-PACK
endif #BR2_TARGET_USBTOOL_AMLOGIC


RECOVERY_OTA_DIR := $(patsubst "%",%,$(BR2_RECOVERY_OTA_DIR))
ifneq ($(RECOVERY_OTA_DIR),)
ifeq ($(BR2_TARGET_UBOOT_ENCRYPTION),y)
	RECOVERY_ENC_FLAG="-enc"
endif
define ROOTFS-OTA-SWU-PACK-EROFS
	$(INSTALL) -m 0755 $(RECOVERY_OTA_DIR)/../swu/* $(BINARIES_DIR)
	$(INSTALL) -m 0644 $(RECOVERY_OTA_DIR)/sw-description-emmc-erofs$(RECOVERY_ENC_FLAG) $(BINARIES_DIR)/sw-description
	$(INSTALL) -m 0644 $(RECOVERY_OTA_DIR)/sw-description-emmc-increment$(RECOVERY_ENC_FLAG) $(BINARIES_DIR)/sw-description-increment
	$(INSTALL) -m 0644 $(RECOVERY_OTA_DIR)/ota-package-filelist-emmc-erofs$(RECOVERY_ENC_FLAG) $(BINARIES_DIR)/ota-package-filelist
	$(BINARIES_DIR)/ota_package_create.sh
endef
ROOTFS_EROFS_POST_GEN_HOOKS += ROOTFS-OTA-SWU-PACK-EROFS
endif



$(eval $(rootfs))
