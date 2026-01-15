################################################################################
#
# pyring-buffer
#
################################################################################

PYRING_BUFFER_VERSION = v1.0.2
PYRING_BUFFER_SITE = https://github.com/rhasspy/pyring-buffer
PYRING_BUFFER_SITE_METHOD = git

PYRING_BUFFER_SETUP_TYPE = setuptools

$(eval $(python-package))
