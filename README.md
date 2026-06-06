# gq-transit-bus

Raspberry Pi 3 software for each bus in the Guinea Ecuatorial public transit network.

**Part of the [GQ Transit platform](https://github.com/YOUR_USERNAME/gq-transit-infra)**

---

## What this does

Runs on the Pi 3 installed inside each bus. Handles:
- Stop tracking via GPIO buttons → announces stops in ES/FR/EN
- Engine health monitoring via OBD-II + ADC sensors every 2 seconds
- Connects to the nearest `BIOKO_BUS` intranet access point automatically
- Offline queue — stores events on SD card when out of WiFi range, syncs on reconnect
- Heartbeat to server every 30 seconds for live map tracking

## Hardware required per bus

| Component | Cost |
|-----------|------|
| Raspberry Pi 3 Model B+ | ~$45 |
| ELM327 USB OBD-II adapter | ~$8 |
| MCP3208 ADC chip | ~$3 |
| Oil pressure sensor + voltage divider + NTC thermistor | ~$7 |
| Buttons × 3 (GPIO) + speaker + 12V→5V converter | ~$26 |

See [`src/WIRING.md`](src/WIRING.md) for full pinout.

## Quick install

```bash
git clone https://github.com/YOUR_USERNAME/gq-transit-bus.git
cd gq-transit-bus/src
sudo bash install.sh
```

The installer will prompt for the WiFi password (`BIOKO_BUS` network) and the API key (must match the server).

## Configuration

Edit `/opt/bioko_bus/.env` after installation:

```env
SERVER_URL=http://bioko-server:5000   # resolves via relay node dnsmasq
API_KEY=your_shared_key
AUDIO_LANGUAGE=es                      # es | fr | en
REGION_NAME=Bioko                      # or Litoral, CentroSur, WeleNzas, KienTem
```

## Keyboard controls (tested)

| Key | Action |
|-----|--------|
| `0` | Next stop |
| `.` | Emergency stop |
| `/` | Complete route |

GPIO buttons on pins 17, 27, 22 also work simultaneously.

## Deployment regions

This same codebase deploys to all regions — only `.env` changes:

| Region | `REGION_NAME` | Server URL |
|--------|---------------|------------|
| Bioko Island | `Bioko` | `http://bioko-server:5000` |
| Litoral (Bata) | `Litoral` | `http://bata-server:5000` |
| Centro Sur | `CentroSur` | `http://bata-server:5000` |
| Wele-Nzas | `WeleNzas` | `http://bata-server:5000` |
| Kie-Ntem | `KienTem` | `http://bata-server:5000` |

Cross-province buses set `REGION_NAME=IntreProvince` and connect to whichever relay node is in range.

## Repository structure

```
src/
  main.py                 — entry point, starts all services
  config.py               — all configuration from .env
  controller.py           — GPIO buttons + keyboard input
  logic.py                — stop tracker, route cache, resume service
  server_client.py        — HTTP client to city hall server
  audio_system.py         — gTTS + pyttsx3 TTS with offline fallback
  audio_utils.py          — amixer hardware config
  data_models.py          — BusRoute, StopInfo, Bus dataclasses
  engine_health.py        — OBD-II + ADC engine monitoring daemon
  wpa_supplicant_bioko.conf — WiFi config for BIOKO_BUS intranet
  WIRING.md               — GPIO pinout reference
  install.sh              — one-command installer
  requirements.txt
  .env.template
```

## License

MIT — owned by the project owner. See LICENSE.
