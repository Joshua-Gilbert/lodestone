// Host stand-in for <avr/interrupt.h>: ISRs become plain functions (the test
// calls none of them), and nothing interrupts.
#pragma once
#define ISR(v) void v(void)
#define cli()
#define sei()
