# BCM43227: brcmsmac or b43?

Question: with the reverse-engineered BCM43227 work in `../b43` available,
is it easier to bring BCM43227 (D11 core 30, N-PHY 16, radio 2057 rev 9)
up in brcmsmac?

Answer: **yes, for upstream purposes**. brcmsmac already implements
the features b43 had to add for this chip: 802.11n TX/RX, TX A-MPDU,
PAPD for internal-PA boards, RX IQ and periodic calibration, per-rate
TX power. The port only adds revision-specific PHY data and the core 30
firmware plumbing. b43 is useful for its traces and as a cross-check,
not as code.

## What each driver had to add

| Area | b43 (`65d9950..HEAD`) | brcmsmac (this series) |
| --- | --- | --- |
| HT20 TX/RX rates, MCS PLCP | added (`xmit.c`, `main.c`) | present upstream |
| TX A-MPDU, Block Ack status | added (`dma.c`, `xmit.c`) | present (`ampdu.c`) |
| RX A-MPDU | added | present (mac80211 reorders) |
| Per-rate TX power | added (ported from brcmsmac) | present |
| PAPD, RX IQ, periodic cal | added for this chip | present for N-PHY rev 3+ |
| Core 30 firmware load | 598-format header gate | new file names + section tags |
| Core 30 FIFO partition | added | one table row |
| Radio 2057 rev 9 | partly upstream | init/RCAL/RCCAL/channel overrides |
| N-PHY 16 workarounds | added, many traced | traced subset only |
| Energy-detect CRS | added, firmware 832+ only | one register + SHM word |
| Total driver diff | 3118+/136- in 11 files | 438+/24- in 12 files |

b43's own survey (`../b43/SURVEY.md`) lists HT, aggregation, RX IQ and
periodic calibration as absent in upstream b43 for this chip. Closing
those took 35 commits and 51 documents (18 of them capture write-ups).
brcmsmac already has them because it derives from Broadcom's own driver,
where these MAC/PHY features are shared across N-PHY revisions.

## Why b43 code cannot be moved across

- Licence: b43 is GPL-2.0-or-later; brcmsmac is ISC. Copying b43 code or
  tables would relicense them; every value in this series instead comes
  from the wl MMIO trace on this card or from existing brcmsmac code. b43
  was used only to cross-check (e.g. the 2057 rev 9 RCCAL offset rule).
- Structure: b43's PHY layer is a clean-room rewrite with its own table
  layout and calibration flow; brcmsmac follows the vendor's
  `wlc_phy_*_nphy` layout. Values carry across, code does not.
- Firmware ABI: b43 runs ucode 784.2/832.127 with its "598" TX header
  (`../b43/xmit.h` `format_598`). That header is brcmsmac's `struct
  d11txh` (`brcmsmac/d11.h`) field for field; b43's 2-byte pad sits where
  brcmsmac has `AmpduSeqCtl`. A trace of wl on this card with 832.127
  shows 71 TX descriptors in exactly brcmsmac's layout and encodings,
  TX status words (including the A-MPDU secondary word) as `ampdu.c`
  parses them, RX offset 38, and the same SHM offsets and values brcmsmac
  writes. b43 had to rebuild this interface piece by piece; brcmsmac
  already speaks it.

## What the brcmsmac port costs

1. Firmware: the core 30 ucode/initvals are not in linux-firmware. They
   are copied unmodified from `wlc_hybrid.o_shipped` by symbol name and
   appended to `brcm/bcm43xx-0.fw` (`tools/brcmsmac-fwcutter.py`). This is
   the blocker for upstream use: the sections need to be redistributable
   before the binding can land.
2. PHY: only N-PHY 16 differences from rev 7/8 that the trace shows,
   each guarded so revisions 0-8 are unchanged.
3. MAC: energy-detect carrier sense on core 30, which wl enables and
   brcmsmac never did; otherwise no change beyond the core revision and
   device ID gates, as core 30 joins the rev 17/23/24 selection paths.

The driver part is 15 commits, 438+/24- in `brcmsmac/` and `include/`,
plus the out-of-tree firmware tool and documentation.

## Risks still open

- Unverified at runtime (by request, the module was not loaded).
  Every PHY value is checked against the wl trace by script, but nothing
  proves the radio tunes or the MAC passes traffic.
- Post-init PHY writes with no identified owner (listed in
  `bcm43227.md`) are not reproduced; they may matter for RX sensitivity.
- 5 GHz and 40 MHz were not traced and are not claimed.
- b43 on this card hits a MAC wedge under sustained bidirectional
  traffic with both firmware versions (`../b43/docs/firmware.md`).
  Whether brcmsmac's ucode handling avoids it is unknown.
- b43 also matches BCMA core revision 30, and its `allhwsupport` guard
  covers only cores 0x17/0x18. With both drivers built, either can bind
  the card; upstream would need b43 to defer core 30 to brcmsmac.
