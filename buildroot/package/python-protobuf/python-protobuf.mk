################################################################################
#
# python-protobuf
#
################################################################################

PYTHON_PROTOBUF_VERSION = 6.30.0
PYTHON_PROTOBUF_SOURCE = protobuf-$(PYTHON_PROTOBUF_VERSION).tar.gz
PYTHON_PROTOBUF_SITE = https://files.pythonhosted.org/packages/source/p/protobuf
PYTHON_PROTOBUF_LICENSE = BSD-3-Clause
PYTHON_PROTOBUF_LICENSE_FILES = LICENSE
PYTHON_PROTOBUF_SETUP_TYPE = setuptools

$(eval $(python-package))