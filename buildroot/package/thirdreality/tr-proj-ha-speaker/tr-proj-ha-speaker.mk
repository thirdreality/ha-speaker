################################################################################
#
# thirdreality ha speaker project
#
################################################################################

TR_PROJ_HA_SPEAKER_VERSION = 0.1
TR_PROJ_HA_SPEAKER_SITE = $(TOPDIR)/package/thirdreality/tr-proj-ha-speaker
TR_PROJ_HA_SPEAKER_SITE_METHOD = local

TR_PROJ_HA_SPEAKER_INSTALL_TARGET = YES

REALITY_DIR = $(TARGET_DIR)/usr/share/thirdreality

define TR_PROJ_HA_SPEAKER_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/setup_env.sh ${REALITY_DIR}/script/setup_env.sh
	$(INSTALL) -D -m 0755 $(@D)/wifi_connect ${REALITY_DIR}/script/wifi_connect
	$(INSTALL) -D -m 0755 $(@D)/ledring.py ${REALITY_DIR}/script/ledring.py

	$(INSTALL) -D -m 0755 $(@D)/S99voice-assistant $(TARGET_DIR)/etc/init.d/S99voice-assistant
endef

$(eval $(generic-package))
