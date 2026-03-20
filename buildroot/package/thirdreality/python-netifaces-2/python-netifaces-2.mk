################################################################################
#
# python-netifaces-2
#
################################################################################

PYTHON_NETIFACES_2_VERSION = V0.0.22
PYTHON_NETIFACES_2_SITE = https://github.com/SamuelYvon/netifaces-2.git
PYTHON_NETIFACES_2_SITE_METHOD = git

PYTHON_NETIFACES_2_SETUP_TYPE = maturin

$(eval $(python-package))