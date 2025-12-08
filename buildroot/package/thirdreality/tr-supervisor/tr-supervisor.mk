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
	cp -rf $(TR_SUPERVISOR_SITE) $(TR_SUPERVISOR_PKG_DIR)
endef

# define TR_SUPERVISOR_COMPILE_PYC
# 	PYTHONPATH="$(TARGET_DIR)/usr/lib/python$(PYTHON3_VERSION_MAJOR)" \
# 	$(HOST_DIR)/bin/python$(PYTHON3_VERSION_MAJOR) -m compileall -q $(TR_SUPERVISOR_PKG_DIR)
# endef

# define TR_SUPERVISOR_REMOVE_PY
# 	find $(HTTP_PKG_DIR) -name '*.py' -print0 | xargs -0 --no-run-if-empty rm -f
# 	rm -rf $(HTTP_PKG_DIR)/*.py
# endef

# TR_SUPERVISOR_POST_INSTALL_TARGET_HOOKS += TR_SUPERVISOR_COMPILE_PYC TR_SUPERVISOR_REMOVE_PY

$(eval $(generic-package))