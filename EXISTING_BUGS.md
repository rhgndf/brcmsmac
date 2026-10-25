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
