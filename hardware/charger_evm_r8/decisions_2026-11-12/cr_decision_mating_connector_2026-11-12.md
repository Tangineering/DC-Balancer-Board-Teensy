# CR decision: mating connector, key, assembly (operator rulings 2026-11-12)

Session: cr-decision-mating-conne (local_89c0c635). Items 4 and 5 of OUTLINE_CHANGE_REASSESSMENT_2026-11-12.md section 10, plus section 4.2.

## 1. Connector stack (item 4) - DECIDED: Samtec 2-piece, sockets on the MB, male on the CR, 11.05 mm

- Operator first proposed (own words): "Female 0.1" header strip on MB (PPPC121LFBN-RC); Stacking 0.1" header strip
  in-between (SSQ-112-03-G-S); Male 0.1" header strip on CR (PH1-12-UA) ... This is not a final decision yet."
- After review the operator chose the dialog option "Samtec 2-piece, 11.05 mm (Recommended)".
- Parts:
  - MB: SSQ-110-01-L-S (column x 45.998, pins 1-10) and SSQ-112-01-L-S (column x 20.998, pins 11-22). Body 8.51 mm on
    the MB top, square tail 2.64 mm through the MB (1.04 mm protrusion at 1.6 mm MB, ASSUMPTION).
  - CR: TSW-110-07-L-S and TSW-112-07-L-S, body on the CR underside, post C 5.84 mm pointing DOWN into the sockets,
    tail B 2.54 mm up through the CR (0.94 mm protrusion above a 1.6 mm CR), hand-soldered from the CR top.
  - Standard-force contacts (-01). Plating -L on both (10 u" Au on the mating surfaces, matte Sn tails).
  - All 22 positions populated (no pin omitted, since no key - inferred from the decision 2 ruling, not asked
    separately).
- Stack: hard stop where the TSW body seats on the SSQ face. CR underside = 8.51 + 2.54 = 11.05 mm above the MB top.
  Insertion 5.84 mm (Samtec SSQ range 3.68-6.35 mm). CR top 12.65 mm. Clearance over L-FC/L-BT (5.0 mm,
  unverified) = 6.05 mm, minus any CR bottom-side part.
- Rating: TSW mated with SSQ 6.3 A per pin, 2 positions powered (TSW F-226 current table). The 4-of-6 powered case at
  pins 14/15/18/19 (1.93 A each) remains TODO(verify: Samtec derating).
- Why the 3-piece was not taken (from the operator's own datasheets):
  - SSQ-112-03 tail is 10.00 mm against the Sullins 6.00 mm insertion depth: no seat, no defined stop
    (-02, 4.93 mm, would seat).
  - Sullins and Adam Tech PH1 are rated 3 A: pin 10 (>= 3 A required) at zero margin; two mated interfaces per pin
    (PH1 20 mOhm max each).
  - CR underside ~19.5 mm with -02, which also defeats the terminal-block key (below).
- The orientation (sockets on the MB) keeps the live MB pins touch-safe with the CR removed.

## 2. Key (item 5) - DECIDED: no key

- Operator's own words: "Regarding keying, let's not worry about it. I will be careful when assembling the board, and
  we will not be removing the CR often if at all after I perform my initial testing. We do not need to add protections
  against a 180 flip. The CR board is keyed by virtue of the board not being able to fit if it's flipped 180 since it
  would run into the power terminals on the -x side."
- Check: a CR rotated 180 deg about the CHG centre (33.498, 50.514) spans x 0-48.4 and lands over J-BL, J-FC and J-BT
  (21.70 mm, mb_mechanical.md Table 3; wire faces x 3.53, rear faces x 16.13/16.38). With the chosen stack the pins
  begin to engage at a CR underside of 11.05 + 5.84 = 16.89 mm, 4.81 mm below the block tops, so the rotated CR is
  stopped before any contact. HOLDS.
- NEW CONSTRAINT: engagement-start height (seated underside + post insertion) must stay < 21.70 mm. Any taller stack
  needs a real key.
- Consequences: retire the keying-blank rule of connector.md 2.5, no polarized SSQ, no omitted MB pin, no asymmetric
  standoff requirement. Keep the pin-1 silkscreen arrow and the pin_identity_check.py capture gate (D-02).

## 3. Assembly sequence and MB underside (section 4.2) - DECIDED

- Operator proposed: "I would solder the female header to the MB, and the male header to the CR, and then assemble by
  pressing in the stacking headers to the MB then the CR to the stacking header."
- For the 2-piece stack the operator chose "Solder CR pins while plugged (Recommended)":
  1. Clear the 22 MB CHG holes after the Ag105 removal.
  2. Solder the SSQ sockets to the MB, bodies flat and square (tack one pin, check, then solder).
  3. Plug the TSW strips into the sockets, set the finished (reflowed) CR on their bodies, solder the TSW tails from the
     CR top. The strips align to the real MB holes at the true height.
  4. Unplug and inspect.
- MB underside at both CHG columns: operator answered "Yes, clear" (checked by the operator, reachable with an iron).

## Changes elsewhere

- dec-standoffs: the stack has a HARD STOP at 11.05 mm (the CR rests on the connector bodies, load path through the
  insulators, not the pin joints). Standoff height must match 11.05 mm; mismatch either rocks the CR or preloads the
  connector. 12.0 mm is retired.
- Ordering BOM: TSW-110/112-07-G-S rows -> TSW-110/112-07-L-S (moved to the CR); add SSQ-110-01-L-S and
  SSQ-112-01-L-S (MB). -G is not on the current TSW sheet; the tap-pin row 78 TSW-101-07-G-S has the same issue.
- CR footprint: bottom courtyard is now the TSW body (2.54 x 25.40 / 30.48 mm, body = 2.54 x N), not the SSQ body;
  keep the footprint on F.Cu (no flip).
- Design doc rows listed in connector.md section 3 must use the 11.05 mm stack and the SSQ-on-MB / TSW-on-CR
  orientation, not Option A.
