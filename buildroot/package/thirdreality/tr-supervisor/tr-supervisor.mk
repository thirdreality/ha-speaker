################################################################################
#
# tr-supervisor
#
################################################################################

TR_SUPERVISOR_VERSION = 0.1
TR_SUPERVISOR_SITE = $(TOPDIR)/package/thirdreality/tr-supervisor/src
TR_SUPERVISOR_SITE_METHOD = local
TR_SUPERVISOR_DEPENDENCIES = host-python3 python3
TR_SUPERVISOR_INSTALL_TARGET = YES

TR_SUPERVISOR_PKG_DIR = $(TARGET_DIR)/usr/lib/python$(PYTHON3_VERSION_MAJOR)/site-packages/supervisor

define TR_SUPERVISOR_INSTALL_TARGET_CMDS
	rm -rf $(TR_SUPERVISOR_PKG_DIR)
	cp -rf $(TR_SUPERVISOR_SITE) $(TR_SUPERVISOR_PKG_DIR)
endef

$(eval $(generic-package))
