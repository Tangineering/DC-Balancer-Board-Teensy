// share_controller.h — Youla-H robust power-share controller runtime.
//
// Replaces PI_Controller_Power() in the droop share loop (powerBalance()) when
// USE_YOULA_SHARE_CONTROLLER is 1. Design provenance: H-infinity mixed-sensitivity
// synthesis + Youla-H T(0)=1 gain adjustment on the plant model of
// controller_design/system_model.md; full derivation and validation record in
// controller_design/controller_synthesis.md. Coefficients are GENERATED into
// share_controller_coeffs.h by controller_design/synthesize_controller.py — never
// hand-edit them; regenerate after bench calibration.
//
// Structure (mirrors the Python DiscreteController reference implementation,
// which the host-native tests replay against generated reference vectors):
//
//   u = r0 + R(z)·e + I(z)·e,   r0 = 0.5 (balanced-split operating point)
//     R(z): SHARE_CTRL_NSOS biquad sections, Direct Form II transposed, float
//     I(z): trapezoidal (Tustin) integrator, gain SHARE_CTRL_KI
//
// Anti-windup: back-calculation on the output clamp — when u would leave
// [rmin, rmax] the integrator absorbs exactly the excess, so u sits on the rail
// and resumes moving the instant the error reverses. The biquad states are NOT
// clamped (R(z) is stable; only the integrator can wind up). Same idiom as the
// legacy PI's clamp, extended to the dynamic controller.
//
// Update cadence: shareControllerStep() advances the difference equations and
// must be called exactly once per SHARE_CTRL_TS_US. The .ino wrapper
// youlaController_Power() does the gating and holds the output between updates
// (this ZOH latency is part of the design plant — system_model.md §6c).

#pragma once

#include "share_controller_coeffs.h"

#define SHARE_CTRL_R0 0.5f   // output operating point: balanced split

// Controller state — file-scope so the host-native tests can reset it
// deterministically between cases (same pattern as pi_power_accum).
static float shareCtrl_sosState[SHARE_CTRL_NSOS][2];
static float shareCtrl_integ     = 0.0f;
static float shareCtrl_eprev     = 0.0f;
static float shareCtrl_alphaFilt = 0.5f;   // measured-share prefilter state

static inline void shareControllerReset() {
    for (int i = 0; i < SHARE_CTRL_NSOS; i++) {
        shareCtrl_sosState[i][0] = 0.0f;
        shareCtrl_sosState[i][1] = 0.0f;
    }
    shareCtrl_integ     = 0.0f;
    shareCtrl_eprev     = 0.0f;
    shareCtrl_alphaFilt = 0.5f;
}

// Measured-share prefilter (200 Hz one-pole, part of the design plant). Call once
// per Ts tick with the raw measured share; returns the filtered value used for the
// error. Filters the MEASUREMENT only — the setpoint stays unfiltered, so EMS steps
// are not smoothed by the sensor filter.
static inline float shareControllerFilterMeas(float alphaRaw) {
    shareCtrl_alphaFilt += (1.0f - SHARE_CTRL_MEAS_FILT_A) * (alphaRaw - shareCtrl_alphaFilt);
    return shareCtrl_alphaFilt;
}

// One controller update (call once per SHARE_CTRL_TS_US tick).
//   e     — share error (setpoint − measured), dimensionless
//   rmin/rmax — droop-ratio authority limits (DROOP_R_MIN/MAX in the .ino)
// Returns the clamped droop ratio r.
static inline float shareControllerStep(float e, float rmin, float rmax) {
    // R(z): cascade of DF2T biquads
    float x = e;
    for (int i = 0; i < SHARE_CTRL_NSOS; i++) {
        const float *c = SHARE_CTRL_SOS[i];   // b0 b1 b2 a1 a2
        float y = c[0]*x + shareCtrl_sosState[i][0];
        shareCtrl_sosState[i][0] = c[1]*x - c[3]*y + shareCtrl_sosState[i][1];
        shareCtrl_sosState[i][1] = c[2]*x - c[4]*y;
        x = y;
    }
    // I(z): trapezoidal integrator
    const float Ts = SHARE_CTRL_TS_US * 1e-6f;
    float integNew = shareCtrl_integ + SHARE_CTRL_KI * Ts * 0.5f * (e + shareCtrl_eprev);
    float u = SHARE_CTRL_R0 + x + integNew;
    // back-calculation anti-windup: integrator absorbs the clamp excess
    if (u > rmax)      { integNew -= (u - rmax); u = rmax; }
    else if (u < rmin) { integNew += (rmin - u); u = rmin; }
    shareCtrl_integ = integNew;
    shareCtrl_eprev = e;
    return u;
}
