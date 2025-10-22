#############################################################
#
# ThirdReality LED Ring
#
#############################################################

TR_LEDRING_VERSION = 0.1
TR_LEDRING_SITE = $(TOPDIR)/package/thirdreality/tr-ledring
TR_LEDRING_SITE_METHOD = local

TR_LEDRING_DEPENDENCIES = flex libglib2

define TR_LEDRING_BUILD_CMDS
	$(TARGET_CONFIGURE_OPTS) $(MAKE) CC=$(TARGET_CC) -C $(@D)/src all
endef

REALITY_DIR = $(TARGET_DIR)/usr/share/thirdreality

define TR_LEDRING_INSTALL_TARGET_CMDS
	mkdir -p $(REALITY_DIR)/animation/
	$(INSTALL) -D -m 0644 $(@D)/amz-led-animation/single/* $(REALITY_DIR)/animation/
	$(INSTALL) -D -m 0644 $(@D)/tr-ledring-dbus.conf $(TARGET_DIR)/etc/dbus-1/system.d/tr-ledring-dbus.conf

	$(TARGET_CONFIGURE_OPTS) $(MAKE) CC=$(TARGET_CC) -C $(@D)/src install
endef

define TR_LEDRING_GENERATE_GDBUS_BINDING
	cd $(@D)/src && \
		gdbus-codegen --interface-prefix=com._3reality.LedringService. --generate-c-code=3r_ledring_binding  3r.ledring_service.xml && \
		mv 3r_ledring_binding.c 3r_ledring_binding.cpp
endef

TR_LEDRING_POST_PATCH_HOOKS += TR_LEDRING_GENERATE_GDBUS_BINDING

$(eval $(generic-package))
