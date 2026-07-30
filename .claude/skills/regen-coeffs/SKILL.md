---
name: regen-coeffs
description: Regenerate the power-share Youla-H controller coefficients after bench calibration or a plant-model change — the full recalibration loop with synthesis gates, full-order validation, and firmware replay tests in the correct order. Use this whenever a value in controller_design/system_model.md changes (ΔV0, τr, Td, k_d, K_DROOP, divider or sense constants), when the user says "regenerate the controller", "recalibrate", "new coefficients", or when share_controller_coeffs.h would otherwise be edited — that file is generated and must never be hand-edited.
---

# Regenerate the power-share controller coefficients

`teensy_controller/share_controller_coeffs.h` is **generated** by
`controller_design/synthesize_controller.py`. Hand-editing it desynchronizes the firmware
from the design record and the replay tests — the only valid way to change it is this loop.
The authoritative recalibration procedure is `controller_design/controller_synthesis.md` §7;
read it before running if anything below seems out of date.

## Order matters

The full-order validation model re-parses the generated coefficients header, and the
firmware replay tests compare the C++ biquads against Python-generated reference vectors —
so synthesis must run first, validation and tests last.

1. **Update the plant parameters.** `controller_design/system_model.md` is the parameter
   source of truth — record the new measured value there (with the bench source/date), then
   mirror it into the synthesis script's parameter block. Resolve any related
   `TODO(calibrate)` markers. Never change a number in the script without updating
   `system_model.md`, or the thesis record drifts from the shipped controller.

2. **Environment: uv only.** System pythons on this machine are externally managed — do not
   use pip or pacman. From `controller_design/`:

   ```bash
   uv venv && uv pip install numpy scipy matplotlib
   ```

   (Reuse the existing `.venv` if present.)

3. **Run the synthesis:** `uv run python synthesize_controller.py`. This regenerates
   `share_controller_coeffs.h` and the Python reference vectors, and writes
   `synthesis_metrics.txt`.

4. **Check the a-posteriori gates — do not skip.** Every synthesized controller is
   gate-checked; a run that regenerates the header but fails a gate must not ship. Compare
   against the previous baseline (γ = 0.686, all 60 plant-corner closed loops stable, delay
   margin 11.7 ms, worst-corner discrete ‖S‖∞ 1.87, T(0) = 1 exact):
   - ‖Tzw‖∞ ≤ γ holds
   - all plant-corner closed loops stable
   - delay margin and discrete ‖S‖∞ not meaningfully degraded
   If a gate fails or a metric regresses sharply, stop and report — the fix is in the
   weights/model, not in overriding the gate.

5. **Run the full-order validation LAST:** `uv run python tps61288_full_model.py`. It
   re-parses the fresh coefficients header and checks the 432-point envelope (baseline:
   432/432 stable, worst ‖S‖∞ 1.24, in-band deviation < 6%). Run any `validate_model.py`
   step per `controller_synthesis.md` §7.

6. **Rebuild and run the firmware tests** via the `test` skill (both builds). The replay
   tests exercise the C++ controller against the regenerated reference vectors, including
   the saturated episode — a mismatch here means the header and vectors are out of sync
   (usually a partial regeneration; rerun step 3).

7. **Report** the metric deltas (old → new γ, ‖S‖∞, margins), which parameters changed and
   why, and confirm `system_model.md`, the header, and the tests all moved together. If
   MATLAB cross-check files (`droop_plant.m`, `full_order_model.m`) are stale relative to a
   parameter change, flag it rather than silently leaving them behind.
