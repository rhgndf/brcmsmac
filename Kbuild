# SPDX-License-Identifier: ISC
#
# Out-of-tree build of drivers/net/wireless/broadcom/brcm80211/brcmsmac.
# The directory layout mirrors brcm80211/ so that brcmsmac/Makefile finds
# the shared headers in $(src)/../include.

# The kernel configuration is not read when cleaning.
ifdef CONFIG_MODULES
ifneq ($(CONFIG_BRCMSMAC),m)
$(error target kernel must be configured with CONFIG_BRCMSMAC=m)
endif
endif

subdir-ccflags-$(CONFIG_BRCMDBG)	+= -DDEBUG

obj-m	+= brcmsmac/
