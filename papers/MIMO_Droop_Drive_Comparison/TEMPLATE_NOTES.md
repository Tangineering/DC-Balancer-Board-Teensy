# Template notes — MIMO_Droop_Drive_Comparison (internal lab report)

Brief for whoever writes the `.tex`. `Definitions/mdpi.cls` (+ `.bst` files, logos) is already
copied into this folder; `Figures/` is populated (see list at the bottom). This is an **internal
lab report**, not a journal submission — keep the MDPI class (it's the house style both other
papers use) but mark it clearly as not-for-publication (see "Internal-report marking" below).

## 1. `\documentclass` line

Follow `Droop_Control`'s pattern (single author, matches this report's authorship), not the
Youla paper's (`moreauthors`):

```latex
\documentclass[energies,article,submit,pdftex,oneauthor]{Definitions/mdpi}
```

- `energies` — journal template to piggyback on (same one Droop_Control uses; picks
  reasonable margins/fonts, doesn't imply real submission).
- `article` — document type.
- `submit` — draft mode (line numbers, watermark eligibility) as opposed to `accept`.
- `pdftex` — pdflatex mode.
- `oneauthor` — single author block layout.

**Caveat:** `mdpi.cls` expects journal metadata (`\PubVolume`, `\Issue`, `\Year`, `\doinum`,
`\pubvolume`, `\history{...}`, etc. — see the boilerplate at the top of `droop_control.tex`)
and **will throw undefined-reference or missing-field errors/warnings if these are omitted
entirely**. Don't delete them — copy the full boilerplate front-matter block from
`droop_control.tex` (the `\firstpage{1}\makeatletter...\PubVolume{1}\Issue{1}\Year{2026}...`
region) and adapt values as placeholders; leave a `% TODO` where a real value doesn't exist
for an internal report (DOI, received/accepted dates, etc.).

## 2. Required preamble (verbatim, on top of what `Definitions/mdpi.cls` already loads)

```latex
\usepackage{siunitx}
\usepackage{tabularx}
\newcolumntype{C}{>{\centering\arraybackslash}X} % centered X column, used in comparison tables
```

Add `\usepackage{amsmath}` only if not already pulled in by the class (it is — class loads
`amsmath`/`amssymb` already, don't double-load). If any MIMO-specific math needs `bmatrix`
environments for state-space blocks, that's already covered by `amsmath`.

## 3. Author block (verbatim, adapted)

Use **"Ricky Tan"** (matches `Droop_Control`, not the Youla paper's "Ricardo Tan" — reconcile
in favor of Droop_Control's spelling since this report continues that project's voice):

```latex
\Author{Ricky Tan $^{1}$\orcidA{}}
\AuthorNames{Ricky Tan}
\isAPAStyle{%
       \AuthorCitation{Tan, R.}
         }{%
        \isChicagoStyle{%
        \AuthorCitation{Tan, Ricky.}
        }{
        \AuthorCitation{Tan, R.}
        }
}
\address[1]{%
Department of Mechanical \& Aerospace Engineering, University of California, Davis, CA 95616,
USA; rstan@ucdavis.edu}
\corres{\hangafter=1 \hangindent=1.05em \hspace{-0.82em}Correspondence: rstan@ucdavis.edu}
```

### Internal-report marking

There's no MDPI class flag for "internal/unpublished." Mark it two ways:

1. In the title itself or a subtitle line — e.g. `\Title{MIMO vs. Decentralized Droop-Share
   Control for the Balancer Board: An Internal Comparison}`.
2. Add a boxed/colored notice right after `\begin{document}\firstpage{1}` (before the abstract),
   e.g. using the class's existing `draftwatermark` package (already loaded) —
   `\SetWatermarkText{INTERNAL DRAFT}` — or a plain one-line `\begin{center}\itshape Internal
   lab report --- not for external distribution\end{center}`. Simplest: reuse the watermark,
   since the package is already in the class and both other papers leave it unconfigured
   (default MDPI watermark behavior under `submit` mode already prints a draft-style banner —
   verify it renders and only add the explicit watermark line if it doesn't).

## 4. Section skeleton (mirror the Youla paper's structure — it's the better fit for a
   comparison/validation study; adapt titles to this report's MIMO-vs-decentralized subject)

```
1. Introduction
2. Methods
   2.1 Notation
   2.2 Plant / Controller Synthesis  (cite controller_design_MIMO/ docs)
3. Plant Models
4. Results
   4.1 Coupling and Conditioning         -> fig_coupling_sigma.pdf
   4.2 Robustness (sigma-bar(S))         -> fig_sigma_S_both.pdf, fig_corner_scatter.pdf,
                                             MATLAB_mimo_sigmaS.png, MATLAB_mimo_corner_scatter.png
   4.3 Transient Response                -> fig_transient_small.pdf, MATLAB_mimo_transient.png
   4.4 Regen Event                       -> fig_regen.pdf
   4.5 Drive Cycle Tracking              -> fig_drive_cycle.pdf
5. Discussion
6. Conclusions
Back matter: \authorcontributions, \funding, \dataavailability, \conflictsofinterest
References (embedded thebibliography, see below)
```

## 5. Notation macros (both papers define none for the droop symbols — write them out directly)

No `\newcommand` layer exists for `\alpha`, `r`, `k_d`, `R_e` etc. in either source paper —
**do the same here**: write `\alpha` (share fraction), `r` (droop ratio, range via
`\num{0.15}`–`\num{0.85}` with `siunitx`), `k_d` (droop scale / firmware `K_DROOP`), `R_e(g)`
(effective output resistance), `g_F`/`g_B` (per-channel MDAC gain) as raw LaTeX each time —
consistent with `Droop_Control/sections/03_robust_controller.tex`'s explicit "NOTATION CHECK"
comment. For MIMO-specific symbols (state-space matrices, $\bar\sigma$, $S_o$, $T$, singular
values), match the Youla paper's style: `S`, `T`, `Y`, `G_P` (or `G_s` for the small-signal
coupling plant, matching the CSV column names `ratio12`, `cond`, `sigmax`/`sigmin`), `W_p`,
`W_u` as plain italic symbols, no macros. Only pre-existing macros to reuse (both from
`01_introduction.tex`, only if a qualitative rating table is needed):
```latex
\newcommand{\rgood}{\textbullet\textbullet\textbullet}
\newcommand{\rmid}{\textbullet\textbullet}
\newcommand{\rbad}{\textbullet}
```

## 6. Bibliography

Both papers use an **embedded `thebibliography`**, not a `.bib`+`.bst` pipeline (despite
`.bst` files sitting unused in `Definitions/`). Follow `Droop_Control`'s simpler pattern: put
a bare
```latex
\begin{thebibliography}{99}
\bibitem{...} ...
\end{thebibliography}
```
in a `sections/99_references.tex` (if you split into multiple files) or inline at the end of
the main `.tex`, `\input`-ed after `\conflictsofinterest`. Cite the `controller_design_MIMO/`
design docs (`system_model.md`/local synthesis scripts) as informal internal references if no
external citation exists — flag with `% TODO(verify)` per the Droop_Control convention for any
reference you haven't double-checked.

## 7. `\includegraphics` conventions

```latex
\begin{figure}[H]
    \includegraphics[width=\linewidth]{Figures/fig_coupling_sigma.pdf}
    \caption{...}
    \label{fig:coupling-sigma}
\end{figure}
```
- Always `[H]` placement (float package), never `figure*` in either source paper.
- Width always `\linewidth` or `1\linewidth` (equivalent) — never hardcode `\textwidth` or a
  fixed `cm`/`in` size.
- Labels use the `fig:` prefix, lowercase-hyphenated.
- Equation refs: Droop_Control uses `\eqref{eq:...}` — use that (not the Youla paper's spelled-
  out `Equation \ref{...}`) since this report continues Droop_Control's line.
- Tables: `\begin{table}[H] ... \caption{...} \label{tab:...} \end{table}`, built with
  `tabularx` + the centered `C` column type declared in the preamble, `\toprule`/`\midrule`/
  `\bottomrule` from `booktabs` (already loaded by the class).

## 8. Figures produced (`Figures/`, generated by `fig_export.py` — rerun it after any CSV
   update in `../../controller_design_MIMO/figures/`; run with
   `../../controller_design_MIMO/ctrl-venv/Scripts/python.exe fig_export.py`)

| File | Size | Shows |
|---|---|---|
| `fig_coupling_sigma.pdf` | 28.4 KB | Two-panel: top is $\|G_{s,12}\|/\|G_{s,11}\|$ vs. $\omega$ for three operating scenarios (nominal, light load 0.5 A, FC cruise $r=0.85$), from `coupling_freq.csv` (`ratio12_*` columns); bottom is $\mathrm{cond}(G_s)$ vs. $\omega$ for the same three scenarios (`cond_*` columns). |
| `fig_sigma_S_both.pdf` | 23.7 KB | $\bar\sigma(S_o(j\omega))$ vs. $\omega$, four curves: decentralized and MIMO controllers, each at nominal (`sigma_nominal_both.csv`: `dec_sigma_So`, `mimo_sigma_So`) and at the worst in-envelope corner (`sigma_worst_corner_both.csv`, same column names — corner parameters are in the CSV's `#`-comment header line: $I_{tot0}=2.0$, $r_0=0.5$, $\Delta V_0=-0.4$). |
| `fig_corner_scatter.pdf` | 19.9 KB | Scatter of per-corner $\bar\sigma(S_o)$, decentralized (x) vs. MIMO (y), from `tier2_corner_scatter.csv` (`dec_sigma_So` vs `mimo_sigma_So`, one point per swept corner incl. out-of-envelope ones labeled `K-out-of-envelope`), with a $y=x$ reference line — points below the line favor MIMO. |
| `fig_transient_small.pdf` | 25.3 KB | 2×2 small-signal transient panel: columns are $\Delta V_0=+0.4$ V / $-0.4$ V (`transient_small_dV0p.csv` / `transient_small_dV0m.csv`), rows are $\Delta\alpha(t)$ and $i_{cmd}(t)$, each with decentralized (`dec_alpha`/`dec_i`) vs. MIMO (`mimo_alpha`/`mimo_i`) overlaid. |
| `fig_regen.pdf` | 19.9 KB | Two-panel regen event from `regen_truth.csv`: top is $v_{bus}(t)$ (`dec_vbus` vs `mimo_vbus`), bottom is $\alpha(t)$ (`dec_alpha` vs `mimo_alpha`), both controllers overlaid. |
| `fig_drive_cycle.pdf` | 20.7 KB | Two-panel tracking result from `drive_cycle.csv`: top is $v(t)$ vs. reference `v_ref` (`dec_v`, `mimo_v`), bottom is $\alpha(t)$ vs. reference `alpha_ref` (`dec_alpha`, `mimo_alpha`). |
| `MATLAB_mimo_corner_scatter.png` | 28.1 KB | Copied verbatim from `controller_design_MIMO/figures/` — MATLAB cross-check of the corner-scatter robustness comparison. |
| `MATLAB_mimo_sigmaS.png` | 32.2 KB | Copied verbatim — MATLAB cross-check of $\bar\sigma(S_o)$ vs. frequency. |
| `MATLAB_mimo_transient.png` | 27.7 KB | Copied verbatim — MATLAB cross-check of the small-signal transient response. |

All PDF figures use serif fonts (matplotlib `font.family: serif`), no in-figure titles
(captions live in the `.tex`), and a consistent 2-color scheme: decentralized = `#1f77b4`
(blue), MIMO $H_\infty$ = `#d62728` (red), reference/truth = dark gray dotted.

## 9. CSVs — column-layout notes / anything unexpected

All six target CSVs matched the plan with no missing columns. Two things worth flagging:

- `coupling_cond_grid.csv` was **not used** — it's a parameter-grid sweep
  (`I_tot0_A, r0, dV0_V, max_cond_Gs_inband, max_G12_over_G11, cond_Gs_dc`), not a
  frequency-response curve, so it doesn't fit a "coupling vs. freq" plot. `coupling_freq.csv`
  (frequency-indexed, three named scenarios) was the right source for `fig_coupling_sigma.pdf`
  instead. If a grid-style figure is wanted later (e.g. a heatmap of `max_cond_Gs_inband` over
  `I_tot0_A`/`r0`), this CSV is the source — not currently rendered.
- `tier2_corner_scatter.csv` has a non-numeric `label` column (e.g.
  `K-out-of-envelope`) mixed in with the numeric corner-parameter columns — `fig_export.py`'s
  `load_csv()` handles this generically (falls back to storing the raw string on a
  `ValueError` from `float()`), so no per-file special-casing was needed, but be aware the
  `label` column exists and is unused in the current plot — could be used to color/annotate
  in/out-of-envelope points differently in a future revision.
- `sigma_worst_corner_both.csv` has a leading `#`-comment header line documenting which
  corner was picked ($I_{tot0}=2.0$, $r_0=0.5$, $\Delta V_0=-0.4$, plus the full share/drive
  parameter dict) — `load_csv()` strips lines starting with `#` before parsing, so this is
  handled automatically. Worth quoting that corner definition in the figure caption in the
  `.tex` since it's not visible in the PDF itself.
