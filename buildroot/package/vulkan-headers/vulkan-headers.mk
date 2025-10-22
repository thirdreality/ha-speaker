################################################################################
#
# vulkan-headers
#
################################################################################

VULKAN_HEADERS_VERSION = 1.2.196
VULKAN_HEADERS_SITE = $(call github,KhronosGroup,Vulkan-Headers,v$(VULKAN_HEADERS_VERSION))
VULKAN_HEADERS_LICENSE = Apache-2.0
VULKAN_HEADERS_LICENSE_FILES = LICENSE.txt
VULKAN_HEADERS_INSTALL_STAGING = YES

define VULKAN_HEADERS_CLEAN_INSTALL_REGISTRY
	rm -rf $(TARGET_DIR)/usr/share/vulkan/registry
endef
VULKAN_HEADERS_POST_INSTALL_TARGET_HOOKS += VULKAN_HEADERS_CLEAN_INSTALL_REGISTRY

$(eval $(cmake-package))
