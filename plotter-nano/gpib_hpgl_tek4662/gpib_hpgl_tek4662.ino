/*
 * gpib_hpgl_tek4662.ino  (v7, for Lodestone's shared bus)
 *
 * GPIB HP-GL to Tektronix 4662 translator. A GPIB listener at GPIB_ADDRESS
 * that takes HP-GL and sends it to the 4662 as Tek commands at 1200 baud.
 *
 * v7.3: ';' is optional, as in HP-GL: a letter after a mnemonic and its
 *    arguments starts the next mnemonic. PD100,200PU300,400 lifts the pen for
 *    300,400 (the PU was taken for separators), and INPU100,200 or
 *    SP2PD100,200 no longer lose all that follows IN or SP up to a ';'. SM
 *    and DT keep the one character they take; BL and WD, like LB, take text
 *    up to ETX (the Nano ignores all four; it draws LB). The serial-poll
 *    byte goes on DIO a pass before DAV, not ~1.7 us before (T1 is 2 us).
 *
 * v7.2: no bumps. A status request no longer re-enters graph mode with GS and
 *    a move to the pen's position, which lifted the pen in the middle of a
 *    stroke every ~600 bytes. The 4662 returns to the mode it was in after a
 *    Style I command (Figure 3-3), so the stroke just carries on. !g 1 puts
 *    the re-entry back.
 *
 * v7: settling after labels. The 4662's own characters leave a ~1 cm tail on
 *    the move after a label and small marks at the spaces inside one
 *    (TESTPAT5). Three console switches, to find which cure works:
 *      !a ms   after a label: wait until the 4662 has drawn it (a status
 *              reply showing its buffer empty), pause ms, then the move
 *      !b 1    after a label: a BS (back one character space, pen up: p. 4-22)
 *              before the move, so the long move starts with the pen clear
 *      !w ms   the same wait and pause before each space inside a label
 *    All off by default, with v6's !r: the drag turned out to be the pen
 *    adapter pressing the pen too hard on the paper, and with a corrected
 *    adapter the plots are clean without them. They stay for a pen that
 *    needs them (a slow-lifting pen: try !r 22, !a 150, !w 150).
 *
 * v6: no drag when the pen lifts. The 4662's pen leaves the paper about 1 mm
 *    into a pen-up move (Claude's detour test: the same ~1 mm tick whatever
 *    the detour), so short gaps were bridged and every move started with a
 *    tail. A pause in the Nano can't help (the plotter runs from its own
 *    buffer), so the plotter is given a move to do while the pen lifts: a
 *    pen-up move of RETRACE_ADU back along the stroke just drawn. The drag
 *    lands on ink that is already there, and the real move starts with the
 *    pen clear. '!r n' sets it (ADU, 273 = 1 inch; 0 turns it off).
 *
 * v5: faster, and quiet.
 *  - No bell: GS BEL ("the first coordinate is a draw") rings the 4662's bell
 *    (070-4164-00 p. 3-6), and v4 sent it at every pen-down run that didn't
 *    start with a move, and after every status request. v5 sends GS and the
 *    pen's own position (a move to where it is) instead.
 *  - Compressed coordinates (Table 3-3, p. 3-10): only the bytes that changed
 *    from the last point, so a short stroke costs 1-3 bytes instead of 5. At
 *    1200 baud that's what limits small detail. A coordinate after a label or
 *    a status request is sent in full, as the manual asks.
 *  - Status requests overlap the drawing: the Nano asks when the room left
 *    drops below QUERY_AT and goes on sending what it already has room for;
 *    the reply resets the limit (the free bytes it reports, counted from the
 *    bytes on the line when it came). The serial line stays busy and the
 *    4662's buffer never runs dry while there is plot to send.
 *
 * v4: flow control by asking, not guessing.
 *  - Toward the plotter: the Nano asks the 4662 how much room its input
 *    buffer has (READ STATUS 1, "ESC A O 1 SUB"; the free bytes are in bits
 *    0-10 of the reply, 070-4164-00 p. 4-13/4-14) and sends that much, less a
 *    margin, then asks again. The 4662's 2 KB buffer (about 1400 characters)
 *    stays full while the pen draws, with no timing model. This needs the
 *    plotter's TX wired back to D13 (MAX3232 RXD). If the plotter never
 *    answers, the Nano falls back to v3's timed pacing (tunable with '!').
 *  - Toward the GPIB bus: the Nano answers a serial poll with how much room
 *    its own buffer has, so a controller (gridlink's grid_plotter) sends only
 *    what fits and never waits on the bus while the pen draws:
 *      bit 7     1: idle (its buffer and its queue to the plotter are empty)
 *      bit 6     0 (RQS: the Nano never requests service)
 *      bits 0-5  room in its buffer, in 4-byte units (0-63)
 *    A controller that sends more than that is held off with NRFD, as before.
 *
 * v2/v3, still here: data read active-low; off the bus when not addressed
 * (ATN pin-change interrupt); non-blocking handshake on port I/O; plotter
 * UART on Timer 2; LB labels end at ETX; '?' on USB shows the bus.
 *
 * USB console (9600): HP-GL for testing; '?' bus and flow state; '!' the
 * fallback pacing (!s ADU/s, !v ms/vector, !p ms/pen, !c ms/char, !l ms lead);
 * '#' asks the plotter for its status now.
 *
 * GPIB PIN MAPPING (AR488 Nano standard):
 *   DIO1-DIO4 D2-D5 (PD2-PD5)   DIO5-DIO8 A0-A3 (PC0-PC3)
 *   DAV D7 (PD7)  NRFD D8 (PB0)  NDAC D9 (PB1)  ATN D10 (PB2)
 *   IFC D11 (PB3) SRQ D12 (PB4, unused)  EOI A4 (PC4)  REN A5 (PC5)
 *   D6 (PD6): TX to the plotter (MAX3232 TXD)
 *   D13 (PB5): RX from the plotter (MAX3232 RXD)
 *
 * PLOTTER: D6/D13 -> MAX3232 -> AT925MF -> 4662 MODEM port
 *          4662 switches A=3, B=2, C=2, D=3 (Copy Mode, 1200 baud),
 *          plotter address character A
 */

#include <avr/io.h>
#include <avr/interrupt.h>

// ============================================================================
// CONFIGURATION
// ============================================================================

#define GPIB_ADDRESS    1       // our GPIB address (0-30): Lodestone's [plotter] address
#define LISTEN_ONLY     false   // true: take every data byte on the bus (never on a shared bus)
#define DEBUG_ENABLED   true    // USB serial debug output

#define PLOTTER_ADDR    'A'     // the 4662's serial address character (rear-panel switches)
#define STATUS_MARGIN   48      // bytes kept free in the 4662's buffer, below what it reports
#define QUERY_AT        600     // ask again when this little room is left
#define QUERY_GAP_MS    400     // at most one status request in this time
#define QUERY_REENTER   0       // !g: re-enter graph/alpha mode after a status request (v5-v7 did)
#define RETRACE_ADU     0       // !r: pen-up move back along the last stroke before a move (22: ~2 mm)
#define LABEL_SETTLE_MS 0       // !a: after a label, wait for the plotter, then this pause (e.g. 150)
#define LABEL_BS        0       // !b: after a label, a BS before the move
#define SPACE_SETTLE_MS 0       // !w: before a space in a label, wait for the plotter, then this (e.g. 150)
#define STATUS_TIMEOUT  180000UL // ms to wait for a status reply (it may wait for the pen)
#define PROBE_MS        1500    // ms to wait for a reply when finding out if the plotter answers

// Fallback pacing, when the plotter doesn't answer status requests (as v3)
#define PACE_SPEED_ADU_S  820
#define PACE_VECTOR_MS    30
#define PACE_PEN_MS       120
#define PACE_CHAR_MS      150
#define PACE_LEAD_MS      1500

// ============================================================================
// PORT BITS
// ============================================================================

#define B_NRFD  _BV(0)   // PB0 = D8
#define B_NDAC  _BV(1)   // PB1 = D9
#define B_ATN   _BV(2)   // PB2 = D10
#define B_IFC   _BV(3)   // PB3 = D11
#define B_RX    _BV(5)   // PB5 = D13, from the plotter
#define D_DAV   _BV(7)   // PD7 = D7
#define D_TEKTX _BV(6)   // PD6 = D6
#define D_DIO   0x3C     // PD2-PD5 = DIO1-DIO4
#define C_DIO   0x0F     // PC0-PC3 = DIO5-DIO8
#define C_EOI   _BV(4)   // PC4 = A4
#define C_REN   _BV(5)   // PC5 = A5

// Open-collector: assert = output low; release = input, no pull-up.
#define assertLines(m)   (DDRB |= (m))
#define releaseLines(m)  (DDRB &= ~(m))

#define atnLow()   (!(PINB & B_ATN))
#define davLow()   (!(PIND & D_DAV))
#define eoiLow()   (!(PINC & C_EOI))
#define ifcLow()   (!(PINB & B_IFC))
#define nrfdLow()  (!(PINB & B_NRFD))
#define ndacLow()  (!(PINB & B_NDAC))

#define GPIB_UNL   0x3F
#define GPIB_UNT   0x5F
#define GPIB_SPE   0x18
#define GPIB_SPD   0x19
#define GPIB_MLA   (0x20 | GPIB_ADDRESS)
#define GPIB_MTA   (0x40 | GPIB_ADDRESS)

static inline uint8_t readDataBus() {           // DIO lines are active-low
    uint8_t raw = ((PIND >> 2) & 0x0F) | ((PINC & 0x0F) << 4);
    return (uint8_t)~raw;
}

// ============================================================================
// RING BUFFER: GPIB -> parser
// ============================================================================

#define RING_SIZE 256                   // uint8_t indices wrap by themselves
volatile uint8_t ring[RING_SIZE];
volatile uint8_t ringHead = 0, ringTail = 0;
static inline uint8_t ringCount() { return (uint8_t)(ringHead - ringTail); }
static inline bool ringEmpty() { return ringHead == ringTail; }
#define RING_HOLD 240                   // hold NRFD from here (room for in-flight bytes)

// ============================================================================
// PLOTTER UART: 1200 baud 8N1, TX on D6 and RX on D13, from Timer 2 at 3x
// ============================================================================

#define TEKQ_SIZE 256
volatile uint8_t tekQ[TEKQ_SIZE];
volatile uint8_t tekHead = 0, tekTail = 0;
#define RXQ_SIZE 32                     // power of two
volatile uint8_t rxQ[RXQ_SIZE];
volatile uint8_t rxHead = 0, rxTail = 0;
volatile uint32_t txCount = 0;          // bytes put on the line to the plotter
uint32_t queuedCount = 0;               // bytes queued for it (tekRaw)

void gpibService();

ISR(TIMER2_COMPA_vect) {                // 3623 Hz: three ticks a bit (1207.7 baud, +0.6%)
    static uint8_t phase = 0, cur, bit = 0;
    static uint8_t rxState = 0, rxCount, rxByte;
    // receive: find the start bit, then sample each bit near its middle
    bool rxHigh = PINB & B_RX;
    if (rxState == 0) {
        if (!rxHigh) { rxState = 1; rxCount = 4; rxByte = 0; }
    } else if (--rxCount == 0) {
        if (rxState <= 8) {             // data bits, LSB first
            rxByte >>= 1;
            if (rxHigh) rxByte |= 0x80;
            rxState++; rxCount = 3;
        } else {                        // stop bit
            if (rxHigh && (uint8_t)(rxHead - rxTail) < RXQ_SIZE) { rxQ[rxHead & (RXQ_SIZE - 1)] = rxByte; rxHead++; }
            rxState = 0;
        }
    }
    // transmit: one bit every third tick
    if (++phase < 3) return;
    phase = 0;
    if (bit == 0) {
        if (tekHead == tekTail) return; // idle: the line stays high
        cur = tekQ[tekTail]; tekTail++; txCount++;
        PORTD &= ~D_TEKTX;              // start bit
        bit = 1;
    } else if (bit <= 8) {
        if (cur & 1) PORTD |= D_TEKTX; else PORTD &= ~D_TEKTX;
        cur >>= 1; bit++;
    } else {
        PORTD |= D_TEKTX;               // stop bit
        bit = 0;
    }
}

static inline uint8_t tekQueued() { return (uint8_t)(tekHead - tekTail); }

void tekRaw(uint8_t b) {                // into the UART queue (no flow control)
    while ((uint8_t)(tekHead + 1) == tekTail) gpibService();
    tekQ[tekHead] = b; tekHead++; queuedCount++;
}

static inline uint32_t txNow() { uint8_t s = SREG; cli(); uint32_t t = txCount; SREG = s; return t; }

int rxRead() {
    if (rxHead == rxTail) return -1;
    uint8_t b = rxQ[rxTail & (RXQ_SIZE - 1)]; rxTail++;
    return b;
}

void uartBegin() {
    DDRD |= D_TEKTX; PORTD |= D_TEKTX;  // TX idles high
    DDRB &= ~B_RX; PORTB &= ~B_RX;      // RX: input (the MAX3232 drives it)
    TCCR2A = _BV(WGM21);                // CTC
    TCCR2B = _BV(CS22);                 // /64
    OCR2A = 68;                         // 16 MHz / 64 / 69 = 3623 Hz
    TIMSK2 = _BV(OCIE2A);
}

// ============================================================================
// GPIB: LISTENER (acceptor) AND SERIAL-POLL TALKER
// ============================================================================

volatile bool isListener = LISTEN_ONLY;
volatile bool isTalker = false, spollMode = false, spollSent = false;
enum { IDLE, READY, ACCEPTED } hsState = IDLE;
volatile uint8_t talkState = 0;         // 0 idle, 1 byte on DIO (waiting for ready), 2 DAV asserted
uint8_t lastByte; bool lastAtn, lastEoi;
unsigned long nCmd = 0, nData = 0, nDropped = 0, nPolls = 0;
volatile uint8_t events = 0;
#define EV_ADDRESSED  1
#define EV_UNLISTENED 2
#define EV_IFC        4

static inline void talkRelease() {      // let go of DAV and the data lines
    uint8_t s = SREG; cli();
    DDRD &= ~(D_DIO | D_DAV);
    DDRC &= ~C_DIO;
    SREG = s;
}

// ATN falling: take part in the command bytes at once, and stop talking.
ISR(PCINT0_vect) {
    if (atnLow()) {
        assertLines(B_NRFD | B_NDAC);
        DDRD &= ~(D_DIO | D_DAV); DDRC &= ~C_DIO;
        talkState = 0;
    }
}

static inline bool takingPart() { return atnLow() || isListener; }

static inline void leaveBus() {         // NRFD and NDAC released, unless ATN has just fallen
    uint8_t s = SREG; cli();
    if (!atnLow()) releaseLines(B_NRFD | B_NDAC);
    SREG = s;
}

void busCommand(uint8_t c) {
    nCmd++;
    c &= 0x7F;                          // DIO8 is parity on some controllers
    if (c == GPIB_MLA) {
        if (!isListener) events |= EV_ADDRESSED;
        isListener = true;
    } else if (c == GPIB_UNL && !LISTEN_ONLY) {
        if (isListener) events |= EV_UNLISTENED;
        isListener = false;
    } else if (c == GPIB_MTA) {
        isTalker = true; spollSent = false;
    } else if (c >= 0x40 && c <= 0x5F) {    // UNT, or another talker
        isTalker = false;
    } else if (c == GPIB_SPE) {
        spollMode = true; spollSent = false;
    } else if (c == GPIB_SPD) {
        spollMode = false;
    }
}

uint8_t statusByte();

void talkService() {
    if (atnLow()) return;               // the interrupt has let go already
    switch (talkState) {
    case 0:
        if (!(isTalker && spollMode && !spollSent)) return;
        {
            uint8_t v = statusByte();
            uint8_t s = SREG; cli();
            DDRD = (DDRD & ~D_DIO) | ((v & 0x0F) << 2);     // a 1 pulls its line low
            DDRC = (DDRC & ~C_DIO) | ((v >> 4) & 0x0F);
            SREG = s;
        }
        nPolls++;
        talkState = 1;
        return;                         // DAV on the next pass: the byte settles first (T1, 2 us)
    case 1:                             // wait for the listeners: NRFD released, NDAC held
        if (nrfdLow() || !ndacLow()) return;
        { uint8_t s = SREG; cli(); if (!atnLow()) DDRD |= D_DAV; SREG = s; }
        talkState = 2;
        return;
    case 2:                             // wait for them to take it
        if (ndacLow()) return;
        talkRelease();
        spollSent = true;               // one byte per poll
        talkState = 0;
        return;
    }
}

void gpibService() {
    if (ifcLow()) {
        if (!LISTEN_ONLY && isListener) events |= EV_IFC;
        if (!LISTEN_ONLY) isListener = false;
        isTalker = false; spollMode = false;
        if (talkState) { talkRelease(); talkState = 0; }
    }
    talkService();
    switch (hsState) {
    case IDLE:
        if (!takingPart()) { leaveBus(); return; }
        assertLines(B_NDAC);
        hsState = READY;
        // fall through
    case READY:
        if (!davLow()) {
            if (!takingPart()) { leaveBus(); hsState = IDLE; return; }
            if (!atnLow() && ringCount() >= RING_HOLD) assertLines(B_NRFD);  // full: hold off data
            else releaseLines(B_NRFD);
            return;
        }
        assertLines(B_NRFD);            // DAV low: the byte is valid
        lastByte = readDataBus();
        lastAtn = atnLow();
        lastEoi = eoiLow();
        releaseLines(B_NDAC);           // accepted
        hsState = ACCEPTED;
        if (lastAtn) busCommand(lastByte);
        else if (isListener) {
            if (ringCount() < RING_SIZE - 1) { ring[ringHead] = lastByte; ringHead++; nData++; }
            else nDropped++;
        }
        return;
    case ACCEPTED:
        if (davLow()) return;
        assertLines(B_NDAC);
        hsState = READY;
        return;
    }
}

void gpibBegin() {
    DDRD &= ~(D_DIO | D_DAV); PORTD &= ~(D_DIO | D_DAV);
    DDRC &= ~0x3F; PORTC &= ~0x3F;
    DDRB &= ~(B_NRFD | B_NDAC | B_ATN | B_IFC | _BV(4));
    PORTB &= ~(B_NRFD | B_NDAC | B_ATN | B_IFC | _BV(4));
    hsState = IDLE;
    PCMSK0 = _BV(PCINT2);               // D10, ATN
    PCIFR = _BV(PCIF0);
    PCICR |= _BV(PCIE0);
}

// ============================================================================
// FLOW TO THE PLOTTER
// ============================================================================

uint16_t labelSettle = LABEL_SETTLE_MS, spaceSettle = SPACE_SETTLE_MS;
uint8_t labelBs = LABEL_BS;
bool afterLabel = false;                // a label was the last thing sent
long emptyFree = -1;                    // what the plotter reports with nothing to do (at the probe)
uint8_t queryReenter = QUERY_REENTER;
bool statusMode = false;                // the plotter answers READ STATUS
bool queryPending = false;
unsigned long querySentAt = 0, lastProbeAt = 0;
uint32_t limitCount = 0;                // queuedCount may grow to this (from the last reply)
uint32_t txAtReply = 0;                 // txCount when the reply began to arrive
long lastFree = -1;                     // what the plotter last said
unsigned long nQueries = 0, nReplies = 0;
unsigned long queryGap = QUERY_GAP_MS;  // longer if the plotter answers at once
bool needsMove = true;                  // the next DRAW must re-enter graph mode (GS + a move)
bool inAlpha = false;
bool coordKnown = false;                // the plotter's graphic memory = what we last sent
uint8_t lastHiY, lastEB, lastLoY, lastHiX;
static inline long roomLeft() { return (long)(limitCount - queuedCount); }

// The reply: 7 characters (070-4164-00 Figure 3-9 B): 1-6 are 0x20-0x3F with
// five bits each, 7 is 0x40-0x5F with the two LSBs and the block type.
uint8_t rxBlock[7]; uint8_t rxLen = 0;

void takeReply(uint16_t v1, uint16_t v2) {
    if (v1 != 1) return;                // not status word 1
    lastFree = v2 & 0x7FF;
    // what it reports leaves out the bytes still on their way: those sent
    // since it answered (txAtReply) and those queued here
    long lim = (long)txAtReply + lastFree - STATUS_MARGIN;
    limitCount = lim > (long)queuedCount ? (uint32_t)lim : queuedCount;
    nReplies++;
    // a reply that comes at once (not when the pen gets to it) is exact:
    // asking less often costs nothing, and the line isn't spent on requests
    if (queryPending) queryGap = (millis() - querySentAt < 300) ? 2000 : QUERY_GAP_MS;
    queryPending = false;
}

void pollRx() {
    int c;
    while ((c = rxRead()) >= 0) {
        c &= 0x7F;
        if (c >= 0x20 && c <= 0x3F) {
            if (rxLen == 0) txAtReply = txNow();       // (the reply began: its count is from here)
            if (rxLen < 6) rxBlock[rxLen++] = c;
            else { for (uint8_t i = 0; i < 5; i++) rxBlock[i] = rxBlock[i + 1]; rxBlock[5] = c; }
        } else if (c >= 0x40 && c <= 0x5F) {
            if (rxLen == 6 && (c & 0x07) == 0x02) {               // a status response
                uint16_t v1 = ((uint16_t)(rxBlock[0] & 0x1F) << 11) | ((rxBlock[2] & 0x1F) << 6)
                            | ((rxBlock[4] & 0x1F) << 1) | ((c >> 4) & 1);
                uint16_t v2 = ((uint16_t)(rxBlock[1] & 0x1F) << 11) | ((rxBlock[3] & 0x1F) << 6)
                            | ((rxBlock[5] & 0x1F) << 1) | ((c >> 3) & 1);
                takeReply(v1, v2);
            }
            rxLen = 0;
        } else rxLen = 0;               // CR, EOT, anything else: a block boundary
    }
}

void sendQuery() {
    tekRaw(0x1B); tekRaw(PLOTTER_ADDR); tekRaw('O'); tekRaw('1'); tekRaw(0x1A);   // ESC A O 1 SUB
    queryPending = true; querySentAt = millis(); nQueries++;
    // The 4662 goes back to the mode it was in once the command is processed
    // (Figure 3-3, p. 3-5: Graph -> ESC -> graph attention -> Graph), and a
    // request goes only between coordinates: a polyline carries on, with no
    // GS and no move (which lifted the pen mid-stroke: a bump every ~600
    // bytes). !g 1 brings back v5-v7's re-entry, should a plotter need it.
    if (queryReenter) { needsMove = true; inAlpha = false; }
}

// Does the plotter answer? Ask once and wait a little (serving the bus).
void probePlotter() {
    lastProbeAt = millis();
    while (tekQueued()) gpibService();
    sendQuery();
    while (queryPending && millis() - querySentAt < PROBE_MS) { pollRx(); gpibService(); }
    bool was = statusMode;
    statusMode = !queryPending;
    if (!statusMode) limitCount = queuedCount;
    queryPending = false;
    if (statusMode && (lastFree > emptyFree)) emptyFree = lastFree;   // (idle at the probe)
    if (DEBUG_ENABLED && statusMode != was) {
        if (statusMode) { Serial.print(F("[4662] status mode: buffer free ")); Serial.println(lastFree); }
        else Serial.println(F("[4662] no status reply: timed pacing (check D13 <- MAX3232 RXD)"));
    }
}

// --- fallback: v3's timed pacing ---
uint16_t paceSpeed = PACE_SPEED_ADU_S, paceVector = PACE_VECTOR_MS, pacePen = PACE_PEN_MS,
         paceChar = PACE_CHAR_MS, paceLead = PACE_LEAD_MS;
unsigned long penFreeAt = 0, nPaceWaits = 0;

void timedWork(unsigned long cost) {
    unsigned long now = millis();
    if ((long)(penFreeAt - now) < 0) penFreeAt = now;
    if ((long)(penFreeAt - now) > (long)paceLead) {
        nPaceWaits++;
        while ((long)(penFreeAt - millis()) > (long)paceLead) gpibService();
    }
    penFreeAt += cost;
}

int penX = 0, penY = 0;
bool penIsDown = false;
int segFromX = 0, segFromY = 0;         // where the last stroke started (it ends at penX, penY)
uint16_t retraceAdu = RETRACE_ADU;

unsigned long travelMs(int x, int y) {
    long dx = labs((long)x - penX), dy = labs((long)y - penY);
    long d = dx > dy ? dx + dy / 2 : dy + dx / 2;
    return (unsigned long)(d * 1000L / (paceSpeed ? paceSpeed : 1)) + paceVector;
}

// Wait until the 4662 has done everything sent so far (a reply showing its
// buffer empty: a reply comes when the pen reaches the request, or at once),
// then pause ms more. Serves the bus while it waits. Timed mode: the clock.
void settle(uint16_t ms) {
    if (statusMode && emptyFree > 0) {
        unsigned long t0 = millis(), lastAsk = 0, seen = nReplies;
        long freeEst = lastFree;            // its free bytes: from each reply, less our requests since
        for (;;) {
            // ask (queued behind the label: a reply comes after it), but a
            // request is 5 bytes in its buffer: only with room for it, or
            // after 8 s (a long stroke takes ~4 s: it has eaten some)
            if (!queryPending && (freeEst >= 13 || millis() - lastAsk >= 8000)) {
                sendQuery(); lastAsk = millis(); freeEst -= 5;
            }
            while (queryPending && millis() - querySentAt < STATUS_TIMEOUT) { pollRx(); gpibService(); }
            if (nReplies != seen) { seen = nReplies; freeEst = lastFree; }
            if (queryPending) { queryPending = false; break; }     // (no reply: just pause)
            if (lastFree >= emptyFree - 8) break;
            if (millis() - t0 > 120000UL) break;
            unsigned long t = millis(); while (millis() - t < 250) gpibService();
        }
    } else {
        while ((long)(penFreeAt - millis()) > 0) gpibService();
    }
    unsigned long t = millis();
    while (millis() - t < ms) gpibService();
}

// Room for n more bytes in the plotter, by asking it (status mode) or by
// the clock (timed mode, cost ms). Serves the bus while it waits. In status
// mode it asks ahead of need, so the line rarely waits for a reply.
void plotterRoom(uint8_t n, unsigned long cost) {
    if (!statusMode) {
        if (millis() - lastProbeAt > 60000UL && tekQueued() == 0) probePlotter();   // plotter on now?
        if (!statusMode) { timedWork(cost); return; }
    }
    for (;;) {
        pollRx();
        if (!queryPending && roomLeft() < QUERY_AT && millis() - querySentAt >= queryGap) {
            sendQuery();                // (5 bytes; no room check: the margin is for it)
            continue;
        }
        if (roomLeft() >= (long)n) return;
        if (queryPending && millis() - querySentAt > STATUS_TIMEOUT) {
            queryPending = false; statusMode = false; lastProbeAt = millis();
            if (DEBUG_ENABLED) Serial.println(F("[4662] status reply lost: timed pacing"));
            timedWork(cost); return;
        }
        gpibService();
    }
}

// ============================================================================
// TEK 4662 OUTPUT
// ============================================================================

#define TEK_GS  0x1D
#define TEK_US  0x1F
#define TEK_MAX_X 4095L
#define TEK_MAX_Y 2731L

// One coordinate, 12-bit, with only the bytes Table 3-3 says must go:
// HIY if it changed; EB and LOY if EB changed; LOY if it or HIX changed;
// HIX if it changed; LOX always. In full when the plotter's graphic memory
// may differ from what we last sent.
void tekSendCoord12(int x, int y) {
    uint8_t hiy = 0x20 | ((y >> 7) & 0x1F);
    uint8_t eb  = 0x60 | ((y & 0x03) << 2) | (x & 0x03);
    uint8_t loy = 0x60 | ((y >> 2) & 0x1F);
    uint8_t hix = 0x20 | ((x >> 7) & 0x1F);
    uint8_t lox = 0x40 | ((x >> 2) & 0x1F);
    bool full = !coordKnown;
    bool sEB = full || eb != lastEB, sHiX = full || hix != lastHiX;
    if (full || hiy != lastHiY) tekRaw(hiy);
    if (sEB) tekRaw(eb);
    if (sEB || sHiX || loy != lastLoY) tekRaw(loy);
    if (sHiX) tekRaw(hix);
    tekRaw(lox);
    lastHiY = hiy; lastEB = eb; lastLoY = loy; lastHiX = hix;
    coordKnown = true;
}

// After a label, before anything else goes: the switches above.
void leaveLabel() {
    if (!afterLabel) return;
    afterLabel = false;
    if (labelBs) {
        plotterRoom(2, paceChar);
        if (!inAlpha) { tekRaw(TEK_US); inAlpha = true; }
        tekRaw(0x08);                   // BS: back one character space, pen up
    }
    if (labelSettle) settle(labelSettle);
}

// Lift the pen with a short pen-up move back along the stroke just drawn,
// so the ~1 mm the pen drags while it lifts lands on that stroke's ink.
void liftAlongStroke() {
    if (!penIsDown) return;
    long dx = (long)segFromX - penX, dy = (long)segFromY - penY;
    float len = sqrt((float)dx * dx + (float)dy * dy);
    if (retraceAdu == 0 || len < 1.0f) return;          // (no stroke to go back along: lift in place)
    float d = len < retraceAdu ? len : (float)retraceAdu;
    int rx = penX + (int)lround(dx * d / len), ry = penY + (int)lround(dy * d / len);
    plotterRoom(6, travelMs(rx, ry) + pacePen);
    tekRaw(TEK_GS);                     // the first coordinate after GS is a pen-up move
    tekSendCoord12(rx, ry);
    penX = rx; penY = ry; penIsDown = false;
    needsMove = false; inAlpha = false;
}

void tekMoveTo(int x, int y) {
    x = constrain(x, 0, (int)TEK_MAX_X); y = constrain(y, 0, (int)TEK_MAX_Y);
    leaveLabel();
    liftAlongStroke();
    plotterRoom(6, travelMs(x, y) + (penIsDown ? pacePen : 0));
    tekRaw(TEK_GS);
    tekSendCoord12(x, y);
    penX = x; penY = y; penIsDown = false;
    needsMove = false; inAlpha = false;
}

void tekDrawTo(int x, int y) {
    x = constrain(x, 0, (int)TEK_MAX_X); y = constrain(y, 0, (int)TEK_MAX_Y);
    leaveLabel();
    plotterRoom(11, travelMs(x, y) + (penIsDown ? 0 : pacePen));  // (may ask: then needsMove)
    if (needsMove) {                    // back into graph mode without the bell:
        tekRaw(TEK_GS);                 //  GS and a move to where the pen is (p. 3-6)
        tekSendCoord12(penX, penY);
        needsMove = false;
    }
    tekSendCoord12(x, y);
    segFromX = penX; segFromY = penY;
    penX = x; penY = y; penIsDown = true; inAlpha = false;
}

void tekText(const char* s) {
    if (penIsDown && *s) {              // a label right after a stroke: lift along it, then back
        int px = penX, py = penY;
        liftAlongStroke();
        if (penX != px || penY != py) tekMoveTo(px, py);
    }
    leaveLabel();                       // (two labels in a row: settle between them too)
    char prev = 0;
    while (*s) {
        if (*s == ' ' && prev && prev != ' ' && spaceSettle) settle(spaceSettle);
        plotterRoom(2, paceChar + (penIsDown ? pacePen : 0));
        penIsDown = false;
        if (!inAlpha) { tekRaw(TEK_US); inAlpha = true; }
        prev = *s;
        tekRaw((uint8_t)*s++);
    }
    needsMove = true;
    coordKnown = false;                 // printing moves the pen: the next coordinate in full
    afterLabel = true;
}

// ============================================================================
// HP-GL PARSER
// ============================================================================

#define HPGL_MAX_X 10365L
#define HPGL_MAX_Y  7962L
#define ETX 0x03

bool penDown = false;
#define CMD_BUF_SIZE 256
char cmdBuf[CMD_BUF_SIZE];
uint8_t cmdLen = 0;
bool inLabel = false;
bool charArg = false;                   // SM, DT: the character after the mnemonic is theirs

int hpglToTekX(long hx) { return (int)((hx * TEK_MAX_X) / HPGL_MAX_X); }
int hpglToTekY(long hy) { return (int)((hy * TEK_MAX_Y) / HPGL_MAX_Y); }

const char* skipSep(const char* p) {
    while (*p == ' ' || *p == ',') p++;
    return p;
}

bool parseNumber(const char** pp, long* value) {
    const char* p = skipSep(*pp);
    if (*p == '\0' || *p == ';') return false;
    if (*p != '-' && *p != '+' && (*p < '0' || *p > '9')) return false;
    *value = 0;
    bool negative = false;
    if (*p == '-') { negative = true; p++; }
    else if (*p == '+') { p++; }
    if (*p < '0' || *p > '9') return false;
    while (*p >= '0' && *p <= '9') { *value = (*value * 10) + (*p - '0'); p++; }
    if (*p == '.') { p++; while (*p >= '0' && *p <= '9') p++; }
    if (negative) *value = -(*value);
    *pp = p;
    return true;
}

void parseCoordinates(const char* args) {
    const char* p = args;
    long x, y;
    while (true) {
        p = skipSep(p);
        if (!parseNumber(&p, &x)) break;
        p = skipSep(p);
        if (!parseNumber(&p, &y)) break;
        int tx = hpglToTekX(x), ty = hpglToTekY(y);
        if (penDown) tekDrawTo(tx, ty); else tekMoveTo(tx, ty);
    }
}

void processCommand(const char* cmd, uint8_t len) {
    if (len < 2) return;
    char c1 = cmd[0], c2 = cmd[1];
    if (c1 >= 'a' && c1 <= 'z') c1 -= 32;
    if (c2 >= 'a' && c2 <= 'z') c2 -= 32;
    const char* args = cmd + 2;

    if (c1 == 'I' && c2 == 'N') {
        penDown = false; needsMove = true; coordKnown = false;
        tekMoveTo(0, 0);
        if (DEBUG_ENABLED) Serial.println(F("  IN"));
    } else if (c1 == 'S' && c2 == 'P') {
        long pen = 0;
        parseNumber(&args, &pen);
        if (pen == 0) { penDown = false; needsMove = true; }
        if (DEBUG_ENABLED) { Serial.print(F("  SP")); Serial.println(pen); }
    } else if (c1 == 'P' && c2 == 'U') {
        penDown = false; needsMove = true;
        if (DEBUG_ENABLED) Serial.println(F("  PU"));
        parseCoordinates(args);
    } else if (c1 == 'P' && c2 == 'D') {
        penDown = true;
        if (DEBUG_ENABLED) Serial.println(F("  PD"));
        parseCoordinates(args);
    } else if (c1 == 'P' && c2 == 'A') {
        if (DEBUG_ENABLED) Serial.println(F("  PA"));
        parseCoordinates(args);
    } else if (c1 == 'L' && c2 == 'B') {
        if (DEBUG_ENABLED) { Serial.print(F("  LB: ")); Serial.println(args); }
        tekText(args);
    } else if (DEBUG_ENABLED) {
        Serial.print(F("  ??")); Serial.write(c1); Serial.println(c2);
    }
}

// PU, PD and PA take their coordinates as they come, a pair at a time, so a
// command of any length draws all of it (v1-v4 kept a whole command in
// cmdBuf and cut anything past 255 characters).
bool inCoords = false;
char numBuf[16]; uint8_t numLen = 0;
bool haveX = false; long coordX = 0;

void flushNumber() {
    if (numLen == 0) return;
    numBuf[numLen] = '\0'; numLen = 0;
    const char* p = numBuf; long v;
    if (!parseNumber(&p, &v)) return;
    if (!haveX) { coordX = v; haveX = true; return; }
    haveX = false;
    int tx = hpglToTekX(coordX), ty = hpglToTekY(v);
    if (penDown) tekDrawTo(tx, ty); else tekMoveTo(tx, ty);
}

void endCommand() {
    if (inCoords) { flushNumber(); inCoords = false; haveX = false; cmdLen = 0; return; }
    if (cmdLen >= 2) { cmdBuf[cmdLen] = '\0'; processCommand(cmdBuf, cmdLen); }
    cmdLen = 0; inLabel = false;
}

void feedChar(char c) {
    if (inLabel) {                      // LB (BL, WD) text, up to ETX (';' is text here)
        if (c == ETX) { endCommand(); return; }
        if (c == '\r' || c == '\n') return;
        if (cmdLen < CMD_BUF_SIZE - 1) cmdBuf[cmdLen++] = c;
        return;
    }
    if (c == ';') { endCommand(); return; }
    // ';' is optional in HP-GL: a letter after a mnemonic (and its numbers)
    // starts the next one. SM and DT take one character, which may be a letter.
    if ((uint8_t)((c | 0x20) - 'a') < 26 && cmdLen >= 2 + charArg) endCommand();
    if (inCoords) {                     // PU/PD/PA coordinates
        if ((c >= '0' && c <= '9') || c == '.' || ((c == '-' || c == '+') && numLen == 0)) {
            if (numLen < sizeof(numBuf) - 1) numBuf[numLen++] = c;
        } else if (c == '-' || c == '+') {      // a sign after a number starts the next one
            flushNumber(); numBuf[numLen++] = c;
        } else flushNumber();           // a separator (comma, space, line end)
        return;
    }
    if (c == '\r' || c == '\n' || (c == ' ' && cmdLen == 0)) return;
    if (c == ETX) return;
    if (cmdLen < CMD_BUF_SIZE - 1) cmdBuf[cmdLen++] = c;
    if (cmdLen == 2) {
        char c1 = cmdBuf[0] & ~0x20, c2 = cmdBuf[1] & ~0x20;      // (upper case)
        charArg = (c1 == 'S' && c2 == 'M') || (c1 == 'D' && c2 == 'T');
        if ((c1 == 'L' && c2 == 'B') || (c1 == 'B' && c2 == 'L') || (c1 == 'W' && c2 == 'D')) inLabel = true;
        else if (c1 == 'P' && (c2 == 'U' || c2 == 'D' || c2 == 'A')) {
            cmdBuf[2] = '\0'; processCommand(cmdBuf, 2);        // the pen state, no coordinates yet
            inCoords = true; numLen = 0; haveX = false;
        }
    }
}

// ============================================================================
// SERIAL POLL STATUS BYTE
// ============================================================================

uint8_t statusByte() {
    uint8_t used = ringCount();
    uint8_t room = used >= RING_HOLD ? 0 : (uint8_t)((RING_HOLD - used) / 4);   // what fits without a hold
    if (room > 63) room = 63;
    bool idle = ringEmpty() && tekQueued() == 0 && cmdLen == 0;
    return (idle ? 0x80 : 0) | room;
}

// ============================================================================
// USB CONSOLE
// ============================================================================

void printLine(const __FlashStringHelper* name, bool high) {
    Serial.print(name); Serial.print(high ? F("hi ") : F("LO "));
}

void printPace() {
    Serial.print(F("pen lift: !r ")); Serial.print(retraceAdu); Serial.println(F(" ADU back along the stroke"));
    Serial.print(F("labels: !a ")); Serial.print(labelSettle); Serial.print(F(" ms settle after, !b "));
    Serial.print(labelBs); Serial.print(F(" BS after, !w ")); Serial.print(spaceSettle);
    Serial.print(F(" ms settle before spaces (empty buffer reads ")); Serial.print(emptyFree); Serial.println(F(")"));
    Serial.print(F("status requests: !g ")); Serial.print(queryReenter);
    Serial.println(queryReenter ? F(" (re-enter the mode after each: lifts the pen)") : F(" (the stroke carries on)"));
    Serial.print(F("timed pacing: !s ")); Serial.print(paceSpeed);
    Serial.print(F(" ADU/s  !v ")); Serial.print(paceVector);
    Serial.print(F(" ms/vector  !p ")); Serial.print(pacePen);
    Serial.print(F(" ms/pen  !c ")); Serial.print(paceChar);
    Serial.print(F(" ms/char  !l ")); Serial.print(paceLead);
    Serial.print(F(" ms lead; waits ")); Serial.println(nPaceWaits);
}

void printFlow() {
    Serial.print(F("plotter: ")); Serial.print(statusMode ? F("status mode") : F("timed pacing"));
    Serial.print(F(", last free ")); Serial.print(lastFree);
    Serial.print(F(", room ")); Serial.print(roomLeft());
    Serial.print(F(", sent ")); Serial.print(txNow());
    Serial.print(F(", queries ")); Serial.print(nQueries);
    Serial.print(F(", replies ")); Serial.print(nReplies);
    Serial.println(queryPending ? F(", waiting for a reply") : F(""));
}

void printStatus() {
    Serial.println(F("--- bus lines (LO = asserted) ---"));
    printLine(F("ATN "), PINB & B_ATN);  printLine(F("DAV "), PIND & D_DAV);
    printLine(F("NRFD "), PINB & B_NRFD); printLine(F("NDAC "), PINB & B_NDAC);
    printLine(F("EOI "), PINC & C_EOI);  printLine(F("IFC "), PINB & B_IFC);
    printLine(F("REN "), PINC & C_REN);
    Serial.print(F("data 0x")); Serial.println(readDataBus(), HEX);
    Serial.print(F("we drive: NRFD ")); Serial.print((DDRB & B_NRFD) ? F("low") : F("off"));
    Serial.print(F(", NDAC ")); Serial.print((DDRB & B_NDAC) ? F("low") : F("off"));
    Serial.print(F(", DAV ")); Serial.println((DDRD & D_DAV) ? F("low") : F("off"));
    Serial.print(F("listener ")); Serial.print(isListener ? F("yes") : F("no"));
    Serial.print(F(", talker ")); Serial.print(isTalker ? F("yes") : F("no"));
    Serial.print(F(", state ")); Serial.print((int)hsState);
    Serial.print(F(", commands ")); Serial.print(nCmd);
    Serial.print(F(", data ")); Serial.print(nData);
    Serial.print(F(", dropped ")); Serial.print(nDropped);
    Serial.print(F(", polls ")); Serial.print(nPolls);
    Serial.print(F(", ring ")); Serial.print(ringCount());
    Serial.print(F(", to plotter ")); Serial.print(tekQueued());
    Serial.print(F(", poll byte 0x")); Serial.println(statusByte(), HEX);
    printFlow();
    printPace();
}

char paceLine[16]; uint8_t paceLen = 0; bool inPace = false;
void paceCommand() {
    paceLine[paceLen] = 0;
    char k = paceLen ? paceLine[0] : 0;
    long v = atol(paceLine + 1);
    if (k && v > 0 && v < 60000L) {
        if (k == 's') paceSpeed = v; else if (k == 'v') paceVector = v;
        else if (k == 'p') pacePen = v; else if (k == 'c') paceChar = v;
        else if (k == 'l') paceLead = v;
    }
    if (k == 'r' && paceLen > 1 && v >= 0 && v <= 400) retraceAdu = v;     // (0 allowed: off)
    if (k == 'a' && paceLen > 1 && v >= 0 && v <= 5000) labelSettle = v;
    if (k == 'w' && paceLen > 1 && v >= 0 && v <= 5000) spaceSettle = v;
    if (k == 'b' && paceLen > 1) labelBs = v ? 1 : 0;
    if (k == 'g' && paceLen > 1) queryReenter = v ? 1 : 0;
    printPace();
    paceLen = 0; inPace = false;
}

// ============================================================================
// MAIN
// ============================================================================

void setup() {
    gpibBegin();                        // off the bus before anything else
    Serial.begin(9600);
    uartBegin();
    sei();
    Serial.println(F("GPIB HP-GL to Tek 4662 Translator v7.3"));
    Serial.print(F("GPIB address: ")); Serial.println(GPIB_ADDRESS);
    Serial.print(F("Listen Only: ")); Serial.println(LISTEN_ONLY ? F("YES") : F("NO"));
    Serial.println(F("USB: HP-GL for testing; '?' bus and flow, '#' ask the plotter, '!' timed pacing"));
    probePlotter();
    if (!statusMode && DEBUG_ENABLED) Serial.println(F("[4662] no status reply: timed pacing for now"));
    Serial.println();
    Serial.println(F("Ready. Waiting for GPIB data..."));
}

void loop() {
    gpibService();
    pollRx();

    if (events) {
        uint8_t e; cli(); e = events; events = 0; sei();
        if (DEBUG_ENABLED) {
            if (e & EV_ADDRESSED) Serial.println(F("[GPIB] Addressed as listener"));
            if (e & EV_UNLISTENED) Serial.println(F("[GPIB] Unlistened"));
            if (e & EV_IFC) Serial.println(F("[GPIB] Interface clear"));
        }
    }

    while (Serial.available()) {        // USB: HP-GL for testing, or a console command
        char c = Serial.read();
        if (inPace) {
            if (c == '\n' || c == '\r') paceCommand();
            else if (c != ' ' && paceLen < sizeof(paceLine) - 1) paceLine[paceLen++] = c;
            continue;
        }
        if (cmdLen == 0 && !inLabel) {
            if (c == '!') { inPace = true; paceLen = 0; continue; }
            if (c == '?') { printStatus(); continue; }
            if (c == '#') { probePlotter(); printFlow(); continue; }
        }
        if (c == '\n' || c == '\r') { if (cmdLen > 0) endCommand(); }
        else feedChar(c);
        gpibService();
    }

    for (uint8_t n = 0; n < 8 && !ringEmpty() && tekQueued() < 64; n++) {
        char c = (char)ring[ringTail]; ringTail++;
        feedChar(c);
        gpibService();
    }
}
