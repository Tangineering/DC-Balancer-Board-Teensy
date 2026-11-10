"""Tally of the IC1 battle-test history for docs/battery_isolation_feasibility_2026-11-07.md section 3.

Inputs: the confirmed-finding lists of battle-test rounds 1-8 (IDs and verified severities, as recorded by the
workflow history and adjudicated in detailed_design_IC1.md Appendices B-F and H-J). For rounds 1-3 the history listed only part
of the minor findings and gave the remainder as a count ("minorCount"); for rounds 4 and 5 every minor ID is taken from
Appendix E Table E1 and Appendix F Table F1, and the history's minorCount (10 per round) is cross-checked against them.
Stdlib only.
Cross-check: Appendix B states 62 findings (1/20/41), C 42 (1/16/25), D 25 (2/12/11), E 29 (0/9/20), F 22 (0/8/14).
Rounds 6 and 7 (added 2026-11-08) attacked only the purge package of revisions 9 and 10 (section 9.11 and the R9/R10
change tables) under the operator rulings OR-P (ideal predictor, out of scope) and OR-SC (safe collapse accepted).
Their IDs and verified severities are taken from Appendix H Table H1 (13 findings: 0/3/10) and Appendix I Table I1
(8 findings: 0/3/5); the workflow history lists 8 and 4 confirmed IDs with minorCount 5 and 4, cross-checked below.
Round 8 (added 2026-11-08) attacked revision 11 as a whole design through five lenses (FMEA, logic, datasheet,
transient, requirements), aimed at the revision-8 hardware that no earlier round had attacked (R_VC1c, R_MS3, R_BL3,
R_PGL, the D_VC1 selection under OR-AC: Appendix F later-review items 1-4) and at the revision 9-11 firmware rules.
Its IDs and verified severities are taken from Appendix J Table J1 (14 findings: 0/3/11; the verifiers lowered five
majors to minor); the workflow history lists 8 confirmed IDs (3 major, 5 minor) with minorCount 6, cross-checked below.
"""
import re
from collections import Counter

R1 = {"blocker": ["FM-1"],
      "major": ["FM-2", "FM-3", "FM-4", "FM-6", "FM-7", "BT1-T1", "BT1-T2", "BT1-02", "BT1-03", "BT1-04", "BT1-07",
                "BT1-DS-04", "BT1-AG-1", "BT1-AG-2", "BT1-AG-4", "BT1-BM-01", "BT1-BM-02", "BT1-BM-04", "BT1-BM-05",
                "BT1-BM-07"],
      "minor": ["FM-5", "FM-8", "BT1-T3", "BT1-01", "BT1-05", "BT1-06", "BT1-DS-01", "BT1-DS-02", "BT1-DS-03",
                "BT1-AG-3", "BT1-AG-5", "BT1-BM-03", "BT1-BM-06"] + ["BT1-RO-0%d" % i for i in range(1, 10)]}
R2 = {"blocker": ["FM2-1"],
      "major": ["FM2-3", "FM2-4", "FM2-6", "FM2-7", "FM2-9", "BT2-TR-01", "BT2-TR-02", "BT2-TR-04", "BT2-LS-01",
                "BT2-LS-02", "BT2-LS-03", "DS2-1", "BT2-AG-1", "BT2-BM-01", "BT2-BM-02", "BT2-RO-01"],
      "minor": ["FM2-2", "FM2-5", "FM2-8", "BT2-TR-03", "DS2-2", "DS2-3", "BT2-AG-2", "BT2-AG-3", "BT2-AG-4",
                "BT2-BM-03", "BT2-BM-04", "BT2-RO-02", "BT2-RO-03"]}
R3 = {"blocker": ["FM3-1", "BT3-BM-01"],
      "major": ["FM3-2", "BT3-TR-01", "BT3-TR-03", "BT3-LS-01", "BT3-LS-02", "DS3-1", "DS3-2", "BT3-AG-1",
                "BT3-BM-02", "BT3-BM-03", "BT3-BM-04", "BT3-RO-01"],
      "minor": ["FM3-3", "BT3-TR-02", "BT3-AG-2", "BT3-AG-3"]}
# Round 4 (design under test: revision 6), Appendix E Table E1.
R4 = {"blocker": [],
      "major": ["FM4-1", "FM4-3", "BT4-LS-01", "BT4-LS-02", "BT4-TR-01", "BT4-TR-02", "BT4-DS-02", "BT4-1", "BT4-3"],
      "minor": ["FM4-2", "FM4-4", "FM4-5", "FM4-6", "BT4-LS-03", "BT4-LS-04", "BT4-TR-03", "BT4-TR-04", "BT4-TR-05",
                "BT4-TR-06", "BT4-DS-01", "BT4-DS-03", "BT4-DS-04", "BT4-DS-05", "BT4-DS-06", "BT4-DS-07", "BT4-2",
                "BT4-4", "BT4-5", "BT4-6"]}
# Round 5 (design under test: revision 7), Appendix F Table F1.
R5 = {"blocker": [],
      "major": ["FM5-1", "FM5-2", "BT5-LS-01", "BT5-LS-02", "BT5-TR-01", "BT5-DS-01", "BT5-BO-02", "BT5-BO-03"],
      "minor": ["FM5-3", "FM5-4", "FM5-5", "BT5-LS-03", "BT5-TR-02", "BT5-TR-03", "BT5-TR-04", "BT5-DS-02",
                "BT5-DS-03", "BT5-DS-04", "BT5-BO-01", "BT5-BO-04", "BT5-BO-05", "BT5-BO-06"]}
# Round 6 (design under test: revision 9, purge package only), Appendix H Table H1.
R6 = {"blocker": [],
      "major": ["BT6-LS-01", "BT6-LS-02", "BT6-TR-01"],
      "minor": ["FM6-1", "FM6-2", "FM6-3", "BT6-LS-03", "BT6-TR-02", "BT6-REQ-01", "BT6-REQ-02", "BT6-REQ-03",
                "BT6-REQ-04", "BT6-REQ-05"]}
# Round 7 (design under test: revision 10, purge package only), Appendix I Table I1.
R7 = {"blocker": [],
      "major": ["FM7-1", "BT7-LS-01", "BT7-REQ-01"],
      "minor": ["FM7-2", "FM7-3", "BT7-LS-02", "BT7-TR-01", "BT7-REQ-02"]}
# Round 8 (design under test: revision 11, whole design incl. the revision-8 hardware), Appendix J Table J1.
R8 = {"blocker": [],
      "major": ["BT8-FM-01", "BT8-LS-01", "BT8-REQ-01"],
      "minor": ["BT8-DS-01", "BT8-DS-02", "BT8-DS-03", "BT8-DS-04", "BT8-REQ-02",      # lowered from major
                "BT8-LS-02", "BT8-TR-01", "BT8-TR-02", "BT8-TR-03", "BT8-REQ-03", "BT8-REQ-04"]}
ROUNDS = {1: R1, 2: R2, 3: R3, 4: R4, 5: R5, 6: R6, 7: R7, 8: R8}
UNDER_TEST = {1: "revision 3", 2: "revision 4", 3: "revision 5", 4: "revision 6", 5: "revision 7",
              6: "revision 9 (purge package)", 7: "revision 10 (purge package)",
              8: "revision 11 (whole design incl. revision-8 hardware)"}
LENSES = {1: 7, 2: 7, 3: 7, 4: 5, 5: 5, 6: 4, 7: 4, 8: 5}   # rounds 6-7: FMEA, logic, transient, requirements;
# round 8: FMEA, logic, datasheet, transient, requirements
EXTRA_MINOR = {1: 19, 2: 12, 3: 7, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0}
HISTORY_MINOR = {4: (10, 10), 5: (4, 10), 6: (5, 5), 7: (1, 4), 8: (5, 6)}  # (minors listed in the history, history minorCount)
APPENDIX = {1: (62, 1, 20, 41), 2: (42, 1, 16, 25), 3: (25, 2, 12, 11), 4: (29, 0, 9, 20), 5: (22, 0, 8, 14),
            6: (13, 0, 3, 10), 7: (8, 0, 3, 5), 8: (14, 0, 3, 11)}
REFUTED = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0}
# Distinct defects among the blocker+major findings of rounds 4 and 5 (several lenses filed the same defect;
# grouping from the "As FM..." dispositions of Appendices E and F).
DISTINCT_BM = {
    4: [["FM4-1"], ["FM4-3", "BT4-1"], ["BT4-3"], ["BT4-DS-02"], ["BT4-TR-02"], ["BT4-LS-01"], ["BT4-LS-02"],
        ["BT4-TR-01"]],
    5: [["FM5-1", "BT5-LS-01", "BT5-TR-01"], ["BT5-LS-02"], ["FM5-2", "BT5-BO-02"], ["BT5-DS-01"], ["BT5-BO-03"]],
    6: [["BT6-LS-01"], ["BT6-LS-02"], ["BT6-TR-01"]],
    7: [["FM7-1", "BT7-LS-01"], ["BT7-REQ-01"]],
    8: [["BT8-FM-01"], ["BT8-LS-01"], ["BT8-REQ-01"]]}
# Majors that the adjudication appendix attributes to the preceding revision's own fixes.
FIX_INDUCED = {
    2: ["FM2-1"],                                       # blocker from the revision-4 fuse move (Appendix C)
    3: ["FM3-1", "BT3-BM-01"],                          # blockers from the revision-5 clamp D_VM (Appendix D)
    4: ["FM4-1", "FM4-3", "BT4-1", "BT4-3", "BT4-LS-02", "BT4-LS-01", "BT4-TR-01"],   # Appendix E text
    5: ["FM5-1", "BT5-LS-01", "BT5-TR-01", "BT5-LS-02", "FM5-2", "BT5-BO-02", "BT5-DS-01"],  # Appendix F text
    6: ["BT6-LS-01", "BT6-LS-02"],                     # Appendix H: "introduced by revision 9 itself"
    7: [],
    # Round 8: Appendix J makes no attribution statement. This document's reading: BT8-FM-01 lies in the revision-8
    # sleeve rule R8-3 (the fix of FM5-2/BT5-BO-02); BT8-LS-01 arises where the self-test "deferred" rule meets the
    # revision-11 parked request form R11-2 (the fix of BT7-REQ-01). BT8-REQ-01 (the 16 V J-FC setpoint of section 9.2)
    # has no stated origin in [DD] and is not counted.
    8: ["BT8-FM-01", "BT8-LS-01"]}                                             # Appendix I attributes none to the revision-10 fixes
# Majors whose defect lies in content that revision 9 (the purge package) added; Appendix H names BT6-TR-01 a wrong
# published revision-9 requirement. Round 7: the D-s/dump-check reachability (R9-4 with R8-2) and the charge_goal
# request semantics (R9-6) are revision-9 content (reading of Table 0f and Appendix I, not an Appendix-I statement).
REV9_CONTENT = {6: ["BT6-LS-01", "BT6-LS-02", "BT6-TR-01"], 7: ["FM7-1", "BT7-LS-01", "BT7-REQ-01"]}
# Round 8 findings (any severity) lying in revision-8 hardware or ruling content (R8-3 sleeves and LB-entry resistors,
# the R_BL2 range, the D_VC1/OR-AC specification), per Table J1 and Appendix J.
REV8_CONTENT = {8: ["BT8-FM-01", "BT8-DS-01", "BT8-DS-02", "BT8-DS-04", "BT8-REQ-02", "BT8-TR-03"]}
LOWERED = {8: ["BT8-DS-01", "BT8-DS-02", "BT8-DS-03", "BT8-DS-04", "BT8-REQ-02"]}


def lens(fid):
    if re.match(r"^BT4-\d", fid):
        return "build"      # BT4-1..6 are the round-4 buildability lens
    for p, name in (("FM", "fmea"), ("-REQ", "requirements"), ("-TR", "transient"), ("-T", "transient"), ("-LS", "logic"), ("DS", "datasheet"),
                    ("-AG", "ag105"), ("-BM", "build"), ("-BO", "build"), ("-RO", "requirements")):
        if p in fid:
            return name
    return "logic"          # BT1-01..07 are the round-1 logic lens


tot = Counter()
for n, r in ROUNDS.items():
    b, M, m = len(r["blocker"]), len(r["major"]), len(r["minor"]) + EXTRA_MINOR[n]
    t = b + M + m
    ok = (t, b, M, m) == APPENDIX[n]
    tot.update(blocker=b, major=M, minor=m, total=t)
    lenses = Counter(lens(f) for f in r["blocker"] + r["major"])
    print(f"Round {n} ({UNDER_TEST[n]}, {LENSES[n]} lenses): total {t} = {b} blocker + {M} major + {m} minor; "
          f"refuted {REFUTED[n]}; matches appendix: {ok}")
    print(f"  blocker+major by lens: {dict(sorted(lenses.items()))}")
    if n in HISTORY_MINOR:
        listed, extra = HISTORY_MINOR[n]
        print(f"  history cross-check: {listed} minors listed + minorCount {extra} = {listed + extra} "
              f"(appendix {APPENDIX[n][3]}): {listed + extra == APPENDIX[n][3]}")
    if n in DISTINCT_BM:
        flat = sorted(f for g in DISTINCT_BM[n] for f in g)
        assert flat == sorted(r["blocker"] + r["major"]), n
        print(f"  distinct blocker+major defects: {len(DISTINCT_BM[n])}")
    if n in FIX_INDUCED:
        assert set(FIX_INDUCED[n]) <= set(r["blocker"] + r["major"]), n
        print(f"  blocker+major attributed to the preceding revision's fixes: {len(FIX_INDUCED[n])} of {b + M}")
    if n in REV9_CONTENT:
        assert set(REV9_CONTENT[n]) <= set(r["blocker"] + r["major"]), n
        print(f"  blocker+major lying in revision-9 purge-package content: {len(REV9_CONTENT[n])} of {b + M}")
    if n in REV8_CONTENT:
        assert set(REV8_CONTENT[n]) <= set(r["blocker"] + r["major"] + r["minor"]), n
        print(f"  findings (any severity) lying in revision-8 hardware or ruling content: {len(REV8_CONTENT[n])} of {t}")
    if n in LOWERED:
        assert set(LOWERED[n]) <= set(r["minor"]), n
        print(f"  filed as major, lowered to minor by the verifiers: {len(LOWERED[n])}")
print(f"All rounds: total {tot['total']} = {tot['blocker']} blocker + {tot['major']} major + {tot['minor']} minor")
print("Blocker+major per round: " + ", ".join(
    f"R{n} {len(r['blocker']) + len(r['major'])}" for n, r in ROUNDS.items()))
prev = None
for n in ROUNDS:
    t = APPENDIX[n][0]
    if prev:
        print(f"  R{n - 1}->R{n} total change: {100.0 * (t - prev) / prev:+.1f} %")
    prev = t
print("Rounds 1-5 attacked the whole design; rounds 6-7 attacked only the purge package (section 9.11); round 8 "
      "attacked revision 11 as a whole, aimed at the revision-8 hardware (Appendix F items 1-4) and the revision 9-11 "
      "rules.")
print("Appendix I items 2-6 were not reported on by round 8 (Appendix J); round 8 answered Appendix I item 1.")
print("Revision 12 (after round 8) has not been battle-tested.")
r15 = sum(APPENDIX[n][0] for n in range(1, 6)); r67 = sum(APPENDIX[n][0] for n in (6, 7))
print(f"  rounds 1-5 total {r15}; rounds 6-7 total {r67}; round 8 total {APPENDIX[8][0]}")
print("Completeness critic: 33 gaps; 18 closed in CC-A; 7 closed in revision 7 (CC-B5, B9, B10, B12-B15); "
      "1 closed in revision 8 (CC-B4); 2 turned into rulings (CC-B1 = OR-Z, CC-B2 = OR-Y); "
      "5 open (CC-B3, CC-B6, CC-B7 part selection, CC-B8, CC-B11).")
print(f"  check: {18 + 7 + 1 + 2 + 5} = 33")
