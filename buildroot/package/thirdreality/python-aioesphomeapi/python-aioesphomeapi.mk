################################################################################
#
# python-aioesphomeapi
#
################################################################################

PYTHON_AIOESPHOMEAPI_VERSION = v42.7.0
PYTHON_AIOESPHOMEAPI_SITE = https://github.com/esphome/aioesphomeapi.git
PYTHON_AIOESPHOMEAPI_SITE_METHOD = git

PYTHON_AIOESPHOMEAPI_SETUP_TYPE = setuptools
PYTHON_AIOESPHOMEAPI_DEPENDENCIES = python-protobuf python-cryptography python-noiseprotocol python-chacha20poly1305-reuseable

$(eval $(python-package))