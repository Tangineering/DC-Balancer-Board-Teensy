function [P_batt_optimal, P_fc_optimal, SOC_out] = SDP_EnergyManagement2(P_dem_array, SOC_initial, TPM)
    % Parameters
    N = length(P_dem_array); % Number of time steps
    SOC_grid = linspace(0.55, 0.65, 250); % SOC grid
    P_fc_max = 106000; % Maximum power from fuel cell (106 kW)
    P_batt_max = 78000; % Maximum power from battery (78 kW)
    P_batt_min = -78000; % Minimum power from battery (discharge limit -78 kW)
    Q = 100; % Battery capacity in Ah
    Em = 720; % Battery open circuit voltage
    alpha = 500; % Weighting factor for SOC deviation
    gamma = 0.95; % Discount factor
    eta_fc = 0.5; % Fuel cell efficiency
    Q_LHV_H2 = 120000; % Lower heating value of hydrogen in J/g

    % Discretize power demand
    Pdemand_bins = linspace(-50000, 60000, size(TPM, 1)); % Align bins with TPM rows

    % Initialize the cost-to-go function
    J = zeros(length(SOC_grid), length(Pdemand_bins)); % Value function (cost-to-go matrix)
    J_new = zeros(size(J)); % Temporary matrix for updates during iteration

    % Bellman iteration (Policy Evaluation)
    % -----------------------------------------------------------
    % This step computes the cost-to-go matrix J for all states.
    % J represents the minimum cost-to-go for each state-action pair,
    % considering future costs using the transition probability matrix (TPM).
    % -----------------------------------------------------------
    max_iterations = 1000;
    tolerance = 1e-3; % Convergence tolerance for Bellman iteration
    for iteration = 1:max_iterations
        for i = 1:length(SOC_grid) % Iterate over SOC states
            SOC_current = SOC_grid(i);
            for pd_idx = 1:length(Pdemand_bins) % Iterate over power demand states
                P_dem = Pdemand_bins(pd_idx);
                min_cost = inf; % Initialize minimum cost for this state

                % Loop over all control actions (fuel cell power)
                for u = linspace(0, P_fc_max, 50)
                    P_fc_temp = u;
                    P_batt_temp = P_dem - P_fc_temp;

                    % Check power limits
                    if P_batt_temp <= P_batt_max && P_batt_temp >= P_batt_min
                        % Battery current and SOC transition
                        I_batt = P_batt_temp / Em;
                        SOC_next = SOC_current - (I_batt * (1 / (3600 * Q)));

                        % Ensure SOC stays within bounds
                        if SOC_next >= SOC_grid(1) && SOC_next <= SOC_grid(end)
                            [~, next_soc_idx] = min(abs(SOC_grid - SOC_next));

                            % Hydrogen consumption
                            W_H2 = P_fc_temp / (eta_fc * Q_LHV_H2);

                            % SOC deviation penalty
                            SOC_penalty = alpha * abs(SOC_next - 0.6);

                            % Stage cost (current cost)
                            stage_cost = W_H2 + SOC_penalty;

                            % Expected future cost (based on TPM and cost-to-go matrix J)
                            future_cost = 0;
                            for next_pd_idx = 1:length(Pdemand_bins)
                                P_trans = TPM(pd_idx, next_pd_idx);
                                future_cost = future_cost + P_trans * J(next_soc_idx, next_pd_idx);
                            end

                            % Total cost for this action
                            total_cost = stage_cost + gamma * future_cost;
                            min_cost = min(min_cost, total_cost);
                        end
                    end
                end

                % Update cost-to-go matrix for this state
                J_new(i, pd_idx) = min_cost;
            end
        end

        % Check convergence of Bellman iteration
        if max(abs(J_new(:) - J(:))) < tolerance
            break;
        end
        J = J_new; % Update the cost-to-go matrix for the next iteration
    end

    % Policy Improvement (Forward Simulation)
    % -----------------------------------------------------------
    % This step uses the precomputed cost-to-go matrix J to determine
    % the optimal control action (fuel cell power) for each time step.
    % Forward simulation applies the policy to the actual state trajectory.
    % -----------------------------------------------------------
    SOC_out = zeros(1, N + 1); % Initialize SOC trajectory
    P_fc_optimal = zeros(1, N); % Optimal fuel cell power
    P_batt_optimal = zeros(1, N); % Optimal battery power

    SOC_out(1) = SOC_initial; % Set the initial SOC
    for k = 1:N
        SOC_current = SOC_out(k);
        [~, soc_idx] = min(abs(SOC_grid - SOC_current)); % Match SOC to closest grid point
        P_dem = P_dem_array(k);
        [~, pd_idx] = min(abs(Pdemand_bins - P_dem)); % Match power demand to closest bin

        % Optimal control policy
        min_cost = inf;
        best_u = 0;

        for u = linspace(0, P_fc_max, 50)
            P_fc_temp = u;
            P_batt_temp = P_dem - P_fc_temp;

            % Check power limits
            if P_batt_temp <= P_batt_max && P_batt_temp >= P_batt_min
                I_batt = P_batt_temp / Em;
                SOC_next = SOC_current - (I_batt * (1 / (3600 * Q)));

                % Ensure SOC stays within bounds
                if SOC_next >= SOC_grid(1) && SOC_next <= SOC_grid(end)
                    [~, next_soc_idx] = min(abs(SOC_grid - SOC_next));

                    % Hydrogen consumption
                    W_H2 = P_fc_temp / (eta_fc * Q_LHV_H2);

                    % SOC penalty
                    SOC_penalty = alpha * abs(SOC_next - 0.6);

                    % Stage cost
                    stage_cost = W_H2 + SOC_penalty;

                    % Expected future cost (using precomputed J)
                    future_cost = 0;
                    for next_pd_idx = 1:length(Pdemand_bins)
                        P_trans = TPM(pd_idx, next_pd_idx);
                        future_cost = future_cost + P_trans * J(next_soc_idx, next_pd_idx);
                    end

                    % Total cost for this action
                    total_cost = stage_cost + gamma * future_cost;

                    % Update the best control action
                    if total_cost < min_cost
                        min_cost = total_cost;
                        best_u = u;
                    end
                end
            end
        end

        % Apply optimal control action
        P_fc_optimal(k) = best_u;
        P_batt_optimal(k) = P_dem - P_fc_optimal(k);
        SOC_out(k + 1) = SOC_current - (P_batt_optimal(k) / Em) * (1 / (3600 * Q)); % Update SOC
    end
end
