#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: ISC
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyelftools>=0.29"]
# ///
"""Add D11 core revision 30 firmware to the brcmsmac firmware image.

Reads the microcode and initvals of D11 core revision 30 (BCM43227) by
symbol name from wlc_hybrid.o_shipped of the broadcom-wl hybrid driver
and appends them, unmodified, to brcm/bcm43xx-0.fw and
brcm/bcm43xx_hdr-0.fw from linux-firmware. The container format is the
one brcmsmac parses: the binary is the concatenated sections, and the
header is an array of little-endian {offset, len, idx} u32 triplets.
Existing sections are kept as they are, so the image still loads on
every other supported core.

Why not b43-fwcutter: brcmsmac is meant to run firmware 832.127, from
broadcom-wl 6.30.223.271, which is what the reference driver runs on
this card. b43-fwcutter, as of b43-tools 36284a5 (version 021), only
accepts driver files whose MD5 is in its built-in list, and it does not
list the 6.30.223.271 x86_64 hybrid object (MD5
6889dbd24abf8006de5cc6eddd138518). Its --brcmsmac mode also writes only
the core revision 16/24 sections, so it cannot produce the revision 30
ones from any driver file.

The output contains Broadcom's proprietary firmware. Use it only on your
own system under the broadcom-wl licence; do not redistribute it.
"""

import argparse
import hashlib
import io
import os
import struct
import sys

from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
from elftools.elf.sections import SymbolTableSection

# Section tags, matching the enum in brcmsmac/ucode_loader.c
D11N16BSINITVALS30 = 16
D11N16INITVALS30 = 17
D11UCODE_OVERSIGHT30_MIMO = 18
D11UCODE_OVERSIGHT30_MIMOSZ = 19

VERSION_SYMBOLS = ("d11ucode_ge24_bommajor", "d11ucode_ge24_bomminor")

SECTIONS = (
    ("d11n16bsinitvals30", D11N16BSINITVALS30),
    ("d11n16initvals30", D11N16INITVALS30),
    ("d11ucode30_mimo", D11UCODE_OVERSIGHT30_MIMO),
    ("d11ucode30_mimosz", D11UCODE_OVERSIGHT30_MIMOSZ),
)

# Firmware versions this tool has been checked against
KNOWN_VERSIONS = ((832, 127),)

# Bounds enforced by brcms_check_firmwares()
MIN_FW_SIZE = 40000
MAX_FW_SIZE = 150000


class FwError(Exception):
    pass


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def find_symbols(elf, wanted):
    symtab = next((s for s in elf.iter_sections()
                   if isinstance(s, SymbolTableSection)), None)
    if symtab is None:
        raise FwError("no symbol table")
    found = {}
    for sym in symtab.iter_symbols():
        if sym.name not in wanted:
            continue
        if sym.name in found:
            raise FwError("duplicate symbol %s" % sym.name)
        if not isinstance(sym["st_shndx"], int):
            raise FwError("%s is not defined in a section" % sym.name)
        found[sym.name] = sym
    missing = [n for n in wanted if n not in found]
    if missing:
        raise FwError("symbols not found: %s" % ", ".join(missing))
    return found


def check_relocations(elf, syms):
    """Refuse symbols that the linker would patch: their bytes in the
    object file would not be the bytes the driver uses."""
    for rel in elf.iter_sections():
        if not isinstance(rel, RelocationSection):
            continue
        target = rel["sh_info"]
        for r in rel.iter_relocations():
            off = r["r_offset"]
            for name, sym in syms.items():
                start = sym["st_value"]
                if (sym["st_shndx"] == target and
                        start <= off < start + sym["st_size"]):
                    raise FwError("%s is relocated at 0x%x" % (name, off))


def check_initvals(name, data):
    """struct d11init: LE16 addr, LE16 size, LE32 value; addr 0xffff ends."""
    if len(data) % 8:
        raise FwError("%s: size %d is not a multiple of 8" %
                      (name, len(data)))
    for i, (addr, size, _value) in enumerate(struct.iter_unpack("<HHI",
                                                                data)):
        if addr == 0xffff:
            return
        if size not in (2, 4):
            raise FwError("%s: entry %d has size %d" % (name, i, size))
    raise FwError("%s: missing 0xffff terminator" % name)


def parse_container(fw, hdr):
    if len(hdr) % 12:
        raise FwError("header size %d is not a multiple of 12" % len(hdr))
    tags = set()
    for offset, length, idx in struct.iter_unpack("<III", hdr):
        if offset + length > len(fw):
            raise FwError("section %d overruns the image" % idx)
        tags.add(idx)
    present = [idx for _, idx in SECTIONS if idx in tags]
    if present:
        raise FwError("image already has section tags %s" %
                      ", ".join(map(str, present)))


def extract(blob):
    elf = ELFFile(io.BytesIO(blob))
    if elf.little_endian is not True or elf.elfclass != 64:
        raise FwError("not a little-endian ELF64 object")
    names = list(VERSION_SYMBOLS) + [n for n, _ in SECTIONS]
    syms = find_symbols(elf, names)
    check_relocations(elf, syms)

    data = {}
    for name, sym in syms.items():
        sec = elf.get_section(sym["st_shndx"])
        start, size = sym["st_value"], sym["st_size"]
        if start + size > sec["sh_size"]:
            raise FwError("%s lies outside its section" % name)
        data[name] = sec.data()[start:start + size]

    for name in VERSION_SYMBOLS + ("d11ucode30_mimosz",):
        if len(data[name]) != 4:
            raise FwError("%s: expected 4 bytes" % name)
    version = tuple(u32(data[name], 0) for name in VERSION_SYMBOLS)
    ucode_len = u32(data["d11ucode30_mimosz"], 0)
    if ucode_len != len(data["d11ucode30_mimo"]) or ucode_len % 4:
        raise FwError("d11ucode30_mimosz %d does not match microcode "
                      "size %d" % (ucode_len, len(data["d11ucode30_mimo"])))
    check_initvals("d11n16initvals30", data["d11n16initvals30"])
    check_initvals("d11n16bsinitvals30", data["d11n16bsinitvals30"])
    return version, data


def merge(fw, hdr, data):
    parse_container(fw, hdr)
    fw = bytearray(fw)
    hdr = bytearray(hdr)
    fw += b"\0" * (-len(fw) % 4)
    for name, idx in SECTIONS:
        offset = len(fw)
        fw += data[name]
        fw += b"\0" * (-len(fw) % 4)
        hdr += struct.pack("<III", offset, len(data[name]), idx)
    if not MIN_FW_SIZE <= len(fw) <= MAX_FW_SIZE:
        raise FwError("image size %d outside brcmsmac bounds" % len(fw))
    return bytes(fw), bytes(hdr)


def read_file(path):
    with open(path, "rb") as f:
        return f.read()


def hdr_path(path):
    """brcmsmac requests NAME-N.fw together with NAME_hdr-N.fw."""
    head, name = os.path.split(path)
    stem, sep, rest = name.partition("-")
    if not sep:
        raise FwError("%s: expected a NAME-N.fw file name" % path)
    return os.path.join(head, stem + "_hdr-" + rest)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--wl", required=True,
                    help="wlc_hybrid.o_shipped from broadcom-wl")
    ap.add_argument("-i", "--input", required=True,
                    help="bcm43xx-0.fw from linux-firmware; the header is "
                    "read from the matching _hdr file")
    ap.add_argument("-o", "--output", required=True,
                    help="patched image, e.g. bcm43xx-0-patched.fw; the "
                    "header is written to the matching _hdr file")
    ap.add_argument("--force", action="store_true",
                    help="accept firmware versions not checked by this tool")
    args = ap.parse_args()

    blob = read_file(args.wl)
    try:
        version, data = extract(blob)
    except (FwError, ELFError, ValueError, struct.error) as e:
        sys.exit("%s: %s" % (args.wl, e or "malformed object"))

    print("%s: sha256 %s, firmware %d.%d" %
          (args.wl, hashlib.sha256(blob).hexdigest(), *version))
    if version not in KNOWN_VERSIONS and not args.force:
        sys.exit("firmware %d.%d has not been checked; use --force" %
                 version)

    try:
        in_hdr = hdr_path(args.input)
        out_hdr = hdr_path(args.output)
        fw, hdr = merge(read_file(args.input), read_file(in_hdr), data)
    except (FwError, OSError, struct.error) as e:
        sys.exit("%s: %s" % (args.input, e))

    for path, content in ((args.output, fw), (out_hdr, hdr)):
        with open(path, "wb") as f:
            f.write(content)
        print("wrote %s (%d bytes)" % (path, len(content)))


if __name__ == "__main__":
    main()
