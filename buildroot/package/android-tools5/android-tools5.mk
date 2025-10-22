################################################################################
#
# android-tools
#
################################################################################

ANDROID_TOOLS5_SITE = https://launchpad.net/ubuntu/+archive/primary/+files
ANDROID_TOOLS5_VERSION = 5.1.1.r38
ANDROID_TOOLS5_SOURCE = android-tools_$(ANDROID_TOOLS5_VERSION).orig.tar.xz
ANDROID_TOOLS5_EXTRA_DOWNLOADS = android-tools_$(ANDROID_TOOLS5_VERSION)-1.1.debian.tar.xz
HOST_ANDROID_TOOLS5_EXTRA_DOWNLOADS = $(ANDROID_TOOLS5_EXTRA_DOWNLOADS)
ANDROID_TOOLS5_LICENSE = Apache-2.0
ANDROID_TOOLS5_LICENSE_FILES = debian/copyright
ANDROID_TOOLS5_DEPENDENCIES = host-pkgconf libcap  openssl pcre zlib
HOST_ANDROID_TOOLS5_DEPENDENCIES = host-openssl host-pkgconf host-zlib

# Target android_arch selection
ifeq ($(BR2_arm),y)
ifeq ($(BR2_ARCH_IS_64),y)
ANDROID_TOOLS5_ANDROID_ARCH = arm64
else
ANDROID_TOOLS5_ANDROID_ARCH = arm
endif
else ifeq ($(BR2_mips),y)
ANDROID_TOOLS5_ANDROID_ARCH = mips
else ifeq ($(BR2_mips64),y)
ANDROID_TOOLS5_ANDROID_ARCH = mips64
else
ANDROID_TOOLS5_ANDROID_ARCH = x86
endif

ANDROID_TOOLS5_TARGET_MAKE_ENV = \
	$(TARGET_MAKE_ENV) \
	android_arch=linux-$(ANDROID_TOOLS5_ANDROID_ARCH)

# Host android_arch: use generic x86 AndroidConfig.h
# The AndroidConfig.h not contain any arch-specific code
ANDROID_TOOLS5_HOST_MAKE_ENV = \
	$(HOST_MAKE_ENV) \
	android_arch=linux-x86

# Extract the Debian tarball inside the sources
define ANDROID_TOOLS5_DEBIAN_EXTRACT
	$(call suitable-extractor,$(notdir $(ANDROID_TOOLS5_EXTRA_DOWNLOADS))) \
		$(ANDROID_TOOLS5_DL_DIR)/$(notdir $(ANDROID_TOOLS5_EXTRA_DOWNLOADS)) | \
		$(TAR) -C $(@D) $(TAR_OPTIONS) -
endef

HOST_ANDROID_TOOLS5_POST_EXTRACT_HOOKS += ANDROID_TOOLS5_DEBIAN_EXTRACT
ANDROID_TOOLS5_POST_EXTRACT_HOOKS += ANDROID_TOOLS5_DEBIAN_EXTRACT

# Apply the Debian patches before applying the Buildroot patches
define ANDROID_TOOLS5_DEBIAN_PATCH
	$(APPLY_PATCHES) $(@D) $(@D)/debian/patches \*
endef

HOST_ANDROID_TOOLS5_PRE_PATCH_HOOKS += ANDROID_TOOLS5_DEBIAN_PATCH
ANDROID_TOOLS5_PRE_PATCH_HOOKS += ANDROID_TOOLS5_DEBIAN_PATCH

ifeq ($(BR2_PACKAGE_HOST_ANDROID_TOOLS5_FASTBOOT),y)
HOST_ANDROID_TOOLS5_BUILD_TARGETS += fastboot
HOST_ANDROID_TOOLS5_INSTALL_TARGETS += build-fastboot/fastboot
HOST_ANDROID_TOOLS5_DEPENDENCIES += host-libselinux
endif

ifeq ($(BR2_PACKAGE_HOST_ANDROID_TOOLS5_ADB),y)
HOST_ANDROID_TOOLS5_BUILD_TARGETS += adb
HOST_ANDROID_TOOLS5_INSTALL_TARGETS += build-adb/adb
endif

ifeq ($(BR2_PACKAGE_HOST_ANDROID_TOOLS5_EXT4_UTILS),y)
HOST_ANDROID_TOOLS5_BUILD_TARGETS += ext4_utils
HOST_ANDROID_TOOLS5_INSTALL_TARGETS += \
	$(addprefix build-ext4_utils/,make_ext4fs ext4fixup ext2simg img2simg simg2img simg2simg)
HOST_ANDROID_TOOLS5_DEPENDENCIES += host-libselinux
endif

ifeq ($(BR2_PACKAGE_ANDROID_TOOLS5_FASTBOOT),y)
ANDROID_TOOLS5_TARGETS += fastboot
endif

ifeq ($(BR2_PACKAGE_ANDROID_TOOLS5_ADB),y)
ANDROID_TOOLS5_TARGETS += adb
endif

ifeq ($(BR2_PACKAGE_ANDROID_TOOLS5_ADBD),y)
ANDROID_TOOLS5_TARGETS += adbd
endif

# Build each tool in its own directory not to share object files

define HOST_ANDROID_TOOLS5_BUILD_CMDS
	$(foreach t,$(HOST_ANDROID_TOOLS5_BUILD_TARGETS),\
		mkdir -p $(@D)/build-$(t) && \
		$(ANDROID_TOOLS5_HOST_MAKE_ENV) $(HOST_CONFIGURE_OPTS) $(MAKE) \
			SRCDIR=$(@D) -C $(@D)/build-$(t) -f $(@D)/debian/makefiles/$(t).mk$(sep))
endef

define ANDROID_TOOLS5_BUILD_CMDS
	$(foreach t,$(ANDROID_TOOLS5_TARGETS),\
		mkdir -p $(@D)/build-$(t) && \
		$(ANDROID_TOOLS5_TARGET_MAKE_ENV) $(TARGET_CONFIGURE_OPTS) $(MAKE) \
			SRCDIR=$(@D) -C $(@D)/build-$(t) -f $(@D)/debian/makefiles/$(t).mk$(sep))
endef

define HOST_ANDROID_TOOLS5_INSTALL_CMDS
	$(foreach t,$(HOST_ANDROID_TOOLS5_INSTALL_TARGETS),\
		$(INSTALL) -D -m 0755 $(@D)/$(t) $(HOST_DIR)/bin/$(notdir $(t))$(sep))
endef

define ANDROID_TOOLS5_INSTALL_TARGET_CMDS
	$(foreach t,$(ANDROID_TOOLS5_TARGETS),\
		$(INSTALL) -D -m 0755 $(@D)/build-$(t)/$(t) $(TARGET_DIR)/usr/bin/$(t)$(sep))
endef

$(eval $(generic-package))
$(eval $(host-generic-package))
