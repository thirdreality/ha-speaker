################################################################################
#
# python-chacha20poly1305-reuseable
#
# Reusable ChaCha20-Poly1305 AEAD cipher.
#
# Runtime dependencies:
#   cryptography  - Cryptographic primitives
#
################################################################################

PYTHON_CHACHA20POLY1305_REUSEABLE_VERSION = v0.13.2
PYTHON_CHACHA20POLY1305_REUSEABLE_SITE = https://github.com/bdraco/chacha20poly1305-reuseable.git
PYTHON_CHACHA20POLY1305_REUSEABLE_SITE_METHOD = git

PYTHON_CHACHA20POLY1305_REUSEABLE_SETUP_TYPE = setuptools
PYTHON_CHACHA20POLY1305_REUSEABLE_DEPENDENCIES = python-cryptography

$(eval $(python-package))
