#############################################################
#
# aml ubootenv
#
#############################################################
AML_UBOOTENV_VERSION = 0.1
AML_UBOOTENV_SITE = $(TOPDIR)/../sources/aml-commonlib/ubootenv
AML_UBOOTENV_SITE_METHOD = local
AML_UBOOTENV_DEPENDENCIES += libzlib

ifeq ($(BR2_TARGET_UBOOT_PLATFORM), "a1")
UBOOTENV_CFLAGS = "$(TARGET_CFLAGS) -DA1_ENVSIZE"
else
UBOOTENV_CFLAGS = "$(TARGET_CFLAGS)"
endif

define AML_UBOOTENV_BUILD_CMDS
	$(TARGET_CONFIGURE_OPTS) CFLAGS=$(UBOOTENV_CFLAGS) $(MAKE) -C $(@D) all
endef

define AML_UBOOTENV_INSTALL_TARGET_CMDS
	$(TARGET_CONFIGURE_OPTS) $(MAKE) CC=$(TARGET_CC) -C $(@D) install
endef

$(eval $(generic-package))
