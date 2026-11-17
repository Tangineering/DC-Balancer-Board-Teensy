"""I2C facts for the FR-07 raise at 100 kHz with the existing pull-ups (read-only fact round, 2026-11-16).

Sources (cited in the printed output):
  - Bit model: docs/reviews/charger_eval_2026-11-05/round4/calc/r7_calc.py:5604-5619 (H.23(o)).
  - Cb estimate: docs/reviews/charger_eval_2026-11-05/round3/calc/r3_calc.py:595-601 (H.16).
  - Teensy LPI2C 100 kHz timing: Teensyduino 1.62.0 libraries/Wire/WireIMXRT.cpp:9, 18-19, 487-494.
  - LPI2C SCL period formula: IMXRT1060RM LPI2C MCCR0, TODO(verify: IMXRT1060RM, not in references/).
  - Teensy pad pull-up PUS(3) = 22 kOhm: TODO(verify: IMXRT1060RM IOMUXC SW_PAD_CTL PUS field).
Run: C:/Users/ricky/miniforge3/python.exe i2c_facts_100k.py
"""
import math

F = 100e3                       # Hz, nominal SCL
T_BIT = 1.0 / F
T_BUF = 4.7e-6                  # s, r7_calc.py:5604 (UM10204 Sm, ASSUMPTION there)


def bits_w(n):                  # r7_calc.py:5610-5613
    return (2 + n) * 9 + 2


def bits_r(n):                  # r7_calc.py:5616-5618
    return (3 + n) * 9 + 3


def ms(x):
    return "%.3f ms" % (x * 1e3)


def par(*r):
    return 1.0 / sum(1.0 / x for x in r)


print("=== (2) Rise time tr = 0.8473 Rp Cb (30-70 %) vs UM10204 Sm 1000 ns / Fm 300 ns")
R_MB = 10e3                     # RSDA/RSCL as built (Scale_Car_Board_20260624.sch:5897-5898)
R_TEENSY = 22e3                 # Wire PINCONFIG PUS(3), TODO(verify)
R_EVM = 10e3                    # EVM R39/R40 to PULLUP (SLUUCB5E BOM, bom_raw.txt:70); EM6 removes them
configs = [
    ("MB 10k only (Teensy pad pull-up off)", R_MB),
    ("MB 10k || Teensy 22k (Wire default)", par(R_MB, R_TEENSY)),
    ("MB 10k || EVM 10k (JP30 in, EM6 not done)", par(R_MB, R_EVM)),
    ("MB 10k || EVM 10k || Teensy 22k", par(R_MB, R_EVM, R_TEENSY)),
    ("PM9 2.7k (reference, rework)", 2.7e3),
]
# Cb = W7 length x c' + board 30 + EVM 20 + Teensy 10 pF (r3_calc.py:599)
cb_cases = []
for L in (0.20, 0.30):
    for cp in (50e-12, 100e-12, 130e-12):
        cb_cases.append((L, cp, L * cp + 60e-12))
hdr = "  %-44s" % "config / Cb (W7 m, pF/m) ->" + "".join("%11s" % ("%.2f/%d" % (L, cp * 1e12)) for L, cp, _ in cb_cases)
print(hdr)
print("  %-44s" % "Cb pF" + "".join("%11.0f" % (cb * 1e12) for _, _, cb in cb_cases))
for lab, rp in configs:
    row = "".join("%11.0f" % (0.8473 * rp * cb * 1e9) for _, _, cb in cb_cases)
    print("  %-44s" % ("%s (Rp %.2fk)" % (lab, rp / 1e3)) + row + "  ns")
for lab, rp in configs:
    print("  %-44s Cb max for 1000 ns: %4.0f pF, for 300 ns: %4.0f pF; sink at VOL 0.4 V from 3.465 V: %.2f mA (Sm/Fm limit 3 mA)"
          % (lab, 1000e-9 / (0.8473 * rp) * 1e12, 300e-9 / (0.8473 * rp) * 1e12, (3.465 - 0.4) / rp * 1e3))

print("\n=== LPI2C effective SCL period at the Wire 100 kHz setting (rise time stretches the bit)")
F_FUNC = 24e6                   # WireIMXRT.cpp:18-19 (24 MHz LPI2C clock)
PRESC, CLKHI, CLKLO, FILTSCL = 1, 55, 59, 5   # WireIMXRT.cpp:489-492
SETHOLD, DATAVD = 40, 25
tick = (2 ** PRESC) / F_FUNC
print("  tLOW = (CLKLO+1) x %.1f ns = %.2f us (Sm min 4.7 us); tHIGH = (CLKHI+1) x tick = %.2f us (Sm min 4.0 us)"
      % (tick * 1e9, (CLKLO + 1) * tick * 1e6, (CLKHI + 1) * tick * 1e6))
print("  SETHOLD (START hold / repeated-START and STOP setup) = (SETHOLD+1) x tick = %.2f us (Sm min 4.0-4.7 us, Fm+ 0.26 us); "
      "DATAVD = %.2f us (Sm tVD;DAT max 3.45 us)" % ((SETHOLD + 1) * tick * 1e6, (DATAVD + 1) * tick * 1e6))
eff = {}
for lab, rp in configs[:2]:
    for cb in (75e-12, 120e-12):
        t_vih = rp * cb * math.log(1 / 0.3)          # 0 -> 0.7 VDD, ASSUMPTION Teensy VIH 0.7 VDD
        rise_cyc = t_vih * F_FUNC
        lat = math.floor((2 + FILTSCL + rise_cyc) / 2 ** PRESC)
        per = (CLKLO + 1 + CLKHI + 1 + lat) * tick
        eff[(lab, cb)] = per
        print("  %-40s Cb %3.0f pF: rise to 0.7 VDD %4.0f ns, SCL_LATENCY %2d -> SCL period %.2f us (%.1f kHz, x%.3f of 10 us)"
              % (lab, cb * 1e12, t_vih * 1e9, lat, per * 1e6, 1e-3 / per, per / T_BIT))
k0 = (CLKLO + 1 + CLKHI + 1 + math.floor((2 + FILTSCL) / 2)) * tick / T_BIT
k_worst = max(eff.values()) / T_BIT

print("\n=== (3) Transaction lengths at 100 kHz (r7_calc bit model, 10 us/bit; x%.3f / x%.3f for the LPI2C period range)" % (k0, k_worst))
items = [("W(REG06:07) IINDPM, 2 data", bits_w(2)), ("W(REG03-05) ICHG+VINDPM, 3 data", bits_w(3)),
         ("R(REG05), 1 data", bits_r(1)), ("R(REG01:02) / R(REG06:07), 2 data", bits_r(2)),
         ("R(REG31-34) IBAT/IBUS, 4 data", bits_r(4)), ("R(REG1B-21) status, 7 data", bits_r(7)),
         ("R(REG01-07), 7 data", bits_r(7)), ("R(REG00-0A) verify, 11 data", bits_r(11)),
         ("one byte + STOP (abort)", 10)]
for lab, b in items:
    print("  %-36s %4d bits  %s  (%s .. %s)" % (lab, b, ms(b * T_BIT), ms(b * T_BIT * k0), ms(b * T_BIT * k_worst)))
writes = (bits_w(2) + bits_w(3)) * T_BIT + 2 * T_BUF


def arch(lab, inflight, detect=0.0, note=""):
    base = detect + inflight + writes
    infl_bus = inflight * k_worst if inflight else 0.0
    worst = detect + infl_bus + (bits_w(2) + bits_w(3)) * T_BIT * k_worst + 2 * T_BUF
    print("  %-62s %s   (LPI2C-stretched %s) %s" % (lab, ms(base), ms(worst), note))


print("\n=== (3) Edge to raise-writes-complete at 100 kHz (ISR latency excluded unless stated)")
print("  two writes + 2 t_BUF = %s" % ms(writes))
arch("(a) design: ISR + queue priority + cap 0.50 ms (H.23(o))", 0.50e-3, note="= H.23(o) 1.359 ms")
arch("(a') design, in-flight = longest write W(REG03-05) (H.23(y)(2))", bits_w(3) * T_BIT)
arch("(a'') ISR + priority + abort, idle bus", 0.0)
arch("(e) ISR, FIFO, one ramp group ahead (H.23(y)(2))", 0.50e-3 + 2 * (bits_r(2) * T_BIT + T_BUF), note="= 2.329 ms")
arch("(b1) ISR + priority, no cap/abort, R(REG1B-21) in flight", bits_r(7) * T_BIT)
arch("(b2) ISR + priority, no cap/abort, R(REG00-0A) unsplit in flight", bits_r(11) * T_BIT)
arch("(c1) no pin ISR, polled in 1 kHz timer (+T_TICK_MAX 1.0 ms), cap", 0.50e-3, detect=1.0e-3)
arch("(c2) polled in loop() (+FR-27 5.0 ms), cap", 0.50e-3, detect=5.0e-3)
arch("(d) blocking Wire in loop(): loop 5.0 ms (incl. its own I2C) + writes", 0.0, detect=5.0e-3)
