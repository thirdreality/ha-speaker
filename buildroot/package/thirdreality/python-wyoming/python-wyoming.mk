################################################################################
#
# python-wyoming
#
################################################################################

PYTHON_WYOMING_VERSION = 1.5.4
PYTHON_WYOMING_SOURCE = $(PYTHON_WYOMING_VERSION).tar.gz
PYTHON_WYOMING_SITE = https://github.com/OHF-Voice/wyoming/archive/refs/tags
PYTHON_WYOMING_SETUP_TYPE = setuptools
PYTHON_WYOMING_LICENSE = MIT
PYTHON_WYOMING_LICENSE_FILES = LICENSE

$(eval $(python-package))
