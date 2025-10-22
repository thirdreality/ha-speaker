################################################################################
#
# wyoming-mic-external
#
################################################################################

WYOMING_MIC_EXTERNAL_VERSION = 7dab7b72
WYOMING_MIC_EXTERNAL_SITE = $(TOPDIR)/package/thirdreality/wyoming-mic-external/src
WYOMING_MIC_EXTERNAL_SITE_METHOD = local

WYOMING_MIC_EXTERNAL_SETUP_TYPE = setuptools
WYOMING_MIC_EXTERNAL_DEPENDENCIES = python-wyoming

$(eval $(python-package))