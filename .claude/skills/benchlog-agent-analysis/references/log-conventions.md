# BLG data + log conventions (agent brief block)

Single source of truth for the anti-artifact rules pasted into (or Read by) every
bench-log analysis agent. Orchestrator: when a round discovers a new trap, add it HERE
(Stage 4 of the skill), not to individual prompt text. Verify the column schemas against
`tools/decode_benchlog.py` (`CSV_HEADER*` constants / `RECORD_INFO`) before relying on
them — the decoder is the authority.

## CSV column schema, by BLG format version

The per-file authority is `DecodeResult.csv_header`; these are the current layouts:

- **v1/v2** (52 B records):
  `t_us, share_sp, share_act, v_sp, v_act, I_fc, I_batt, gFC, gBT, V_bus, I_cmd,
  fault_flags, ps_phase, dc_phase, trap_phase, flags`
- **v3/v4** (68 B): v1/v2 + `V_fc, V_batt, V_chg, V_rgn` (inserted after `I_cmd`).
- **v5** (76 B): v3/v4 + `u_unsat, drive_x0` (inserted after `V_rgn`).

Header carries `fw_version` from format v2 on (`decode_report.txt` banner line; v1 =
"pre-versioning"). v4+ headers may carry `profile_amp`/`profile_b` when their valid bits
are set. Trailer `close_reason`: 1=complete, 2=stop, 3=X, 4=Q, 5=fault, 6=io_error.
A truncated log (MCU stop / power loss) has **no trailer** — `close_reason`/`error_code`
must be inferred from the last records and flagged as inferred.

## Timing

- `t_us` is ABSOLUTE microseconds — subtract `t[0]` before anything else.
- Actual sample rate is ~861–885 Hz, **not** the nominal 1 kHz (median interval
  ~1.13–1.16 ms). Never compute Hz, settling times, or FFT axes on the nominal rate;
  measure `median(diff(t_us))` per log.
- `missed_periods` in the decode report counts 1 kHz ticks that appear not to have run.

## Signal semantics and reconstruction

- Share = FC fraction: `share_act = I_fc / (I_fc + I_batt)`; droop command
  `r_cmd = gBT / (gFC + gBT)` — NaN (honest gap), not 0, when `gFC = gBT = 0`
  (early-run window before the governor engages).
- The LOGGED `share_sp` is the RAW commanded setpoint; the governor clip is internal.
  Apparent "tracking error" at low current is governor action, not a bug — reconstruct
  the effective setpoint (clip against the conduction floor using an EMA of `I_tot`) and
  score tracking against that.
- `v_act` is flywheel SURFACE speed (m/s); `v_sp` and profile commands share that scale.
  **Encoder geometry is PER-LOG — read `fw_version` before converting counts to metres:**
  - fw ≤ 17: 120 slots, **240 counts/rev**, pitch **3.990 mm** (2π·0.0762/120).
  - fw ≥ 18: 90 slots, **180 counts/rev**, pitch **5.3198 mm** (2π·0.0762/90).

  The flywheel encoder DISC was physically replaced on 2026-08-25 (operator hand count:
  90 slots, verified at 180 `encoderPos` counts/rev); the flywheel radius r = 0.0762 m and
  the surface-speed convention did NOT change. So pre-v18 and v18+ logs were taken on
  **physically different wheels**, and a cross-wheel `v_act` comparison is
  physical-configuration-dependent: identical motion reads 4/3× higher on v18+ than on
  v12–v17. Using the wrong pitch mis-scales the `encoder_pos` truth velocity by exactly
  4/3, which is the same size as the artifacts the scale audit exists to catch — so state
  which pitch you used in any encoder finding. (`tools/benchlog_analysis/figures.py`
  selects the pitch from the log's own `fw_version`; a hand-rolled analysis must do the
  same.) Note there have now been TWO wheels in the record's history, plus the fw v7→v8
  slot-count transcription fix, so three distinct `v_act` scale eras exist.

  **LOG-NUMBER BOUNDARY — `fw_version` is only a PROXY for the physical disc.** The two
  are correlated, not identical: the firmware constant changed in the same session as the
  swap, but a log taken on one wheel with the other wheel's firmware still flashed would be
  mis-scaled by 4/3 with nothing in the header to reveal it. The boundary on record:

  - **`ML0183` is the LAST log taken on the 120-slot thin-tooth wheel.** `ML0182` and
    `ML0183` are pre-swap (operator-confirmed), so the `fw ≤ 17 → 3.990 mm` heuristic is
    correct for them and no relabeling is needed.
  - Every log numbered **above `ML0183`** should be on the 90-slot wheel. Check its
    `fw_version` anyway.
  - A hypothetical `fw ≤ 17` log taken on the **90-slot** wheel would be mis-scaled by the
    heuristic. None is known to exist. If one turns up, use the explicit override —
    `analysis_config.json`'s `"_encoder_pitch_m"` (metres), which wins over the
    `fw_version` heuristic in `figures.py` — and **state the override in the finding**.
  - The `encoder_diagnostics` figure stamps the pitch it used and where that value came
    from in its bottom-right corner; a `FALLBACK` source (no `fw_version` parsed) is
    printed in the warning colour and means the wheel was ASSUMED, not read.

  fw v12+ uses the edge-period estimator (timer-fine quantization,
  delay ≈ (N+1)·pitch/(2v) — which grew by 4/3 at v18 with the pitch); fw ≤ v11 used a
  ~113 ms boxcar with a 0.0177 m/s quantization ladder. A ladder in a v12+ trace is a
  smoking gun that the old estimator is somehow active.
- Phase bytes (`ps_phase`, `dc_phase`, `trap_phase`) are **0-based**. Hold windows are
  better defined by signal level (e.g. `I_cmd >= 5.99` for a 6 A hold) than phase byte.
- `flags`: bit2 = closed-loop mode, bit3 = closed-loop-has-run, bit4 = command from the
  Youla drive controller, bit5 = share loop is the Youla build (v5-era bits — records are
  law-self-identifying), bit6 = HIL provenance (fw v21), **bit7 = a source current
  ceiling was binding on this tick (fw v26)**. Bit 7 is decoded as the helper column
  `share_ceiling` by `tools/decode_benchlog.py`; it is a spare bit in an existing byte,
  so the record size and BLG format v7 are unchanged. It is the ONLY bench-log evidence
  that the clamp acted: the clamp is a reference-side bound, so a decoded run cannot
  distinguish "the governor held the fuel cell at 1.25 A" from "the load happened to
  stop there" out of the logged currents alone.

## v5 drive-controller fields (`u_unsat`, `drive_x0`)

- `u_unsat` is the drive controller's PRE-clamp output; `drive_x0` is the exact-
  integrator state x[0]. The controller runs at 500 Hz while logging is ~1 kHz, so both
  appear in **held pairs** — duplicated consecutive values are by design, not a defect.
- During a rail episode (|I_cmd| = 12 A): `u_unsat` hugging the rail = Hanus conditioning
  working; `u_unsat` diverging far beyond ±12 A = windup. Report rail-episode count,
  worst excursion, and release behavior.
- Under a `USE_YOULA_DRIVE_CONTROLLER=0` build the same fields carry the PI's pre-clamp
  command and accumulator (check flags bit4 before interpreting).
- Clamp dither (rapid transitions across ±12 A) during hard regen is expected behavior,
  not a fault (~50 mA-scale replay tolerance is genuine controller dithering).

## Statistics hygiene

- `share_act` is ill-conditioned near zero current — gate ALL share statistics on
  `I_tot > 0.3 A`.
- Event counters need hysteresis: e.g. dropout when minority current < 0.02 A while
  `I_tot > 0.3 A`, count an event only on re-conduction above 0.05 A. Naive threshold
  counters fabricate hundreds of phantom events from ADC noise.
- Do not interpolate across NaN gaps; a gap is data.
- Unsettled plateaus (visible creep) are not settled values — fit an exponential to the
  hold and report the extrapolated settle, or declare the datapoint unusable.

## Provenance and comparability

- Read `fw_version` from each log's own header; never assume a batch is homogeneous.
- Traces across fw versions can be DIFFERENT CONTROL LAWS (v11 vs v12 vs v13 vs v14)
  even where `v_act` scale is comparable; v7-and-earlier `v_act` is 2× (slot-count
  error) and pre-v12 is boxcar-filtered. State the reference trace's law and estimator
  in any cross-run comparison.
- Never take time off a Serial Plotter screenshot — its x-axis is SAMPLE COUNT, not
  seconds (the `'L'` stream runs at ~50 Hz with jitter). Use BLG `t_us` or a
  timestamped capture.
- Hardware bodges outrun documentation: current fitted values include encoder pull-ups
  2.2 kΩ (not the designed 4.7 kΩ) and RC-BT 61.2 kΩ. Check the CLAUDE.md bodge records
  before citing a designed constant as fitted.

## Environment (paste into every brief)

- Interpreter: `.venv_benchlog/Scripts/python.exe` at repo root. numpy and matplotlib
  are available; **pandas is NOT**.
- Read-only except scratch scripts in a temp dir — never write into the repo or `logs/`;
  never touch any `analysis_config.json`.
- The Read tool renders PNGs — read the figures for shape, but derive all numbers from
  the CSV.

## Encoder scale-basin detection (pre-fw-v15 logs; established logs 153-162 round)

- Any log whose header reads fw_version <= 14 may carry the fw v13 estimator poison
  basin: v_act reads ~2x true (fast T/2 basin, common) or ~0.5x true (slow 2T basin).
  In closed loop the error is INVISIBLE in v_act — the controller regulates the
  corrupted signal onto the setpoint — so v_act-discontinuity sweeps find only the
  ESCAPES (x0.5 or x2 sample-level steps), not the locked dwell.
- The standard discriminator is the RAIL-ACCELERATION BOUND, which is independent of
  v_act scale: at |I_cmd| = 12 A, a_true <= (12*0.7538 - 2.00 - 0.534*v_true)/3.5
  ~= 2.0 m/s^2. A sustained (>=0.25 s) rail window whose fitted dv_act/dt is ~2x the
  bound means v_act is 2x true. Apply it to every sustained rail episode; a windowed
  ODE inversion (solve the scale s with a_meas/s = f(v_meas/s, I)) corroborates.
- Secondary tells: hold current fits the drag law at ratio ~0.86-0.91 on the face
  axis but ~0.96-1.04 with v halved; bus input power implying a different speed than
  v_act; escapes clustering at drive removal or large current changes.
- Basin entry is typically seeded during low-speed breakaway (spurious edges,
  un-Schmitted front end); escapes occur at speed. Segment every pre-v15 log into
  scale regimes BEFORE fitting anything; never mix regimes in one drag/gain fit.

## fw v15/v16 rounding basin + BLG v6 conventions (established logs 164-180 round)

- **v6 schema** (92 B): v5 + `encoder_pos, enc_period_ref_us, enc_multi_pitch_count,
  enc_spurious_drop_count` (after `drive_x0`). `encoder_pos` is GROUND TRUTH
  (truth v = dpos x (pitch/2) / dt, with the pitch taken from the log's own fw_version —
  1.995 mm/count on fw ≤ 17's 240 counts/rev, **2.6599 mm/count on fw ≥ 18's 180
  counts/rev**; see the encoder-geometry note above). `enc_period_ref_us` is a LEVEL —
  never difference it. The two counters are cumulative; a NEGATIVE diff means
  `encoderVelReset()` fired, not wrap.
- **The x2 basin persists on fw v15/v16**, by a different mechanism than pre-v15: a
  spurious mid-pitch A-edge carries dpos = 1 and `(|dpos|+1)>>1` rounds it up to a
  full pitch — a self-consistent T/2 lock the dpos count is structurally blind to
  (confirmed logs 164-180: accepted-interval rate exactly 2.00/true slot, ref/T =
  0.500). Seeded at breakaway (~0.08-0.24 m/s); escape is speed-gated (~1.0-1.6 m/s
  true), so runs cruising below the escape speed stay locked whole-run. Segment every
  pre-Schmitt log by the encoder_pos scale audit before fitting.
- **encoder_diagnostics panel 2 is self-confirming** — it plots pitch/ref against
  v_act, which are the same corrupted quantity; only panel 1 (encoder_pos truth
  overlay) is a valid basin check until the figure is fixed.
- **Counter-rate normalization trap:** the CSV `t_us` axis is session-absolute; divide
  counter sums by RUN DURATION (t[-1]-t[0]), never by t[-1] (this error produced fake
  8-320/s rates and a fake declining trend in one scout pass). True pre-Schmitt
  baseline: ~480-560 spurious drops/s at 1.9-3.0 m/s cruise (~0.7-1.2 per true pitch),
  20-30 per pitch at breakaway; multi-pitch counter ~0 (it is structurally blind to
  the dominant miss mode — it does NOT exonerate missed edges).
- **A manual 'V' run never steps the share loop** unless `powerBalanceLive` was armed
  (State-98 share-setpoint command): gains freeze and flags bits 2/3 stay 0 regardless
  of Itot. Profile runs ('T'/'D'/'Y'/'W') call powerBalanceGated() unconditionally.
  Do not read a frozen-gain 'V' run as a share-loop gate failure.
- **Share governor clip bands are computable:** sp_eff is clipped to
  [I_min/Itot_filt, 1 - I_min/Itot_filt] with SHARE_MINORITY_I_MIN_A = 0.30 A (e.g.
  Itot 0.72 A -> [0.42, 0.58]). Measured share parking at ~0.40/~0.60 at ~0.7 A load
  is the governor working, not a tracking failure.

## fw v19 conduction-aware slew mode (NOT in the log)

- **The droop-ratio slew ceiling is no longer a constant, and you CANNOT reconstruct it
  from the logged currents.** From fw v19 `updateShareSlewMode()` selects between
  `DROOP_RATIO_SLEW_PER_TICK` (0.02/tick) and `DROOP_RATIO_SLEW_HANDOFF_PER_TICK`
  (0.002/tick) each `powerBalance()` tick. The decision runs on **filtered** per-channel
  magnitudes (EMA of |I_fc|/|I_batt| at SHARE_GOV_FILT_ALPHA), with **hysteresis**
  (dark < 0.15 A, live >= 0.20 A) and a **motion-gated dwell counter** capped at
  SHARE_HANDOFF_DWELL_MAX_TICKS = 175 ticks (~200 ms) per dark event — it counts only ticks
  on which the commanded ratio actually moved, so a static hold with a dark channel burns
  none of the allowance. None of the filter,
  hysteresis or dwell state is in the BLG record, and the raw `ifc`/`ibt` columns are not
  the quantity the test uses. **Do not infer the mode from raw currents** — a channel's raw
  current crossing 0.15 A in a log tells you nothing about which ceiling was in force.
- **The observable is the State-98 `'S'` dump line** `share slew mode: FULL|HANDOFF|CAPPED`
  (with both filtered magnitudes, the dwell counter and the tick's step). If a run's share
  behaviour hinges on the slew rate, ask for an `'S'` dump; without one, report the ceiling
  as unknown rather than assuming the nominal rate.
- **Expected fw v19 signature, not a defect:** a share-ratio walk that takes ~10x longer
  than a fw v18 walk while one channel sits near zero current, reverting to the fast rate
  after ~200 ms. Applies to arming walks, governor floor-clip walks after a load fall, and
  setpoint-latch releases with the re-closed channel still dark.
