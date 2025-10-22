################################################################################
#
# wyoming-openwakeword
#
################################################################################

WYOMING_OPENWAKEWORD_VERSION = 419701f6
WYOMING_OPENWAKEWORD_SITE = $(TOPDIR)/package/thirdreality/wyoming-openwakeword/src
WYOMING_OPENWAKEWORD_SITE_METHOD = local

WYOMING_OPENWAKEWORD_SETUP_TYPE = setuptools
WYOMING_OPENWAKEWORD_DEPENDENCIES = python-wyoming

$(eval $(python-package))
