################################################################################
#
# linux voice assistant
#
################################################################################

LINUX_VOICE_ASSISTANT_VERSION = fd4c1d97
LINUX_VOICE_ASSISTANT_SITE = $(TOPDIR)/package/thirdreality/linux-voice-assistant/src
LINUX_VOICE_ASSISTANT_SITE_METHOD = local

LINUX_VOICE_ASSISTANT_SETUP_TYPE = setuptools

define LINUX_VOICE_ASSISTANT_INSTALL_WAKEWORDS
	cp -rf $(@D)/wakewords $(TARGET_DIR)/usr/lib/python3.11/site-packages/
endef
LINUX_VOICE_ASSISTANT_POST_INSTALL_TARGET_HOOKS += LINUX_VOICE_ASSISTANT_INSTALL_WAKEWORDS

$(eval $(python-package))
