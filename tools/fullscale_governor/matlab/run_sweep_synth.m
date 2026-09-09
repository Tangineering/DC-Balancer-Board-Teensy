%% RUN_SWEEP_SYNTH -- the student's sweep_governor_scale.m, with the UDDS demand
%  loaded from a plain .mat (variable P_dem1, 1x1370) because the original
%  simulink_pdem_output_UDDS.mat is not in the repository.  Everything from
%  section 2 down is the student's code verbatim (plots dropped); results are
%  written to OUT_JSON so the Python port can be compared number by number.
clear; clc;
addpath('C:\Life Ops\School\Thesis\DC-Balancer-Board-Teensy\references\EMS');

S0 = load(getenv('PDEM_FILE'));
P_dem1 = double(S0.P_dem1(:).');
S = load('C:\Life Ops\School\Thesis\DC-Balancer-Board-Teensy\references\EMS\TPM_fullsize.mat');
f = fieldnames(S);  TPM = S.(f{1});
outjson = getenv('OUT_JSON');
only_alpha = str2double(getenv('ONLY_ALPHA'));      % NaN -> both alphas

SOC_initial = 0.6;
Em = 720;  Q = 100;
fprintf('UDDS: P_dem range [%.1f, %.1f] kW, N = %d\n', min(P_dem1)/1e3, max(P_dem1)/1e3, numel(P_dem1));

%% 2. Fixed configuration -- everything except S_I and alpha
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
if ~isnan(only_alpha), sweep_alpha = only_alpha; end
nS = numel(sweep_SI);
nA = numel(sweep_alpha);
res = struct();

%% 3. Sweep
for ia = 1:nA
    a = sweep_alpha(ia);
    fprintf('\n===== alpha = %d =====\n', a);
    c_b = cfg;  c_b.alpha = a;  c_b.governor_enabled = false;
    fprintf('  baseline ... ');  t0 = tic;
    [~, ~, SOC_b, gb] = SDP_EnergyManagement_Governor3(P_dem1, SOC_initial, TPM, c_b);
    fprintf('%.1f s\n', toc(t0));
    cache = gb.policy_cache;
    s_eq  = gb.h2.s_eq;
    Eb_b  = -(SOC_b(end) - SOC_initial) * Em * 3600 * Q;

    res(ia).alpha       = a;
    res(ia).MH2_base    = gb.summary.M_H2_total;
    res(ia).SOC_end_base = SOC_b(end);
    res(ia).MH2_eq_base = gb.summary.M_H2_total + Eb_b*s_eq;
    res(ia).SOCrms_base = gb.summary.SOC_rms_dev;
    res(ia).starts_base = gb.summary.n_starts;
    res(ia).vi_sweeps   = NaN;

    for is = 1:nS
        SI = sweep_SI(is);
        c_g = cfg;
        c_g.alpha             = a;
        c_g.governor_enabled  = true;
        c_g.S_I               = SI;
        c_g.policy_cache      = cache;
        fprintf('  S_I = %6.1f ... ', SI);  t0 = tic;
        [~, ~, SOC_g, gg] = SDP_EnergyManagement_Governor3(P_dem1, SOC_initial, TPM, c_g);
        fprintf('%.1f s\n', toc(t0));
        Eb_g = -(SOC_g(end) - SOC_initial) * Em * 3600 * Q;

        res(ia).SI(is)          = SI;
        res(ia).MH2(is)         = gg.summary.M_H2_total;
        res(ia).SOC_end(is)     = SOC_g(end);
        res(ia).MH2_eq(is)      = gg.summary.M_H2_total + Eb_g*s_eq;
        res(ia).penalty(is)     = 100*(res(ia).MH2_eq(is) - res(ia).MH2_eq_base) / res(ia).MH2_eq_base;
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

%% 4. Tables
for ia = 1:nA
    r = res(ia);
    fprintf('\n========== SDP, UDDS, alpha = %d: governor scale sweep ==========\n', r.alpha);
    fprintf('baseline M_H2,eq = %.2f g,  SOC RMS = %.3e,  starts = %d\n\n', r.MH2_eq_base, r.SOCrms_base, r.starts_base);
    fprintf('%8s %10s %10s %9s %8s %8s %8s %8s %9s\n', 'S_I','entry kW','MH2eq [g]','penalty','SOC x','closed','latched','events','md|dPfc|');
    for is = 1:nS
        fprintf('%8.1f %10.1f %10.2f %8.2f%% %8.2f %7.1f%% %7.1f%% %8d %9.0f\n', ...
                r.SI(is), r.entry_kW(is), r.MH2_eq(is), r.penalty(is), r.SOCratio(is), ...
                100*r.closed(is), 100*r.latched(is), r.events(is), r.mean_dPfc(is));
    end
    fprintf('================================================================\n');
end

if ~isempty(outjson)
    fid = fopen(outjson, 'w');  fprintf(fid, '%s', jsonencode(res));  fclose(fid);
    fprintf('wrote %s\n', outjson);
end
