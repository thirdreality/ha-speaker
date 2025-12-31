################################################################################
#
# python-tzlocal
#
################################################################################

PYTHON_TZLOCAL_VERSION = 5.3.1
PYTHON_TZLOCAL_SITE = https://github.com/regebro/tzlocal.git
PYTHON_TZLOCAL_SITE_METHOD = git

PYTHON_TZLOCAL_SETUP_TYPE = setuptools

$(eval $(python-package))