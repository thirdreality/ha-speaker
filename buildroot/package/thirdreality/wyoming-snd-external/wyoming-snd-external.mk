################################################################################
#
# wyoming-snd-external
#
################################################################################

WYOMING_SND_EXTERNAL_VERSION = f4d6bea4
WYOMING_SND_EXTERNAL_SITE = $(TOPDIR)/package/thirdreality/wyoming-snd-external/src
WYOMING_SND_EXTERNAL_SITE_METHOD = local

WYOMING_SND_EXTERNAL_SETUP_TYPE = setuptools
WYOMING_SND_EXTERNAL_DEPENDENCIES = python-wyoming

$(eval $(python-package))
