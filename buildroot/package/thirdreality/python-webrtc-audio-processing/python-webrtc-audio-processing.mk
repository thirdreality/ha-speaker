################################################################################
#
# python-webrtc-audio-processing
#
################################################################################

PYTHON_WEBRTC_AUDIO_PROCESSING_VERSION = 0637014c
PYTHON_WEBRTC_AUDIO_PROCESSING_SITE = https://github.com/xiongyihui/python-webrtc-audio-processing.git
PYTHON_WEBRTC_AUDIO_PROCESSING_SITE_METHOD = git
PYTHON_WEBRTC_AUDIO_PROCESSING_GIT_SUBMODULES = YES
PYTHON_WEBRTC_AUDIO_PROCESSING_SETUP_TYPE = setuptools
PYTHON_WEBRTC_AUDIO_PROCESSING_LICENSE = MIT
PYTHON_WEBRTC_AUDIO_PROCESSING_LICENSE_FILES = LICENSE

# Build dependencies
PYTHON_WEBRTC_AUDIO_PROCESSING_DEPENDENCIES = host-swig host-python3

# Set environment variables to trigger ARM build path in setup.py
PYTHON_WEBRTC_AUDIO_PROCESSING_ENV = \
	BITBAKE_BUILD=1 \
	TARGET_SYS=$(GNU_TARGET_NAME) \
	TARGET_CC_ARCH="$(TARGET_CFLAGS)"

$(eval $(python-package))