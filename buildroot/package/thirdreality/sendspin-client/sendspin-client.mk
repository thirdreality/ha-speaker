################################################################################
#
# sendspin-client
#
# Sendspin synchronized audio streaming client for ThirdReality speaker.
# Builds sendspin-cpp library and a PulseAudio-based client application.
# mDNS advertisement via avahi-daemon service file.
#
################################################################################

SENDSPIN_CLIENT_VERSION = v0.3.1
SENDSPIN_CLIENT_SITE = $(call github,Sendspin,sendspin-cpp,$(SENDSPIN_CLIENT_VERSION))
SENDSPIN_CLIENT_LICENSE = Apache-2.0
SENDSPIN_CLIENT_LICENSE_FILES = LICENSE
SENDSPIN_CLIENT_DEPENDENCIES = pulseaudio avahi zlib

SENDSPIN_CLIENT_CONF_OPTS = \
	-DSENDSPIN_ENABLE_PLAYER=ON \
	-DSENDSPIN_ENABLE_CONTROLLER=ON \
	-DSENDSPIN_ENABLE_METADATA=ON \
	-DSENDSPIN_ENABLE_ARTWORK=OFF \
	-DSENDSPIN_ENABLE_VISUALIZER=OFF \
	-DUSE_TLS=OFF \
	-DUSE_ZLIB=ON \
	-DBUILD_SHARED_LIBS=OFF

# Restructure: put sendspin-cpp source into a subdirectory,
# overlay our CMakeLists.txt and client source at root.
define SENDSPIN_CLIENT_RESTRUCTURE
	$(Q)mkdir -p $(@D)/_sendspin_src
	$(Q)mv $(@D)/CMakeLists.txt $(@D)/cmake $(@D)/include $(@D)/src \
	       $(@D)/examples $(@D)/Kconfig $(@D)/idf_component.yml \
	       $(@D)/_sendspin_src/ 2>/dev/null || true
	$(Q)mv $(@D)/_sendspin_src $(@D)/sendspin-cpp
	$(Q)$(SED) '/add_subdirectory(examples/d' $(@D)/sendspin-cpp/CMakeLists.txt
	$(Q)cp $(SENDSPIN_CLIENT_PKGDIR)/CMakeLists.txt $(@D)/
	$(Q)cp $(SENDSPIN_CLIENT_PKGDIR)/sendspin-client.cpp $(@D)/
endef
SENDSPIN_CLIENT_POST_EXTRACT_HOOKS += SENDSPIN_CLIENT_RESTRUCTURE

# Install avahi service file for mDNS advertisement
define SENDSPIN_CLIENT_INSTALL_AVAHI_SERVICE
	$(INSTALL) -D -m 0644 $(SENDSPIN_CLIENT_PKGDIR)/sendspin.service \
		$(TARGET_DIR)/etc/avahi/services/sendspin.service
endef
SENDSPIN_CLIENT_POST_INSTALL_TARGET_HOOKS += SENDSPIN_CLIENT_INSTALL_AVAHI_SERVICE

$(eval $(cmake-package))
