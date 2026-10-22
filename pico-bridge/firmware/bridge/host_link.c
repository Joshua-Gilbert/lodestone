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
#define DMB() __atomic_thread_fence(__ATOMIC_SEQ_CST)
#else
#define DMB() __asm volatile("dmb" ::: "memory")
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
      SH.session_seq++; request();                   // a new session always starts clean (core 1 resets)
      send_hello();
      break;
    case F_CONFIG:
      if (n >= 3 && p[1] <= 30) {
        SH.addr = p[1]; SH.want_online = (p[2] & 1) ? 1 : 0; SH.auto_rsv = (p[2] & 2) ? 1 : 0; request();
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
    case F_TX: {
      if (n < 4) break;
      uint16_t gen = (uint16_t)(p[1] | (p[2] << 8));
      uint32_t flags = p[3];
      size_t len = n - 4;
      if ((int16_t)(gen - SH.gen) < 0) {             // older than core 1's generation: stale already
        SH.tx_dropped0 += (uint32_t)len;
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
        uint32_t fl = (i == len - 1 && (flags & 1)) ? TXF_EOI : 0;
        SH.tx[h] = ((uint32_t)gen << 16) | (fl << 8) | p[4 + i];
        h = (h + 1u) & (TX_RING - 1u);
      }
      DMB();
      SH.tx_head = h;
      DMB();
      if (take == len && len && (flags & 1)) {       // a whole reply is queued
        SH.tx_eoi_pushed++;
        if (SH.auto_rsv) { request(); break; }       // core 1 raises SRQ for it (request() wakes it too)
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
    go_offline(); SH.rx_tail = SH.rx_head; out_r = out_w = 0;
    return;
  }
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
    if (r.code == R_DATA) {                          // gather a run of data of one generation
      size_t dn = 0;
      uint8_t flags = 0;
      uint32_t i = t;
      while (i != h && dn < DATA_CHUNK) {
        rec_t q = SH.rx[i];
        if (q.code != R_DATA || q.gen != r.gen) break;
        f[4 + dn++] = q.b;
        i = (i + 1u) & (RX_RING - 1u);
        if (q.arg & 1u) { flags = DF_EOI; break; }
      }
      used = dn;
      f[0] = F_DATA; put16(f + 1, r.gen); f[3] = flags;
      flen = 4 + dn;
    } else if (r.code == R_END) {
      f[0] = F_DATA; put16(f + 1, r.gen); f[3] = DF_END;
      flen = 4;
    } else {
      f[0] = F_EVENT; f[1] = r.code; put16(f + 2, r.gen); f[4] = r.b; put32(f + 5, r.arg);
      flen = 9;
    }
    if (!send_frame(f, flen)) break;                 // no room: the records wait in the ring (NRFD backs up)
    DMB();
    SH.rx_tail = (t + (uint32_t)used) & (RX_RING - 1u);
  }
  uint32_t c = consumed_total();
  if (c != credit_reported && (c - credit_reported >= 1024u || now_ms - last_credit_ms >= 5u)) {
    uint8_t e[5]; e[0] = F_CREDIT; put32(e + 1, c);
    if (send_frame(e, 5)) { credit_reported = c; last_credit_ms = now_ms; }
  }
  out_drain();
}
