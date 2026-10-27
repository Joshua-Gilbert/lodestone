# GPIB-Pico2 bridge

The Raspberry Pi Pico 2 board that is the GRiD 1520's GPIB device for the Claude link: the 1520 talks GPIB to
it, and it passes everything to the Raspberry Pi over USB, where gridlink (`../claude-link`) answers.

| | |
|---|---|
| `firmware/bridge/` | the bridge firmware: sources, `bridge_pico2.uf2` ready to flash, `FIRMWARE.md` (build, flash, what changed), `PROTOCOL.md` (USB frames to and from the Pi) |
| `sim/host/` | the firmware compiled for Linux against a model of the board and the bus (`bus_sim.c`), and `run_sim_tests.py`: the real Pi daemon and gridlink's `pico.py` against it (`python3 sim/host/run_sim_tests.py`, 111 checks) |
| `pi/` | the gpib-bridge daemon (`gpibbridge`, `gpibctl`): the bridge's own test handlers (thrutest, scpi) and `gpibctl flash`. gridlink replaces it in normal use |

Flash from the Pi: `sudo systemctl stop gridlink; sudo gpibctl flash bridge_pico2.uf2; sudo systemctl start gridlink`.
