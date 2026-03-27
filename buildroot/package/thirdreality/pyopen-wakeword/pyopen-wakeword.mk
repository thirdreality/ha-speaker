################################################################################
#
# pyopen-wakeword
#
################################################################################

PYOPEN_WAKEWORD_VERSION = v1.1.0
PYOPEN_WAKEWORD_SITE = $(TOPDIR)/package/thirdreality/pyopen-wakeword/src
PYOPEN_WAKEWORD_SITE_METHOD = local

PYOPEN_WAKEWORD_SETUP_TYPE = setuptools

define PYOPEN_WAKEWORD_INSTALL_SO_LIBS
	$(INSTALL) -D -m 0755 $(@D)/lib/trspk/libtensorflowlite_c.so \
		$(TARGET_DIR)/usr/lib/python3.11/site-packages/pyopen_wakeword/lib/libtensorflowlite_c.so
endef
PYOPEN_WAKEWORD_POST_INSTALL_TARGET_HOOKS += PYOPEN_WAKEWORD_INSTALL_SO_LIBS

$(eval $(python-package))