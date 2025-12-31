################################################################################
#
# python-pymicro-features
#
################################################################################

PYTHON_PYMICRO_FEATURES_VERSION = v2.0.2
PYTHON_PYMICRO_FEATURES_SITE = https://github.com/rhasspy/pymicro-features.git
PYTHON_PYMICRO_FEATURES_SITE_METHOD = git

PYTHON_PYMICRO_FEATURES_SETUP_TYPE = setuptools

$(eval $(python-package))