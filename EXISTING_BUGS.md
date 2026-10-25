# Existing brcmsmac bugs

Pre-existing defects found while adding BCM43227 support. They are not
fixed by this series, which only adds what the new device needs. Line
numbers refer to the standalone import, `050991b`.

## TX FIFO size table bounds check is off by one and only warns

`brcms_b_attach()`, `brcmsmac/main.c:4529-4535`:

```c
WARN_ON(wlc_hw->corerev < XMTFIFOTBL_STARTREV ||
	(wlc_hw->corerev - XMTFIFOTBL_STARTREV) >
		ARRAY_SIZE(xmtfifo_sz));
wlc_hw->xmtfifo_sz =
    xmtfifo_sz[(wlc_hw->corerev - XMTFIFOTBL_STARTREV)];
WARN_ON(!wlc_hw->xmtfifo_sz[0]);
```

- The upper bound uses `>` instead of `>=`, so a core revision with
  `corerev - XMTFIFOTBL_STARTREV == ARRAY_SIZE(xmtfifo_sz)` is not
  flagged.
- Both checks only warn. Attach continues, indexes past the end of
  `xmtfifo_sz[]` for an out-of-range revision, and programs a zero-sized
  partition for an all-zero row.

Not reachable with the shipped configuration: the BCMA match table,
`brcms_coreid_table[]`, only binds core revisions 17, 23 and 24 (and 30
after this series), and each has a non-zero row. It only matters when a
revision is bound without its row.

**Fix:** use `>=`, and fail the attach (`err = 20; goto fail;`) instead
of warning, for both the range and the zero-row check.

## The per-second background noise sample costs a beacon and is never used

`wlc_phy_watchdog()`, `brcmsmac/phy/phy_cmn.c:2252-2256`, requests a
background noise sample every second (`MCMD_BG_NOISE` in `maccommand`).
On the `MI_BG_NOISE` interrupt, `wlc_phy_noise_sample_intr()`
(`brcmsmac/main.c:7725-7726`, `phy_cmn.c:1965`) stores the result in
`phy_noise_window[]` or `nphy_noise_win[]` through `wlc_phy_noise_cb()`
(`phy_cmn.c:1903`). Nothing reads either array, and brcmsmac does not
report noise to mac80211 (no `get_survey`).

The sample is not free. On a BCM43227 (firmware 832.127) with power
save off, the station received 87-89 of the AP's ~98 beacons in 10 s
with the sample, and 97-98 without it (4 alternating rounds, beacon
interval 100 TU): each request costs about one beacon. In power save
the microcode takes the sample when it next wakes up, before the TBTT
of a beacon it listens for, and misses that beacon. The power save
commit stops requesting the sample while the microcode sleeps, because
power save depends on those beacons; the cost while awake remains.

Reachable on every N-PHY and LCN-PHY device whenever the interface is
up.

**Fix:** stop requesting the sample, or report its result to mac80211
through `get_survey` so that it is used.

## AP mode sends group frames for sleeping clients at once, not after DTIM

In AP mode, when a client is in power save, mac80211 marks broadcast
and multicast frames `IEEE80211_TX_CTL_SEND_AFTER_DTIM` and leaves
holding them until after the next DTIM beacon to the device (brcmsmac
does not set `HOST_BROADCAST_PS_BUFFERING`). brcmsmac ignores the flag:
`brcms_c_sendpkt_mac80211()` and `brcms_c_tx()` (`brcmsmac/main.c:6821`,
`6768`) always pick the FIFO of the frame's access category, so the
frame goes out immediately while the client sleeps. The microcode's
broadcast/multicast FIFO (`TX_BCMC_FIFO`), which it releases after the
DTIM beacon, is never used: `bcmc_fid_generate()` (`main.c:5628`) and
the `M_BCMC_FID` update (`main.c:6792`) are reachable only through a
queue number that no caller produces (`main.c:6179` calls it an
assertion).

On a BCM43227 AP (firmware 832.127) with an RTL8812AU client in power
save, 1 of 6 broadcast pings was answered; unicast pings to the same
client all were (28-210 ms, delivered after the TIM).

Reachable on every device in AP mode with a power saving client.

**Fix:** queue frames with `IEEE80211_TX_CTL_SEND_AFTER_DTIM` on
`TX_BCMC_FIFO` with a frame ID from `bcmc_fid_generate()`, and keep the
ATIM/BCMC FIFO sized for it; or set `HOST_BROADCAST_PS_BUFFERING` and
release frames with `ieee80211_get_buffered_bc()` after each DTIM
beacon.

## Loading brcmsmac before the bcma bus is registered oopses in the LED code

`brcms_led_register()` (`brcmsmac/led.c:82`, called from
`brcms_attach()`, `mac80211_if.c:1256`) requests the radio LED line from
the ChipCommon GPIO chip, `bus->drv_cc.gpio`, without checking that the
chip has been registered. bcma registers it last:
`bcma_register_devices()` (`drivers/bcma/main.c`) adds the 802.11 core
with `device_add()`, which probes a driver that is already loaded, and
only then calls `bcma_gpio_init()`. If brcmsmac is loaded when the bus
is registered, `gpiochip_request_own_desc()` dereferences the chip's
NULL `gpiodev`:

```
BUG: kernel NULL pointer dereference, address: 00000000000003cc
RIP: 0010:gpiochip_request_own_desc+0x2b/0x180
 brcms_led_register+0xc4/0x180 [brcmsmac]
 brcms_bcma_probe+0x59b/0x5d6 [brcmsmac]
 bcma_device_probe+0x2f/0x60 [bcma]
 ...
 bcma_bus_register+0x4dd/0x570 [bcma]
 bcma_host_pci_probe+0x160/0x1d0 [bcma]
```

The probing task dies holding the CPU hotplug lock, so CPUs taken
offline afterwards (by mmiotrace, for example) cannot come back until a
reboot. On a BCM43227: with the PCI device held by another driver, load
bcma and brcmsmac, release the device, and bind it to
`bcma-pci-bridge`. The usual order, bcma binding the device when it is
loaded and brcmsmac loaded afterwards, does not hit it.

Reachable on every device whose SPROM assigns a radio LED, whenever
brcmsmac is loaded before the bus is registered.

**Fix:** register the GPIO chip before the cores in bcma, or skip the
LED in brcmsmac when the chip has no `gpiodev` yet.

## A failed PHY init check leaves init_in_progress set

`wlc_phy_init()` (`brcmsmac/phy/phy_cmn.c:706-751`) sets
`pi->init_in_progress` and returns early, without clearing it, when the
MAC is running (`WARN` at line 714), when the core has no fast clock
(line 721) or when the PHY has no init function. Every later
`wlc_phy_init()` then returns at the `init_in_progress` check at line
706, so the PHY is never initialised again until the driver is
reloaded, and no further warning is printed.

Not seen on the BCM43227. It is reachable whenever one of the two
warnings fires.

**Fix:** clear `init_in_progress` on the early returns.
