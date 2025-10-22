################################################################################
#
# python-wyoming
#
################################################################################

PYTHON_WYOMING_VERSION = 1.8.0
PYTHON_WYOMING_SOURCE = wyoming-$(PYTHON_WYOMING_VERSION).tar.gz
PYTHON_WYOMING_SITE = https://files.pythonhosted.org/packages/source/w/wyoming
PYTHON_WYOMING_SETUP_TYPE = setuptools
PYTHON_WYOMING_LICENSE = MIT
PYTHON_WYOMING_LICENSE_FILES = LICENSE

$(eval $(python-package))