# Scripted PCB toolchain (Windows)

This file records the PCB toolchain installed on this machine on 2026-11-10 and the command
line for each step that was verified on a two-resistor test board. Each command was run in
Windows PowerShell 5.1.

## 1. Installed tools

| Tool | Version | Path |
|------|---------|------|
| KiCad (GUI, libraries, 3D models) | 9.0.9 | `C:\Program Files\KiCad\9.0` |
| kicad-cli | 9.0.9 | `C:\Program Files\KiCad\9.0\bin\kicad-cli.exe` |
| KiCad bundled Python (imports `pcbnew`) | 3.11.5 | `C:\Program Files\KiCad\9.0\bin\python.exe` |
| pcbnew Python module | 9.0.9 | bundled; importable from the venv in section 2 |
| ngspice shared library | KiCad 9.0.9 bundle | `C:\Program Files\KiCad\9.0\bin\ngspice.dll` |
| kiutils | 1.4.8 | `tools\pcb\.venv` |
| easyeda2kicad | 1.0.1 | `tools\pcb\.venv\Scripts\easyeda2kicad.exe` |
| KiKit | 1.8.1 | `tools\pcb\.venv\Scripts\kikit.exe` |
| InteractiveHtmlBom | 2.12.0 | `tools\pcb\.venv\Scripts\generate_interactive_bom.exe` |
| Freerouting | 2.5.0 | `C:\Tools\freerouting\freerouting-2.5.0.jar` |
| JDK for Freerouting (Temurin) | 25.0.5+8 | `C:\Tools\jdk-25.0.5+8\bin\java.exe` |
| JDK, pre-existing (not used by Freerouting) | 17.0.9 | `C:\Program Files\BellSoft\LibericaJDK-17-Full\bin\java.exe` |

Note that Freerouting 2.5.0 is compiled for Java 25 and does not run on Java 17. JDK 25 is
not on `PATH` and `JAVA_HOME` is unchanged; call it by its full path.

Note that ngspice is installed only as `ngspice.dll`. There is no `ngspice.exe`; batch
simulation uses the shared-library API (section 3.4).

The following tools are NOT installed: KiBot, a KiCad-GUI JLCPCB/LCSC parts plugin, and KiCad
MCP servers. Fab design rules for OSH Park and PCBWay are in
`tools\pcb\fab_rules\` (section 3.9).

The venv packages were installed with this command:

```powershell
& $py -m pip install kiutils==1.4.8 easyeda2kicad==1.0.1 kikit==1.8.1
```

KiKit pulled in click 8.5.1, commentjson 0.9.0, markdown2 2.5.5, pybars3 0.9.7, shapely 2.2.0,
solidpython 1.1.3, prettytable 0.7.2, euclid3 0.1, lark-parser 0.7.8, ply 3.11, PyMeta3 0.5.1
and pypng 0.0.19. numpy comes from KiCad's Python.

InteractiveHtmlBom was installed without its declared wxPython dependency, so the venv uses
KiCad's bundled wxPython 4.2.2 instead of a second copy:

```powershell
& $py -m pip install --no-deps interactivehtmlbom==2.12.0 jsonschema==4.26.0 attrs==26.1.0 jsonschema-specifications==2025.9.1 referencing==0.37.0 rpds-py==2026.9.1 typing_extensions==4.16.0
```

Note that `pip check` therefore reports "interactivehtmlbom 2.12.0 requires wxpython, which is
not installed". This message is expected.

## 2. Libraries and Python environment

The stock libraries are in `C:\Program Files\KiCad\9.0\share\kicad\` (`symbols`,
`footprints`, `3dmodels`). The global library tables are
`%APPDATA%\kicad\9.0\sym-lib-table` and `fp-lib-table` (KiCad's default tables). They resolve
`${KICAD9_SYMBOL_DIR}`, `${KICAD9_FOOTPRINT_DIR}` and `${KICAD9_3DMODEL_DIR}` internally; no
system environment variables are set. Put project-local libraries in the project folder and
list them in a project `sym-lib-table` / `fp-lib-table` with `${KIPRJMOD}` paths.

The venv was created from KiCad's Python with `--system-site-packages`, so `pcbnew` and
`kiutils` import together. To activate it in PowerShell:

```powershell
& "C:\Life Ops\School\Thesis\DC-Balancer-round4\tools\pcb\.venv\Scripts\Activate.ps1"
```

Alternatively, call the interpreter directly:
`"C:\Life Ops\School\Thesis\DC-Balancer-round4\tools\pcb\.venv\Scripts\python.exe"`.
The venv contains a `.gitignore` with `*`, so git ignores it.

## 3. Verified commands

The examples use these PowerShell variables:

```powershell
$k  = "C:\Program Files\KiCad\9.0\bin\kicad-cli.exe"
$py = "C:\Life Ops\School\Thesis\DC-Balancer-round4\tools\pcb\.venv\Scripts\python.exe"
$jv = "C:\Tools\jdk-25.0.5+8\bin\java.exe"
$fr = "C:\Tools\freerouting\freerouting-2.5.0.jar"
```

### 3.1 ERC and DRC

```powershell
& $k sch erc --format report --severity-all --exit-code-violations -o erc.rpt board.kicad_sch
& $k pcb drc --format report --severity-all --schematic-parity --exit-code-violations -o drc.rpt board.kicad_pcb
```

With `--exit-code-violations`, the exit code is non-zero when violations exist. On the test
board, ERC reported 0 errors and 0 warnings. DRC reported 0 violations, 0 unconnected items
and 0 parity issues after routing.

### 3.2 Schematic generation with kiutils

kiutils 1.4.8 writes `.kicad_sch` in the KiCad 6 format (`version 20211014`). kicad-cli 9
reads it; ERC, netlist, BOM and PDF export all succeeded on it. Copy each library symbol into
`lib_symbols` with `libraryNickname` set (for example `Device`). Give each placed symbol an
`instances` entry with path `/<schematic uuid>`. Device:R pins are at (0, ±3.81) in symbol
coordinates; schematic y is inverted.

### 3.3 Board generation with pcbnew

The test board (outline plus one footprint) was created with this script:

```python
import pcbnew, sys
b = pcbnew.BOARD(); r = pcbnew.PCB_SHAPE(b); r.SetShape(pcbnew.SHAPE_T_RECT); r.SetLayer(pcbnew.Edge_Cuts); r.SetStart(pcbnew.VECTOR2I_MM(0, 0)); r.SetEnd(pcbnew.VECTOR2I_MM(20, 15)); b.Add(r)
fp = pcbnew.FootprintLoad(r"C:\Program Files\KiCad\9.0\share\kicad\footprints\Resistor_SMD.pretty", "R_0603_1608Metric")
fp.SetPosition(pcbnew.VECTOR2I_MM(10, 7.5)); fp.SetReference("R1"); b.Add(fp)
b.Save(sys.argv[1])
```

For DRC schematic parity, also call `fp.SetFPID(pcbnew.LIB_ID("<lib>", "<footprint>"))`
and use the net names that KiCad derives from the schematic (for example `Net-(R1-Pad1)`;
read them from `kicad-cli sch export netlist`).

### 3.4 ngspice batch transient

`ngspice.dll` is driven through `ctypes`: `ngSpice_Init`, `ngSpice_Circ` (netlist lines),
`ngSpice_Command(b"run")`, then `ngGet_Vec_Info(b"time")` / `(b"out")`. For a 1 kΩ / 1 µF RC
step, the simulation returned v(out) = 0.6309 V at t = 0.9968 ms. The analytic value
1 − e^(−0.9968) is 0.6309 V.

### 3.5 Autorouting with Freerouting (headless)

1. Export the DSN through pcbnew: `pcbnew.ExportSpecctraDSN(pcbnew.LoadBoard(pcb), dsn)`.
2. Run Freerouting:

   ```powershell
   & $jv '-Djava.awt.headless=true' -jar $fr --gui.enabled=false --usage_and_diagnostic_data.disable_analytics=true -de board.dsn -do board.ses --router.autorouter.max_passes=20
   ```

3. Import the SES and save the board: `b = pcbnew.LoadBoard(pcb); pcbnew.ImportSpecctraSES(b, ses); b.Save(pcb)`.
4. Run DRC (section 3.1) on the routed board.

Note that the `-D` argument must be in single quotes; PowerShell 5.1 otherwise splits it and
Java reports `Could not find or load main class .awt.headless=true`. The flag `-mp` still
works but is deprecated. The test board routed in 0.18 s (exit code 0, 871-byte SES).

Note that `%APPDATA%\freerouting\freerouting.json` stores `"disable_analytics": false` and
`"allow_telemetry": true`. The command-line flag above was accepted without a warning.
Whether it suppresses all network traffic was not verified.

### 3.6 Fabrication and documentation exports

```powershell
& $k pcb export gerbers -o fab\ board.kicad_pcb
& $k pcb export drill --format excellon --generate-map --map-format gerberx2 -o fab\ board.kicad_pcb
& $k pcb export step --subst-models --force -o fab\board.step board.kicad_pcb
& $k pcb export pos --format csv --units mm --side both -o fab\board-pos.csv board.kicad_pcb
& $k sch export bom -o fab\board-bom.csv board.kicad_sch
& $k sch export pdf -o fab\board-sch.pdf board.kicad_sch
& $k pcb export pdf --layers F.Cu,Edge.Cuts -o fab\board-pcb.pdf board.kicad_pcb
```

All seven exports returned exit code 0. Without `--layers`, `export gerbers` plots every
enabled layer, including the empty User layers; pass an explicit `--layers` list for a fab
package. STEP export included the stock 3D model (`R_0603_1608Metric.step`).

### 3.7 LCSC parts with easyeda2kicad

```powershell
& "C:\Life Ops\School\Thesis\DC-Balancer-round4\tools\pcb\.venv\Scripts\easyeda2kicad.exe" --full --lcsc_id=C2876593 --output <dir>\lcsc --overwrite
```

The command writes `<dir>\lcsc.kicad_sym`, `<dir>\lcsc.pretty\*.kicad_mod` and
`<dir>\lcsc.3dshapes\*.wrl` and `*.step`. It sends only the LCSC number to EasyEDA's API. The
test fetched the BQ25798RQMR (LCSC C2876593): symbol `BQ25798RQMR`, footprint
`QFN-29_L4.0-W4.0-P0.40-TL-BQ25792RQMR` (29 pads; pcbnew loads it) and a 2.07 MB STEP model.
Note that EasyEDA named the footprint after the BQ25792. Compare every fetched land pattern
with the manufacturer datasheet before use.

### 3.8 Fab packages with KiKit

```powershell
$kk = "C:\Life Ops\School\Thesis\DC-Balancer-round4\tools\pcb\.venv\Scripts\kikit.exe"
& $kk fab jlcpcb --drc --assembly --missingWarn --schematic board.kicad_sch board.kicad_pcb out_jlc
& $kk fab pcbway --drc --assembly --schematic board.kicad_sch board.kicad_pcb out_pcbway
& $kk fab oshpark --drc board.kicad_pcb out_osh
```

All three presets returned exit code 0 on the test board. `jlcpcb` and `pcbway` wrote
`gerbers.zip`, a `gerber\` folder with Gerbers and PTH/NPTH drill files, `bom.csv` and
`pos.csv`. `oshpark` wrote Gerbers and drill files only, because OSH Park does not assemble.
`jlcpcb` reads the LCSC number from the field `LCSC` (change with `--field`). `pcbway` reads
manufacturer and part-number fields (`--manufacturer`, `--partNumber`). KiKit 1.8.1 also has
`neodenyy1` and `openpnp` presets.

### 3.8a Interactive HTML BOM

```powershell
$env:INTERACTIVE_HTML_BOM_CLI_MODE = '1'
$env:INTERACTIVE_HTML_BOM_NO_DISPLAY = '1'
& "C:\Life Ops\School\Thesis\DC-Balancer-round4\tools\pcb\.venv\Scripts\generate_interactive_bom.exe" --no-browser --dest-dir <outdir> --name-format "%f_ibom" board.kicad_pcb
```

The test board gave `rtest_ibom.html` (172 kB, exit code 0, about 1 s). The "Adding duplicate
image handler" lines on stderr are harmless.

WARNING: Set both environment variables before you run the command or import the package.
Without `INTERACTIVE_HTML_BOM_CLI_MODE`, the package registers a KiCad action plugin when it is
imported. Outside KiCad this opens a modal "wxWidgets Debug Alert" dialog
(`assert "PgmOrNull()" failed in ACTION_PLUGINS::register_action()`), which blocks an
unattended run until someone dismisses it.

### 3.9 Fab design rules (OSH Park and PCBWay, conservative)

The folder `tools\pcb\fab_rules\` contains these files:

- `fab_2layer_oshpark_pcbway.kicad_dru` for the EIB.
- `fab_4layer_oshpark_pcbway.kicad_dru` for the CR (superseded for the charger EVM CR, see the next item).
- `fab_4layer_oshpark_only.kicad_dru` for the charger EVM CR (OSH Park only, 2026-11-13;
  `hardware/charger_evm_r8/LAYOUT_DECISIONS.md` D-29 amended and D-55). Track and clearance minimum
  0.127 mm, annular ring 0.1016 mm, via diameter 0.4572 mm, hole to hole 0.127 mm. `gen/make_board.sh`
  copies it and then lowers the board-setup minimums to these values after `apply_board_setup.py`;
  the board Default net class stays 0.1524 / 0.1524 mm.
- `fab_4layer_5mil_oshpark_pcbway.kicad_dru`: the shared OSH Park/PCBWay 5/5 mil file of D-29
  (2026-11-11), superseded for the CR by the OSH Park-only file.
- `apply_board_setup.py`, which writes the same minimums into the board setup. It also sets
  the solder-mask expansion, the solder-mask web and the board thickness, which custom rules
  cannot express.

Each rule cites both fabs' published values and URLs. The values were read on 2026-11-10 from
docs.oshpark.com (two-layer, four-layer) and pcbway.com (capabilities, pcb_prototype).

| Item | 2-layer (EIB) | 4-layer (CR) |
|------|---------------|--------------|
| Track width / clearance | 0.1524 / 0.1524 mm (6/6 mil) | 0.1524 / 0.1524 mm |
| Copper to board edge | 0.381 mm | 0.381 mm |
| Minimum hole (PTH and via) | 0.254 mm | 0.254 mm |
| Annular ring | 0.15 mm | 0.15 mm |
| Via pad diameter (derived) | 0.554 mm | 0.554 mm |
| Hole to hole: general / via-via | 0.4064 / 0.2794 mm | 0.4064 / 0.2794 mm |
| Plated hole to inner copper | n/a | 0.254 mm |
| Silk text height / stroke | 0.8 / 0.15 mm | 0.8 / 0.15 mm |
| Mask expansion / web | 0.0508 / 0.1016 mm | 0.0508 / 0.1016 mm |
| Thickness; copper | 1.6 mm; 1 oz | 1.6 mm; 1 oz outer, design for 0.5 oz inner |

To apply the rules to a project:

1. Copy the matching `.kicad_dru` file into the project folder as `<project>.kicad_dru`.
2. Run `& $py tools\pcb\fab_rules\apply_board_setup.py <project>.kicad_pcb`.
3. Run DRC (section 3.1).

The script saves the board with `pcbnew.SaveBoard()`, which also writes the `.kicad_pro`. With
each rule file loaded, the routed test board passed DRC (0 violations). A negative test then
added a 0.10 mm track 0.15 mm from the edge. DRC flagged the track under `fab_track_width` and
`fab_edge_clearance` (exit code 5).

The open `TODO(verify)` items are listed in the rule files:

- which PCBWay track/space option and copper weight is base price;
- whether OSH Park's 10 mil minimum drill is drilled or finished (use a 0.3 mm via drill);
- whether PCBWay hole-to-hole figures are edge to edge;
- the preferred mask expansion;
- OSH Park's temporary alternate 4-layer stackup.

## 4. Known quirks

- The first `kicad-cli sch erc` call after installation crashed with exit code -1073741819
  (access violation) and wrote no report. Every later ERC run on the same file succeeded.
  When ERC crashes, run the command again before you debug the input.
- `kicad-cli` 9.0.9 has no `sch upgrade` subcommand.
- Paths with spaces must be quoted. `kicad-cli` ran without a GUI session.
