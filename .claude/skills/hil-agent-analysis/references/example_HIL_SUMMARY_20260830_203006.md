# HIL campaign summary — 2026-08-30 20:30 (fix-round validation)

Headline digest of `HIL_FINDINGS.md` (same folder — full evidence, numbers, and per-run
sections live there). Suite ran on fw v23, tooling commit 7802466, hifi electrical mode.

## Scoreboard

**38 runs — 36 PASS / 1 FAIL / 1 SKIP. Every verdict is correct.** Zero false FAILs
(previous campaign: 23), zero rubber-stamp PASSes (was 3), zero power cycles. The one
FAIL (comm-loss) is a real latch correctly scored; its root cause is a simulator defect,
not the board. soc-depletion (880 s) was excluded from the plan by the operator.

## Headlines

- **Grace-aware scoring validated on hardware** — carried-in settle latches excused,
  post-grace unions bit-exact against independent recomputation on every analyzed run.
  The carried-in signature is systematic: `carried == predecessor_final | 0x0010`, 26/26
  replays without exception.
- **Regen power path validated end-to-end** (charge-regen, first time ever): three
  braking windows, REGEN/FC_CHARGE mutual exclusion absolute, Ag105 power-cycling with
  0.499 s settles, I_charge 1.54 A via REGEN+MOT_PWR at 39% OC margin. *Path validation
  only — the plant floors regen power at zero; SOC net fell.*
- **First Ag105 GENSTAT input-collapse observation** (charge-fault): readiness gate works
  in the loss direction; MPPT re-inhibited +13.5 ms after collapse; 0.8 A ceiling held
  to four decimals.
- **Share-cut setpoint latch proven** (handoff-sag): cut 12 ms after the rail command,
  load guard admitted at 24% margin, one-tick current transfer, clean single-source step.
- **RT1987 SOFT-state SCP cut fired** (scp-inrush): 6.29 A cut; structural finding — the
  fold is unreachable without an OC fault at any share split; the ~1 ms
  sim-fires-before-firmware window is the whole test.
- **charge-cruise delivers the ruling-(b) validation**: OC_FC at 1.4024 A on the FC-charge
  ramp — the designed infeasibility signature.
- **Replay half alive**: UV-latch coverage restored (TP0010/TP0053 latch within 2–3 ms of
  recorded qualification under the 1.3 A clamp), ML0217 cold-boot INIT_FAIL at +301 ms,
  OC quartet latching 0.8–1.7 ms after the recorded crossings. Adversarial audit: zero
  wrongly-scored entries; 32/79 checks vacuous by construction (no commander — tagged for
  fixing).
- **Repeatability**: staged bring-up to ~1 ms/~1 mA across campaigns (third corroboration
  of the SOFT-state physics fix); UV dwell 19.992 vs 19.887 ms; ems-drive-cycle a sub-1%
  repeat (tracking median 0.53 mm/s).
- **comm-loss FAIL root-caused**: hifi SOFT-start defect on PRE-CHARGED nodes (3.9×
  non-physical current 3 ms after an otherwise perfect recovery, Δ 1.1 ms). Fix shipped in
  the post-suite round: warm case 6.82× → 1.02× physical, cold path byte-identical.
- **Cross-cutting**: the hifi engine implements the DESIGN droop (0.316/0.633 Ω, ratio
  exactly 2.000) — 4× the bench-measured K_DROOP_BUS. Hifi sag depths are conservative and
  not bench-comparable; now bannered.

## Worth reviewing manually

1. **charge-regen CSV, braking windows t≈14–16/26–28/37–39 s** — the first regen-path
   traces in the project; worth eyeballing I_charge/V_chg/GENSTAT against intuition
   before EMS-strategy work builds on them.
2. **scp-inrush events.jsonl + t=0.59–0.62 s** — the entire test lives in ~1 ms; the
   fold/cut/teardown interplay is worth one human pass before trusting the tightened
   checks to police it alone.
3. **comm-loss t=7.50–7.62 s** — the artifact current spike shape, to sanity-check the
   post-suite sim fix against what the board actually saw.
4. **handoff-sag t=6.0–6.02 s** — the share-cut transient (0.24 V, one-tick transfer);
   also the open question of where the UV objective should live.
5. **WP0097 replay** — the OC latch rests on a 41 ms stimulus window and a 39 ms held
   tail; fragile by construction, flagged in its entry.
6. **ML0151 replay** — knife-edge conformance at 96.7% of LIMIT_I_FC_MAX; any
   injection-path change flips its class.

## Open items (operator)

- soc-depletion needs a session with ~15 spare minutes (880 s run).
- UV-dwell objective has no reachable home (OC_BT wins on the BT rail) — retire it from
  handoff-sag or give it a `v_bus_sense_offset` scenario.
- Ag105 lazy re-config and the FC_CHARGE open-through-loss policy need real-hardware
  verification (HIL mirrors pollAg105 by fiat).
- Chopper coverage needs a stimulus that injects energy into the motor node (plant floors
  regen power today).
