################################################################################
#
# python-async-interrupt
#
################################################################################

PYTHON_ASYNC_INTERRUPT_VERSION = v1.1.1
PYTHON_ASYNC_INTERRUPT_SITE = https://github.com/Bluetooth-Devices/async_interrupt.git
PYTHON_ASYNC_INTERRUPT_SITE_METHOD = git

PYTHON_ASYNC_INTERRUPT_SETUP_TYPE = setuptools
PYTHON_ASYNC_INTERRUPT_LICENSE = Apache-2.0
PYTHON_ASYNC_INTERRUPT_LICENSE_FILES = LICENSE

$(eval $(python-package))


# PYTHON_ASYNC_INTERRUPT_VERSION = 1.2.2
# PYTHON_ASYNC_INTERRUPT_SOURCE = async_interrupt-$(PYTHON_ASYNC_INTERRUPT_VERSION).tar.gz
# PYTHON_ASYNC_INTERRUPT_SITE = https://files.pythonhosted.org/packages/source/a/async_interrupt
# PYTHON_ASYNC_INTERRUPT_SETUP_TYPE = setuptools
# PYTHON_ASYNC_INTERRUPT_LICENSE = Apache-2.0
# PYTHON_ASYNC_INTERRUPT_LICENSE_FILES = LICENSE

# $(eval $(python-package))