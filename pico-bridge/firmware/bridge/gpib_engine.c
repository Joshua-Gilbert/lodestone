// gpib_engine.c -- the GPIB device engine.  Runs alone on core 1 with interrupts off, from SRAM, so nothing can
// delay its response to ATN.  See gpib_engine.h for the pin map and the subsets.
//
// Timing rule (IEEE-488.1): within 200 ns of ATN going true a device must take part in the command handshake
// (NDAC asserted) and, if it was talking, stop driving DAV and the data lines.  Every wait loop below samples
// the GPIO inputs once per pass and tests ATN first; the response is one or two stores to the SIO.
// FIRMWARE.md gives the instruction count of the critical paths (from the compiled code) and how to scope it.
//
// Direction changes follow the board's turnaround rule (README "Notes for the real firmware"): to stop
// talking, transceiver TE low first, then the GPIOs become inputs; to start, output latches released-high
// first, then outputs, then TE high.  Overlaps cost ~3 mA through the 1 kOhm series resistors.
#include "gpib_engine.h"

#ifdef GPIB_SIM
#include "hal_sim.h"
#define RAMFUNC(f) f
#define INL static inline __attribute__((always_inline))
#define DMB() __atomic_thread_fence(__ATOMIC_SEQ_CST)
#else
#include "hardware/structs/sio.h"
#include "hardware/structs/timer.h"
#include "hardware/structs/systick.h"
#include "pico/platform.h"
#define RAMFUNC(f) __not_in_flash_func(f)
#define INL static inline __attribute__((always_inline))
#define DMB() __asm volatile("dmb" ::: "memory")
INL uint32_t hal_in(void) { return sio_hw->gpio_in; }
INL void hal_set(uint32_t m) { sio_hw->gpio_set = m; }
INL void hal_clr(uint32_t m) { sio_hw->gpio_clr = m; }
INL void hal_oe_set(uint32_t m) { sio_hw->gpio_oe_set = m; }
INL void hal_oe_clr(uint32_t m) { sio_hw->gpio_oe_clr = m; }
INL uint32_t hal_us(void) { return timer0_hw->timerawl; }   // RP2350 timer 0, as time_us_32()
#endif


shared_t SH;

enum { CFG_IDLE, CFG_ENGAGED, CFG_TALK };

// engine state (core 1 only)
static int cfg;
static bool online, listener, talker, spms, llo, rsv, rx_partial, talk_wait_sent, dav_hi_seen, nrfd_hi;
static uint8_t addr, stb;
static uint16_t gen;
static uint32_t req_seen, last_ifc_ren, rsv_seq_seen, rsv_served, session_seen;
static bool auto_rsv, reply_ready;
static uint32_t eoi_consumed, auto_served;              // auto mode: replies taken off the ring / announced
static bool bell;                                       // auto mode: the Pi rang (F_WAKE) for generation bell_gen
static uint16_t bell_gen;
static uint32_t bell_seen;
// The hold (F_HOLD): compared byte by byte as the message of its generation arrives
static uint32_t hold_seen;                              // SH.hold_seq last taken
static bool hold_cmp;                                   // this message may still be the one the hold expects
static bool hold_ok;                                    // it was: the held reply (this generation's) may go
static bool hold_rqs;                                   //  and RQS hasn't been served for it yet
static uint8_t hold_n, hold_kind, hold_exp[HOLD_MAX];
static uint32_t hold_pos, hold_end;                     // HOLD_GLP: bytes so far; the frame's length (8 + payload)
static uint8_t hold_a, hold_b;                          //  and its Fletcher sums so far (A = 1 + bytes, B = sum of A)

// ---- rings ----------------------------------------------------------------------------------------------------
INL uint32_t rx_free(void) { return (SH.rx_tail - SH.rx_head - 1u) & (RX_RING - 1u); }

INL void rx_push(uint8_t code, uint8_t b, uint32_t arg) {
  uint32_t h = SH.rx_head, n = (h + 1u) & (RX_RING - 1u);
  if (n == SH.rx_tail) { SH.ev_lost++; return; }
  SH.rx[h].code = code; SH.rx[h].b = b; SH.rx[h].gen = gen; SH.rx[h].arg = arg; SH.rx[h].t = hal_us();
  DMB();
  SH.rx_head = n;
}
#define EV(c) rx_push((c), 0, 0)

INL bool tx_peek(uint32_t *e) {
  uint32_t t = SH.tx_tail;
  if (t == SH.tx_head) return false;
  DMB();
  *e = SH.tx[t];
  return true;
}
INL void tx_pop(uint32_t e) {
  DMB();                                   // the slot is read before core 0 may reuse it
  SH.tx_tail = (SH.tx_tail + 1u) & (TX_RING - 1u);
  SH.tx_consumed++;
  if ((e >> 8) & TXF_EOI) {
    if (!((e >> 8) & TXE_HELD)) eoi_consumed++;   // a reply has left (sent, or dropped as stale)
    else if ((uint16_t)(e >> 16) == gen) hold_ok = false;   // (a held one was never in tx_eoi_pushed)
  }
}

// What to do with the entry at the ring's tail: send it, wait (leave it), or drop it as stale.  A held reply is
// for the next message: it waits until that message has come and matched (sent) or not (dropped).
enum { TXC_SEND, TXC_WAIT, TXC_DROP };
INL int tx_class(uint32_t e) {
  int16_t d = (int16_t)((uint16_t)(e >> 16) - gen);
  if (d < 0) return TXC_DROP;                           // queued before a clear or a newer message
  if (d > 0) return TXC_WAIT;                           // held for the next message
  if (!((e >> 8) & TXE_HELD) || hold_ok) return TXC_SEND;
  return (rx_partial && hold_cmp) ? TXC_WAIT : TXC_DROP;  // its message still arriving / it didn't match
}

// ---- bus configurations ---------------------------------------------------------------------------------------
// Idle / listen: TE_C = TE_D = PE = 0.  U3 sends NRFD, NDAC, SRQ to the bus (GPIO outputs) and receives ATN, EOI,
// DAV, IFC, REN; U2 receives DIO.  engage = NDAC asserted (taking part, nothing accepted yet), NRFD released (ready).
INL void cfg_listen(bool engage) {
  hal_clr(TEC_M | TED_M | PE_M);
  hal_oe_clr(DIO_M | DAV_M | EOI_M);
  hal_set(NRFD_M | (engage ? 0 : NDAC_M));
  if (engage) hal_clr(NDAC_M);
  hal_oe_set(NRFD_M | NDAC_M);
  nrfd_hi = true;
  cfg = engage ? CFG_ENGAGED : CFG_IDLE;
}

// The ATN path.  From idle the first store alone asserts NDAC (NDAC is already an output).  From talk it also
// drops all three TE/PE at once; NRFD/NDAC latches are pre-set (1/0) by cfg_talk, so the next store finishes it.
INL void engage_fast(void) {
  hal_clr(TEC_M | TED_M | PE_M | NDAC_M);
  hal_oe_set(NRFD_M | NDAC_M);
  hal_oe_clr(DIO_M | DAV_M | EOI_M);
  hal_set(DIO_M | DAV_M | EOI_M);          // latches released for the next talk
  nrfd_hi = true;
  dav_hi_seen = false;                     // a DAV already low belongs to someone else's data byte
  cfg = CFG_ENGAGED;
}

// Talk: U2/U3 send DIO, DAV, EOI (totem-pole), receive NRFD/NDAC.  SRQ stays an output (DC = 1).
INL void cfg_talk(void) {
  hal_set(DIO_M | DAV_M | EOI_M | NRFD_M);
  hal_clr(NDAC_M);                         // pre-set for engage_fast (NDAC is an input while talking)
  hal_oe_set(DIO_M | DAV_M | EOI_M);
  hal_oe_clr(NRFD_M | NDAC_M);
  hal_set(PE_M);
  hal_set(TEC_M | TED_M);
  cfg = CFG_TALK;
}

static bool srq_on;
INL void set_srq(void) {                               // (quiet read as it is now: no window after a CONFIG)
  if (rsv && online && !SH.quiet) { hal_clr(SRQ_M); if (!srq_on) { srq_on = true; EV(E_SRQ); } }
  else { hal_set(SRQ_M); srq_on = false; }
}

// Auto mode: READY while a complete reply waits, RQS once for each new one.
INL void auto_status(void) {
  if (!auto_rsv) return;
  uint32_t pushed = SH.tx_eoi_pushed;
  reply_ready = pushed != eoi_consumed || hold_ok;
  if (bell && bell_gen != gen) bell = false;            // the 1520 has sent since: it is awake
  rsv = (reply_ready && pushed != auto_served) || (hold_ok && hold_rqs) || bell;
  SH.cur_rsv = rsv;
  set_srq();
}

// ---- state changes --------------------------------------------------------------------------------------------
INL void hold_void(void) { if (hold_cmp) { hold_cmp = false; SH.n_held_void++; } }

INL void end_partial(void) {                     // the 1520 unaddressed us mid-message: that ends the message
  if (rx_partial) { hold_void(); rx_push(R_END, 0, 0); rx_partial = false; }
}

INL void drop_partial(void) {                    // IFC, going offline: a half message is thrown away, not ended
  if (rx_partial) { hold_void(); rx_partial = false; gen++; hold_ok = false; }   // (the Pi drops its partial on
}                                                // the IFC/OFFLINE event)

INL void unaddress(void) {
  if (listener) { listener = false; EV(E_UNLISTEN); }
  if (talker) { talker = false; EV(E_UNTALK); }
  spms = false;
}

INL void device_clear(uint8_t code) {
  if (rx_partial) hold_void();
  rx_partial = false;                      // the Pi drops what it has of the message
  gen++;                                   // replies queued before the clear become stale
  hold_ok = false;
  talk_wait_sent = false;
  if (bell) auto_status();
  EV(code);
}

static void RAMFUNC(do_cmd)(uint8_t c) {
  c &= 0x7F;
  uint8_t a = c & 0x1F;
  SH.n_cmd++;
  if (c >= 0x20 && c <= 0x3E) {                          // MLA / other listen address
    if (a == addr) {
      if (talker) { talker = false; EV(E_UNTALK); }      // L4/T6: never both
      if (!listener) { listener = true; EV(E_LISTEN); }
    }
  } else if (c == 0x3F) {                                // UNL
    if (listener) { end_partial(); listener = false; EV(E_UNLISTEN); }
  } else if (c >= 0x40 && c <= 0x5E) {                   // MTA / OTA
    if (a == addr) {
      if (listener) { end_partial(); listener = false; EV(E_UNLISTEN); }
      if (!talker) { talker = true; EV(E_TALK); }
      talk_wait_sent = false;
    } else if (talker) { talker = false; EV(E_UNTALK); }
  } else if (c == 0x5F) {                                // UNT
    if (talker) { talker = false; EV(E_UNTALK); }
  } else if (c >= 0x60) {
    // secondary address: not used by this device
  } else switch (c) {
    case 0x01: if (listener) EV(E_GTL); break;           // GTL
    case 0x04: if (listener) device_clear(E_SDC); break; // SDC
    case 0x08: if (listener) EV(E_GET); break;           // GET
    case 0x11: if (SH.ren) { llo = true; EV(E_LLO); } break;   // LLO (only means something with REN)
    case 0x14: device_clear(E_DCL); break;               // DCL
    case 0x18: spms = true; break;                       // SPE
    case 0x19: spms = false; break;                      // SPD
    default: break;                                      // PPC, PPU, TCT, ...: not implemented (PP0, C0)
  }
}

// A new message: is there a hold for it?  (Taken once: a hold is for one message.)  hold_seq is a sequence lock:
// odd while core 0 writes, so a hold read while it changes is no hold.
INL void hold_take(void) {
  uint32_t q = SH.hold_seq;
  if (q == hold_seen || (q & 1u)) return;
  DMB();
  uint8_t n = SH.hold_n, k = SH.hold_kind;
  bool mine = SH.hold_gen == gen && n && n <= HOLD_MAX && (k == HOLD_EXACT || (k == HOLD_GLP && n == 4));
  if (mine) for (uint32_t i = 0; i < n; i++) hold_exp[i] = SH.hold_exp[i];
  DMB();
  if (SH.hold_seq != q) return;                         // rewritten meanwhile: look again at the next message
  hold_seen = q;
  if (!mine) { SH.n_held_void++; return; }             // too late (or after a clear): its reply will be dropped
  hold_n = n; hold_kind = k; hold_pos = 0; hold_cmp = true;
  hold_a = 1; hold_b = 0; hold_end = 8;
}

// HOLD_GLP, one byte: the 4 bytes expected, the length (its frame ends 8 bytes after it), the payload, then the
// Fletcher sum of all but the sync byte, A then B, with EOI on B.  False: it isn't the frame expected.
INL bool hold_glp_byte(uint8_t b, bool eoi) {
  uint32_t p = hold_pos++;
  if (p == 0) return b == hold_exp[0] && !eoi;          // (the sync byte: not in the sum)
  if (p < 4 && b != hold_exp[p]) return false;
  if (p == 4) hold_end = b;                             // (the length's low byte, for now)
  else if (p == 5) {
    hold_end = 8u + (hold_end | ((uint32_t)b << 8));
    if (hold_end > 8u + HOLD_GLP_MAX) return false;
  } else if (p > 5 && p + 2u >= hold_end) {             // the check
    if (p + 2u == hold_end) return b == hold_a && !eoi;
    return p + 1u == hold_end && b == hold_b && eoi;    // (EOI with the last byte, and nothing after it)
  }
  hold_a += b; hold_b += hold_a;
  return !eoi;
}

INL void got_data(uint8_t b, bool eoi) {
  uint32_t arg = eoi ? 1u : 0u;
  if (!rx_partial) {                                    // a new message voids the old reply (and a ring)
    gen++; rx_partial = true; talk_wait_sent = false;
    hold_ok = false; hold_cmp = false;
    hold_take();
    if (bell) auto_status();
  }
  if (hold_cmp) {
    bool good, done;
    if (hold_kind == HOLD_GLP) { good = hold_glp_byte(b, eoi); done = good && eoi; }
    else {
      good = hold_pos < hold_n && b == hold_exp[hold_pos];
      hold_pos++;
      done = good && eoi && hold_pos == hold_n;
      if (good && eoi && !done) good = false;           // (a shorter message)
    }
    if (!good) hold_void();
    else if (done) { hold_cmp = false; hold_ok = hold_rqs = true; SH.n_held++; arg |= 2u; }
  }
  rx_push(R_DATA, b, arg);
  SH.n_rx++;
  if (eoi) { rx_partial = false; if (hold_ok) auto_status(); }   // SRQ for the held reply now
}

// Mid-byte, only IFC, ATN or the Pi taking the bridge offline may interrupt a handshake.  (Other requests --
// a TX frame, SRQ -- wait for the byte to finish: breaking off with DAV or NDAC half done would lose or
// repeat a byte.)
INL bool going_offline(void) { return SH.req_seq != req_seen && !SH.want_online; }

// ---- acceptor handshake: one byte (command or data), or a return when something else needs the main loop --------
static void RAMFUNC(accept)(void) {
  uint32_t g;
  bool atn_was = true;
  for (;;) {
    g = hal_in();
    if (!(g & IFC_M)) return;
    bool atn = !(g & ATN_M);
    if (!atn && !listener) return;
    if (SH.req_seq != req_seen || (g & (IFC_M | REN_M)) != last_ifc_ren) return;   // main loop first
    if (atn != atn_was) { atn_was = atn; if (atn) dav_hi_seen = false; }  // ATN just came: a low DAV is a
    if (g & DAV_M) dav_hi_seen = true;                                    // talker's, not a command
    if (!dav_hi_seen) continue;                         // wait for a fresh DAV
    if (!nrfd_hi) {                                     // not ready: only for data with the Pi's ring full
      if (atn || rx_free() > RX_RESERVE) { hal_set(NRFD_M); nrfd_hi = true; }
      continue;                                         // re-sample: DAV can only follow our NRFD
    }
    if (!(g & DAV_M)) break;                            // data valid
  }
  hal_clr(NRFD_M); nrfd_hi = false;                     // not ready for the next one
  uint8_t b = (uint8_t)(~g & DIO_M);                    // active low
  bool eoi = !(g & EOI_M), atn = !(g & ATN_M);
  hal_set(NDAC_M);                                      // accepted
  dav_hi_seen = false;
  for (;;) {                                            // wait for the source to release DAV
    uint32_t g2 = hal_in();
    if (g2 & DAV_M) { dav_hi_seen = true; break; }
    if (!(g2 & IFC_M) || going_offline()) break;        // (not for other requests: this byte is half done)
  }
  hal_clr(NDAC_M);                                      // NDAC asserted again for the next byte
  if (atn) do_cmd(b);
  else if (listener) got_data(b, eoi);
  // Ready again: for a command at once, for data if the ring has room (checked at the top).
  if (atn || rx_free() > RX_RESERVE) { hal_set(NRFD_M); nrfd_hi = true; }
  else SH.rx_holds++;                                   // the Pi is behind: NRFD held until it catches up
}

// ---- waiting with nothing driven -------------------------------------------------------------------------------
// The tightest loop in the engine.  With react_atn, on ATN its very next store asserts NDAC (and drops TE/PE,
// already low here); engage_fast then finishes the job.  Returns when *watch changes, IFC/REN change, or (with
// react_atn) on ATN.  FIRMWARE.md has the compiled loop and its cycle count.
static void RAMFUNC(spin)(bool react_atn, volatile uint32_t *watch) {
  uint32_t r = *watch, l = last_ifc_ren;
  if (react_atn) {
#ifdef GPIB_SIM
    uint32_t g;
    for (;;) {
      g = hal_in(); if (!(g & ATN_M)) break;
      if ((g & (IFC_M | REN_M)) != l || *watch != r) return;
    }
    hal_clr(TEC_M | TED_M | PE_M | NDAC_M);
#else
    // Four ATN samples for each look at IFC/REN and the watched counter.  On ATN: one taken branch, then the
    // store to SIO GPIO_CLR (offset 0x20) that asserts NDAC and drops TE_C/PE/TE_D.  Written in assembly so the
    // compiler can't put work between the test and the store.
    uint32_t g, t, hit;
    __asm volatile(
      "1:  ldr  %[g], [%[sio], #4]   \n\t"   // SIO GPIO_IN
      "    tst  %[g], #0x200         \n\t"   // ATN (GP9) low?
      "    beq  2f                   \n\t"
      "    ldr  %[g], [%[sio], #4]   \n\t"
      "    tst  %[g], #0x200         \n\t"
      "    beq  2f                   \n\t"
      "    ldr  %[g], [%[sio], #4]   \n\t"
      "    tst  %[g], #0x200         \n\t"
      "    beq  2f                   \n\t"
      "    ldr  %[g], [%[sio], #4]   \n\t"
      "    tst  %[g], #0x200         \n\t"
      "    beq  2f                   \n\t"
      "    and  %[t], %[g], #0xC000  \n\t"   // IFC, REN
      "    cmp  %[t], %[l]           \n\t"
      "    bne  3f                   \n\t"
      "    ldr  %[t], [%[w]]         \n\t"   // the watched counter
      "    cmp  %[t], %[r]           \n\t"
      "    beq  1b                   \n\t"
      "3:  movs %[hit], #0           \n\t"
      "    b    4f                   \n\t"
      "2:  str  %[m], [%[sio], #32]  \n\t"   // SIO GPIO_CLR: NDAC asserted, TE/PE low
      "    movs %[hit], #1           \n\t"
      "4:                            \n\t"
      : [g] "=&r"(g), [t] "=&r"(t), [hit] "=&r"(hit)
      : [sio] "r"(SIO_BASE), [m] "r"(TEC_M | TED_M | PE_M | NDAC_M), [l] "r"(l), [w] "r"(watch), [r] "r"(r)
      : "cc", "memory");
    if (!hit) return;
#endif
    engage_fast();
    return;
  }
  for (;;) {                                            // offline, or IFC asserted: ATN is not ours to answer
    uint32_t g = hal_in();
    if ((g & (IFC_M | REN_M)) != l || *watch != r) return;
    SH.engine_alive++;                                  // shows core 1 is running
  }
}

// ---- source handshake: the bytes of a reply, or a serial poll's status byte -------------------------------------
// T1, the settling time from the data lines to DAV.  IEEE-488.1 asks 2 us of an open-collector source and 1.1 us
// of a three-state one, which this bridge is for its own bytes (U2 PE high, U3 drives DAV and EOI totem-pole).
// On the Pico it is timed on core 1's SysTick, which counts CPU cycles: t1_cycles (engine_timing_init) is
// 1.1 us at the clock the build runs at, rounded up.  Before 2026-10-21 it was 2-3 us on the 1 us timer.
#define T1_NS 1100u
static uint32_t t1_cycles = 1000u;

void engine_timing_init(uint32_t sys_hz) {     // core 1, before engine_run (not in SRAM: it runs once)
  t1_cycles = (uint32_t)(((uint64_t)sys_hz * T1_NS + 999999999u) / 1000000000u) + 1u;
#ifndef GPIB_SIM
  systick_hw->rvr = 0x00FFFFFFu;               // free-running, 24 bits
  systick_hw->cvr = 0;
  systick_hw->csr = 0x5u;                      // enabled, processor clock, no interrupt
#endif
}

// One byte out: false if ATN, IFC or a request broke it off before the listeners accepted it (the caller
// leaves it queued).  After it, DAV, EOI and DIO are released again (or ATN took us to engaged).
static bool RAMFUNC(send_byte)(uint8_t b, bool eoi) {
  uint32_t g;
  for (;;) {                                            // wait for every listener ready: NRFD high, NDAC low
    g = hal_in();
    if (!(g & ATN_M)) { engage_fast(); return false; }
    if (!(g & IFC_M) || SH.req_seq != req_seen) return false;   // nothing asserted yet: safe to leave
    if ((g & NRFD_M) && !(g & NDAC_M)) break;
  }
  hal_set(DIO_M & (uint32_t)~b);
  hal_clr((uint32_t)b | (eoi ? EOI_M : 0));
#ifdef GPIB_SIM
  uint32_t t0 = hal_us();
  for (;;) {                                            // (the model has no cycles: 2 us on its clock)
    g = hal_in();
    if (!(g & ATN_M)) { engage_fast(); return false; }
    if (hal_us() - t0 >= 2u) break;
  }
#else
  uint32_t t0 = systick_hw->cvr;                        // settling time T1, watching ATN (SysTick counts down)
  for (;;) {
    g = hal_in();
    if (!(g & ATN_M)) { engage_fast(); return false; }
    if (((t0 - systick_hw->cvr) & 0x00FFFFFFu) >= t1_cycles) break;
  }
#endif
  hal_clr(DAV_M);
  for (;;) {                                            // wait for data accepted: NDAC high
    g = hal_in();
    if (g & NDAC_M) break;                              // accepted (even if ATN came in the same sample)
    if (!(g & ATN_M)) { engage_fast(); return false; }  // not accepted: the byte stays queued
    if (!(g & IFC_M) || going_offline()) { hal_set(DAV_M | EOI_M | DIO_M); return false; }
  }
  if (!(g & ATN_M)) engage_fast();                      // ATN with the acceptance: stop driving first
  else hal_set(DAV_M | EOI_M | DIO_M);
  return true;
}

static void RAMFUNC(talk)(void) {
  uint32_t e = 0;
  if (spms) {                                           // serial poll: the status byte
    uint8_t b;
    uint32_t pushed_used = SH.tx_eoi_pushed;
    if (auto_rsv) { auto_status(); b = (uint8_t)((stb & 0x9F) | (reply_ready ? 0x20 : 0) | (rsv ? 0x40 : 0)); }
    else b = (uint8_t)((stb & 0xBF) | (rsv ? 0x40 : 0));
    uint32_t rsv_seq_used = rsv_seq_seen;
    if (cfg != CFG_TALK) cfg_talk();
    if (!send_byte(b, false)) return;
    SH.n_polls++;
    rx_push(E_SPOLL, b, 0);
    if (b & 0x40) {                                     // the request is served
      rsv = false; SH.cur_rsv = 0; bell = false;
      if (auto_rsv) { auto_served = pushed_used; hold_rqs = false; } else rsv_served = rsv_seq_used;
      set_srq();
    }
    return;
  }
  for (;;) {                                            // the reply, byte after byte while nothing else happens
    for (;;) {
      if (!tx_peek(&e)) {
        if (!talk_wait_sent) { rx_push(E_TALK_WAIT, 0, SH.tx_consumed); talk_wait_sent = true; }
        if (cfg != CFG_IDLE) cfg_listen(false);         // nothing to send: drive nothing while waiting
        spin(true, &SH.wake_seq);                       // returns on ATN (engaged), IFC/REN, a request or a
        return;                                         // TX frame (core 0 bumps wake_seq for both)
      }
      int c = tx_class(e);
      if (c == TXC_SEND) break;
      if (c == TXC_WAIT) {                              // (only a held reply, for a message still to come)
        if (!talk_wait_sent) { rx_push(E_TALK_WAIT, 0, SH.tx_consumed); talk_wait_sent = true; }
        if (cfg != CFG_IDLE) cfg_listen(false);
        spin(true, &SH.wake_seq);
        return;
      }
      tx_pop(e);                                        // stale: queued before a clear or a new message
      auto_status();
    }
    bool eoi = (e >> 8) & TXF_EOI;
    if (cfg != CFG_TALK) cfg_talk();
    if (!send_byte((uint8_t)e, eoi)) return;
    tx_pop(e);
    SH.n_tx++;
    if (eoi) { rx_push(E_TX_DONE, 0, 0); talk_wait_sent = true; auto_status(); return; }   // the reply is complete
    // Straight on to the next byte unless the main loop has something to see: ATN, IFC or REN changing, a
    // request from core 0.  (Before 2026-10-21 every byte went round the main loop.)
    uint32_t g = hal_in();
    if (!(g & ATN_M)) { engage_fast(); return; }
    if ((g & (IFC_M | REN_M)) != last_ifc_ren || SH.req_seq != req_seen || cfg != CFG_TALK) return;
  }
}

// ---- requests from core 0 -------------------------------------------------------------------------------------
static void RAMFUNC(go_offline_now)(void) {
  drop_partial();
  unaddress();
  online = false;
  rsv = false;
  EV(E_OFFLINE);
}

static void RAMFUNC(apply_requests)(void) {
  req_seen = SH.req_seq;
  DMB();
  bool want = SH.want_online;
  uint8_t a = SH.addr;
  stb = SH.stb;
  rsv_seq_seen = SH.rsv_seq;
  auto_rsv = SH.auto_rsv;
  // A service request is asserted once per STB-with-rsv from the Pi, and stays served after the poll.
  rsv = SH.rsv && rsv_seq_seen != rsv_served;
  if (SH.session_seq != session_seen) {                 // the Pi started a new session: start clean
    session_seen = SH.session_seq;
    if (online) go_offline_now();
  }
  if (want && (!online || a != addr)) {
    if (online) { drop_partial(); unaddress(); }
    if (!online) { gen++; hold_ok = false; }            // a new session: whatever is left in the tx ring is stale
    addr = a; online = true;
    rx_push(E_ONLINE, addr, (last_ifc_ren & REN_M) ? 0u : 1u);
  } else if (!want && online) {
    go_offline_now();
  }
  if (!online && cfg != CFG_IDLE) cfg_listen(false);
  if (SH.bell_seq != bell_seen) {                       // the Pi rang: SRQ until the 1520 sends or polls
    bell_seen = SH.bell_seq;
    DMB();
    bell_gen = SH.bell_gen;
    bell = online && auto_rsv;
  }
  if (!online) { rsv = false; bell = false; }
  set_srq();
  SH.online = online; SH.cur_rsv = rsv;
  auto_status();
}

static void RAMFUNC(bus_lines)(uint32_t g) {
  uint32_t s = g & (IFC_M | REN_M);
  if (s == last_ifc_ren) return;
  uint32_t ch = s ^ last_ifc_ren;
  last_ifc_ren = s;
  if (g & REN_M) llo = false;                           // REN false clears local lockout
  if (!online) return;
  if ((ch & IFC_M) && !(g & IFC_M)) { drop_partial(); unaddress(); EV(E_IFC); }
  if (ch & REN_M) rx_push(E_REN, 0, (g & REN_M) ? 0u : 1u);
}

INL void publish(uint32_t g) {                          // status for core 0's reports
  SH.listener = listener; SH.talker = talker; SH.spms = spms; SH.llo = llo; SH.gen = gen;
  SH.ren = !(g & REN_M);
  SH.engine_alive++;
}

void RAMFUNC(engine_run)(void) {
  cfg_listen(false);
  hal_set(SRQ_M);
  last_ifc_ren = hal_in() & (IFC_M | REN_M);
  session_seen = SH.session_seq;
  hold_seen = SH.hold_seq & ~1u;
  req_seen = SH.req_seq - 1u;                           // apply the first requests at once
  for (;;) {
#ifdef GPIB_SIM
    if (sim_stop) return;
#endif
    uint32_t g = hal_in();
    if (online && !(g & ATN_M) && (g & IFC_M)) {        // ATN first, always
      if (cfg != CFG_ENGAGED) engage_fast();
      // The controller may hold ATN for as long as it likes between commands: REN, IFC and the Pi's requests
      // (SRQ, address, offline) are handled here too, while engaged.
      if ((g & (IFC_M | REN_M)) != last_ifc_ren) bus_lines(g);
      if (SH.req_seq != req_seen) apply_requests();
      publish(g);
      if (online) accept();
      continue;
    }
    // the slow path: between bytes, never while ATN waits
    if ((g & (IFC_M | REN_M)) != last_ifc_ren) bus_lines(g);
    if (SH.req_seq != req_seen) apply_requests();
    publish(g);
    for (int k = 0; k < 8; k++) {                       // drop stale replies, a few at a time (core 0 drops
      uint32_t e;                                       // most of them before they reach the ring)
      if (!tx_peek(&e) || tx_class(e) != TXC_DROP) break;
      tx_pop(e);
      auto_status();
    }
    if (!online || !(g & IFC_M)) {
      if (cfg != CFG_IDLE) cfg_listen(false);
      spin(false, &SH.req_seq);                         // offline or in IFC: take no part, not even in ATN
    } else if (!(g & ATN_M)) {
      continue;
    } else if (listener) {
      if (cfg != CFG_ENGAGED) cfg_listen(true);
      accept();
    } else if (talker) {
      talk();
    } else {
      if (cfg != CFG_IDLE) cfg_listen(false);           // ATN false and not addressed: take no part
      uint32_t e;
      if (tx_peek(&e) && tx_class(e) == TXC_DROP) continue;   // more stale entries to drop first
      spin(true, &SH.req_seq);
    }
  }
}
