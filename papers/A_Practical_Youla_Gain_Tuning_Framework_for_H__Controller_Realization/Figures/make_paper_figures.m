%% make_paper_figures.m
%  Regenerates the manuscript's computed figures with a vertically compressed
%  aspect ratio (to cut page count), in the same style as the originals: MATLAB
%  defaults, black line styles for the controller family, blue for the inverse
%  weights, bold titles, boxed legends, 'Time [sec]' / 'Frequency (rad/s)'.
%
%  Figure  File            Content
%    2     H-TSY-18        T, S, Y of the H-inf controller vs 1/Wd, 1/Wp, 1/Wu
%    3     YH-TSY-18       same for the Youla-H controller
%    4     H-&-YH-Gc-18    |Gc| of both controllers (1e-6 .. 1e3 rad/s)
%    5     FTP75           FTP-75 target speed, first 340 s, in kph
%    7     H-TSY-2nd       example plant 1/(s+1)  -- REPLACE the placeholder weights
%    8     YH-AW-18        saturated drivetrain step: clamp only / integrator
%                          back-calc. / full-state conditioning (antiwindup study)
%  Figure 1 (block diagram) and Figure 6 (nonlinear-model tracking error) are not
%  produced here: 6 needs the nonlinear drivetrain model of tan2025scaling.
%
%  Output: Figures/compressed/<name>.png (screen-resolution PNG via saveas, like
%  the originals) and .pdf (vector). Adjust FIG_H below to taste; the originals were
%  875 x 656 px (aspect 0.75), FIG_H = 380 gives 0.43.
%
%  Requires: Control System Toolbox, Robust Control Toolbox.

clear; clc; close all;
s  = tf('s');
Ts = 1e-3;
FIG_W = 875;  FIG_H = 380;                     % compressed aspect ratio
here   = fileparts(mfilename('fullpath')); if isempty(here), here = pwd; end
outdir = fullfile(here, 'compressed'); if ~exist(outdir, 'dir'), mkdir(outdir); end
w  = logspace(-2, 4, 800);                     % TSY frequency grid (Figs 2, 3, 7)
wG = logspace(-6, 3, 900);                     % Gc frequency grid (Fig 4)

%% ---------------------------------------------------------------- drivetrain synthesis
Gp = 22.624/(s + 4.32e-5);                     % Eq. Gp_numerical
Wd = makeweight(0.707, 18, 1e3, 0, 1);         % Appendix A weights (wc = 18)
Wp = makeweight(1e4, 18, 0.707, 0, 2);
Wu = makeweight(0.707, 300, 1e4, 0, 2);
[Gc_H, Gc_YH, info] = youlaH(Gp, Wp, Wu, Wd);
[S_H,  T_H,  Y_H ] = loopTFs(Gc_H,  Gp);
[S_YH, T_YH, Y_YH] = loopTFs(Gc_YH, Gp);
fprintf('Drivetrain: gamma = %.4f, T_H(0) = %.6f, T_YH(0) = %.8f\n', info.gamma, info.T0_H, info.T0_YH);

%% Figure 2 / 3 -- TSY plots
tsyFigure(w, T_H,  S_H,  Y_H,  Wd, Wp, Wu, 'H\infty TSY wc=18',  [-120 20], fullfile(outdir, 'H-TSY-18'),  FIG_W, FIG_H);
tsyFigure(w, T_YH, S_YH, Y_YH, Wd, Wp, Wu, 'Youla-H TSY wc=18',  [-120 20], fullfile(outdir, 'YH-TSY-18'), FIG_W, FIG_H);

%% Figure 4 -- controller magnitude comparison
h = newFig(FIG_W, FIG_H); hold on; grid on;
plot(wG, mag2db(abs(squeeze(freqresp(Gc_H,  wG)))), 'k-');
plot(wG, mag2db(abs(squeeze(freqresp(Gc_YH, wG)))), 'k--');
set(gca, 'XScale', 'log'); xlim([1e-6 1e3]); ylim([-40 80]);
xlabel('Frequency (rad/s)'); ylabel('Magnitude (dB)');
title('H\infty & Youla-H, Gc, wc=18', 'FontWeight', 'bold');
legend({'H\infty', 'Youla-H'}, 'Location', 'south');
saveFig(h, fullfile(outdir, 'H-&-YH-Gc-18'));

%% Figure 5 -- FTP-75 drive cycle, first 340 s
cyc = readmatrix(fullfile(here, '..', '..', '..', 'references', 'drive_cycles', 'ftpcol.txt'), ...
                 'FileType', 'text', 'NumHeaderLines', 2);
tC = cyc(:, 1); vC = cyc(:, 2) * 1.609344;    % mph -> kph
keep = tC <= 340;
h = newFig(FIG_W, FIG_H); hold on;
plot(tC(keep), vC(keep), 'k-');
xlim([0 350]); ylim([0 100]);
xlabel('Time [sec]'); ylabel('Speed [kph]');
title('FTP75 Drive Cycle: 340sec', 'FontWeight', 'bold');
saveFig(h, fullfile(outdir, 'FTP75'));

%% Figure 7 -- example plant  (REPLACE the three weights with the originals)
Gp2 = 1/(s + 1);
Wp2 = makeweight(1e4, 1.0, 1e-3);              % placeholder, read off Figure 7
Wd2 = makeweight(0.1, 1.0, 50);
Wu2 = makeweight(0.1, 100, 30);
[Gc_H2, ~, info2] = youlaH(Gp2, Wp2, Wu2, Wd2);
[S_H2, T_H2, Y_H2] = loopTFs(Gc_H2, Gp2);
fprintf('Example plant: gamma = %.4f, T_H(0) = %.7f\n', info2.gamma, info2.T0_H);
tsyFigure(logspace(-1.5, 2.5, 600), T_H2, S_H2, Y_H2, Wd2, Wp2, Wu2, 'H\infty TSY', [-60 20], ...
          fullfile(outdir, 'H-TSY-2nd'), FIG_W, FIG_H);

%% Figure 8 -- saturated drivetrain step (antiwindup study, section A)
[kI, R] = splitIntegrator(Gc_YH);
ctrlH  = c2d(ss(Gc_H), Ts, 'tustin');
ctrlYH = splitRealization(kI, R, Ts);
Pd     = c2d(ss(Gp), Ts, 'zoh');
LH = conditioningGain(ctrlH); LYH = conditioningGain(ctrlYH);
Umax = 0.10;  tA = (0:Ts:12)';  rA = 5*(tA >= 0.5);
res.H     = simSat(ctrlH,  Pd, rA, Umax, 'clamp', LH);
res.YH    = simSat(ctrlYH, Pd, rA, Umax, 'clamp', LYH);
res.integ = simSat(ctrlYH, Pd, rA, Umax, 'integ', LYH);
res.cond  = simSat(ctrlYH, Pd, rA, Umax, 'cond',  LYH);

h = newFig(FIG_W, round(1.35*FIG_H));          % two stacked panels + legend
tl = tiledlayout(2, 1, 'TileSpacing', 'compact', 'Padding', 'compact');
nexttile; hold on; grid on;
plot(tA, rA, '-', 'Color', [0.75 0.75 0.75]);
plot(tA, res.H.y, 'b--'); plot(tA, res.YH.y, 'k:'); plot(tA, res.integ.y, 'k-.'); plot(tA, res.cond.y, 'k-');
ylabel('v [m/s]'); title('Drivetrain wc=18: Saturated Step Response', 'FontWeight', 'bold');
nexttile; hold on; grid on;
plot(tA, res.H.u, 'b--'); plot(tA, res.YH.u, 'k:'); plot(tA, res.integ.u, 'k-.'); plot(tA, res.cond.u, 'k-');
yline( Umax, '-', 'Color', [0.75 0.75 0.75]); yline(-Umax, '-', 'Color', [0.75 0.75 0.75]);
ylabel('T_e [N\cdotm]'); xlabel('Time [sec]');
lgd = legend({'H_\infty, clamp only', 'Youla-H, clamp only', ...
              'Youla-H, integrator back-calc.', 'Youla-H, full-state conditioning'}, 'NumColumns', 2);
lgd.Layout.Tile = 'south';
saveFig(h, fullfile(outdir, 'YH-AW-18'));

fprintf('Done. Figures written to %s\n', outdir);

%% ================================================================== local functions
function h = newFig(wpx, hpx)
    h = figure('Position', [100 100 wpx hpx], 'Color', 'w');
end

function tsyFigure(w, T, S, Y, Wd, Wp, Wu, ttl, yl, fname, wpx, hpx)
    h = newFig(wpx, hpx); hold on; grid on;
    plot(w, mag2db(abs(squeeze(freqresp(T, w)))), 'k-');
    plot(w, mag2db(abs(squeeze(freqresp(S, w)))), 'k--');
    plot(w, mag2db(abs(squeeze(freqresp(Y, w)))), 'k:');
    plot(w, -mag2db(abs(squeeze(freqresp(Wd, w)))), 'b--');
    plot(w, -mag2db(abs(squeeze(freqresp(Wp, w)))), 'b-.');
    plot(w, -mag2db(abs(squeeze(freqresp(Wu, w)))), 'b:');
    set(gca, 'XScale', 'log'); xlim([w(1) w(end)]); ylim(yl);
    xlabel('Frequency (rad/s)'); ylabel('Magnitude (dB)'); title(ttl, 'FontWeight', 'bold');
    legend({'T', 'S', 'Y', '1/Wd', '1/Wp', '1/Wu'}, 'Location', 'south', 'NumColumns', 3);
    saveFig(h, fname);
end

function [Gc_H, Gc_YH, info] = youlaH(Gp, Wp, Wu, Wd)
% Hinf synthesis then the Youla-H gain adjustment (Appendix A flow, numerically).
    mreal_tol = 1e-3;
    Ph = augw(Gp, Wp, Wu, Wd);
    [sysGc, ~, gam] = hinfsyn(Ph);
    Gc_H = zpk(minreal(tf(sysGc), mreal_tol));
    [S_H, T_H, Y_H] = loopTFs(Gc_H, Gp);
    T0_H  = evalfr(T_H, 0);
    Y_YH  = Y_H / T0_H;
    Gc_YH = zpk(minreal(Y_YH/(1 - Y_YH*Gp), mreal_tol));
    Gc_YH = snapIntegrator(Gc_YH);
    [S_YH, T_YH, ~] = loopTFs(Gc_YH, Gp);
    info.gamma = gam; info.T0_H = T0_H; info.T0_YH = evalfr(T_YH, 0);
    info.M2_H = 1/norm(S_H, inf); info.M2_YH = 1/norm(S_YH, inf);
end

function [S, T, Y] = loopTFs(Gc, Gp)
    mreal_tol = 1e-3;
    L = Gc*Gp;
    S = zpk(minreal(1/(1 + L), mreal_tol));
    T = zpk(minreal(L/(1 + L), mreal_tol));
    Y = zpk(minreal(Gc/(1 + L), mreal_tol));
end

function G = snapIntegrator(G)
    [z, p, k] = zpkdata(G, 'v');
    [pmin, i] = min(abs(p));
    assert(pmin < 1e-3, 'no near-origin pole to snap (closest %.2e)', pmin);
    p(i) = 0;
    G = zpk(z, p, k);
end

function [kI, R] = splitIntegrator(Gc)
    [R, Gi] = stabsep(ss(Gc), 'Offset', 1e-6);
    assert(order(Gi) == 1, 'expected exactly one marginal pole, got %d', order(Gi));
    kI = Gi.C*Gi.B;
    assert(isstable(R), 'remainder is not stable');
end

function C = splitRealization(kI, R, Ts)
    Rd = c2d(ss(R), Ts, 'tustin');
    C  = ss(blkdiag(1, Rd.A), [kI*Ts; Rd.B], [1, Rd.C], kI*Ts/2 + Rd.D, Ts);
end

function L = conditioningGain(C)
    Ad = C.A; Bd = C.B; Cd = C.C; Dd = C.D;
    ev = eig(Ad - (Bd/Dd)*Cd);
    ev(abs(ev + 1) < 1e-3) = 0.5;
    L = place(Ad', Cd', ev)';
end

function out = simSat(C, Pd, r, umax, mode, L)
    N = numel(r); n = order(C);
    Ad = C.A; Bd = C.B; Cd = C.C; Dd = C.D;
    Ap = Pd.A; Bp = Pd.B; Cp = Pd.C; Dp = Pd.D;
    switch mode
        case 'clamp', K = zeros(n, 1);
        case 'integ', K = zeros(n, 1); K(1) = 1;
        case 'cond',  K = L;
    end
    xc = zeros(n, 1); xp = zeros(order(Pd), 1); y = 0;
    out.y = zeros(N, 1); out.u = zeros(N, 1);
    for k = 1:N
        e  = r(k) - y;
        ul = Cd*xc + Dd*e;
        u  = min(max(ul, -umax), umax);
        xc = Ad*xc + Bd*e + K*(u - ul);
        xp = Ap*xp + Bp*u;  y = Cp*xp + Dp*u;
        out.y(k) = y; out.u(k) = u;
    end
end

function saveFig(h, base)
    set(h, 'Color', 'w');
    saveas(h, [base '.png']);
    exportgraphics(h, [base '.pdf'], 'ContentType', 'vector');
end
