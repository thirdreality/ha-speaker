################################################################################
#
# liblc3
#
################################################################################

LIBLC3_VERSION = 1.1.3
LIBLC3_SOURCE = v$(LIBLC3_VERSION).tar.gz
LIBLC3_SITE = https://github.com/google/liblc3/archive
LIBLC3_LICENSE = Apache
LIBLC3_LICENSE_FILES = LICENSE
LIBLC3_INSTALL_STAGING = YES

$(eval $(meson-package))
