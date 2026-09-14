#!/usr/bin/env python3
"""v16: vendor-aware fix for the early model-8 CPU-type reset in the directly-mapped
decomp block (raw ROM ~0x37BB7, runtime F000:7BB7). On the model-8 brand-vs-class
mismatch, instead of jumping straight to the CPU-defaults fallback (which writes
CMOS 37=46/41=03/3A=00), jump to a cave that checks CPUID(0) vendor: CentaurHauls
-> success continuation (F000:7BED); anything else -> the original fallback
(F000:7C7D). Intel CPU-change detection is therefore unchanged. Recomputes the
decomp-block checksum: byte[0x37FFE] = sum8(image[:0x37FFE]).
  usage: apply_early_cpu_fix.py <in 256K.BIN> <out.BIN>
"""
import sys, struct
r=bytearray(open(sys.argv[1],'rb').read())
assert len(r)==0x40000, f"expected 256K ROM, got {len(r):#x}"
# --- context asserts (raw offsets; F000 base = raw 0x30000) ---
# 0x37BB5: and al,3 (2434) ; 0x37BB7 cmp bl,al (3ad8) ; 0x37BB9 jz +0x32 (7432) ; 0x37BBB jmp 0x7c7d (e9bf00)
assert bytes(r[0x37BB5:0x37BBE])==bytes.fromhex('24033ad87432e9bf00'), \
    f"early-check context moved: {bytes(r[0x37BB5:0x37BBE]).hex()}"
CAVE_RUN=range(0x37F1D,0x37FFE)
assert all(r[i]==0xFF for i in range(0x37F1D,0x37F40)), "cave slot not free"
def raw(f000_off): return 0x30000+f000_off         # F000:off -> raw
def rel16(from_raw_after, to_raw): return (to_raw-from_raw_after)&0xFFFF
BED=raw(0x7BED); C7D=raw(0x7C7D); CAVE=raw(0x7F1D)
# --- hook: 0x37BBB e9 bf 00 (jmp 0x7C7D) -> jmp CAVE ---
r[0x37BBB]=0xE9; struct.pack_into('<H', r, 0x37BBC, rel16(0x37BBE, CAVE))
# --- cave ---
c=bytearray()
c+=bytes.fromhex('6633c0')                          # xor eax,eax
c+=bytes.fromhex('0fa2')                             # cpuid
c+=bytes.fromhex('6681fb')+struct.pack('<I',0x746E6543)  # cmp ebx,'Cent'
# je 0x7BED
je_after=CAVE+len(c)+4
c+=b'\x0f\x84'+struct.pack('<H', rel16(je_after, BED))
# jmp 0x7C7D
jmp_after=CAVE+len(c)+3
c+=b'\xe9'+struct.pack('<H', rel16(jmp_after, C7D))
assert CAVE+len(c) < 0x37FFE
r[CAVE:CAVE+len(c)]=c
# --- fix decomp-block checksum: byte[0x37FFE] = sum8(image[:0x37FFE]) ---
r[0x37FFE]=sum(r[0:0x37FFE])&0xff
# --- fix bootblock per-4KB page checksum for the F000:7000 page:
#     sum8(page[0:0xFFF]) == page[0xFFF]  (page byte at 0x37FFF; includes 0x37FFE) ---
r[0x37FFF]=sum(r[0x37000:0x37FFF])&0xff
# verify both invariants the real bootblock enforces on the two decomp pages
assert r[0x37FFE]==sum(r[0:0x37FFE])&0xff, "awdbedit decomp cksum"
for pg in (0x36000,0x37000):
    assert (sum(r[pg:pg+0xFFF])&0xff)==r[pg+0xFFF], f"page cksum @{pg:#07x}"
open(sys.argv[2],'wb').write(bytes(r))
print(f"  hook  0x37BBB: jmp -> cave F000:7F1D")
print(f"  cave  {CAVE:#07x}: {len(c)} bytes; ck byte[0x37FFE]={r[0x37FFE]:#04x}")
