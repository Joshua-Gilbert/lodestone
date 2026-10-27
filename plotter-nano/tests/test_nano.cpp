// Host tests for the Nano's sketch: the .ino compiled with g++ against stub
// Arduino and AVR headers, fed HP-GL a character at a time.
//
//   cd plotter-nano && g++ -std=gnu++17 -Wall -I tests/stubs -I gpib_hpgl_tek4662
//       tests/test_nano.cpp -o /tmp/test_nano && /tmp/test_nano
//
// What goes to the 4662 is read back from the sketch's own pen state
// (penX, penY, penIsDown) each time a character puts bytes in its queue.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <string>
#include <vector>

// --- what Arduino.h would give the sketch ---
class __FlashStringHelper;
#define F(s) (reinterpret_cast<const __FlashStringHelper *>(s))
#define HEX 16
#define constrain(a, lo, hi) ((a) < (lo) ? (lo) : ((a) > (hi) ? (hi) : (a)))
static unsigned long fakeMs = 0;
unsigned long millis() { return fakeMs += 1; }
struct FakeSerial {
    void begin(long) {}
    int available() { return 0; }
    int read() { return -1; }
    template <class T> void print(T) {}
    template <class T> void print(T, int) {}
    template <class T> void println(T) {}
    template <class T> void println(T, int) {}
    void println() {}
    void write(char) {}
} Serial;

#include <avr/io.h>
#include "gpib_hpgl_tek4662.ino"

// --- harness ---
static int failures = 0;

struct Ev { char kind; int x, y; };    // 'D' a draw, 'U' a move (pen up), 'L' a label

static bool operator==(const Ev& a, const Ev& b) { return a.kind == b.kind && a.x == b.x && a.y == b.y; }

static std::string show(const std::vector<Ev>& v) {
    std::string s; char b[40];
    for (const Ev& e : v) { snprintf(b, sizeof b, " %c(%d,%d)", e.kind, e.x, e.y); s += b; }
    return s;
}

static void resetSketch() {
    tekTail = tekHead;
    inCoords = false; cmdLen = 0; numLen = 0; haveX = false; inLabel = false;
    penDown = false; penIsDown = false; needsMove = true; coordKnown = false; afterLabel = false;
    penX = penY = 0;
    statusMode = true; queryPending = false;   // room enough, and no waiting
    limitCount = queuedCount + 1000000UL;
}

static std::vector<Ev> run(const char* hpgl) {
    resetSketch();
    std::vector<Ev> out;
    for (const char* p = hpgl; *p; p++) {
        uint32_t q = queuedCount;
        feedChar(*p);
        tekTail = tekHead;              // (the UART is not running: drain it)
        if (queuedCount != q)
            out.push_back({afterLabel ? 'L' : penIsDown ? 'D' : 'U', penX, penY});
    }
    return out;
}

static Ev P(char kind, long hx, long hy) {     // an HP-GL point as the Tek point it becomes
    return {kind, constrain(hpglToTekX(hx), 0, (int)TEK_MAX_X), constrain(hpglToTekY(hy), 0, (int)TEK_MAX_Y)};
}

static void expect(const char* name, const char* hpgl, std::vector<Ev> want) {
    std::vector<Ev> got = run(hpgl);
    bool ok = got == want;
    if (!ok) failures++;
    printf("%s %s\n", ok ? "ok  " : "FAIL", name);
    if (!ok) printf("     want%s\n     got %s\n", show(want).c_str(), show(got).c_str());
}

static void check(const char* name, bool ok) {
    if (!ok) failures++;
    printf("%s %s\n", ok ? "ok  " : "FAIL", name);
}

// X62: a serial poll. The byte goes on DIO in one gpibService() pass and DAV
// only in a later one, so the byte has settled for T1 (2 us) before DAV.
static void testPoll() {
    resetSketch();
    ringTail = ringHead; cmdLen = 0;
    DDRB = DDRC = 0; DDRD = D_TEKTX;
    PINB = B_ATN | B_IFC | B_NRFD;      // ATN, IFC high; the controller ready: NRFD high, NDAC low
    PINC = PIND = 0xFF;
    isListener = false; isTalker = true; spollMode = true; spollSent = false; talkState = 0;
    hsState = IDLE;
    uint8_t v = statusByte();
    uint8_t dio = (uint8_t)((v & 0x0F) << 2);
    gpibService();
    check("poll: the byte on DIO", (DDRD & D_DIO) == dio && (DDRC & C_DIO) == (v >> 4) && talkState == 1);
    check("poll: no DAV in the same pass", !(DDRD & D_DAV));
    gpibService();
    check("poll: DAV on the next pass", (DDRD & D_DAV) && (DDRD & D_DIO) == dio && talkState == 2);
    PINB |= B_NDAC;                     // the controller has taken it
    gpibService();
    check("poll: released after", !(DDRD & (D_DAV | D_DIO)) && !(DDRC & C_DIO) && spollSent && talkState == 0);
    gpibService();
    check("poll: one byte per poll", !(DDRD & D_DAV) && talkState == 0);
    isTalker = spollMode = false;
}

int main() {
    // X61: a mnemonic straight after coordinates ends them (';' is optional)
    expect("PD..PU without ';'", "PD100,200PU300,400;",
           {P('D', 100, 200), P('U', 300, 400)});
    expect("lower case", "pd100,200pu300,400;",
           {P('D', 100, 200), P('U', 300, 400)});
    expect("with ';' as before", "PD100,200;PU300,400;",
           {P('D', 100, 200), P('U', 300, 400)});
    expect("a run of mnemonics", "PU10,20PD100,200,300,400PA500,600PU700,800;",
           {P('U', 10, 20), P('D', 100, 200), P('D', 300, 400), P('D', 500, 600), P('U', 700, 800)});
    expect("space and line end before it", "PD100,200 PU300,400\r\nPD500,600;",
           {P('D', 100, 200), P('U', 300, 400), P('D', 500, 600)});
    expect("an odd coordinate is dropped", "PD100,200,300PU400,500;",
           {P('D', 100, 200), P('U', 400, 500)});
    expect("signs still start numbers", "PU100,200PD-50,+300+400,500;",
           {P('U', 100, 200), P('D', -50, 300), P('D', 400, 500)});
    expect("a label after coordinates", "PD100,200LBhi\x03PU300,400;",
           {P('D', 100, 200), P('L', 100, 200), P('U', 300, 400)});
    expect("PU with no coordinates", "IN;PU100,200PD300,400PU;PD500,600;",
           {P('U', 0, 0), P('U', 100, 200), P('D', 300, 400), P('D', 500, 600)});
    testPoll();

    printf(failures ? "%d FAILED\n" : "all passed\n", failures);
    return failures ? 1 : 0;
}
