%% MAIN_SDP_GOVERNOR
%  Driver for SDP_EnergyManagement_Governor.
%
%  Runs the SAME SDP policy twice on the UDDS demand trace:
%     (a) ungoverned baseline  -- the request is honoured exactly
%     (b) governed             -- the power-share governor sits between the
%                                 SDP request and the hardware
%  so every difference in the plots is attributable to the governor and not
%  to a different policy.
%
%  Requires on the path:
%     SDP_EnergyManagement_Governor.m
%     simulink_pdem_output_UDDS.mat
%     TPM (transition probability matrix) in the workspace or a .mat file

clear; close all; clc;

%% ------------------------------------------------------------------
%  1. Load the drive cycle and the TPM
%  ------------------------------------------------------------------
data2 = load('simulink_pdem_output_UDDS.mat', 'out');
P_dem = data2.out.simout.Data;      % W
Time  = data2.out.simout.Time;

wholeSeconds = 0:1:1369;            % N = 1370, Ts = 1 s
P_dem1 = interp1(Time, P_dem, wholeSeconds, 'linear');
P_dem1 = P_dem1(:).';               % force row

if ~exist('TPM', 'var')
    S = load('TPM.mat');
    f = fieldnames(S);
    TPM = S.(f{1});
end

SOC_initial = 0.6;

%% ------------------------------------------------------------------
%  2. Configuration
%     The two numbers below are the ones that drive the governed result.
%     Both are placeholders until the bench / stack specs are in hand.
%  ------------------------------------------------------------------
cfg = struct();
cfg.I_bench_nominal_A = 2.0;        % anchor for the current scale S_I
cfg.P_fc_ramp_W_per_s = 50000;      % fuel-cell stack ramp limit
cfg.n_subticks        = 880;        % governor ticks per SDP second
cfg.verbose           = true;

% Hydrogen map. 'convex' gives an interior optimum and makes dSOC-corrected
% fuel a real metric; 'constant' reverts to W_H2 = P_fc/(0.5*120000).
% Fit a0 / P_peak / eta_peak to your polarization curve.
cfg.h2_model    = 'convex';
cfg.h2_a0       = 0.05;             % g/s parasitic at idle
cfg.h2_P_peak_W = 35000;            % W, peak system efficiency
cfg.h2_eta_peak = 0.50;

% Stack start cost, in grams of H2 per start. Prices thermal cycling and
% durability, not literal fuel. Without it the DP pulses the stack at 1 Hz.
% Set to 0 to recover the previous unconstrained policy.
cfg.h2_start_cost_g = 0.5;

% Charge-sustaining equivalence factor, g/J. Leave empty for the marginal
% rate at eta_peak. MUST be identical across every run being compared.
cfg.h2_s_eq_fixed = [];

%% ------------------------------------------------------------------
%  3. Run: ungoverned baseline, then governed
%  ------------------------------------------------------------------
fprintf('=== Baseline (governor disabled) ===\n');
cfg_base = cfg;  cfg_base.governor_enabled = false;
tic
[P_bat_base, P_fc_base, SOC_base, gov_base] = ...
    SDP_EnergyManagement_Governor2(P_dem1, SOC_initial, TPM, cfg_base);
t_base = toc;
fprintf('baseline run: %.1f s\n\n', t_base);

fprintf('=== Governed ===\n');
cfg_gov = cfg;  cfg_gov.governor_enabled = true;
tic
[P_bat_gov, P_fc_gov, SOC_gov, gov] = ...
    SDP_EnergyManagement_Governor2(P_dem1, SOC_initial, TPM, cfg_gov);
t_gov = toc;
fprintf('governed run: %.1f s\n\n', t_gov);

%% ------------------------------------------------------------------
%  4. Hydrogen
%  ------------------------------------------------------------------
eta_fc   = 0.5;          % legacy constant, kept only for reference
Q_LHV_H2 = 120000;
Ts       = 1;

% Both runs already computed hydrogen through the map configured in cfg.
% Reuse those rather than re-applying a constant gain here, so the driver
% and the function can never disagree about the map.
W_H2_base = gov_base.W_H2_applied;                  % g/s
W_H2_gov  = gov.W_H2_applied;

M_H2_base = gov_base.M_H2_applied;                  % g
M_H2_gov  = gov.M_H2_applied;

k = 1:length(P_dem1);

%% ------------------------------------------------------------------
%  Figure 1 -- power split, both runs
%  ------------------------------------------------------------------
figure(1); clf
subplot(2,1,1)
plot(k, P_fc_base, 'LineWidth', 1); hold on
plot(k, P_bat_base, 'LineWidth', 1);
plot(k, P_dem1, 'k:', 'LineWidth', 0.8);
legend('P_{fc}', 'P_{bat}', 'P_{dem}', 'Location', 'best')
xlabel('Time (s)'); ylabel('Power (W)')
title('Ungoverned baseline'); grid on

subplot(2,1,2)
plot(k, P_fc_gov, 'LineWidth', 1); hold on
plot(k, P_bat_gov, 'LineWidth', 1);
plot(k, P_dem1, 'k:', 'LineWidth', 0.8);
legend('P_{fc}', 'P_{bat}', 'P_{dem}', 'Location', 'best')
xlabel('Time (s)'); ylabel('Power (W)')
title('With power-share governor'); grid on

%% ------------------------------------------------------------------
%  Figure 2 -- SOC
%  ------------------------------------------------------------------
figure(2); clf
plot(0:length(SOC_base)-1, SOC_base, 'LineWidth', 1.2); hold on
plot(0:length(SOC_gov)-1,  SOC_gov,  'LineWidth', 1.2);
yline(0.6, 'k--');
legend('baseline', 'governed', 'SOC_0', 'Location', 'best')
xlabel('Time (s)'); ylabel('SOC')
title('State of charge'); grid on

%% ------------------------------------------------------------------
%  Figure 3 -- instantaneous hydrogen rate
%  ------------------------------------------------------------------
figure(3); clf
plot(k, W_H2_base, 'LineWidth', 1); hold on
plot(k, W_H2_gov,  'LineWidth', 1);
legend('baseline', 'governed', 'Location', 'best')
xlabel('Time (s)'); ylabel('H_2 rate (g/s)')
title('Hydrogen consumption rate'); grid on

%% ------------------------------------------------------------------
%  Figure 4 -- cumulative hydrogen mass
%  ------------------------------------------------------------------
figure(4); clf
plot(k, M_H2_base, 'LineWidth', 1.2); hold on
plot(k, M_H2_gov,  'LineWidth', 1.2);
legend('baseline', 'governed', 'Location', 'best')
xlabel('Time (s)'); ylabel('M_{H2} (g)')
title('Cumulative hydrogen mass'); grid on

%% ------------------------------------------------------------------
%  Figure 5 -- what the governor did to the request
%  ------------------------------------------------------------------
figure(5); clf
subplot(3,1,1)
plot(k, gov.P_fc_cmd, 'LineWidth', 1); hold on
plot(k, gov.P_fc_applied, 'LineWidth', 1);
legend('requested', 'applied', 'Location', 'best')
ylabel('P_{fc} (W)'); title('Fuel-cell request vs delivery'); grid on

subplot(3,1,2)
plot(k, gov.sp_cmd, 'LineWidth', 1); hold on
plot(k, gov.r_applied, 'LineWidth', 1);
yline(0.15, 'k--'); yline(0.85, 'k--');
legend('sp (commanded share)', 'r (applied ratio)', 'Location', 'best')
ylabel('share ratio'); ylim([0 1]); grid on

subplot(3,1,3)
area(k, double(gov.latchFC | gov.latchBT), 'FaceAlpha', 0.4, 'EdgeColor', 'none'); hold on
area(k, double(gov.isoFC  | gov.isoBT),   'FaceAlpha', 0.4, 'EdgeColor', 'none');
plot(k, double(gov.closedLoop), 'LineWidth', 1);
legend('setpoint latch', 'iso claim', 'closed loop', 'Location', 'best')
xlabel('Time (s)'); ylabel('flag'); ylim([-0.1 1.2]); grid on

%% ------------------------------------------------------------------
%  Figure 6 -- governor override magnitude
%  ------------------------------------------------------------------
figure(6); clf
subplot(2,1,1)
plot(k, gov.dP_fc, 'LineWidth', 1);
xlabel('Time (s)'); ylabel('\DeltaP_{fc} (W)')
title('Applied minus requested fuel-cell power'); grid on

subplot(2,1,2)
plot(k, SOC_gov(2:end) - SOC_base(2:end), 'LineWidth', 1);
xlabel('Time (s)'); ylabel('\DeltaSOC')
title('SOC divergence introduced by the governor'); grid on

%% ------------------------------------------------------------------
%  5. Comparison table
%  ------------------------------------------------------------------
sb = gov_base.summary;
sg = gov.summary;

fprintf('\n================ Baseline vs governed ==================\n');
fprintf('%-28s %14s %14s\n', '', 'baseline', 'governed');
fprintf('%-28s %14.4f %14.4f\n', 'SOC final',            sb.SOC_final,      sg.SOC_final);
fprintf('%-28s %14.3e %14.3e\n', 'SOC RMS deviation',    sb.SOC_rms_dev,    sg.SOC_rms_dev);
fprintf('%-28s %14.2f %14.2f\n', 'M_H2 total [g]',       sb.M_H2_total,     sg.M_H2_total);
fprintf('%-28s %14s %14.2f\n',   'M_H2 penalty [%]',     '--',              sg.M_H2_penalty_pct);
fprintf('%-28s %14s %14.1f\n',   'closed loop [%]',      '--',              100*sg.frac_closed_loop);
fprintf('%-28s %14s %14.1f\n',   'channel latched [%]',  '--',              100*sg.frac_latched);
fprintf('%-28s %14s %14.1f\n',   'channel isolated [%]', '--',              100*sg.frac_isolated);
fprintf('%-28s %14s %14.1f\n',   'saturated [%]',        '--',              100*sg.frac_saturated);
fprintf('%-28s %14s %14.1f\n',   'mean |dP_fc| [W]',     '--',              sg.mean_abs_dP_fc);
fprintf('========================================================\n');

% Charge-sustaining check: the two runs end at different SOC, so the raw
% M_H2 comparison is not like-for-like.  Equivalent H2 at equal dSOC:
dSOC_base = SOC_base(end) - SOC_initial;
dSOC_gov  = SOC_gov(end)  - SOC_initial;
Em = 720; Q = 100;
E_bat_base = -dSOC_base * Em * 3600 * Q;      % J drawn from the battery
E_bat_gov  = -dSOC_gov  * Em * 3600 * Q;

% Equivalence factor: the MARGINAL hydrogen rate dW/dP_fc at the run's own
% mean operating point, not the constant 1/(eta*LHV).  With the convex map
% the two runs generally sit at different mean P_fc, so they convert battery
% energy at different rates -- which is exactly why this comparison stops
% being an identity and starts carrying information.
s_eq = gov.h2.s_eq;              % same factor for BOTH runs, by construction

M_H2_eq_base = sb.M_H2_total + E_bat_base * s_eq;
M_H2_eq_gov  = sg.M_H2_total + E_bat_gov  * s_eq;

fprintf('\nCharge-sustaining correction (equivalent H2 at equal dSOC):\n');
fprintf('  H2 map        : %s   a = [%.4g %.4g %.4g]\n', ...
        gov.h2.model, gov.h2.a(1), gov.h2.a(2), gov.h2.a(3));
fprintf('  dSOC          : %+.5f (baseline)  %+.5f (governed)\n', dSOC_base, dSOC_gov);
fprintf('  mean P_fc [kW]: %.1f (baseline)  %.1f (governed)\n', ...
        gov_base.h2.P_fc_bar/1e3, gov.h2.P_fc_bar/1e3);
fprintf('  eta at mean   : %.3f (baseline)  %.3f (governed)\n', ...
        gov_base.h2.eta_bar, gov.h2.eta_bar);
fprintf('  s_eq [g/J]    : %.4e (fixed, both runs)\n', s_eq);
fprintf('  per-run marginal (diagnostic only): %.4e / %.4e\n', ...
        gov_base.h2.s_eq_marginal, gov.h2.s_eq_marginal);
fprintf('  stack starts  : %d (baseline)  %d (governed)\n', ...
        sb.n_starts, sg.n_starts);
fprintf('  M_H2,eq [g]   : %.2f (baseline)  %.2f (governed)  -> %+.2f %%\n', ...
        M_H2_eq_base, M_H2_eq_gov, ...
        100*(M_H2_eq_gov - M_H2_eq_base)/max(M_H2_eq_base, eps));


%% ==================================================================
%  6. Hydrogen from the fuel-cell dynamic model  M_H2 / P_fc
%  ==================================================================
%  The static map used above, W_H2 = P_fc/(eta_fc*Q_LHV_H2), is a pure
%  gain.  Gfc below is the dynamic model of the same path.  Note the
%  trailing zero in the denominator: Gfc already contains the integrator,
%  so its OUTPUT IS CUMULATIVE MASS in grams, not a rate.  The rate comes
%  from s*Gfc.

num = [5.51 2.248e6 2.488e9 6.473e11];
den = [1044 1.239e10 2.034e13 8.21e15 3.67e16 0];
Gfc = tf(num, den);                 % M_H2 / P_fc   [g / W]

Gfc_rate = tf(num, den(1:end-1));   % same TF with the integrator removed
                                    % -> W_H2 / P_fc   [(g/s) / W]

% --- consistency check against the static map ----------------------
k_dyn = dcgain(Gfc_rate);           % g/s per W
k_sta = 1/(eta_fc*Q_LHV_H2);        % g/s per W
fprintf('\n--- Gfc vs static map -----------------------------------\n');
fprintf('  DC gain of s*Gfc : %.4e g/s/W\n', k_dyn);
fprintf('  static 1/(eta*LHV): %.4e g/s/W   (%+.2f %%)\n', ...
        k_sta, 100*(k_dyn - k_sta)/k_sta);
fprintf('  slowest non-integrator pole: %.4g rad/s (tau = %.3g s)\n', ...
        min(abs(pole(Gfc_rate))), 1/min(abs(pole(Gfc_rate))));
fprintf('----------------------------------------------------------\n');

% --- simulate ------------------------------------------------------
%  Gfc is LTI: it has ONE gain, so pushing P_fc through it reimposes the
%  linear identity the convex map exists to break. Correct structure is
%  Hammerstein -- static nonlinearity first, then unit-DC-gain dynamics:
%
%      P_fc --> W_H2(P_fc) --> Gfc_norm --> W_H2 dynamic --> integrate
%
%  Gfc_norm keeps the 0.22 s pole and the phase, and contributes no gain,
%  so the steady-state fuel comes entirely from the convex map.

Gfc_norm = Gfc_rate / dcgain(Gfc_rate);     % unit DC gain, dynamics only

dt_fine = 0.01;                             % s
t_fine  = (0 : dt_fine : (length(P_dem1)-1)).';
t_1Hz   = (0 : length(P_dem1)-1).';

% ZOH the 1 Hz static hydrogen RATE, then filter it
u_base_fine = interp1(t_1Hz, W_H2_base(:), t_fine, 'previous');
u_gov_fine  = interp1(t_1Hz, W_H2_gov(:),  t_fine, 'previous');

W_H2_tf_base_fine = lsim(Gfc_norm, u_base_fine, t_fine);
W_H2_tf_gov_fine  = lsim(Gfc_norm, u_gov_fine,  t_fine);

M_H2_tf_base_fine = cumsum(W_H2_tf_base_fine) * dt_fine;
M_H2_tf_gov_fine  = cumsum(W_H2_tf_gov_fine)  * dt_fine;

% decimate back to the 1 s grid for plotting alongside the static results
M_H2_tf_base = interp1(t_fine, M_H2_tf_base_fine, t_1Hz);
M_H2_tf_gov  = interp1(t_fine, M_H2_tf_gov_fine,  t_1Hz);
W_H2_tf_base = interp1(t_fine, W_H2_tf_base_fine, t_1Hz);
W_H2_tf_gov  = interp1(t_fine, W_H2_tf_gov_fine,  t_1Hz);

%% ------------------------------------------------------------------
%  Figure 7 -- dynamic vs static hydrogen model
%  ------------------------------------------------------------------
figure(7); clf
subplot(2,1,1)
plot(k, W_H2_base, '--', 'LineWidth', 1); hold on
plot(k, W_H2_tf_base, 'LineWidth', 1);
plot(k, W_H2_gov, '--', 'LineWidth', 1);
plot(k, W_H2_tf_gov, 'LineWidth', 1);
legend('baseline, static', 'baseline, G_{fc}', ...
       'governed, static', 'governed, G_{fc}', 'Location', 'best')
ylabel('H_2 rate (g/s)'); title('Hydrogen rate: static map vs G_{fc}'); grid on

subplot(2,1,2)
plot(k, M_H2_base, '--', 'LineWidth', 1); hold on
plot(k, M_H2_tf_base, 'LineWidth', 1.2);
plot(k, M_H2_gov, '--', 'LineWidth', 1);
plot(k, M_H2_tf_gov, 'LineWidth', 1.2);
legend('baseline, static', 'baseline, G_{fc}', ...
       'governed, static', 'governed, G_{fc}', 'Location', 'best')
xlabel('Time (s)'); ylabel('M_{H2} (g)')
title('Cumulative hydrogen mass'); grid on

%% ------------------------------------------------------------------
%  7. Hydrogen totals from Gfc, with the charge-sustaining correction
%  ------------------------------------------------------------------
MH2_tf_base = M_H2_tf_base(end);
MH2_tf_gov  = M_H2_tf_gov(end);

% Battery energy converted to equivalent hydrogen at the SAME gain the
% dynamic model settles to, so the two terms are consistent.
MH2_eq_tf_base = MH2_tf_base + E_bat_base * s_eq;
MH2_eq_tf_gov  = MH2_tf_gov  + E_bat_gov  * s_eq;

fprintf('\n=========== Hydrogen from G_fc (M_H2/P_fc) =============\n');
fprintf('%-30s %14s %14s\n', '', 'baseline', 'governed');
fprintf('%-30s %14.2f %14.2f\n', 'M_H2, static map [g]', sb.M_H2_total,  sg.M_H2_total);
fprintf('%-30s %14.2f %14.2f\n', 'M_H2, G_fc [g]',       MH2_tf_base,    MH2_tf_gov);
fprintf('%-30s %14.2f %14.2f\n', 'dSOC-corrected, G_fc [g]', MH2_eq_tf_base, MH2_eq_tf_gov);
fprintf('%-30s %14s %14.2f\n',   'governor penalty [%]', '--', ...
        100*(MH2_eq_tf_gov - MH2_eq_tf_base)/max(MH2_eq_tf_base, eps));
fprintf('%-30s %14.2f %14.2f\n', 'G_fc vs static [%]', ...
        100*(MH2_tf_base - sb.M_H2_total)/max(sb.M_H2_total, eps), ...
        100*(MH2_tf_gov  - sg.M_H2_total)/max(sg.M_H2_total, eps));
fprintf('========================================================\n');


%% ==================================================================
%  8. ALPHA SWEEP  (optional -- set RUN_ALPHA_SWEEP = false to skip)
%  ==================================================================
%  Self-contained. Uses only P_dem1, TPM, SOC_initial and cfg from above,
%  writes only sweep_* variables, and touches nothing the sections above
%  produced. Comment out the whole block, or flip the flag, and the rest
%  of the script still runs unchanged.
%
%  Why sweep alpha: at alpha = 500 the SOC penalty (up to 25) outweighs the
%  fuel term (up to 1.77) by ~14x, so the SDP pins SOC to 0.6 and commands
%  P_fc ~ P_dem. That puts sp ~ 1.0, above R_MAX, so the governor latches the
%  battery off the bus instead of arbitrating a split. Lowering alpha lets
%  the battery swing, which is the only regime where the share loop has an
%  opinion.
%
%  NOTE: total hydrogen corrected for dSOC is INVARIANT here -- with a
%  constant eta_fc, M_H2 + k*E_bat = k*E_dem is an identity, so it will not
%  move with alpha or with the governor. The columns that carry information
%  are SOC RMS, the latch fraction, the contactor event count, and dP_fc.

RUN_ALPHA_SWEEP = true;

if RUN_ALPHA_SWEEP

    sweep_alpha = [200 500 1000 2000 5000];

    % Each governed run is length(P_dem1)*n_subticks governor ticks. Drop
    % n_subticks for a faster scouting pass, then re-run the interesting
    % alpha at full rate.
    sweep_cfg = cfg;
    sweep_cfg.verbose    = false;
    sweep_cfg.n_subticks = 220;      % 4x faster than 880; raise to confirm

    nA = numel(sweep_alpha);
    sweep_res = struct('alpha', num2cell(sweep_alpha));

    fprintf('\n=== alpha sweep (%d points) ===\n', nA);
    for ia = 1:nA

        a = sweep_alpha(ia);
        fprintf('  alpha = %6.1f ... ', a);
        t0 = tic;

        c_b = sweep_cfg;  c_b.alpha = a;  c_b.governor_enabled = false;
        c_g = sweep_cfg;  c_g.alpha = a;  c_g.governor_enabled = true;

        [~, Pfc_b, SOC_b, gb] = SDP_EnergyManagement_Governor2(P_dem1, SOC_initial, TPM, c_b);
        [~, Pfc_g, SOC_g, gg] = SDP_EnergyManagement_Governor2(P_dem1, SOC_initial, TPM, c_g);

        % contactor open events per cycle (rising edges of either latch)
        latch_b = gb.latchFC | gb.latchBT;
        latch_g = gg.latchFC | gg.latchBT;

        % dSOC-corrected hydrogen, same convention as section 5
        Eb_b = -(SOC_b(end) - SOC_initial) * 720 * 3600 * 100;
        Eb_g = -(SOC_g(end) - SOC_initial) * 720 * 3600 * 100;

        sweep_res(ia).SOC_rms_base   = gb.summary.SOC_rms_dev;
        sweep_res(ia).SOC_rms_gov    = gg.summary.SOC_rms_dev;
        sweep_res(ia).MH2_base       = gb.summary.M_H2_total;
        sweep_res(ia).MH2_gov        = gg.summary.M_H2_total;
        s_eq_sw = gg.h2.s_eq;        % fixed powertrain constant, same both runs
        sweep_res(ia).MH2_eq_base    = gb.summary.M_H2_total + Eb_b*s_eq_sw;
        sweep_res(ia).MH2_eq_gov     = gg.summary.M_H2_total + Eb_g*s_eq_sw;
        sweep_res(ia).starts_base    = gb.summary.n_starts;
        sweep_res(ia).starts_gov     = gg.summary.n_starts;
        sweep_res(ia).eta_bar_base   = gb.h2.eta_bar;
        sweep_res(ia).eta_bar_gov    = gg.h2.eta_bar;
        sweep_res(ia).duty_on_gov    = gg.h2.duty_on;
        sweep_res(ia).frac_closed    = gg.summary.frac_closed_loop;
        sweep_res(ia).frac_latched   = gg.summary.frac_latched;
        sweep_res(ia).frac_sat       = gg.summary.frac_saturated;
        sweep_res(ia).mean_dPfc      = gg.summary.mean_abs_dP_fc;
        sweep_res(ia).max_dPfc       = max(abs(gg.dP_fc));
        sweep_res(ia).n_latch_events = sum(diff([false latch_g]) == 1);
        sweep_res(ia).sp_in_band     = mean(gg.sp_cmd >= 0.15 & gg.sp_cmd <= 0.85);
        sweep_res(ia).Ibat_rms_base  = sqrt(mean(((P_dem1 - Pfc_b)/720).^2));
        sweep_res(ia).Ibat_rms_gov   = sqrt(mean(((P_dem1 - Pfc_g)/720).^2));

        fprintf('%.1f s\n', toc(t0));
    end

    % ---- table ----
    fprintf('\n============================ alpha sweep ============================\n');
    fprintf('%7s %10s %10s %9s %9s %9s %8s %10s\n', ...
            'alpha', 'SOCrms_b', 'SOCrms_g', 'sp inbnd', 'latched', 'closed', 'events', 'md|dPfc|');
    for ia = 1:nA
        r = sweep_res(ia);
        fprintf('%7.1f %10.2e %10.2e %8.1f%% %8.1f%% %8.1f%% %8d %10.0f\n', ...
                r.alpha, r.SOC_rms_base, r.SOC_rms_gov, ...
                100*r.sp_in_band, 100*r.frac_latched, 100*r.frac_closed, ...
                r.n_latch_events, r.mean_dPfc);
    end
    fprintf('---------------------------------------------------------------------\n');
    fprintf('%7s %12s %12s %12s %12s\n', 'alpha', 'MH2_b [g]', 'MH2_g [g]', 'MH2eq_b', 'MH2eq_g');
    for ia = 1:nA
        r = sweep_res(ia);
        fprintf('%7.1f %12.2f %12.2f %12.2f %12.2f\n', ...
                r.alpha, r.MH2_base, r.MH2_gov, r.MH2_eq_base, r.MH2_eq_gov);
    end
    fprintf('=====================================================================\n');
    if strcmpi(gov.h2.model, 'constant')
        fprintf('(MH2eq flat by construction: constant eta_fc makes it an identity)\n');
    else
        fprintf('(convex map: MH2eq is now a real metric and should vary)\n');
        fprintf('%7s %10s %10s %10s %9s %9s\n', ...
                'alpha', 'eta_b', 'eta_g', 'stackOn_g', 'start_b', 'start_g');
        for ia = 1:nA
            r = sweep_res(ia);
            fprintf('%7.1f %10.3f %10.3f %9.1f%% %9d %9d\n', ...
                    r.alpha, r.eta_bar_base, r.eta_bar_gov, 100*r.duty_on_gov, ...
                    r.starts_base, r.starts_gov);
        end
    end

    % ---- plots ----
    av = [sweep_res.alpha];

    figure(8); clf
    subplot(2,2,1)
    semilogx(av, [sweep_res.SOC_rms_base], 'o-', 'LineWidth', 1.2); hold on
    semilogx(av, [sweep_res.SOC_rms_gov],  's-', 'LineWidth', 1.2);
    legend('baseline', 'governed', 'Location', 'best')
    xlabel('\alpha'); ylabel('SOC RMS deviation'); grid on
    title('SOC regulation tightness')

    subplot(2,2,2)
    semilogx(av, 100*[sweep_res.sp_in_band],   'o-', 'LineWidth', 1.2); hold on
    semilogx(av, 100*[sweep_res.frac_latched], 's-', 'LineWidth', 1.2);
    semilogx(av, 100*[sweep_res.frac_closed],  '^-', 'LineWidth', 1.2);
    legend('sp in [0.15,0.85]', 'latched', 'closed loop', 'Location', 'best')
    xlabel('\alpha'); ylabel('% of cycle'); grid on
    title('Governor operating regime')

    subplot(2,2,3)
    semilogx(av, [sweep_res.n_latch_events], 'o-', 'LineWidth', 1.2);
    xlabel('\alpha'); ylabel('contactor open events / cycle'); grid on
    title('Bus-switch duty')

    subplot(2,2,4)
    semilogx(av, [sweep_res.mean_dPfc], 'o-', 'LineWidth', 1.2); hold on
    semilogx(av, [sweep_res.max_dPfc],  's-', 'LineWidth', 1.2);
    legend('mean |\DeltaP_{fc}|', 'max |\DeltaP_{fc}|', 'Location', 'best')
    xlabel('\alpha'); ylabel('W'); grid on
    title('Governor override magnitude')

    figure(9); clf
    yyaxis left
    semilogx(av, [sweep_res.MH2_base], 'o-', 'LineWidth', 1.2); hold on
    semilogx(av, [sweep_res.MH2_gov],  's-', 'LineWidth', 1.2);
    ylabel('M_{H2} raw (g)')
    yyaxis right
    semilogx(av, [sweep_res.MH2_eq_base], 'd--', 'LineWidth', 1.2); hold on
    semilogx(av, [sweep_res.MH2_eq_gov],  'v--', 'LineWidth', 1.2);
    ylabel('M_{H2} dSOC-corrected (g)')
    xlabel('\alpha'); grid on
    legend('raw base', 'raw gov', 'corrected base', 'corrected gov', 'Location', 'best')
    title('Hydrogen vs \alpha (corrected curves are flat by construction)')

end