%% SWEEP_GOVERNOR_SCALE
%  How does the governor penalty depend on the current-threshold scale S_I?
%
%  S_I multiplies ONLY the Class-2 constants -- the six absolute-current
%  thresholds (min-load gate, minority floor, open-loop hysteresis, dark/live,
%  cut ceiling). The dimensionless droop band [0.15, 0.85] and the Class-3
%  rates (slew ceiling, dwell) are untouched by construction, so this sweep
%  isolates one mechanism instead of scaling the whole governor.
%
%  Why it matters: S_I = 127.8 rests on an inferred 2.0 A bench nominal
%  current, the least defensible number in the study. At S_I = 127.8 the
%  closed-loop entry threshold is 55 kW, which UDDS rarely reaches, so the
%  loop is locked out and the split is set by contactors. At S_I = 1 the
%  thresholds are milliwatt-scale, the loop is always closed, and only the
%  band and the slew limiter remain active.
%
%  If the penalty tracks S_I, the earlier "the governor is expensive when its
%  own entry threshold locks it out" reading is confirmed and the whole result
%  hinges on that one unverified constant.
%
%  Requires: SDP_EnergyManagement_Governor3.m, the UDDS cycle, TPM.

clear; close all; clc;

%% ------------------------------------------------------------------
%  1. Cycle and TPM
%  ------------------------------------------------------------------
data2 = load('simulink_pdem_output_UDDS.mat', 'out');
P_dem = data2.out.simout.Data;
Time  = data2.out.simout.Time;
wholeSeconds = 0:1:1369;
P_dem1 = interp1(Time, P_dem, wholeSeconds, 'linear');
P_dem1 = P_dem1(:).';

if ~exist('TPM', 'var')
    S = load('TPM.mat');
    f = fieldnames(S);
    TPM = S.(f{1});
end

SOC_initial = 0.6;
Em = 720;  Q = 100;

fprintf('UDDS: P_dem range [%.1f, %.1f] kW\n', min(P_dem1)/1e3, max(P_dem1)/1e3);

%% ------------------------------------------------------------------
%  2. Fixed configuration -- everything except S_I and alpha
%  ------------------------------------------------------------------
cfg = struct();
cfg.n_subticks        = 880;
cfg.P_fc_ramp_W_per_s = 50000;
cfg.h2_model          = 'convex';
cfg.h2_a0             = 0.05;
cfg.h2_P_peak_W       = 35000;
cfg.h2_eta_peak       = 0.50;
cfg.h2_start_cost_g   = 0.5;
cfg.h2_s_eq_fixed     = 1/(0.50*120000);
cfg.verbose           = false;

sweep_SI    = [1 10 25 50 100 127.8];
sweep_alpha = [200 500];

nS = numel(sweep_SI);
nA = numel(sweep_alpha);

res = struct();

%% ------------------------------------------------------------------
%  3. Sweep
%     The SDP policy does not depend on S_I, so it is computed once per
%     alpha and reused for every governor scale via cfg.policy_cache.
%     The baseline likewise does not depend on S_I -- one run per alpha.
%  ------------------------------------------------------------------
for ia = 1:nA

    a = sweep_alpha(ia);
    fprintf('\n===== alpha = %d =====\n', a);

    % ---- baseline: governor off, so S_I is irrelevant ---------------
    c_b = cfg;  c_b.alpha = a;  c_b.governor_enabled = false;
    fprintf('  baseline ... ');  t0 = tic;
    [~, ~, SOC_b, gb] = SDP_EnergyManagement_Governor3(P_dem1, SOC_initial, TPM, c_b);
    fprintf('%.1f s\n', toc(t0));

    cache = gb.policy_cache;              % reuse for every governed run
    s_eq  = gb.h2.s_eq;
    Eb_b  = -(SOC_b(end) - SOC_initial) * Em * 3600 * Q;

    res(ia).alpha       = a;
    res(ia).MH2_eq_base = gb.summary.M_H2_total + Eb_b*s_eq;
    res(ia).SOCrms_base = gb.summary.SOC_rms_dev;
    res(ia).starts_base = gb.summary.n_starts;

    % ---- governed, one run per S_I ----------------------------------
    for is = 1:nS
        SI = sweep_SI(is);
        c_g = cfg;
        c_g.alpha             = a;
        c_g.governor_enabled  = true;
        c_g.S_I               = SI;        % <-- the swept quantity
        c_g.policy_cache      = cache;     % skip value iteration

        fprintf('  S_I = %6.1f ... ', SI);  t0 = tic;
        [~, ~, SOC_g, gg] = SDP_EnergyManagement_Governor3(P_dem1, SOC_initial, TPM, c_g);
        fprintf('%.1f s\n', toc(t0));

        Eb_g = -(SOC_g(end) - SOC_initial) * Em * 3600 * Q;

        res(ia).SI(is)          = SI;
        res(ia).MH2_eq(is)      = gg.summary.M_H2_total + Eb_g*s_eq;
        res(ia).penalty(is)     = 100*(res(ia).MH2_eq(is) - res(ia).MH2_eq_base) ...
                                  / res(ia).MH2_eq_base;
        res(ia).SOCrms(is)      = gg.summary.SOC_rms_dev;
        res(ia).SOCratio(is)    = gg.summary.SOC_rms_dev / res(ia).SOCrms_base;
        res(ia).closed(is)      = gg.summary.frac_closed_loop;
        res(ia).latched(is)     = gg.summary.frac_latched;
        res(ia).events(is)      = gg.summary.n_latch_events;
        res(ia).mean_dPfc(is)   = gg.summary.mean_abs_dP_fc;
        res(ia).starts(is)      = gg.summary.n_starts;
        res(ia).sat(is)         = gg.summary.frac_saturated;
        res(ia).entry_kW(is)    = 2*gg.C.MINORITY_I_MIN_A*720/1e3;
    end
end

%% ------------------------------------------------------------------
%  4. Tables
%  ------------------------------------------------------------------
for ia = 1:nA
    r = res(ia);
    fprintf('\n========== SDP, UDDS, alpha = %d: governor scale sweep ==========\n', r.alpha);
    fprintf('baseline M_H2,eq = %.2f g,  SOC RMS = %.3e,  starts = %d\n\n', ...
            r.MH2_eq_base, r.SOCrms_base, r.starts_base);
    fprintf('%8s %10s %10s %9s %8s %8s %8s %8s %9s\n', ...
            'S_I','entry kW','MH2eq [g]','penalty','SOC x','closed','latched','events','md|dPfc|');
    for is = 1:nS
        fprintf('%8.1f %10.1f %10.2f %8.2f%% %8.2f %7.1f%% %7.1f%% %8d %9.0f\n', ...
                r.SI(is), r.entry_kW(is), r.MH2_eq(is), r.penalty(is), ...
                r.SOCratio(is), 100*r.closed(is), 100*r.latched(is), ...
                r.events(is), r.mean_dPfc(is));
    end
    fprintf('================================================================\n');
end

%% ------------------------------------------------------------------
%  5. Plots
%  ------------------------------------------------------------------
figure(1); clf
subplot(1,3,1)
for ia = 1:nA
    semilogx(res(ia).SI, res(ia).penalty, 'o-', 'LineWidth', 1.4); hold on
end
yline(0,'k:'); xlabel('S_I'); ylabel('governor penalty (%)'); grid on
legend(arrayfun(@(r) sprintf('\\alpha = %d', r.alpha), res, 'uni', 0), 'Location','best')
title('Fuel penalty vs current scale')

subplot(1,3,2)
for ia = 1:nA
    semilogx(res(ia).SI, 100*res(ia).closed, 'o-', 'LineWidth', 1.4); hold on
    semilogx(res(ia).SI, 100*res(ia).latched, 's--', 'LineWidth', 1.2);
end
xlabel('S_I'); ylabel('% of cycle'); grid on
legend('closed loop','latched','Location','best')
title('Governor operating regime')

subplot(1,3,3)
for ia = 1:nA
    semilogx(res(ia).SI, res(ia).SOCratio, 'o-', 'LineWidth', 1.4); hold on
end
yline(1,'k:'); xlabel('S_I'); ylabel('SOC RMS ratio (gov / base)'); grid on
title('SOC regulation')

figure(2); clf
for ia = 1:nA
    plot(100*res(ia).closed, res(ia).penalty, 'o', 'MarkerSize', 9, ...
         'MarkerFaceColor','auto'); hold on
    for is = 1:nS
        text(100*res(ia).closed(is), res(ia).penalty(is), ...
             sprintf('  %.0f', res(ia).SI(is)), 'FontSize', 8);
    end
end
yline(0,'k:'); grid on
xlabel('closed-loop fraction (%)'); ylabel('governor penalty (%)')
title('Penalty vs lockout (labels are S_I)')
legend(arrayfun(@(r) sprintf('\\alpha = %d', r.alpha), res, 'uni', 0), 'Location','best')
