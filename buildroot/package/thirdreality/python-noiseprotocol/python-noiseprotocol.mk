################################################################################
#
# python-noiseprotocol
#
# Noise Protocol Framework implementation.
#
# Runtime dependencies:
#   cryptography  - Cryptographic primitives (Diffie-Hellman, AES-GCM, etc.)
#
################################################################################

PYTHON_NOISEPROTOCOL_VERSION = v0.3.1
PYTHON_NOISEPROTOCOL_SITE = https://github.com/plizonczyk/noiseprotocol.git
PYTHON_NOISEPROTOCOL_SITE_METHOD = git

PYTHON_NOISEPROTOCOL_SETUP_TYPE = setuptools
PYTHON_NOISEPROTOCOL_DEPENDENCIES = python-cryptography

$(eval $(python-package))
