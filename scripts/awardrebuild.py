#!/usr/bin/env python3
"""Rebuild an Award BIOS ROM with a modified main module (original.tmp).
Zero-layout-change: recompressed stream is padded back to the original size."""
import sys, os, struct, subprocess, tempfile, shutil

LHA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools/lhainst/bin/lha')
MODOFF = 0x20000

def crc16(data):
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc

def rebuild(rom_path, body_path, out_path):
    rom = bytearray(open(rom_path,'rb').read())
    body = open(body_path,'rb').read()
    # --- parse original header ---
    hsize = rom[MODOFF]                      # header length - 2
    hdr_total = hsize + 2
    orig_csize, orig_osize = struct.unpack_from('<II', rom, MODOFF+7)
    assert len(body) == orig_osize, f"body must be {orig_osize} bytes, got {len(body)}"
    # --- compress with lha (level-0 header) ---
    tmp = tempfile.mkdtemp()
    shutil.copy(body_path, os.path.join(tmp,'original.tmp'))
    subprocess.run([LHA,'a0','-o5','out.lzh','original.tmp'], cwd=tmp,
                   capture_output=True, check=True)
    lz = open(os.path.join(tmp,'out.lzh'),'rb').read()
    our_hsize = lz[0]+2
    our_csize = struct.unpack_from('<I', lz, 7)[0]
    cdata = lz[our_hsize:our_hsize+our_csize]
    shutil.rmtree(tmp)
    if our_csize > orig_csize:
        raise SystemExit(f"ERROR: recompressed {our_csize} > original {orig_csize}; won't fit")
    # --- pad compressed stream back to original size (preserves all later offsets) ---
    cdata_padded = cdata + b'\xff' * (orig_csize - our_csize)
    # --- build header: clone original, fix CRC, keep csize, fix header checksum ---
    hdr = bytearray(rom[MODOFF:MODOFF+hdr_total])
    struct.pack_into('<I', hdr, 7, orig_csize)         # keep original csize (padded)
    struct.pack_into('<I', hdr, 11, len(body))
    namelen = hdr[21]
    struct.pack_into('<H', hdr, 22+namelen, crc16(body))
    hdr[1] = sum(hdr[2:]) & 0xff                        # header checksum
    # --- splice ---
    rom[MODOFF:MODOFF+hdr_total+orig_csize] = bytes(hdr) + cdata_padded
    # --- module trailer: awdbedit writes 0x00 then sum8(LZH header + compressed data) ---
    end = MODOFF + hdr_total + orig_csize
    trailer = sum(rom[MODOFF:end]) & 0xff
    rom[end]   = 0x00
    rom[end+1] = trailer
    print(f"  module trailer fixed: 0x00 {trailer:#04x}")
    assert len(rom) == os.path.getsize(rom_path), "size changed!"
    open(out_path,'wb').write(rom)
    print(f"  rebuilt -> {out_path}")
    print(f"  compressed {our_csize} bytes (padded to {orig_csize}, {orig_csize-our_csize} slack)")
    print(f"  body CRC16 = {crc16(body):#06x}   header cksum = {hdr[1]:#04x}")

if __name__=='__main__':
    rebuild(sys.argv[1], sys.argv[2], sys.argv[3])
