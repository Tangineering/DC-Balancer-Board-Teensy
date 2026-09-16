%% make_paper_figures.m
%  Regenerates the manuscript's computed figures with a vertically compressed
%  aspect ratio (to cut page count), in the same style as the originals: MATLAB
%  defaults, black line styles for the controller family, blue for the inverse
%  weights, bold titles, boxed legends, 'Time [sec]' / 'Frequency (rad/s)'.
%
%  Figure numbers follow the ACC (two-column) version, root.pdf:
%    2     H-TSY-18        T, S, Y of the H-inf controller vs 1/Wd, 1/Wp, 1/Wu
%    3     YH-TSY-18       same for the Youla-H controller
%    4     H-&-YH-Gc-18    |Gc| of both controllers (1e-6 .. 1e3 rad/s)
%    5     FTP75           FTP-75 target speed, first 340 s, in kph
%    8     H-TSY-2nd       example plant 1/(s+1)  -- REPLACE the placeholder weights
%  Not produced here: Figure 1 (block diagram), Figure 6 (needs the nonlinear
%  drivetrain model of tan2025scaling) and Figure 7 (the anti-windup step, generated
%  by antiwindup_study/antiwindup_variants.m).
%
%  Output: Figures/compressed/<name>.png (screen-resolution PNG via saveas, like
%  the originals) and .pdf (vector). Adjust FIG_H below to taste; the originals were
%  875 x 656 px (aspect 0.75), FIG_H = 380 gives 0.43. In the ACC layout every figure
%  is column-width, so only the aspect ratio matters for the page count.
%
%  Requires: Control System Toolbox, Robust Control Toolbox.

clear; clc; close all;
s  = tf('s');
FIG_W = 875;  FIG_H = 380;                     % compressed aspect ratio
here   = fileparts(mfilename('fullpath')); if isempty(here), here = pwd; end
outdir = fullfile(here, 'Figures', 'compressed'); if ~exist(outdir, 'dir'), mkdir(outdir); end
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
cyc = readmatrix(fullfile(here, '..', '..', 'references', 'drive_cycles', 'ftpcol.txt'), ...
                 'FileType', 'text', 'NumHeaderLines', 2);
tC = cyc(:, 1); vC = cyc(:, 2) * 1.609344;    % mph -> kph
keep = tC <= 340;
h = newFig(FIG_W, 240); hold on;
plot(tC(keep), vC(keep), 'k-');
xlim([0 350]); ylim([0 100]);
xlabel('Time [sec]'); ylabel('Speed [kph]');
title('FTP75 Drive Cycle: 340sec', 'FontWeight', 'bold');
saveFig(h, fullfile(outdir, 'FTP75'));

%% Figure 8 -- example plant  (REPLACE the three weights with the originals)
Gp2 = 1/(s + 1);
Wp2 = makeweight(1e4, 1.0, 1e-3);              % placeholder, read off Figure 7
Wd2 = makeweight(0.1, 1.0, 50);
Wu2 = makeweight(0.1, 100, 30);
[Gc_H2, ~, info2] = youlaH(Gp2, Wp2, Wu2, Wd2);
[S_H2, T_H2, Y_H2] = loopTFs(Gc_H2, Gp2);
fprintf('Example plant: gamma = %.4f, T_H(0) = %.7f\n', info2.gamma, info2.T0_H);
tsyFigure(logspace(-1.5, 2.5, 600), T_H2, S_H2, Y_H2, Wd2, Wp2, Wu2, 'H\infty TSY', [-60 20], ...
          fullfile(outdir, 'H-TSY-2nd'), FIG_W, FIG_H);

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

function saveFig(h, base)
    set(h, 'Color', 'w');
    saveas(h, [base '.png']);
    exportgraphics(h, [base '.pdf'], 'ContentType', 'vector');
end
