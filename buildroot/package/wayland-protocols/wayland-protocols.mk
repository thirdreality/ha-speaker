################################################################################
#
# wayland-protocols
#
################################################################################

ifneq ($(BR2_PACKAGE_WAYLAND_PROTOCOLS_VERSION),"")
WAYLAND_PROTOCOLS_VERSION = $(call qstrip,$(BR2_PACKAGE_WAYLAND_PROTOCOLS_VERSION))
else
WAYLAND_PROTOCOLS_VERSION = 1.20
endif
WAYLAND_PROTOCOLS_SITE = http://wayland.freedesktop.org/releases
WAYLAND_PROTOCOLS_SOURCE = wayland-protocols-$(WAYLAND_PROTOCOLS_VERSION).tar.xz
WAYLAND_PROTOCOLS_LICENSE = MIT
WAYLAND_PROTOCOLS_LICENSE_FILES = COPYING
WAYLAND_PROTOCOLS_INSTALL_STAGING = YES
WAYLAND_PROTOCOLS_INSTALL_TARGET = NO

$(eval $(autotools-package))
