BASE    equ 02E1h
R_DIR   equ BASE+0000h      ; r: data in        w: CDOR data out
R_ISR1  equ BASE+0400h      ; r: int status 1   w: IMR1
R_ISR2  equ BASE+0800h      ; r: int status 2   w: IMR2
R_SPSR  equ BASE+0C00h      ; r: serial poll st w: SPMR
R_ADSR  equ BASE+1000h      ; r: address status w: ADMR
R_CPTR  equ BASE+1400h      ; r: cmd pass thru  w: AUXMR
R_ADR0  equ BASE+1800h      ; r: address 0      w: ADR
R_ADR1  equ BASE+1C00h      ; r: address 1      w: EOSR
R_CDOR  equ R_DIR
R_IMR1  equ R_ISR1
R_IMR2  equ R_ISR2
R_SPMR  equ R_SPSR
R_ADMR  equ R_ADSR
R_AUXMR equ R_CPTR
R_ADR   equ R_ADR0

ISR1_DI  equ 01h
ISR1_DO  equ 02h
ISR1_ERR equ 04h
ISR1_END equ 10h
ISR2_CO  equ 08h
ADSR_CIC equ 80h

AUX_PON  equ 00h
AUX_CR   equ 02h
AUX_SEOI equ 06h
AUX_GTS  equ 10h
AUX_TCA  equ 11h
AUX_CIFC equ 16h
AUX_CREN equ 17h
AUX_SIFC equ 1Eh
AUX_SREN equ 1Fh

MYADDR  equ 21
UNL     equ 3Fh
UNT     equ 5Fh
SPE     equ 18h
SPD     equ 19h

T_CMD   equ 9                   ; ~0.5 s for command bytes
T_SPOLL equ 3                   ; ~0.15 s for a serial-poll answer
T_DATA  equ 36                  ; ~2 s for data bytes
GHOSTLAT equ 8                  ; answers slower than this = ghost
