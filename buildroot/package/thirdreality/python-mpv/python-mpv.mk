################################################################################
#
# python-mpv
#
################################################################################

PYTHON_MPV_VERSION = v1.0.8
PYTHON_MPV_SITE = https://github.com/jaseg/python-mpv.git
PYTHON_MPV_SITE_METHOD = git

PYTHON_MPV_SETUP_TYPE = setuptools
PYTHON_MPV_DEPENDENCIES = mpv

$(eval $(python-package))