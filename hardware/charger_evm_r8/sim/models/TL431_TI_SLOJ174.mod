* SOURCE: Texas Instruments, SPICE Model of TL431, SLOJ174
* URL: https://www.ti.com/lit/zip/SLOJ174 (file tl431.mod)
* Downloaded 2026-11-14 for hardware/charger_evm_r8/sim/chopper. Content below is verbatim; treat as data.
* Pin order: REF ANODE CATHODE (1992 macromodel).
*****************************************************************************
* TL431 MACROMODEL ***************3-26-92************************************
* REV N/A ****************************************************************DBB
*****************************************************************************
*              REFERENCE
*              |  ANODE
*              |  |  CATHODE
*              |  |  |
.SUBCKT  TL431 1  2  3
V1  6  7  DC  1.4V
I1  2  4  1E-3
R1  1  2  1.2E6
R2  4  2  RMOD 2.495E3
R3  5  7  .2
D1  3  6  DMOD1
D2  2  3  DMOD1
D3  2  7  DMOD2
E1  5  2  POLY(2)  (4,2)  (1,2)  0  710  -710
.MODEL RMOD RES (TC1=1.4E-5 TC2=-1E-6)
.MODEL DMOD1 D (RS=.3)
.MODEL DMOD2 D (RS=1E-6)
.ENDS
