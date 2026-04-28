################################################################################
#
# linux-voice-assistant
#
################################################################################

LINUX_VOICE_ASSISTANT_VERSION = v1.1.10
LINUX_VOICE_ASSISTANT_SITE = $(TOPDIR)/package/thirdreality/linux-voice-assistant/src
LINUX_VOICE_ASSISTANT_SITE_METHOD = local

LINUX_VOICE_ASSISTANT_SETUP_TYPE = setuptools
LINUX_VOICE_ASSISTANT_DEPENDENCIES = \
	python-aioesphomeapi \
	python-netifaces-2 \
	python-soundcard \
	python-numpy \
	python-pymicro-wakeword \
	pyopen-wakeword \
	python-mpv \
	python-zeroconf \
	python-getmac \
	python-webrtc-noise-gain

define LINUX_VOICE_ASSISTANT_INSTALL_FILES
	cp -rf $(@D)/wakewords $(TARGET_DIR)/usr/lib/python3.11/site-packages/
	cp -rf $(@D)/sounds $(TARGET_DIR)/usr/lib/python3.11/site-packages/
endef
LINUX_VOICE_ASSISTANT_POST_INSTALL_TARGET_HOOKS += LINUX_VOICE_ASSISTANT_INSTALL_FILES

$(eval $(python-package))
