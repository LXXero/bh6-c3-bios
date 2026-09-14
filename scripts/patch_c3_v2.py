#!/usr/bin/env python3
"""BH6 SP -> VIA C3 support: (1) vendor detection, (2) correct multiplier table."""
import sys, struct
BODY_IN, BODY_OUT = sys.argv[1], sys.argv[2]
b = bytearray(open(BODY_IN,'rb').read()); stock = bytes(b)
assert len(b) == 0x20000

# ---------- PART 1: vendor table + name handler (already proven on hardware) ----------
TBL   = 0x3443
CAVE  = 0xD600
HAND  = CAVE
NAME  = CAVE + 0x20
GATE  = CAVE + 0x40          # new multiplier-table gate
COMP  = CAVE + 0x80          # sum compensator (well clear of code)
assert bytes(b[TBL:TBL+2]) == b'\x9f\x34'
assert bytes(b[TBL+2:TBL+14]) == b'CyriteadxIns'
assert all(x == 0xFF for x in b[CAVE:CAVE+0x100])

b[HAND:HAND+20] = bytes([
    0x66,0xB9,0x1B,0x00,0x00,0x00,  # mov ecx,0x1b
    0x0F,0x32,                       # rdmsr
    0x80,0xE4,0xF7,                  # and ah,0xf7   (disable local APIC)
    0x0F,0x30,                       # wrmsr
    0xC7,0x86,0x22,0x02, NAME&0xFF, NAME>>8,   # mov word [bp+0x222],name
    0xC3])
b[NAME:NAME+7] = b"VIA C3\x00"
struct.pack_into('<H', b, TBL, HAND)
b[TBL+2:TBL+14] = b'CentaulsaurH'

# ---------- PART 2: force C3 (CPUID 0x69x) onto the NEW multiplier table ----------
# Original sub @0x358B picks OLD table (max 8.0x) for CPUID 0x69x, which cannot
# represent the C3's 10.0x -> BIOS speed never matches -> "CPU has been changed".
# NEW table @0x34E8 contains 10.0x. Redirect the sub through a cave gate.
CPUID1 = 0x900F                       # helper: cpuid leaf 1 -> ax
def rel16(frm_end, to): return (to - frm_end) & 0xFFFF
gate = bytearray()
gate += bytes([0xE8]) + struct.pack('<H', rel16(GATE+3, CPUID1))      # call cpuid1
gate += bytes([0x80,0xE4,0x0F])                                       # and ah,0x0f
gate += bytes([0x3D,0x90,0x06])                                       # cmp ax,0x0690
gate += bytes([0x72,0x07])                                            # jc  -> orig
gate += bytes([0x3D,0x9F,0x06])                                       # cmp ax,0x069f
gate += bytes([0x77,0x02])                                            # ja  -> orig
gate += bytes([0xF8,0xC3])                                            # clc ; ret  (NEW table)
ORIG = GATE + len(gate)                                               # 'orig' label
gate += bytes([0x66,0xB9,0x2A,0x00,0x00,0x00])                        # mov ecx,0x2a
gate += bytes([0xE9]) + struct.pack('<H', rel16(ORIG+6+3, 0x3591))    # jmp back into original
b[GATE:GATE+len(gate)] = gate
# hook: replace 'mov ecx,0x2a' at 0x358B with a jump to the gate
b[0x358B:0x358E] = bytes([0xE9]) + struct.pack('<H', rel16(0x358E, GATE))

# ---------- keep body byte-sum identical to stock ----------
delta = (sum(stock[:0x10000]) - sum(b[:0x10000])) & 0xff
b[COMP] = (b[COMP] + delta) & 0xff
assert (sum(b[:0x10000])&0xff) == (sum(stock[:0x10000])&0xff)
assert (sum(b[0x10000:])&0xff) == 0

print(f"  vendor entry @{TBL:#06x} -> handler {HAND:#06x}, name {NAME:#06x}")
print(f"  mult-table gate @{GATE:#06x} ({len(gate)} bytes), hook at 0x358B")
print(f"  sum compensator @{COMP:#06x}={b[COMP]:#04x} | E000={sum(b[:0x10000])&0xff:#04x} F000={sum(b[0x10000:])&0xff:#04x}")
open(BODY_OUT,'wb').write(bytes(b))
