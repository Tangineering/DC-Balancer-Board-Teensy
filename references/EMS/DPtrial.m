clear all;
close all;
clc;
%%
% Load the demand power from the MAT file and convert it to W
data = load('simulink_pdem_output_UDDS.mat', 'out');
%data = load('simulink_pdem_output_stochastic_V10.mat', 'out');
%data = load('simulink_pdem_output_UDDS10.mat', 'out');
%data = load('simulink_pdem_output_WLTP.mat', 'out');
%data = load('simulink_pdem_output_NEDC.mat', 'out');
P_dem = data.out.simout.Data;  % P_dem is in kW, convert to W if needed
Time = data.out.simout.Time;
wholeSeconds = 0:1:1369;
P_dem1 = interp1(Time, P_dem, wholeSeconds, 'linear');
P_dem1 = P_dem1';
%% SOC_initial should be given as a fraction between 0 and 1
SOC_initial = 0.6; 

% Call the DP function with the demand power and initial SOC
[P_batt, P_fc, SOC_out] = DP_EnergyManagement2(P_dem1, SOC_initial);

%% Plot the results
figure(1)
plot(P_fc)

hold on
plot(P_batt)

hold on

plot(P_dem1)
legend('Pfc','Pbatt','Preq')
xlabel('Time Steps')
ylabel('Power (Watts*10^4)')


figure(2)
plot(SOC_out)
title('State of Charge (SOC)')
xlabel('Time Steps')
ylabel('SOC')

W_H2 =  P_fc / (0.55 * 120000);
figure(3)
plot(W_H2)
title('Hydrogen Consumption (W_{H2})')
xlabel('Time Steps')
ylabel('H_2 Consumption (g/s)')

% % Define transfer function for H2 consumption
% num2 = 2.016 * [2.733, 1.115e6, 1.234e9, 3.211e11];
% den2 = 720 * 1.45 * [1, 1.187e7, 1.948e10, 7.864e12, 3.515e13];
% H2_tf = tf(num2, den2);
% 
% % Simulate dynamic hydrogen consumption using lsim
% dt = 1; % 1 second time step
% t = 0:dt:(length(P_fc)-1)*dt;
% W_H2_2 = lsim(H2_tf, P_fc, t);

% Plot hydrogen consumption 
figure(3)
plot(W_H2)
title('Hydrogen Consumption (W_{H_2})')
xlabel('Time Steps')
ylabel('H_2 Consumption (g/s)')

% Calculate cumulative hydrogen consumption
cumulative_H2 = cumsum(W_H2);  
figure(4)
plot(cumulative_H2)
title('Cumulative Hydrogen Consumption')
xlabel('Time Steps')
ylabel('Cumulative H_2 Consumption (g)')
cumulative_H2(end)


%% Assuming a time step of 1 second
t = (0:length(P_fc)-1)';  % Create a time vector (1370x1)
% figure(5)
% plot(t,P_fc./P_dem1', 'ro')
% legend('power index Pfc/Preq')
% Combine time and data for Simulink
P_fc_simulink = [t'; P_fc];
P_batt_simulink = [t'; P_batt];
% SOC_target =  [t';  SOC_out(1:end-1)];
% H2_cons_target =  [t'; cumulative_H2];
P_dem_simulink = [t'; P_dem1'];
%save('FCHEV_pdem_data_UDDS_V2.mat', 'P_dem_simulink');
save('FCHEV_power_datanew3_UDDS.mat', 'P_fc_simulink', 'P_batt_simulink');
%save('FCHEV_DP_target_UDDS.mat', 'SOC_target', 'H2_cons_target');

% Ptot= P_fc+P_batt;
% plot(Ptot)
% hold on 
% plot(P_dem)

