################################################################################
#
# python-aioesphomeapi
#
# ESPHome native API client (protobuf + chacha20poly1305 encryption).
#
# Runtime dependencies (from requirements/base.txt):
#   aiohappyeyeballs          - Happy Eyeballs connection algorithm
#   async-interrupt           - Async context manager for interrupts
#   protobuf                  - Protocol Buffers serialization
#   tzlocal                   - Local timezone detection
#   zeroconf                  - mDNS service discovery
#   chacha20poly1305-reuseable - Reusable ChaCha20-Poly1305 cipher
#   cryptography              - Cryptographic primitives
#   noiseprotocol             - Noise Protocol Framework
#
################################################################################

PYTHON_AIOESPHOMEAPI_VERSION = v42.7.0
PYTHON_AIOESPHOMEAPI_SITE = https://github.com/esphome/aioesphomeapi.git
PYTHON_AIOESPHOMEAPI_SITE_METHOD = git

PYTHON_AIOESPHOMEAPI_SETUP_TYPE = setuptools
PYTHON_AIOESPHOMEAPI_DEPENDENCIES = \
	python-aiohappyeyeballs \
	python-async-interrupt \
	python-protobuf \
	python-tzlocal \
	python-zeroconf \
	python-chacha20poly1305-reuseable \
	python-cryptography \
	python-noiseprotocol

$(eval $(python-package))
