%% full_order_model.m — MATLAB mirror of tps61288_full_model.py
% Full-order small-signal model of the droop share plant (complete TPS61288
% dynamics per DS §9.2.2.5) vs the simplified design plant, plus closed-loop
% validation with the SHIPPED controller parsed from share_controller_coeffs.h.
% Derivation and expected results: full_order_validation.md. The construction
% mirrors the Python implementation state-for-state so this run cross-checks it.
%
% Python reference results (2026-07-11): DC gain 0.9933, nominal in-band dev
% 3.86%, worst best-corner dev 5.78% (432 pts), CL 432/432 stable, worst
% ||S||inf 1.240, step overlay 0.0008, settle 25 ms.
%
% Outputs: MATLAB_fullorder_validation.txt (this folder),
%          figures/MATLAB_fullorder_bode.png, figures/MATLAB_fullorder_step.png
% Requires: Control System Toolbox. Tested syntax: R2024b.

clear; clc; close all;
here    = fileparts(mfilename('fullpath'));
figdir  = fullfile(here, 'figures');
hdrfile = fullfile(here, '..', 'teensy_controller', 'share_controller_coeffs.h');
fid = fopen(fullfile(here, 'MATLAB_fullorder_validation.txt'), 'w');

logf(fid, 'MATLAB full-order TPS61288 model validation\n');
logf(fid, 'generated: %s\n\n', datestr(now));

% ── parameters (TPS61288 DS §7.5/§9.2.2.5; schematic + bodges; system_model.md §8)
prm.VREF = 0.6;    prm.GEA  = 180e-6; prm.KCOMP = 13.5;  prm.L   = 2.2e-6;
prm.RC   = 61.2e3; prm.CC   = 2e-9;   prm.CP    = 27e-12;
prm.RD1  = 215e3;  prm.RD2  = 10e3;   prm.RINJ  = 53.6e3;
prm.AV   = 5.02;   prm.KSNS = 0.1;    prm.RSH   = 2e-3;  prm.WINA = 2*pi*350e3;
prm.RE_MAX = prm.KSNS*prm.AV*prm.RD1/prm.RINJ;
prm.K_D    = 0.30;
prm.VBUS0  = prm.VREF*(1 + prm.RD1/prm.RD2 + prm.RD1/prm.RINJ);   % 15.907 V
P_  = prm.RD2*prm.RINJ/(prm.RD2 + prm.RINJ);
prm.H1 = P_/(prm.RD1 + P_);  prm.H2 = prm.H1*prm.RD1/prm.RINJ;
Ts = 1e-3;  Td = 1e-3;  TAUR_NOM = 100e-6;
fails = 0;

%% ═══ A. Norton equivalent vs DS Eq. 7 (single channel, resistive load) ═══
Vin = 9.0; Ro = 8.0; Co_ = 66e-6; ESR = 2e-3;
oneD = Vin/prm.VBUS0;  wr = Ro*oneD^2/prm.L;
w = logspace(1, 6, 200).';  s = 1j*w;
Zc = ESR + 1./(s*Co_);
G_norton = prm.KCOMP*oneD*(1 - s/wr) ./ (1/Ro + 1/Ro + 1./Zc);
G_exact  = prm.KCOMP*oneD*(1 - s/wr).*(Ro/2).*(1 + s*ESR*Co_)./(1 + s*(Ro/2 + ESR)*Co_);
errA = max(abs(G_norton - G_exact)./abs(G_exact));
fails = fails + gatef(fid, 'A: Norton == exact parallel algebra', errA < 1e-12, ...
                      sprintf('max rel err %.2e', errA));

%% ═══ B. Full plant: DC gain + stability ═══
Pn = buildFullPlant(prm, 9.0, 8.0, 2.0, 0.5, 30e-6, 30e-6, 10e6, Td);
dc = dcgain(Pn);
fails = fails + gatef(fid, 'B: d(alpha)/dr(0) = 1 (finite-EA tolerance)', ...
                      abs(dc-1) < 1e-2, sprintf('dc = %.6f (Python 0.993297)', dc));
fails = fails + gatef(fid, 'B: full plant open-loop stable', isstable(Pn), ...
                      sprintf('order %d', order(Pn)));

%% ═══ C. Nominal Bode deviation vs simplified plant (band <= 1100 rad/s) ═══
wband = logspace(-1, log10(1100), 120).';
Gs_nom = simpPlant(1.0, Td, TAUR_NOM);
Gf = squeeze(freqresp(Pn, wband));  Gs = squeeze(freqresp(Gs_nom, wband));
devC = max(abs(Gf - Gs)./abs(Gs));
fails = fails + gatef(fid, 'C: nominal in-band deviation < 15%%', devC < 0.15, ...
                      sprintf('%.2f%% (Python 3.86%%)', 100*devC));

% corner family (K = 1)
TDs = [0.5e-3 1e-3 2e-3];  TRs = [20e-6 100e-6 300e-6];
cornerResp = cell(9,1); ci = 0;
for td = TDs, for tr = TRs
    ci = ci + 1; cornerResp{ci} = squeeze(freqresp(simpPlant(1.0, td, tr), wband));
end, end

%% ═══ D. Envelope study over the operating grid ═══
grid_ = {};
for vf = [9 12], for vb = [7.4 8.4], for it = [1 2 4]
for r0 = [0.3 0.5 0.7], for co = [30e-6 66e-6], for cb = [30e-6 500e-6]
for rea = [1e6 10e6 100e6]
    grid_{end+1} = [vf vb it r0 co cb rea]; %#ok<SAGROW>
end, end, end, end, end, end
worstE = 0; worstPt = [];
for gi = 1:numel(grid_)
    g = grid_{gi};
    Pg = buildFullPlant(prm, g(1), g(2), g(3), g(4), g(5), g(6), g(7), Td);
    Gg = squeeze(freqresp(Pg, wband));
    best = inf;
    for ci = 1:9
        best = min(best, max(abs(Gg - cornerResp{ci})./abs(cornerResp{ci})));
    end
    if best > worstE, worstE = best; worstPt = g; end
end
fails = fails + gatef(fid, 'D: every grid point within 15%% of a simplified corner', ...
    worstE < 0.15, sprintf('worst %.2f%% at [%g %g %g %g %g %g %g] (Python 5.78%%)', ...
    100*worstE, worstPt));

%% ═══ E. Discrete closed loop with the SHIPPED controller ═══
txt = fileread(hdrfile);
tok = regexp(txt, 'SHARE_CTRL_TS_US\s+(\d+)', 'tokens', 'once');  Ts_fw = str2double(tok{1})*1e-6;
tok = regexp(txt, 'SHARE_CTRL_KI\s*=\s*([^f;\s]+)f', 'tokens', 'once');  kI_fw = str2double(tok{1});
tok = regexp(txt, 'SHARE_CTRL_MEAS_FILT_A\s*=\s*([^f;\s]+)f', 'tokens', 'once');  Afilt = str2double(tok{1});
rows = regexp(txt, '\{\s*([^{}]*?)\s*\}', 'tokens');
Rz = tf(1, 1, Ts_fw);  nsos = 0;
for i = 1:numel(rows)
    v = sscanf(strrep(rows{i}{1}, 'f', ''), '%f,');
    if numel(v) == 5, Rz = Rz*tf(v(1:3).', [1 v(4:5).'], Ts_fw); nsos = nsos + 1; end
end
assert(nsos > 0, 'failed to parse SOS rows');
Gc_d = ss(Rz + tf(kI_fw*Ts_fw/2*[1 1], [1 -1], Ts_fw));
Hf_d = ss(tf((1-Afilt)*[1 0], [1 -Afilt], Ts_fw));
logf(fid, 'parsed shipped controller: Ts=%g s, kI=%.4f, filtA=%.6f, %d SOS\n', ...
     Ts_fw, kI_fw, Afilt, nsos);

Pd_full = c2d(Pn, Ts_fw, 'zoh');
Pd_simp = c2d(ss(Gs_nom), Ts_fw, 'zoh');
[yF, tt] = clStep(Pd_full, Gc_d, Hf_d, 0.2, 400, Ts_fw);
yS = clStep(Pd_simp, Gc_d, Hf_d, 0.2, 400, Ts_fw);
devStep = max(abs(yF - yS));
fails = fails + gatef(fid, 'E: nominal step overlay within 0.02 share', devStep < 0.02, ...
                      sprintf('max |diff| = %.4f (Python 0.0008)', devStep));

worstS = 0; nUnst = 0;
for gi = 1:numel(grid_)
    g = grid_{gi};
    Pd = c2d(buildFullPlant(prm, g(1), g(2), g(3), g(4), g(5), g(6), g(7), Td), Ts_fw, 'zoh');
    Sd = feedback(1, Pd*Gc_d*Hf_d);
    if ~isstable(Sd), nUnst = nUnst + 1; continue; end
    worstS = max(worstS, getPeakGain(Sd, 1e-3));
end
fails = fails + gatef(fid, 'E: discrete CL stable on ALL grid points', nUnst == 0, ...
                      sprintf('%d/%d stable', numel(grid_)-nUnst, numel(grid_)));
fails = fails + gatef(fid, 'E: worst ||S||inf < 2.2', worstS < 2.2, ...
                      sprintf('worst = %.3f (Python 1.240; simplified corners 1.867)', worstS));

%% ═══ figures ═══
f1 = figure('Name', 'fullorder bode');
wwide = logspace(-1, 5, 400);
bodemag(Pn, 'r-', Gs_nom, 'b--', wwide); grid on;
legend('full-order (11 states)', 'simplified design plant');
title('Share plant r \rightarrow \alpha: full-order vs simplified');
exportgraphics(f1, fullfile(figdir, 'MATLAB_fullorder_bode.png'), 'Resolution', 150);

f2 = figure('Name', 'fullorder step');
plot(tt, 0.5 + yS, 'b--', tt, 0.5 + yF, 'r-'); grid on;
xlabel('Time (s)'); ylabel('share \alpha'); xlim([0 0.15]);
legend('simplified plant', 'full-order plant', 'Location', 'southeast');
title('Closed loop with shipped G_C(z): step 0.5 \rightarrow 0.7');
exportgraphics(f2, fullfile(figdir, 'MATLAB_fullorder_step.png'), 'Resolution', 150);

if fails == 0
    logf(fid, '\nVERDICT: PASS — full-order model confirms the simplified design plant.\n');
else
    logf(fid, '\nVERDICT: FAIL — %d gate(s) failed, see above.\n', fails);
end
fclose(fid);
fprintf('\nwrote MATLAB_fullorder_validation.txt + 2 figures\n');

%% ───────────────────────── local functions ─────────────────────────
function P = buildFullPlant(prm, VinF, VinB, Itot, r0, Co, Cbus, REA, Td)
    % state layout (mirrors Python): [xzcF(1:2) xzcB(3:4) voF(5) voB(6) vbus(7)
    %                                 xinaF(8) xinaB(9) xpade(10:11)]
    I0   = [r0*Itot, (1-r0)*Itot];
    oneD = [VinF, VinB]/prm.VBUS0;
    Rint = prm.VBUS0./I0;
    wr   = Rint.*oneD.^2/prm.L;
    g0   = [prm.K_D/(prm.RE_MAX*r0),      prm.K_D/(prm.RE_MAX*(1-r0))];
    dg   = [-prm.K_D/(prm.RE_MAX*r0^2),   +prm.K_D/(prm.RE_MAX*(1-r0)^2)];

    % exact Z_comp (strictly proper, 2 states); Czc scaled by GEA
    num = [prm.RC*prm.CC, 1];
    den = [prm.RC*prm.CC*prm.CP, prm.CP + prm.CC + prm.RC*prm.CC/REA, 1/REA];
    [Azc, Bzc, Czc, Dzc] = ssdata(ss(tf(num, den)));
    assert(abs(Dzc) < 1e-18);
    Czc = prm.GEA*Czc;

    [np_, dp_] = pade(Td, 2);
    [Apd, Bpd, Cpd, Dpd] = ssdata(ss(tf(np_, dp_)));

    n = 11;  A = zeros(n);  B = zeros(n, 1);
    iZ = {1:2, 3:4};  iV = [5 6];  iBus = 7;  iI = [8 9];  iP = 10:11;
    A(iP, iP) = Apd;  B(iP) = Bpd;

    for k = 1:2
        row_i = zeros(1, n);  row_i(iV(k)) = 1/prm.RSH;  row_i(iBus) = -1/prm.RSH;
        row_vop = zeros(1, n);  row_vop(iI(k)) = prm.AV*g0(k);
        row_vop(iP) = row_vop(iP) + prm.AV*prm.KSNS*I0(k)*dg(k)*Cpd;
        vopD = prm.AV*prm.KSNS*I0(k)*dg(k)*Dpd;

        row_u = zeros(1, n);  row_u(iV(k)) = -prm.H1;
        row_u = row_u - prm.H2*row_vop;   uD = -prm.H2*vopD;

        A(iZ{k}, iZ{k}) = Azc;
        A(iZ{k}, :) = A(iZ{k}, :) + Bzc*row_u;   B(iZ{k}) = B(iZ{k}) + Bzc*uD;

        Kc = prm.KCOMP*oneD(k);
        row_iN = zeros(1, n);
        row_iN(iZ{k}) = Kc*(Czc - (Czc*Azc)/wr(k));
        cb = Czc*Bzc;
        row_iN = row_iN - Kc*cb/wr(k)*row_u;   iND = -Kc*cb/wr(k)*uD;

        A(iV(k), :) = A(iV(k), :) + (row_iN - row_i)/Co;
        A(iV(k), iV(k)) = A(iV(k), iV(k)) - 1/(Rint(k)*Co);
        B(iV(k)) = B(iV(k)) + iND/Co;

        A(iBus, :) = A(iBus, :) + row_i/Cbus;

        A(iI(k), :) = A(iI(k), :) + prm.WINA*prm.KSNS*row_i;
        A(iI(k), iI(k)) = A(iI(k), iI(k)) - prm.WINA;
    end
    rF = zeros(1, n);  rF(iV(1)) = 1/prm.RSH;  rF(iBus) = -1/prm.RSH;
    rB = zeros(1, n);  rB(iV(2)) = 1/prm.RSH;  rB(iBus) = -1/prm.RSH;
    C = (I0(2)*rF - I0(1)*rB)/Itot^2;
    P = ss(A, B, C, 0);
end

function G = simpPlant(K, Td, taur)
    [np_, dp_] = pade(Td, 2);
    G = K*tf(np_, dp_)*tf(1, [taur 1]);
end

function [y, tt] = clStep(Pd, Gc_d, Hf_d, amp, nsteps, Ts)
    % e = ref - Hf(alpha); r = Gc e; alpha = Pd r   (Pd has D = 0)
    [Ap, Bp, Cp, ~]  = ssdata(Pd);
    [Ac, Bc, Cc, Dc] = ssdata(Gc_d);
    [Af, Bf, Cf, Df] = ssdata(Hf_d);
    np_ = size(Ap,1); nc = size(Ac,1); nf = size(Af,1);
    A = zeros(np_+nc+nf);  Bref = zeros(np_+nc+nf, 1);
    A(1:np_, 1:np_)            = Ap - Bp*Dc*Df*Cp;
    A(1:np_, np_+1:np_+nc)     = Bp*Cc;
    A(1:np_, np_+nc+1:end)     = -Bp*Dc*Cf;
    Bref(1:np_)                = Bp*Dc;
    A(np_+1:np_+nc, 1:np_)     = -Bc*Df*Cp;
    A(np_+1:np_+nc, np_+1:np_+nc) = Ac;
    A(np_+1:np_+nc, np_+nc+1:end) = -Bc*Cf;
    Bref(np_+1:np_+nc)         = Bc;
    A(np_+nc+1:end, 1:np_)     = Bf*Cp;
    A(np_+nc+1:end, np_+nc+1:end) = Af;
    C = [Cp, zeros(1, nc+nf)];
    x = zeros(np_+nc+nf, 1);  y = zeros(nsteps, 1);
    for k = 1:nsteps
        y(k) = C*x;
        x = A*x + Bref*amp;
    end
    tt = (0:nsteps-1).'*Ts;
end

function nfail = gatef(fid, name, cond, detail)
    if cond, tag = 'PASS'; nfail = 0; else, tag = 'FAIL'; nfail = 1; end
    logf(fid, '  [%s] %s  (%s)\n', tag, name, detail);
end

function logf(fid, varargin)
    fprintf(1, varargin{:});
    fprintf(fid, varargin{:});
end
