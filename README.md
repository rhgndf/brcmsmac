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

D11 core revision 30 (BCM43227) needs four more sections in that image,
which linux-firmware does not have. `tools/brcmsmac-fwcutter.py` copies
them, unmodified, from `wlc_hybrid.o_shipped` of Broadcom's hybrid `wl`
driver (checked against 6.30.223.271, firmware 832.127) and appends them
to the linux-firmware image, leaving the existing sections as they are.
The result contains Broadcom's proprietary firmware under the `wl`
licence; do not redistribute it.

```sh
mkdir -p .work/fw
zstd -d /lib/firmware/brcm/bcm43xx-0.fw.zst /lib/firmware/brcm/bcm43xx_hdr-0.fw.zst \
	--output-dir-flat .work/fw
tools/brcmsmac-fwcutter.py --wl /usr/lib/broadcom-wl-dkms/wlc_hybrid.o_shipped \
	-i .work/fw/bcm43xx-0.fw -o .work/fw/bcm43xx-0-patched.fw
```

The tool runs through `uv`, which fetches its one dependency,
pyelftools. Without `uv`, run it with a Python that has pyelftools
installed. It writes `bcm43xx-0-patched.fw` and `bcm43xx_hdr-0-patched.fw`.
Install them as `brcm/bcm43xx-0.fw` and `brcm/bcm43xx_hdr-0.fw` in place
of the linux-firmware files. b43-fwcutter cannot be used: it does not
recognise this `wl` release, and its brcmsmac mode has no core revision
30 sections.

The BCM43227 port, its evidence and open questions are described in
[docs/bcm43227.md](docs/bcm43227.md); the comparison with b43 in
[docs/bcm43227-feasibility.md](docs/bcm43227-feasibility.md).
Pre-existing defects found along the way, and not fixed here, are in
[EXISTING_BUGS.md](EXISTING_BUGS.md).

## License

The driver is ISC licensed; see `LICENSES/ISC`. `brcmsmac/led.c` is
GPL-2.0; see `LICENSES/GPL-2.0`.
