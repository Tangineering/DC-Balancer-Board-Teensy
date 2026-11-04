# Drive-cycle raw data — provenance

This directory holds drive-cycle source data committed **verbatim**, exactly as
fetched. Nothing here is edited, reformatted, or re-saved. Every derived
artifact in the repository is produced from these bytes by a generator that
verifies the recorded sha256 first.

## ftpcol.txt — EPA FTP-75 (Federal Test Procedure) speed trace

| Field | Value |
|---|---|
| Source URL | `https://www.epa.gov/sites/default/files/2015-10/ftpcol.txt` |
| Fetch date | 2026-08-31 |
| Size | 17 689 bytes |
| sha256 | `9791a45a7fb2415de0bf01948b96e8aeff499bfd63744a8c6ca781ae88826f8a` |
| Line endings | CRLF, preserved by `references/drive_cycles/.gitattributes` (`* -text`) |
| Consumer | `tools/gen_ftp75_profile.py` -> `tools/ftp75_profile.py` |

**How the bytes are preserved.** This repository is developed with
`core.autocrlf=true`, which would normalize CRLF to LF in the object store and
hand back an LF file (15 812 bytes, a different sha256) on any checkout that does
not convert back — Linux, macOS, CI, or a clone with `autocrlf=false`. The
generator verifies the recorded sha256 before it will emit anything, so such a
checkout does not silently produce a wrong table; it refuses to run. The
directory-scoped `.gitattributes` in this folder sets `* -text`, which disables
end-of-line conversion here and makes "preserved" a mechanism rather than a
convention. Verify with `git check-attr text -- references/drive_cycles/ftpcol.txt`
(expected: `text: unset`).

### File structure

Two header lines, then 1875 tab-delimited data rows:

```
FTPCOL.TXT<TAB>Federal Test Procedure
Test Time, secs Target Speed, mph
0<TAB>0
1<TAB>0
...
1874<TAB>0
```

Column 1 is test time in seconds, column 2 is target vehicle speed in miles per
hour. The series is 1 Hz and contiguous: row *i* carries `t = i`.

Note that the second header line separates its two column titles with spaces,
not a tab. Only the data rows are tab-delimited, which is why the parser skips
exactly two lines rather than splitting the header.

### The 10-minute soak is NOT in this file

The FTP-75 procedure is Phase 1 (cold transient, t = 0-505 s), Phase 2
(stabilized, t = 505-1372 s), a **10-minute engine-off soak**, then Phase 3 (a
hot repeat of Phase 1). The soak is a procedural pause, not a speed record, so
the file's `t` runs continuously from 0 to 1874 with no gap and no marker.
Any phase or segment must therefore be taken by **time slice**, and a reader who
assumes `t` includes the soak will be 600 s out for the whole of Phase 3.

### Peak

The maximum speed in the file is 56.7 mph, first reached at t = 240 s (held
through t = 241 s). This is the scaling anchor `tools/gen_ftp75_profile.py`
uses.

### What this repository takes from it

`tools/gen_ftp75_profile.py` slices **t = 0..340 s inclusive** — the segment of
the scaled-vehicle study
`references/Systemic_Scaling_of_Powertrain_Models_with_Youla_Driver_Control.pdf`
(operator direction, 2026-08-31). The bound matches the published study; it is
not a trim of Phase 1 chosen for run length, and it must not be moved to 505 s
without the study moving first. The 56.7 mph peak at t = 240 s lies inside the
segment, so the scaling anchor is unaffected by the choice.

**t = 340 falls in a native idle segment — the trace reads 0 mph continuously
from t = 333 (after a decel 8 -> 4.7 -> 1.4 -> 0 mph over t = 330..333) — so the
segment ends at rest on its own and no synthetic ramp-down tail is added.** The
generator asserts this tail is at rest and refuses to emit otherwise.

The slice is then scaled by one constant, `3.0 / 56.7` m/s per mph, so the
cycle peak lands at 3.0 m/s of rig flywheel surface speed, and shifted by +5 s
so the cycle starts 5 s into the HIL run. No dynamic-similarity claim is made
or implied by the scaling: it is a range map onto the speeds this bench has
actually driven.

### Re-fetching

If the EPA file is re-fetched and its digest differs, the generator refuses to
run. Update the digest here and in `gen_ftp75_profile.py`'s `RAW_SHA256`
together, in one change, and regenerate — never bypass the check.

## Pi drive-cycle traces (PhD student, imported 2026-11-04)

Four speed traces that the Pi's `drive_cycle_node` plays on the bench. They are
copied byte-for-byte from `phd/siddhesh-2026-11-03` (`64fb553`, student folder
`scale_car/Documentation/Drive Cycles/`). Each is LF, a `time_s,v_mps` header
plus one row per sample, and is covered by this directory's `* -text`. The
student did not document how they were generated. The trimming and scaling
are not verified here, and no repo generator consumes them yet.

| File | Bytes | sha256 | Samples | End time | Peak v | Notes |
|---|---:|---|---:|---:|---:|---|
| `RegenTest_decel_sweep.csv` | 24 589 | `50c5bad1ae58cebc6a4b154ca7a4bac12db760e5f72511e415c56eb83f6548b9` | 1834 | 183.3 s | 3.5 | Regen deceleration sweep, ends at rest |
| `RegenTest_v2_lowspeed.csv` | 20 137 | `bf5f51910d873f463e1d61d1712324c62a97f6e521cb1a4f1a91c6bfaa86b5fd` | 1516 | 151.5 s | 2.0 | Low-speed regen test, ends at rest |
| `UDDS_trimmed_3.5mps.csv` | 4 245 | `624ef94953b301859ca00740a117797d1d4001ce22bfa75c9a04ba48f187b718` | 334 | 333 s | 3.5 | UDDS slice scaled to a 3.5 m/s peak, ends at rest |
| `UDDS_trimmed_to_idle.csv` | 3 225 | `2f437aa8add37df98ac0084e9291667f962181e1c62c2d2c81774413a7bc2bdc` | 334 | 333 s | 5 | Integer speeds; **the last row is `333,5`, so it does not end at rest despite the name**. Probably an earlier, unscaled or differently scaled version of the 3.5 m/s file (unverified) |
