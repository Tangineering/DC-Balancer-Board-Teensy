# V_rgn mismatch root-cause investigation (2026-11-05)

Multi-agent workflow run in response to the 2026-11-05 V_rgn record
(`docs/vrgn_measurement_error_2026-11-05.md`). **The conclusions, ranking, safety implications
and lab plan are in that document, section 7.** This folder holds the raw record.

## Contents

- `workflow_result.json`: every agent's structured return value. `investigators[]` has eight
  entries, each with `summary`, `hypotheses` (verdict and confidence), `new_facts` (cited),
  `remote_checks`, `lab_checks` and `could_not_access`. `synthesis` has the ranking, the
  predicted-vs-observed matrix, uncertainties, the lab plan and the safety list. `verdicts[]`
  holds the three adversarial reviews.
- `agent_work/<agent>/`: the agents' analysis scripts, intermediate CSVs and renders. Paths
  inside the scripts point at the session scratchpad
  (`/tmp/claude-0/.../scratchpad/dec/*.csv` for decoded BLGs, `.../npz/*.npz` for Pi bags);
  regenerate those with `tools/decode_benchlog.py` and `tools/rosbag_analysis/scout_bags.py`.
  The pcb-assembly agent's Python venv (gerbonara) was not kept.

## Agents

| Agent | Brief | Bottom line |
|---|---|---|
| tl431-orientation | Swapped-pinout substitute vs healthy part, quantitative model | Swapped pinout refuted on four independent grounds (it predicts a continuous 0.34 A dump). A healthy TL431 gives a ratio ≥ 0.968 |
| tl431-damaged | Damaged TL431 in the correct orientation; TL431 REF physics; overstress history | Dip I-V = knee 1.19-1.25 V + 9.2-9.3 k; best fit is an input-stage failure. No in-circuit overstress route |
| teensy-pad | i.MX RT1062 pad, ADC, keeper, Teensy core | An intact pad cannot draw 31 uA; pins 38/39 sit on the same ADC2. A damaged pad stays possible (brownout back-injection route) |
| data-leak-curve | Voltage dependence of the leak from all logs and bags | Threshold-linear leak, ~0 below ~1.2 V; small-signal gain 0.52-0.65; trip ~33 V if linear |
| data-thermal-noise | Incremental gain, warm-up, ground shift, noise | Gain 0.45-0.62 << ratio, so the leak is superlinear. Warm-up = 3 % with tau 5.4 min, a forward-junction signature; ground shift ruled out |
| pcb-assembly | Board file, Gerbers, PnP, assembler | Footprint and netlist correct (TI DBZ). RGN-V routing clean. Assembler not recorded |
| repo-archaeology | History of the chopper and pin 39 | No DMM reading of the node ever taken; "18.1 V held" not supported by the logs; no Teensy swap recorded |
| fresh-eyes | Completeness critic | Found the incremental-gain test; proposed the open-cathode / open-R-G variant; refuted every linear mechanism |
| synthesizer | Ranking and matrix | TL431 REF path ~0.62 combined, pad ~0.19, flux ~0.08 |
| verify: physics | Re-derive device claims | Keeps TL431 on top; a second internal path (PNP clamp / Darlington) fits; the safety numbers are lower bounds (a possible soft clamp near node 2 V) |
| verify: data | Re-run the analyses | Core claims reproduce. Small-signal gain and dip slope disagree (13-17 k vs 9.3 k); the dips share one stimulus |
| verify: devil | Best alternative | TL431 vs pad cannot be separated on log data (~even); open joint more likely than die damage. Lab steps 2 and 3 decide it |

## Sources the agents could not reach

righto.com (TL431 die analysis), ti.com (E2E, the SNVA809 FMEA), eevblog and dtsheet.com were
blocked or unavailable. No published measurement of TL431 REF current below Vref, or with the
cathode open, was obtained, so the TL431-path magnitudes are estimates from TI Fig 8-2 resistor
values.
