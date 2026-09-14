#!/usr/bin/env python3
"""Validate an Award 4.51PG ROM against every known invariant."""
import sys, struct, subprocess, tempfile, shutil, os

def crc16(d):
    c=0
    for b in d:
        c^=b
        for _ in range(8): c=(c>>1)^0xA001 if c&1 else c>>1
    return c

def check(path, verbose=True):
    r=open(path,'rb').read(); ok=True
    def p(msg,good):
        nonlocal ok
        if not good: ok=False
        if verbose: print(f"    [{'PASS' if good else 'FAIL'}] {msg}")
    p(f"size 262144 (got {len(r)})", len(r)==262144)
    MOD=0x20000
    hs=r[MOD]+2; cs,os_=struct.unpack_from('<II',r,MOD+7)
    # 1. LZH header checksum
    hsum=sum(r[MOD+2:MOD+hs])&0xff
    p(f"LZH header checksum {r[MOD+1]:#04x} == {hsum:#04x}", r[MOD+1]==hsum)
    # 2. decompress
    tmp=tempfile.mkdtemp(); open(f"{tmp}/m.lzh","wb").write(r[MOD:])
    subprocess.run(['7z','x','-y',f"{tmp}/m.lzh",f"-o{tmp}/o"],capture_output=True)
    bp=f"{tmp}/o/original.tmp"; body=open(bp,'rb').read() if os.path.exists(bp) else b''
    shutil.rmtree(tmp,ignore_errors=True)
    p(f"module decompresses to 131072 (got {len(body)})", len(body)==131072)
    if len(body)==131072:
        # 3. file CRC16 in header
        nl=r[MOD+21]; hcrc=struct.unpack_from('<H',r,MOD+22+nl)[0]
        p(f"body CRC16 {hcrc:#06x} == {crc16(body):#06x}", hcrc==crc16(body))
        # 4. F000 segment checksum
        f0=sum(body[0x10000:0x20000])&0xff
        p(f"F000 seg sum8 == 0x00 (got {f0:#04x})", f0==0)
    # 5. module trailer  (awdbedit: writes 0x00 then sum8(lzh header+data))
    end=MOD+hs+cs
    tsum=sum(r[MOD:end])&0xff
    p(f"trailer[0]==0x00 (got {r[end]:#04x})", r[end]==0x00)
    p(f"trailer[1]=={tsum:#04x} (got {r[end+1]:#04x})", r[end+1]==tsum)
    # 6. decompression-block checksum @0x37FFE  (awdbedit: (imgsz-(decomp+boot))&0xFFFFF000 + 0xFFE)
    POS=0x37FFE
    dsum=sum(r[:POS])&0xff
    p(f"decomp-block cksum @{POS:#07x} == {dsum:#04x} (got {r[POS]:#04x})", r[POS]==dsum)
    # 7. bootblock per-4KB page checksums on the two decomp pages: sum8(pg[:0xFFF])==pg[0xFFF]
    for pg in (0x36000,0x37000):
        ps=sum(r[pg:pg+0xFFF])&0xff
        p(f"page cksum @{pg:#07x} byte@0xFFF {r[pg+0xFFF]:#04x} == {ps:#04x}", r[pg+0xFFF]==ps)
    return ok

if __name__=='__main__':
    for f in sys.argv[1:]:
        print(f"\n=== {os.path.basename(f)} ===")
        print(f"  ==> {'VALID' if check(f) else 'INVALID'}")
