################################################################################
#
# python-aioesphomeapi
#
################################################################################

PYTHON_AIOESPHOMEAPI_VERSION = v42.7.0
PYTHON_AIOESPHOMEAPI_SITE = https://github.com/esphome/aioesphomeapi.git
PYTHON_AIOESPHOMEAPI_SITE_METHOD = git

PYTHON_AIOESPHOMEAPI_SETUP_TYPE = setuptools

$(eval $(python-package))