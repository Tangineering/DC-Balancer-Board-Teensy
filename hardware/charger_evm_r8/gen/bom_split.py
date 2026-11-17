"""Per-unit BOMs for the charger retrofit: one CR, one EIB, and the rest of one build; plus a Digi-Key import CSV.

Usage (pcbnew venv or any Python 3): python gen/bom_split.py <out dir>   (run from hardware/charger_evm_r8)

Sources:
  cr/cr.net, eib/eib.net          fitted reference designators (DNP excluded; W and E lead pads are not parts)
  bom_2026-11-11/ordering_bom.csv  row data (part, specification, manufacturer, MPN, vendor, SKU, links, notes)

Quantities are for ONE unit, with no spares:
  cr_bom.csv      one CR: the count of fitted CR references on each row, the CR PCB and the CR stencil
  eib_bom.csv     one EIB: the count of fitted EIB references on each row and the EIB PCB
  system_bom.csv  the rest of one build (EVMs, EVM and MB rework, harness, wire, materials, hardware, workshop):
                  the design quantity from the row's "design qty N" note; vendor-unit rows (wire spools, tape
                  rolls, kits) keep their sellable unit
  digikey_import.csv  every row of the three files whose vendor is Digi-Key and whose MPN is identified,
                  merged by MPN with the quantities summed; columns for the Digi-Key BOM Manager / list upload
The script refuses when a fitted reference has no ordering-BOM row, when a netlist MPN names a different part
than its row, or when a system row has no parseable design quantity.

2026-11-14 round (REVIEW_2026-11-14.md BOM-1, BOM-3, BOM-4, BOM-6, BOM-8, BOM-9, BOM-10, BOM-11): the netlist now
carries the ordered MPNs, so a netlist MPN equal to the SUBST target of its row is accepted; the stencil rows are
written per board; SUBST targets carry their rated voltage (VMAX); boilerplate and wrong-board note fragments are
removed (clean_notes); the Digi-Key SKU of the upload result fills any row with an empty Vendor SKU; ALTERNATES writes
the explicitly labelled alternate and bench lines (not fitted by default) to a separate opt-in file,
digikey_optional.csv (fix round 2026-11-15; before it they were appended to digikey_import.csv). Run:
python gen/bom_split.py bom_2026-11-14

Phase C round (2026-11-15, second review C:/.../phaseC/review2_findings.md, IDs R2-*): further stale notes on settled
parts are rewritten (R2-BOM-1, R2-LOG-1); the Digi-Key and Mouser Description cells are cut at a word boundary, not
mid-word (R2-BOM-6, desc120()); the ALTERNATES table also writes five opt-in SPARE lines (R2-BOM-0, R2-BOM-5,
R2-CRT-1); the EIB stencil row no longer carries the CR stencil history (R2-BOM-1).
"""
import csv
import os
import re
import sys
from collections import OrderedDict, defaultdict

OUT = sys.argv[1]
SRC = "bom_2026-11-11/ordering_bom.csv"
NON_PART = ("W", "E")                     # lead pads (W1-W7 on the CR, E1-E8 on the EIB)
# J101 and J201 become wire pads with no part (operator ruling 2026-11-13: "Let's remove the J101 and J201." and
# "Change the footprints to through-hole wire pads"); they keep their reference designators.
NON_PART_REFS = {"J101", "J201"}
# rows off the BOM by operator ruling 2026-11-13 (see RULED_OUT below): never treated as system rows
RULED_OUT_MPNS = {"FTSH-107-01-L-DV", "FTSH-107-01-L-DV-K", "FFSD-07-D-12.00-01-N", "22-01-3047", "08-50-0114"}
RULED_OUT_PARTS = {"Polarising plug for FFSD socket hole 6"}
# D-67 (operator ruling 2026-11-13: "Use TCKE1401NM for U101"): the 2026-11-11 row MPN -> the MPN the netlist now
# carries; the rows are replaced through SUBST below and ordered from Mouser
D67_NETLIST = {"TPS26630RGER": "TCKE1401NM,R1F", "CRCW06038K06FKEA": "CRCW06038K45FKEA",
               "TNPW060366K5BEEA": "ERA-3AEB6492V", "TNPW060349K9BEEA": "TNPW060351K1BEEA"}


def netlist(path):
    s = open(path, encoding="utf-8").read()
    out = OrderedDict()
    for ch in re.split(r'\n\s*\(comp \(ref "', s)[1:]:
        ref = ch.split('"', 1)[0]
        body = ch.split("(tstamps", 1)[0]
        mpn = re.search(r'\(field \(name "MPN"\) "([^"]*)"\)', body)
        out[ref] = dict(mpn=mpn.group(1) if mpn else "", dnp=bool(re.search(r'\(property \(name "dnp"\)', body)),
                        value=(re.search(r'\(value "([^"]*)"\)', body) or [None, ""])[1])
    return out


def expand(names):
    """Reference tokens named by a 'PCB Names' cell, ranges such as C114-C116 expanded; EVM/MB refs kept apart."""
    refs = set()
    for tok in re.split(r"[,;]", names):
        tok = tok.strip()
        if not tok or tok.startswith(("EVM", "MB")) or " mate" in tok:
            continue                       # rework parts and mating cables are not board parts
        tok = tok.split(":")[0].split(" ")[0]
        m = re.fullmatch(r"([A-Z]+)(\d+)-\1?(\d+)", tok)
        if m:
            refs |= {"%s%d" % (m.group(1), n) for n in range(int(m.group(2)), int(m.group(3)) + 1)}
        elif re.fullmatch(r"[A-Z]+\d+[A-Za-z]?", tok):
            refs.add(tok)
    return refs


rows = list(csv.reader(open(SRC, encoding="utf-8", newline="")))
HDR = rows[0]
C = {n: i for i, n in enumerate(HDR)}
DATA = [r for r in rows[1:] if len(r) >= 35 and (r[C["Part"]].strip() or r[C["Mft. SKU"]].strip())]
by_ref = defaultdict(list)
for k, r in enumerate(DATA):
    for ref in expand(r[C["PCB Names"]]):
        by_ref[ref].append(k)

boards = {b: netlist("%s/%s.net" % (b, b)) for b in ("cr", "eib")}
errors = []
mpn_pending = []
used = set()
board_rows = {}
for b, parts in boards.items():
    fitted = [ref for ref, p in parts.items()
              if not p["dnp"] and not ref.startswith(NON_PART) and ref not in NON_PART_REFS]
    groups = OrderedDict()
    for ref in fitted:
        ks = by_ref.get(ref)
        if not ks:
            errors.append("%s %s: no ordering-BOM row names it" % (b, ref))
            continue
        nm = parts[ref]["mpn"].replace(" ", "").lower()
        for k in ks:
            row_mpn = DATA[k][C["Mft. SKU"]].replace(" ", "").lower()
            # the netlist may carry a placeholder (T-A-05 class) or the MPN without its packaging suffix; since D-67
            # it carries the U101 change set, which replaces the 2026-11-11 row MPN (D67_NETLIST)
            d67 = D67_NETLIST.get(DATA[k][C["Mft. SKU"]].strip(), "").replace(" ", "").lower()
            if nm and d67 and nm == d67:
                pass
            elif nm and row_mpn not in nm and not row_mpn.startswith(nm) and not re.search(r"t-a-05|class|selected", nm):
                # 2026-11-14 (BOM-11): the netlist may carry the ordered SUBST target; checked after SUBST below
                mpn_pending.append((b, ref, parts[ref]["mpn"], DATA[k][C["Mft. SKU"]]))
            groups.setdefault(k, []).append(ref)
            used.add(k)
    board_rows[b] = groups

# 2026-11-14: the fab packages of the 2026-11-14 boards (written 2026-11-15 by gen/export.sh <board> 2026-11-14;
# update_2026-11-14/notes_phaseB_export.md)
PKG = {"cr": "fab/cr_2026-11-14", "eib": "fab/eib_2026-11-14"}
# the board rows, restated from the fab package READMEs (the 2026-11-11 rows describe the pre-trim CR and the
# pre-D-25 EIB outline)
PCB_SPEC = {
    "cr": ("4-layer, 1.6 mm, 1 oz outer / 0.5 oz inner (OSH Park 4-layer, D-29), ENIG; 10-corner outline with 1.0 mm "
           "fillets (D-62), 40.02 x 64.81 mm bounding box, 2327.7 mm2; four 3.70 mm NPTH for 6-32 (MH1-MH4, D-60)",
           "Order 6 (operator ruling 2026-11-13: \"Use 6\"; OSH Park sells boards in multiples of 3). Upload: "
           "%s/kikit_oshpark/gerbers.zip, the package of the 2026-11-14 board, exported 2026-11-15 by gen/export.sh "
           "cr 2026-11-14 (tracks, vias, pads and zone outlines as D-66/D-69; F.Cu pour fill changed at J1 pin 18 by "
           "D-75; silkscreen D-72 to D-78; stack-up D-76); fab/cr_2026-11-13/, "
           "fab/cr_2026-11-13b_oshpark/, 13c, 13d, 13e and 13f are superseded." % PKG["cr"], "OSH Park"),
    "eib": ("2-layer, 1.6 mm, 1 oz, ENIG, 24.0 x 38.0 mm (D-25), two M3 holes; AGND pours on both layers stitched "
            "by vias (D-63); J201 as wire pads (D-66)",
            "A separate 2-layer order at OSH Park (not on the CR panel). OSH Park sells boards in multiples of 3; the "
            "E BOM asked for 5; order 3, one lot (operator ruling 2026-11-13, chat: \"Order 3\"). Upload: "
            "%s/kikit_oshpark/gerbers.zip, the package of the 2026-11-14 board, exported 2026-11-15 by gen/export.sh "
            "eib 2026-11-14 (board marking \"EIB r8 2026-11-14\"; tracks, vias, pads and zone outlines as D-68; "
            "F.Cu and B.Cu pour fill changed at J201 by D-70; no paste on the DNP pads, D-71); fab/eib_2026-11-13/, "
            "13b and 13c are superseded."
            % PKG["eib"],
            "OSH Park"),
}
SYS_DQ = re.compile(r"design qty (\d+)")
# system rows whose note states no "design qty N": the per-unit quantity and its basis
SYS_OVERRIDE = {
    '467MP 0.5" x 4"': (1, "section E: 1 sheet"),
    "29341": (4, "4 screws for the 2 female-female EIB standoffs"),
    "3200894": (10, "count assumed 10 in the 2026-11-11 BOM (section E gives no count; ASSUMPTION)"),
    "AI 0,5-8 WH": (10, "count assumed 10 in the 2026-11-11 BOM (ASSUMPTION)"),
    "PLT1M-C": (3, "A1 and A2 anchors and the chassis tie; Digi-Key sells PLT1M-C per piece (pre-order review "
                   "2026-11-13, DK-5)"),
    "Adhesive cable-tie base 6 x 6 mm": (1,"A1; section E: 2 tie bases = one A1 and one A2"),
    "Adhesive cable-tie base 10 x 10 mm": (1, "A2; section E: 2 tie bases = one A1 and one A2"),
}
out_rows = {"cr": [], "eib": [], "system": []}


def per_unit(r, qty, refs=None, note=None):
    r = list(r)
    r[C["BOM Qty"]] = "%d" % qty
    if refs is not None:
        r[C["PCB Names"]] = ",".join(refs)
    notes = r[C["Notes"]]
    notes = re.sub(r"^Order qty = [^.]*\.\s*", "", notes)
    r[C["Notes"]] = (note + " " + notes).strip() if note else notes
    for col in ("Assembly Cost", "Cost / BOM Unit"):
        r[C[col]] = ""
    return r


def ref_key(ref):
    m = re.match(r"([A-Z]+)(\d+)(.*)", ref)
    return (m.group(1), int(m.group(2)), m.group(3)) if m else (ref, 0, "")


for b in ("cr", "eib"):
    for k, refs in board_rows[b].items():
        refs = sorted(refs, key=ref_key)
        out_rows[b].append(per_unit(DATA[k], len(refs), refs, "Per-unit qty = %d (one %s)." % (len(refs), b.upper())))

for k, r in enumerate(DATA):
    if k in used:
        # a row shared by board parts and EVM/MB rework parts (e.g. the 47.0 kOhm row: EVM R272, R272b) also
        # yields a system row for the rework references (pre-order review 2026-11-13, finding SYS-1)
        rework = [t.strip() for t in re.split(r"[,;]", r[C["PCB Names"]]) if t.strip().startswith(("EVM", "MB"))]
        if rework:
            out_rows["system"].append(per_unit(r, len(rework), rework, "Per-unit qty = %d (one build; the rework "
                                               "references of a row shared with board parts)." % len(rework)))
        continue
    cat, part = r[C["Category"]], r[C["Part"]]
    if r[C["Mft. SKU"]].strip() in RULED_OUT_MPNS or part.strip() in RULED_OUT_PARTS:
        out_rows["system"].append(per_unit(r, 1, None, None))   # dropped again by RULED_OUT below, with its reason
        continue
    if cat == "PCB":
        b = "cr" if r[C["PCB Names"]].strip() == "CR" else "eib"
        r = list(r)
        r[C["Specification"]], r[C["Notes"]], r[C["Vendor"]] = PCB_SPEC[b]
        out_rows[b].append(per_unit(r, 1, None, "Per-unit qty = 1 board."))
        continue
    if cat == "Assembly":                                  # the stencils (D-69: one per board, OSH Stencils)
        # 2026-11-14 (BOM-1, BOM-2): PCB Names, specification and note per board; the EIB stencil has no apertures on
        # the 14 DNP footprints (gen/eib_dnp_paste.py, update_2026-11-14/notes_eib.md section 2.2)
        STENCIL = {
            "cr": ("upload %s/gerbers/cr-F_Paste.gtp. Finest pitch: U101 0.5 mm VQFN; U101 exposed-pad paste "
                   "windows about 55 %% coverage (D-69). Solder paste NOT IDENTIFIED (a Type 4 paste is the usual "
                   "choice for the 0.5 mm U101 pitch)" % PKG["cr"],
                   "Smallest area ratio at 4 mil: U101 pins 0.96; at 5 mil 0.76; IPC-7525 asks >= 0.66."),
            "eib": ("upload %s/gerbers/eib-F_Paste.gtp. Apertures on the fitted pads only (62 pads): the 14 DNP "
                    "footprints C203, C204, E4, E6, R258-R265, U203 and U204 carry a -2.0 mm paste margin, so the "
                    "stencil has no aperture on them (gen/eib_dnp_paste.py). Finest pitch: 0.65 mm (U201 DCT, U202 "
                    "SC-70). Solder paste NOT IDENTIFIED" % PKG["eib"],
                    "Smallest area ratio at 4 mil: U202 SC-70 1.24; at 5 mil 0.98; IPC-7525 asks >= 0.66."),
        }
        for b_ in ("cr", "eib"):
            s_ = list(r)
            s_[C["Part"]] = "Solder paste stencil (%s top side)" % b_.upper()
            s_[C["PCB Names"]] = "%s top side (reflow assembly)" % b_.upper()
            s_[C["Manufacturer"]], s_[C["Vendor"]] = "OSH Stencils", "OSH Stencils"
            s_[C["Mft. SKU"]] = "Stainless steel 4 mil, frameless"
            s_[C["Vendor SKU"]], s_[C["Link"]] = "", "https://www.oshstencils.com/"
            s_[C["Specification"]] = ("Stainless steel 4 mil (0.1 mm) frameless stencil, top side only (no bottom "
                                      "paste); %s" % STENCIL[b_][0])
            # phase C (R2-BOM-1): the 2026-11-11 row described the CR stencil only, so its text stays as the CR
            # row's superseded history; the EIB row is new by D-69 and states that instead
            hist = ("Superseded: %s" % r[C["Notes"]] if b_ == "cr" else
                    "The 2026-11-11 ordering BOM had no EIB stencil row; this row is new by D-69 (one stencil per "
                    "board).")
            s_[C["Notes"]] = ("Operator ruling 2026-11-13 (chat: \"I would order from OSH Stencil\"; \"Yes, do both\"): "
                              "4 mil stainless, one stencil per board in one order (OSH Stencils prices by area per "
                              "material, so a combined sheet saves only the border). %s %s"
                              % (STENCIL[b_][1], hist))
            out_rows[b_].append(per_unit(s_, 1, None, "Per-unit qty = 1."))
        continue
    m = SYS_DQ.search(r[C["Notes"]])
    q = r[C["BOM Qty"]].strip()
    unit = r[C["BOM Units"]].strip()
    ov = SYS_OVERRIDE.get(r[C["Mft. SKU"]].strip()) or SYS_OVERRIDE.get(part.strip())
    if ov:
        out_rows["system"].append(per_unit(r, ov[0], None, "Per-unit qty = %d (one build; %s)." % ov))
        continue
    if m:
        dq = int(m.group(1))
    elif unit and unit not in ("ea", "board"):
        dq = int(float(q))                                 # sellable unit (spool, roll, kit, pack)
    elif re.match(r"^Order qty = (\d+)\b", r[C["Notes"]]):
        dq = int(re.match(r"^Order qty = (\d+)\b", r[C["Notes"]]).group(1))
    elif cat == "Workshop":
        dq = int(float(q))
    else:
        errors.append("system row %r (%s): no design quantity" % (part, r[C["Mft. SKU"]]))
        continue
    out_rows["system"].append(per_unit(r, dq, None, "Per-unit qty = %d (one build)." % dq))

# ---- Digi-Key upload review, 2026-11-13 ----------------------------------------------------------------------
# The operator uploaded digikey_import.csv to Digi-Key; the result is recorded in
# bom_2026-11-13/digikey_upload_result_2026-11-13.csv. Every replacement below was read on its live Digi-Key
# product page on 2026-11-13 (status Active, stock > 0, cut tape or bulk at quantity 1 unless stated).

# Operator ruling 2026-11-13 (chat): "Let's take the wire and tape off of the BOM, I'll use what I have in my
# workshop." These rows leave the system BOM and are listed in digikey_skipped.csv as workshop stock.
WORKSHOP_TAPE = {'467MP 0.5" x 4"', "5413 AMBER 1/4 IN X 36 YD"}
# Operator ruling 2026-11-13 (chat): "I'll deal with the J-TAP cable with whatever materials I have in my workshop."
# The J102 mate cable leaves the BOM; the J102 header on the CR stays.
WORKSHOP_TAPE.add("2147561101")
workshop = [r for r in out_rows["system"] if r[C["Category"]] == "Wire" or r[C["Mft. SKU"]].strip() in WORKSHOP_TAPE]
out_rows["system"] = [r for r in out_rows["system"] if not any(r is w for w in workshop)]
# Operator ruling 2026-11-13 (chat): "no second BQ25798EVM": one EVM per build (section E ordered 2)
for r in out_rows["system"]:
    if r[C["Mft. SKU"]].strip() == "BQ25798EVM":
        r[C["BOM Qty"]] = "1"
        r[C["Notes"]] = ("Per-unit qty = 1 (one build; operator ruling 2026-11-13, chat: \"no second BQ25798EVM\"; "
                         "section E ordered 2). " + re.sub(r"^Per-unit qty = \d+ \(one build\)\.\s*", "", r[C["Notes"]]))

# Operator connector rulings 2026-11-13 (forked side session, relayed): "Let's remove the J101 and J201." (the W5
# ribbon, its key plug and both FTSH headers go; the link becomes direct-soldered wires) and "The EVM J8 KK I'll
# solder directly to the pins." (the KK housing and crimps go). J1 and J102 stay.
RULED_OUT = {
    "FTSH-107-01-L-DV": "J101 removed (operator ruling 2026-11-13)",
    "FTSH-107-01-L-DV-K": "J201 removed (operator ruling 2026-11-13)",
    "FFSD-07-D-12.00-01-N": "W5 ribbon removed with J101/J201 (operator ruling 2026-11-13)",
    "22-01-3047": "EVM J8 lead soldered to the pins; no KK mate (operator ruling 2026-11-13)",
    "08-50-0114": "EVM J8 lead soldered to the pins; no KK crimps (operator ruling 2026-11-13)",
}
RULED_OUT_PART = {"Polarising plug for FFSD socket hole 6": "W5 key removed with J101/J201 (operator ruling 2026-11-13)"}
ruled = []
for b in ("cr", "eib", "system"):
    keep = []
    for r in out_rows[b]:
        why = RULED_OUT.get(r[C["Mft. SKU"]].strip()) or RULED_OUT_PART.get(r[C["Part"]].strip())
        if why:
            ruled.append(({"cr": "CR", "eib": "EIB", "system": "SYS"}[b], r, why))
        else:
            keep.append(r)
    out_rows[b] = keep

# old MPN -> (new MPN, manufacturer, Digi-Key part number, specification or None to keep, reason)
SUBST = {
    "GRM188R71H223KA01D": ("C0603C223K5RACTU", "KEMET", "399-C0603C223K5RACTUCT-ND", "22 nF 50 V X7R 0603",
                           "Murata GRM188R71H223KA01D is obsolete (Digi-Key 2026-11-13); KEMET C0603C223K5RACTU is "
                           "Digi-Key's direct substitute, same value, rating, dielectric and case."),
    "GRM21BR71H105KA12L": ("CL21B105KBFNNNF", "Samsung Electro-Mechanics", "1276-CL21B105KBFNNNFCT-ND",
                           "1.0 uF 50 V X7R 0805 (1.35 mm max thickness)",
                           "Murata GRM21BR71H105KA12L is obsolete (Digi-Key 2026-11-13); Samsung CL21B105KBFNNNF is a "
                           "direct substitute listed by Digi-Key, same value, rating, dielectric and case."),
    "GRM188R71H104KA93D": ("GRM188R72A104KA35D", "Murata Electronics", "490-3285-1-ND", "100 nF 100 V X7R 0603",
                           "Murata GRM188R71H104KA93D (50 V) is obsolete (Digi-Key 2026-11-13); GRM188R72A104KA35D is "
                           "Digi-Key's 'upgrade' substitute (100 V, same series and case) and is already the C102c "
                           "part, so the two lines merge."),
    "GRM21BR71A106KE51L": ("CL21B106KOQNNNE", "Samsung Electro-Mechanics", "1276-2872-1-ND",
                           "10 uF 16 V X7R 0805 (1.40 mm max thickness)",
                           "Murata GRM21BR71A106KE51L (10 V) is obsolete (Digi-Key 2026-11-13); Samsung "
                           "CL21B106KOQNNNE is Digi-Key's 'upgrade' substitute (16 V, X7R, 0805)."),
    "GRM31CR72A105KA01L": ("CL31B105KCHSFNE", "Samsung Electro-Mechanics", "1276-3095-1-ND",
                           "1.0 uF 100 V X7R 1206 (1.80 mm max thickness)",
                           "Murata GRM31CR72A105KA01L has 0 stock at Digi-Key, restock 22-Feb-2027 (2026-11-13); "
                           "Samsung CL31B105KCHSFNE is a direct substitute listed by Digi-Key."),
    "C3225X7S2A475K200AB": ("CNC6P1X7R2A475K250AE", "TDK", "445-181657-1-ND",
                            "4.7 uF 100 V X7R 1210 (2.50 mm, Digi-Key description); effective >= 3 uF at 23.6 V "
                            "required",
                            "TDK C3225X7S2A475K200AB has 0 stock at Digi-Key, restock 15-Feb-2027 (2026-11-13); TDK "
                            "CNC6P1X7R2A475K250AE (X7R, soft termination) is in stock. DC bias closed 2026-11-13: "
                            "about 3.04 uF typ at 23.6 V and 2.96 uF at the 24.41 V D-67 OVP maximum (TDK Product "
                            "Center; bom_2026-11-13/README.md section 4.4); T-A-04 measures the fitted part."),
    "BAV199,215": ("BAV199-7-F", "Diodes Incorporated", "BAV199-FDICT-ND",
                   "BAV199 series pair, 85 V, 140 mA, IR <= 5 nA at 75 V, SOT-23",
                   "Nexperia BAV199,215 has 0 stock at Digi-Key, restock 19-Nov-2026 (2026-11-13); Diodes "
                   "BAV199-7-F is Digi-Key's direct substitute (same pinout and leakage class)."),
    "TNPW060356K2BEEA": ("ERA-3AEB5622V", "Panasonic Industry", "P56.2KDBCT-ND",
                         "56.2 kOhm 0.1 % 25 ppm/K 0603 thin film",
                         "Vishay TNPW060356K2BEEA has 0 stock at Digi-Key, restock 15-Dec-2026 (2026-11-13); "
                         "Panasonic ERA-3AEB5622V is a direct substitute (0.1 %, 25 ppm/K, 0603)."),
    "TNPW080510K0BEEA": ("ERA-6AEB103V", "Panasonic Industry", "P10KDACT-ND", "10.0 kOhm 0.1 % 25 ppm/K 0805 thin film",
                         "Vishay TNPW080510K0BEEA has 0 stock at Digi-Key, restock 01-Dec-2026 (2026-11-13); "
                         "Panasonic ERA-6AEB103V is a direct substitute (0.1 %, 25 ppm/K, 0805)."),
    "TNPW0805845KBEEA": ("ERA-6AEB8453V", "Panasonic Industry", "P845KDACT-ND", "845 kOhm 0.1 % 25 ppm/K 0805 thin film",
                         "Vishay TNPW0805845KBEEA is a non-stock reel item at Digi-Key (MOQ 15,000, 2026-11-13); "
                         "Panasonic ERA-6AEB8453V is in stock (0.1 %, 25 ppm/K, 0805, 0.125 W)."),
    "TNPW0805487KBEEA": ("ERA-6AEB4873V", "Panasonic Industry", "10-ERA-6AEB4873VCT-ND",
                         "487 kOhm 0.1 % 25 ppm/K 0805 thin film",
                         "Vishay TNPW0805487KBEEA is a non-stock reel item at Digi-Key (MOQ 5,000, 2026-11-13); "
                         "Panasonic ERA-6AEB4873V is in stock (0.1 %, 25 ppm/K, 0805, 0.125 W)."),
    "TNPW0603104KBEEA": ("RT0603BRD07104KL", "YAGEO", "13-RT0603BRD07104KLCT-ND", "104 kOhm 0.1 % 25 ppm/K 0603 thin film",
                         "Vishay TNPW0603104KBEEA is a non-stock reel item at Digi-Key (MOQ 5,000, 2026-11-13); YAGEO "
                         "RT0603BRD07104KL is in stock (0.1 %, 25 ppm/K, 0603)."),
    "SN74LVC2G08DCTR": ("SN74LVC2G08IDCTRQ1", "Texas Instruments", "296-36980-1-ND", None,
                        "SN74LVC2G08DCTR has 0 stock at every authorized distributor (Digi-Key restock 22-Feb-2027, "
                        "2026-11-13); SN74LVC2G08IDCTRQ1 is the AEC-Q100 version in the same SM8 (DCT) package."),
    "SN74LVC1G06DCKR": ("SN74LVC1G06DCKT", "Texas Instruments", "296-32290-1-ND", None,
                        "SN74LVC1G06DCKR had 2 pieces in stock at Digi-Key (2026-11-13); SN74LVC1G06DCKT is the same "
                        "part on a 250-piece reel (1,237 in stock)."),
    "2N7002KT1G": ("2N7002BK,215", "Nexperia USA Inc.", "1727-4789-1-ND",
                   "60 V N-MOSFET, SOT-23, Vgs(th) max 2.1 V",
                   "onsemi 2N7002KT1G has 0 stock at Digi-Key with no restock date (2026-11-13); Nexperia "
                   "2N7002BK,215 has the same SOT-23 pinout and a lower maximum threshold (2.1 V against 2.3 V). "
                   "The Q201 and Q202 gates are pulled to REGN (4.8-5.2 V at VBUS 15 V, SLUSDV2C p.15) through "
                   "R252 and R254 47.0 kOhm and sunk by the open-drain U202 and U201 (gen/netlist.py), not driven "
                   "from 3.3 V. 2N7002BK Vgs(th) max TODO(verify: Nexperia 2N7002BK datasheet). Diodes 2N7002K-7 "
                   "was not taken (Vgs(th) max 2.5 V). (Superseded 2026-11-14, BOM-9: \"which suits the 3.3 V "
                   "gate drive of Q201 and Q202\".)"),
    "GRM1885C1H222JA01D": ("C1608C0G1H222J080AA", "TDK", "445-1297-1-ND", "2.2 nF 50 V C0G 0603",
                           "Murata GRM1885C1H222JA01D has 0 stock at Digi-Key, restock 08-Feb-2027 (2026-11-13); TDK "
                           "C1608C0G1H222J080AA is Digi-Key's direct substitute."),
    "GRM21BR6YA106KE43L": ("GMC21X5R106K50NT", "Cal-Chip Electronics, Inc.", "4713-GMC21X5R106K50NTCT-ND",
                           "10 uF 50 V X5R 0805 (1.50 mm max thickness)",
                           "Murata GRM21BR6YA106KE43L (35 V) has 0 stock at Digi-Key, restock 23-Feb-2027 "
                           "(2026-11-13), and no 10 uF 35 V X5R 0805 was stocked; Cal-Chip GMC21X5R106K50NT (50 V, "
                           "10 %) is stocked by Digi-Key (not the Marketplace listing)."),
    "SMAJ33A": ("SMAJ33A", "Littelfuse Inc.", "SMAJ33ALFCT-ND", None,
                "The upload did not match SMAJ33A without a manufacturer; the Littelfuse part (the datasheet the "
                "row cites) is SMAJ33ALFCT-ND."),
    "08-50-0114": ("0008500113", "Molex", "WM1114CT-ND", "KK 254 crimp socket 2759, 22-30 AWG, tin",
                   "Molex 08-50-0114 is obsolete; 0008500113 (08-50-0113) is the active drop-in (same 2759 terminal, "
                   "22-30 AWG). Digi-Key sells it in cut tape of 100 minimum."),
    "AI 0,5-8 WH": ("3200014", "Phoenix Contact", "277-2185-ND", None,
                    "'AI 0,5-8 WH' is a type designation; Phoenix 3200014 is its order number (sold per piece)."),
    "SSQ-110-01-L-S": ("SSQ-110-01-G-S", "Samtec Inc.", "612-SSQ-110-01-G-S-ND",
                       "SSQ 1x10, 2.54 mm, standard-force contacts (-01), -G plating (gold mating), through-hole; "
                       "mates TSW-110-07-L-S",
                       "SSQ-110-01-L-S is a non-stock item at Digi-Key (est. 04-Jan-2027, 2026-11-13); SSQ-110-01-G-S "
                       "differs only in the heavier gold plating on the contacts, which mates the -L TSW post. Operator "
                       "ruling 2026-11-13 (chat): \"Yes, use -G\"."),
    "SSQ-112-01-L-S": ("SSQ-112-01-G-S", "Samtec Inc.", "612-SSQ-112-01-G-S-ND",
                       "SSQ 1x12, 2.54 mm, standard-force contacts (-01), -G plating (gold mating), through-hole; "
                       "mates TSW-112-07-L-S",
                       "SSQ-112-01-L-S is a non-stock item at Digi-Key (MOQ 1,445, est. 04-Jan-2027, 2026-11-13); "
                       "SSQ-112-01-G-S differs only in the heavier gold plating on the contacts. Operator ruling "
                       "2026-11-13 (chat): \"Yes, use -G\"."),
    # ---- D-67: U101 TCKE1401NM and its divider / current-limit resistors (Mouser order, MOUSER below)
    "TPS26630RGER": ("TCKE1401NM,R1F", "Toshiba", "",
                     "eFuse 4.7-75 V (80 V abs max), 44.5 mOhm, 6 A, adjustable OVP/UVLO/ILIM, IMON, FLAG, latch-off; "
                     "VQFN24D 4 x 4 mm, 0.5 mm, pin- and land-compatible with TPS26630 RGE",
                     "TPS26630RGER has no authorized stock (Digi-Key restock 08-Jul-2027; Mouser and TME 0, 2026-11-13); "
                     "operator ruling 2026-11-13 (chat): \"Use TCKE1401NM for U101\" (D-67, RESPIN_HANDOFF_2026-11-13.md "
                     "section 2). Digi-Key sells it only as a 3,000-piece reel; Mouser sells it from 1 piece."),
    "CRCW06038K06FKEA": ("CRCW06038K45FKEA", "Vishay Dale", "", "8.45 kOhm 1 % 0603 (U101 ILIM)",
                         "D-67: I_LIM = 18.9/R(kOhm) + 0.13 A = 2.37 A typ for TCKE1401NM (DS Formula 9); was 8.06k "
                         "for TPS26630 (2.23 A)."),
    "TNPW060366K5BEEA": ("ERA-3AEB6492V", "Panasonic Industry", "", "64.9 kOhm 0.1 % 25 ppm/K 0603 thin film",
                         "D-67: divider R102/R103/R104 = 845k/64.9k/51.1k for the TCKE1401NM references: OVP 23.19 V, "
                         "UVLO 9.86 V typ. 64.9k because 64.2k 0.1 % is not stocked."),
    "TNPW060349K9BEEA": ("TNPW060351K1BEEA", "Vishay Dale", "", "51.1 kOhm 0.1 % 25 ppm/K 0603 thin film",
                         "D-67: divider R102/R103/R104 = 845k/64.9k/51.1k for the TCKE1401NM references."),
}
# rows ordered from Mouser (D-67): MPN -> Mouser part number (findchips.com listing of Mouser stock, 2026-11-13)
MOUSER = {
    "TCKE1401NM,R1F": "757-TCKE1401NMR1F",        # 1,984 in stock, $4.61 at 1
    "CRCW06038K45FKEA": "71-CRCW0603-8.45K-E3",   # 705,867 in stock, $0.10 at 1
    "ERA-3AEB6492V": "667-ERA-3AEB6492V",         # 1,948 in stock, $0.10 at 1
    "TNPW060351K1BEEA": "71-TNPW060351K1BEEA",    # 6,705 in stock, $0.26 at 1
}
# 2026-11-14 (BOM-11): a netlist MPN equal to the SUBST target of its row is the ordered part
for b, ref, nmpn, rmpn in mpn_pending:
    tgt = SUBST.get(rmpn.strip(), ("",))[0]
    if not (tgt and tgt.replace(" ", "").lower() == nmpn.replace(" ", "").lower()):
        errors.append("%s %s: netlist MPN %r vs row MPN %r" % (b, ref, nmpn, rmpn))
if errors:
    sys.exit("REFUSED:\n  " + "\n  ".join(errors))

# kept on the BOM but held out of the Digi-Key file: no authorized stock (D-67 resolved the U101 hold)
DK_HOLD = {}
# Digi-Key order quantity above the BOM quantity (sellable minimum)
ORDER_QTY = {"0008500113": (100, "Digi-Key cut-tape minimum")}

# Attrition (operator request 2026-11-13: "include an attrition rate for the small inexpensive components so that I
# have extras of anything inexpensive"). The Digi-Key order quantity, never the per-unit BOM quantity, follows the
# Digi-Key unit price at quantity 1: <= $0.25 orders at least 10 and at least 1.5 x the BOM quantity; $0.25 to
# $1.00 orders the BOM quantity + 25 % (at least + 2); above $1.00 orders the BOM quantity.
# Unit prices: the upload result for unchanged lines; read on the live product pages on 2026-11-13 for the
# replacements below.
PRICE_Q1 = {
    "C0603C223K5RACTU": 0.12, "CL21B105KBFNNNF": 0.14, "CL21B106KOQNNNE": 0.27, "CL31B105KCHSFNE": 0.41,
    "CNC6P1X7R2A475K250AE": 1.47, "BAV199-7-F": 0.30, "ERA-3AEB5622V": 0.11, "ERA-6AEB103V": 0.10,
    "ERA-6AEB8453V": 0.10, "ERA-6AEB4873V": 0.10, "RT0603BRD07104KL": 0.10, "SN74LVC2G08IDCTRQ1": 0.77,
    "SN74LVC1G06DCKT": 0.93, "2N7002BK,215": 0.19, "C1608C0G1H222J080AA": 0.17, "GMC21X5R106K50NT": 1.76,
    "SMAJ33A": 0.47, "3200014": 0.18, "SSQ-110-01-G-S": 2.56, "SSQ-112-01-G-S": 3.05,
    "GRM188R72A104KA35D": 0.16,
    "TCKE1401NM,R1F": 4.61, "CRCW06038K45FKEA": 0.10, "ERA-3AEB6492V": 0.10, "TNPW060351K1BEEA": 0.26,
}
CHEAP, MID = 0.25, 1.00


def order_qty(qty, price):
    if price is None or price > MID:
        return qty
    if price <= CHEAP:
        return max(10, -(-qty * 3 // 2))
    return qty + max(2, -(-qty // 4))

subst_log = []
for b in ("cr", "eib", "system"):
    for r in out_rows[b]:
        old = r[C["Mft. SKU"]].strip()
        if old not in SUBST:
            continue
        new, mfr, sku, spec, why = SUBST[old]
        r[C["Mft. SKU"]], r[C["Manufacturer"]], r[C["Vendor SKU"]] = new, mfr, sku
        if spec:
            r[C["Specification"]] = spec
        r[C["Datasheet"]] = ""
        if new in MOUSER:
            r[C["Vendor"]], r[C["Vendor SKU"]] = "Mouser", MOUSER[new]
            r[C["Link"]] = "https://www.mouser.com/c/?q=" + new.replace(" ", "%20").replace(",", "%2C")
            r[C["Notes"]] = "Replaced 2026-11-13 (D-67, U101 change): %s %s" % (why, r[C["Notes"]])
        else:
            r[C["Vendor"]] = "Digikey"
            r[C["Link"]] = "https://www.digikey.com/en/products/result?keywords=" + new.replace(" ", "%20")
            r[C["Notes"]] = "Replaced 2026-11-13 (Digi-Key upload review): %s %s" % (why, r[C["Notes"]])
        subst_log.append((b, old, new))

# Digi-Key part numbers of the unchanged rows, from the upload result (keyed by the requested MPN)
UPLOAD = os.path.join(OUT if os.path.exists(os.path.join(OUT, "digikey_upload_result_2026-11-13.csv"))
                      else "bom_2026-11-13", "digikey_upload_result_2026-11-13.csv")
dk_pn = {}
if os.path.exists(UPLOAD):
    for u in csv.DictReader(open(UPLOAD, encoding="utf-8")):
        if u["Digi-Key Part Number"] and u["Part Status"] != "Obsolete":
            dk_pn[u["Requested Part Number"]] = u["Digi-Key Part Number"]
            if u["Unit Price"] and u["Requested Part Number"] not in PRICE_Q1:
                PRICE_Q1[u["Requested Part Number"]] = float(u["Unit Price"])
for b in ("cr", "eib", "system"):
    for r in out_rows[b]:
        mpn = r[C["Mft. SKU"]].strip()
        # 2026-11-14 (BOM-10): also when the MPN is a SUBST target but the row has no SKU (C102c)
        if mpn in dk_pn and (mpn not in {s[0] for s in SUBST.values()} or not r[C["Vendor SKU"]].strip()):
            r[C["Vendor SKU"]] = dk_pn[mpn]

# ---- 2026-11-14 round: rated voltage, row notes, PLT1M-C (BOM-3, BOM-4, BOM-6, BOM-8, sim 3, decisions) ----------
# Voltage Max [V] of the substituted parts (BOM-3). Sources: Digi-Key descriptions of the 13b upload result
# (GRM188R72A104KA35D 'CAP CER 0.1UF 100V', CL21B106KOQNNNE 'CAP CER 10UF 16V', GMC21X5R106K50NT 'CAP0805 X5R 10UF
# 10% 50V'); TCKE1401NM DS Rev. 3.0 Table 9.1, input voltage operating range 4.7 to 75 V.
VMAX = {"GRM188R72A104KA35D": "100", "CL21B106KOQNNNE": "16", "GMC21X5R106K50NT": "50", "TCKE1401NM,R1F": "75"}
UPLOAD_B = os.path.join("bom_2026-11-13", "digikey_upload_result_2026-11-13b.csv")
dk_desc = {}
if os.path.exists(UPLOAD_B):
    for u in csv.DictReader(open(UPLOAD_B, encoding="utf-8")):
        dk_desc[u["Digi-Key Part Number"]] = u["Description"]
BOILER = [r"No Digi-Key product page URL was found; Link is the Digi-Key keyword search; Vendor SKU blank\.\s*",
          r"Price and stock not read: digikey\.com, mouser\.com, newark\.com, arrow\.com and octopart\.com served "
          r"bot-check or 403 pages to the built-in browser on 2026-11-11\.\s*",
          r"Price and stock not read\.\s*",
          r"Link and Vendor SKU from the digikey\.com search-engine index, not read on the live page; confirm before "
          r"ordering\.\s*",
          r"Vendor SKU from the search-engine index; no product page URL found \(Link is the keyword search\)\.\s*",
          r"Only the tape-and-reel SKU 296-13278-2-ND was seen in the index; the cut-tape SKU was not seen, so Vendor "
          r"SKU is blank\.\s*",
          r"Index snippets disagree on stock \(one shows backorder\)\.\s*",
          r"Search-index snippet \(undated\) reported Digi-Key stock 0 with a restock date in 2027; availability is a "
          r"risk - TODO\(verify\)\.\s*",
          r"Product URL from a digikey\.jp index entry\.\s*",
          # phase C (R2-BOM-1): the lower-case J102 variant
          r"Link is the Digi-Key keyword search for [^;]+; Vendor SKU blank; price and stock not read\.\s*"]
MURATA_V = r"Voltage from the Murata part code \(TODO\(verify\) on the spec sheet; murata\.com returned 403\)\.\s*"
# wrong-board fragments of shared ordering rows (BOM-4): (board, MPN) -> patterns
DROP = {
    ("eib", "CRCW06031K00FKEA"): [r"r9 \(2026-11-12\): R121, R125.*?the spare kept\)\.\s*",
                                  r"Power: the R106s design dissipation.*?TODO\(verify: doc 20035\)\.\s*"],
    ("eib", "GRM188R72A104KA35D"): [r"r9 \(2026-11-12\): C109, C112.*?\(D-38, 2026-11-12\)\.\s*",
                                    r" and is already the C102c part, so the two lines merge"],
    ("eib", "CRCW060310K0FKEA"): [r"r9 \(2026-11-12\): R118 and R120 removed.*?R274 stays fitted\.\s*"],
    ("eib", "CRCW060347K0FKEA"): [r"r9 \(2026-11-12\): R124 \(FCCEIL\) removed \(tap review\)\.\s*"],
    ("system", "CRCW060347K0FKEA"): [r"r9 \(2026-11-12\): R124 \(FCCEIL\) removed \(tap review\)\.\s*"],
}
# stale statements on settled parts (BOM-4): MPN -> [(pattern, replacement)]
REWRITE = {
    "CL31B105KCHSFNE": [(r"Voltage rating 100 V: confirmed by distributor listings.*?\(T-A-04/T-A-05\)\.\s*", ""),
                        (r"FLAG: Octopart.*?TODO\(verify: TDK datasheet\)\.\s*", "")],
    "CNC6P1X7R2A475K250AE": [(r"Voltage rating 100 V: confirmed by distributor listings.*?\(T-A-04/T-A-05\)\.\s*", ""),
                             (r"FLAG: Buerklin.*?2 x 2\.2 uF 100 V 1210\.\s*", ""),
                             (r"Full MPN of the section E 'C3225X7S2A475K class'\.\s*", "")],
    "ERA-3AEB6492V": [(r"Range checked in Vishay TNPW e3 datasheet doc 28758 \(rev 10-Apr-2026\): 0603 0\.1 %/25 ppm "
                       r"covers 3\.5 Ohm to 332 kOhm; 66\.5 k in range; packaging code EA as on the other 0603 TNPW "
                       r"rows\.\s*",
                       "Panasonic ERA-3A resistance range for 64.9 kOhm 0.1 %/25 ppm TODO(verify: Panasonic ERA-3A "
                       "datasheet). ")],
    "TNPW060351K1BEEA": [(r"49\.9 k in range", "51.1 k in range")],
    "STPS2H100A": [(r"candidate - T-A-05 datasheet check required\.\s*",
                    "Ordered part (2026-11-14 decision); T-A-05 still reads IR at 23.6 V / 60 C from the IR(VR) curve. "
                    "(Superseded 2026-11-15, R2-BOM-1: \"candidate - T-A-05 datasheet check required.\") "),
                   (r"The netlist \(gen/netlist\.py, cr\.net\) and design section E leave the D103 MPN open.*$",
                    "Since 2026-11-14 the netlist, the board fields and design section E (r9-25 D103 row) carry "
                    "STPS2H100A (BOM-11). (Superseded 2026-11-15, R2-BOM-1: \"design section E still reads "
                    "'selected in T-A-05' (records step)\".)")],
    # phase C (2026-11-15, REVIEW2 R2-BOM-1): stale statements on settled parts
    "C0603C223K5RACTU": [(r"TODO\(verify: Murata\) GRM188R71H223KA01D \(22 nF 50 V X7R 0603\): part number from the "
                          r"decision record, not read on a Murata or distributor page\.\s*", ""),
                         (r"Datasheet URL follows the Murata product-page pattern for the 0603 part, not opened, "
                          r"TODO\(verify: Murata\)\.\s*", "")],
    "BAV199-7-F": [(r"Index snippet \(undated\) showed Digi-Key out of stock with restock 08-Dec-2026; listed direct "
                    r"substitutes are Diodes BAV199-7-F and onsemi BAV199LT1G - TODO\(verify\) leakage equivalence in "
                    r"T-A-05 before substituting\.\s*",
                    "The substitution to BAV199-7-F is made (2026-11-13). Confirm the leakage of the fitted part in "
                    "T-A-05, TODO(verify: Diodes BAV199 datasheet IR at 75 V). ")],
    "43045-1012": [(r"T5 \(A4\) is diagonal to T10 \(B5\): the gate rule \(T5/T6/T10 pairwise non-adjacent\) is met, "
                    r"the recommended diagonal separation is not - open item for operator confirmation\.\s*",
                    "T5 (A4) is diagonal to T10 (B5): the gate rule (T5/T6/T10 pairwise non-adjacent) is met, the "
                    "recommended diagonal separation is not; accepted by the operator 2026-11-12 (gen/netlist.py J102 "
                    "comment). ")],
    "CRCW06034K99FKEA": [(r"The MPN follows the CRCW0603 code pattern of the other rows, TODO\(verify: Vishay doc "
                          r"20035 ordering code\)\.\s*",
                          "Ordering code confirmed by the 13b upload match: 541-4.99KHCT-ND, \"RES SMD 4.99K OHM 1% "
                          "1/10W 0603\" (bom_2026-11-13/digikey_upload_result_2026-11-13b.csv). ")],
    "SN74LVC1G11DBVR": [(r"TODO\(verify: TI SN74LVC1G11 Pin Functions table\) the DBV pinout against the DCK pinout, "
                         r"and re-check B\.8 pin by pin\.\s*",
                         "DBV pinout closed: TI SCES487I (revised November 2024) Figure 4-1 and Table 4-1 give one "
                         "pinout for DBV and DCK (A 1, GND 2, B 3, Y 4, VCC 5, C 6), as captured in gen/netlist.py "
                         "lvc1g11() and on the U107 pads (LAYOUT_DECISIONS section 11 item 18; re-read 2026-11-15, "
                         "R2-LOG-1). ")],
}
MOUSER_SRC = ("Mouser part number, stock and price from the Mouser listing on findchips.com, 2026-11-13 "
              "(bom_2026-11-13/README.md section 4.8).")
# notes added in the 2026-11-14 round: (board, MPN) -> text appended
ADD = {
    ("cr", "STPS2H100A"): "Alternate (2026-11-14 decision, not adopted; operator question): onsemi MBRA2H100T3G, "
                          "same D_SMA land, pin 1 = cathode, IFSM 130 A; like STPS2H100A it fails the T-A-05 "
                          "'VF at 3 A <= 0.5 V' limit, and the 130 A / 1 us pulse rating is open for both "
                          "(sim/hardshort/RESULTS.md). It is the opt-in ALT D103 line of digikey_optional.csv (2 parts for a test fit, "
                          "order 3).",
    ("cr", "GRM1885C1H102JA01D"): "Option at assembly (2026-11-14 decision, not adopted): C108 = 470 pF "
                                  "GRM1885C1H471JA01D, a partial T2-race improvement only (bom_2026-11-14/README.md "
                                  "section 5.3); opt-in ALT C108 line of digikey_optional.csv. C129 stays 1.0 nF.",
    ("cr", "CRCW0603100RFKEA"): "2026-11-14 decision (not adopted: raise to 3.16-10.5 kOhm): R130 and R131A stay "
                                "100 Ohm. The former R131A reason 'conductor 7 has no GND neighbour' is void under "
                                "D-66: a CR 7-3 bridge pulls the CR rail to 1.98-2.36 V (sim/permit/RESULTS.md Table "
                                "5.6). The W5 grid mitigation is an operator question.",
    ("cr", "TLV3012BIDBVR"): "B suffix required, no non-B substitute (SBOS300C 9.4.4; sim/comparators/RESULTS.md "
                             "section 5.6: the BAV199 clamp level 3.75-4.03 V exceeds the non-B V+ + 0.5 V absolute "
                             "maximum).",
    ("cr", "SN74LVC2G08IDCTRQ1"): "Operating range -40 to 85 C (SCES557E p.14 package option addendum); no "
                                  "requirement above 85 C was found (REVIEW_2026-11-14 BOM-8).",
    ("cr", "TCKE1401NM,R1F"): "Voltage Max 75 V: TCKE1401NM DS Rev. 3.0 Table 9.1 (input voltage 4.7 to 75 V); "
                              "80 V absolute maximum (Table 8.1).",
    ("cr", "43045-1012"): "Mate (phase C 2026-11-15, R2-INT-5): built from workshop stock (operator ruling "
                          "2026-11-13); the Molex 2147561101 cable is not ordered (digikey_skipped.csv). The wire "
                          "gauge against the R170/R171 joints is TODO(verify: workshop wire, T-A-05).",
}


def clean_notes(b, r):
    mpn, n = r[C["Mft. SKU"]].strip(), r[C["Notes"]]
    sku, vendor = r[C["Vendor SKU"]].strip(), r[C["Vendor"]].strip().lower()
    if sku:
        for p in BOILER:
            n = re.sub(p, "", n)
        if vendor == "mouser":
            n = n.rstrip() + " " + MOUSER_SRC
        elif sku in dk_desc:
            n = n.rstrip() + " Digi-Key part number, stock and price from the upload result of 2026-11-13 " \
                "(bom_2026-11-13/digikey_upload_result_2026-11-13b.csv)."
    if sku in dk_desc:
        n = re.sub(MURATA_V, "Voltage rating from the Digi-Key description '%s' (upload result 2026-11-13b). "
                   % dk_desc[sku], n)
    for p in DROP.get((b, mpn), []):
        n = re.sub(p, "", n)
    for p, rep in REWRITE.get(mpn, []):
        n = re.sub(p, rep, n)
    if (b, mpn) in ADD:
        n = n.rstrip() + " " + ADD[(b, mpn)]
    r[C["Notes"]] = re.sub(r"\s{2,}", " ", n).strip()
    if mpn in VMAX:
        r[C["Voltage Max [V]"]] = VMAX[mpn]


for b in ("cr", "eib", "system"):
    for r in out_rows[b]:
        clean_notes(b, r)
        if r[C["Mft. SKU"]].strip() == "PLT1M-C":            # BOM-6: sold and counted per tie
            r[C["BOM Units"]] = "ea"
            r[C["Specification"]] = "Panduit Pan-Ty miniature cable tie, 2.5 mm wide, natural, one tie"
            r[C["Notes"]] = re.sub(r"One 100-pack \(PLT1M-C is a 100-piece pack, TODO\(verify\)\)\.\s*", "",
                                   r[C["Notes"]])
PRICE_Q1["PLT1M-C"] = 0.229                                 # 13b upload result (Bulk, MOQ 1)

os.makedirs(OUT, exist_ok=True)
SUMMARY = ["Total Assembly Cost:", "$0.00", "", "PCB components:", "", "PCB unique parts:", ""]


def write(name, rs, b=None):
    rs = sorted(rs, key=lambda r: (r[C["Category"]] == "PCB", r[C["Category"]] == "Assembly"))
    s = list(SUMMARY)
    if b:
        fitted = sum(int(r[C["BOM Qty"]]) for r in rs if r[C["Category"]] not in ("PCB", "Assembly"))
        mpns = {r[C["Mft. SKU"]] for r in rs if r[C["Category"]] not in ("PCB", "Assembly")}
        s[4], s[6] = str(fitted), str(len(mpns))
    with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(HDR[:35] + s)
        for r in rs:
            w.writerow(r[:35] + [""] * 7)
    return rs


cr = write("cr_bom.csv", out_rows["cr"], "cr")
eib = write("eib_bom.csv", out_rows["eib"], "eib")
sysr = write("system_bom.csv", out_rows["system"])

# Digi-Key import: identified MPNs at Digi-Key, merged by MPN
dk = OrderedDict()
mo = OrderedDict()   # Mouser lines (D-67)
skipped = [("SYS", r[C["Part"]], r[C["Mft. SKU"]].strip(), "workshop stock (operator ruling 2026-11-13; off the BOM)")
           for r in workshop] + [(t, r[C["Part"]], r[C["Mft. SKU"]].strip(), "off the BOM: " + why) for t, r, why in ruled]
for tag, rs in (("CR", cr), ("EIB", eib), ("SYS", sysr)):
    for r in rs:
        mpn, vendor = r[C["Mft. SKU"]].strip(), r[C["Vendor"]]
        if mpn in DK_HOLD:
            skipped.append((tag, r[C["Part"]], mpn, "held out of the Digi-Key file: " + DK_HOLD[mpn]))
            continue
        if vendor.strip().lower() == "mouser":
            target = mo
        elif "digi" not in vendor.lower() or not mpn or "NOT IDENTIFIED" in mpn.upper() or r[C["Category"]] == "PCB":
            skipped.append((tag, r[C["Part"]], mpn, vendor))
            continue
        else:
            target = dk
        e = target.setdefault(mpn, dict(qty=0, sku=r[C["Vendor SKU"]].strip(), mfr=r[C["Manufacturer"]].strip(),
                                    desc=r[C["Specification"]].strip(), uses=OrderedDict(), refs=[]))
        q = int(r[C["BOM Qty"]])
        e["qty"] += q
        e["uses"][tag] = e["uses"].get(tag, 0) + q
        if not e["sku"]:
            e["sku"] = r[C["Vendor SKU"]].strip()
        names = r[C["PCB Names"]].strip()
        e["refs"].append("%s: %s" % (tag, names))
        e.setdefault("groups", []).append((tag, names, q))

# Customer Reference: Digi-Key prints it on the bag label and accepts at most 48 characters. It carries the
# reference designators of the line, so a bag can be matched to the parts at assembly. CR parts are numbered
# 1xx and EIB parts 2xx, so the designators are unique across the two boards.
CREF_MAX = 48
# system rows whose part name does not fit: a shorter name for the bag label
SYS_CREF = {
    "J102 mate: J-TAP leads T1, T2, T5, T6, T7b, T10, T13, T16, T17, T17r": "J102 mate (J-TAP cable, leads T1-T17r)",
    "W3/W4 or W1/W2 terminal ends (if terminated in a screw terminal)": "Ferrules: W1-W4 screw-terminal ends",
    "20 AWG lead ends (if terminated in a screw terminal)": "Ferrules: 20 AWG screw-terminal lead ends",
}
REF_RE = re.compile(r"^([A-Z]+)(\d+)([A-Za-z]*)$")


def compress(names):
    """'C110,C111,C114,C115,C116' -> 'C110,111,114-116': runs of 3 or more consecutive numbers become a range, and
    the letter prefix is written only where it changes. Tokens that are not plain designators stay as written."""
    toks = [t.strip() for t in names.split(",") if t.strip()]
    out, prev, i = [], None, 0
    while i < len(toks):
        m = REF_RE.match(toks[i])
        if not m:
            out.append(toks[i]); prev = None; i += 1
            continue
        pre, num, suf = m.group(1), int(m.group(2)), m.group(3)
        j = i
        if not suf:
            while j + 1 < len(toks):
                n = REF_RE.match(toks[j + 1])
                if not (n and n.group(1) == pre and not n.group(3) and int(n.group(2)) == num + (j + 1 - i)):
                    break
                j += 1
        head = ("" if pre == prev else pre) + str(num) + suf
        if j - i >= 2:
            out.append("%s-%d" % (head, num + j - i)); i = j + 1
        else:
            out.append(head); i += 1
        prev = pre
    return ",".join(out)


def merge_tags(groups):
    """Join the groups of one tag (for example the C102c row and the 100 nF row after the 2026-11-13 merge)."""
    out = OrderedDict()
    for tag, names, q in groups:
        t = out.setdefault(tag, [[], 0])
        t[0].append(names); t[1] += q
    return [(tag, ",".join(n), q) for tag, (n, q) in out.items()]


def customer_ref(groups):
    """The short designator text, or None when it does not fit in CREF_MAX characters."""
    parts = []
    for tag, names, _ in groups:
        if tag == "SYS":  # system names are mostly free text: kept as written unless too long
            parts.append(SYS_CREF.get(names, names))
        else:
            parts.append(compress(names))
    labelled = " ".join(("%s %s" % (g[0], p)) if g[0] != "SYS" else p for g, p in zip(groups, parts))
    if len(labelled) <= CREF_MAX:
        return labelled
    bare = ",".join(parts)  # CR 1xx and EIB 2xx designators do not collide
    return bare if len(bare) <= CREF_MAX else None


DESC_MAX = 120
# phase C (R2-BOM-6): a shorter description where the word-boundary cut would drop a load-bearing clause
DESC_SHORT = {"43045-1012": "Molex Micro-Fit 3.0 43045-1012, vertical header, 3.00 mm pitch, dual row, 10 circuits, "
                            "PCB pegs, tin, 8.5 A per contact"}


def desc120(mpn, d):
    """The Description cell: at most DESC_MAX characters, cut at a word boundary (phase C, R2-BOM-6; was d[:120],
    which cut 'tin, 8.5 A p' and '-L plating ' mid-clause)."""
    d = DESC_SHORT.get(mpn, d)
    if len(d) <= DESC_MAX:
        return d
    cut = d[:DESC_MAX]
    if d[DESC_MAX] not in " ,;)":
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;(-")


with open(os.path.join(OUT, "digikey_import.csv"), "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["Quantity", "Digi-Key Part Number", "Manufacturer Part Number", "Manufacturer", "Description",
                "Customer Reference", "Reference Designators", "BOM Quantity", "Unit Price (qty 1, 2026-11-13)"])
    for mpn, e in dk.items():
        groups = merge_tags(e["groups"])
        cref = customer_ref(groups)
        # a part whose designators do not fit one label gets one line (one bag) per BOM
        lines = [(e["qty"], cref, e["refs"])] if cref else [
            (q, customer_ref([(t, n, q)]), [x for x in e["refs"] if x.startswith(t + ":")]) for t, n, q in groups]
        for qty, cr_, refs in lines:
            assert cr_ and len(cr_) <= CREF_MAX, ("Customer Reference over %d characters" % CREF_MAX, mpn)
            bom_q, price = qty, PRICE_Q1.get(mpn)
            qty = order_qty(qty, price)
            if mpn in ORDER_QTY:
                qty = max(qty, ORDER_QTY[mpn][0])
            w.writerow([qty, e["sku"], mpn, e["mfr"], desc120(mpn, e["desc"]), cr_, "; ".join(refs), bom_q,
                        "" if price is None else "%.2f" % price])

# ALTERNATES (2026-11-14 decisions, adopt_change false): explicitly labelled lines, not fitted by default. They go to
# the opt-in file digikey_optional.csv, not to digikey_import.csv (fix round 2026-11-15, check1 issue 8): an opt-out
# line could reach the order unnoticed, and the ALT C108 line shares 490-1443-1-ND with the C106/C107 main line, which
# a Digi-Key list upload can merge into one line of the summed quantity. BOM Quantity: ALT C108 is one per CR of the
# order of 6; ALT D103 is 2, a test fit on two CRs (the 2026-11-14 D103 decision recommends 2-3 parts for an operator
# question; check1 issue 1), with an explicit order quantity of 3; the bench lines are the bench count. Without an
# explicit order quantity the attrition rule applies.
# (Digi-Key PN, MPN, manufacturer, description, Customer Reference, designators, BOM qty, USD price at 1 or None,
#  explicit order qty or None)
ALTERNATES = [
    ("MBRA2H100T3GOSCT-ND", "MBRA2H100T3G", "onsemi",
     "ALTERNATE D103 (operator question 2026-11-14): Schottky 100 V 2 A SMA; not fitted by default",
     "ALT D103 MBRA2H100T3G (test fit 2 CR)", "CR: D103 alternate, test fit on 2 CRs", 2, 0.98, 3),
    ("490-1443-1-ND", "GRM1885C1H471JA01D", "Murata Electronics",
     "ALTERNATE C108 470 pF 50 V C0G 0603 (option at assembly 2026-11-14)",
     "ALT C108 470pF option (6 CR)", "CR: C108 alternate x 6 CR", 6, 0.069, None),
    ("490-9669-1-ND", "GRM1885C1H472JA01D", "Murata Electronics",
     "BENCH ONLY 4.7 nF 50 V C0G 0603 (C107 brief-interruption test 2026-11-14); never fit in service",
     "BENCH C107 4.7nF test only", "bench: C107 test", 4, 0.11, None),
    ("490-9666-1-ND", "GRM1885C1H103JA01D", "Murata Electronics",
     "BENCH ONLY 10 nF 50 V C0G 0603 (sim 4 section 8 test 2, 2026-11-14); never fit in service",
     "BENCH C106/C107 10nF test only", "bench: C106/C107 test", 4, None, None),
    # phase C (2026-11-15) SPARE lines: opt-in, never in digikey_import.csv. They share the Digi-Key part number of
    # a main line, so a list upload may merge them into that line; for a spare the merged quantity is the intended
    # total. Unit prices: the 13b upload result (bom_2026-11-13/digikey_upload_result_2026-11-13b.csv).
    # R2-BOM-5: the B suffix has no substitute (cr_bom.csv U102 note; sim/comparators/RESULTS.md section 5.6), and the
    # main line orders exactly the 4 fitted parts ($2.78 > $1.00, no attrition).
    ("296-TLV3012BIDBVRCT-ND", "TLV3012BIDBVR", "Texas Instruments",
     "SPARE comparator + ref, push-pull, SOT-23-6 (B suffix required, no substitute)",
     "SPARE U102,103,119,120 TLV3012B x2", "CR: spare for U102,U103,U119,U120", 2, 2.78, 2),
    # R2-CRT-1 / BOM-7: the main line orders exactly 7 (MB 2 + EVM 5); design section E promises 2 (+2) and 5 (+3)
    ("4713-GMC21X5R106K50NTCT-ND", "GMC21X5R106K50NT", "Cal-Chip Electronics, Inc.",
     "SPARE 10 uF 50 V X5R 0805 (1.50 mm max thickness), the section E spares (+2 MB, +3 EVM)",
     "SPARE C (MB) +2, C (EVM) +3", "SYS: spare for C (MB) x2, C (EVM) x5", 5, 1.76, 5),
    # R2-BOM-0: one CR needs one TSW-110 and one TSW-112 (J1 pads 1-10 and 11-22, gen/netlist.py J1); the main lines
    # order 3 x TSW-110 (attrition) and 1 x TSW-112, so the extra 1x10 strips have no 1x12 partner. One TSW-112 more
    # makes a second matched J1 set.
    ("612-TSW-112-07-L-S-ND", "TSW-112-07-L-S", "Samtec",
     "SPARE TSW 1x12, 2.54 mm, -07, -L plating: second matched J1 set with a main-line TSW-110",
     "SPARE CR J1 TSW-112 (2nd matched set)", "CR: J1 spare 1x12", 1, 1.10, 1),
    # R2-BOM-0: one MB takes one SSQ-110 and one SSQ-112; the main lines order exactly one each
    ("612-SSQ-110-01-G-S-ND", "SSQ-110-01-G-S", "Samtec Inc.",
     "SPARE SSQ 1x10, 2.54 mm, -01, -G plating, through-hole; mates TSW-110-07-L-S",
     "SPARE MB CHG socket 1x10", "SYS: spare MB CHG socket 1x10", 1, 2.56, 1),
    ("612-SSQ-112-01-G-S-ND", "SSQ-112-01-G-S", "Samtec Inc.",
     "SPARE SSQ 1x12, 2.54 mm, -01, -G plating, through-hole; mates TSW-112-07-L-S",
     "SPARE MB CHG socket 1x12", "SYS: spare MB CHG socket 1x12", 1, 3.05, 1),
]
# the 10 nF line has no USD price read (digikey.co.uk 2026-11-15: GBP 0.10 at 1); it is ordered as a <= $0.25 part
ALT_CHEAP = {"GRM1885C1H103JA01D"}
with open(os.path.join(OUT, "digikey_optional.csv"), "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["Quantity", "Digi-Key Part Number", "Manufacturer Part Number", "Manufacturer", "Description",
                "Customer Reference", "Reference Designators", "BOM Quantity", "Unit Price (qty 1, 2026-11-13)"])
    for sku, mpn, mfr, desc, cref, refs, q, price, oq in ALTERNATES:
        assert len(cref) <= CREF_MAX, cref
        if oq is None:
            oq = order_qty(q, 0.25 if mpn in ALT_CHEAP else price)
        w.writerow([oq, sku, mpn, mfr, desc120(mpn, desc), cref, refs, q, "" if price is None else "%.2f" % price])

# Mouser import (D-67): the rows whose vendor is Mouser, with the same Customer Part Number text, attrition rule and
# extra columns as the Digi-Key file. Mouser's BOM tool maps the columns at upload.
with open(os.path.join(OUT, "mouser_import.csv"), "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["Mouser Part Number", "Manufacturer Part Number", "Manufacturer", "Description", "Quantity",
                "Customer Part Number", "Reference Designators", "BOM Quantity", "Unit Price (qty 1, 2026-11-13)"])
    for mpn, e in mo.items():
        groups = merge_tags(e["groups"])
        cref = customer_ref(groups)
        assert cref, ("Mouser Customer Part Number too long", mpn)
        price = PRICE_Q1.get(mpn)
        w.writerow([e["sku"], mpn, e["mfr"], desc120(mpn, e["desc"]), order_qty(e["qty"], price), cref, "; ".join(e["refs"]),
                    e["qty"], "" if price is None else "%.2f" % price])
with open(os.path.join(OUT, "digikey_skipped.csv"), "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["BOM", "Part", "MPN", "Vendor"])
    w.writerows(skipped)
opt_total = 0.0
for sku, mpn, mfr, desc, cref, refs, q, price, oq in ALTERNATES:
    oq = oq if oq is not None else order_qty(q, 0.25 if mpn in ALT_CHEAP else price)
    opt_total += oq * (price if price is not None else 0.0)
print("optional lines at qty-1 prices: USD %.2f (lines without a USD price excluded)" % opt_total)
print("cr rows %d (parts %d), eib rows %d (parts %d), system rows %d, digikey lines %d, optional lines %d, "
      "mouser lines %d, skipped %d" % (
          len(cr), sum(int(r[C["BOM Qty"]]) for r in cr if r[C["Category"]] not in ("PCB", "Assembly")),
          len(eib), sum(int(r[C["BOM Qty"]]) for r in eib if r[C["Category"]] not in ("PCB", "Assembly")),
          len(sysr), len(dk), len(ALTERNATES), len(mo), len(skipped)))
