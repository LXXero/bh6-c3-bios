# ABIT BH6 (v1.1 / v1.2) + VIA C3 "Ezra-T" — BIOS patch project

Goal: make a **VIA C3 (CentaurHauls, CPUID family 6, locked 10× multiplier)**
run at **100 MHz FSB × 10 = 1000 MHz** on an **ABIT BH6** (i440BX, Award BIOS
4.51PG, "SP" revision) by patching the BIOS. The stock BH6 does not know the C3:
it mis-detects it, refuses the settings, and cold-boots it at 66 MHz × 10 = 667.

**Status: SOLVED and proven on hardware (2026-09-07), released as
[v1.0](https://github.com/LXXero/bh6-c3-bios/releases/tag/v1.0).** Detection,
naming, the multiplier, the "CPU unworkable" nag *and* the FSB-won't-stick-at-100
problem are all fixed. The real root cause of the FSB reset was **not** in the
SoftMenu apply path: an early CPU-type check in the directly-mapped decompression
block (raw ROM `0x37BB7`, outside `original.tmp`, so MODBIN never touched it)
mis-classified the model-8 C3 as a CPU change and restored CPU defaults on every
cold boot. v16 fixed it with a vendor-aware cave that excuses CentaurHauls
(`scripts/apply_early_cpu_fix.py`, applied to the raw ROM after the MODBIN rebuild,
recomputing both the decomp-block and the per-4 KB page checksums); v17 is the clean
production build shipped in the release. The v15 "FSBFIX" clock-apply hook described
further down was superseded and is **not** in the shipped ROM. Full analysis:
`CPU-RESET-DIAGNOSIS.md` and `C3-RESET-HANDOFF.txt`.

**Board revisions: ABIT BH6 v1.1 / v1.2 only** — the ROM is built from the BH32
"SP" BIOS for those revisions. Do not flash it to other BH6 revisions or boards.

---

## The hardware / environment

- Board: ABIT BH6 **v1.1 / v1.2** (i440BX), Award 4.51PG, SoftMenu II, clock synth = ICS9148
  programmed over SMBus (I/O 0x5000, device address 0xD2). Fixed-mode synth: one
  "mode byte" per FSB selection sets CPU + PCI + AGP-ref together.
- CPU under test: VIA C3 marked **"1000AMHz"** (1000 MHz, 100 MHz bus). It is an
  **Ezra-T** — CPUID vendor "CentaurHauls", family 6 model 8, CPUID.1 EAX `0x068A`;
  the 100 MHz bus ("A" part) is the Ezra-T tell (it was initially mis-identified as
  a Nehemiah). Ceramic package. A second C3 is a 133 part. Slotket currently
  strapped to 100.
- Stock ROM: `roms/BH32_SP.BIN` (256 KB, md5 `236165383346b718189c7c97fe61aef4`).
- Recovery is proven: bootblock + a DOS floppy with stock `BH32_SP.BIN` and
  `awdflash` always brings it back after a bad flash. A TL866 + PLCC32 adapter is
  the last-resort out-of-band recovery. **Always keep stock on the floppy.**

## Award 4.51PG ROM layout (what has to stay valid)

- ROM is LHA `-lh5-` modules. The main body is the module at ROM 0x20000,
  which decompresses to a **128 KB `original.tmp`**: first 64 KB = E000 segment,
  last 64 KB = F000 segment. All patch offsets below are into that 128 KB body.
- Five checksums must all be correct or you get "BIOS ROM checksum error" ->
  bootblock recovery:
  1. LZH header checksum = sum8(header[2:])
  2. body CRC16 in the LZH header
  3. F000-segment sum8(body[0x10000:0x20000]) == 0
  4. module trailer = `[0x00][sum8(LZH header + compressed data)]` right after data
  5. decomp-block checksum at ROM 0x37FFE = sum8(rom[0:0x37FFE])
- **MODBIN 4.50.80C is the only tool that rebuilds the body + fixes all five.**
  CBROM handles the component modules but NOT `original.tmp`. We drive MODBIN under
  DOSBox (see Build below).

## Build / flash workflow

1. `scripts/patch_c3_v15.py <in original.tmp> <out body.bin>` produces a patched
   128 KB body. It self-checks: every cave write lands on 0xFF, E000 sum is made
   equal to stock via a compensator byte, F000 sum stays 0, all hook sites are
   asserted against expected stock bytes.
2. `tools/run-modbin.sh` launches MODBIN in DOSBox. It creates `ORIGINAL.TMP`
   (the decompressed stock body). Overwrite that with the patched body, then in
   MODBIN choose **Update File -> BH32_SP.BIN**; MODBIN recompresses with Award's
   own compressor and fixes all checksums.
3. `scripts/validate.py <rebuilt BH32_SP.BIN>` checks all ROM invariants; it
   passes all 7 official BH6 revisions and rejects bad builds.
4. Write the rebuilt `.BIN` to the DOS floppy as `BH32_C3.BIN`, flash on the board
   with `awdflash`.

DOSBox on this machine (xLin.x, labwc/Wayland) needs
`DISPLAY=:0 SDL_VIDEODRIVER=x11 XDG_RUNTIME_DIR=/run/user/1000`. Key injection:
`wtype` works (xdotool/XTEST does not under Xwayland) but is flaky, so the user
usually clicks Update File by hand.

---

## What the body patches do (v12 lineage — proven on hardware)

The shipped body patch is `scripts/patch_c3_v17.py` (the v12 lineage below, cleaned
of the v14 trace instrumentation and the superseded v15 FSB hook); the raw-ROM
early-CPU-check fix is applied on top by `scripts/apply_early_cpu_fix.py`. In order:

1. **Vendor detect + POST name (PROVEN).** The BH6 vendor-dispatch table at body
   0x3443 is 14-byte entries `[handler ptr][12-byte vendor string]`. We repoint
   the Cyrix entry's string to `CentaulsaurH` and its handler to a cave routine
   (0xD600) that disables the local APIC bit and sets the POST CPU name to
   "VIA C3". Result on hardware: board shows **VIA C3**, no beep.

2. **VIA EBLCR multiplier decode (PROVEN).** Stock reads the multiplier the Intel
   way; the C3 encodes it differently (Linux `drivers/cpufreq/longhaul.h`). We
   hook the multiplier getter at 0x3554 into a cave routine (0xD660) that: checks
   CentaurHauls, reads MSR 0x2A / EBLCR, does `cpuid` to pick the VIA model table
   (samuel1/samuel2/ezra/ezrat/nehemiah — tables at 0xD700), and returns the true
   ratio. Result: **10× sticks** (CMOS 0x60 persists across cold boots).

3. **Preset-vs-computed validation bypass (PROVEN).** 0x17A (called from the
   validator at 0x54) -> `xor al,al; ret` so the speed check always passes. This
   is what the BF6 effectively does; kills the "CPU has been changed" path.

4. **"CPU is unworkable / changed" nag + settings-reset kill (PROVEN).** Validator
   entry 0x44 `test [bp+0x39],1; jnz reset` -> `call NAGCLR` (cave 0xD7A0), which
   clears the sticky bit in the RAM shadow AND in CMOS 0x39.

5. **CMOS writeback range extension (from v12).** Generic writeback at E000:0x9EB3
   originally commits CMOS 0x10..0x3F; extended to 0x10..0x41 so the FSB byte
   (CMOS 0x41) is carried shadow<->CMOS. (Checksum ranges are a separate table and
   unchanged; 0x41 and 0x3A are in the un-checksummed gap, safe to poke.)

6. **v15 "FSBFIX" clock-apply hook — SUPERSEDED, not shipped.** It forced 100 MHz
   at clock-apply time; the real reset happens far earlier (see Status). Kept in the
   next section because the synth/FSB analysis there is still correct.

---

## The FSB problem and the v15 attempt (historical — superseded)

> The clock-synth / CMOS analysis in this section is correct and was essential, but
> the v15 hook it proposes was superseded: the FSB reset originates in an early
> CPU-type check in the decompression block (see Status and `CPU-RESET-DIAGNOSIS.md`).
> The "open questions" at the end are answered by that finding.

### Symptom
Multiplier (10×) sticks, but FSB will not stay at 100 across a **cold** boot.
- Manual CMOS poke `0x41=0x0F` + **warm** reboot: value stays, but the board still
  runs 66 MHz (warm reboot does not reprogram the clock synth).
- **Cold** boot: `0x41` reverts and the board programs the synth to 66 MHz.

### How the board actually sets FSB (discovered this session)
The real hardware FSB is set exactly once, at POST phase 0x1C11 (the clock-gen
apply), by the routine at body **0xC672**:
```
mov al,0x41 ; call CMOS-read      ; al = FSB byte
mov ah,0xF8 ; call extract        ; si_index = (0x41 & 0xF8) >> 3
add si, index ; mov al,[cs:si]    ; si -> mode-byte table @0xC618
                                  ; -> cs:0xC524 = ICS9148 mode byte
... then 0xC68E writes the synth over SMBus (port 0x5000, dev 0xD2)
```
So **CMOS 0x41 at the instant 0xC672 runs fully determines the FSB.** The index
-> frequency -> mode-byte map is decoded in `traces/external_clock_index_map.txt`.
Key rows:
| CMOS 0x41 (idx) | mode byte | meaning |
|---|---|---|
| idx 0  (0x03) | 0x30 | 66 MHz(1/2)N  <- the cold-boot revert value |
| idx 1  (0x0F) | 0x70 | 100 MHz(1/3)**N** — SEL not asserted -> 443BX straps AGP **1/1** (AGP would run 100!) |
| idx 22 (0xB7) | 0x72 | 100 MHz(1/3)**S** — SEL100/66# asserted -> 443BX straps AGP **2/3 = 66** ✅ |

### Why it reverts (v14 trace)
`traces/F_v14_coldboot_after_SET100.TXT` is a full CMOS dump after setting
`0x41=0x0F` then cold booting a v14 build that snapshots CMOS 0x41 at two POST
phases into scratch CMOS bytes 0x33/0x34:
- Before phase 0x1A11: `0x41` was already **0x83** (user's 0x0F overwritten early)
- Before phase 0x1C11 (apply): `0x41` was **0x03** (idx0 = 66)

So the SoftMenu preset engine (in `modules/awardext.rom`, the SoftMenu apply
routines around 0x55C5 / preset->FSB table at awardext 0x5860) rewrites 0x41 twice
on cold boot, landing on the 66 MHz default, *before* the synth is ever
programmed. That is the reset the user asked us to find.

### The fix
Rather than chase every writer of 0x41 in awardext, v15 forces the correct value
**downstream of all of them**, right before 0xC672 reads it. The dead-code gate at
0xC658 is repurposed to `call FSBFIX` (cave 0xD7C0):
```
FSBFIX: call CENTCHK            ; ZF=1 iff CentaurHauls (C3)
        jnz  done
        mov al,0x41 ; mov ah,0xB7 ; call CMOS-write   ; idx22 = 100MHz(1/3)S
        mov al,0x3A ; call CMOS-read ; or al,0x40      ; AGPCLK/CPUCLK = 2/3
        mov ah,al ; mov al,0x3A ; call CMOS-write
done:   ret
```
Then the normal apply reads 0x41=0xB7 -> mode byte 0x72 -> synth programmed to
**100 MHz host, SEL asserted, PCI 33, AGP 66**. Because idx22 is the "S" variant,
the 443BX sees SEL100/66# asserted and straps AGP to 2/3 (this is what protects
the user's AGP card from a 100 MHz AGP clock — their explicit requirement).
Non-Centaur CPUs skip the whole thing, so the ROM is still correct for any Intel
part. The multiplier is already forced to 10 by patch #2, so the result is
**100 × 10 = 1000 MHz** on every cold boot.

### Open questions for a reviewer
- **N vs S / AGP strap timing.** We force idx22 (S, mode 0x72) specifically so the
  northbridge straps AGP 2/3. Assumption: the 443BX AGP strap is (re)sampled from
  the clock chip's SEL output when the synth is reprogrammed at apply, matching a
  normal 100 MHz SoftMenu selection. If the strap is latched only at power-on
  CPURST, AGP could still come up wrong and we may need to also force 0x41 earlier
  (e.g. at the CMOS-load hook, F:3406 -> E000:0x9E48) and/or trigger a warm reset
  after the synth write. Verify AGP clock after boot.
- **Is there a second synth write?** Confirm 0xC68E is the only clock program on
  the C3 path (v13 trace showed the computed speed after apply was 0x9B=667, i.e.
  the apply is the deciding write; v15 changes only its input).
- **SoftMenu display.** After v15, CMOS 0x41 ends at 0xB7 so SoftMenu should show
  100 MHz(1/3)S. Confirm it isn't re-reset for display after apply.

---

## File map (local working tree — only `roms/`, `scripts/` and the docs are published; see Repository contents)

- `scripts/patch_c3_v17.py` — shipped body patch; `scripts/apply_early_cpu_fix.py`
  then applies the v16 raw-ROM early-CPU-check fix. v8..v12 are the working lineage;
  v14/v15 are the trace and FSB-hook experiments; v2/v4/v6/v7 are dead ends kept for
  history (see patch-notes).
- `scripts/validate.py`, `scripts/awardrebuild.py` — ROM checksum tooling.
- `bodies/BH6_SP_original.tmp` — decompressed stock body (patch input, all offsets
  are relative to this). `body_v12/14/15_patched.bin` — patched bodies.
- `modules/awardext.rom` — decompressed SoftMenu/CPU module (the FSB reset lives
  here). `awardeyt.rom`, `bootblock_8k.bin` — other extracted pieces.
- `roms/` — stock, all 7 BH6 family revs, the BF6 (which supports the C3 natively,
  reference only — different programmable synth), and the flashed C3 builds.
- `dos/` — `CMOSDUMP.COM` (dump 0x00-0x7F), `CMOSDMP2.COM` (0x80-0xFF),
  `CMOSSET.COM <idx> <val>`, and batch files `SET100.BAT` / `SET66.BAT` /
  `DUMP.BAT`.
- `traces/external_clock_index_map.txt` — the decoded FSB index/mode-byte/MHz map.
- `traces/F_v14_coldboot_after_SET100.TXT` — the cold-boot CMOS dump proving the
  early double-reset of 0x41.
- `tools/` — MODBIN.EXE, run-modbin.sh, lha.

## Key body offsets (into `bodies/BH6_SP_original.tmp`)

| Offset | What |
|---|---|
| 0x3443 | vendor dispatch table (14-byte entries) |
| 0x3554 | multiplier getter hook site |
| 0xC672 | clock-gen apply: reads CMOS 0x41 -> synth mode byte |
| 0xC618 | 32-entry ICS9148 mode-byte table (index by 0x41>>3) |
| 0xC68E | SMBus synth write (port 0x5000, dev 0xD2) |
| 0x9EB3 | generic CMOS writeback (range table F000:0x0B90) |
| 0x0044 / 0x017A | nag / validator entries |
| 0xD600.. | cave: handler/name/centchk/mult/tables/nagclr/**FSBFIX@0xD7C0** |

CMOS map (SoftMenu): 0x35 preset+class, 0x39 flags, **0x3A** turbo7/agpclk6/pwr5/
vcore[4:0], **0x41** FSB[7:3]/SEL.2, 0x60 multiplier[4:0], 0x7C VID.

## Repository contents

- `roms/BH32_SP.BIN` — original ABIT BH6 "SP" Award BIOS (the base this patch was built from)
- `roms/BH32_C3_v17_clean.BIN` — the final patched BIOS: VIA C3 (Ezra-T) at 100 MHz FSB × 10 = 1000 MHz on the BH6
- `scripts/` — the patch tooling (`patch_c3_*.py` body patches, `apply_early_cpu_fix.py` raw-ROM fix, `validate.py` checksum checks, `diagnose_cpu_reset.py` emulation-based diagnosis)
- `CPU-RESET-DIAGNOSIS.md`, `C3-RESET-HANDOFF.txt`, `bh6-c3-bios-patch-notes.md` — the full write-up of the problem and the fix

Not included: intermediate decompressed bodies, extracted Award modules, third-party tools (MODBIN, lha) and unrelated BIOS dumps — they are regenerable or obtainable elsewhere and add nothing for end users.

**Flash at your own risk.** This is a modified BIOS for one specific board revision (ABIT BH6 v1.1 / v1.2) and CPU (VIA C3). Verify checksums with `scripts/validate.py` before flashing, and keep a recovery path (hot-flash / spare chip).
