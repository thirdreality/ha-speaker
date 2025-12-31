################################################################################
#
# python-soundcard
#
################################################################################

PYTHON_SOUNDCARD_VERSION = 0.4.5
PYTHON_SOUNDCARD_SOURCE = soundcard-$(PYTHON_SOUNDCARD_VERSION).tar.gz
PYTHON_SOUNDCARD_SITE = https://files.pythonhosted.org/packages/source/s/soundcard
PYTHON_SOUNDCARD_SETUP_TYPE = setuptools
PYTHON_SOUNDCARD_LICENSE = BSD-3-Clause
PYTHON_SOUNDCARD_DEPENDENCIES = python-cffi host-python-cffi

$(eval $(python-package))