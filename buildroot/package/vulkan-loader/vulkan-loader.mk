################################################################################
#
# vulkan-loader
#
################################################################################

VULKAN_LOADER_VERSION = 1.2.196
VULKAN_LOADER_SITE = $(call github,KhronosGroup,Vulkan-Loader,v$(VULKAN_LOADER_VERSION))
VULKAN_LOADER_LICENSE = Apache-2.0
VULKAN_LOADER_LICENSE_FILES = LICENSE.txt
VULKAN_LOADER_INSTALL_STAGING = YES

VULKAN_LOADER_DEPENDENCIES = vulkan-headers

VULKAN_LOADER_CONF_OPTS += \
	-DBUILD_WSI_XCB_SUPPORT=OFF \
	-DBUILD_WSI_XLIB_SUPPORT=OFF \
	-DBUILD_WSI_WAYLAND_SUPPORT=OFF \
	-DBUILD_WSI_DIRECTFB_SUPPORT=OFF \
	-DUSE_CCACHE=OFF

$(eval $(cmake-package))
