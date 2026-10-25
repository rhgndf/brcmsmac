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

wl requests the sample too, mostly 1.02 s apart (450 requests in 361 s
of the `wl-percal-ch6-13-01` trace), and in monitor mode it missed
single beacons 28 times in 30 s, as brcmsmac did 27 times. wl may use
the result, though; brcmsmac does not.

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

## A-MPDU frames reserve the medium for an ACK, not a BlockAck

`brcms_c_d11hdrs_mac80211()`, `brcmsmac/main.c:6415-6441`, sets the
Duration field of every unicast frame, and its fallback copy
`FragDurFallback`, with `brcms_c_compute_frame_dur()` (`main.c:5696`):
SIFS plus an ACK at the response rate. An MPDU sent in an A-MPDU is
answered by a BlockAck (32 bytes instead of 14), so its Duration should
be SIFS plus `brcms_c_calc_ba_time()` (`main.c:5670`), which the RTS/CTS
duration of an A-MPDU already uses. Neither `ampdu.c` nor the microcode
corrects it.

On a BCM43227 uploading at HT20 to the RTL8812AU peer (24 Mbit/s
response rate), a monitor on the peer saw Duration 44 us on all 36,497
data frames from brcmsmac and 48 us on all 16,152 from wl. wl's TX
descriptors also carry 48 (0x30) in `FragDurFallback`, against 44 (0x2c)
from brcmsmac.

Other stations' NAV ends 4 us before the BlockAck does. They still sense
the BlockAck on the medium and wait at least DIFS after it, so this
should not cause collisions. Reachable on every device with an A-MPDU
session.

**Fix:** for frames with `IEEE80211_TX_CTL_AMPDU`, set both durations
to `get_sifs(wlc->band) + brcms_c_calc_ba_time(wlc, rspec[k],
BRCMS_SHORT_PREAMBLE)`, as `brcms_c_compute_rtscts_dur()` does for the
BlockAck.
