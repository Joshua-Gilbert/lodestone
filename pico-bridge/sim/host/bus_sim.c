// bus_sim.c -- host simulation of the GPIB-Pico2 bridge on a GPIB bus.
//
// Compiles the real firmware files (gpib_engine.c = core 1, host_link.c = core 0) for Linux with a model of the
// board between them and the bus:
//   * the Pico's GPIO latches/output enables, the 1 kOhm-isolated U2 SN75160B and U3 SN75161B (DC = 1) with their
//     direction rules (TE_D, TE_C, PE; EOI steered by ATN when TE_C = 1), R1-R3 pull-downs on TE/PE, R4-R6
//     pull-ups on SRQ/NRFD/NDAC, wired-OR open-collector bus lines;
//   * a controller (the 1520's role) driven by line commands on stdin, with the GRIDGPIB-style calls THRUTEST uses;
//   * a second instrument at address 5 (an acceptor/talker like the DM5120), so traffic to someone else is on the
//     same bus as the bridge.
// Core 0's USB is a pseudo-terminal: the Pi daemon (pi/gpibbridge) opens the slave end exactly as it would open
// /dev/ttyACM0.
//
// Timing is not modelled (threads, not nanoseconds): this checks the logic -- handshakes, addressing, the
// protocol, flow control, the offline behaviour.  The ATN response time is checked from the compiled code.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>
#include <sched.h>
#include "gpib_engine.h"
#include "host_link.h"

volatile int sim_stop = 0;

// ---- the board ------------------------------------------------------------------------------------------------
static _Atomic uint32_t b_out = 0, b_oe = 0;
static _Atomic uint32_t c_assert = 0, d_assert = 0;    // lines the controller / device 5 pull low (pin-number bits)
static _Atomic uint32_t contention = 0;
#define GPIB_LINES 0xFFFFu

static uint32_t now_us(void) {
  struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
  return (uint32_t)(t.tv_sec * 1000000ull + t.tv_nsec / 1000);
}
static uint32_t now_ms(void) { return now_us() / 1000u; }

static uint32_t pin_levels(void) {          // what each Pico pin would be at, as an output or pulled
  uint32_t out = b_out, oe = b_oe;
  uint32_t lv = (out & oe) | (~oe & (GPIB_LINES));          // undriven GPIB-side pins: pulled or floating high
  lv &= ~(~oe & (TEC_M | PE_M | TED_M));                    // R1-R3 hold TE/PE low when not driven
  lv |= out & oe & (TEC_M | PE_M | TED_M);
  return lv;
}

static uint32_t bridge_assert_from(uint32_t lv, uint32_t others) {
  uint32_t a = 0, low = ~lv;
  bool tec = lv & TEC_M, ted = lv & TED_M;
  bool atn = others & ATN_M;
  if (ted) a |= low & DIO_M;
  if (tec) { a |= low & DAV_M; if (!atn) a |= low & EOI_M; }
  else a |= low & (NRFD_M | NDAC_M);
  a |= low & SRQ_M;
  return a;
}
static uint32_t bridge_assert(void) { return bridge_assert_from(pin_levels(), c_assert | d_assert); }
static uint32_t bus_asserted(void) { uint32_t o = c_assert | d_assert; return o | bridge_assert_from(pin_levels(), o); }

uint32_t hal_in(void) {
  uint32_t lv = pin_levels(), out = b_out, oe = b_oe;
  uint32_t others = c_assert | d_assert;
  uint32_t busA = others | bridge_assert_from(lv, others);
  uint32_t bus = ~busA & GPIB_LINES;
  bool tec = lv & TEC_M, ted = lv & TED_M, atn = busA & ATN_M;
  uint32_t rx = ATN_M | IFC_M | REN_M;
  if (!ted) rx |= DIO_M;
  if (!tec) rx |= DAV_M | EOI_M;
  else { rx |= NRFD_M | NDAC_M; if (atn) rx |= EOI_M; }
  uint32_t in = 0;
  in |= out & oe;
  in |= ~oe & rx & bus;
  in |= ~oe & ~rx & GPIB_LINES;
  in |= lv & (TEC_M | PE_M | TED_M);
  uint32_t fight = oe & rx & GPIB_LINES & (out ^ bus);
  if (fight) contention++;
  return in;
}
void hal_set(uint32_t m) { b_out |= m; }
void hal_clr(uint32_t m) { b_out &= ~m; }
void hal_oe_set(uint32_t m) { b_oe |= m; }
void hal_oe_clr(uint32_t m) { b_oe &= ~m; }
uint32_t hal_us(void) { return now_us(); }

static bool line_low(uint32_t m) { return bus_asserted() & m; }

// ---- core 0 glue: the pty is the USB CDC port ------------------------------------------------------------------
static int pty_master = -1;
static atomic_bool host_open = false;

static _Atomic uint32_t sim_stall_until = 0;      // "usbstall MS": the USB host takes no data for MS ms
size_t link_write_some(const uint8_t *b, size_t n) {
  if (!host_open || (int32_t)(now_ms() - sim_stall_until) < 0) return 0;
  ssize_t k = write(pty_master, b, n);
  return k > 0 ? (size_t)k : 0;
}
void link_bootsel(void) { fprintf(stderr, "[sim] BOOTSEL requested\n"); }

static void *core0(void *arg) {
  (void)arg;
  uint8_t buf[512];
  link_init();
  while (!sim_stop) {
    struct pollfd p = {pty_master, POLLIN, 0};
    int r = poll(&p, 1, 1);
    if (r > 0 && (p.revents & POLLIN)) {
      ssize_t k = read(pty_master, buf, sizeof buf);
      if (k > 0) { host_open = true; link_input(buf, (size_t)k, now_ms()); }
    }
    if (r > 0 && (p.revents & POLLHUP)) { host_open = false; usleep(2000); }
    link_poll(now_ms(), host_open);
  }
  return NULL;
}

static void *core1(void *arg) { (void)arg; engine_run(); return NULL; }

// ---- device 5: another instrument on the bus ------------------------------------------------------------------
#define DEV_ADDR 5
static uint8_t dev_last[4096]; static _Atomic int dev_last_len = 0;
static _Atomic int dev_cmds = 0;
static const char DEV_REPLY[] = "+1.234567E+00\n";

static void dset(uint32_t m, bool assert) { if (assert) d_assert |= m; else d_assert &= ~m; }

static void *device5(void *arg) {
  (void)arg;
  bool listener = false, talker = false;
  uint8_t msg[4096]; int len = 0; int txpos = 0;
  while (!sim_stop) {
    uint32_t A = bus_asserted();
    bool atn = A & ATN_M;
    if (A & IFC_M) { listener = talker = false; dset(NRFD_M | NDAC_M | DAV_M | EOI_M | DIO_M, false); continue; }
    if (atn || listener) {
      dset(DAV_M | EOI_M | DIO_M, false);
      dset(NDAC_M, true); dset(NRFD_M, false);             // engaged, ready
      // wait DAV low, or the reason to take part going away
      for (;;) {
        A = bus_asserted();
        if (sim_stop || (A & IFC_M)) break;
        if (!(A & ATN_M) && !listener) break;
        if (A & DAV_M) break;
      }
      if (!(A & DAV_M)) { if (!(A & ATN_M) && !listener) dset(NRFD_M | NDAC_M, false); continue; }
      uint8_t b = (uint8_t)(A & DIO_M); bool eoi = A & EOI_M; bool cmd = A & ATN_M;
      dset(NRFD_M, true); dset(NDAC_M, false);
      while (!sim_stop && (bus_asserted() & DAV_M)) {}
      dset(NDAC_M, true);
      if (cmd) {
        uint8_t c = b & 0x7F, a = c & 0x1F; dev_cmds++;
        if (c >= 0x20 && c <= 0x3E && a == DEV_ADDR) { listener = true; talker = false; }
        else if (c == 0x3F) { if (listener && len) { memcpy(dev_last, msg, len); dev_last_len = len; len = 0; } listener = false; }
        else if (c >= 0x40 && c <= 0x5E) { if (a == DEV_ADDR) { talker = true; listener = false; txpos = 0; } else talker = false; }
        else if (c == 0x5F) talker = false;
      } else if (listener) {
        if (len < (int)sizeof msg) msg[len++] = b;
        if (eoi) { memcpy(dev_last, msg, len); dev_last_len = len; len = 0; }
      }
      dset(NRFD_M, false);
      continue;
    }
    dset(NRFD_M | NDAC_M, false);
    if (talker && txpos < (int)strlen(DEV_REPLY)) {
      // wait listeners ready
      A = bus_asserted();
      if (!(A & NRFD_M) && (A & NDAC_M)) {
        uint8_t b = (uint8_t)DEV_REPLY[txpos];
        bool last = txpos == (int)strlen(DEV_REPLY) - 1;
        dset(DIO_M, false); dset(b, true); dset(EOI_M, last);
        dset(DAV_M, true);
        for (;;) { A = bus_asserted(); if (sim_stop || (A & ATN_M) || !(A & NDAC_M)) break; }
        bool accepted = !(A & NDAC_M);
        dset(DAV_M | EOI_M | DIO_M, false);
        if (accepted) txpos++;
      }
    }
  }
  return NULL;
}

// ---- the controller --------------------------------------------------------------------------------------------
#define MY_ADDR 21
static uint32_t tmo_ms = 2000;
static atomic_bool late_engage = false;

static void cset(uint32_t m, bool assert) { if (assert) c_assert |= m; else c_assert &= ~m; }

// Source handshake, one byte.  0 ok, 1 timeout, 2 no listener.
static int c_send(uint8_t b, bool eoi, bool atn) {
  uint32_t t0 = now_ms();
  for (;;) {                                         // wait NRFD high (all ready)
    uint32_t A = bus_asserted();
    if (!(A & NRFD_M)) { if (!(A & NDAC_M)) return 2; break; }
    if (now_ms() - t0 > tmo_ms) return 1;
  }
  cset(DIO_M, false); cset(b, true); cset(EOI_M, eoi && !atn);
  usleep(5);
  if (atn && SH.online && !(bridge_assert() & NDAC_M) && !(bridge_assert() & NRFD_M)) {
    late_engage = true;
    fprintf(stderr, "[sim] bridge online but not engaged at command byte 0x%02X\n", b);
  }
  cset(DAV_M, true);
  int r = 0;
  t0 = now_ms();
  while (bus_asserted() & NDAC_M) { if (now_ms() - t0 > tmo_ms) { r = 1; break; } }
  cset(DAV_M | EOI_M | DIO_M, false);
  return r;
}

static int c_cmds(const uint8_t *c, int n) {
  cset(ATN_M, true);
  // A real controller waits T7/T1 (microseconds); the threads here may not be scheduled that fast, so allow the
  // acceptors up to 20 ms to take part.  Logic, not timing, is what this simulation checks.
  uint32_t t0 = now_ms();
  while (!(bus_asserted() & NDAC_M) && now_ms() - t0 < 20) sched_yield();
  while (SH.online && !(bridge_assert() & NDAC_M) && now_ms() - t0 < 20) sched_yield();   // the bridge too
  usleep(200);
  for (int i = 0; i < n; i++) { int r = c_send(c[i], false, true); if (r) return r; }
  return 0;
}

// Acceptor handshake, as the controller-listener.  Returns bytes read; *end: 1 EOI, 4 count, 8 timeout
static int c_recv(uint8_t *buf, int max, int *end) {
  int n = 0; *end = 4;
  cset(NDAC_M, true); cset(NRFD_M, false);
  while (n < max) {
    uint32_t t0 = now_ms();
    while (!(bus_asserted() & DAV_M)) { if (now_ms() - t0 > tmo_ms) { *end = 8; goto done; } }
    uint32_t A = bus_asserted();
    buf[n++] = (uint8_t)(A & DIO_M);
    bool eoi = A & EOI_M;
    cset(NRFD_M, true); cset(NDAC_M, false);
    t0 = now_ms();
    while (bus_asserted() & DAV_M) { if (now_ms() - t0 > tmo_ms) { *end = 8; goto done; } }
    cset(NDAC_M, true);
    if (eoi) { *end = 1; break; }
    cset(NRFD_M, false);
  }
done:
  cset(NRFD_M | NDAC_M, false);
  return n;
}


static int c_write(int addr, const uint8_t *d, int n, bool eoi, int *sent) {
  // The exact sequences of the 1520's INT 60h driver (GRIDGPIB 1.1 / Lodestone 1.20, from its disassembly, as
  // modelled in tools/grid/harness.py): write = UNL, MTA 21, MLA a ... UNT, UNL.
  uint8_t cmd[3] = {0x3F, (uint8_t)(0x40 | MY_ADDR), (uint8_t)(0x20 | addr)};
  *sent = 0;
  int r = c_cmds(cmd, 3);
  if (r) { cset(ATN_M, false); return r; }
  cset(ATN_M, false);
  for (int i = 0; i < n; i++) { r = c_send(d[i], eoi && i == n - 1, false); if (r) break; (*sent)++; }
  uint8_t fin[2] = {0x5F, 0x3F};                     // ATN, UNT, UNL
  c_cmds(fin, 2);
  return r;
}

static int c_read(int addr, uint8_t *buf, int max, int *got, int *end) {
  uint8_t cmd[3] = {0x3F, (uint8_t)(0x20 | MY_ADDR), (uint8_t)(0x40 | addr)};
  int r = c_cmds(cmd, 3);
  if (r) { cset(ATN_M, false); *got = 0; *end = 0; return 1; }
  cset(ATN_M, false);
  *got = c_recv(buf, max, end);
  uint8_t fin[2] = {0x5F, 0x3F};                     // ATN, UNT, UNL
  c_cmds(fin, 2);
  return *got ? 0 : 5;
}

static int c_spoll(int addr, int *stb) {
  uint8_t cmd[4] = {0x3F, (uint8_t)(0x20 | MY_ADDR), (uint8_t)(0x40 | addr), 0x18};   // driver: UNL MLA21 MTA SPE
  int r = c_cmds(cmd, 4);
  if (r) { cset(ATN_M, false); return 1; }
  cset(ATN_M, false);
  uint8_t b; int end;
  int n = c_recv(&b, 1, &end);
  uint8_t fin[2] = {0x19, 0x5F};
  c_cmds(fin, 2);
  if (n != 1) return 1;
  *stb = b;
  return 0;
}

static void hexout(const uint8_t *b, int n) { for (int i = 0; i < n; i++) printf("%02x", b[i]); if (!n) printf("-"); }
static int unhex(const char *s, uint8_t *o) {
  int n = 0; if (!strcmp(s, "-")) return 0;
  while (s[0] && s[1]) { unsigned v; sscanf(s, "%2x", &v); o[n++] = (uint8_t)v; s += 2; }
  return n;
}

int main(void) {
  setvbuf(stdout, NULL, _IOLBF, 0);
  pty_master = posix_openpt(O_RDWR | O_NOCTTY | O_NONBLOCK);
  grantpt(pty_master); unlockpt(pty_master);
  const char *slave = ptsname(pty_master);
  { int s = open(slave, O_RDWR | O_NOCTTY); struct termios t; tcgetattr(s, &t); cfmakeraw(&t); tcsetattr(s, TCSANOW, &t); close(s); }
  memset((void *)&SH, 0, sizeof SH);
  // bridge.ino safeState(): TE/PE outputs driven low, SRQ/NRFD/NDAC outputs released, the rest inputs
  b_out = SRQ_M | NRFD_M | NDAC_M;
  b_oe = TEC_M | PE_M | TED_M | SRQ_M | NRFD_M | NDAC_M;
  pthread_t t0, t1, td;
  pthread_create(&t1, NULL, core1, NULL);
  pthread_create(&t0, NULL, core0, NULL);
  pthread_create(&td, NULL, device5, NULL);
  printf("PTY %s\n", slave);

  char line[70000];
  static uint8_t buf[40000];
  while (fgets(line, sizeof line, stdin)) {
    char cmd[32] = ""; int a = 0, b = 0; char arg[65536] = "";
    sscanf(line, "%31s", cmd);
    if (!strcmp(cmd, "quit")) break;
    else if (!strcmp(cmd, "ifc")) { cset(IFC_M, true); usleep(500); cset(IFC_M, false); cset(REN_M, true); printf("ok 0\n"); }
    else if (!strcmp(cmd, "ren")) { sscanf(line, "%*s %d", &a); cset(REN_M, a); usleep(20000); printf("ok 0\n"); }
    else if (!strcmp(cmd, "usbstall")) { sscanf(line, "%*s %d", &a); sim_stall_until = now_ms() + (uint32_t)a; printf("ok 0\n"); }
    else if (!strcmp(cmd, "tmo")) { sscanf(line, "%*s %d", &a); tmo_ms = (uint32_t)a; printf("ok 0\n"); }
    else if (!strcmp(cmd, "write")) {
      sscanf(line, "%*s %d %65535s %d", &a, arg, &b);
      int n = unhex(arg, buf), sent;
      int r = c_write(a, buf, n, b, &sent);
      printf("ok %d %d\n", r, sent);
    } else if (!strcmp(cmd, "read")) {
      sscanf(line, "%*s %d %d", &a, &b);
      int got, end; int r = c_read(a, buf, b, &got, &end);
      printf("ok %d ", r); hexout(buf, got); printf(" %d\n", end);
    } else if (!strcmp(cmd, "spoll")) {
      sscanf(line, "%*s %d", &a);
      int s = -1; int r = c_spoll(a, &s); printf("ok %d %d\n", r, s);
    } else if (!strcmp(cmd, "dcl")) { uint8_t c = 0x14; printf("ok %d\n", c_cmds(&c, 1)); cset(ATN_M, false); }
    else if (!strcmp(cmd, "sdc") || !strcmp(cmd, "get") || !strcmp(cmd, "gtl")) {
      sscanf(line, "%*s %d", &a);
      uint8_t op = !strcmp(cmd, "sdc") ? 0x04 : !strcmp(cmd, "get") ? 0x08 : 0x01;
      uint8_t c[4] = {0x3F, (uint8_t)(0x20 | a), op, 0x3F};
      printf("ok %d\n", c_cmds(c, 4)); cset(ATN_M, false);
    } else if (!strcmp(cmd, "llo")) { uint8_t c = 0x11; printf("ok %d\n", c_cmds(&c, 1)); cset(ATN_M, false); }
    else if (!strcmp(cmd, "srq")) { usleep(2000); printf("ok %d\n", line_low(SRQ_M) ? 1 : 0); }
    else if (!strcmp(cmd, "drives")) { usleep(20000); printf("ok %x\n", bridge_assert()); }
    else if (!strcmp(cmd, "dev")) { printf("ok "); hexout(dev_last, dev_last_len); printf(" %d\n", (int)dev_cmds); }
    else if (!strcmp(cmd, "stats")) {
      printf("ok online=%d addr=%d L=%d T=%d gen=%u cmds=%u rx=%u tx=%u polls=%u lost=%u holds=%u fights=%u late=%d\n",
             SH.online, SH.addr, SH.listener, SH.talker, SH.gen, SH.n_cmd, SH.n_rx, SH.n_tx, SH.n_polls, SH.ev_lost,
             SH.rx_holds, (unsigned)contention, (int)late_engage);
    } else if (cmd[0]) printf("err unknown command\n");
  }
  sim_stop = 1; SH.req_seq++;
  pthread_join(t1, NULL); pthread_join(t0, NULL); pthread_join(td, NULL);
  return 0;
}
