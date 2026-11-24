// Host stand-in for <avr/interrupt.h>: ISRs become plain functions, and
// nothing interrupts. A test may set stubAtCli to run once at the next cli(),
// as an interrupt that came just before it (test_nano.cpp's ATN race).
#pragma once
#define ISR(v) void v(void)
static void (*stubAtCli)() = 0;
static inline void stubCli() { if (stubAtCli) { void (*f)() = stubAtCli; stubAtCli = 0; f(); } }
#define cli() stubCli()
#define sei()
