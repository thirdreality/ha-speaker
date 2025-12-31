################################################################################
#
# python-pymicro-wakeword
#
################################################################################

PYTHON_PYMICRO_WAKEWORD_VERSION = v2.1.0
PYTHON_PYMICRO_WAKEWORD_SITE = https://github.com/OHF-Voice/pymicro-wakeword.git
PYTHON_PYMICRO_WAKEWORD_SITE_METHOD = git

define PYTHON_PYMICRO_WAKEWORD_INSTALL_SO_LIBS
	$(INSTALL) -D -m 0755 $(TOPDIR)/package/thirdreality/python-pymicro-wakeword/lib/trspk/libtensorflowlite_c.so \
		$(TARGET_DIR)/usr/lib/python3.11/site-packages/pymicro_wakeword/lib/libtensorflowlite_c.so
endef
PYTHON_PYMICRO_WAKEWORD_POST_INSTALL_TARGET_HOOKS += PYTHON_PYMICRO_WAKEWORD_INSTALL_SO_LIBS

PYTHON_PYMICRO_WAKEWORD_SETUP_TYPE = setuptools
PYTHON_PYMICRO_WAKEWORD_DEPENDENCIES = python-pymicro-features

$(eval $(python-package))