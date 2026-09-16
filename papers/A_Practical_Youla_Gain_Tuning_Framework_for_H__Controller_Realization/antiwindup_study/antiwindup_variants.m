%% antiwindup_variants.m
%  Discretization / anti-windup study for the Youla-H paper. Runs every variant
%  explored in the drafting round and writes the figures in the paper's MATLAB
%  style (black line styles, bold title, boxed legend, 'Time [sec]'). Colours follow
%  Figure 7 of the paper: black line styles for the Youla-H family, blue for H-inf
%  (and for the inverse weights on the loop-shape plot). Each figure is a tiledlayout
%  with ONE shared legend in the 'south' tile, below every subplot.
%
%  Variants
%    A. Drivetrain plant (Eq. Gp_numerical), controllers re-synthesized with the
%       Appendix-A weights:  clamp only (Hinf, Youla-H), integrator-only
%       back-calculation, full-state (Hanus) conditioning.      -> YH-AW-18
%    B. Drivetrain: Hinf vs Youla-H, BOTH fully conditioned, saturating step and
%       a slow unsaturated ramp (does the DC benefit survive?). -> YH-vs-H-cond-18
%    C. Example plant 1/(s+1), crossover 1 rad/s (paper's alternate system):
%       same four variants.                                       -> YH-AW-2nd
%    D. Example plant 1/(s+1), crossover 0.3 rad/s (below the plant pole):
%       clamp only vs integrator-only back-calculation; this is the case where
%       conditioning is unnecessary, proposed as the replacement alternate
%       system. Also writes its loop-shape figure.                -> YH-AW-3rd, YH-TSY-3rd
%
%  Realization used for every Youla-H controller (the point of the section):
%       Gc_YH(s) = kI/s + R(s)   ->  trapezoidal integrator + Tustin R(z)
%  Anti-windup laws on the discrete state x = [x_I ; x_R]:
%       'clamp' : x+ = Ad x + Bd e                       (no anti-windup)
%       'integ' : x+ = Ad x + Bd e + [1;0](u_sat - u)    (back-calculation, integrator)
%       'cond'  : x+ = Ad x + Bd e + L (u_sat - u)       (Hanus general conditioning)
%  L is pole-placed from the self-conditioned spectrum eig(Ad - Bd Cd / Dd) with the
%  structural z = -1 eigenvalue (Tustin's (z+1) factor) moved to +0.5.
%
%  Output: every figure is written as PNG (300 dpi) + PDF into antiwindup_study/figures/.
%  Requires: Control System Toolbox, Robust Control Toolbox (hinfsyn, makeweight).
%  Tested against the Python originals make_YH-AW-*.py; small differences in the
%  example-plant numbers are expected because those weights were read off a plot.

clear; clc; close all;
s  = tf('s');
Ts = 1e-3;
scriptdir = fileparts(mfilename('fullpath')); if isempty(scriptdir), scriptdir = pwd; end
outdir = fullfile(scriptdir, 'figures');        % all figures go to this sub-folder
if ~exist(outdir, 'dir'), mkdir(outdir); end

%% ------------------------------------------------------------------ A. drivetrain
Gp = 22.624/(s + 4.32e-5);                       % Eq. Gp_numerical
Wd = makeweight(0.707, 18, 1e3, 0, 1);           % Appendix A weights
Wp = makeweight(1e4, 18, 0.707, 0, 2);
Wu = makeweight(0.707, 300, 1e4, 0, 2);
[Gc_H, Gc_YH, info] = youlaH(Gp, Wp, Wu, Wd);
fprintf('\n=== A. Drivetrain ===\n  gamma = %.4f   T_H(0) = %.6f   T_YH(0) = %.8f\n', ...
        info.gamma, info.T0_H, info.T0_YH);

[kI, R] = splitIntegrator(Gc_YH);
fprintf('  split: kI = %.4e   R(0) = %.4f   order(R) = %d\n', kI, dcgain(R), order(R));
ctrlH  = c2d(ss(Gc_H), Ts, 'tustin');            % Hinf: plain Tustin state space
ctrlYH = splitRealization(kI, R, Ts);            % Youla-H: exact integrator + Tustin R
Pd     = c2d(ss(Gp), Ts, 'zoh');
LH  = conditioningGain(ctrlH);
LYH = conditioningGain(ctrlYH);

Umax = 0.10;                                     % N*m, illustrative (rails ~2 s)
tA   = (0:Ts:12)';   rA = 5*(tA >= 0.5);         % 5 m/s step
resA.H     = simSat(ctrlH,  Pd, rA, Umax, 'clamp', LH);
resA.YH    = simSat(ctrlYH, Pd, rA, Umax, 'clamp', LYH);
resA.integ = simSat(ctrlYH, Pd, rA, Umax, 'integ', LYH);
resA.cond  = simSat(ctrlYH, Pd, rA, Umax, 'cond',  LYH);
resA.Hcond = simSat(ctrlH,  Pd, rA, Umax, 'cond',  LH);
printMetrics('Drivetrain step (settle rel. to step at 0.5 s)', resA, tA, 5, 0.5, Umax);

figure('Name','YH-AW-18');
tl = tiledlayout(2,1,'TileSpacing','compact','Padding','compact');
nexttile; hold on; grid on;
plot(tA, rA, '-', 'Color', [0.75 0.75 0.75], 'LineWidth', 1.0);
plot(tA, resA.H.y,     'b--', 'LineWidth', 1.5); plot(tA, resA.YH.y,    'k:',  'LineWidth', 2.0);
plot(tA, resA.integ.y, 'k-.', 'LineWidth', 1.5); plot(tA, resA.cond.y,  'k-',  'LineWidth', 1.5);
ylabel('v [m/s]'); title('Drivetrain wc=18: Saturated Step Response', 'FontWeight','bold');
nexttile; hold on; grid on;
plot(tA, resA.H.u, 'b--', 'LineWidth', 1.5); plot(tA, resA.YH.u, 'k:', 'LineWidth', 2.0);
plot(tA, resA.integ.u, 'k-.', 'LineWidth', 1.5); plot(tA, resA.cond.u, 'k-', 'LineWidth', 1.5);
yline( Umax, '-', 'Color', [0.75 0.75 0.75]); yline(-Umax, '-', 'Color', [0.75 0.75 0.75]);
ylabel('T_e [N\cdotm]'); xlabel('Time [sec]');
lgd = legend({'H_\infty, clamp only','Youla-H, clamp only', ...
              'Youla-H, integrator back-calc.','Youla-H, full-state conditioning'}, 'NumColumns', 2);
lgd.Layout.Tile = 'south';
saveFig(gcf, fullfile(outdir, 'YH-AW-18'));

%% ------------------------------------------------------------------ B. H vs YH, both conditioned
tB = (0:Ts:200)';  rB = 0.025*tB;                % slow ramp, never saturates
resB.H  = simSat(ctrlH,  Pd, rB, Umax, 'cond', LH);
resB.YH = simSat(ctrlYH, Pd, rB, Umax, 'cond', LYH);
fprintf('\n=== B. Both conditioned ===\n');
fprintf('  step  residual at 12 s : Hinf %+.2e   Youla-H %+.2e  m/s\n', resA.Hcond.y(end)-5, resA.cond.y(end)-5);
fprintf('  ramp  error at 200 s   : Hinf %+.2e   Youla-H %+.2e  m/s\n', resB.H.y(end)-rB(end), resB.YH.y(end)-rB(end));
fprintf('  saturated-mode eig, Hinf  : %s\n', mat2str(sort(eig(ctrlH.A  - LH *ctrlH.C)),  5));
fprintf('  saturated-mode eig, YoulaH: %s\n', mat2str(sort(eig(ctrlYH.A - LYH*ctrlYH.C)), 5));

figure('Name','YH-vs-H-cond-18');
tl = tiledlayout(1,2,'TileSpacing','compact','Padding','compact');
nexttile; hold on; grid on;
plot(tA, rA, '-', 'Color', [0.75 0.75 0.75], 'LineWidth', 1.0);
plot(tA, resA.Hcond.y, 'b--', 'LineWidth', 1.5); plot(tA, resA.cond.y, 'k-', 'LineWidth', 1.5);
xlabel('Time [sec]'); ylabel('v [m/s]'); title('Saturating Step', 'FontWeight','bold');
nexttile; hold on; grid on;
plot(tB, resB.H.y - rB, 'b--', 'LineWidth', 1.5); plot(tB, resB.YH.y - rB, 'k-', 'LineWidth', 1.5);
xlabel('Time [sec]'); ylabel('v - v_{ref} [m/s]'); title('Slow Ramp, No Saturation', 'FontWeight','bold');
lgd = legend({'H_\infty, conditioned','Youla-H, conditioned'}, 'NumColumns', 2);
lgd.Layout.Tile = 'south';
saveFig(gcf, fullfile(outdir, 'YH-vs-H-cond-18'));

%% ------------------------------------------------------------------ C. example plant, wc = 1
%  REPLACE these three weights with the ones used for Figure H-TSY-2nd if you
%  have them; the values below are read off that figure.
Gp2 = 1/(s + 1);
wc2 = 1.0;
Wp2 = makeweight(1e4, wc2, 1e-3);                % on S  (near-integral, ~0 dB at HF)
Wd2 = makeweight(0.1, wc2, 50);                  % on T  (1/Wd: +20 dB -> -34 dB)
Wu2 = makeweight(0.1, 100, 30);                  % on Y  (1/Wu: +20 dB, rolls off > ~100)
[Gc_H2, Gc_YH2, info2] = youlaH(Gp2, Wp2, Wu2, Wd2);
fprintf('\n=== C. Example plant, wc = %.1f ===\n  gamma = %.4f   T_H(0) = %.7f   T_YH(0) = %.8f\n', ...
        wc2, info2.gamma, info2.T0_H, info2.T0_YH);
[kI2, R2] = splitIntegrator(Gc_YH2);
fprintf('  split: kI = %.4f   R(0) = %.4f\n', kI2, dcgain(R2));
c2H = c2d(ss(Gc_H2), Ts, 'tustin'); c2YH = splitRealization(kI2, R2, Ts);
Pd2 = c2d(ss(Gp2), Ts, 'zoh'); L2H = conditioningGain(c2H); L2YH = conditioningGain(c2YH);

Umax2 = 1.5;  tC = (0:Ts:16)';
rC = 3*(tC >= 1 & tC < 3.5) + 1*(tC >= 3.5);    % out-of-reach hold, then step down to 1
resC.H     = simSat(c2H,  Pd2, rC, Umax2, 'clamp', L2H);
resC.YH    = simSat(c2YH, Pd2, rC, Umax2, 'clamp', L2YH);
resC.integ = simSat(c2YH, Pd2, rC, Umax2, 'integ', L2YH);
resC.cond  = simSat(c2YH, Pd2, rC, Umax2, 'cond',  L2YH);
printMetrics('Example plant wc=1 (settle rel. to step-down at 3.5 s)', resC, tC, 1, 3.5, Umax2);
plotAW(tC, rC, resC, Umax2, 'Example Plant wc=1: Saturated Response', ...
       {'H_\infty, clamp only','Youla-H, clamp only','Youla-H, integrator back-calc.','Youla-H, full-state conditioning'}, ...
       fullfile(outdir, 'YH-AW-2nd'));

%% ------------------------------------------------------------------ D. example plant, wc = 0.3
wc3 = 0.3;
Wp3 = makeweight(1e3, wc3, 1e-3);
Wd3 = makeweight(0.1, wc3, 20);
Wu3 = makeweight(0.1, 100*wc3, 30);
[Gc_H3, Gc_YH3, info3] = youlaH(Gp2, Wp3, Wu3, Wd3);
fprintf('\n=== D. Example plant, wc = %.1f ===\n  gamma = %.4f   T_H(0) = %.7f   T_YH(0) = %.8f   M2_H = %.4f   M2_YH = %.4f\n', ...
        wc3, info3.gamma, info3.T0_H, info3.T0_YH, info3.M2_H, info3.M2_YH);
[kI3, R3] = splitIntegrator(Gc_YH3);
fprintf('  split: kI = %.4f   R(0) = %.4f   slowest R poles: %s\n', kI3, dcgain(R3), mat2str(sort(real(pole(R3)),'descend')', 4));
c3H = c2d(ss(Gc_H3), Ts, 'tustin'); c3YH = splitRealization(kI3, R3, Ts);
L3H = conditioningGain(c3H); L3YH = conditioningGain(c3YH);

tD = (0:Ts:20)';  rD = 3*(tD >= 1 & tD < 3.5) + 1*(tD >= 3.5);
resD.H     = simSat(c3H,  Pd2, rD, Umax2, 'clamp', L3H);
resD.YH    = simSat(c3YH, Pd2, rD, Umax2, 'clamp', L3YH);
resD.integ = simSat(c3YH, Pd2, rD, Umax2, 'integ', L3YH);
resD.cond  = simSat(c3YH, Pd2, rD, Umax2, 'cond',  L3YH);   % computed, not plotted
printMetrics('Example plant wc=0.3 (settle rel. to step-down at 3.5 s)', resD, tD, 1, 3.5, Umax2);
resDplot = rmfield(resD, 'cond');
plotAW(tD, rD, resDplot, Umax2, 'Example Plant wc=0.3: Saturated Response', ...
       {'H_\infty, clamp only','Youla-H, clamp only','Youla-H, integrator back-calc.'}, ...
       fullfile(outdir, 'YH-AW-3rd'));

% loop shapes for the replacement alternate-system figure (same style as H-TSY-2nd)
[S3, T3, Y3] = loopTFs(Gc_YH3, Gp2);
w = logspace(-2, 3, 600);
figure('Name','YH-TSY-3rd');
tl = tiledlayout(1,1,'Padding','compact');
nexttile; hold on; grid on;
plot(w, mag2db(abs(squeeze(freqresp(T3, w)))), 'k-',  'LineWidth', 1.5);
plot(w, mag2db(abs(squeeze(freqresp(S3, w)))), 'k--', 'LineWidth', 1.5);
plot(w, mag2db(abs(squeeze(freqresp(Y3, w)))), 'k:',  'LineWidth', 2.0);
plot(w, -mag2db(abs(squeeze(freqresp(Wd3, w)))), 'b--', 'LineWidth', 1.5);
plot(w, -mag2db(abs(squeeze(freqresp(Wp3, w)))), 'b-.', 'LineWidth', 1.5);
plot(w, -mag2db(abs(squeeze(freqresp(Wu3, w)))), 'b:',  'LineWidth', 2.0);
set(gca, 'XScale', 'log'); ylim([-60 25]);
xlabel('Frequency (rad/s)'); ylabel('Magnitude (dB)'); title('Youla-H TSY', 'FontWeight','bold');
lgd = legend({'T','S','Y','1/Wd','1/Wp','1/Wu'}, 'NumColumns', 6);
lgd.Layout.Tile = 'south';
saveFig(gcf, fullfile(outdir, 'YH-TSY-3rd'));

fprintf('\nDone. Figures written to %s\n', outdir);

%% ================================================================== local functions
function [Gc_H, Gc_YH, info] = youlaH(Gp, Wp, Wu, Wd)
% Hinf synthesis followed by the Youla-H gain adjustment of the paper (Appendix A
% flow, done numerically: Y_YH = Y_H / T_H(0), which is Eq. KYH).
    mreal_tol = 1e-3;
    Ph = augw(Gp, Wp, Wu, Wd);
    [sysGc, ~, gam] = hinfsyn(Ph);
    Gc_H = zpk(minreal(tf(sysGc), mreal_tol));
    [S_H, T_H, Y_H] = loopTFs(Gc_H, Gp);
    T0_H = evalfr(T_H, 0);
    Y_YH  = Y_H / T0_H;                                   % K_YH = K_H / (Y_H(0) Gp(0))
    Gc_YH = zpk(minreal(Y_YH/(1 - Y_YH*Gp), mreal_tol));
    Gc_YH = snapIntegrator(Gc_YH);                        % pole nearest 0 -> exactly 0
    [S_YH, T_YH, ~] = loopTFs(Gc_YH, Gp);
    info.gamma = gam; info.T0_H = T0_H; info.T0_YH = evalfr(T_YH, 0);
    info.M2_H  = 1/norm(S_H, inf); info.M2_YH = 1/norm(S_YH, inf);
end

function [S, T, Y] = loopTFs(Gc, Gp)
    mreal_tol = 1e-3;
    L = Gc*Gp;
    S = zpk(minreal(1/(1 + L), mreal_tol));
    T = zpk(minreal(L/(1 + L), mreal_tol));
    Y = zpk(minreal(Gc/(1 + L), mreal_tol));
end

function G = snapIntegrator(G)
% Youla-H leaves the integrator at |p| ~ 1e-9..1e-6 after minreal; make it exact.
    [z, p, k] = zpkdata(G, 'v');
    [pmin, i] = min(abs(p));
    assert(pmin < 1e-3, 'no near-origin pole to snap (closest %.2e)', pmin);
    p(i) = 0;
    G = zpk(z, p, k);
end

function [kI, R] = splitIntegrator(Gc)
% Gc = kI/s + R(s), R strictly stable. stabsep puts the (exact) origin pole in the
% non-stable part; that part is a 1-state system kI/s.
    [R, Gi] = stabsep(ss(Gc), 'Offset', 1e-6);   % pole at 0 -> non-stable part
    assert(order(Gi) == 1, 'expected exactly one marginal pole, got %d', order(Gi));
    kI = Gi.C*Gi.B;                                       % residue of the 1/s term
    assert(isstable(R), 'remainder is not stable');
end

function C = splitRealization(kI, R, Ts)
% Discrete state space [x_I ; x_R]: trapezoidal integrator + Tustin remainder.
    Rd = c2d(ss(R), Ts, 'tustin');
    Ai = 1; Bi = kI*Ts; Ci = 1; Di = kI*Ts/2;
    C = ss(blkdiag(Ai, Rd.A), [Bi; Rd.B], [Ci, Rd.C], Di + Rd.D, Ts);
end

function L = conditioningGain(C)
% Hanus general conditioning gain. Self-conditioned choice L = B/D has eig(A - LC)
% = controller transmission zeros, one of which sits at exactly z = -1 (Tustin);
% move it to +0.5 by pole placement, keep every other eigenvalue where it is.
    Ad = C.A; Bd = C.B; Cd = C.C; Dd = C.D;
    ev = eig(Ad - (Bd/Dd)*Cd);
    ev(abs(ev + 1) < 1e-3) = 0.5;
    L = place(Ad', Cd', ev)';
end

function out = simSat(C, Pd, r, umax, mode, L)
% Closed loop of discrete controller C (error-driven) and ZOH plant Pd with an
% output clamp |u| <= umax and the selected anti-windup law.
    N = numel(r); n = order(C);
    Ad = C.A; Bd = C.B; Cd = C.C; Dd = C.D;
    Ap = Pd.A; Bp = Pd.B; Cp = Pd.C; Dp = Pd.D;
    switch mode
        case 'clamp', K = zeros(n,1);
        case 'integ', K = zeros(n,1); K(1) = 1;           % integrator is state 1
        case 'cond',  K = L;
    end
    xc = zeros(n,1); xp = zeros(order(Pd),1); y = 0;
    out.y = zeros(N,1); out.u = zeros(N,1); out.uUnsat = zeros(N,1);
    for k = 1:N
        e  = r(k) - y;
        ul = Cd*xc + Dd*e;
        u  = min(max(ul, -umax), umax);
        xc = Ad*xc + Bd*e + K*(u - ul);
        xp = Ap*xp + Bp*u;  y = Cp*xp + Dp*u;
        out.y(k) = y; out.u(k) = u; out.uUnsat(k) = ul;
    end
end

function printMetrics(label, res, t, rFinal, tRef, umax)
    fprintf('\n  %s\n', label);
    Ts = t(2) - t(1);
    names = fieldnames(res);
    for i = 1:numel(names)
        o = res.(names{i}); seg = t >= tRef;
        err = o.y(seg) - rFinal; tt = t(seg);
        idx = find(abs(err) > 0.02*rFinal, 1, 'last');
        if isempty(idx), settle = 0; else, settle = tt(idx) - tRef; end
        fprintf('    %-6s rail %.2f s   peak %.3f   min %.3f   2%% settle %.2f s   final err %+.1e\n', ...
                names{i}, sum(abs(o.u) >= umax - 1e-12)*Ts, max(o.y(seg)), min(o.y(seg)), settle, err(end));
    end
end

function plotAW(t, r, res, umax, ttl, leg, fname)
% Youla-H family in black (dotted / dash-dot / solid), H-inf in blue dashed.
    styles = {'b--','k:','k-.','k-'}; widths = [1.5 2.0 1.5 1.5];
    names = fieldnames(res);
    figure('Name', fname);
    tl = tiledlayout(2,1,'TileSpacing','compact','Padding','compact');
    nexttile; hold on; grid on;
    plot(t, r, '-', 'Color', [0.75 0.75 0.75], 'LineWidth', 1.0);
    for i = 1:numel(names), plot(t, res.(names{i}).y, styles{i}, 'LineWidth', widths(i)); end
    ylabel('y'); title(ttl, 'FontWeight','bold');
    nexttile; hold on; grid on;
    for i = 1:numel(names), plot(t, res.(names{i}).u, styles{i}, 'LineWidth', widths(i)); end
    yline(umax, '-', 'Color', [0.75 0.75 0.75]);
    ylabel('u'); xlabel('Time [sec]');
    lgd = legend([{'reference'}, leg], 'NumColumns', 3);
    lgd.Layout.Tile = 'south';
    saveFig(gcf, fname);
end

function saveFig(h, base)
    set(h, 'Color', 'w');
    exportgraphics(h, [base '.png'], 'Resolution', 300);
    exportgraphics(h, [base '.pdf'], 'ContentType', 'vector');
end
