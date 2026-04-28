################################################################################
#
# python-webrtc-noise-gain
#
################################################################################

PYTHON_WEBRTC_NOISE_GAIN_VERSION = 1.2.5
PYTHON_WEBRTC_NOISE_GAIN_SOURCE = webrtc_noise_gain-$(PYTHON_WEBRTC_NOISE_GAIN_VERSION).tar.gz
PYTHON_WEBRTC_NOISE_GAIN_SITE = https://files.pythonhosted.org/packages/source/w/webrtc-noise-gain
PYTHON_WEBRTC_NOISE_GAIN_LICENSE = MIT
PYTHON_WEBRTC_NOISE_GAIN_SETUP_TYPE = setuptools
PYTHON_WEBRTC_NOISE_GAIN_DEPENDENCIES = python-pybind

# Fix cross-compilation: setup.py uses platform.machine() which returns
# the build host arch. Replace with _PYTHON_HOST_PLATFORM detection.
define PYTHON_WEBRTC_NOISE_GAIN_FIX_CROSS_COMPILE
	$(SED) 's/^system = platform.system().lower()/_hp = os.environ.get("_PYTHON_HOST_PLATFORM", ""); system = _hp.split("-")[0].lower() if _hp else platform.system().lower()/' $(@D)/setup.py
	$(SED) 's/^machine = platform.machine().lower()/machine = _hp.split("-", 1)[1].lower() if _hp and "-" in _hp else platform.machine().lower()/' $(@D)/setup.py
endef
PYTHON_WEBRTC_NOISE_GAIN_POST_EXTRACT_HOOKS += PYTHON_WEBRTC_NOISE_GAIN_FIX_CROSS_COMPILE

$(eval $(python-package))
