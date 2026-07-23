%% droop_plant.m — MATLAB cross-validation of the SHIPPED Youla-H share controller
% Independently validates the controller produced by synthesize_controller.py:
%   A) Re-runs the H-inf + Youla-H synthesis with the EXACT shipped weights
%      (strictly-proper Wp, first-order Wd/Wu, tau_f in the plant) and compares
%      gamma, T(0), kI, crossover, and M2 against the Python pipeline's numbers.
%   B) Parses ../teensy_controller/share_controller_coeffs.h (the GENERATED
%      firmware coefficients) and compares the shipped Gc(z) frequency response
%      against the MATLAB-synthesized controller.
%   C) Re-runs the validation battery on the SHIPPED Gc(z): 30-corner discrete
%      stability + sensitivity peaks, nominal margins, step and ramp tracking —
%      using the firmware-accurate topology (measurement filter Hf(z) in the
%      feedback path only; setpoint unfiltered).
%
% Outputs (no copy/paste needed):
%   MATLAB_validation.txt                     — full numeric log (this folder)
%   figures/MATLAB_loopshapes_exactweights.png
%   figures/MATLAB_Gc_shipped_vs_matlab.png
%   figures/MATLAB_shipped_step_ramp.png
%
% Requires: Control System Toolbox + Robust Control Toolbox. Tested syntax: R2024b.

clear; clc; close all;
here   = fileparts(mfilename('fullpath'));
figdir = fullfile(here, 'figures');
hdrfile = fullfile(here, '..', 'teensy_controller', 'share_controller_coeffs.h');
fid = fopen(fullfile(here, 'MATLAB_validation.txt'), 'w');
% logf (end of file): prints to console AND the validation file

logf(fid, 'MATLAB cross-validation of the shipped Youla-H share controller\n');
logf(fid, 'generated: %s\n\n', datestr(now));

% ── Python pipeline reference values (synthesis_metrics.txt, 2026-07-10) ────
ref.gamma_opt   = 0.6532;
ref.T0_H        = 0.99996423;
ref.kI          = 111.9296;
ref.crossover   = 109.9;      % rad/s
ref.M2_nominal  = 0.7978;
ref.step_settle = 0.022;      % s (2%)
ref.ramp_err    = 4.47e-4;

%% ═══ A. Exact-weight synthesis reproduction ═════════════════════════════════
Ts   = 1e-3;
Td   = 1.0e-3;  taur = 100e-6;  tauf = 0.8e-3;      % nominal plant (TODO(calibrate))
mkGp = @(K, Td_, taur_, tauf_) K * pade_tf(Td_, 2) * tf(1, [taur_ 1]) ...
                                 * tf_optional_lag(tauf_);
Gp = mkGp(1.0, Td, taur, tauf);

% EXACT shipped weights (synthesize_controller.py §2):
%  Wp: strictly proper, dc = 1e4, |Wp(j40)| = 1  ->  Wp = dc*a/(s+a), a = 40/sqrt(dc^2-1)
a_wp = 40/sqrt(1e8 - 1);
Wp = tf(1e4*a_wp, [1 a_wp]);
Wd = makeweight(0.5, 250, 40);      % on T
Wu = makeweight(0.3, 600, 20);      % on Y

Ph = augw(Gp, Wp, Wu, Wd);
[K0, ~, gam_opt] = hinfsyn(Ph);
logf(fid, 'A. synthesis: hinfsyn gamma_opt = %.4f   (Python: %.4f, diff %+.1f%%)\n', ...
     gam_opt, ref.gamma_opt, 100*(gam_opt/ref.gamma_opt - 1));

% same 5%% back-off as the Python pipeline (fallback: near-optimal controller)
try
    [sysGc, ~, gam_used] = hinfsyn(Ph, 1, 1, gam_opt*1.05);
catch
    sysGc = K0; gam_used = gam_opt;
    logf(fid, '   (4-arg hinfsyn unavailable; using near-optimal controller)\n');
end
mtol = 1e-3;
Gc_H = zpk(minreal(tf(sysGc), mtol));

L_H = minreal(Gp*Gc_H, mtol);
S_H = minreal(1/(1+L_H), mtol);
T_H = minreal(L_H/(1+L_H), mtol);
Y_H = minreal(Gc_H/(1+L_H), mtol);
T0_H = dcgain(T_H);
logf(fid, '   T_H(0) = %.8f          (Python: %.8f)\n', T0_H, ref.T0_H);

% Youla-H gain adjustment (paper Eq. 5, numeric form)
Y_YH  = Y_H / T0_H;
Gc_YH = zpk(minreal(feedback(Y_YH, Gp, +1), mtol));   % Y/(1 - Y*Gp)
L_YH  = minreal(Gp*Gc_YH, mtol);
T_YH  = minreal(L_YH/(1+L_YH), mtol);
S_YH  = minreal(1/(1+L_YH), mtol);
logf(fid, ['   T_YH(0) = %.9f  (= 1 up to minreal tolerance; the SHIPPED controller''s\n' ...
           '   exact-integrator DC check is section C''s closed-loop DC gain)\n'], dcgain(T_YH));

% Integrator residue kI: probe at w = 0.3 rad/s — above the numerical near-zero
% pole that feedback()+minreal leave at ~1e-3 (an exact-0 probe reads the DC
% plateau instead of the residue), below the R(s) dynamics. The -90 deg
% component rejects the finite R(0) real-part bias: Gc(jw) ~ kI/(jw) + R(0).
w_kI = 0.3;
kI_m = -imag(squeeze(freqresp(Gc_YH, w_kI)))*w_kI;
wc_m = getGainCrossover(L_YH, 1); wc_m = wc_m(1);
M2_m = 1/getPeakGain(S_YH);
logf(fid, '   kI = %.3f (Python %.3f), crossover = %.1f rad/s (Python %.1f), M2 = %.3f (Python %.3f)\n\n', ...
     kI_m, ref.kI, wc_m, ref.crossover, M2_m, ref.M2_nominal);

f1 = figure('Name', 'loopshapes');
bodemag(T_YH, 'k-', S_YH, 'k--', minreal(Gc_YH/(1+L_YH), mtol), 'k:', ...
        1/Wd, 'b--', 1/Wp, 'b-.', 1/Wu, 'b:', {1e-2, 1e5}); grid on;
legend('T', 'S', 'Y', '1/Wd', '1/Wp', '1/Wu');
title('Exact-weight Youla-H loop shapes (MATLAB reproduction)');
exportgraphics(f1, fullfile(figdir, 'MATLAB_loopshapes_exactweights.png'), 'Resolution', 150);

%% ═══ B. Parse the SHIPPED firmware coefficients and compare ═════════════════
txt = fileread(hdrfile);
tok  = regexp(txt, 'SHARE_CTRL_TS_US\s+(\d+)', 'tokens', 'once');
Ts_fw = str2double(tok{1})*1e-6;
tok  = regexp(txt, 'SHARE_CTRL_KI\s*=\s*([^f;\s]+)f', 'tokens', 'once');
kI_fw = str2double(tok{1});
tok  = regexp(txt, 'SHARE_CTRL_MEAS_FILT_A\s*=\s*([^f;\s]+)f', 'tokens', 'once');
Afilt = str2double(tok{1});
rows = regexp(txt, '\{\s*([^{}]*?)\s*\}', 'tokens');   % SOS rows (skip outer array brace)
sosco = [];
for i = 1:numel(rows)
    v = sscanf(strrep(rows{i}{1}, 'f', ''), '%f,');
    if numel(v) == 5, sosco(end+1, :) = v(:).'; end %#ok<SAGROW>
end
assert(~isempty(sosco), 'failed to parse SOS rows from %s', hdrfile);
logf(fid, 'B. parsed %s:\n   Ts = %g s, kI = %.4f, filt A = %.6f, %d SOS section(s)\n', ...
     hdrfile, Ts_fw, kI_fw, Afilt, size(sosco, 1));
logf(fid, '   kI shipped vs MATLAB-synthesized: %.3f vs %.3f (%+.2f%%)\n', ...
     kI_fw, kI_m, 100*(kI_fw/kI_m - 1));

Rz = tf(1, 1, Ts_fw);
for i = 1:size(sosco, 1)
    Rz = Rz * tf(sosco(i, 1:3), [1 sosco(i, 4:5)], Ts_fw);
end
Iz = tf(kI_fw*Ts_fw/2*[1 1], [1 -1], Ts_fw);           % trapezoidal integrator
Gc_fw = Rz + Iz;                                        % the SHIPPED controller
Hf = tf((1-Afilt)*[1 0], [1 -Afilt], Ts_fw);            % measurement filter y=A y+(1-A)u

% frequency-response comparison vs MATLAB-synthesized Youla-H (Tustin-discretized)
Gc_m_d = c2d(ss(Gc_YH), Ts_fw, 'tustin');
wcmp = logspace(0, log10(0.9*pi/Ts_fw), 400);
r_fw = squeeze(freqresp(Gc_fw,  wcmp));
r_m  = squeeze(freqresp(Gc_m_d, wcmp));
devB = max(abs(r_fw - r_m)./abs(r_m));
logf(fid, ['   max rel. freq-response deviation, shipped vs MATLAB-synthesized: %.2f%%\n' ...
      '   (< ~10%% expected: order reduction 21->3 + two independent gamma iterations;\n' ...
      '   the closed-loop agreement in section C is the meaningful comparison)\n\n'], 100*devB);

f2 = figure('Name', 'Gc comparison');
bodemag(Gc_m_d, 'k-', Gc_fw, 'r--', {1e-1, pi/Ts_fw}); grid on;
legend('MATLAB-synthesized G_C(z) (full order)', 'Shipped firmware G_C(z) (int + 3 states)');
title('Shipped controller vs independent MATLAB synthesis');
exportgraphics(f2, fullfile(figdir, 'MATLAB_Gc_shipped_vs_matlab.png'), 'Resolution', 150);

%% ═══ C. Independent validation battery on the SHIPPED controller ════════════
% Firmware-accurate topology: e = ref - Hf*alpha (filter in feedback path only),
% physical plant = K * Pade2(Td) * 1/(taur s + 1)  — tau_f is NOT in the plant
% (it is realized by Hf inside the firmware wrapper).
logf(fid, 'C. shipped-controller validation battery (discrete, Ts = %g s)\n', Ts_fw);
K_SET  = [0.55 0.75 1.0 1.25 1.45];
TD_SET = [0.5 1.0 2.0]*1e-3;
TR_SET = [20 300]*1e-6;
worstS = 0; worstC = [0 0 0]; nUnstable = 0;
for K = K_SET
    for Td_ = TD_SET
        for tr = TR_SET
            Gpd = c2d(ss(K * pade_tf(Td_, 2) * tf(1, [tr 1])), Ts_fw, 'zoh');
            Ld  = Gpd * Gc_fw * Hf;                     % loop gain
            Sd  = feedback(1, Ld);
            if ~isstable(Sd)
                nUnstable = nUnstable + 1;
                logf(fid, '   UNSTABLE corner: K=%.2f Td=%.1fms taur=%.0fus\n', K, Td_*1e3, tr*1e6);
            else
                pk = getPeakGain(Sd, 1e-3);
                if pk > worstS, worstS = pk; worstC = [K Td_ tr]; end
            end
        end
    end
end
logf(fid, '   corners: %d/30 stable; worst ||S||inf = %.3f (M2 = %.3f) at K=%.2f Td=%.1fms taur=%.0fus\n', ...
     30 - nUnstable, worstS, 1/worstS, worstC(1), worstC(2)*1e3, worstC(3)*1e6);
logf(fid, '   (Python worst-corner discrete ||S||inf was 1.867 on its 60-corner grid incl. tau_f variants)\n');

% nominal margins on the shipped loop
Gpd_nom = c2d(ss(mkGp(1, Td, taur, 0)), Ts_fw, 'zoh');  % tau_f=0: filter is in Hf
Ld_nom  = Gpd_nom * Gc_fw * Hf;
[Gm, Pm, ~, Wcp] = margin(Ld_nom);
logf(fid, '   nominal margins: GM = %.1f dB, PM = %.1f deg at %.1f rad/s, delay margin = %.2f ms\n', ...
     20*log10(Gm), Pm, Wcp, (Pm*pi/180)/Wcp*1e3);

% step + ramp tracking: ref -> alpha = Gpd*Gc / (1 + Gpd*Gc*Hf)  (setpoint unfiltered)
Try  = feedback(Gpd_nom*Gc_fw, Hf);
si   = stepinfo(Try, 'SettlingTimeThreshold', 0.02);
logf(fid, '   step: 2%% settle = %.0f ms (Python: %.0f ms), overshoot = %.1f%%, DC gain = %.9f\n', ...
     si.SettlingTime*1e3, ref.step_settle*1e3, si.Overshoot, dcgain(Try));
t = (0:8000-1)'*Ts_fw;
rmp = 0.05*max(0, t - 0.01);  rmp = min(rmp, 0.3);      % EMS blend 0.05 share/s
y = lsim(Try, rmp, t);
logf(fid, '   ramp: tracking error at t = 6 s: %.2e (Python: %.2e)\n', ...
     abs(y(6001) - rmp(6001)), ref.ramp_err);

f3 = figure('Name', 'shipped step+ramp');
tiledlayout(2, 1);
nexttile; step(Try, 0.4); grid on; title('Shipped G_C(z): step response (nominal plant)');
nexttile; plot(t, rmp, 'k:', t, y, 'b-'); grid on;
legend('ramp reference', '\alpha', 'Location', 'southeast');
title('Shipped G_C(z): ramp tracking (T(0)=1 — no accumulating bias)');
xlabel('Time (s)');
exportgraphics(f3, fullfile(figdir, 'MATLAB_shipped_step_ramp.png'), 'Resolution', 150);

verdict = (nUnstable == 0) && (worstS < 2.5) && (abs(dcgain(Try) - 1) < 1e-6);
if verdict
    logf(fid, '\nVERDICT: PASS — all 30 corners stable, worst ||S||inf = %.3f, exact DC tracking.\n', worstS);
else
    logf(fid, '\nVERDICT: FAIL — see lines above (unstable corners, ||S||inf >= 2.5, or DC gain != 1).\n');
end
fclose(fid);
fprintf('\nwrote MATLAB_validation.txt + 3 figures to figures/\n');

%% helpers
function P = pade_tf(Td, n)
    [np, dp] = pade(Td, n);
    P = tf(np, dp);
end

function P = tf_optional_lag(tau)
    if tau > 0, P = tf(1, [tau 1]); else, P = tf(1, 1); end
end

function logf(fid, varargin)
    % print to the console and mirror into the validation file
    fprintf(1, varargin{:});
    fprintf(fid, varargin{:});
end
