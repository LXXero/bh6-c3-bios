#!/usr/bin/env python3
"""BH6 SP -> VIA C3: (1) vendor detect + POST name, (2) CPU-TYPE field 0x0407 (Centaur), as BF6."""
import sys, struct
b = bytearray(open(sys.argv[1],'rb').read()); stock = bytes(b)
assert len(b) == 0x20000
TBL, CAVE = 0x3443, 0xD600
HAND, NAME, CENTCHK, TYPEFN, COMP = CAVE, CAVE+0x20, CAVE+0x40, CAVE+0x60, CAVE+0xA0
assert bytes(b[TBL:TBL+2])==b'\x9f\x34' and bytes(b[TBL+2:TBL+14])==b'CyriteadxIns'
assert bytes(b[0x34bf:0x34c2])==b'\xba\x01\x01'
assert all(x==0xFF for x in b[CAVE:CAVE+0x100])
def put(off, data):
    assert all(x==0xFF for x in b[off:off+len(data)]), f"cave collision at {off:#06x}"
    b[off:off+len(data)] = data
def rel16(end,to): return (to-end)&0xFFFF

# (1) vendor table + POST name handler  [proven working on hardware]
put(HAND, bytes([0x66,0xB9,0x1B,0,0,0, 0x0F,0x32, 0x80,0xE4,0xF7, 0x0F,0x30,
                 0xC7,0x86,0x22,0x02, NAME&0xFF, NAME>>8, 0xC3]))
put(NAME, b"VIA C3\x00")
struct.pack_into('<H', b, TBL, HAND); b[TBL+2:TBL+14] = b'CentaulsaurH'

# (2a) CentaurHauls test, modelled byte-for-byte on the BIOS's Cyrix test @0x901C
put(CENTCHK, bytes([0x66,0x60, 0x66,0x33,0xC0, 0x0F,0xA2,
                    0x66,0x81,0xFB]) + struct.pack('<I',0x746E6543) + bytes([0x66,0x61, 0xC3]))

# (2b) CPU-type routine: original logic + Centaur -> 0x0407.  Two-pass label resolution.
def build(L):
    f=bytearray()
    f += bytes([0xBA,0x01,0x01])                                  # mov dx,0x101
    f += bytes([0x89,0x96,0xDB,0x01])                             # mov [bp+0x1db],dx
    f += bytes([0xE8])+struct.pack('<H',rel16(TYPEFN+len(f)+3,CENTCHK))   # call centaur?
    f += bytes([0x75,(L['nc']-(len(f)+2))&0xFF])                  # jnz not_centaur
    f += bytes([0xBA,0x03,0x04])                                  # mov dx,0x403  <<< Centaur -> take the CYRIX path
    f += bytes([0x89,0x96,0xDB,0x01])                             # mov [bp+0x1db],dx
    f += bytes([0xEB,(L['done']-(len(f)+2))&0xFF])                # jmp done
    L2={'nc':len(f)}
    f += bytes([0xE8])+struct.pack('<H',rel16(TYPEFN+len(f)+3,0x901C))    # call cyrix?
    f += bytes([0x75,(L['done']-(len(f)+2))&0xFF])                # jnz done
    f += bytes([0xBA,0x03,0x04])                                  # mov dx,0x403
    f += bytes([0x89,0x96,0xDB,0x01])                             # mov [bp+0x1db],dx
    L2['done']=len(f)
    f += bytes([0xC6,0x86,0xE0,0x01,0x04])                        # mov byte [bp+0x1e0],4
    f += bytes([0xC3])                                            # ret
    return f,L2
L={'nc':0,'done':0}
for _ in range(3): f,L = build(L)
put(TYPEFN, f)
b[0x34BF:0x34C2] = bytes([0xE9]) + struct.pack('<H', rel16(0x34C2, TYPEFN))

# (3) KILL SWITCH for the "CPU is unworkable or has been changed" reset:
# POST detection (patched, says VIA C3) and SoftMenu's own detection (awardext.rom,
# still thinks Celeron) write DIFFERENT parameter blocks, so the stored-vs-detected
# checksum @0x9F63 can never match -> settings wiped every boot. NOP the flag-set.
assert bytes(b[0x9FD9:0x9FDD]) == bytes.fromhex('804e0e60'), "or [bp+0xe],0x60 not found"
b[0x9FD9:0x9FDD] = b'\x90\x90\x90\x90'

delta=(sum(stock[:0x10000])-sum(b[:0x10000]))&0xff
b[COMP]=(b[COMP]+delta)&0xff
assert len(b)==0x20000
assert (sum(b[:0x10000])&0xff)==(sum(stock[:0x10000])&0xff) and (sum(b[0x10000:])&0xff)==0
print(f"  name->{NAME:#06x} centaur_chk->{CENTCHK:#06x} typefn->{TYPEFN:#06x} ({len(f)}b) hook 0x34BF")
print(f"  comp@{COMP:#06x}={b[COMP]:#04x}  E000={sum(b[:0x10000])&0xff:#04x} F000={sum(b[0x10000:])&0xff:#04x}  len={len(b)}")
open(sys.argv[2],'wb').write(bytes(b))
