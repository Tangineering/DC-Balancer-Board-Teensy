%% =====================================================================
%  *** STALE — DO NOT TRUST A GREEN RESULT FROM THIS FILE (2026-08-16) ***
%
%  This script rebuilds the 2x2 plant from constants HARDCODED below, which are
%  the PRE-CALIBRATION placeholder values.  The drive channel was calibrated on
%  2026-08-16 (calibration/motor_id_20260815.md); plant_mimo.py now carries the
%  measured constants and they differ substantially:
%      k_t   5.457e-3 -> 4.266e-3 N*m/A       r_t   0.033 -> 0.0762 m
%      m_eff 2.95     -> 3.5 kg               R_m   0.075 -> 0.0226 ohm
%      b_eff 0.3597   -> 0.32 N*s/m (measured local slope; the aero + C_rr +
%                                    free-run composite is RETIRED)
%      G22(0) 3.7085  -> 1.4112 (m/s)/A       drive pole -0.1219 -> -0.0914 rad/s
%      I_CLAMP 20 A   -> 12 A
%
%  The failure mode here is the dangerous one: this file validates against
%  mimo_controller_coeffs.h and the metrics files, which are ALSO stale, so the
%  two agree and the script reports PASS.  That agreement confirms only that the
%  MATLAB and Python transcriptions of a RETIRED plant match each other.
%
%  Do not re-run this as a check on the current design.  It is superseded until
%  the MIMO controller is re-synthesized on the calibrated plant, at which point
%  the constants below must be updated in lockstep with plant_mimo.py.
%  Status and scope: README.md staleness banner; mimo_system_model.md 11.
%  The MATLAB mirror is deliberately left otherwise unmodified.
%% =====================================================================

%% mimo_crosscheck.m — MATLAB cross-validation of the MIMO H-inf / Youla-H design
% Independently validates controller_design_MIMO's Python pipeline, mirroring
% what controller_design/droop_plant.m does for the SISO share controller:
%   A) Rebuilds the 2x2 design plant from the documented equations/constants
%      (mimo_system_model.md) with MATLAB tf algebra — NO import from Python —
%      and checks the DC-gain matrix.
%   B) Re-runs the H-inf synthesis with the EXACT shipped weights (hinfsyn on
%      augw of the scaled plant) and applies the MIMO Youla-H DC correction
%      M = [Gs(0) Y_H(0)]^-1, Y_YH = Y_H*M  ->  T(0) = I  (the thesis
%      contribution; mimo_synthesis.md §4). Compares gamma against the Python
%      pipeline's Riccati-bisection and a-posteriori values.
%   C) Parses mimo_controller_coeffs.h (the GENERATED artefact) and validates
%      the SHIPPED controller: closed-loop stability, T(0) = I, nominal
%      sigma_max(S_o), per-channel S peaks, cross-coupling transfer, and the
%      a-posteriori ||Tzw||inf on the weighted plant.
%   D) 576-corner battery (24 share x 24 drive corners at the nominal OP,
%      discrete, Ts = 2 ms): stability count + worst sigma_max(S_o).
%   E) Small-signal drive-transient share excursion at dV0 = +-0.4 V
%      (v_ref step +0.05 m/s), compared against comparison_metrics.txt.
%
% Outputs (no copy/paste needed — give MATLAB_mimo_results.txt back to Claude):
%   MATLAB_mimo_results.txt                    — full numeric log (this folder)
%   figures/MATLAB_mimo_sigmaS.png
%   figures/MATLAB_mimo_corner_scatter.png
%   figures/MATLAB_mimo_transient.png
%
% Requires: Control System Toolbox + Robust Control Toolbox. Tested syntax
% target: R2024b (same as controller_design/droop_plant.m).

% ╔══════════════════════════════════════════════════════════════════════════╗
% ║ STALE-RESULT WARNING (2026-08-04)                                        ║
% ║ MATLAB_mimo_results.txt on disk PREDATES the +-20 A recalibration round.  ║
% ║ The old log was renamed MATLAB_mimo_results_5A.txt; re-run THIS script to ║
% ║ revalidate and regenerate MATLAB_mimo_results.txt at the new design.      ║
% ║ Everything below (ref.*, Du, gamma) is already updated to the +-20 A      ║
% ║ controller (mimo_controller_coeffs.h, MIMO_CTRL_NX = 7, 9 total states).  ║
% ╚══════════════════════════════════════════════════════════════════════════╝

clear; clc; close all;
here    = fileparts(mfilename('fullpath'));
figdir  = fullfile(here, 'figures');
hdrfile = fullfile(here, 'mimo_controller_coeffs.h');
fid = fopen(fullfile(here, 'MATLAB_mimo_results.txt'), 'w');

logf(fid, 'MATLAB cross-validation of the MIMO H-inf / Youla-H controller\n');
logf(fid, 'generated: %s\n\n', datestr(now));

% ── Python pipeline reference values ─────────────────────────────────────────
% (mimo_synthesis_metrics.txt + comparison_metrics.txt, 2026-08-04, git-clean run)
ref.G0            = [1.0 -0.02757267; 0 3.70852146];  % design_plant dcgain_matrix
% ALL ref.* below are the +-20 A recalibration values (2026-08-04).  The
% superseded +-5 A values are given in [brackets] for traceability.
ref.gamma_bisect  = 0.89769;   % DGKF Riccati bisection (OPTIMISTIC in MIMO: Y=0
                               % makes rho(XY)<g^2 vacuous — mimo_synthesis.md)
                               % [+-5 A: 1.1917]
ref.gamma_apost   = 1.6456;    % honest a-posteriori ||Tzw||inf of the shipped
                               % design [+-5 A: 1.8168]
ref.sigmaS_nom    = 1.22867;   % nominal.mimo.sigma_So_peak      [1.20955]
ref.S11_nom       = 1.21142;   % nominal.mimo.S11_peak           [1.20942]
ref.S22_nom       = 1.22847;   % nominal.mimo.S22_peak           [1.10788]
ref.Tav_nom       = 1.31399e-3;% nominal.mimo.T_alpha_from_vref_peak (share per
                               % m/s)                            [8.7759e-4]
ref.tier2_worst   = 1.8754;    % worst in-envelope sigma(S_o) over the FULL OP grid
                               % (this file sweeps the nominal OP only — expect <=)
                               % [1.9153]
ref.exc_p         = 0.00667286;% transient.small.dV0p.mimo.max_abs_dalpha
                               % (+0.05 m/s step)                [0.0106181]
ref.exc_m         = 0.0193501; % transient.small.dV0m.mimo.max_abs_dalpha [0.030959]
ref.icmd_p        = 1.17900;   % transient.small.dV0p.mimo.peak_abs_i_cmd_A [1.32606]
ref.icmd_m        = 1.17629;   % transient.small.dV0m.mimo.peak_abs_i_cmd_A [1.31672]
ref.NX            = 7;         % MIMO_CTRL_NX in the +-20 A header (was 5); the
                               % total controller order is NX + 2 = 9 states.

% ── Nominal constants (mimo_system_model.md; provenance in that file) ────────
Ts    = 2e-3;                    % controller rate, 500 Hz (VESC UART floor)
kd    = 0.30;                    % as-built droop scale [ohm]
Td    = 1.0e-3; taur = 100e-6; tauf = 0.8e-3;   % share channel (TODO(calibrate))
tau_v = 1.0e-3; Td_v = 2.0e-3;                  % VESC lag/delay (TODO(identify))
k_t   = 9.5493/1750;             % 5.4567e-3 N*m/A, design-case KV=1750 (TODO(calibrate))
phi   = 9.49;  r_t = 0.033;  eta_dt = 0.85;  eta_v = 0.85;
m_eff = 2.95;                    % 2.5 kg design mass + 0.45 kg reflected rotor inertia
b_mot = 4.0528473456935104e-6;   % motor-shaft viscous [N*m*s/rad] (free-run loss)
rho   = 1.225;  C_dA = 0.010;
K_enc = 1.0;  R_m = 0.075;  V_bus0 = 15.906716417910447;
De = diag([0.05 0.5]);  Du = diag([0.35 20.0]); % scaling (plan §3 / coeffs header)
% Du(2,2) = 20.0 A is the motor-current clamp U_MAX(2) = -U_MIN(2) of the
% +-20 A round (was 5.0).  Section E's linear sim never reaches it (peak ~1.2 A).

op.I_tot0 = 2.0; op.r0 = 0.5; op.dV0 = 0.2; op.v0 = 2.0;   % nominal OP

%% ═══ A. Rebuild the 2x2 design plant (documented equations only) ════════════
mkG = @(dV0, Td_, taur_, tauf_, Kv, polef, tauv_, Tdv_) build_plant( ...
        op, kd, dV0, Td_, taur_, tauf_, Kv, polef, tauv_, Tdv_, ...
        k_t, phi, r_t, eta_dt, eta_v, m_eff, b_mot, rho, C_dA, K_enc, R_m, V_bus0);
G = mkG(op.dV0, Td, taur, tauf, 1.0, 1.0, tau_v, Td_v);

G0 = dcgain(G);
devA = max(abs(G0(:) - ref.G0(:)));
logf(fid, 'A. design plant DC gain:\n   MATLAB  [%9.6f %9.6f; %9.6f %9.6f]\n', G0.');
logf(fid, '   Python  [%9.6f %9.6f; %9.6f %9.6f]   max abs dev = %.2e\n\n', ref.G0.', devA);

Gs = De \ G * Du;                               % scaled plant (synthesis coordinates)

%% ═══ B. Independent H-inf synthesis + MIMO Youla-H T(0) = I ═════════════════
% EXACT shipped weights (synthesize_mimo_controller.py SHARE_W / DRIVE_W):
%   share: Wp strictly proper dc=1e4 @40; Wd makeweight(0.5,250,40); Wu (0.3,600,20)
%   drive: Wp strictly proper dc=1e4 @24 (1st-order — the papers' 2nd-order form
%          is structurally unmeetable here, mimo_synthesis.md §3.2);
%          Wd (0.5,60,40); Wu (0.5,200,20)
sp = @(dc, wc) tf(dc*wc/sqrt(dc^2-1), [1 wc/sqrt(dc^2-1)]);
Wp = blkdiag(sp(1e4, 40), sp(1e4, 24));
Wd = blkdiag(makeweight(0.5, 250, 40), makeweight(0.5, 60, 40));
Wu = blkdiag(makeweight(0.3, 600, 20), makeweight(0.5, 200, 20));

Ph = augw(Gs, Wp, Wu, Wd);
[K0, ~, gam_m] = hinfsyn(Ph);
logf(fid, 'B. hinfsyn gamma = %.4f\n', gam_m);
logf(fid, ['   Python Riccati bisection = %.4f (optimistic: Y=0 makes rho(XY)<g^2\n' ...
           '   vacuous), Python a-posteriori shipped level = %.4f.  Expect the\n' ...
           '   MATLAB gamma between the two; large deviation = investigate.\n'], ...
           ref.gamma_bisect, ref.gamma_apost);

% MIMO Youla-H DC correction (mimo_synthesis.md §4):
mtol = 1e-4;
Y_H  = feedback(K0, Gs);                        % K (I + Gs K)^-1
M    = inv(dcgain(Gs * Y_H));                   % matrix analogue of K_H/(Y_H(0)G_P(0))
Y_YH = Y_H * M;
T0_B = dcgain(Gs * feedback(Y_YH, Gs, +1) );   % T = Gs Gc (I + Gs Gc)^-1 == Gs Y_YH
% (Gs*Y_YH IS T for the corrected loop: T = Gs*Y by the Youla identity)
T0_Y = dcgain(Gs * Y_YH);
logf(fid, '   ||M - I||_2 = %.3e (Python: 1.75e-4), cond(Gs(0)Y_H(0)) = %.4f\n', ...
     norm(M - eye(2), 2), cond(dcgain(Gs)*dcgain(Y_H)));
logf(fid, '   T(0) via Gs*Y_YH = [%12.9f %12.9f; %12.9f %12.9f]  (target I)\n\n', T0_Y.');

%% ═══ C. Parse the SHIPPED controller and validate it ════════════════════════
txt  = fileread(hdrfile);
NX   = parse_def(txt, 'MIMO_CTRL_NX');
Ts_h = parse_def(txt, 'MIMO_CTRL_TS_US')*1e-6;
assert(abs(Ts_h - Ts) < 1e-12, 'header Ts != 2 ms');
if NX ~= ref.NX
    warning(['mimo_controller_coeffs.h has MIMO_CTRL_NX = %d but this script ', ...
             'is pinned to %d (+-20 A round).  The header has been ', ...
             're-synthesized; refresh the ref.* block.'], NX, ref.NX);
end
Ah  = parse_arr(txt, 'MIMO_CTRL_A',  NX, NX);
Bh  = parse_arr(txt, 'MIMO_CTRL_B',  NX, 2);
Ch  = parse_arr(txt, 'MIMO_CTRL_C',  2,  NX);
Dh  = parse_arr(txt, 'MIMO_CTRL_D',  2,  2);
KIh = parse_arr(txt, 'MIMO_CTRL_KI', 2,  2);
logf(fid, 'C. parsed %s: NX = %d, Ts = %g s\n', hdrfile, NX, Ts_h);

% discrete scaled controller: remainder + exact Tustin integrator KI*Ts/2*(z+1)/(z-1)
Krem = ss(Ah, Bh, Ch, Dh, Ts);
Kint = tf(Ts/2*[1 1], [1 -1], Ts) * KIh;        % numeric matrix: sample-time neutral
Kd_s = Krem + Kint;                             % scaled coords: e_s -> u_s
Kd   = Du * Kd_s / De;                          % physical: (ref - y) -> u

% nominal discrete loop (plant ZOH @ 2 ms, negative feedback)
Gd  = c2d(ss(G), Ts, 'zoh');
So  = feedback(eye(2), Gd*Kd);                  % output sensitivity
To  = eye(2) - So;
stab = isstable(So);
sS   = getPeakGain(So, 1e-3);
sS11 = getPeakGain(So(1,1), 1e-3);  sS22 = getPeakGain(So(2,2), 1e-3);
Tav  = getPeakGain(To(1,2), 1e-3);              % share response to speed ref
T0_C = dcgain(To);
logf(fid, '   nominal loop: stable = %d\n', stab);
logf(fid, '   sigma(S_o) = %.4f (Python %.4f), |S11| = %.4f (%.4f), |S22| = %.4f (%.4f)\n', ...
     sS, ref.sigmaS_nom, sS11, ref.S11_nom, sS22, ref.S22_nom);
logf(fid, '   ||T_alpha<-vref|| = %.3e (Python %.3e)\n', Tav, ref.Tav_nom);
logf(fid, '   T(0) = [%12.9f %12.9f; %12.9f %12.9f]  (target I)\n', T0_C.');

% a-posteriori ||Tzw||inf of the SHIPPED controller on the weighted plant:
% d2c(tustin) inverts the pipeline's c2d(tustin) exactly (up to numerics)
Kc_s   = d2c(Kd_s, 'tustin');
Tzw    = lft(Ph, Kc_s);
gApost = hinfnorm(Tzw, 1e-4);
logf(fid, '   a-posteriori ||Tzw||inf (shipped, continuous) = %.4f (Python %.4f)\n\n', ...
     gApost, ref.gamma_apost);

f1 = figure('Name', 'sigma S');
sigma(So, {1e-1, pi/Ts}); grid on; hold on; yline(20*log10(ref.sigmaS_nom), 'r--');
title('Shipped MIMO controller: \sigma(S_o), nominal plant (red: Python peak)');
exportgraphics(f1, fullfile(figdir, 'MATLAB_mimo_sigmaS.png'), 'Resolution', 150);

%% ═══ D. 576-corner battery at the nominal OP (discrete, Ts = 2 ms) ══════════
DV0_SET = [-0.4 0 0.4];  TD_SET = [0.5 2.0]*1e-3;
TR_SET  = [20 300]*1e-6; TF_SET = [0 0.8e-3];
KV_SET  = [0.5 1 2];     PF_SET = [0.5 2];
TV_SET  = [0.5 5]*1e-3;  TDV_SET = [1 4]*1e-3;
nC = 0; nUnst = 0; worstS = 0; worstTag = '';
allS = [];
for dV0 = DV0_SET, for Td_ = TD_SET, for tr = TR_SET, for tf_ = TF_SET
  for Kv = KV_SET, for pf = PF_SET, for tv = TV_SET, for tdv = TDV_SET
    nC = nC + 1;
    Gc_ = mkG(dV0, Td_, tr, tf_, Kv, pf, tv, tdv);
    Sd  = feedback(eye(2), c2d(ss(Gc_), Ts, 'zoh')*Kd);
    if ~isstable(Sd)
        nUnst = nUnst + 1;
        logf(fid, '   UNSTABLE: dV0=%+.1f Td=%.1fms tr=%.0fus tf=%.1fms Kv=%.1f pf=%.1f tv=%.1fms tdv=%.0fms\n', ...
             dV0, Td_*1e3, tr*1e6, tf_*1e3, Kv, pf, tv*1e3, tdv*1e3);
    else
        pk = getPeakGain(Sd, 1e-2);
        allS(end+1) = pk; %#ok<SAGROW>
        if pk > worstS
            worstS = pk;
            worstTag = sprintf('dV0=%+.1f Td=%.1fms tr=%.0fus tf=%.1fms Kv=%.1f pf=%.1f tv=%.1fms tdv=%.0fms', ...
                               dV0, Td_*1e3, tr*1e6, tf_*1e3, Kv, pf, tv*1e3, tdv*1e3);
        end
    end
  end, end, end, end
end, end, end, end
logf(fid, 'D. corner battery: %d/%d stable; worst sigma(S_o) = %.4f at %s\n', ...
     nC - nUnst, nC, worstS, worstTag);
logf(fid, ['   (Python Tier-2 worst over the FULL OP grid was %.4f; this sweep is the\n' ...
           '   nominal OP only, so expect a value at or below that.)\n\n'], ref.tier2_worst);

f2 = figure('Name', 'corner scatter');
histogram(allS, 40); grid on; xlabel('\sigma(S_o) peak'); ylabel('corners');
title(sprintf('576-corner \\sigma(S_o) distribution (worst = %.3f)', worstS));
exportgraphics(f2, fullfile(figdir, 'MATLAB_mimo_corner_scatter.png'), 'Resolution', 150);

%% ═══ E. Small-signal drive transient share excursion (dV0 = +-0.4 V) ════════
% v_ref deviation step +0.05 m/s; linear sim is valid (Python peak |i_cmd| ~1.3 A,
% no clamp touched). Python simulated multirate with a 0.1 ms ZOH base plant;
% this is single-rate 2 ms ZOH — expect agreement to ~tens of %, not exact.
t = (0:Ts:12).';
excs = zeros(1, 2); icmds = zeros(1, 2); dvs = [0.4 -0.4];
f3 = figure('Name', 'transient'); tiledlayout(2, 1);
for i = 1:2
    Gc_ = mkG(dvs(i), Td, taur, tauf, 1.0, 1.0, tau_v, Td_v);
    Gd_ = c2d(ss(Gc_), Ts, 'zoh');
    Try = feedback(Gd_*Kd, eye(2));             % ref -> y
    Tru = feedback(Kd, Gd_);                    % ref -> u
    r   = [zeros(numel(t), 1), 0.05*ones(numel(t), 1)];   % speed-ref step only
    y   = lsim(Try, r, t);
    u   = lsim(Tru, r, t);
    excs(i)  = max(abs(y(:, 1)));
    icmds(i) = max(abs(u(:, 2)));
    nexttile; plot(t, y(:, 1), 'b-'); grid on; ylabel('\Delta\alpha');
    title(sprintf('v_{ref} step +0.05 m/s, \\DeltaV_0 = %+.1f V  (max |\\Delta\\alpha| = %.4f)', ...
                  dvs(i), excs(i)));
end
xlabel('Time (s)');
exportgraphics(f3, fullfile(figdir, 'MATLAB_mimo_transient.png'), 'Resolution', 150);
logf(fid, 'E. share excursion: dV0=+0.4: %.5f (Python %.5f), dV0=-0.4: %.5f (Python %.5f)\n', ...
     excs(1), ref.exc_p, excs(2), ref.exc_m);
logf(fid, '   peak |i_cmd|:    dV0=+0.4: %.3f A (Python %.3f), dV0=-0.4: %.3f A (Python %.3f)\n\n', ...
     icmds(1), ref.icmd_p, icmds(2), ref.icmd_m);

%% ═══ Verdict ═════════════════════════════════════════════════════════════════
crit = [devA < 1e-3, ...
        nUnst == 0, ...
        stab && max(abs(T0_C(:) - reshape(eye(2),[],1))) < 1e-6, ...
        abs(sS/ref.sigmaS_nom - 1) < 0.05, ...
        abs(gApost/ref.gamma_apost - 1) < 0.05, ...
        abs(excs(1)/ref.exc_p - 1) < 0.25 && abs(excs(2)/ref.exc_m - 1) < 0.25];
names = {'plant DC gain', 'all corners stable', 'T(0)=I', 'nominal sigma(S_o) 5%', ...
         'a-posteriori gamma 5%', 'transient excursions 25%'};
for i = 1:numel(crit)
    logf(fid, '  [%s] %s\n', pick(crit(i), 'PASS', 'FAIL'), names{i});
end
logf(fid, '\nVERDICT: %s\n', pick(all(crit), ...
     'PASS — MATLAB independently confirms the Python MIMO design.', ...
     'FAIL — see lines above; give this file back to Claude to diagnose.'));
fclose(fid);
fprintf('\nwrote MATLAB_mimo_results.txt + 3 figures to figures/\n');

%% helpers
function G = build_plant(op, kd, dV0, Td, taur, tauf, Kv, polef, tauv, Tdv, ...
                         k_t, phi, r_t, eta_dt, eta_v, m_eff, b_mot, rho, C_dA, ...
                         K_enc, R_m, V_bus0)
    % 2x2 design plant from mimo_system_model.md (transfer-function algebra;
    % same I/O behavior as plant_mimo.design_plant, different realization).
    K_share = 1 + dV0*(1 - 2*op.r0)/(kd*op.I_tot0);       % = 1 at r0 = 0.5
    dAdI    = -dV0*op.r0*(1 - op.r0)/(kd*op.I_tot0^2);    % share per A (sign = dV0)
    b_eff   = rho*C_dA*op.v0 + b_mot*(phi/r_t)^2;         % aero + motor free-run
    b_eff   = b_eff*polef;                                % pole_factor corner
    KF      = k_t*eta_dt*phi/r_t;                         % wheel force per amp
    omega0  = op.v0*phi/r_t;
    % OP torque balance for i_m0 (C_rr = 0.02 Coulomb term enters the OP only;
    % g = 9.80665 to match plant_mimo.G_ACC — verified to machine precision):
    i_m0    = (b_eff*op.v0 + 0.02*m_eff*9.80665)*r_t/(k_t*eta_dt*phi);
    A_i     = (k_t*omega0 + 2*R_m*i_m0)/(eta_v*V_bus0);   % dI_bus per A of i_m
    Aw_v    = (k_t*i_m0/(eta_v*V_bus0))*phi/r_t;          % dI_bus per (m/s)
    Hf   = opt_lag(tauf);                                 % shared meas prefilter
    Gpre = K_share * pade_tf(Td, 2) * tf(1, [taur 1]);    % share pre-path
    Dv   = pade_tf(Tdv, 2) * tf(1, [tauv 1]);             % i_cmd -> i_m
    Mm   = tf(1, [m_eff b_eff]);                          % force -> v
    Gv   = KF*Dv*Mm;                                      % i_cmd -> v (physical)
    G11  = Hf*Gpre;
    G12  = Hf*dAdI*(A_i*Dv + Aw_v*Gv);                    % i_cmd -> alpha
    G22  = K_enc*Kv*Gv;                                   % Kv: structural gain corner
    G    = [G11 G12; tf(0, 1) G22];                       % G21 = 0 (r-invariant kd)
end

function P = pade_tf(Td, n)
    [np, dp] = pade(Td, n); P = tf(np, dp);
end

function P = opt_lag(tau)
    if tau > 0, P = tf(1, [tau 1]); else, P = tf(1, 1); end
end

function v = parse_def(txt, name)
    tok = regexp(txt, ['#define\s+' name '\s+(\d+)'], 'tokens', 'once');
    v = str2double(tok{1});
end

function M = parse_arr(txt, name, rows, cols)
    % parse "static const float NAME[...] = { {..f, ..f}, ... };"
    blk = regexp(txt, [name '\[[^=]*=\s*\{(.*?)\};'], 'tokens', 'once');
    assert(~isempty(blk), 'failed to find array %s', name);
    rr = regexp(blk{1}, '\{\s*([^{}]*?)\s*\}', 'tokens');
    assert(numel(rr) == rows, '%s: expected %d rows, got %d', name, rows, numel(rr));
    M = zeros(rows, cols);
    for i = 1:rows
        v = sscanf(strrep(rr{i}{1}, 'f', ''), '%f,');
        assert(numel(v) == cols, '%s row %d: expected %d cols', name, i, cols);
        M(i, :) = v(:).';
    end
end

function s = pick(cond, a, b)
    if cond, s = a; else, s = b; end
end

function logf(fid, varargin)
    fprintf(1, varargin{:});
    fprintf(fid, varargin{:});
end
