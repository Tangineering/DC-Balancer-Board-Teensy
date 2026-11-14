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
"""
import csv
import os
import re
import sys
from collections import OrderedDict, defaultdict

OUT = sys.argv[1]
SRC = "bom_2026-11-11/ordering_bom.csv"
NON_PART = ("W", "E")                     # lead pads (W1-W7 on the CR, E1-E8 on the EIB)


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
used = set()
board_rows = {}
for b, parts in boards.items():
    fitted = [ref for ref, p in parts.items() if not p["dnp"] and not ref.startswith(NON_PART)]
    groups = OrderedDict()
    for ref in fitted:
        ks = by_ref.get(ref)
        if not ks:
            errors.append("%s %s: no ordering-BOM row names it" % (b, ref))
            continue
        nm = parts[ref]["mpn"].replace(" ", "").lower()
        for k in ks:
            row_mpn = DATA[k][C["Mft. SKU"]].replace(" ", "").lower()
            # the netlist may carry a placeholder (T-A-05 class) or the MPN without its packaging suffix
            if nm and row_mpn not in nm and not row_mpn.startswith(nm) and not re.search(r"t-a-05|class|selected", nm):
                errors.append("%s %s: netlist MPN %r vs row MPN %r" % (b, ref, parts[ref]["mpn"], DATA[k][C["Mft. SKU"]]))
            groups.setdefault(k, []).append(ref)
            used.add(k)
    board_rows[b] = groups

# the board rows, restated from the fab package READMEs (the 2026-11-11 rows describe the pre-trim CR and the
# pre-D-25 EIB outline)
PCB_SPEC = {
    "cr": ("4-layer, 1.6 mm, 1 oz outer / 0.5 oz inner (OSH Park 4-layer, D-29), ENIG; 10-corner outline with 1.0 mm "
           "fillets (D-62), 40.02 x 64.81 mm bounding box, 2327.7 mm2; four 3.70 mm NPTH for 6-32 (MH1-MH4, D-60)",
           "Order 6 (operator ruling 2026-11-13: \"Use 6\"; OSH Park sells boards in multiples of 3). Upload: "
           "fab/cr_2026-11-13b_oshpark/cr_oshpark_gerbers.zip (the board after the operator's routing cleanup); "
           "fab/cr_2026-11-13/ is the package of the board before that cleanup.", "OSH Park"),
    "eib": ("2-layer, 1.6 mm, 1 oz, ENIG, 24.0 x 38.0 mm (D-25), two M3 holes; AGND pours on both layers stitched "
            "by vias (D-63)",
            "A separate 2-layer order at OSH Park (not on the CR panel). OSH Park sells boards in multiples of 3; the "
            "E BOM asks for 5; order quantity TODO(operator). Upload: fab/eib_2026-11-13/kikit_oshpark/gerbers.zip.",
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
    if cat == "PCB":
        b = "cr" if r[C["PCB Names"]].strip() == "CR" else "eib"
        r = list(r)
        r[C["Specification"]], r[C["Notes"]], r[C["Vendor"]] = PCB_SPEC[b]
        out_rows[b].append(per_unit(r, 1, None, "Per-unit qty = 1 board."))
        continue
    if cat == "Assembly":                                  # the CR stencil
        out_rows["cr"].append(per_unit(r, 1, None, "Per-unit qty = 1."))
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

if errors:
    sys.exit("REFUSED:\n  " + "\n  ".join(errors))

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
skipped = []
for tag, rs in (("CR", cr), ("EIB", eib), ("SYS", sysr)):
    for r in rs:
        mpn, vendor = r[C["Mft. SKU"]].strip(), r[C["Vendor"]]
        if "digi" not in vendor.lower() or not mpn or "NOT IDENTIFIED" in mpn.upper() or r[C["Category"]] == "PCB":
            skipped.append((tag, r[C["Part"]], mpn, vendor))
            continue
        e = dk.setdefault(mpn, dict(qty=0, sku=r[C["Vendor SKU"]].strip(), mfr=r[C["Manufacturer"]].strip(),
                                    desc=r[C["Specification"]].strip(), uses=OrderedDict(), refs=[]))
        q = int(r[C["BOM Qty"]])
        e["qty"] += q
        e["uses"][tag] = e["uses"].get(tag, 0) + q
        if not e["sku"]:
            e["sku"] = r[C["Vendor SKU"]].strip()
        names = r[C["PCB Names"]].strip()
        e["refs"].append("%s: %s" % (tag, names))
with open(os.path.join(OUT, "digikey_import.csv"), "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["Quantity", "Digi-Key Part Number", "Manufacturer Part Number", "Manufacturer", "Description",
                "Customer Reference", "Reference Designators"])
    for mpn, e in dk.items():
        cref = " ".join("%s x%d" % (t, n) for t, n in e["uses"].items())
        w.writerow([e["qty"], e["sku"], mpn, e["mfr"], e["desc"][:120], cref[:48], "; ".join(e["refs"])])
with open(os.path.join(OUT, "digikey_skipped.csv"), "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["BOM", "Part", "MPN", "Vendor"])
    w.writerows(skipped)
print("cr rows %d (parts %d), eib rows %d (parts %d), system rows %d, digikey lines %d, skipped %d" % (
    len(cr), sum(int(r[C["BOM Qty"]]) for r in cr if r[C["Category"]] not in ("PCB", "Assembly")),
    len(eib), sum(int(r[C["BOM Qty"]]) for r in eib if r[C["Category"]] not in ("PCB", "Assembly")),
    len(sysr), len(dk), len(skipped)))
