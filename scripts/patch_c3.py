#!/usr/bin/env python3
"""Patch BH6 SP BIOS body to recognise VIA C3 (CentaurHauls) CPUs."""
import sys, struct

BODY_IN, BODY_OUT = sys.argv[1], sys.argv[2]
b = bytearray(open(BODY_IN,'rb').read())
assert len(b) == 0x20000

# --- offsets discovered by RE ---
TBL_CYRIX_ENTRY = 0x3443     # [2-byte handler ptr][12-byte vendor string]
CAVE            = 0xD600     # 10752 bytes of 0xFF, E000 segment (not checksummed)
HANDLER         = CAVE
NAMESTR         = CAVE + 0x20
NAME            = b"VIA C3\x00"
VENDOR_CENTAUR  = b"CentaulsaurH"   # CPUID leaf0 EBX,ECX,EDX order

# --- sanity checks before touching anything ---
assert bytes(b[TBL_CYRIX_ENTRY:TBL_CYRIX_ENTRY+2]) == b'\x9f\x34', "unexpected Cyrix handler ptr"
assert bytes(b[TBL_CYRIX_ENTRY+2:TBL_CYRIX_ENTRY+14]) == b'CyriteadxIns', "unexpected vendor string"
assert bytes(b[TBL_CYRIX_ENTRY+14:TBL_CYRIX_ENTRY+16]) == b'\xff\xff', "table terminator missing"
assert all(x == 0xFF for x in b[CAVE:CAVE+0x40]), "code cave not free!"

# --- new handler (mirrors BF6's Centaur handler + BH6's variable layout) ---
handler = bytes([
    0x66,0xB9,0x1B,0x00,0x00,0x00,   # mov ecx,0x1b      (IA32_APIC_BASE)
    0x0F,0x32,                        # rdmsr
    0x80,0xE4,0xF7,                   # and ah,0xf7       (clear APIC global enable)
    0x0F,0x30,                        # wrmsr
    0xC7,0x86,0x22,0x02,              # mov word [bp+0x222], ...
        NAMESTR & 0xFF, NAMESTR >> 8, #   ...-> name string
    0xC3,                             # ret
])

# --- apply ---
b[HANDLER:HANDLER+len(handler)] = handler
b[NAMESTR:NAMESTR+len(NAME)]    = NAME
struct.pack_into('<H', b, TBL_CYRIX_ENTRY, HANDLER)
b[TBL_CYRIX_ENTRY+2:TBL_CYRIX_ENTRY+14] = VENDOR_CENTAUR

# --- verify F000 checksum untouched (patch is all in E000) ---
f000 = sum(b[0x10000:0x20000]) & 0xff
print(f"  handler @ {HANDLER:#06x} ({len(handler)} bytes), name '{NAME[:-1].decode()}' @ {NAMESTR:#06x}")
print(f"  table entry @ {TBL_CYRIX_ENTRY:#06x}: CyrixInstead -> CentaurHauls, ptr 0x349f -> {HANDLER:#06x}")
print(f"  F000 checksum = {f000:#04x}  {'OK (must be 0x00)' if f000==0 else '*** BROKEN ***'}")
open(BODY_OUT,'wb').write(bytes(b))
