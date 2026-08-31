function [P_batt, P_fc, SOC_out] = DP_EnergyManagement2(P_dem, SOC_initial)
    % Parameters
    N = length(P_dem); %1000
    SOC_grid = linspace(0.55, 0.65, 500); % SOC grid from .585 to .615
    P_fc_max = 106000; % Maximum power from fuel cell (106 kW)
    P_batt_max = 78000; % Maximum power from battery (78 kW)
    P_batt_min = -78000; % Minimum power from battery (discharge limit -78 kW)
    Q = 100; % Battery capacity in Ah
    Em = 720; % Battery open circuit voltage
    lambda_terminal = 1e4; % Heavy penalty for terminal SOC deviation NEDC - 50000 1e4
    lambda_deviation =50; %500
    eta_fc = 0.55; % Fuel cell efficiency
    Q_LHV_H2 = 120000; % Lower heating value of hydrogen in J/g
    

    % Initialize Cost-to-go function
    J = inf(length(SOC_grid), N+1);
    
    % Terminal cost heavily penalizes deviation from initial SOC
    J(:, end) = lambda_terminal * abs(SOC_grid - SOC_initial);

    % Backward Induction
    for k = N:-1:1
        for i = 1:length(SOC_grid)
            SOC_state = SOC_grid(i);
            for u = linspace(0, P_fc_max, 200) % Control variable: Fuel cell power
                P_fc_temp = u;
                P_batt_temp = P_dem(k) - P_fc_temp;

                % Ensure power limits are respected
                if P_fc_temp <= P_fc_max && P_batt_temp <= P_batt_max && P_batt_temp >= P_batt_min
                    % Battery current calculation (I_batt = P_batt / Em)
                    I_batt = P_batt_temp / Em;

                    % State transition equation for SOC
                    SOC_next = SOC_state - (I_batt * (1 / (3600 * Q))); % SOC transition

                    if SOC_next >= SOC_grid(1) && SOC_next <= SOC_grid(end)
                        [~, idx] = min(abs(SOC_grid - SOC_next));

                        % Hydrogen consumption calculation
                        W_H2 = P_fc_temp / (eta_fc * Q_LHV_H2);

                        % penalty: discourage SOC to deviate a lot from SOC_initial in the middle of the simulation
                        SOC_penalty = lambda_deviation * abs(SOC_next - SOC_initial);

                        % Objective function (hydrogen consumption + SOC penalties)
                        stage_cost = W_H2 + SOC_penalty;
                        J(i, k) = min(J(i, k), stage_cost + J(idx, k+1));
                    end
                end
            end
        end
    end

    % Forward Simulation to find the optimal policy
    P_batt = zeros(1, N);
    P_fc = zeros(1, N);
    SOC_out = zeros(1, N+1); % Initialize SOC array
    SOC_out(1) = SOC_initial; % Initial SOC
    for k = 1:N
        SOC_current = SOC_out(k);
        [~, idx] = min(abs(SOC_grid - SOC_current)); % Find the closest SOC state
        min_cost = inf;
        best_u = 0;
        for u = linspace(0, P_fc_max, 200) % Loop through possible control actions
            P_fc_temp = u;
            P_batt_temp = P_dem(k) - P_fc_temp; % Battery power = demand - fuel cell power

            if P_fc_temp <= P_fc_max && P_batt_temp <= P_batt_max && P_batt_temp >= P_batt_min
                % Battery current calculation (I_batt = P_batt / Em)
                I_batt = P_batt_temp / Em;

                % State transition equation for SOC
                SOC_next = SOC_current - (I_batt * (1 / (3600 * Q))); % SOC transition

                if SOC_next >= SOC_grid(1) && SOC_next <= SOC_grid(end)
                    [~, idx_next] = min(abs(SOC_grid - SOC_next));

                    % Hydrogen consumption calculation
                    W_H2 = P_fc_temp / (eta_fc * Q_LHV_H2);

                    % Penalty: encourage SOC to deviate from SOC_initial in the middle of the simulation
                    SOC_penalty = lambda_deviation * abs(SOC_next - SOC_initial);

                    % Objective function (hydrogen consumption + SOC penalties)
                    stage_cost = W_H2 + SOC_penalty;
                    total_cost = stage_cost + J(idx_next, k+1); % Update total cost
                    if total_cost < min_cost
                        min_cost = total_cost;
                        best_u = u;
                    end
                end
            end
        end
        P_fc(k) = best_u; % Update the fuel cell power for this step
        P_batt(k) = P_dem(k) - P_fc(k); % Calculate the battery power
        SOC_out(k+1) = SOC_current - (P_batt(k) / Em) * (1 / (3600 * Q)); % Update SOC for next step
    end

    % Ensure the final SOC matches the initial SOC
    SOC_deviation = SOC_out(end) - SOC_initial;
    if abs(SOC_deviation) > 0
        warning('Final SOC deviates from initial SOC by %f', SOC_deviation);
    end
end
