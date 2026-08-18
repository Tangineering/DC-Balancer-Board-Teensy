// drive_controller.h — Youla-H robust DRIVE (velocity) controller runtime.
//
// Replaces PI_Controller_Motor() on the velocity path (motorControl()) when
// USE_YOULA_DRIVE_CONTROLLER is 1. Design provenance: H-infinity mixed-sensitivity
// synthesis + Youla-H T(0)=1 DC rescale on the drive channel G22 of
// controller_design_MIMO/plant_mimo.py (plant CALIBRATED 2026-08-16,
// controller_design_MIMO/calibration/motor_id_20260815.md); design record in
// controller_design_MIMO/mimo_synthesis.md and drive_siso_metrics.txt. Coefficients are
// GENERATED into drive_controller_coeffs.h by
// controller_design_MIMO/synthesize_drive_siso.py — never hand-edit them; regenerate
// after bench calibration or after any change to the motor-current clamp.
//
// Signal chain (units matter — this is the one thing that differs structurally from the
// legacy PI path):
//
//   e = v_setpoint − v_actual  [m/s]   →   Gc(z)   →   i_cmd  [A]
//
// The controller outputs AMPS DIRECTLY. There is no division by motorConstant on this
// path: motorConstant existed only to convert the PI's notional torque output into a
// current, and the synthesis plant already maps di_cmd [A] → dv [m/s]. Dividing here
// would rescale the loop gain by 1/motorConstant and invalidate every synthesis gate.
//
// Structure — Hanus self-conditioned state-space form, NOT a biquad cascade:
//
//   u_unsat   = Σ_j CD[0][j]·x[j] + DD·e
//   u         = clamp(u_unsat, DRIVE_CTRL_I_MIN, DRIVE_CTRL_I_MAX)      [A]
//   x_next[i] = Σ_j AC[i][j]·x[j] + BD[i][0]·(u / DD)
//
// Anti-windup: the CLAMPED u drives the state update — that IS the anti-windup, and it
// conditions the FULL controller state, not just the integrator. Do NOT "improve" this
// into share_controller.h's integrator-only back-calculation: the non-integral branch R
// has a low-frequency gain of 745.5 A/(m/s), so against the ±12 A clamp its lag states
// saturate and wind up independently of the integrator (measured: a −0.48 m/s standing
// error and a 22 mm/s limit cycle on the 0→2 m/s step). The full rationale, including the
// step size at which integrator-only AW starts to fail, is in the header block of
// drive_controller_coeffs.h.
//
// Source: Hanus, Kinnaert & Henrotte, "Conditioning Technique, a General Anti-windup and
// Bumpless Transfer Method," Automatica 23(6):729-739, 1987
// (references/Conditioning_Technique_A_General_Anti-Windup_and_B.pdf). This implementation
// is the paper's SELF-CONDITIONED linear form, eqs. (19a)/(20a), specialized to the
// one-DOF error-driven SISO case (input e = w − y makes the paper's y-feedthrough term
// B·D⁻¹·F − E vanish identically). Reconciled against the paper 2026-08-17; three known,
// deliberate departures from its assumptions:
//   1. u^r is a clamp MODEL, not the measured actual control the paper calls for. The
//      static_assert pairing DRIVE_CTRL_I_MAX to MOTOR_I_CMD_MAX makes the model exact for
//      the firmware's own limit, but VESC-side limits (Battery Current Max/Regen Max) and
//      the ML0151 ~428 ms post-reversal dead window are invisible to it — while they bind,
//      the states condition against current that never flowed and windup can transiently
//      return. Documented in docs/VESC_MOTOR_INTEGRATION.md ("invisible to the drive
//      controller's anti-windup"). Do not close this by feeding back VESC-reported current
//      without a synthesis round (UART latency + noise into a marginally-stable recursion).
//   2. The paper's stability condition 3 requires A − B·D⁻¹·C (our AC) asymptotically
//      stable; ours is only MARGINALLY stable (exact-integrator structure). The synthesis
//      substitutes an empirical gate (saturated-vs-linear excursion, windup_excess) and the
//      double state below for the theorem.
//   3. Mode transitions use hard resets (driveControllerReset()) instead of the paper's
//      converged-initialization bumpless transfer — determinism over bumplessness.
// The biproperness requirement (paper eq. 12) is why DD ≠ 0 is load-bearing: at DD → 0 the
// u/DD conditioning becomes impossible, and the synthesis emitter owns that guarantee.
//
// Arithmetic precision: the state vector is DOUBLE, deliberately. The realization carries
// an exact integrator (an eigenvalue at 1) plus a second mode at ~0.9999 alongside CD
// entries of order 50, so perturbations are integrated rather than damped. A float32 state
// recursion was MEASURED to diverge by ~1.4e-2 A at rail release on the saturated regen
// episode (validate_drive_siso.py check 4) — not a slow accumulation that a shorter run
// bounds. The Teensy 4.1 FPU runs the ~35 double MACs per tick (5 for the output, 30 for the
// 5x5 state update) at 500 Hz with enormous
// margin. The COEFFICIENTS stay the shipped float32 values (the reference replay vectors
// were generated from exactly those roundings); they are promoted to double per operation.
//
// Update cadence: driveControllerStep() advances the difference equations and must be
// called exactly once per DRIVE_CTRL_TS_US. The .ino wrapper youlaController_Drive() does
// the gating and holds the output between updates (the ZOH + VESC UART latency is part of
// the design plant).

#pragma once

#include "drive_controller_coeffs.h"

// Controller state — file-scope so the host-native tests can reset it deterministically
// between cases (same pattern as pi_motor_accum and the share controller's states).
// DOUBLE by design — see the precision note above.
static double driveCtrl_x[DRIVE_CTRL_NSTATES];

// Observability only (fw v11 / BLG record format v5): the PRE-clamp output u of the most
// recent driveControllerStep(). Written by the step, read by nothing in the control path —
// logSampleTick() copies it into the record so a decoded run shows how far the law WANTED to
// drive versus what the ±MOTOR_I_CMD_MAX clamp allowed, which is the only way to see the
// Hanus conditioning working (or a rail episode) from the log alone.
//
// It is a HELD value: the step runs at DRIVE_CTRL_TS_US (500 Hz) while logSampleTick() samples
// at 1 kHz, so PAIRS OF IDENTICAL SAMPLES per controller tick are EXPECTED in the log — the
// same zero-order hold the wrapper applies to driveCtrl_heldOut. Never recompute it in the
// logger: recomputing would evaluate the output equation against a state that has already been
// advanced, and would not be the value the clamp actually acted on.
static float driveCtrl_uUnsat = 0.0f;

static inline void driveControllerReset() {
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++) driveCtrl_x[i] = 0.0;
    driveCtrl_uUnsat = 0.0f;
}

// One controller update (call once per DRIVE_CTRL_TS_US tick).
//   e — velocity error (v_setpoint − v_actual), m/s
// Returns the clamped motor current command in AMPS.
static inline float driveControllerStep(float e) {
    // Output first: u depends on the CURRENT state, and the state update below needs the
    // clamped u. Accumulate in double — see the precision note.
    double u = (double)DRIVE_CTRL_DD * (double)e;
    for (int j = 0; j < DRIVE_CTRL_NSTATES; j++)
        u += (double)DRIVE_CTRL_CD[0][j] * driveCtrl_x[j];

    // Capture the PRE-clamp output for the bench log (observability only — see the
    // driveCtrl_uUnsat declaration). Deliberately BEFORE the clamp below and not used by any
    // line that follows: the update law itself is untouched by this round.
    driveCtrl_uUnsat = (float)u;

    // Actuator clamp. DRIVE_CTRL_I_MAX is synthesized to equal the firmware's
    // MOTOR_I_CMD_MAX, so the clamp the controller conditions against is the SAME limit
    // commandMotorCurrent() enforces downstream — that equality is what makes the Hanus
    // conditioning correct rather than merely plausible. Changing MOTOR_I_CMD_MAX requires
    // re-synthesis (synthesize_drive_siso.py I_CLAMP), not just an edit here.
    const double uMin = (double)DRIVE_CTRL_I_MIN;
    const double uMax = (double)DRIVE_CTRL_I_MAX;
    if (u > uMax)      u = uMax;
    else if (u < uMin) u = uMin;

    // Self-conditioned state update, driven by the CLAMPED u. While unsaturated this is
    // algebraically identical to x_next = AD·x + BD·e; once clamped it is what prevents
    // windup of every state, integrator and lag alike.
    const double uOverD = u / (double)DRIVE_CTRL_DD;
    double xNext[DRIVE_CTRL_NSTATES];
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++) {
        double acc = (double)DRIVE_CTRL_BD[i][0] * uOverD;
        for (int j = 0; j < DRIVE_CTRL_NSTATES; j++)
            acc += (double)DRIVE_CTRL_AC[i][j] * driveCtrl_x[j];
        xNext[i] = acc;
    }
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++) driveCtrl_x[i] = xNext[i];

    return (float)u;
}
