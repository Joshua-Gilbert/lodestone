/*
  GPIB-Pico2 bridge rev 1.2 -- production firmware: the GRiDCase 1520's GPIB device, piped to a Raspberry Pi.

  Board: "Raspberry Pi Pico 2" (Earle Philhower arduino-pico core, rp2040:rp2040:rpipico2), CPU 150 MHz.
  Build: see FIRMWARE.md (arduino-cli line).  Flash: hold BOOTSEL while plugging in and copy bridge_pico2.uf2,
  or from the Pi: gpibctl flash bridge_pico2.uf2.

  Core 1: the GPIB engine (gpib_engine.c), alone, interrupts off, running from SRAM.  It answers ATN within the
          IEEE-488.1 200 ns, does the 3-wire handshakes, addressing, serial poll, SRQ, clears, REN/LLO/GTL/GET.
  Core 0: USB CDC to the Pi (host_link.c, PROTOCOL.md).  The Pi daemon (pi/ folder) decides the address and
          answers every message the 1520 sends to it.

  Until the Pi says CONFIG online, and whenever its port closes or its PINGs stop for 5 s, the bridge takes no
  part in the bus at all (NRFD/NDAC/SRQ released, nothing driven) -- like a powered-off instrument.
  LED: off = no Pi, slow blink = Pi connected but offline, on = online, flicker = bus traffic for us.
*/
#include "gpib_engine.h"
#include "host_link.h"
#include "hardware/sync.h"
#include "pico/bootrom.h"
#include "hardware/clocks.h"
#include <tusb.h>
#include "CoreMutex.h"
#include "USB.h"

static volatile bool engine_go = false;

extern "C" size_t link_write_some(const uint8_t *b, size_t n) {
  if (!Serial) return 0;
  int room = Serial.availableForWrite();       // never block: what doesn't fit waits in host_link's buffer
  if (room <= 0) return 0;
  if ((size_t)room < n) n = (size_t)room;
  return Serial.write(b, n);
}

extern "C" void link_bootsel(void) {
  Serial.flush();
  delay(50);
  rp2040.wdt_reset();
  rp2040.rebootToBootloader();
}

static void safeState() {
  // The board's power-up state: R1-R3 hold TE/PE low, R4-R6 hold SRQ/NRFD/NDAC released.  Same here: latches set
  // before any pin becomes an output, TE/PE driven low first.
  const uint8_t te[3] = {P_TE_C, P_PE_D, P_TE_D};
  for (int i = 0; i < 3; i++) { digitalWrite(te[i], LOW); pinMode(te[i], OUTPUT); }
  for (int p = 0; p <= 7; p++) pinMode(p, INPUT);
  const uint8_t ins[5] = {P_ATN, P_EOI, P_DAV, P_IFC, P_REN};
  for (int i = 0; i < 5; i++) pinMode(ins[i], INPUT);
  const uint8_t outs[3] = {P_SRQ, P_NRFD, P_NDAC};          // U3 sends these to the bus in listen mode
  for (int i = 0; i < 3; i++) { digitalWrite(outs[i], HIGH); pinMode(outs[i], OUTPUT); }
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
}

void setup() {
  safeState();
  memset((void *)&SH, 0, sizeof SH);
  link_init();
  Serial.begin(115200);       // USB CDC: the baud rate is ignored
  rp2040.wdt_begin(2000);     // if core 0 ever hangs, the chip resets into the safe state (bus released)
  engine_go = true;
}

void setup1() {
  while (!engine_go) tight_loop_contents();
  engine_timing_init(clock_get_hz(clk_sys));   // T1 in cycles, on this core's SysTick
  save_and_disable_interrupts();       // core 1 never takes an interrupt again
  engine_run();
}

void loop1() {}

void loop() {
  static uint8_t buf[CFG_TUD_CDC_RX_BUFSIZE];
  static uint32_t lastActivity, ledAt;
  static uint32_t lastRx, lastTx;
  rp2040.wdt_reset();
  uint32_t now = millis();
  bool open = (bool)Serial;            // DTR: the Pi has the port open
  // All the Pi has sent, in one tud_cdc_read.  Serial.readBytes went through read() a byte at a time, and every
  // read() took the USB mutex and ran tud_task.  A 2 KB reply took ~18 ms from the Pi's write to the 1520's
  // read (gridlink.bench --trace, 2026-10-22), an 8-byte one under 1 ms.
  for (int k = 0; k < 16 && Serial.available() > 0; k++) {     // (available() runs tud_task: the FIFO refills)
    uint32_t n = 0;
    { CoreMutex m(&USB.mutex, 0); if (m) n = tud_cdc_read(buf, sizeof buf); }
    if (!n) break;
    link_input(buf, n, now);
  }
  link_poll(now, open);

  // LED
  if (SH.n_rx != lastRx || SH.n_tx != lastTx) { lastRx = SH.n_rx; lastTx = SH.n_tx; lastActivity = now; }
  bool led;
  if (!open) led = false;
  else if (!SH.online) led = ((now / 500) & 3) == 0;
  else led = !(now - lastActivity < 100 && ((now / 25) & 1));
  if (now != ledAt) { digitalWrite(LED_BUILTIN, led ? HIGH : LOW); ledAt = now; }
}
