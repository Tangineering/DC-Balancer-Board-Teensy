#!/usr/bin/env python3
"""Round 4 work: ORDER-OF-MAGNITUDE pin-field load and extension-resonance check for a CR that extends past the
Ag105 footprint. Imported by mb_mech_calc.py. Every input below is either from the design (A.8 pin coordinates) or an
ASSUMPTION printed with the result; none is a measured value.
"""
import math

ASSUMPTIONS = {
    "pin": "0.64 mm square phosphor-bronze post (Samtec F-226 TSW catalogue: terminal material phosphor bronze); "
           "yield is not stated by Samtec, 345 MPa ASSUMED for comparison only",
    "pin_field": "column A x 20.998, 12 pins y 36.544-64.484; column B x 45.998, 10 pins y 39.084-61.944 (design A.8)",
    "CR_main": "31 x 33 mm, CG at the pin-field centroid; main CR + headers 5 or 10 g ASSUMED",
    "areal_mass": "populated 4-layer CR 0.6-0.8 g/cm2 ASSUMED (bare 1.6 mm FR4 0.30 g/cm2 + four Cu layers ~0.11 g/cm2, "
                  "x1.5-2 for parts)",
    "shock": "10 g and 30 g normal to the MB; 30 g is ASSUMED as an RC-vehicle bump class, TODO(measure)",
    "FR4": "E = 20 GPa ASSUMED (TODO(verify: fab laminate datasheet)), rho 1.85 g/cm3, t 1.6 mm; mass factor 1-2 for "
           "parts on the extension",
    "support": "far support = a simple vertical prop at the extension tip; it carries half the extension load "
               "(uniform load on a propped strip, the order-of-magnitude split)",
}

XA, XB = 20.998e-3, 45.998e-3
NA, NB = 12, 10
XC = (NA * XA + NB * XB) / (NA + NB)
YC = 50.514e-3  # mean y of the 22 pins (A.8)
EXTS = {
    "+x usable (to x 80.2)": (48.70, 80.23, 55.01, 68.30),
    "+x core (to x 65.0)": (48.70, 65.00, 55.01, 67.14),
    "+y usable": (17.70, 39.72, 67.14, 76.51),
    "-y usable": (17.70, 48.70, 26.00, 34.14),
}


PINS = [(XA, 36.544e-3 + 2.54e-3 * k) for k in range(NA)] + [(XB, 39.084e-3 + 2.54e-3 * k) for k in range(NB)]


def pin_load():
    """Elastic pin-group model (rigid CR on 22 equal axial springs): F_i = F/22 + M (r_i - r_c) / sum (r_j - r_c)^2,
    r along x for a +x extension (moment about the y axis) and along y for a +/-y extension (about the x axis)."""
    res = {"assumptions": ASSUMPTIONS}
    s = 0.64e-3
    I = s ** 4 / 12.0
    Z = I / (s / 2)
    xs = [p[0] for p in PINS]
    ys = [p[1] for p in PINS]
    xc = sum(xs) / len(xs)
    yc = sum(ys) / len(ys)
    sxx = sum((x - xc) ** 2 for x in xs)
    syy = sum((y - yc) ** 2 for y in ys)
    res["pin_group"] = {"x_c_mm": round(xc * 1e3, 3), "y_c_mm": round(yc * 1e3, 3),
                        "Sxx_mm2": round(sxx * 1e6, 1), "Syy_mm2": round(syy * 1e6, 1),
                        "rmax_x_mm": round(max(abs(x - xc) for x in xs) * 1e3, 2),
                        "rmax_y_mm": round(max(abs(y - yc) for y in ys) * 1e3, 2)}
    rows = []
    for name, (x0, x1, y0, y1) in EXTS.items():
        area_cm2 = (x1 - x0) * (y1 - y0) / 100.0
        if name.startswith("+x"):
            arm_cg = (x0 + x1) / 2 * 1e-3 - xc
            L_cant = x1 * 1e-3 - XB
            k_m = max(abs(x - xc) for x in xs) / sxx
        else:
            arm_cg = abs((y0 + y1) / 2 * 1e-3 - yc)
            L_cant = (y1 * 1e-3 - 64.484e-3) if name.startswith("+y") else (36.544e-3 - y0 * 1e-3)
            k_m = max(abs(y - yc) for y in ys) / syy
        for m_main_g in (5.0, 10.0):
            for rho_a in (0.6, 0.8):
                m_ext = rho_a * area_cm2 * 1e-3
                for g in (10.0, 30.0):
                    a = 9.81 * g
                    F = (m_main_g * 1e-3 + m_ext) * a
                    M = m_ext * a * arm_cg
                    per_pin_no = F / (NA + NB) + M * k_m
                    R = 0.5 * m_ext * a
                    lever_R = arm_cg + L_cant / 2   # the tip lies L_cant/2 beyond the extension CG (uniform strip)
                    M_sup = abs(M - R * lever_R)
                    per_pin_sup = (F - R) / (NA + NB) + M_sup * k_m
                    rows.append({"ext": name, "m_main_g": m_main_g, "rho_a": rho_a, "m_ext_g": round(m_ext * 1e3, 2),
                                 "g": g, "arm_cg_mm": round(arm_cg * 1e3, 1), "M_Nmm": round(M * 1e3, 1),
                                 "per_pin_N_no_support": round(per_pin_no, 3),
                                 "per_pin_N_far_support": round(per_pin_sup, 3),
                                 "support_reaction_N": round(R, 3)})
    res["rows"] = rows
    inpl = []
    for m_tot_g in (10.0, 20.0):
        for g in (10.0, 30.0):
            V = m_tot_g * 1e-3 * 9.81 * g / 22
            inpl.append({"m_total_g": m_tot_g, "g": g, "V_per_pin_N": round(V, 4),
                         "sigma_MPa_free_2.54mm": round(V * 2.54e-3 / 2 / Z / 1e6, 2),
                         "sigma_MPa_free_5.08mm": round(V * 5.08e-3 / 2 / Z / 1e6, 2)})
    res["inplane"] = inpl
    E, rho, t = 20e9, 1850.0, 1.6e-3
    k = math.sqrt(E * t * t / (12.0 * rho))
    freq = []
    for name, L_mm in (("+x usable", 80.23 - 45.998), ("+x core", 65.0 - 45.998), ("+y usable", 76.51 - 64.484),
                       ("-y usable", 36.544 - 26.0)):
        L = L_mm * 1e-3
        for mf in (1.0, 2.0):
            f_c = (1.875 ** 2) / (2 * math.pi * L * L) * k / math.sqrt(mf)
            f_p = (3.927 ** 2) / (2 * math.pi * L * L) * k / math.sqrt(mf)
            freq.append({"ext": name, "L_from_pins_mm": round(L_mm, 1), "mass_factor": mf,
                         "f1_cantilever_Hz": round(f_c), "f1_tip_propped_Hz": round(f_p)})
    res["freq"] = freq
    # root bending stress of the extension strip under 30 g (uniform load, cantilever), per unit width
    stress = []
    for name, L_mm in (("+x usable", 80.23 - 45.998), ("+y usable", 76.51 - 64.484)):
        L = L_mm * 1e-3
        for mf in (1.0, 2.0):
            q_rho = rho * mf
            sig = 3 * q_rho * 30 * 9.81 * L * L / t
            defl = 1.5 * q_rho * 30 * 9.81 * L ** 4 / (E * t * t)
            stress.append({"ext": name, "mass_factor": mf, "root_stress_MPa_30g": round(sig / 1e6, 2),
                           "tip_deflection_um_30g": round(defl * 1e6, 1)})
    res["strip_stress"] = stress
    res["pin_section_modulus_m3"] = Z
    return res


if __name__ == "__main__":
    import json
    print(json.dumps(pin_load(), indent=1))
