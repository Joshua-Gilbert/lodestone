# The Claude link without the GPIB cartridge: SERLINK

`tools/SERLINK.COM` lets CLAUDE.COM reach gridlink on the Pi over a serial line instead of GPIB, for a GRiD
without the GPIB cartridge, or as a backup to it. It works over either of two connections:

- **the internal modem** (COM1, Option 331, 2400 baud): the GRiD dials the Pi's USB modem through a Grandstream
  HT802 and Asterisk on the Pi;
- **a null-modem cable** from the GRiD's external serial port (COM2) to a USB serial adapter on the Pi, at 19200
  baud by default.

CLAUDE.COM, resident Claude, Term, pictures and gridfox use it unchanged. SERLINK answers the same INT 60h calls as
the GPIB driver (`os/src/KGPIB.INC`), so they can't tell the difference, apart from the speed.

## Using it

On the GRiD, load SERLINK, then run CLAUDE as usual:

```
SERLINK /D:300          the internal modem: dial 300 (the Pi's extension), 2400 baud
SERLINK /P:2            the cable on COM2, 19200 baud
SERLINK /P:2 /B:38400   another speed (300-115200; the same on the Pi)
SERLINK                 already loaded: says how it stands (port, speed, carrier)
SERLINK /U              hang up and unload
```

Other options:
- **`/A:n`** sets the link's GPIB address, as with `CLAUDE /A:` (default 7).
- **`/I:nn`** sets the vector (hex, default 60).

**Under Lodestone with multitasking on,** load it in the Executive's own task with Shift-Return, as with `CLAUDE /R`.
A resident program loaded inside a task is removed when the task ends, and SERLINK refuses to load there.

**With the GPIB cartridge,** SERLINK takes INT 60h ahead of the kernel's driver and passes calls for every other
address to it. CLAUDE's link goes over the serial line, and Claude's instrument tools still reach the bus through
the cartridge. Without the cartridge, those calls fail with "no listener".

**COM2 is where a serial mouse goes,** so with the cable there's no mouse until `SERLINK /U`.

On the Pi, gridlink runs with the matching bridge:

```
venv/bin/python -m gridlink --bridge modem --port /dev/ttyACM0
venv/bin/python -m gridlink --bridge serial --port /dev/ttyUSB0 --baud 19200
```

Or in `config.toml`:

```
[bridge]
kind = "modem"            # or "serial"
port = "/dev/ttyACM0"
```

`--baud` for a modem is the speed between the Pi and the modem, 115200 by default. The line's own speed comes from
the modem's `CONNECT`.

## Built into the kernel instead (`-dSERIAL`)

`KFLAGS=-dSERIAL os/build.sh` builds a kernel, and ROM 1, with this driver's resident part built in
(`os/src/KSER.INC`) in place of the GPIB driver. The README's Build section has the details:
- `SERLINK=` in LODE.INI sets the port and speed;
- the UART is claimed at CLAUDE's first call;
- it's pre-interrupt style: a 2 KB ring, but no IRQ to sleep on;
- there's no dialing, so the modem still uses SERLINK.COM.

Its signature is `SERKERN`, so SERLINK.COM can be loaded over it. The default build, and the committed binaries,
stay GPIB.

## How it works

### GRiD side (`tools/SERLINK.ASM`)

- **Frames:** GLP frames are binary and carry their length: sync 47h, type, sequence, acknowledgement, a 16-bit
  length, the payload, and a 2-byte check. So they go over the line unchanged, with no escaping.
- **Reading (03h):** a read skips bytes until the sync byte, reads the header, and returns exactly one frame, ending
  with DL = 1 (EOI), as GPIB's END does.
  - A length over 8 KB means the 47h wasn't a sync byte, so the hunt goes on.
  - If a byte times out partway through, the read returns what it has with DL = 8. CLAUDE then finds no good frame
    and NAKs.
- **Addresses:** SERLINK only serves the link's address (`/A:`, default 7). Every other address goes on to a GPIB
  driver it was loaded over, or fails with error 2.
- **Receiving:** bytes come in on the UART's interrupt (IRQ 4 for COM1, IRQ 3 for COM2) into a 4 KB ring buffer.
- **Serial poll (05h):** answers 60h (RQS, and the line complete) while anything is waiting, so CLAUDE reads at
  once. The Pi's answer can then take longer than CLAUDE's 2-second wait to arrive in full: the wait only covers
  the first byte.
- **Waking CLAUDE:**
  - 0Bh latches "something came".
  - 0Eh gives CLAUDE a count of bytes arriving into an empty ring, which it sleeps on (HLT) as it does on the
    cartridge's SRQ interrupt.
  - gridlink's "ring", which wakes an idle CLAUDE, is a single 07h byte that the frame hunt skips.
- **Version:** SERLINK reports 1.10, so CLAUDE keeps the Fletcher check itself. The 1.23 driver's in-place check
  (02h AL=3, 03h AL=2) belongs to the kernel's driver.
- **Writes:** polled, a byte at a time. On a modem, a write with the carrier gone fails with error 2, and CLAUDE says
  the link is lost.
- **IRQ test:** at install, SERLINK enables the UART's transmit-empty interrupt for a moment to see whether the IRQ
  actually comes. If it doesn't, SERLINK says so and runs polled: every wait and poll drains the UART, and 0Eh
  reports no IRQ, so CLAUDE polls rather than sleeps.
  - Polled works at 2400 baud but can't keep up at 19200, because the 1520's 16450 holds only one received byte.
  - Whether the internal modem's UART raises IRQ 4 on the 1520 hasn't been tried yet.
- **Dialing (`/D:`), at install:**
  - It sends `AT` (once more if there's no answer), `ATE0V1Q0X4` and `AT&C1&D2`. Some modems ERROR on the
    `&C1&D2` line, and either answer is fine.
  - Then it sends `ATDT` and the number, and waits up to a minute.
  - Echoed lines and `RING` are skipped. `CONNECT` succeeds. `NO CARRIER`, `NO DIALTONE`, `NO ANSWER`, `BUSY` and
    `ERROR` fail.
  - If it fails, the UART, the PIC mask and the vectors go back as they were, and nothing stays resident (exit code
    2).
- **Unloading (`/U`):** hangs up by dropping DTR for a second (`&D2`). If the carrier stays, it sends `+++`
  between two silences, then `ATH0`. Then it puts the UART, the IRQ vector, the PIC mask and INT 60h back.
- **Size:** about 5.4 KB resident, 4 KB of it the ring.

### Pi side (`claude-link/gridlink/serline.py`)

- **`SerialLink`:**
  - writes frames as they are and reads raw bytes; the Link's `StreamParser` finds the frames, as it does for GPIB;
  - caps each frame to the GRiD at about a second of line time (`frame_limit`): 240 bytes at 2400 baud, 1,920 at
    19200, 3,348 at most. So a 2400-baud answer arrives within CLAUDE's wait, and no single read holds the GRiD up
    for long.
- **`ModemLink`:**
  - sets the USB modem up with `ATZ`, `ATE0V1Q0`, `AT&C1&D2` and `ATS0=1`, so it answers on the first ring;
  - reads its result lines until `CONNECT` (and the speed in it);
  - is online from then until the carrier (DCD) drops, then sets the modem up again for the next call.

### Speed

At 2400 baud the link moves about 240 bytes a second each way. That's fine for chat. Term works, but Claude Code's
screen updates arrive slowly. A 1.2 KB file takes about five seconds. At 19200 on the cable it's about 1.9 KB/s.
Through the Pico 2 bridge it's over 100 KB/s, so GPIB stays the fast path and the serial link is the fallback.

## The modem path: HT802, Asterisk, a USB modem

```
GRiD internal modem (RJ-11) ── HT802 port 1 (ext 201) ─┐
2500 phone on the GRiD's second jack ──(same line)──────┤
                                                        HT802 ── LAN ── Pi: Asterisk
Pi USB modem (RJ-11) ─────────── HT802 port 2 (ext 300) ┘            └─ gridlink --bridge modem
```

**Hardware:**
- A Grandstream **HT802** (two FXS ports).
- A USB data modem on the Pi that can do V.22bis (2400 baud), for example a USRobotics USR5637. Any V.92 modem
  falls back to V.22bis for the GRiD.

**Settings for both HT802 ports:**
- G.711 µ-law only;
- a fixed jitter buffer;
- the line echo canceller and network echo suppressor turned off, as for a fax machine.

Modem tones don't survive compression or echo cancelling. On a LAN, 2400 baud over G.711 is undemanding.

**Asterisk:** register both ports as PJSIP endpoints, and route the Pi's extension to port 2. This is a sketch; the
HT802's own pages give the account settings.

```
; pjsip.conf (one block per port; passwords to taste)
[ht802-1]
type=endpoint
context=grid
disallow=all
allow=ulaw
auth=ht802-1
aors=ht802-1
[ht802-1]
type=auth
auth_type=userpass
username=201
password=...
[ht802-1]
type=aor
max_contacts=1
; ... the same for [ht802-2] (username 300)

; extensions.conf
[grid]
exten => 300,1,Dial(PJSIP/ht802-2,30)   ; the Pi's modem: the Claude link
exten => 201,1,Dial(PJSIP/ht802-1,30)   ; the GRiD's line (Claude calling back, later)
```

**Untested so far:** the HT802 and Asterisk setup above hasn't been tried on the real hardware. The tests check the
GRiD and Pi sides against a model of the call.

## Room for the voice call (not built yet)

The phone plan, a Western Electric 2500 on the GRiD's second RJ-11 jack in parallel with the internal modem, fits
this layout as it is:

- **Calling Claude:** another extension (say 252, "CLA") goes to an Asterisk AGI script on the Pi: Whisper,
  Claude, Piper.
- **From the phone:** the 2500 dials 252 directly.
- **From the GRiD:** the modem dials `ATDT252;`, where the trailing semicolon means back to command mode without a
  data call. The handset is picked up, then `ATH0` lets the modem go while the phone holds the call.
- **Claude calling back:** rings extension 201, so the 2500's bell rings, and the GRiD's modem sees `RING`.

One phone line is shared between data and voice, so the modem link and a voice call can't happen at once. The
Option 331 modem answers `ATI0` with 249, `ATI1` with 017 and `ATI3` with `04-00027-16` (MODEMID 1.1, 2026-11-04).

## Tests

`claude-link/tests/test_emu_serial.py` runs the real CLAUDE.COM and SERLINK.COM in the x86 emulator (`grid_emu.py`)
against the real gridlink SerialLink and ModemLink. The models are in `serial_model.py`:
- **The 1520's 16450:** one byte held and overwritten if unread, a character's time on the line each way, and the
  transmit-empty interrupt.
- **The cable.**
- **The two Hayes modems in one call:** echo until ATE0, ATDT ringing the Pi's modem, auto-answer, `CONNECT 2400`,
  the bytes at 2400 baud, and DTR down hanging up.

It covers (12 tests):
- chat over the cable and over the modem;
- Term (CLAUDE /T, a stand-in Claude Code) over both, its screen matching the Pi's;
- a 22 KB file over the cable, and 1.2 KB over the modem;
- speeds from 300 to 115200 baud;
- polled mode with the IRQ never coming;
- a busy number leaving nothing behind;
- `/U` hanging up, the Pi's modem set up again, and a second call;
- other addresses failing without the cartridge, and reaching the bus through GRIDGPIB with it.
