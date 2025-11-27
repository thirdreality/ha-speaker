################################################################################
#
# wyoming-satellite
#
################################################################################

WYOMING_SATELLITE_VERSION = ha-spk
WYOMING_SATELLITE_SITE = https://github.com/thirdreality/wyoming-satellite.git
WYOMING_SATELLITE_SITE_METHOD = git

WYOMING_SATELLITE_SETUP_TYPE = setuptools
WYOMING_SATELLITE_DEPENDENCIES = python-wyoming

$(eval $(python-package))
