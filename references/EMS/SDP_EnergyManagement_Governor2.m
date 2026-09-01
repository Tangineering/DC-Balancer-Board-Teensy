function [P_batt_applied, P_fc_applied, SOC_out, gov] = SDP_EnergyManagement_Governor(P_dem_array, SOC_initial, TPM, cfg)
% SDP_ENERGYMANAGEMENT_GOVERNOR
%   Stochastic dynamic programming energy management for the full-scale FCHEV,
%   with the low-level power-share governor in the forward simulation loop.
%
%   The SDP policy is computed exactly as before (it is unaware of the
%   governor).  The forward simulation then treats the SDP output P_fc as a
%   *request*: it is converted to a share setpoint sp = |I_fc|/(|I_fc|+|I_bat|),
%   handed to the governor, ticked at the governor rate for one SDP sample, and
%   the ratio the governor actually applies is converted back to power.  SOC is
%   propagated from the ACHIEVED battery power, so the SDP re-optimizes each
%   step from the state the governor actually put the vehicle in.
%
%   [P_batt, P_fc, SOC] = SDP_EnergyManagement_Governor(P_dem, SOC0, TPM)
%   [...]                = SDP_EnergyManagement_Governor(P_dem, SOC0, TPM, cfg)
%
%   Set cfg.governor_enabled = false to reproduce the ungoverned baseline from
%   the identical policy.
%
% ------------------------------------------------------------------------
% GOVERNOR SCALING -- EVERYTHING HERE IS FULL SCALE
% ------------------------------------------------------------------------
% The governor spec is written for the scaled testbed (~16 V bus, currents of
% 0.075-0.5 A).  P_dem, the TPM, SOC and M_H2 are full-scale physical
% quantities and are NOT scaled down.  The governor constants are scaled up
% instead, in three classes that transfer differently:
%
%   Class 1 -- dimensionless.  R_MIN/R_MAX, CUTOFF_HYST, SP_CHANGE_EPS,
%       filter ALPHA.  Carried across unchanged.
%
%   Class 2 -- currents.  I_TOT_MIN, MINORITY_I_MIN, OL_HYST, HANDOFF_MIN,
%       HANDOFF_LIVE, CUT_MAX_HANDOFF.  Multiplied by cfg.S_I.
%       The anchor for S_I: the bench governor clip lo = 0.30/I_tot equals the
%       band edge 0.15 exactly at I_tot = 2.0 A, so 2.0 A is taken as the
%       bench nominal total current.  S_I = I_tot_nominal_full / 2.0.
%       >>> REPLACE 2.0 A WITH THE BENCH'S ACTUAL RATED CHANNEL CURRENT WHEN
%       >>> YOU HAVE IT.  Everything in Class 2 rides on that number.
%
%   Class 3 -- rates and times.  NOT scaled.  DROOP_RATIO_SLEW_PER_TICK is
%       re-derived from the fuel-cell stack ramp limit:
%           slew_per_tick = (P_fc_ramp_W_per_s / P_tot_nominal_W) * TICK_S
%       At full scale this is far SLOWER than the bench number, so the slew
%       limiter becomes the binding constraint on the loop rather than a
%       handoff nicety.  The dwell allowance is a physical duration (~200 ms
%       of diode pickup) converted to ticks, not the bench count of 175.
%       >>> cfg.P_fc_ramp_W_per_s IS A PLACEHOLDER.  SET IT FROM THE STACK
%       >>> SPEC.  It and S_I are the two numbers that drive the results.
%
% RATIO -> POWER INVERSION.  r = |I_fc| / (|I_fc| + |I_bat|) is NOT monotone
% in P_fc when P_dem > 0: the branch with the battery discharging and the
% branch with it charging can give the same r.  This code keeps the branch the
% SDP command sat on for the duration of that sample.  For P_dem < 0 the map
% is monotone and bounded above by 0.5, so a BT cut can never fire during
% regen, and the R_MIN = 0.15 band edge forces P_fc ~ 0.21*|P_dem| whenever
% the loop is closed.
%
% Governor spec: "The Power-Share Governor", Sections 2-8 and 13.
% ------------------------------------------------------------------------

if nargin < 4 || isempty(cfg), cfg = struct(); end
cfg = fill_defaults(cfg);

% ========================================================================
% 1. VEHICLE / SDP PARAMETERS
% ========================================================================
N          = length(P_dem_array);
SOC_grid   = linspace(cfg.SOC_min, cfg.SOC_max, cfg.n_SOC);
P_fc_max   = 106000;        % W
P_batt_max =  78000;        % W   (battery discharging)
P_batt_min = -78000;        % W   (battery charging)
Q          = 100;           % Ah
Em         = 720;           % V   battery OCV
alpha      = cfg.alpha;     % SOC deviation weight
gamma      = cfg.gamma;     % discount factor
Q_LHV_H2   = 120000;        % J/g
eta_fc     = 0.5;           % legacy constant, used only by h2_model='constant'

% Hydrogen rate map, W_H2(P_fc) [g/s].  See h2_coefficients() and the
% header note.  h2.a = [a0 a1 a2], h2.shutdown = true if the stack burns
% nothing at P_fc = 0.
h2 = h2_coefficients(cfg, Q_LHV_H2, eta_fc);
Ts         = cfg.Ts;        % s, SDP sample time
SOC_ref    = 0.6;

% Coulomb counting coefficient.  1/(Em*3600*Q) = 3.858e-9, i.e. |G_bat(s)|.
k_soc = 1 / (Em * 3600 * Q);

Pdemand_bins = linspace(-50000, 60000, size(TPM, 1));
nPd  = length(Pdemand_bins);
nSOC = length(SOC_grid);
u_grid = linspace(0, P_fc_max, cfg.n_u);
nU     = length(u_grid);

BIG = 1e6;   % finite penalty for a state with no feasible action.
             % NOTE: the original code left Inf here, which propagated through
             % the TPM expectation and made the convergence test NaN, so the
             % loop always ran all max_iterations without ever breaking.

% ========================================================================
% 2. VALUE ITERATION
% ========================================================================
% The state is augmented with a binary "stack was on last step" flag so that
% a start cost can be charged.  Without that flag the DP cannot tell a start
% from continued operation, and the optimal policy pulses the stack on and
% off at 1 Hz -- which no real stack does, and which is what made the
% governor look expensive: it was cleaning up a command the supervisor
% should never have issued.
%
% Index 3 of J: 1 = stack was OFF last step, 2 = stack was ON.
c_start = cfg.h2_start_cost_g;      % g of hydrogen charged per cold start

J     = zeros(nSOC, nPd, 2);
J_new = zeros(nSOC, nPd, 2);

for iteration = 1:cfg.max_iterations

    % Expectation over the next demand bin, per next-stack-state slice.
    % J_exp(s,pd,m) = sum_next TPM(pd,next) * J(s,next,m).
    J_exp = zeros(nSOC, nPd, 2);
    J_exp(:,:,1) = J(:,:,1) * TPM.';
    J_exp(:,:,2) = J(:,:,2) * TPM.';

    for i = 1:nSOC
        SOC_current = SOC_grid(i);
        for pd_idx = 1:nPd
            P_dem = Pdemand_bins(pd_idx);

            for onPrev = 0:1
                min_cost = BIG;

                for ui = 1:nU
                    P_fc_temp   = u_grid(ui);
                    P_batt_temp = P_dem - P_fc_temp;

                    if P_batt_temp > P_batt_max || P_batt_temp < P_batt_min
                        continue
                    end

                    SOC_next = SOC_current - P_batt_temp * Ts * k_soc;
                    if SOC_next < SOC_grid(1) || SOC_next > SOC_grid(end)
                        continue
                    end

                    onNext      = (P_fc_temp > 0);
                    W_H2        = h2_rate(P_fc_temp, h2) * Ts;            % g
                    SOC_penalty = alpha * abs(SOC_next - SOC_ref);
                    start_pen   = c_start * (onNext && ~onPrev);
                    stage_cost  = W_H2 + SOC_penalty + start_pen;

                    m = onNext + 1;
                    if cfg.use_interp
                        future_cost = interp1(SOC_grid, J_exp(:, pd_idx, m), SOC_next, 'linear');
                    else
                        [~, ns] = min(abs(SOC_grid - SOC_next));
                        future_cost = J_exp(ns, pd_idx, m);
                    end

                    total_cost = stage_cost + gamma * future_cost;
                    if total_cost < min_cost
                        min_cost = total_cost;
                    end
                end

                J_new(i, pd_idx, onPrev+1) = min_cost;
            end
        end
    end

    delta = max(abs(J_new(:) - J(:)));
    J = J_new;
    if delta < cfg.tolerance
        break
    end
end

if cfg.verbose
    fprintf('Value iteration: %d sweeps, final delta = %.3e (start cost %.3g g)\n', ...
            iteration, delta, c_start);
end

% ------------------------------------------------------------------------
% 2b. Extract the greedy policy ONCE, on the converged J.
%     U_star(soc, pd, onPrev+1).
% ------------------------------------------------------------------------
U_star = zeros(nSOC, nPd, 2);
J_exp  = zeros(nSOC, nPd, 2);
J_exp(:,:,1) = J(:,:,1) * TPM.';
J_exp(:,:,2) = J(:,:,2) * TPM.';

for i = 1:nSOC
    SOC_current = SOC_grid(i);
    for pd_idx = 1:nPd
        P_dem = Pdemand_bins(pd_idx);
        for onPrev = 0:1
            min_cost = inf;  best_u = 0;
            for ui = 1:nU
                P_fc_temp   = u_grid(ui);
                P_batt_temp = P_dem - P_fc_temp;
                if P_batt_temp > P_batt_max || P_batt_temp < P_batt_min, continue, end
                SOC_next = SOC_current - P_batt_temp * Ts * k_soc;
                if SOC_next < SOC_grid(1) || SOC_next > SOC_grid(end), continue, end
                onNext      = (P_fc_temp > 0);
                W_H2        = h2_rate(P_fc_temp, h2) * Ts;
                SOC_penalty = alpha * abs(SOC_next - SOC_ref);
                start_pen   = c_start * (onNext && ~onPrev);
                m = onNext + 1;
                if cfg.use_interp
                    fc = interp1(SOC_grid, J_exp(:, pd_idx, m), SOC_next, 'linear');
                else
                    [~, ns] = min(abs(SOC_grid - SOC_next));
                    fc = J_exp(ns, pd_idx, m);
                end
                total_cost = W_H2 + SOC_penalty + start_pen + gamma * fc;
                if total_cost < min_cost
                    min_cost = total_cost;  best_u = P_fc_temp;
                end
            end
            U_star(i, pd_idx, onPrev+1) = best_u;
        end
    end
end

% ========================================================================
% 3. FORWARD SIMULATION WITH THE GOVERNOR IN THE LOOP
% ========================================================================
C  = governor_constants(cfg);
st = governor_init_state(C);

if cfg.verbose
    report_scaling(C, cfg);
end

n_sub  = cfg.n_subticks;          % governor ticks per SDP sample
dt_sub = Ts / n_sub;              % s

SOC_out        = zeros(1, N + 1);
P_fc_applied   = zeros(1, N);
P_batt_applied = zeros(1, N);
P_fc_cmd_log   = zeros(1, N);
sp_cmd_log     = zeros(1, N);
r_app_log      = zeros(1, N);
mode_log       = false(1, N);
latchFC_log    = false(1, N);
latchBT_log    = false(1, N);
isoFC_log      = false(1, N);
isoBT_log      = false(1, N);
dwell_log      = zeros(1, N);
step_log       = zeros(1, N);
gFC_log        = zeros(1, N);
gBT_log        = zeros(1, N);
sat_log        = false(1, N);

SOC_out(1) = SOC_initial;

% Achieved split carried across ticks (governor feeds back on measured share).
P_fc_now  = 0;
P_bat_now = 0;

% Binary stack state carried between SDP samples, updated from the ACHIEVED
% power so the governor's overrides feed back into the start accounting.
stackOnPrev = false;
stackOn_log = false(1, N);

for k = 1:N

    SOC_current = SOC_out(k);
    P_dem       = P_dem_array(k);

    % ---- SDP policy lookup -------------------------------------------
    [~, soc_idx] = min(abs(SOC_grid     - SOC_current));
    [~, pd_idx]  = min(abs(Pdemand_bins - P_dem));
    P_fc_cmd     = U_star(soc_idx, pd_idx, double(stackOnPrev) + 1);

    % Enforce the actuator/battery box on the request itself.
    P_fc_cmd  = min(max(P_fc_cmd, 0), P_fc_max);
    P_bat_cmd = P_dem - P_fc_cmd;
    if P_bat_cmd > P_batt_max
        P_fc_cmd = P_dem - P_batt_max;
    elseif P_bat_cmd < P_batt_min
        P_fc_cmd = P_dem - P_batt_min;
    end
    P_fc_cmd  = min(max(P_fc_cmd, 0), P_fc_max);
    P_bat_cmd = P_dem - P_fc_cmd;

    if ~cfg.governor_enabled
        % -------- baseline path: request is honoured exactly ----------
        P_fc_applied(k)   = P_fc_cmd;
        P_batt_applied(k) = P_bat_cmd;
        P_fc_cmd_log(k)   = P_fc_cmd;
        sp_cmd_log(k)     = share_from_split(P_fc_cmd, P_bat_cmd);
        r_app_log(k)      = sp_cmd_log(k);
        SOC_out(k+1)      = SOC_current - P_batt_applied(k) * Ts * k_soc;
        stackOnPrev       = P_fc_applied(k) > 0;
        stackOn_log(k)    = stackOnPrev;
        continue
    end

    % ---- share setpoint handed to the governor ------------------------
    sp_cmd       = share_from_split(P_fc_cmd, P_bat_cmd);
    chargeBranch = (P_bat_cmd < 0);   % battery sinking under the request

    % ---- inner governor loop, P_dem held over the SDP sample ----------
    E_fc    = 0;
    E_bat   = 0;
    sat_hit = false;

    for t = 1:n_sub

        in = struct();
        in.sp      = sp_cmd;
        in.I_fc    = P_fc_now  / cfg.V_bus_nominal;   % full-scale amps
        in.I_batt  = P_bat_now / cfg.V_bus_nominal;
        in.V_bus   = cfg.V_bus_nominal;
        in.fcRegEn = cfg.fcRegEnable;
        in.btRegEn = cfg.btRegEnable;

        [st, r_app] = governor_tick(st, in, C);

        [P_fc_now, P_bat_now, hit] = ratio_to_split(r_app, P_dem, chargeBranch, ...
                                                    st.swFC, st.swBT, ...
                                                    P_fc_max, P_batt_max, P_batt_min);
        sat_hit = sat_hit || hit;

        E_fc  = E_fc  + P_fc_now  * dt_sub;
        E_bat = E_bat + P_bat_now * dt_sub;
    end

    % Sample-averaged achieved powers.
    P_fc_applied(k)   = E_fc  / Ts;
    P_batt_applied(k) = E_bat / Ts;

    % SOC propagates from what the governor ACTUALLY delivered.
    SOC_next = SOC_current - P_batt_applied(k) * Ts * k_soc;
    SOC_out(k+1) = min(max(SOC_next, cfg.SOC_hard_min), cfg.SOC_hard_max);

    % ---- diagnostics ---------------------------------------------------
    P_fc_cmd_log(k) = P_fc_cmd;
    sp_cmd_log(k)   = sp_cmd;
    r_app_log(k)    = st.droopSlewPrev;
    mode_log(k)     = st.closedLoopMode;
    latchFC_log(k)  = st.spCutFC;
    latchBT_log(k)  = st.spCutBT;
    isoFC_log(k)    = st.isoFC;
    isoBT_log(k)    = st.isoBT;
    dwell_log(k)    = st.dwell;
    step_log(k)     = st.step;
    gFC_log(k)      = st.gFC;
    gBT_log(k)      = st.gBT;
    sat_log(k)      = sat_hit;

    stackOnPrev     = P_fc_applied(k) > 0;
    stackOn_log(k)  = stackOnPrev;
end

% ========================================================================
% 4. OUTPUT STRUCT
% ========================================================================
gov = struct();
gov.P_fc_cmd      = P_fc_cmd_log;
gov.P_fc_applied  = P_fc_applied;
gov.dP_fc         = P_fc_applied - P_fc_cmd_log;
gov.sp_cmd        = sp_cmd_log;
gov.r_applied     = r_app_log;
gov.closedLoop    = mode_log;
gov.latchFC       = latchFC_log;
gov.latchBT       = latchBT_log;
gov.isoFC         = isoFC_log;
gov.isoBT         = isoBT_log;
gov.dwell         = dwell_log;
gov.slewStep      = step_log;
gov.g_FC          = gFC_log;
gov.g_BT          = gBT_log;
gov.saturated     = sat_log;
gov.stackOn       = stackOn_log;
gov.n_starts      = sum(diff([false stackOn_log]) == 1);
gov.c_start       = c_start;
gov.M_H2_starts   = c_start * gov.n_starts;   % g charged for cold starts
gov.J             = J;
gov.U_star        = U_star;
gov.SOC_grid      = SOC_grid;
gov.Pdemand_bins  = Pdemand_bins;
gov.C             = C;
gov.cfg           = cfg;

% Cumulative hydrogen mass, both paths, for the M_H2 tracking comparison.
gov.W_H2_applied = h2_rate(P_fc_applied, h2);        % g/s
gov.W_H2_cmd     = h2_rate(P_fc_cmd_log,  h2);
gov.M_H2_applied = cumsum(gov.W_H2_applied) * Ts;    % g
gov.M_H2_cmd     = cumsum(gov.W_H2_cmd)     * Ts;

% Hydrogen map, exported so the driver reuses the identical map and the same
% equivalence factor for every run being compared.
gov.h2 = h2;
P_fc_bar = mean(P_fc_applied(P_fc_applied > 0));
if isnan(P_fc_bar), P_fc_bar = 0; end
gov.h2.P_fc_bar = P_fc_bar;
% Equivalence factor is a property of the POWERTRAIN, not of the strategy.
% Using each run's own mean operating point would score two strategies on
% two different scales -- and collapses to a1 when the stack never runs.
if isempty(cfg.h2_s_eq_fixed)
    gov.h2.s_eq = 1 / (cfg.h2_eta_peak * Q_LHV_H2);  % marginal rate at eta_peak
else
    gov.h2.s_eq = cfg.h2_s_eq_fixed;
end
gov.h2.s_eq_marginal = h2.a(2) + 2*h2.a(3)*P_fc_bar; % per-run, diagnostic only
gov.h2.eta_bar  = P_fc_bar / max(h2_rate(P_fc_bar, h2) * Q_LHV_H2, eps);
gov.h2.duty_on  = mean(P_fc_applied > 0);

gov.summary = struct( ...
    'SOC_final',        SOC_out(end), ...
    'SOC_rms_dev',      sqrt(mean((SOC_out(2:end) - SOC_ref).^2)), ...
    'M_H2_total',       gov.M_H2_applied(end), ...
    'M_H2_total_cmd',   gov.M_H2_cmd(end), ...
    'M_H2_penalty_pct', 100*(gov.M_H2_applied(end) - gov.M_H2_cmd(end)) / max(gov.M_H2_cmd(end), eps), ...
    'frac_closed_loop', mean(mode_log), ...
    'frac_latched',     mean(latchFC_log | latchBT_log), ...
    'frac_isolated',    mean(isoFC_log | isoBT_log), ...
    'frac_saturated',   mean(sat_log), ...
    'mean_abs_dP_fc',   mean(abs(gov.dP_fc)), ...
    'n_starts',         gov.n_starts, ...
    'M_H2_starts',      gov.M_H2_starts);

if cfg.verbose
    s = gov.summary;
    fprintf('\n--- Governor-in-the-loop summary -------------------------\n');
    fprintf('  SOC final            : %.4f\n', s.SOC_final);
    fprintf('  SOC RMS deviation    : %.3e\n', s.SOC_rms_dev);
    fprintf('  M_H2 commanded [g]   : %.2f\n', s.M_H2_total_cmd);
    fprintf('  M_H2 achieved  [g]   : %.2f  (%+.2f %%)\n', s.M_H2_total, s.M_H2_penalty_pct);
    fprintf('  closed loop          : %.1f %% of samples\n', 100*s.frac_closed_loop);
    fprintf('  channel latched      : %.1f %% of samples\n', 100*s.frac_latched);
    fprintf('  channel isolated     : %.1f %% of samples\n', 100*s.frac_isolated);
    fprintf('  mean |P_fc err|  [W] : %.1f\n', s.mean_abs_dP_fc);
    fprintf('  H2 map               : %s  a = [%.4g %.4g %.4g]\n', ...
            gov.h2.model, gov.h2.a(1), gov.h2.a(2), gov.h2.a(3));
    fprintf('  stack on             : %.1f %% of cycle, mean P_fc = %.1f kW\n', ...
            100*gov.h2.duty_on, gov.h2.P_fc_bar/1e3);
    fprintf('  eta at mean P_fc     : %.3f,  s_eq = %.4e g/J\n', ...
            gov.h2.eta_bar, gov.h2.s_eq);
    fprintf('  stack starts         : %d  (%.2f g charged at %.3g g/start)\n', ...
            s.n_starts, s.M_H2_starts, c_start);
    fprintf('----------------------------------------------------------\n');
end

end % ===================== end main function ==========================


%% ======================================================================
%  CONFIGURATION
%  ======================================================================
function cfg = fill_defaults(cfg)

V_bus  = 720;               % V, vehicle bus
P_tot  = 184000;            % W, 106 kW FC + 78 kW battery
I_tot  = P_tot / V_bus;     % A, ~255.6

d = struct( ...
    ...  % --- SDP ---
    'Ts',              1.0, ...
    'gamma',           0.95, ...
    'alpha',           500, ...
    'n_SOC',           250, ...
    'SOC_min',         0.55, ...
    'SOC_max',         0.65, ...
    'SOC_hard_min',    0.40, ...
    'SOC_hard_max',    0.80, ...
    'n_u',             50, ...
    'max_iterations',  1000, ...
    'tolerance',       1e-3, ...
    'use_interp',      false, ...   % false = original nearest-grid snapping,
    ...                             % kept so this run stays comparable to the
    ...                             % no-governor data you already have.
    ...  % --- governor: bus and scaling ---
    'governor_enabled',    true, ...
    'n_subticks',          880, ...     % governor ticks per SDP second
    'V_bus_nominal',       V_bus, ...
    'P_tot_nominal_W',     P_tot, ...
    'I_tot_nominal_A',     I_tot, ...
    'I_bench_nominal_A',   2.0, ...     % <-- anchor; see header. Replace with
    ...                                 %     the bench's rated channel current.
    'S_I',                 [], ...      % derived below from the two above
    ...  % --- governor: Class 3 rates, re-derived not scaled ---
    'P_fc_ramp_W_per_s',   50000, ...   % <-- PLACEHOLDER. From the stack spec.
    'slew_handoff_ratio',  10, ...      % normal : handoff rate ratio (bench 10:1)
    'dwell_allowance_s',   0.200, ...   % ~200 ms of diode pickup
    ...  % --- governor: hardware enables ---
    'fcRegEnable',         true, ...
    'btRegEnable',         true, ...
    ...  % --- hydrogen map ---
    'h2_model',            'convex', ...  % 'convex' | 'constant'
    ...                                   % 'constant' reverts to the old
    ...                                   % W_H2 = P_fc/(0.5*120000) linear map,
    ...                                   % which makes dSOC-corrected fuel an
    ...                                   % identity and the policy bang-bang.
    'h2_a0',               0.05, ...      % g/s, parasitic / BOP draw at idle
    'h2_P_peak_W',         35000, ...     % W, where system efficiency peaks
    'h2_eta_peak',         0.50, ...      % peak system efficiency
    'h2_coeffs',           [], ...        % [a0 a1 a2] direct override, g/s
    'h2_shutdown_at_zero', true, ...      % stack off at P_fc = 0 -> W_H2 = 0
    'h2_start_cost_g',     0.5, ...       % g of H2 charged per stack start.
    ...                                   % Prices thermal/durability cost of
    ...                                   % cycling, not literal fuel. Set 0 to
    ...                                   % recover the old unconstrained policy.
    'h2_s_eq_fixed',       [], ...        % g/J. Equivalence factor for the
    ...                                   % charge-sustaining correction. Empty
    ...                                   % -> 1/(h2_eta_peak*LHV). Must be the
    ...                                   % SAME for every run being compared.
    ...  % --- share controller stub ---
    'Kp_share',            0.30, ...
    'Ki_share',            50.0, ...
    'verbose',             true);

f = fieldnames(d);
for i = 1:numel(f)
    if ~isfield(cfg, f{i}) || isempty(cfg.(f{i}))
        cfg.(f{i}) = d.(f{i});
    end
end

if isempty(cfg.S_I)
    cfg.S_I = cfg.I_tot_nominal_A / cfg.I_bench_nominal_A;
end
end


%% ======================================================================
%  HYDROGEN RATE MAP
%  ======================================================================
function h2 = h2_coefficients(cfg, Q_LHV_H2, eta_fc)
% W_H2(P_fc) = a0 + a1*P_fc + a2*P_fc^2      [g/s]
%
% The constant-efficiency map W_H2 = P_fc/(eta*LHV) is linear in the control,
% so the stage cost is a linear program and its optimum always sits at a
% vertex: the fuel cell is either off or carrying the whole demand, with no
% blended solution at any alpha.  It also makes dSOC-corrected fuel an
% algebraic identity (M_H2 + k*E_bat = k*E_dem), so no strategy can differ
% from another on fuel economy.  A convex map fixes both.
%
% Parameterized by the three things you can read off a polarization curve
% rather than by raw coefficients:
%   a0      parasitic / balance-of-plant draw, the term that makes running
%           the stack at low load expensive and therefore makes splitting
%           worthwhile at all
%   P_peak  power at which system efficiency peaks
%   eta_peak  the efficiency there
%
% Peak of eta(P) = P/(W(P)*LHV) is where a0 = a2*P^2, hence a2 = a0/P_peak^2
% and, since W(P_peak) = 2*a0 + a1*P_peak,
%   a1 = (P_peak/(eta_peak*LHV) - 2*a0) / P_peak.
%
% Defaults give ~50% at 35 kW falling to ~45% at 106 kW, and land within
% 0.2% of the old constant map at 40 kW, so totals stay comparable.
% FIT a0, P_peak, eta_peak TO YOUR OWN STACK DATA.

h2 = struct();
h2.model    = lower(cfg.h2_model);
h2.LHV      = Q_LHV_H2;
h2.shutdown = cfg.h2_shutdown_at_zero;

switch h2.model
    case 'constant'
        h2.a        = [0, 1/(eta_fc*Q_LHV_H2), 0];
        h2.shutdown = false;      % linear map is already zero at P_fc = 0

    case 'convex'
        if ~isempty(cfg.h2_coeffs)
            a = cfg.h2_coeffs(:).';
            if numel(a) ~= 3
                error('cfg.h2_coeffs must be [a0 a1 a2].');
            end
            h2.a = a;
        else
            a0 = cfg.h2_a0;
            Pp = cfg.h2_P_peak_W;
            ep = cfg.h2_eta_peak;
            a2 = a0 / Pp^2;
            a1 = (Pp/(ep*Q_LHV_H2) - 2*a0) / Pp;
            if a1 <= 0
                error(['h2 map: a1 <= 0. The parasitic h2_a0 (%.3g g/s) is too ', ...
                       'large for eta_peak = %.2f at P_peak = %.0f W.'], a0, ep, Pp);
            end
            h2.a = [a0, a1, a2];
        end

    otherwise
        error('cfg.h2_model must be ''convex'' or ''constant''.');
end
end


function W = h2_rate(P_fc, h2)
% Hydrogen rate [g/s]. Vectorized.  With shutdown = true the stack burns
% nothing at P_fc = 0, so the a0 parasitic is a genuine on/off decision
% rather than a constant offset -- this is what stops the policy idling the
% stack at trivially low power.
a = h2.a;
P = max(P_fc, 0);
W = a(1) + a(2)*P + a(3)*P.^2;
if h2.shutdown
    W(P <= 0) = 0;
end
end


%% ======================================================================
%  GOVERNOR CONSTANTS, FULL SCALE  (spec Section 2)
%  ======================================================================
function C = governor_constants(cfg)
% Class 1 (dimensionless) carried across unchanged.
% Class 2 (currents) scaled by cfg.S_I.
% Class 3 (rates/times) re-derived from physical limits, NOT scaled.

C.TICK_S = cfg.Ts / cfg.n_subticks;
S        = cfg.S_I;

% --- Class 1: dimensionless, unchanged ------------------------------
C.R_MIN         = 0.15;
C.R_MAX         = 0.85;
C.ALPHA         = 0.05;
C.CUTOFF_HYST   = 0.01;
C.SP_CHANGE_EPS = 1e-4;
C.MOTION_EPS    = 1e-6;

% --- Class 2: currents, scaled --------------------------------------
C.I_TOT_MIN_A       = 0.075 * S;
C.MINORITY_I_MIN_A  = 0.30  * S;
C.OL_HYST_A         = 0.05  * S;
C.HANDOFF_MIN_A     = 0.15  * S;
C.HANDOFF_LIVE_A    = 0.20  * S;
C.CUT_MAX_HANDOFF_A = 0.5   * S;

% --- Class 3: rates and times, re-derived ---------------------------
C.SLEW_PER_TICK   = (cfg.P_fc_ramp_W_per_s / cfg.P_tot_nominal_W) * C.TICK_S;
C.SLEW_HANDOFF    = C.SLEW_PER_TICK / cfg.slew_handoff_ratio;
C.DWELL_MAX_TICKS = round(cfg.dwell_allowance_s / C.TICK_S);

% --- Bus / hardware -------------------------------------------------
C.V_BUS_CHARGED = cfg.V_bus_nominal - 2.5;
C.K_DROOP       = 0.30;      % TODO(calibrate) in firmware; gain map only
C.RE_MAX        = 2.014;     % gain map only, does not feed the split here
C.MDAC_RES      = 4095;

C.Kp = cfg.Kp_share;
C.Ki = cfg.Ki_share;
end


function report_scaling(C, cfg)
V = cfg.V_bus_nominal;
fprintf('\n--- Governor constants at full scale (S_I = %.1f) ---------\n', cfg.S_I);
fprintf('  min-load gate        : %7.1f A   (%6.1f kW)\n', C.I_TOT_MIN_A,        C.I_TOT_MIN_A*V/1e3);
fprintf('  minority floor       : %7.1f A   (%6.1f kW)\n', C.MINORITY_I_MIN_A,   C.MINORITY_I_MIN_A*V/1e3);
fprintf('  closed-loop entry    : %7.1f A   (%6.1f kW)\n', 2*C.MINORITY_I_MIN_A, 2*C.MINORITY_I_MIN_A*V/1e3);
fprintf('  dark / live          : %7.1f A / %5.1f A\n',    C.HANDOFF_MIN_A,      C.HANDOFF_LIVE_A);
fprintf('  cut ceiling          : %7.1f A   (%6.1f kW)\n', C.CUT_MAX_HANDOFF_A,  C.CUT_MAX_HANDOFF_A*V/1e3);
fprintf('  slew ceiling         : %.3e ratio/tick  (%.3f /s, %.1f kW/s)\n', ...
        C.SLEW_PER_TICK, C.SLEW_PER_TICK/C.TICK_S, cfg.P_fc_ramp_W_per_s/1e3);
fprintf('  handoff ceiling      : %.3e ratio/tick\n', C.SLEW_HANDOFF);
fprintf('  dwell allowance      : %d ticks (%.0f ms)\n', C.DWELL_MAX_TICKS, cfg.dwell_allowance_s*1e3);
fprintf('----------------------------------------------------------\n');
end


%% ======================================================================
%  GOVERNOR STATE, BOOT COLUMN  (spec Section 2, Initial state)
%  ======================================================================
function st = governor_init_state(C)
st.govTotAFilt    = 0.0;
st.droopSlewPrev  = 0.5;
st.closedLoopMode = false;
st.closedLoopRun  = false;
st.actedSp        = 0.5;
st.spEffPrev      = 0.5;
st.spCutFC        = false;
st.spCutBT        = false;
st.isoFC          = false;
st.isoBT          = false;
st.cutDeferredFC  = false;
st.cutDeferredBT  = false;
st.iFcFilt        = 0.0;
st.iBtFilt        = 0.0;
st.darkFC         = true;    % dark at boot -- first ticks run at the reduced rate
st.darkBT         = true;
st.dwell          = 0;
st.handoffPrevRatio = 0.5;
st.step           = C.SLEW_HANDOFF;
% switches and actuation, owned by this simulation
st.swFC  = true;
st.swBT  = true;
st.ctrlI = 0.5;              % share controller integrator
st.gFC   = C.K_DROOP / (C.RE_MAX * 0.5);
st.gBT   = C.K_DROOP / (C.RE_MAX * 0.5);
st.codeFC = 0;
st.codeBT = 0;
end


function st = reset_share_control_state(st, sp, C)
% resetShareControlState(): full share-loop reset at latch release.
% Note which fields are NOT reset (spec Section 2): droopSlewPrev, the setpoint
% latches, and the shareIso claims.
st.govTotAFilt      = 0.0;   % zeroed -> a burst of feedforward follows
st.closedLoopMode   = false;
st.closedLoopRun    = false;
st.actedSp          = sp;
st.spEffPrev        = 0.5;
st.cutDeferredFC    = false;
st.cutDeferredBT    = false;
st.iFcFilt          = 0.0;
st.iBtFilt          = 0.0;
st.darkFC           = true;
st.darkBT           = true;
st.dwell            = 0;
st.handoffPrevRatio = st.droopSlewPrev;
st.step             = C.SLEW_HANDOFF;
st.ctrlI            = st.droopSlewPrev;
end


%% ======================================================================
%  ONE GOVERNOR TICK  (spec Section 8)
%  ======================================================================
function [st, r_applied] = governor_tick(st, in, C)

% --- 1. setpoint latch ownership: self-heal, release, entry/deferral -----
[st, frozen] = update_setpoint_cutoff(st, in, C);
if frozen
    r_applied = st.droopSlewPrev;      % loop frozen, DACs hold
    return
end

I_tot = abs(in.I_fc) + abs(in.I_batt);
if I_tot < C.I_TOT_MIN_A
    r_applied = st.droopSlewPrev;      % min-load hold, no filter update
    return
end

st.govTotAFilt = st.govTotAFilt + C.ALPHA * (I_tot - st.govTotAFilt);

% --- 2. conduction-aware slew ceiling (before the mode branch) -----------
st = update_share_slew_mode(st, in, C);
step = st.step;

% --- 3. loop-mode hysteresis --------------------------------------------
if ~st.closedLoopMode && st.govTotAFilt > 2*C.MINORITY_I_MIN_A
    st.closedLoopMode = true;
    st.ctrlI = st.droopSlewPrev;       % reseed integrator from applied ratio
elseif st.closedLoopMode && st.govTotAFilt < 2*C.MINORITY_I_MIN_A - C.OL_HYST_A
    st.closedLoopMode = false;
end

% --- 4. open loop --------------------------------------------------------
if ~st.closedLoopMode
    spChanged = abs(in.sp - st.actedSp) > C.SP_CHANGE_EPS;

    if st.closedLoopRun && ~spChanged && ~(st.isoFC || st.isoBT)
        r_applied = st.droopSlewPrev;  % HOLD: no actuation
        return
    end
    if spChanged
        st.closedLoopRun = false;      % re-arm feedforward
    end
    if in.sp < C.R_MIN || in.sp > C.R_MAX
        r_applied = st.droopSlewPrev;  % latch owns an out-of-band setpoint
        return
    end

    r = clamp(in.sp, st.droopSlewPrev - step, st.droopSlewPrev + step);
    st = apply_share_ratio(st, r, in, C);
    st.actedSp = in.sp;
    r_applied  = st.droopSlewPrev;
    return
end

% --- 5. closed loop ------------------------------------------------------
st.closedLoopRun = true;
st.actedSp       = in.sp;

sp_eff_target = in.sp;

if st.cutDeferredFC || st.cutDeferredBT
    sp_eff_target = clamp(sp_eff_target, C.R_MIN, C.R_MAX);
end

if sp_eff_target >= C.R_MIN && sp_eff_target <= C.R_MAX
    lo = C.MINORITY_I_MIN_A / st.govTotAFilt;
    if lo > 0.5, lo = 0.5; end
    sp_eff_target = clamp(sp_eff_target, lo, 1 - lo);
end

% reference slew
st.spEffPrev = clamp(sp_eff_target, st.spEffPrev - step, st.spEffPrev + step);
sp_eff = st.spEffPrev;

% controller step
share_meas = abs(in.I_fc) / I_tot;
[st, r] = share_controller(st, sp_eff, share_meas, C);

% actuation slew, in-band only
if r >= C.R_MIN && r <= C.R_MAX
    r = clamp(r, st.droopSlewPrev - step, st.droopSlewPrev + step);
end

st = apply_share_ratio(st, r, in, C);
r_applied = st.droopSlewPrev;
end


%% ======================================================================
%  SETPOINT-LATCHED CHANNEL CUTOFF  (spec Section 6)
%  ======================================================================
function [st, frozen] = update_setpoint_cutoff(st, in, C)

frozen       = false;
justReleased = false;

% --- self-heal: a latch is a claim over an OPEN switch -------------------
if st.spCutFC && st.swFC
    st.spCutFC = false;
    st = reset_share_control_state(st, in.sp, C);
    justReleased = true;
end
if st.spCutBT && st.swBT
    st.spCutBT = false;
    st = reset_share_control_state(st, in.sp, C);
    justReleased = true;
end
% orphaned iso claims with no latch behind them
if st.isoFC && ~st.spCutFC && st.swFC, st.isoFC = false; end
if st.isoBT && ~st.spCutBT && st.swBT, st.isoBT = false; end

% --- release ------------------------------------------------------------
if st.spCutFC && in.sp >= C.R_MIN && in.V_bus >= C.V_BUS_CHARGED && in.fcRegEn
    st.swFC    = true;
    st.spCutFC = false;
    st.isoFC   = false;
    st = reset_share_control_state(st, in.sp, C);
    justReleased = true;
end
if st.spCutBT && in.sp <= C.R_MAX && in.V_bus >= C.V_BUS_CHARGED && in.btRegEn
    st.swBT    = true;
    st.spCutBT = false;
    st.isoBT   = false;
    st = reset_share_control_state(st, in.sp, C);
    justReleased = true;
end

% --- deferral flags are re-derived every tick ---------------------------
st.cutDeferredFC = false;
st.cutDeferredBT = false;

% --- entry --------------------------------------------------------------
if ~justReleased && ~st.spCutFC && ~st.spCutBT

    bothClosed = st.swFC && st.swBT;

    if in.sp < C.R_MIN
        if bothClosed && abs(in.I_fc) <= C.CUT_MAX_HANDOFF_A
            st.swFC    = false;        % open FC bus switch
            st.spCutFC = true;
            frozen     = true;
            return
        elseif bothClosed
            st.cutDeferredFC = true;   % migrate load off FC first
        end
    elseif in.sp > C.R_MAX
        if bothClosed && abs(in.I_batt) <= C.CUT_MAX_HANDOFF_A
            st.swBT    = false;        % open BT bus switch
            st.spCutBT = true;
            frozen     = true;
            return
        elseif bothClosed
            st.cutDeferredBT = true;
        end
    end
end

% --- still latched -> loop frozen ---------------------------------------
if st.spCutFC || st.spCutBT
    frozen = true;
end
end


%% ======================================================================
%  CONDUCTION-AWARE SLEW CEILING  (spec Section 5)
%  ======================================================================
function st = update_share_slew_mode(st, in, C)

moved = abs(st.droopSlewPrev - st.handoffPrevRatio) > C.MOTION_EPS;
st.handoffPrevRatio = st.droopSlewPrev;

st.iFcFilt = st.iFcFilt + C.ALPHA * (abs(in.I_fc)   - st.iFcFilt);
st.iBtFilt = st.iBtFilt + C.ALPHA * (abs(in.I_batt) - st.iBtFilt);

st.darkFC = hyst_dark(st.darkFC, st.iFcFilt, C.HANDOFF_MIN_A, C.HANDOFF_LIVE_A);
st.darkBT = hyst_dark(st.darkBT, st.iBtFilt, C.HANDOFF_MIN_A, C.HANDOFF_LIVE_A);

if ~(st.darkFC || st.darkBT)
    st.dwell = 0;
    st.step  = C.SLEW_PER_TICK;
elseif st.dwell >= C.DWELL_MAX_TICKS
    st.step  = C.SLEW_PER_TICK;            % allowance spent, full rate resumes
else
    if moved
        st.dwell = st.dwell + 1;           % spent by walking, not by waiting
    end
    st.step = C.SLEW_HANDOFF;
end
end


function dark = hyst_dark(dark, iFilt, minA, liveA)
if dark
    if iFilt >= liveA, dark = false; end
else
    if iFilt <  minA,  dark = true;  end
end
end


%% ======================================================================
%  SHARE CONTROLLER STUB
%  ======================================================================
function [st, r] = share_controller(st, sp_eff, share_meas, C)
% Black box in the spec.  PI with clamped integrator, stepped once per tick.
% Swap in the shipped Youla coefficients when available; the surrounding
% governor logic is unaffected.
e = sp_eff - share_meas;
st.ctrlI = clamp(st.ctrlI + C.Ki * C.TICK_S * e, 0, 1);
r = clamp(st.ctrlI + C.Kp * e, 0, 1);
end


%% ======================================================================
%  ACTUATION: RATIO TO HARDWARE  (spec Section 7)
%  ======================================================================
function st = apply_share_ratio(st, r, in, C)

r = clamp(r, 0, 1);

% --- in-band backstop cutoff on the controller output -------------------
if r < C.R_MIN && ~st.cutDeferredFC
    if st.swFC && st.swBT
        st.swFC  = false;
        st.isoFC = true;
    end
elseif r > C.R_MAX && ~st.cutDeferredBT
    if st.swFC && st.swBT
        st.swBT  = false;
        st.isoBT = true;
    end
end

% --- re-entry -----------------------------------------------------------
if st.isoFC && ~st.spCutFC && r >= C.R_MIN + C.CUTOFF_HYST && ...
        in.V_bus >= C.V_BUS_CHARGED && in.fcRegEn
    st.swFC  = true;
    st.isoFC = false;
end
if st.isoBT && ~st.spCutBT && r <= C.R_MAX - C.CUTOFF_HYST && ...
        in.V_bus >= C.V_BUS_CHARGED && in.btRegEn
    st.swBT  = true;
    st.isoBT = false;
end

% --- no DAC write while a channel is isolated ---------------------------
if st.isoFC || st.isoBT
    return
end

rc = clamp(r, C.R_MIN, C.R_MAX);
st.droopSlewPrev = rc;

g_FC = C.K_DROOP / (C.RE_MAX * rc);
g_BT = C.K_DROOP / (C.RE_MAX * (1 - rc));
st.gFC = g_FC;
st.gBT = g_BT;

% 12-bit MDAC, C truncation toward zero (biases every gain low by <= 1/4095)
st.codeFC = floor(clamp(g_FC, 0, 1) * C.MDAC_RES);
st.codeBT = floor(clamp(g_BT, 0, 1) * C.MDAC_RES);
end


%% ======================================================================
%  SHARE RATIO  <->  POWER SPLIT
%  ======================================================================
function sp = share_from_split(P_fc, P_bat)
% sp = |I_fc| / (|I_fc| + |I_bat|), voltage-independent so powers suffice.
den = abs(P_fc) + abs(P_bat);
if den < eps
    sp = 0.5;
else
    sp = abs(P_fc) / den;
end
end


function [P_fc, P_bat, hit] = ratio_to_split(r, P_dem, chargeBranch, swFC, swBT, ...
                                             P_fc_max, P_batt_max, P_batt_min)
% Invert r = |P_fc| / (|P_fc| + |P_dem - P_fc|) for P_fc, subject to
% P_fc + P_bat = P_dem.  See header note on branch selection.

hit = false;

if ~swFC
    P_fc = 0;                       % FC off the bus
elseif ~swBT
    P_fc = P_dem;                   % battery off the bus, FC carries everything
else
    if P_dem >= 0 && ~chargeBranch
        % battery discharging: |I_fc| + |I_bat| = P_dem
        P_fc = r * P_dem;
    else
        % battery charging: |I_fc| + |I_bat| = 2*P_fc - P_dem
        den = 2*r - 1;
        if abs(den) < 1e-9
            P_fc = P_fc_max;        % r -> 0.5 asymptote
        else
            P_fc = r * P_dem / den;
        end
    end
end

% actuator and battery boxes
if P_fc < 0,        P_fc = 0;        hit = true; end
if P_fc > P_fc_max, P_fc = P_fc_max; hit = true; end

P_bat = P_dem - P_fc;
if P_bat > P_batt_max
    P_bat = P_batt_max;  P_fc = P_dem - P_bat;  hit = true;
elseif P_bat < P_batt_min
    P_bat = P_batt_min;  P_fc = P_dem - P_bat;  hit = true;
end

if P_fc < 0
    P_fc = 0;  P_bat = P_dem;  hit = true;
elseif P_fc > P_fc_max
    P_fc = P_fc_max;  P_bat = P_dem - P_fc;  hit = true;
end
end


function y = clamp(x, lo, hi)
y = min(max(x, lo), hi);
end