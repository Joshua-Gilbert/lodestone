// gpib_engine.h -- GPIB-Pico2 bridge: the IEEE-488.1 device engine (runs alone on core 1) and the
// rings it shares with core 0 (USB to the Raspberry Pi).
//
// Board: GPIB-Pico2 device bridge rev 1.2 (U3 side-swap bodge fitted).  GPIO map, unchanged since r1:
//   GP0-7 DIO1-8 (U2 SN75160B)   GP8 SRQ  GP9 ATN  GP10 EOI  GP11 DAV  GP12 NRFD  GP13 NDAC  GP14 IFC  GP15 REN (U3)
//   GP16 U3 TE   GP17 U2 PE   GP18 U2 TE.  U3 DC is tied to +5 V (device mode) in copper.
// GPIB is active low and the transceivers do not invert: GPIO low = line asserted.
//
// The engine is a device with the IEEE-488.1 subsets SH1 AH1 T6 L4 SR1 RL1 PP0 DC1 DT1 C0: basic talker with
// serial poll, basic listener, each unaddressed by the other's own address (so it is never both), service
// request, remote/local, device clear, device trigger.  No secondary addressing, no parallel poll, never a
// controller.  RL1 and DT1 only report to the Pi: what "remote" or "trigger" means is up to its handler.
//
// This file is shared by the Arduino build (GPIB_SIM undefined) and the host simulation (GPIB_SIM defined).
#pragma once
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

#define FW_TAG "bridge fw 2026-10-24"
#define PROTO_VERSION 1

// ---- pins ----------------------------------------------------------------------------------------------------
#define P_SRQ 8
#define P_ATN 9
#define P_EOI 10
#define P_DAV 11
#define P_NRFD 12
#define P_NDAC 13
#define P_IFC 14
#define P_REN 15
#define P_TE_C 16
#define P_PE_D 17
#define P_TE_D 18

#define DIO_M  0xFFu
#define SRQ_M  (1u << P_SRQ)
#define ATN_M  (1u << P_ATN)
#define EOI_M  (1u << P_EOI)
#define DAV_M  (1u << P_DAV)
#define NRFD_M (1u << P_NRFD)
#define NDAC_M (1u << P_NDAC)
#define IFC_M  (1u << P_IFC)
#define REN_M  (1u << P_REN)
#define TEC_M  (1u << P_TE_C)
#define PE_M   (1u << P_PE_D)
#define TED_M  (1u << P_TE_D)

// ---- records core 1 -> core 0 (what came off the bus, in bus order) --------------------------------------------
enum {
  R_DATA = 0,        // b = data byte, arg bit 0 = EOI was asserted with it (end of message); with EOI, bit 1 =
                     //   the message was the one the Pi's hold (F_HOLD) expected: its held reply is ready
  R_END = 1,         // the message ended without EOI (unlistened, IFC) -- no byte
  // events: arg as noted
  E_LISTEN = 0x10, E_UNLISTEN, E_TALK, E_UNTALK,
  E_TALK_WAIT,       // addressed to talk, ATN released, nothing to send.  arg = tx_consumed at that moment
  E_DCL, E_SDC, E_GET, E_GTL, E_LLO, E_IFC,
  E_REN,             // arg 1 = REN asserted, 0 = released
  E_SPOLL,           // serially polled; b = the status byte sent
  E_TX_DONE,         // the last byte of a reply (EOI) was accepted
  E_ONLINE,          // b = address, arg = REN asserted (1/0)
  E_OFFLINE,
  // (2026-10-23b, for gridlink.bench --trace: every event frame carries the time it happened, on the Pico's
  //  microsecond timer)
  E_RX_END,          // core 0: the last byte of a message from the 1520 (with EOI) came, at the record's time;
                     //   b = 1: it matched the hold, the held reply answers it (2026-10-23c)
  E_TX_IN,           // core 0: a reply is queued (its first TX frame, or a whole one): READY from now
  E_SRQ,             // SRQ asserted
};

typedef struct { uint8_t code, b; uint16_t gen; uint32_t arg; uint32_t t; } rec_t;   // t: the timer, us

#define RX_RING  4096u     // records, power of 2
#define RX_RESERVE 64u     // kept free for events: data stops (NRFD held) before the ring is full
#define TX_RING  16384u    // entries, power of 2.  entry = gen << 16 | flags << 8 | byte
#define TXF_EOI  0x01u
#define TXE_HELD 0x02u     // (2026-10-23c) a held reply: sent only if the message of its generation matches the hold
#define HOLD_MAX 16u       // bytes a hold can expect (GLP's POLL is 8)
#define HOLD_EXACT 0u      // the message is exactly hold_exp
#define HOLD_GLP 1u        // (2026-10-23d) the message is one GLP frame whose first 4 bytes are hold_exp (sync, type,
                           //  seq, ack), whose length field is right and whose Fletcher sum is good (CLAUDE's next
                           //  fragment of a message: the Pi's answer to it, a NOP, can't depend on what it carries)
#define HOLD_GLP_MAX 8192u // the longest payload such a frame may have

typedef struct {
  // core 1 -> core 0
  volatile uint32_t rx_head;            // written by core 1
  volatile uint32_t rx_tail;            // written by core 0
  rec_t rx[RX_RING];
  // core 0 -> core 1
  volatile uint32_t tx_head;            // written by core 0
  volatile uint32_t tx_tail;            // written by core 1
  uint32_t tx[TX_RING];
  // requests from core 0: change any of these, then bump req_seq (and wake_seq)
  volatile uint8_t want_online, addr, stb, rsv;
  volatile uint32_t rsv_seq;            // +1 for every new service request (STB with rsv = 1) from the Pi
  volatile uint32_t session_seq;        // +1 when the Pi starts a session (HELLO_REQ): a clean start
  volatile uint32_t req_seq;
  volatile uint32_t wake_seq;           // bumped with req_seq AND for every TX frame: wakes a waiting talker
  volatile uint32_t tx_dropped0;        // tx entries core 0 never queued (stale on arrival); counted as consumed
  volatile uint16_t bell_gen;           // F_WAKE: the generation the Pi rang for
  volatile uint32_t bell_seq;           // +1 for every F_WAKE (bell_gen written first)
  // Auto service request (CONFIG flags bit 1), for gridlink's GLP link: the bridge itself requests service
  // (status 60h: RQS + READY) once for every complete reply (an EOI byte) queued, keeps READY (20h) until that
  // reply has been sent, and drops it all if the reply goes stale -- as the AR488 +GRiD1 patch does.
  volatile uint8_t auto_rsv;
  // Quiet (CONFIG flags bit 2, 2026-10-24): RQS and READY in the status byte as ever, but the SRQ line is never
  // driven, so a controller's SRQ latch (a DOS program's, under resident Claude) sees nothing of ours.  The
  // 1520 finds the answers by serial-polling.
  volatile uint8_t quiet;
  volatile uint32_t tx_eoi_pushed;      // complete replies queued by core 0 (EOI entries), ever
  // A held reply (F_HOLD, 2026-10-23c): the Pi expects the 1520's next message to be exactly hold_exp (its next
  // POLL) and has queued the answer to it ahead, as TXE_HELD entries of the next generation.  If the message is
  // that, core 1 counts the reply ready at its EOI byte (SRQ at once, no round trip to the Pi); if it isn't,
  // the held entries are dropped and the Pi answers it as usual.  hold_seq is odd while core 0 writes the rest.
  volatile uint32_t hold_seq;
  volatile uint16_t hold_gen;
  volatile uint8_t hold_n;
  volatile uint8_t hold_kind;           // HOLD_EXACT, or (2026-10-23d) HOLD_GLP: a good GLP frame starting thus
  volatile uint8_t hold_exp[HOLD_MAX];
  volatile uint32_t n_held, n_held_void;  // held replies used / not (core 1)
  // status from core 1 (for reports)
  volatile uint8_t online, listener, talker, ren, llo, spms, cur_rsv;
  volatile uint16_t gen;
  volatile uint32_t tx_consumed;        // tx entries taken off the ring (sent or dropped as stale)
  volatile uint32_t n_cmd, n_rx, n_tx, n_polls, ev_lost, rx_holds;
  volatile uint32_t engine_alive;       // incremented now and then by core 1
} shared_t;

extern shared_t SH;

void engine_timing_init(uint32_t sys_hz);   // core 1, once, before engine_run: T1 in CPU cycles (SysTick)
void engine_run(void);          // core 1, never returns (the simulation stops it with sim_stop)

#ifdef GPIB_SIM
extern volatile int sim_stop;
#endif

#ifdef __cplusplus
}
#endif
