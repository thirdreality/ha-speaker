################################################################################
#
# wyoming-satellite
#
################################################################################

WYOMING_SATELLITE_VERSION = 13bb0249
WYOMING_SATELLITE_SITE = $(TOPDIR)/package/thirdreality/wyoming-satellite/src
WYOMING_SATELLITE_SITE_METHOD = local

WYOMING_SATELLITE_SETUP_TYPE = setuptools
WYOMING_SATELLITE_DEPENDENCIES = python-wyoming

$(eval $(python-package))
