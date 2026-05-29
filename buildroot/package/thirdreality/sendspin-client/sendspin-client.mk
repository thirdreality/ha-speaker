################################################################################
#
# sendspin-client
#
# Sendspin synchronized audio streaming client for ThirdReality speaker.
# Builds sendspin-cpp library and a PulseAudio-based client application.
# mDNS advertisement via avahi-daemon service file.
#
################################################################################

SENDSPIN_CLIENT_VERSION = v0.6.1
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
	-DSENDSPIN_ENABLE_COLOR=OFF \
	-DUSE_TLS=OFF \
	-DUSE_ZLIB=ON \
	-DBUILD_SHARED_LIBS=OFF

# Restructure: move upstream sendspin-cpp source into a subdirectory and
# overlay our wrapper CMakeLists.txt + client source at the build dir root.
#
# This must happen in POST_EXTRACT (not PRE_BUILD or PRE_CONFIGURE),
# because cmake configure runs on $(@D) and needs to see CMakeLists.txt
# already in place. Hooks earlier than configure don't fire on a plain
# `<pkg>-rebuild`; if you edit sendspin-client.cpp and want to re-pick it
# up without a full extract, use `<pkg>-reconfigure` (which also doesn't
# re-cp here, so dirclean is the safe fallback) or just dirclean the
# package build dir.
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
