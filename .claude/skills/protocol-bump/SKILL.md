---
name: protocol-bump
description: Safely change the UDP telemetry or command packet layout — recompute byte count and checksum span, bump the protocol version, update PLAN.md §6b and the tests, and flag the Pi bridge lockstep. Use this whenever a change adds, removes, resizes, or reorders any field in the telemetry struct or the 22-byte command packet, even if the change looks like "just one byte" — the Pi bridge parses fixed offsets and silently desynchronizes.
---

# Telemetry / command protocol change

The Raspberry Pi bridge parses the packets at **fixed byte offsets**. Any layout change that
isn't versioned and mirrored on the Pi side produces silently garbled telemetry, which on
this board means wrong voltages/currents feeding the EMS. That's why "don't silently change
the layout" is a standing rule — this skill is the non-silent way.

Current state (verify against the code, not this file, if they disagree): telemetry is
**v4, 58 bytes, XOR checksum over bytes 1–56**, sync byte first; layout table lives in
**PLAN.md §6b**. Command packet is 22 bytes.

## Checklist — do every item, in order

1. **Design the layout change.** Prefer appending fields over inserting; note that v4
   deliberately reinstated `charger_status` at its *historic* offset 51, so offsets are not
   free to shuffle without a reason. Write the new full offset table before touching code.
2. **Edit the struct/packing code** in `teensy_controller.ino`. Keep packing explicit
   (byte-by-byte offsets), matching the existing style.
3. **Recompute the total byte count** — by summing the field sizes yourself, not by trusting
   the diff. Update the length constant and anywhere the length is asserted.
4. **Recompute the checksum span.** The XOR runs from byte 1 through the last payload byte
   (currently 1–56 for 58 bytes: sync excluded, checksum byte excluded). A new length moves
   the span's end; update it in both the packer and any parser.
5. **Bump the protocol version constant.** Never reuse a version number for a different
   layout, even during development.
6. **Update the tests.** `test/test_main.cpp` has telemetry-packing tests asserting the byte
   count, checksum, and field offsets — update them to the new layout (they should fail
   before this step; if they didn't, the coverage has a hole worth fixing).
7. **Update PLAN.md §6b** with the new offset table and version, and note what changed.
   If CLAUDE.md or the memory index states the version/length, update those too.
8. **Run the `test` skill** — both builds must pass.
9. **Report the Pi-bridge delta explicitly.** End with a summary the user can hand to the
   Pi side: old version → new version, old length → new length, every offset that moved,
   and new/removed fields with their encodings. The firmware and Pi bridge must be updated
   in lockstep — say so in the report; do not let it be implied.

For **command packet** changes, the same applies in reverse (the Teensy is the parser):
update the parse offsets, the length check, the version handling, and the command-parsing
tests. Note the standing quirk: `droop_enable` is parsed and discarded (reserved) — if the
change touches it, resolve that explicitly rather than leaving it ambiguous.
