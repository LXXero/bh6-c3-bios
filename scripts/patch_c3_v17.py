#!/usr/bin/env python3
"""BH6 SP -> VIA C3 (v17 clean production body): (1) vendor detect + POST name, (2) VIA EBLCR multiplier decode.
Multiplier tables from Linux drivers/cpufreq/longhaul.h (values are mult*2, reserved -> comment value/20)."""
import sys, struct
b = bytearray(open(sys.argv[1],'rb').read()); stock = bytes(b)
assert len(b) == 0x20000
TBL, CAVE = 0x3443, 0xD600
HAND, NAME, CENTCHK, MULT, TABS, COMP = CAVE, CAVE+0x20, CAVE+0x40, CAVE+0x60, CAVE+0x100, CAVE+0x180
assert bytes(b[TBL:TBL+2])==b'\x9f\x34' and bytes(b[TBL+2:TBL+14])==b'CyriteadxIns'
assert bytes(b[0x3554:0x3559])==bytes.fromhex('e8c55a7511'), "hook site changed"
assert all(x==0xFF for x in b[CAVE:CAVE+0x1C0])
def put(off,data):
    assert all(x==0xFF for x in b[off:off+len(data)]), f"cave collision {off:#x}"
    b[off:off+len(data)]=data
def rel16(end,to): return (to-end)&0xFFFF

# (1) vendor table entry + POST name  [proven on hardware]
put(HAND, bytes([0x66,0xB9,0x1B,0,0,0, 0x0F,0x32, 0x80,0xE4,0xF7, 0x0F,0x30,
                 0xC7,0x86,0x22,0x02, NAME&0xFF, NAME>>8, 0xC3]))
put(NAME, b"VIA C3\x00")
struct.pack_into('<H', b, TBL, HAND); b[TBL+2:TBL+14] = b'CentaulsaurH'

# CentaurHauls test (mirrors the BIOS's own Cyrix test @0x901C)
put(CENTCHK, bytes([0x66,0x60, 0x66,0x33,0xC0, 0x0F,0xA2, 0x66,0x81,0xFB])+struct.pack('<I',0x746E6543)+bytes([0x66,0x61,0xC3]))

# (2) multiplier tables (mult*2), 16 or 32 entries
def t(v): return bytes(x//5 for x in v)
SAM1=t([50,30,40,100,55,35,45,100,100,70,80,60,100,75,100,65])           # reserved->10.0x
SAM2=t([50,30,40,100,55,35,45,110,90,70,80,60,120,75,130,65])
EZRA=t([50,30,40,100,55,35,45,95,90,70,80,60,120,75,85,65])
EZRT=EZRA+t([90,110,120,100,135,115,125,105,130,150,160,140,120,155,130,145])
NEHE=t([50,160,40,100,55,100,45,95,90,70,80,60,120,75,85,65])+t([90,110,120,100,135,115,125,105,130,150,160,140,120,155,130,145])
T_SAM1=TABS; T_SAM2=TABS+16; T_EZRA=TABS+32; T_EZRT=TABS+48; T_NEHE=TABS+80
put(TABS, SAM1+SAM2+EZRA+EZRT+NEHE)

# multiplier hook body (entered from 0x3554; must preserve BX = measured clock)
def build(L):
    f=bytearray(); A=lambda: MULT+len(f)
    f+=bytes([0xE8])+struct.pack('<H',rel16(A()+3,CENTCHK))     # call centaur_chk
    f+=bytes([0x74,(L['cent']-(len(f)+2))&0xFF])                # jz centaur
    f+=bytes([0xE8])+struct.pack('<H',rel16(A()+3,0x901C))      # call cyrix_chk (original)
    f+=bytes([0x75,0x03])                                       # jnz -> to_msr
    f+=bytes([0xE9])+struct.pack('<H',rel16(A()+3,0x3559))      # jmp Cyrix path
    f+=bytes([0xE9])+struct.pack('<H',rel16(A()+3,0x356A))      # to_msr: jmp Intel MSR path
    L2={'cent':len(f)}
    f+=bytes([0x66,0xB9,0x2A,0,0,0])                            # mov ecx,0x2a
    f+=bytes([0x0F,0x32])                                       # rdmsr
    f+=bytes([0x66,0xC1,0xE8,0x16])                             # shr eax,22
    f+=bytes([0x8B,0xF0])                                       # mov si,ax
    f+=bytes([0x83,0xE6,0x0F])                                  # and si,0x0f
    f+=bytes([0xA8,0x20])                                       # test al,0x20 (old bit 27)
    f+=bytes([0x74,0x03])                                       # jz +3
    f+=bytes([0x83,0xC6,0x10])                                  # add si,16
    f+=bytes([0xE8])+struct.pack('<H',rel16(A()+3,0x900F))      # call cpuid(1) -> ax (preserves ebx)
    f+=bytes([0x8A,0xD0])                                       # mov dl,al   (model|stepping)
    f+=bytes([0xC0,0xE8,0x04])                                  # shr al,4
    f+=bytes([0x24,0x0F])                                       # and al,0x0f -> model
    f+=bytes([0x3C,0x06,0x75,0x08])                             # cmp al,6 ; jne m7
    f+=bytes([0x83,0xE6,0x0F])                                  #   and si,0x0f
    f+=bytes([0x81,0xC6])+struct.pack('<H',T_SAM1)              #   add si,T_SAM1
    f+=bytes([0xC3])                                            #   ret
    f+=bytes([0x3C,0x07,0x75,0x13])                             # m7: cmp al,7 ; jne m8
    f+=bytes([0x83,0xE6,0x0F])                                  #   and si,0x0f
    f+=bytes([0x80,0xE2,0x0F])                                  #   and dl,0x0f (stepping)
    f+=bytes([0x75,0x05])                                       #   jnz ezra
    f+=bytes([0x81,0xC6])+struct.pack('<H',T_SAM2)              #   add si,T_SAM2 (stepping 0)
    f+=bytes([0xC3])                                            #   ret
    f+=bytes([0x81,0xC6])+struct.pack('<H',T_EZRA)              #   ezra: add si,T_EZRA
    f+=bytes([0xC3])                                            #   ret
    f+=bytes([0x3C,0x08,0x75,0x05])                             # m8: cmp al,8 ; jne m9
    f+=bytes([0x81,0xC6])+struct.pack('<H',T_EZRT)              #   add si,T_EZRT
    f+=bytes([0xC3])                                            #   ret
    f+=bytes([0x81,0xC6])+struct.pack('<H',T_NEHE)              # m9: add si,T_NEHE (model 9+)
    f+=bytes([0xC3])                                            #   ret
    return f,L2
L={'cent':0}
for _ in range(3): f,L=build(L)
assert len(f) <= 0xA0, len(f)
put(MULT, f)
b[0x3554:0x3559] = bytes([0xE9])+struct.pack('<H',rel16(0x3557,MULT))+b'\x90\x90'

# (3) BF6 behaviour: no preset-vs-computed CPU speed validation.
#     0x17A is the check called from the validator entry (0x54: call 0x17A / jz pass).
#     Replace its first instruction with `xor al,al ; ret` -> ZF=1 -> always pass.
assert bytes(b[0x17A:0x17E]) == bytes.fromhex('f6463902'), "validator check moved"
b[0x17A:0x17E] = bytes([0x30,0xC0,0xC3,0x90])

# v17: NAGCLR (0x44), the clock-apply gate NOP (0xC65F) and the CMOS writeback-range
# extension (0x9F26) were reset-era workarounds. The real reset is fixed in the raw ROM
# by apply_early_cpu_fix.py, so these are RESTORED TO STOCK here. Only C3 detection/name/
# boot-hang, the VIA multiplier decode, and the 0x17A preset-vs-computed speed bypass remain.

delta=(sum(stock[:0x10000])-sum(b[:0x10000]))&0xff
b[COMP]=(b[COMP]+delta)&0xff
assert len(b)==0x20000 and (sum(b[:0x10000])&0xff)==(sum(stock[:0x10000])&0xff) and (sum(b[0x10000:])&0xff)==0
assert bytes(b[0x34bf:0x34c2])==b'\xba\x01\x01', "type routine must be STOCK in v8"
print(f"  name@{NAME:#06x} centchk@{CENTCHK:#06x} mult@{MULT:#06x}({len(f)}b) tables@{TABS:#06x} comp@{COMP:#06x}={b[COMP]:#04x}")
print(f"  hook 0x3554 -> {MULT:#06x} | E000={sum(b[:0x10000])&0xff:#04x} F000={sum(b[0x10000:])&0xff:#04x} | 0x34BF stock: True")
open(sys.argv[2],'wb').write(bytes(b))
