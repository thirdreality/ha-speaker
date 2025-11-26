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

ifdef SPEAKER_FIRMWARE_VERSION
	IMAGE_VERSION=$(SPEAKER_FIRMWARE_VERSION)
else
	IMAGE_VERSION=$(shell date "+0.%m.%d")
endif

define TR_PROJ_HA_SPEAKER_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/device.json ${REALITY_DIR}/conf/device.json
	$(INSTALL) -D -m 0755 $(@D)/setup_env.sh ${REALITY_DIR}/script/setup_env.sh
	$(INSTALL) -D -m 0755 $(@D)/wifi_connect ${REALITY_DIR}/script/wifi_connect
	$(INSTALL) -D -m 0755 $(@D)/ledring.py ${REALITY_DIR}/script/ledring.py
	$(INSTALL) -D -m 0755 $(@D)/S99voice-assistant $(TARGET_DIR)/etc/init.d/S99voice-assistant

	@echo "firmwareVersion is $(IMAGE_VERSION)"
	@jq '.device.firmwareVersion = "$(IMAGE_VERSION)"' $(TARGET_DIR)/usr/share/thirdreality/conf/device.json > \
		tmp.$$.json && mv tmp.$$.json $(TARGET_DIR)/usr/share/thirdreality/conf/device.json

endef

$(eval $(generic-package))
