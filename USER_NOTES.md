# HIL Updates 2026-08-26a

> Every item in this block has shipped — see the `CLAUDE.md` 2026-08-27c addendum.

- Measure K_DROOP_BUS for the plant simulation empirically from previous logs.
- Let's add an option that can be utilized in certain scenarios to enable high-fidelity electrical simulation. 
    - The high-fidelity electrical simulation should run at the maximum frequency possible on the PC that is running it, and at a separate rate than the 1kHz mechanical plant.
    - For the high-fidelity electrical simulation, include at least:
        - TPS61288 modeling based on previous plant simulation, ideally the full-state version developed from the datasheet transfer functions.
        - RT1987 modeling based on its datasheet and empirical observations. This should include turn-on delays, slew rates, foldback current shutoff, (the 100nF CSS was applied to the FC, BT, and MOT swithces but not to any others).
        - Droop chain propagation and its effect on the TPS61288 output.
        - The effect of bulk capacitance on the various voltage nodes as power flows.
        - If possible, parasitic inductances on boost regulator output pins, configured either with the long-trace results from inductance modeling or short-trace results after putting bodge capacitors directly on the output nodes.
        - The shunt resistor mechanism.
        - Electrical noise on each signal.
    - The goal is to be able to recreate as many of the data logs and failure modes observed as possible.
    - When complete, add scenarios that utilize the high-fidelity electrical simulation.
- Add the charging path functionality and scenarios that utilize it.
- Add a class of scenarios comprised by all real data logs that are useful to recreate.
    - Highest priority to include are those that had failures or degenerate behavior, but also incldue good runs. 
    - Ignore runs such as the manually-turned wheel logs that were for diagnosing the encoder wheel.
    - Since the firmware may differ from what was used when the log was collected, reporting on the results of these logs should value conformance to the original log only when the firmware version matches or if there is no important difference in functionality between the used and  historical firmware versions. For logs with older firmware versions, you can decide whether to omit it from the scenario suite or to include it with a desired deviation from the log that the new firmware should achieve, such as avoiding a failure mode that was previously observed.
    - Write a document that goes over what logs were used and why. This should be upkept as new logs are added.
- Add a wrapper script that runs all scenarios and collects the output data to package into the final HIL report.