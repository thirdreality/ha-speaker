################################################################################
#
# webrtc-noise-gain
#
################################################################################

WEBRTC_NOISE_GAIN_VERSION = 1.2.5
WEBRTC_NOISE_GAIN_SITE = $(TOPDIR)/package/thirdreality/webrtc-noise-gain/src
WEBRTC_NOISE_GAIN_SITE_METHOD = local

WEBRTC_NOISE_GAIN_SETUP_TYPE = setuptools

WEBRTC_NOISE_GAIN_DEPENDENCIES = python3
WEBRTC_NOISE_GAIN_BUILD_DEPENDENCIES = host-python-pybind

WEBRTC_NOISE_GAIN_ENV = \
	BITBAKE_BUILD=1 \
	TARGET_SYS=$(GNU_TARGET_NAME) \
	TARGET_CC_ARCH="$(TARGET_CFLAGS)"

define WEBRTC_NOISE_GAIN_FIX_CROSS_COMPILE
	$(SED) 's/machine = platform\.machine()\.lower()/machine = "aarch64"/' \
		$(@D)/setup.py
endef
WEBRTC_NOISE_GAIN_POST_PATCH_HOOKS += WEBRTC_NOISE_GAIN_FIX_CROSS_COMPILE

$(eval $(python-package))