################################################################################
#
# bluez5_inc
#
################################################################################

# Keep the version and patches in sync with bluez5_inc
BLUEZ_INC_VERSION = 821f6d5839f88b708d781330cc0e785ce6ac9f0b
BLUEZ_INC_SITE = $(call github,weliem,bluez_inc,$(BLUEZ_INC_VERSION))
BLUEZ_INC_LICENSE = MIT
BLUEZ_INC_LICENSE_FILES = LICENSE
BLUEZ_INC_DEPENDENCIES = libglib2

BLUEZ_INC_INSTALL_STAGING = YES
BLUEZ_INC_INSTALL_TARGET = YES

define BLUEZ_INC_INSTALL_STAGING_CMDS
	$(INSTALL) -d $(STAGING_DIR)/usr/include/binc
	$(INSTALL) -m 644 $(@D)/binc/*.h $(STAGING_DIR)/usr/include/binc
	$(INSTALL) -m 644 $(@D)/binc/libBinc.so $(STAGING_DIR)/usr/lib
endef

define BLUEZ_INC_INSTALL_TARGET_CMDS
	$(INSTALL) -m 644 $(@D)/binc/libBinc.so $(TARGET_DIR)/usr/lib
endef

$(eval $(cmake-package))

