# brcmsmac

Out-of-tree build of the Linux `brcmsmac` driver for Broadcom IEEE 802.11n
PCIe SoftMAC chips (`drivers/net/wireless/broadcom/brcm80211/brcmsmac`).

The tree keeps the upstream layout: `brcmsmac/` is the driver and `include/`
is the shared `brcm80211/include`. Patches therefore apply to a Linux tree
with `git am --directory=drivers/net/wireless/broadcom/brcm80211`.

## Building

Requires the target kernel's build tree configured with `CONFIG_BRCMSMAC=m`
(the module links against the in-tree `brcmutil`), and pahole for BTF
kernels.

```sh
make -j"$(nproc)"          # builds brcmsmac/brcmsmac.ko for the running kernel
make KDIR=/path/to/build   # builds against another kernel
sudo make modules_install
make clean
```

Firmware (`brcm/bcm43xx-0.fw`, `brcm/bcm43xx_hdr-0.fw`) comes from
linux-firmware.

## License

The driver is ISC licensed; see `LICENSES/ISC`. `brcmsmac/led.c` is
GPL-2.0; see `LICENSES/GPL-2.0`.
