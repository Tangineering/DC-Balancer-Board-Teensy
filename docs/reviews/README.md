# Adversarial review registry

Each row is a review project: a stable target reviewed across runs. Same target reviewed
again = same project, next run number — never a second project.

| Slug | Prefix | Target | Ledger |
|---|---|---|---|
| boost-debug | BOOST | docs/boost-bringup-debug.md (bring-up failure analysis: hypotheses, arithmetic, fixes) | [boost-debug/ledger.md](boost-debug/ledger.md) |
| firmware | FW | teensy_controller/ + test/ + tools/decode_benchlog.py (State-98 bench features: SD logging, Y combined profile; Run-state/Pi-bridge interactions) | [firmware/ledger.md](firmware/ledger.md) |
| hil-plant | PLANT | docs/HIL_PLANT.md (HIL plant physics: charger, regen, chopper, RT1987, power identity, DP/walk fidelity) | [hil-plant/ledger.md](hil-plant/ledger.md) |
