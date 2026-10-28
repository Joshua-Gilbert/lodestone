// Host tests for the Nano's sketch: the .ino compiled with g++ against stub
// Arduino and AVR headers, fed HP-GL a character at a time.
//
//   cd plotter-nano && g++ -std=gnu++17 -Wall -I tests/stubs -I gpib_hpgl_tek4662
//       tests/test_nano.cpp -o /tmp/test_nano && /tmp/test_nano
//
// What goes to the 4662 is read back from the bytes the sketch queues for it
// (decoded as the 4662 would: GS, then a move and draws; US, then text), with
// the GPIB lines idle, so the bus is served as on a quiet bus.

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

// --- the 4662's side: Tek bytes -> "U(x,y)" moves, "D(x,y)" draws, "L(text)" ---
typedef std::vector<std::string> Evs;
static struct {
    int mode;                           // 0 nothing yet, 1 GS (a move next), 2 drawing, 3 text, 4 ESC..SUB
    int before;                         // the mode an ESC command interrupted (it goes back to it: Figure 3-3)
    std::string esc;
    int ons;                            // PLOTTER ONs (ESC A E)
    std::vector<std::string> cmds;      // every ESC command, as "AJ30" (SUB left off)
    uint8_t hiy, eb, loy, hix;
    bool lastLo, loySeen;
    std::string text;
} tk;

static std::string pt(char k, int x, int y) { char b[32]; snprintf(b, sizeof b, "%c(%d,%d)", k, x, y); return b; }

static void endText(Evs& out) {
    if (tk.mode == 3 && !tk.text.empty()) out.push_back("L(" + tk.text + ")");
    tk.text.clear();
}

static void tekByte(uint8_t b, Evs& out) {
    if (tk.mode == 4) {                 // as p. 3-3: no arguments, one character, or numbers to SUB
        bool end = false;
        size_t n = tk.esc.size();
        if (b == 0x1A) end = true;
        else {
            tk.esc += (char)b;
            if (n == 0) end = !(b >= 'A' && b <= 'D');                 // a Style II escape
            else if (n == 1) end = strchr("EF(NQVMKL", b) != NULL;
            else if (n == 2) end = strchr("USR", tk.esc[1]) != NULL;
        }
        if (end) {
            if (tk.esc == "AE") tk.ons++;
            if (tk.esc != "AO1") tk.cmds.push_back(tk.esc);   // (not the Nano's status requests)
            tk.mode = tk.before;
        }
        return;
    }
    if (b == 0x1B) { endText(out); tk.before = tk.mode; tk.esc.clear(); tk.mode = 4; return; }
    if (b == TEK_GS) { endText(out); tk.mode = 1; tk.lastLo = tk.loySeen = false; return; }
    if (b == TEK_US) { tk.mode = 3; return; }
    if (tk.mode == 3) { tk.text += (char)b; return; }
    if (tk.mode == 0) { out.push_back("?"); return; }
    if (b >= 0x20 && b < 0x40) { if (tk.loySeen) tk.hix = b; else tk.hiy = b; tk.lastLo = false; }
    else if (b >= 0x60) { if (tk.lastLo) tk.eb = tk.loy; tk.loy = b; tk.lastLo = tk.loySeen = true; }
    else if (b >= 0x40) {               // LOX: the point is complete
        int x = ((tk.hix & 0x1F) << 7) | ((b & 0x1F) << 2) | (tk.eb & 3);
        int y = ((tk.hiy & 0x1F) << 7) | ((tk.loy & 0x1F) << 2) | ((tk.eb >> 2) & 3);
        out.push_back(pt(tk.mode == 1 ? 'U' : 'D', x, y));
        tk.mode = 2; tk.lastLo = tk.loySeen = false;
    } else out.push_back("?");
}

// --- harness ---
static int failures = 0;

static void busIdle() {                 // every line released (high), nothing driven
    PINB = B_ATN | B_IFC | B_NRFD | B_NDAC | B_RX;
    PINC = PIND = 0xFF;
    DDRB = DDRC = 0; DDRD = D_TEKTX;
    isListener = isTalker = spollMode = false; talkState = 0; hsState = IDLE;
}

static void resetSketch() {
    busIdle();
    tekTail = tekHead;
    inCoords = false; cmdLen = 0; numLen = 0; haveX = false; inLabel = false;
    penDown = false; penIsDown = false; needsMove = true; coordKnown = false; afterLabel = false;
    penX = penY = 0; retraceAdu = 0;
    statusMode = true; queryPending = false;   // room enough, and no waiting
    limitCount = queuedCount + 1000000UL;
    tk.mode = 0; tk.text.clear(); tk.ons = 0; tk.cmds.clear(); inAlpha = false;
    alphaDefaults(); tekTail = tekHead; tk.cmds.clear(); natState = 0;
    pageMode = 2; copySwitch = -1; copyMode = true; tekMaxY = 3123;
}

static Evs run(const char* hpgl, uint16_t retrace = 0) {
    resetSketch();
    retraceAdu = retrace;
    Evs out;
    for (const char* p = hpgl; *p; p++) {
        feedChar(*p);
        while (tekTail != tekHead) { tekByte(tekQ[tekTail], out); tekTail++; }   // (no UART here)
    }
    endText(out);
    return out;
}

static int tx(long hx) { return constrain(hpglToTekX(hx), 0, (int)TEK_MAX_X); }
static int ty(long hy) { return constrain(hpglToTekY(hy), 0, (int)TEK_MAX_Y); }
static std::string U(long hx, long hy) { return pt('U', tx(hx), ty(hy)); }   // HP-GL points as the Tek ones
static std::string D(long hx, long hy) { return pt('D', tx(hx), ty(hy)); }
static std::string L(const char* s) { return std::string("L(") + s + ")"; }

static std::string show(const Evs& v) { std::string s; for (const std::string& e : v) s += " " + e; return s; }

static void expect(const char* name, const char* hpgl, Evs want, uint16_t retrace = 0) {
    Evs got = run(hpgl, retrace);
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
    PINB &= ~B_NDAC;                    // the controller ready: NRFD high, NDAC low
    isTalker = true; spollMode = true; spollSent = false;
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
    busIdle();
}

// X63: the page follows the 4662's COPY MODE switch (status bit 14), at IN
// only; !m forces it; PLOTTER ON goes at every IN.
static void testPage() {
    run("IN;");
    check("page: PLOTTER ON at IN", tk.ons == 1);
    resetSketch();
    takeReply(1, 0x4000 | 500);
    check("page: status bit 14 is the Copy switch", copySwitch == 1 && lastFree == 500);
    takeReply(1, 700);
    check("page: bit 14 clear, standard", copySwitch == 0 && lastFree == 700);

    // (run() resets the page, so set it inside: feed by hand)
    struct Case { const char* name; uint8_t mode; int8_t sw; int top; };
    Case cases[] = {
        {"page: switch Copy -> 0-3123", 2, 1, 3123},
        {"page: switch standard -> 0-2730", 2, 0, 2730},
        {"page: not heard -> Copy (as before)", 2, -1, 3123},
        {"page: !m 0 over a Copy switch", 0, 1, 2730},
        {"page: !m 1 over a standard switch", 1, 0, 3123},
    };
    for (const Case& c : cases) {
        resetSketch(); pageMode = c.mode; copySwitch = c.sw;
        Evs out;
        for (const char* p = "IN;PU10365,7962;"; *p; p++) {
            feedChar(*p);
            while (tekTail != tekHead) { tekByte(tekQ[tekTail], out); tekTail++; }
        }
        Evs want = {pt('U', 0, 0), pt('U', 4095, c.top)};
        bool ok = out == want;
        check(c.name, ok);
        if (!ok) printf("     want%s\n     got %s\n", show(want).c_str(), show(out).c_str());
    }
    // a switch heard in the middle of a plot waits for the next IN
    resetSketch(); copySwitch = 1;
    Evs out;
    auto feed = [&](const char* h) { for (const char* p = h; *p; p++) {
        feedChar(*p); while (tekTail != tekHead) { tekByte(tekQ[tekTail], out); tekTail++; } } };
    feed("IN;PU0,7962;");
    copySwitch = 0;
    feed("PU10,7962;");
    check("page: no change until IN", out.size() == 3 && out[2] == pt('U', 3, 3123));
    feed("IN;PU0,7962;");
    check("page: the change at IN", out.size() == 5 && out[4] == pt('U', 0, 2730) && tk.ons == 2);
}

// the native commands the 4662 got, as "AI119,257 AJ90" (ESC and SUB left off)
static std::string cmds() {
    std::string r;
    for (const std::string& c : tk.cmds) {
        if (!r.empty()) r += ' ';
        for (char ch : c) { if ((uint8_t)ch < 0x20) { r += '^'; r += (char)(ch + 0x40); } else r += ch; }
    }
    return r;
}

static void expectCmds(const char* name, const char* hpgl, const char* want, Evs* evs = nullptr) {
    Evs got = run(hpgl);
    if (evs) *evs = got;
    std::string c = cmds();
    bool ok = c == want;
    check(name, ok);
    if (!ok) printf("     want %s\n     got  %s\n", want, c.c_str());
}

// X64: HP-GL's label size, direction and character sets as the 4662's alpha
// commands, sent before the label that needs them, only when they change.
static void testAlpha() {
    // SI 0.5,1 cm: 0.5*400*1.5*4095/10365 = 118.5 -> 119; 1*400*18/11*3123/7962 = 256.7 -> 257
    expectCmds("SI: ESC A I in ADUs, Copy Mode", "IN;SI0.5,1;PU100,100;LBhi\x03", "AE AV AI119,257");
    expectCmds("SR: % of the page", "SR2,3;LBx\x03", "AI123,153");          // 0.02*1.5*4095, 0.03*18/11*3123
    expectCmds("SR with no numbers: 0.75,1.5", "SR;LBx\x03", "AI46,77");
    expectCmds("SI with no numbers: the plotter's own", "SI0.5,1;LBx\x03SI;LBy\x03", "AI119,257 AI56,88");
    expectCmds("ES: extra space and lines", "SI0.5,1;ES1,0.5;LBx\x03", "AI237,385");
    expectCmds("sent once for labels of one size", "SI0.5,1;LBx\x03LBy\x03", "AI119,257");
    expectCmds("DI 0,1: 90 degrees", "DI0,1;LBx\x03", "AJ90");
    expectCmds("DI -1,0: 180", "DI-1,0;LBx\x03" "DI;LBy\x03", "AJ180 AJ0");
    expectCmds("DR 0,1: 90", "DR0,1;LBx\x03", "AJ90");
    expectCmds("DI 1,1: 45 on the page", "DI1,1;LBx\x03", "AJ45");
    expectCmds("nothing set, nothing sent", "LBplain\x03", "");
    {
        Evs e;
        expectCmds("CS, CA, SO and SI", "CS33;CA35;LBa\x0e" "b\x0f" "c\x03", "AT2 AT3 AT2", &e);
        check("  ... the text between, a font each", e == Evs({"L(a)", "L(b)", "L(c)"}));
    }
    expectCmds("SA, SS", "CA30;SA;LBx\x03SS;LBy\x03", "AT1 AT0");
    expectCmds("CS100-109: the 4662's fonts", "CS109;LBx\x03", "AT9");
    expectCmds("a set it hasn't: font 0", "CS34;LBx\x03", "");
    {
        Evs e;
        expectCmds("CR in a label: the margin at its start", "PU100,100;LBab\r\ncd\x03", "AJ0", &e);
        check("  ... CR and LF go to the plotter", e.size() == 2 && e[1] == "L(ab\r\ncd)");
    }
    expectCmds("IN resets the 4662's alpha", "SI0.5,1;LBx\x03IN;LBy\x03", "AI119,257 AE AV");
    expectCmds("DF resets it too", "DI0,1;LBx\x03" "DF;LBy\x03", "AJ90 AV");
}

// X65: the 4662's own commands, from an ESC, as they are.
static void testNative() {
    expectCmds("a command with numbers, to ';'", "\x1b" "AJ30;", "AJ30");
    expectCmds("... to SUB", "\x1b" "AJ30\x1a", "AJ30");
    {
        Evs e;
        expectCmds("... to a letter, which is HP-GL", "\x1b" "AT5PU100,200;", "AT5", &e);
        check("  ... the PU drawn", e.size() == 1 && e[0] == U(100, 200));
    }
    expectCmds("two numbers", "\x1b" "AI100,150;", "AI100,150");
    expectCmds("no arguments: ends at its code", "\x1b" "AEPU1,1;", "AE");
    expectCmds("a character argument", "\x1b" "ARZPU1,1;", "ARZ");
    expectCmds("Option 31: two-letter codes", "\x1b" "ABP2;" "\x1b" "ABY100;", "ABP2 ABY100");
    expectCmds("a Style II escape (ESC FF)", "\x1b\x0c", "^L");
    expectCmds("an exponent", "\x1b" "AJ0.3E+02;", "AJ0.3E+02");
    expectCmds("an ESC ends an HP-GL command", "PU100,200\x1b" "AL", "AL");
    {
        Evs e;
        expectCmds("in a stroke: back to the pen before drawing on", "PD100,200\x1b" "AK;PD300,400;", "AK", &e);
        check("  ... GS and a move to the pen, then the draw",
              e.size() == 4 && e[2] == U(100, 200) && e[3] == D(300, 400));
    }
    expectCmds("ESC A J sets labels' direction", "\x1b" "AJ45;LBx\x03" "DI1,0;LBy\x03", "AJ45 AJ0");
    expectCmds("ESC A T sets labels' font", "\x1b" "AT9;LBx\x03" "CS0;LBy\x03", "AT9 AT0");
    expectCmds("ESC A I sets labels' size", "\x1b" "AI80,120;LBx\x03SI;LBy\x03", "AI80,120 AI56,88");
    expectCmds("ESC A V: the plotter at its defaults", "SI0.5,1;LBx\x03\x1b" "AV" "LBy\x03SI0.5,1;LBz\x03",
               "AI119,257 AV AI119,257");
    expectCmds("an ESC in a label is not a command", "LBa\x1b" "AEb\x03", "");
}

int main() {
    std::string home = pt('U', 0, 0);   // (the first draw goes back into graph mode with a move to the pen)

    // X61: ';' is optional, a letter after a mnemonic's arguments starts the next one
    expect("PD..PU without ';'", "PD100,200PU300,400;",
           {home, D(100, 200), U(300, 400)});
    expect("lower case", "pd100,200pu300,400;",
           {home, D(100, 200), U(300, 400)});
    expect("with ';' as before", "PD100,200;PU300,400;",
           {home, D(100, 200), U(300, 400)});
    expect("a run of mnemonics", "PU10,20PD100,200,300,400PA500,600PU700,800;",
           {U(10, 20), D(100, 200), D(300, 400), D(500, 600), U(700, 800)});
    expect("space and line end before it", "PD100,200 PU300,400\r\nPD500,600;",
           {home, D(100, 200), U(300, 400), D(500, 600)});
    expect("an odd coordinate is dropped", "PD100,200,300PU400,500;",
           {home, D(100, 200), U(400, 500)});
    expect("signs still start numbers", "PU100,200PD-50,+300+400,500;",
           {U(100, 200), D(-50, 300), D(400, 500)});
    expect("a label after coordinates", "PD100,200LBhi\x03PU300,400;",
           {home, D(100, 200), L("hi"), U(300, 400)});
    expect("PU with no coordinates", "IN;PU100,200PD300,400PU;PD500,600;",
           {home, U(100, 200), D(300, 400), U(300, 400), D(500, 600)});
    // ... after mnemonics other than PU, PD and PA too
    expect("IN then PU, no ';'", "INPU100,200PD300,400;",
           {home, U(100, 200), D(300, 400)});
    expect("SP between strokes, no ';'", "PD100,200SP2PD300,400PU500,600;",
           {home, D(100, 200), D(300, 400), U(500, 600)});
    expect("a whole plot without ';'", "INSP1PU100,100PD200,100,200,200LBok\x03PU300,300SP0",
           {home, U(100, 100), D(200, 100), D(200, 200), L("ok"), U(300, 300)});
    expect("an unknown command is skipped", "PU100,200CS33PD300,400;",
           {U(100, 200), D(300, 400)});
    expect("SM's character may be a letter", "SMAPU100,200;",
           {U(100, 200)});
    expect("DT's character may be a letter", "DTXPU100,200;",
           {U(100, 200)});
    expect("BL's text to ETX is not commands", "BLPD9,9\x03PU100,200;",
           {U(100, 200)});
    expect("WD's text to ETX is not commands", "WDPD9,9\x03PU100,200;",
           {U(100, 200)});
    // the lift back along the stroke (!r) before a move, ';' or not
    {
        int x1 = tx(1000), y1 = ty(0);
        int rx = x1 + (int)lround(-x1 * 22.0f / x1);
        expect("!r 22: lift along the stroke", "PD1000,0PU2000,0;",
               {home, D(1000, 0), pt('U', rx, y1), U(2000, 0)}, 22);
    }
    testPoll();
    testPage();
    testAlpha();
    testNative();

    printf(failures ? "%d FAILED\n" : "all passed\n", failures);
    return failures ? 1 : 0;
}
