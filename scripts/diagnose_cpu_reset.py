#!/usr/bin/env python3
"""Run actual BH6 machine code with simulated CPUID/MSR and port inputs.

No host port access and no firmware writes. This is a routine-level emulator,
not a model of the motherboard or a complete POST. CPUID, MSR 11E, and I/O
inputs are supplied by the harness. Input CMOS is the captured v14 dump with
SET100.BAT's three edits applied in memory. Board VID reads are mocked as zero;
therefore CMOS 40/7C are not predictions of the physical board's VID values.

Dependencies: unicorn 2.1.4, capstone 5.0.9 (versions used for this analysis).
Use --ebx with C3CHECK's BIOS-input EBX result to reproduce a measured value.
"""
import argparse
from pathlib import Path
from collections import deque
import unicorn as u
from unicorn import x86_const as x
from capstone import Cs, CS_ARCH_X86, CS_MODE_16

ROOT = Path(__file__).resolve().parents[1]
DIS = Cs(CS_ARCH_X86, CS_MODE_16)

def read_cmos():
    result = bytearray(128)
    for line in (ROOT/'traces/F_v14_coldboot_after_SET100.TXT').read_text().splitlines():
        key, data = line.split(':')
        values = bytes.fromhex(data)
        offset = int(key, 16)
        result[offset:offset+len(values)] = values
    return result

class Run:
    def __init__(self, cmos, signature=0x68a, ebx=0, msr=0, stage='early', verbose=False):
        self.cmos = bytearray(cmos)
        self.signature, self.ebx, self.msr = signature, ebx, msr
        self.verbose = verbose
        self.selected = 0
        self.writes = []
        self.path = []
        self.recent = deque(maxlen=25)
        self.reason = None
        self.m = m = u.Uc(u.UC_ARCH_X86, u.UC_MODE_16)
        m.mem_map(0, 0x200000)
        m.mem_write(0xc0000, (ROOT/'roms/BH32_C3_v14_trace.BIN').read_bytes())
        assert bytes(m.mem_read(0xf7bb5, 9)) == bytes.fromhex('24033ad87432e9bf00')
        if stage == 'main':
            m.mem_write(0xe0000, (ROOT/'bodies/body_v14_patched.bin').read_bytes())
            m.reg_write(x.UC_X86_REG_CS, 0xe000)
            m.reg_write(x.UC_X86_REG_SS, 0)
            m.reg_write(x.UC_X86_REG_DS, 0xf000)
            m.reg_write(x.UC_X86_REG_SP, 0x7f00)
            m.reg_write(x.UC_X86_REG_BP, 0x500)
            m.mem_write(0x500, bytes(cmos))
            self.start, self.stops = 0xe008e, {0xe0126: 'main identification complete'}
        else:
            # The early code uses a ROM word as a return address: SS=CS, SP
            # points to the inline continuation word following each JMP.
            m.reg_write(x.UC_X86_REG_CS, 0xf000)
            m.reg_write(x.UC_X86_REG_SS, 0xf000)
            self.start = 0xf7af1
            self.stops = {0xf7d33: 'apply current CPU settings',
                          0xf7db8: 'continue POST without CPU reset'}
        m.hook_add(u.UC_HOOK_INSN, self.cpuid, None, 1, 0, x.UC_X86_INS_CPUID)
        m.hook_add(u.UC_HOOK_INSN, self.port_in, None, 1, 0, x.UC_X86_INS_IN)
        m.hook_add(u.UC_HOOK_INSN, self.port_out, None, 1, 0, x.UC_X86_INS_OUT)
        m.hook_add(u.UC_HOOK_CODE, self.code)

    def cpuid(self, m, data):
        leaf = m.reg_read(x.UC_X86_REG_EAX)
        if leaf == 1:
            ebx = m.reg_read(x.UC_X86_REG_EBX) if self.ebx is None else self.ebx
            values = (self.signature, ebx, 0, 0)
        elif leaf == 0:
            values = (1, 0x746e6543, 0x736c7561, 0x48727561)
        else:
            raise RuntimeError(f'unmodeled CPUID leaf {leaf:x}')
        for reg, val in zip((x.UC_X86_REG_EAX, x.UC_X86_REG_EBX,
                             x.UC_X86_REG_ECX, x.UC_X86_REG_EDX), values):
            m.reg_write(reg, val)
        return 1

    def port_in(self, m, port, size, data):
        if port == 0x71:
            return self.cmos[self.selected & 0x7f]
        if port == 0x60:
            return 0  # No INSERT key held.
        if port in (0xcfc, 0xcfd, 0xcfe, 0xcff, 0xd96):
            return 0  # Board setup reads after reset decision only.
        raise RuntimeError(f'unmodeled IN {port:x} at {m.reg_read(x.UC_X86_REG_IP):x}')

    def port_out(self, m, port, size, value, data):
        if port == 0x70:
            self.selected = value
        elif port == 0x71:
            off = self.selected & 0x7f
            self.writes.append((off, self.cmos[off], value))
            self.cmos[off] = value
        elif port not in (0x60, 0x64, 0x80, 0xeb, 0xcf8, 0xcfc, 0xcfd,
                          0xcfe, 0xcff, 0xd95):
            raise RuntimeError(f'unmodeled OUT {port:x}')

    def code(self, m, addr, size, data):
        self.recent.append(addr)
        if addr in self.stops:
            self.reason = self.stops[addr]
            m.emu_stop()
            return
        if addr in (0xf7b8e, 0xf7bb7, 0xf7bed, 0xf7c5c, 0xf7c7d,
                    0xf7cdb, 0xf7d0b):
            self.path.append(f'{addr-0xc0000:05X}')
        if self.verbose and not (0xf7c0d <= addr <= 0xf7c31):
            ins = next(DIS.disasm(bytes(m.mem_read(addr, size)), addr))
            print(f'{addr:05x}: {ins.mnemonic:8} {ins.op_str:24} '
                  f'AX={m.reg_read(x.UC_X86_REG_AX):04x} '
                  f'BX={m.reg_read(x.UC_X86_REG_BX):04x}')
        if bytes(m.mem_read(addr, 2)) == b'\x0f\x32':
            assert m.reg_read(x.UC_X86_REG_ECX) == 0x11e
            m.reg_write(x.UC_X86_REG_EAX, self.msr & 0xffffffff)
            m.reg_write(x.UC_X86_REG_EDX, self.msr >> 32)
            m.reg_write(x.UC_X86_REG_IP, (m.reg_read(x.UC_X86_REG_IP)+2)&0xffff)

    def run(self):
        try:
            self.m.emu_start(self.start, 0x200000, count=300000)
        except Exception:
            print('Last executed physical addresses:', [hex(a) for a in self.recent])
            raise
        assert self.reason, 'instruction budget exhausted'
        shadow35 = self.m.mem_read(0x535,1)[0]
        return {'end': self.reason, 'path_rom_offsets': self.path,
                'changed_cmos': [f'{a:02X}: {b:02X}->{c:02X}'
                                 for a,b,c in self.writes if b != c],
                'final_cmos': {f'{a:02X}':f'{self.cmos[a]:02X}'
                               for a in (0x35,0x37,0x39,0x3a,0x41,0x7d,0x7e)},
                'shadow35': f'{shadow35:02X}'}

    def call_main(self, offset):
        """Execute a near-returning E000 routine with a RAM stack sentinel."""
        self.m.reg_write(x.UC_X86_REG_CS, 0xe000)
        self.m.reg_write(x.UC_X86_REG_SS, 0)
        self.m.reg_write(x.UC_X86_REG_SP, 0x7efe)
        self.m.mem_write(0x7efe, b'\x00\x10')
        self.start = 0xe0000 + offset
        self.stops = {0xe1000: f'near return from E000:{offset:04X}'}
        self.reason = None
        return self.run()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--verbose', action='store_true')
    p.add_argument('--ebx', type=lambda s: int(s,16),
                   help='CPUID(1) EBX hex result from C3CHECK, using the BIOS input')
    args=p.parse_args()
    c=read_cmos()
    for a,v in ((0x41,0x0f),(0x3a,0x40),(0x37,0xf9)):
        c[a]=v
    stock=(ROOT/'roms/BH32_SP.BIN').read_bytes()
    v14=(ROOT/'roms/BH32_C3_v14_trace.BIN').read_bytes()
    assert stock[0x37af1:0x37dbb] == v14[0x37af1:0x37dbb]
    for start,end,stored in ((0x10,0x2d,0x2e),(0x42,0x79,0x7a)):
        computed=sum(c[start:end+1])
        actual=int.from_bytes(c[stored:stored+2],'big')
        assert computed == actual
        print(f'CMOS {start:02X}..{end:02X}: checksum {computed:04X} VALID')
    if args.ebx is not None:
        print(f'Supplied EBX={args.ebx:08X}:',Run(c,ebx=args.ebx,verbose=args.verbose).run())
        return
    for ebx in (0,1,2,3):
        r=Run(c,ebx=ebx,verbose=args.verbose)
        print(f'EARLY POST signature=068A EBX={ebx:08X} saved CMOS35={c[0x35]:02X}')
        result=r.run()
        print(result)
        if ebx==1:
            assert not r.writes
        else:
            assert (r.cmos[0x37],r.cmos[0x41],r.cmos[0x3a]) == (0x46,3,0)
            assert result['path_rom_offsets'] == ['37B8E','37BB7','37C7D','37D0B']
    for msr in (0,0x2000,0x800000,0x802000):
        r=Run(c,msr=msr,stage='main',verbose=args.verbose)
        print(f'MAIN IDENTIFICATION signature=068A MSR11E={msr:016X}')
        print(r.run())
    print('EARLY POST with CPUID(1) leaving EBX unchanged:')
    print(Run(c, ebx=None).run())
    print('TWO BOOTS: CPUID EBX=0, MSR11E=00800000, actual early/main/write routines:')
    cycle = c.copy()
    for boot in range(1,3):
        early = Run(cycle)
        print(f'boot {boot}, early:', early.run())
        late = Run(early.cmos, stage='main', msr=0x800000)
        print(f'boot {boot}, identify:', late.run())
        late.call_main(0xd7a0)
        late.m.reg_write(x.UC_X86_REG_CX,0x1041)
        print(f'boot {boot}, nag clear + shadow writeback:',late.call_main(0x9f4e))
        assert (late.cmos[0x35],late.cmos[0x37],late.cmos[0x39],
                late.cmos[0x3a],late.cmos[0x41]) == (1,0x46,0,0,3)
        cycle = late.cmos
    print('PASS: all routine-level reproduction checks passed.')

if __name__ == '__main__':
    main()
