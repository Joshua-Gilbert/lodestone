// host_link.c -- core 0: COBS-framed protocol to the Raspberry Pi over USB CDC.  See PROTOCOL.md.
//
// Output never blocks and is never lost silently: frames go whole into outbuf, and outbuf drains into USB only
// as fast as the host takes it (link_write_some).  A record leaves core 1's ring only once its frame is in
// outbuf, so a Pi that stops reading fills outbuf, then the ring, and core 1 then holds NRFD -- GPIB flow
// control all the way back to the 1520.
#include <string.h>
#include "gpib_engine.h"
#include "host_link.h"

#ifdef GPIB_SIM
#include "hal_sim.h"
#define DMB() __atomic_thread_fence(__ATOMIC_SEQ_CST)
#define LINK_US() hal_us()
#else
#include "hardware/structs/timer.h"
#define DMB() __asm volatile("dmb" ::: "memory")
#define LINK_US() (timer0_hw->timerawl)          // the timer core 1 stamps its records with
#endif

static uint8_t inbuf[600];
static size_t inlen;
static bool in_overrun;
static uint32_t last_ping_ms, last_credit_ms, credit_reported;
static bool host_session;      // the Pi asked us to go online since the port opened
static uint32_t ctl_dropped;   // control frames that found outbuf full

#define OUTBUF 8192u
static uint8_t outbuf[OUTBUF];
static size_t out_r, out_w;    // bytes [out_r, out_w) still to send

static size_t out_room(void) { return OUTBUF - out_w + out_r; }

static void out_drain(void) {
  while (out_r < out_w) {
    size_t k = link_write_some(outbuf + out_r, out_w - out_r);
    if (!k) break;
    out_r += k;
  }
  if (out_r == out_w) out_r = out_w = 0;
  else if (out_r > OUTBUF / 2) { memmove(outbuf, outbuf + out_r, out_w - out_r); out_w -= out_r; out_r = 0; }
}

// ---- COBS -----------------------------------------------------------------------------------------------------
// Worst-case encoded size of an n-byte frame: n + n/254 + 2.
static size_t cobs_max(size_t n) { return n + n / 254u + 2u; }

static void cobs_put(const uint8_t *p, size_t n) {   // caller has checked out_room() >= cobs_max(n)
  if (OUTBUF - out_w < cobs_max(n)) { memmove(outbuf, outbuf + out_r, out_w - out_r); out_w -= out_r; out_r = 0; }
  uint8_t *out = outbuf + out_w;
  size_t o = 1, code_at = 0;
  uint8_t code = 1;
  for (size_t i = 0; i < n; i++) {
    if (p[i] == 0) {
      out[code_at] = code; code_at = o++; code = 1;
    } else {
      out[o++] = p[i];
      if (++code == 0xFF) { out[code_at] = code; code_at = o++; code = 1; }
    }
  }
  out[code_at] = code;
  out[o++] = 0;
  out_w += o;
}

static bool send_frame(const uint8_t *p, size_t n) {  // false: no room now (control frames are then dropped)
  if (out_room() < cobs_max(n)) { out_drain(); if (out_room() < cobs_max(n)) return false; }
  cobs_put(p, n);
  return true;
}
static void send_ctl(const uint8_t *p, size_t n) { if (!send_frame(p, n)) ctl_dropped++; }

static size_t cobs_decode(const uint8_t *in, size_t n, uint8_t *out) {
  size_t i = 0, o = 0;
  while (i < n) {
    uint8_t code = in[i++];
    if (code == 0) return 0;
    for (uint8_t k = 1; k < code; k++) { if (i >= n) return 0; out[o++] = in[i++]; }
    if (code != 0xFF && i < n) out[o++] = 0;
  }
  return o;
}

static void put16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void put32(uint8_t *p, uint32_t v) { for (int i = 0; i < 4; i++) p[i] = (uint8_t)(v >> (8 * i)); }

static uint32_t consumed_total(void) { return SH.tx_consumed + SH.tx_dropped0; }

// An EVENT frame: code, gen, b, arg, and (2026-10-23b) when it happened on the Pico's microsecond timer.
static void ev_fill(uint8_t *f, uint8_t code, uint16_t gen, uint8_t b, uint32_t arg, uint32_t t) {
  f[0] = F_EVENT; f[1] = code; put16(f + 2, gen); f[4] = b; put32(f + 5, arg); put32(f + 9, t);
}
static void send_event_now(uint8_t code) {   // core 0's own events (not in the ring: core 1 is its producer)
  uint8_t f[13]; ev_fill(f, code, SH.gen, 0, 0, LINK_US()); send_ctl(f, 13);
}

// ---- replies streamed in (TXF_EARLY, 2026-10-23a) ------------------------------------------------------------
// gridlink sends a 2 KB reply as TX frames of 512.  Without EARLY the bridge says READY once the last one is
// in: the whole reply crosses USB (~4 ms) before the 1520 starts reading it.  With EARLY on the first frame the
// reply counts as queued at once (tx_eoi_pushed), so SRQ comes then and the 1520 reads while the rest arrives
// (USB is ~3.5 times faster than the 1520 reads; if the ring runs dry, core 1 waits as for any reply).  Core 1
// counts a reply done when its EOI entry leaves the ring, so every announced reply must put exactly one EOI
// entry in it.  One that will never be finished (stale before its last frame, another reply announced, a new
// session, offline) gets a stand-in: one EOI entry of an older generation, which core 1 drops as stale.
static bool ann_open;          // an EARLY frame came, its ANNOUNCED last frame hasn't
static uint16_t ann_gen;
static uint32_t ann_due;       // stand-ins still to queue (the ring was full)

static void ann_flush(void) {
  while (ann_due) {
    uint32_t h = SH.tx_head, t = SH.tx_tail;
    if (((t - h - 1u) & (TX_RING - 1u)) == 0) return;   // no room yet: core 1 makes some
    SH.tx[h] = ((uint32_t)(uint16_t)(ann_gen - 1u) << 16) | (TXF_EOI << 8);
    SH.tx_dropped0--;                                  // (it is no byte of the Pi's: its pop mustn't count)
    DMB();
    SH.tx_head = (h + 1u) & (TX_RING - 1u);
    ann_due--;
    SH.wake_seq++;
  }
}

static void ann_close(void) {
  if (!ann_open) return;
  ann_open = false;
  ann_due++;
  ann_flush();
}

static void send_log(const char *t) {
  uint8_t f[200]; size_t n = strlen(t); if (n > 190) n = 190;
  f[0] = F_LOG; memcpy(f + 1, t, n); send_ctl(f, n + 1);
}

static void send_hello(void) {
  uint8_t f[80]; size_t n = strlen(FW_TAG);
  uint32_t c, used;
  do {                                              // a consistent pair: core 1 may pop meanwhile
    c = consumed_total();
    DMB();
    used = (SH.tx_head - SH.tx_tail) & (TX_RING - 1u);
    DMB();
  } while (c != consumed_total());
  f[0] = F_HELLO; f[1] = PROTO_VERSION; put16(f + 2, (uint16_t)(TX_RING - 1u)); put16(f + 4, DATA_CHUNK);
  put32(f + 6, c); put16(f + 10, (uint16_t)used);
  memcpy(f + 12, FW_TAG, n);
  send_ctl(f, 12 + n);
  credit_reported = c;
}

static void send_pong(uint32_t now_ms) {
  uint8_t f[48];
  f[0] = F_PONG;
  f[1] = SH.online; f[2] = SH.addr; f[3] = SH.listener; f[4] = SH.talker; f[5] = SH.ren; f[6] = SH.llo;
  f[7] = SH.spms; f[8] = SH.cur_rsv;
  put16(f + 9, SH.gen);
  put32(f + 11, consumed_total()); put32(f + 15, SH.n_cmd); put32(f + 19, SH.n_rx); put32(f + 23, SH.n_tx);
  put32(f + 27, SH.n_polls); put32(f + 31, SH.ev_lost + ctl_dropped); put32(f + 35, SH.rx_holds);
  put32(f + 39, now_ms); put32(f + 43, SH.engine_alive);
  send_ctl(f, 47);
}

static void request(void) { DMB(); SH.req_seq++; SH.wake_seq++; }

static void go_offline(void) {
  if (SH.want_online) { SH.want_online = 0; SH.rsv = 0; request(); }
  host_session = false;
}

// ---- frames from the Pi ---------------------------------------------------------------------------------------
static void handle(const uint8_t *p, size_t n, uint32_t now_ms) {
  if (n < 1) return;
  switch (p[0]) {
    case F_HELLO_REQ:
      ann_close();
      SH.session_seq++; request();                   // a new session always starts clean (core 1 resets)
      send_hello();
      break;
    case F_CONFIG:
      if (n >= 3 && p[1] <= 30) {
        SH.addr = p[1]; SH.want_online = (p[2] & 1) ? 1 : 0; SH.auto_rsv = (p[2] & 2) ? 1 : 0;
        SH.quiet = (p[2] & 4) ? 1 : 0; request();
        host_session = (p[2] & 1) != 0; last_ping_ms = now_ms;
      } else send_log("CONFIG refused: address must be 0..30");
      break;
    case F_STB:
      if (n >= 3) {
        SH.stb = p[1];
        if (p[2]) { SH.rsv = 1; SH.rsv_seq++; } else SH.rsv = 0;   // each rsv = 1 is a new request
        request();
      }
      break;
    case F_PING: last_ping_ms = now_ms; send_pong(now_ms); break;
    case F_WAKE:
      if (n >= 3) { SH.bell_gen = (uint16_t)(p[1] | (p[2] << 8)); DMB(); SH.bell_seq++; request(); }
      break;
    case F_HOLD:                                     // the 1520's next message, expected (2026-10-23c)
    case F_HOLD_GLP:                                 //  or the start of its next GLP frame (2026-10-23d)
      if (n >= 4 && n - 3 <= HOLD_MAX && (p[0] == F_HOLD || n == 7)) {
        SH.hold_seq++;                               // odd: being written
        DMB();
        SH.hold_gen = (uint16_t)(p[1] | (p[2] << 8));
        SH.hold_kind = p[0] == F_HOLD ? HOLD_EXACT : HOLD_GLP;
        SH.hold_n = (uint8_t)(n - 3);
        for (size_t i = 0; i < n - 3; i++) SH.hold_exp[i] = p[3 + i];
        DMB();
        SH.hold_seq++;                               // even: core 1 takes it when that message begins
      }
      break;
    case F_TX: {
      if (n < 4) break;
      uint16_t gen = (uint16_t)(p[1] | (p[2] << 8));
      uint32_t flags = p[3];
      size_t len = n - 4;
      bool held = (flags & TXF_HELD) != 0;          // (a held reply: core 1 counts it, if its message matches)
      if (!held && ann_open && (gen != ann_gen || (flags & TXF_EARLY))) ann_close();   // that one won't be finished
      if ((int16_t)(gen - SH.gen) < 0) {             // older than core 1's generation: stale already
        SH.tx_dropped0 += (uint32_t)len;
        if (!held && ann_open && gen == ann_gen) ann_close();  // (an announced reply gone stale before its end)
        break;
      }
      uint32_t h = SH.tx_head, t = SH.tx_tail;
      uint32_t freeq = (t - h - 1u) & (TX_RING - 1u);
      size_t take = len;
      if (take > freeq) {
        send_log("TX overrun: the Pi sent more than its credit; reply truncated");
        SH.tx_dropped0 += (uint32_t)(take - freeq);
        take = freeq;
      }
      for (size_t i = 0; i < take; i++) {
        uint32_t fl = ((i == len - 1 && (flags & 1)) ? TXF_EOI : 0) | (held ? TXE_HELD : 0);
        SH.tx[h] = ((uint32_t)gen << 16) | (fl << 8) | p[4 + i];
        h = (h + 1u) & (TX_RING - 1u);
      }
      DMB();
      SH.tx_head = h;
      DMB();
      if (held) { SH.wake_seq++; break; }
      if (take < len) ann_close();                   // (its EOI may be lost: a stand-in for it)
      if ((flags & TXF_EARLY) && !(flags & 1) && take == len && len) {   // a reply begins: ready now
        ann_open = true; ann_gen = gen;
        SH.tx_eoi_pushed++;
        send_event_now(E_TX_IN);
        if (SH.auto_rsv) { request(); break; }
      } else if (take == len && len && (flags & 1)) {
        bool counted = (flags & TXF_ANN) && ann_open;
        ann_open = false;
        if (!counted) {                              // a whole reply is queued
          SH.tx_eoi_pushed++;
          send_event_now(E_TX_IN);
          if (SH.auto_rsv) { request(); break; }     // core 1 raises SRQ for it (request() wakes it too)
        }
      }
      SH.wake_seq++;                                 // wakes core 1 if it waits to talk (not a request)
      break;
    }
    case F_BOOTSEL:
      go_offline();
      link_bootsel();
      break;
    default: break;
  }
}

void link_init(void) {
  inlen = 0; in_overrun = false; host_session = false; out_r = out_w = 0;
  SH.want_online = 0; SH.addr = 10; SH.stb = 0; SH.rsv = 0;
  request();
}

void link_input(const uint8_t *b, size_t n, uint32_t now_ms) {
  for (size_t i = 0; i < n; i++) {
    if (b[i] == 0) {
      if (!in_overrun && inlen) {
        uint8_t dec[600];
        size_t m = cobs_decode(inbuf, inlen, dec);
        if (m) handle(dec, m, now_ms);
      }
      inlen = 0; in_overrun = false;
    } else if (inlen < sizeof inbuf) inbuf[inlen++] = b[i];
    else in_overrun = true;
  }
}

// ---- records from core 1 --------------------------------------------------------------------------------------
void link_poll(uint32_t now_ms, bool host_open) {
  if (!host_open) {                                  // nobody listening: offline, drop the records and output
    ann_close();
    go_offline(); SH.rx_tail = SH.rx_head; out_r = out_w = 0;
    return;
  }
  if (ann_open && (uint16_t)SH.gen != ann_gen) ann_close();   // core 1 moved on (SDC, a new message)
  ann_flush();
  if (host_session && now_ms - last_ping_ms > LINK_PING_TIMEOUT_MS) {
    go_offline();
    send_log("no PING from the Pi for 5 s: offline (bus released)");
  }
  out_drain();
  uint8_t f[8 + DATA_CHUNK];
  for (int frames = 0; frames < 64; frames++) {
    uint32_t t = SH.rx_tail, h = SH.rx_head;
    if (t == h) break;
    DMB();
    rec_t r = SH.rx[t];
    size_t used = 1;                                 // records this frame takes
    size_t flen;
    uint32_t end_t = 0;
    uint8_t held = 0;
    if (r.code == R_DATA) {                          // gather a run of data of one generation
      size_t dn = 0;
      uint8_t flags = 0;
      uint32_t i = t;
      while (i != h && dn < DATA_CHUNK) {
        rec_t q = SH.rx[i];
        if (q.code != R_DATA || q.gen != r.gen) break;
        f[4 + dn++] = q.b;
        i = (i + 1u) & (RX_RING - 1u);
        if (q.arg & 1u) { flags = DF_EOI; end_t = q.t; if (q.arg & 2u) { flags |= DF_HELD; held = 1; } break; }
      }
      used = dn;
      f[0] = F_DATA; put16(f + 1, r.gen); f[3] = flags;
      flen = 4 + dn;
    } else if (r.code == R_END) {
      f[0] = F_DATA; put16(f + 1, r.gen); f[3] = DF_END;
      flen = 4;
    } else {
      if (r.code == E_TALK_WAIT) r.arg += SH.tx_dropped0;   // core 1's count, put on CREDIT's scale (PROTOCOL.md)
      ev_fill(f, r.code, r.gen, r.b, r.arg, r.t);
      flen = 13;
    }
    if (!send_frame(f, flen)) break;                 // no room: the records wait in the ring (NRFD backs up)
    DMB();
    SH.rx_tail = (t + (uint32_t)used) & (RX_RING - 1u);
    if (f[0] == F_DATA && (f[3] & DF_EOI)) {         // (when the message's last byte came: for the trace)
      uint8_t e[13]; ev_fill(e, E_RX_END, r.gen, held, 0, end_t); send_ctl(e, 13);   // b = 1: the held reply
    }
  }
  uint32_t c = consumed_total();
  if (c != credit_reported && (c - credit_reported >= 1024u || now_ms - last_credit_ms >= 5u)) {
    uint8_t e[5]; e[0] = F_CREDIT; put32(e + 1, c);
    if (send_frame(e, 5)) { credit_reported = c; last_credit_ms = now_ms; }
  }
  out_drain();
}
