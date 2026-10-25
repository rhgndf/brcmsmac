# SPDX-License-Identifier: ISC

KDIR ?= /lib/modules/$(shell uname -r)/build

.PHONY: all modules modules_install clean
all: modules

modules modules_install clean:
	$(MAKE) -C "$(KDIR)" M="$(CURDIR)" $@
