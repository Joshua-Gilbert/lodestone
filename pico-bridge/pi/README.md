# gpib-bridge: the Pi side of the GPIB-Pico2 bridge

`gpibbridge` is a small daemon, gpib-bridged, that owns the Pico's USB serial port and answers the 1520 through
a handler. It is the bridge's own test and bring-up service. In normal use gridlink (`../../claude-link`)
opens the Pico itself and answers the 1520 as the Claude link, so only one of the two runs at a time: they
can't share the port.

| | |
|---|---|
| `gpibbridge/daemon.py` | the daemon: keeps the bridge online at its address, turns what the 1520 sends into messages for the handler, sends its replies back, and serves a control socket |
| `gpibbridge/protocol.py` | the USB frames (`../firmware/bridge/PROTOCOL.md`); gridlink's `pico.py` has its own copy |
| `gpibbridge/handlers/` | `thrutest` (like the bench firmware: `*IDN?` gives the bench ID, anything else is echoed), `scpi` (a small 488.2/SCPI instrument), and `base.py` for your own |
| `gpibbridge/ctl.py`, `gpibctl` | the control client |
| `bridge.toml` | the settings, with a comment on each |

## Install

The daemon needs Python 3.11 or later (it reads its settings with `tomllib`) and pyserial
(`sudo apt install python3-serial`). The paths below are the ones the code and the docs use:

- **The code:** copy `gpibbridge/` to `/opt/gpib-bridge/`, so that `/opt/gpib-bridge/gpibbridge/daemon.py`
  exists, and `gpibctl` to a directory on the PATH. gpibctl runs `python3 -m gpibbridge.ctl` with
  `PYTHONPATH=/opt/gpib-bridge`. `FIRMWARE.md` expects `bridge_pico2.uf2` there too.
- **The settings:** copy `bridge.toml` to `/etc/gpib-bridge/bridge.toml` and set `address` and `handler`.
  Without that file the daemon uses its defaults: address 7, the thrutest handler, port `auto`.
- **The control socket:** `/run/gpib-bridge/ctl.sock` by default (`control_socket` in bridge.toml). The
  daemon creates its directory and makes the socket mode 660, so gpibctl needs the daemon's user or group,
  or sudo.

Run it by hand to try it:

```
sudo PYTHONPATH=/opt/gpib-bridge python3 -m gpibbridge.daemon -v
```

The options: `-c FILE` (default `/etc/gpib-bridge/bridge.toml`), `--port`, `--address`, `--handler` and
`--ctl`, which override the file, and `-v` to log at debug level (every message and event).

### The service and the udev rule

The systemd unit and the udev rule live on Joshua's Pi and are not in this tree yet; copy the real files in
here when they are wanted. What the rest of the code assumes of them:

- **The unit** is called `gpib-bridge` (gpibctl's error message names `systemctl status gpib-bridge`, and
  `gpibctl flash` runs `systemctl try-restart gpib-bridge gridlink`). It runs
  `python3 -m gpibbridge.daemon` with `PYTHONPATH=/opt/gpib-bridge`. Under systemd the daemon leaves the
  time stamps out of its log lines, as the journal has its own. It must not be enabled while gridlink's
  service uses the bridge.
- **Its user.** The daemon creates the socket's directory, `/run/gpib-bridge`, itself, and only root may
  create it under `/run`. So either run it as root, or as a user of its own with
  `RuntimeDirectory=gpib-bridge` in the unit (systemd then makes the directory, owned by that user). That
  user needs the serial port: on Raspberry Pi OS, membership of `dialout`.
- **Who may use gpibctl.** The socket is mode 660, owned by the daemon's user and group (`Group=` in the
  unit sets the group). Anyone else gets EACCES, and gpibctl then says it "can't reach the daemon ...
  Is gpib-bridge running?" although it is: add them to that group, or use sudo.
- **Restarts.** Give the unit `Restart=on-failure`: a daemon that ends on an error it didn't expect then
  comes back by itself.
- **The udev rule** names the bridge `/dev/gpib-bridge` by its USB product string, "GPIB-Pico2 Bridge"
  (VID 2E8A, PID 000F; `FIRMWARE.md`'s build sets the string). Without the rule, `port = "auto"` still finds
  the bridge: it tries `/dev/gpib-bridge`, then `/dev/serial/by-id/*GPIB-Pico2*`, then `*Pico*`, then any
  serial port with the Raspberry Pi USB vendor ID, as gridlink's `find_port` does.

## What the daemon does

- It opens the port and asks for HELLO. A port that doesn't answer within 3 s isn't the bridge firmware
  (the bench firmware, say); it closes it and tries again every second, and says so once for that port
  until it answers. A port that fails while it opens is skipped and tried again later.
- Once connected it sets the status byte, sends CONFIG online at its address, and PINGs every second from a
  thread of its own, so a slow handler can't make the Pico think the Pi has gone (5 s without a PING and the
  Pico goes offline). No PONG for 6 s and it reconnects. A Pico that reports itself offline is put back
  online.
- A frame it can't decode, or one shorter than its fields, is dropped and counted: the bad frames since the
  daemon started, on gpibctl status's Pi line (`bad_frames` in `--json`).
- Replies go out as the Pico's ring has room (its CREDIT frames), each tagged with the generation of the
  message it answers, so a late reply never answers the wrong question.

## gpibctl

```
gpibctl status                 connection, address, counters (Pi and Pico)
gpibctl watch                  every message and bus event, live (Ctrl-C stops)
gpibctl reply TEXT             queue TEXT + newline for the GRiD's next read
gpibctl srq STATUS             request service (SRQ) with this status byte; the GRiD's serial poll clears it
gpibctl address N              move the bridge to GPIB address N (until restart: set it in bridge.toml)
gpibctl offline | online       take the bridge off the bus / put it back
gpibctl flash FILE.uf2         reboot the Pico into its bootloader and copy new firmware (run with sudo)
```

`--json` prints the daemon's raw answer, and `--ctl PATH` (or `$GPIB_CTL`) names another socket.

`gpibctl flash` works whichever firmware is on the Pico. With the daemon running it asks the bridge to
reboot into its bootloader. Without it, it gives the bench firmware a 1200-baud touch, or you hold BOOTSEL
while plugging the Pico in. It then mounts the RP2350 drive, copies the file and restarts whichever of
gpib-bridge and gridlink was running. While gridlink owns the port, stop it first:
`sudo systemctl stop gridlink; sudo gpibctl flash bridge_pico2.uf2; sudo systemctl start gridlink`.

## Your own handler

Subclass `Handler` (`gpibbridge/handlers/base.py`) in a .py file and set `handler = "/path/file.py:ClassName"`
in bridge.toml. The daemon calls it from its single thread, one call at a time. Keep each call well under the
GRiD driver's 2 s time-out, and answer slow work later with `ctx.reply()` or `ctx.request_service()`.
`handler_options` in bridge.toml reaches the handler as its `options`.

## Tests

`../sim/host/run_sim_tests.py` runs this daemon against the real firmware compiled for Linux, on a simulated
bus (see `../firmware/bridge/FIRMWARE.md`).
