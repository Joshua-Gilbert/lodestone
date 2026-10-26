/*
 * gpib_hpgl_tek4662.ino  (v4, for Lodestone's shared bus)
 *
 * GPIB HP-GL to Tektronix 4662 translator. A GPIB listener at GPIB_ADDRESS
 * that takes HP-GL and sends it to the 4662 as Tek commands at 1200 baud.
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
        cur = tekQ[tekTail]; tekTail++;
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
    tekQ[tekHead] = b; tekHead++;
}

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
        // fall through
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

bool statusMode = false;                // the plotter answers READ STATUS
bool queryPending = false;
unsigned long querySentAt = 0, lastProbeAt = 0, noQueryBefore = 0;
long budget = 0;                        // bytes we may still send before asking again
long lastFree = -1;                     // what the plotter last said
unsigned long nQueries = 0, nReplies = 0;
bool needsMove = true;                  // the next DRAW must re-enter graph mode (GS BEL)
bool inAlpha = false;

// The reply: 7 characters (070-4164-00 Figure 3-9 B): 1-6 are 0x20-0x3F with
// five bits each, 7 is 0x40-0x5F with the two LSBs and the block type.
uint8_t rxBlock[7]; uint8_t rxLen = 0;

void takeReply(uint16_t v1, uint16_t v2) {
    if (v1 != 1) return;                // not status word 1
    lastFree = v2 & 0x7FF;
    budget = lastFree - STATUS_MARGIN;
    nReplies++;
    if (queryPending) {
        queryPending = false;
        if (budget < 64) noQueryBefore = millis() + 300;  // nearly full: let the pen work a little
    }
}

void pollRx() {
    int c;
    while ((c = rxRead()) >= 0) {
        c &= 0x7F;
        if (c >= 0x20 && c <= 0x3F) {
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
    needsMove = true; inAlpha = false;  // the next element re-enters its mode
}

// Does the plotter answer? Ask once and wait a little (serving the bus).
void probePlotter() {
    lastProbeAt = millis();
    while (tekQueued()) gpibService();
    sendQuery();
    while (queryPending && millis() - querySentAt < PROBE_MS) { pollRx(); gpibService(); }
    bool was = statusMode;
    statusMode = !queryPending;
    queryPending = false;
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

unsigned long travelMs(int x, int y) {
    long dx = labs((long)x - penX), dy = labs((long)y - penY);
    long d = dx > dy ? dx + dy / 2 : dy + dx / 2;
    return (unsigned long)(d * 1000L / (paceSpeed ? paceSpeed : 1)) + paceVector;
}

// Room for n more bytes in the plotter, by asking it (status mode) or by
// the clock (timed mode, cost ms). Serves the bus while it waits.
void plotterRoom(uint8_t n, unsigned long cost) {
    if (!statusMode) {
        if (millis() - lastProbeAt > 60000UL && tekQueued() == 0) probePlotter();   // plotter on now?
        if (!statusMode) { timedWork(cost); return; }
    }
    for (;;) {
        pollRx();
        if (!queryPending && budget >= n) { budget -= n; return; }
        if (!queryPending && (long)(millis() - noQueryBefore) >= 0) sendQuery();
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

void tekSendCoord12(int x, int y) {
    tekRaw((uint8_t)(0x20 | ((y >> 7) & 0x1F)));
    tekRaw((uint8_t)(0x60 | ((y & 0x03) << 2) | (x & 0x03)));
    tekRaw((uint8_t)(0x60 | ((y >> 2) & 0x1F)));
    tekRaw((uint8_t)(0x20 | ((x >> 7) & 0x1F)));
    tekRaw((uint8_t)(0x40 | ((x >> 2) & 0x1F)));
}

void tekMoveTo(int x, int y) {
    x = constrain(x, 0, (int)TEK_MAX_X); y = constrain(y, 0, (int)TEK_MAX_Y);
    plotterRoom(6, travelMs(x, y) + (penIsDown ? pacePen : 0));
    tekRaw(TEK_GS);
    tekSendCoord12(x, y);
    penX = x; penY = y; penIsDown = false;
    needsMove = false; inAlpha = false;
}

void tekDrawTo(int x, int y) {
    x = constrain(x, 0, (int)TEK_MAX_X); y = constrain(y, 0, (int)TEK_MAX_Y);
    plotterRoom(7, travelMs(x, y) + (penIsDown ? 0 : pacePen));   // (may ask: then needsMove)
    if (needsMove) {
        tekRaw(TEK_GS);
        tekRaw(0x07);                   // BEL: the first coordinate is a DRAW
        needsMove = false;
    }
    tekSendCoord12(x, y);
    penX = x; penY = y; penIsDown = true; inAlpha = false;
}

void tekText(const char* s) {
    while (*s) {
        plotterRoom(2, paceChar + (penIsDown ? pacePen : 0));
        penIsDown = false;
        if (!inAlpha) { tekRaw(TEK_US); inAlpha = true; }
        tekRaw((uint8_t)*s++);
    }
    needsMove = true;
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
        penDown = false; needsMove = true;
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

void endCommand() {
    if (cmdLen >= 2) { cmdBuf[cmdLen] = '\0'; processCommand(cmdBuf, cmdLen); }
    cmdLen = 0; inLabel = false;
}

void feedChar(char c) {
    if (inLabel) {                      // LB text, up to ETX (';' is text here)
        if (c == ETX) { endCommand(); return; }
        if (c == '\r' || c == '\n') return;
        if (cmdLen < CMD_BUF_SIZE - 1) cmdBuf[cmdLen++] = c;
        return;
    }
    if (c == ';') { endCommand(); return; }
    if (c == '\r' || c == '\n' || (c == ' ' && cmdLen == 0)) return;
    if (c == ETX) return;
    if (cmdLen < CMD_BUF_SIZE - 1) cmdBuf[cmdLen++] = c;
    if (cmdLen == 2 && (cmdBuf[0] == 'L' || cmdBuf[0] == 'l') && (cmdBuf[1] == 'B' || cmdBuf[1] == 'b'))
        inLabel = true;
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
    Serial.print(F(", budget ")); Serial.print(budget);
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
    Serial.println(F("GPIB HP-GL to Tek 4662 Translator v4"));
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
