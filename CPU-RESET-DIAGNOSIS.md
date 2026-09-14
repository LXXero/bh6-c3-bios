# CPU settings reset: evidence from the early ROM code

2026-09-07. Diagnostic work only; no BIOS image was changed or built.

The supplied ROM contains an early CPU-type comparison that can mistake this
VIA CPU for a changed Intel CPU and explicitly restore CPU defaults. It is in
the **raw ROM at 0x37AF1..0x37DBA**, outside the decompressed `original.tmp`.
That whole routine is byte-identical in stock SP and the v14 ROM.

The reset writer and its branch conditions are identified below.
**The hardware reading in `traces/C3CHECK.TXT` now confirms the CPU-type
disagreement: the CPU returns BL=00, while CMOS35&03 is 01.** Replaying the
actual v14 machine code with the measured CPUID registers selects the identified
CPU-defaults writer. This is a hardware measurement of the comparison inputs
plus routine-level execution of the ROM, not an instruction trace of physical
POST or a hardware test of a replacement firmware image.

## Hardware confirmation

The supplied `C3CHECK.TXT` reports:

```text
Vendor: CentaurHauls
CPUID 1 EAX EBX ECX EDX: 0000068A 00000000 00000000 00803035
CPUID 1 EBX with BIOS input 00000680 -> 00000000
CMOS: 0E=00 0F=00 35=01 37=46 39=00 3A=00 40=0C 41=03 7C=0C 7D=8A 7E=06
Early BIOS compares BL vs CMOS[35]&03: 00 vs 01
```

The live signature 068A matches the saved signature 068A. The subsequent
Intel-specific type comparison fails, however: 00 does not equal 01. EBX also
returns zero when seeded exactly as in the early BIOS check, ruling out the
previously unmeasured possibility that the comparison might pass on this CPU.

I reran the early ROM with all four measured CPUID(1) registers and the measured
CMOS fields overlaid on the earlier full dump. Both the captured settings and
SET100 settings applied only in simulated memory take this path:

```text
37B8E (signature matches) -> 37BB7 (type mismatches)
    -> 37C7D (fallback) -> 37D0B (load CPU defaults)
```

With the simulated SET100 settings, the actual firmware writes 37:F9->46,
41:0F->03, and 3A:40->00. The resulting defaults match the hardware capture.
Board VID inputs remain mocked; 40/7C changes in emulation are not hardware
predictions. This confirms the faulty comparison without another flash.

## What the existing evidence says

- The user reports that date and boot order survive, while CPU settings revert
  during both warm and cold POST.
- `F_v14_coldboot_after_SET100.TXT` contains CMOS 35=01, 37=46, 39=00,
  3A=00, 41=03, and saved signature 7E:7D=068A.
- The two configured CMOS checksums are valid: 10..2D sums to 0640, matching
  2E:2F; 42..79 sums to 12FB, matching 7A:7B. `SET100.BAT` changes only
  41, 3A, and 37, which are outside both checksum ranges.
- Stock SP and v14 pass the supplied ROM validator. A checksum failure is not
  required to reproduce this CPU reset.

## The early comparison

Addresses in this section are **raw 256-KiB ROM offsets**, not body offsets.
The code runs in F000, so raw 37BB7 corresponds to F000:7BB7. The bootblock
jumps into the early routine at raw 3E1A5, before its C1 POST checkpoint.

The early routine checks the standard CMOS checksum, then the saved signature,
then additional Intel-specific CPU-type information. The signature comparison
at 37B8E passes when both live and saved signatures are 068A.

```asm
; Raw 37B94: after the live-vs-saved signature comparison has passed
and bl,0xF0
cmp bl,0x60
je  0x37BED
cmp bl,0x80
jne 0x37BBE              ; another Intel MSR-based comparison

; Raw 37BA3: model 8, without a vendor check
mov eax,1
cpuid
; read CMOS 0x35 into AL, preserving CPUID's BL
; (uses ROM-based return addresses, see below)

; Raw 37BB5
and al,3
cmp bl,al                ; CPUID(1).EBX low byte vs CMOS[35]&3
je  0x37BED
jmp 0x37C7D              ; CPU-change fallback
```

The captured saved type is 01. The comparison therefore requires BL=01.
If the C3 returns 00, another value, or leaves EBX unchanged, it fails. If EBX
is left unchanged, BL is 80 here because of the earlier model mask. The DOS
diagnostic repeats CPUID with that BIOS input to distinguish these cases.

For this Centaur CPU, the saved 068A signature identifies family 6, model 8,
stepping A. The README's Nehemiah label conflicts with the captured model:
Linux's [Longhaul driver](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+/c7decec2f2d2ab0366567f9e30c0e1418cece43f/drivers/cpufreq/longhaul.c)
maps VIA model 8 to Ezra-T and model 9 to Nehemiah. `C3CHECK` now confirms the
live vendor and signature rather than relying on the project label.

## The writes that match the symptom

The fallback at 37C7D performs board/VID setup, then reaches 37CF1 and 37D0B.
It sets the CPU-change flag and writes these exact values:

| Raw ROM location | CMOS byte | Value | Captured post-boot value |
| --- | --- | --- | --- |
| 37D01 / 37D06 | 39 | old value OR 01, then AND 3F | 00 after the later NAGCLR patch |
| 37D11 / 37D16 | 37 | 46 | 46 |
| 37D1D / 37D22 | 41 | 03 | 03 |
| 37D29 / 37D2E | 3A | 00 | 00 |

The data constants are loaded at 37D0B: `mov ah,46; mov bh,03; mov bl,00`.
These are explicit firmware writes, not random CMOS corruption. They happen
before either of v14's trace hooks or the patched validator.

This explains how the warning can be gone while CPU defaults still return:
NAGCLR runs later, clears bit 0 of 39, and leaves the already-reset settings in
place. Extending generic writeback to 41 cannot recover the lost user value.

The main-body identification routine at E000:008E separately derives type 01
from its Intel-style MSR 11E logic and stores it into shadow byte 35. With MSR
11E=00800000, that assignment is unconditional. VIA's [Ezra datasheet, Appendix
A](https://device.report/m/50ec9eb1a5d4924d4a781a2a128cbe44cc101da6d20080ae63ab5c7a811135c0.pdf)
documents this compatibility MSR value for that core; the harness also tests
other values rather than assuming an MSR measurement of this board. The
physical dump independently establishes that the saved type currently is 01.
Later writeback persists it, so the mismatch can repeat on every boot.

## Reproduction and limits

`scripts/diagnose_cpu_reset.py` runs the actual raw-ROM instructions with
Unicorn. Its inputs are the captured CMOS dump plus the three SET100 edits,
applied only in simulated memory. It models the CMOS ports and supplies CPUID
and MSR responses. It performs no host port I/O and writes no input files.

| Controlled input | Executed branch | Result |
| --- | --- | --- |
| signature 068A, EBX=0, CMOS35=01 | 37BB7 -> 37C7D -> 37D0B | 37:F9->46, 41:0F->03, 3A:40->00 |
| signature 068A, EBX=1, CMOS35=01 | 37BB7 -> 37BED | no CMOS writes before apply |
| signature 068A, EBX=2 or 3, CMOS35=01 | mismatch fallback | same three reset values |
| signature 068A, EBX unchanged, CMOS35=01 | BL remains 80; mismatch | same three reset values |

The harness also executes the main identification, v14 NAGCLR, and actual
shadow-write loop for two successive simulated boots. For the mismatching
case, each ends with 35=01, 37=46, 39=00, 3A=00, 41=03, matching those fields in
the captured dump. These are selected routines connected by the harness,
**not full motherboard emulation or a hardware boot test**. Board VID reads are
mocked; resulting 40/7C values are not predictions. Synth programming and AGP
clock behavior are outside this reproduction.

Dependencies: Unicorn 2.1.4 and Capstone 5.0.9. From the repository root:

```sh
python scripts/diagnose_cpu_reset.py
```

For reuse elsewhere, install those Python packages in a virtual environment.
An observed CPUID EBX can be supplied as hex with `--ebx 00000000`.

## Why the previous trace interpretation was misleading

The snapshots use CMOS 33 and 34, which normal writeback covers. Stock POST
also changes shadow 33 bit 7 at E000:272A/2735 and E000:8C22. Therefore final
33=83 and 34=03 do **not** establish that CMOS 41 was first 83 and then 03, or
that `awardext.rom` performed two overwrites. A captured 03 can become 83 through
the normal shadow update; 34 can be replaced by an older shadow value.

The new README's attribution of the reset to SoftMenu based on those snapshots
is unsupported. The early raw-ROM routine provides a concrete alternative
with matching write values and an executable reproduction.

## Hardware diagnostic and next step

The hardware diagnostic has been run, and its output is preserved in
`traces/C3CHECK.TXT`. The invocation, for reference, is:

```dos
C3CHECK > C3CHECK.TXT
```

It reports the vendor, raw CPUID(1) registers, a second CPUID with the BIOS's BX
input, relevant CMOS bytes, and the operands of the exact early comparison.
It does not write CMOS data, access MSRs, program clocks, or flash firmware.
The 789-byte executable was tested under emulation with zero, one, and unchanged
EBX responses; all formatting and comparison checks passed, with zero CMOS
data writes. Source is `dos/C3CHECK.ASM`; build with NASM:

```sh
nasm -f bin -o dos/C3CHECK.COM dos/C3CHECK.ASM
```

The BIOS-input BL differs from CMOS35&3 for live signature 068A, confirming
the identified type disagreement. Other early fallback conditions still exist,
including the live signature comparison, CPU-change flag, and boot-attempt
counter; the targeted fix should not disable those safeguards indiscriminately.

The relevant fix is consistent Centaur handling in the early
CPU-type check and later identification. A vendor-aware change should retain
the real signature comparison and intentional recovery paths. Forcing an FSB
at the later clock-apply hook does not fix this early reset of CPU settings.
The v15 body patch leaves the early raw-ROM comparison unchanged, so it is not
a root-cause fix for this confirmed mismatch.
No replacement ROM has been generated by this diagnostic work.

Input SHA-256:

```text
BH32_SP.BIN:
393d9030c662cbcc5d4ea246f43ef0592f2bb6db4309b25cbadacebe5396b42d
BH32_C3_v14_trace.BIN:
18435ff46374bab49490cdd993d58fdcf2f09c0acfff1edf16987cfd6b6a8cb3
body_v14_patched.bin:
2a42e83c7b97e4fe8f94b6af7459c2470cacab09b42aa8358adc25e28abded50
C3CHECK.COM:
8ad35989fc3b9c28653aa2e4866aa3e4c8db6f43c0052618be9ff1b3367af97b
```
