// hal_sim.h -- the engine's GPIO access, redirected to the host simulation's bus model (sim/host/bus_sim.c).
#pragma once
#include <stdint.h>
uint32_t hal_in(void);
void hal_set(uint32_t m);
void hal_clr(uint32_t m);
void hal_oe_set(uint32_t m);
void hal_oe_clr(uint32_t m);
uint32_t hal_us(void);
