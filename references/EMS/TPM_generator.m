clear; clc;

% Load and Resample Data
num_datasets = 10;  % Number of datasets
P_demand_all = [];  % Container for all resampled P_demand data
time_common = 0:1:1000; % Common time grid (0.1-second intervals for finer granularity)

m_original = 2242;      %kg
vmax_original = 130;    %kph
m_scale = 3.5;          %kg
vmax_scale = 3*3.6;     %kph (from 3m/s)

sm = m_scale/m_original; % mass scaling factor
sl = vmax_scale/vmax_original;  % length scaling factor
sE = sm*sl^2;           % energy scaling factor

for i = 1:num_datasets
    filename = ['Pdem_cycles/simulink_pdem_output_stochastic_V' num2str(i) '.mat'];
    data = load(filename);

    % Extract time and P_demand
    time_original = data.out.simout.Time;
    P_demand_original = data.out.simout.Data.*sE;

    % Resample with spline interpolation for smoother transitions
    P_demand_resampled = interp1(time_original, P_demand_original, time_common, 'spline', 'extrap');


    % Store all datasets
    P_demand_all = [P_demand_all; P_demand_resampled(:)];
end

% Normalize P_demand
P_demand_normalized = (P_demand_all - min(P_demand_all)) / (max(P_demand_all) - min(P_demand_all));


% Define Bins and Discretize
P_demand_bins = linspace(0, 1, 51); % 10 bins
P_demand_indices = discretize(P_demand_normalized, P_demand_bins);

% Transition Count Matrix
num_bins = length(P_demand_bins) - 1;
transition_counts = zeros(num_bins, num_bins);

for t = 1:length(P_demand_indices) - 1
    current_bin = P_demand_indices(t);
    next_bin = P_demand_indices(t + 1);

    % Debug transitions
    if ~isnan(current_bin) && ~isnan(next_bin)
        transition_counts(current_bin, next_bin) = ...
            transition_counts(current_bin, next_bin) + 1;
    else

    end
end



% Normalize to Create TPM
TPM = transition_counts ./ sum(transition_counts, 2);
TPM(isnan(TPM)) = 0; % Handle empty rows

% Validate TPM
row_sums = sum(TPM, 2);
disp('Row Sums After Normalization:');
disp(row_sums);

% Visualize TPM
imagesc(TPM);
colorbar;
xlabel('To Bin');
ylabel('From Bin');
title('Transition Probability Matrix (TPM) for Pdem');