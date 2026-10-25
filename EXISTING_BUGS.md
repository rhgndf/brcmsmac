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

## A-MPDU frames at a legacy rate are aggregated at that rate

When the bitrate mask leaves no MCS for the band (for example
`iw dev wlan0 set bitrates legacy-2.4 1 ht-mcs-2.4`), rate control gives
QoS data for an HT peer a CCK or OFDM rate, but mac80211 still marks it
`IEEE80211_TX_CTL_AMPDU` while a Block Ack session runs. brcmsmac does
not look at the rate: `dma_txfast()` (`brcmsmac/dma.c:1395`) passes every
such frame to `brcms_c_ampdu_add_frame()`, which aggregates it at the
legacy rate. That function also reads the MCS from the legacy PLCP and
uses it to index `max_txlen[]`, `mcs2ampdu_table[]` and `mcs_table[]`
(`brcmsmac/ampdu.c:555-573`, and `735` in `brcms_c_ampdu_finalize()`).
These tables have 33 entries, and an OFDM or 11 Mbit/s CCK PLCP byte
reads past them.

On a BCM43227 (firmware 832.127) associated to an HT20 or HT40 access
point, with the mask at 1 or 11 Mbit/s, no ping was answered (0 of 20)
while the Block Ack session ran. Each aggregate ended in a PHY error
(`TxStatus 0x161`, `PHYTxStatus 0x01`) followed by a BAR. Right after
the session was stopped through mac80211's `agg_status`, frames went out
alone at the CCK rate and were acknowledged until minstrel_ht started a
new session. The port commit (`800781c`) behaves the same.

Reachable on every device, but only with a bitrate mask without MCS
rates. Otherwise minstrel_ht picks only MCS rates for HT peers, because
brcmsmac does not set `SUPPORTS_HT_CCK_RATES`.

**Fix:** send frames whose primary rate is not an MCS outside an A-MPDU,
as ath9k does (`ath_lookup_rate()`, `ath_lookup_legacy()`).

## A station never switches to the short slot time

mac80211 reports `BSS_CHANGED_ERP_SLOT` together with
`BSS_CHANGED_ASSOC`. `brcms_ops_bss_info_changed()` handles the
association first (`brcmsmac/mac80211_if.c:592-599`), so when it passes
the slot setting on (line 611), `brcms_c_set_shortslot_override()`
(`brcmsmac/main.c:5477`) finds the station associated and leaves the
change to "watchdog or beacon processing" (line 5489). Nothing there
calls `brcms_c_switch_shortslot()` (line 3768). Its only caller is the
unassociated branch at line 5492, which turns the short slot off. The
station keeps the 20 us slot of 802.11b on every BSS.

On a BCM43227 associated to an RTL8812AU access point that reports
`short-slot-time`, IHR `ifs_slot` (0x684) held 0x0212 and SHM
`M_DOT11_SLOT` 20, where wl writes 0x0207 at association. With the
short slot written by hand, TCP ran at 92.6-114.5 Mbit/s up and
104.1-121.7 Mbit/s down, against 92.1-102 and 94.7-118.6 Mbit/s with the
long slot over the same three rounds. That is within the run-to-run
variation of this lab, which has no other stations.

Reachable on every device in station mode on 2.4 GHz.

**Fix:** apply the slot setting while associated, for example by
calling `brcms_c_switch_shortslot()` from
`brcms_c_set_shortslot_override()` when the core is up.
