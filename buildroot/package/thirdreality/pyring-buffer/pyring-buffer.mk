################################################################################
#
# pyring-buffer
#
################################################################################

PYRING_BUFFER_VERSION = 5486556c
PYRING_BUFFER_SITE = $(TOPDIR)/package/thirdreality/pyring-buffer/src
PYRING_BUFFER_SITE_METHOD = local

PYRING_BUFFER_SETUP_TYPE = setuptools

$(eval $(python-package))
