################################################################################
#
# python-pymicro-wakeword
#
# Micro wake word detection engine.
#
# Runtime dependencies (from pyproject.toml):
#   pymicro-features  - Audio feature extraction (C++ extension)
#   numpy             - Array processing
#
################################################################################

PYTHON_PYMICRO_WAKEWORD_VERSION = v2.1.0
PYTHON_PYMICRO_WAKEWORD_SITE = https://github.com/OHF-Voice/pymicro-wakeword.git
PYTHON_PYMICRO_WAKEWORD_SITE_METHOD = git

define PYTHON_PYMICRO_WAKEWORD_INSTALL_SO_LIBS
	mkdir -p $(TARGET_DIR)/usr/lib/python3.11/site-packages/pymicro_wakeword/lib
	ln -sf ../../pyopen_wakeword/lib/libtensorflowlite_c.so \
		$(TARGET_DIR)/usr/lib/python3.11/site-packages/pymicro_wakeword/lib/libtensorflowlite_c.so
endef
PYTHON_PYMICRO_WAKEWORD_POST_INSTALL_TARGET_HOOKS += PYTHON_PYMICRO_WAKEWORD_INSTALL_SO_LIBS

PYTHON_PYMICRO_WAKEWORD_SETUP_TYPE = setuptools
PYTHON_PYMICRO_WAKEWORD_DEPENDENCIES = \
	python-pymicro-features \
	python-numpy

$(eval $(python-package))
