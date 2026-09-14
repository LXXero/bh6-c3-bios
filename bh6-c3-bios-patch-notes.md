# BH6 BIOS — adding VIA C3 support (reverse-engineering notes)
*Sep 6 2026. Goal: make ABIT BH6 (rev 1.1, BIOS "SP") POST with a VIA C3 (Nehemiah 1.0A),
which currently garbles the CPU line ("BsG") and hangs.*

## Files
- BH6 latest:  `BH32_SP.BIN` (256KB, ID 2A69KA1V, bh632sp.exe) — on NAS `/mnt/xnas/media/dos/BH32_SP.BIN`
- BF6 latest:  `Beh_70.bin`  (256KB, beh-70, 12/2001) — the board that DOES run the C3
- BH6 family for diffing: kk, lg, nk, nx, pm, qm, sp (theretroweb)

## ROM structure (Award, 256KB)
LHA `-lh5-` modules. Main body = module at **0x20000** → `original.tmp`, **128KB decompressed**
(78074 compressed). Other modules: CPUCODE.BIN (40KB), ACPITBL.BIN, AWARDEPA.BIN, awardext.rom.
`original.tmp` maps to **E000 seg = first 64K**, **F000 seg = last 64K**.

## ROOT CAUSE (found)
The CPU-vendor dispatch table is a list of 14-byte entries:
`[2-byte handler offset][12-byte CPUID leaf-0 vendor string in EBX,ECX,EDX order]`, terminated `FF FF`.
Dispatch loop confirms it: `add si,0xe` / `mov si,[cs:si]` / `call si`.

| BIOS | table entries |
|---|---|
| **BH6 SP** | GenuineIntel(→0x3453), CyrixInstead(→0x349f), FFFF |
| **BF6 beh-70** | GenuineIntel(→0x2f06), CyrixInstead(→0x2f5c), **CentaurHauls(→0x2f69)**, FFFF |

**A VIA C3 reports vendor `CentaurHauls`. BH6 has no such entry** → falls off the end of the
table → garbage name + hang. BF6 has it → works. That's the entire bug (~14 bytes).
NOTE: BH6's "Cyrix III" support is for the *Joshua* core (reports `CyrixInstead`), NOT Samuel.

## The handlers (tiny!)
BF6 CentaurHauls @0x2f69:
```asm
mov ecx,0x1b ; rdmsr ; and ah,0xf7 ; wrmsr   ; <-- DISABLES LOCAL APIC (MSR 0x1B bit 11)
mov word [bp+0x1a7],0x407
mov word [bp+0x1a5],0x75b9                   ; -> name string "VIA CyrixIII"
ret
```
BH6 CyrixInstead @0x349f:
```asm
mov word [bp+0x222],0x8f92                   ; -> name string "Cyrix III "
ret
```
**The APIC-disable is likely the critical anti-hang step** (BF6 does it only for Centaur CPUs).
Handler pointers and name-string pointers are **direct file offsets into original.tmp**.

## CHECKSUM RULE (verified on all 7 BH6 revisions + needed for any patch)
`sum8(original.tmp[0x10000:0x20000]) == 0x00`  ← the **F000 segment** must sum to zero.
The **E000 segment (first 64K) is NOT checksummed** (varies freely across revisions).
No whole-flash-image checksum exists (whole/lower/upper sums all vary across revisions).

## PATCH PLAN
Everything we touch is in the **E000 segment → no checksum fix required.**
1. Overwrite BH6's CyrixInstead table entry (file ~0x3490) with `[newptr]["CentaulsaurH"]`
   (sacrifices Joshua-core Cyrix III detection — acceptable; those are unicorn-rare).
   *Alt:* relocate whole table into the cave to keep both entries.
2. Write new handler into **code cave @0x0d600 (10752 bytes of 0xFF, in E000 seg)**:
   `mov ecx,0x1b / rdmsr / and ah,0xf7 / wrmsr / mov word [bp+0x222],<nameptr> / ret`  (~20 bytes)
3. Put a "VIA C3" name string in the cave.
4. **Recompress** original.tmp as `-lh5-` and rebuild the Award container. ← ONLY REMAINING HURDLE
   (7z decompresses lh5 fine but can't create it; need CBROM under dosbox, or an lha compressor.)
   Other free space: 0x05d51 (8879 bytes of 0x00).

## Caveats
- Fixing detection is necessary but maybe not sufficient — C3 on 440BX may also have AGTL/VREF
  quirks. But xero's Nehemiah runs fine in the BF6 (also 440BX), so hardware is likely OK.
- Flash in-system with awdflash; keep TL866 + PLCC32 as brick recovery. Back up stock SP first.

---
# ✅ PATCH BUILT (Sep 6 2026) — `BH32_C3.BIN` md5 af86f64945a0b1b2a2f3587dd77c393a

## Toolchain solved
`-lh5-` recompression: built **jca02266/lha** from source (`lha a0 -o5` = level-0 header).
Round-trip verified byte-identical (CRC16 0xa1c0 matches Award's own).
Rebuild script `awardrebuild.py`: recompresses body, **pads the stream back to the original
78074 bytes so ZERO downstream offsets move**, clones Award's header, fixes CRC16 +
header checksum (reproduced Award's own 0x62 exactly on an unmodified rebuild).
Pipeline proven: rebuilt-unmodified ROM = same size, all diffs inside module data, body md5 identical.

## The patch (40 bytes changed, all in the un-checksummed E000 segment)
- `0x3443` vendor table: `CyrixInstead`→**`CentaulsaurH`**, handler ptr `0x349f`→`0xd600`
  (sacrifices Cyrix III *Joshua* detection — vanishingly rare)
- `0xd600` new handler in the 0xFF code cave (20 bytes):
  `mov ecx,0x1b / rdmsr / and ah,0xf7 / wrmsr / mov word [bp+0x222],0xd620 / ret`
  (the APIC-disable is copied from BF6's Centaur handler — likely the anti-hang step)
- `0xd620` name string `"VIA C3\0"`
- F000 checksum still `0x00` ✓

## Files (NAS `/mnt/xnas/media/dos/bh6-c3-project/`)
`BH32_C3.BIN` (the patched ROM), `awardrebuild.py`, `patch_c3.py`, `lha-linux-x86_64`,
all 7 stock BH6 revs, BF6 beh70, both decompressed bodies.

## ⚠️ BEFORE FLASHING
UNTESTED ON HARDWARE. Have the **TL866 + PLCC32** ready as recovery.
`awdflash BH32_C3.BIN` and **say YES to saving the old BIOS** first.
If it hangs differently / doesn't POST → reflash stock `BH32_SP.BIN`, or recover via TL866.
Detection is fixed, but C3-on-440BX may still have hardware-level (AGTL/VREF) quirks.
