# Bus Node — Hardware Wiring Reference

## Raspberry Pi 3 GPIO pinout (BCM numbering)

```
                 Pi 3 Header
    3.3V  [1]  [2]  5V
   GPIO2  [3]  [4]  5V
   GPIO3  [5]  [6]  GND
   GPIO4  [7]  [8]  GPIO14
     GND  [9] [10]  GPIO15
  GPIO17 [11] [12]  GPIO18   ← BUTTON: Next stop
  GPIO27 [13] [14]  GND      ← BUTTON: Emergency stop
  GPIO22 [15] [16]  GPIO23   ← BUTTON: Complete route
    3.3V [17] [18]  GPIO24
  GPIO10 [19] [20]  GND      ← SPI MOSI (to MCP3208 Din)
   GPIO9 [21] [22]  GPIO25   ← SPI MISO (to MCP3208 Dout)
  GPIO11 [23] [24]  GPIO8    ← SPI CLK / SPI CS0
     GND [25] [26]  GPIO7
```

---

## Buttons (GPIO 17, 27, 22)

Each button: one wire to GPIO pin, other wire to any GND pin.
No resistors needed — Pi internal pull-ups are enabled in software.

| Button label      | GPIO pin | Physical pin |
|-------------------|----------|--------------|
| Next stop         | GPIO 17  | Pin 11       |
| Emergency stop    | GPIO 27  | Pin 13       |
| Complete route    | GPIO 22  | Pin 15       |

Use GND pins 9, 14, 20, or 25.

---

## MCP3208 ADC (SPI) — for oil pressure, battery voltage, intake temp

```
MCP3208 pin → Pi pin
─────────────────────────────────────
Pin 1  (CS/SHDN) → Pin 24 (GPIO 8, CE0)
Pin 2  (Din)     → Pin 19 (GPIO 10, MOSI)
Pin 3  (Dout)    → Pin 21 (GPIO 9,  MISO)
Pin 4  (CLK)     → Pin 23 (GPIO 11, SCLK)
Pin 9  (DGND)    → Pin 6  (GND)
Pin 14 (AGND)    → Pin 6  (GND)
Pin 15 (VREF)    → Pin 1  (3.3V)
Pin 16 (VDD)     → Pin 1  (3.3V)
```

### ADC channel wiring

**Channel 0 — Oil pressure transducer (0–100 PSI, 0.5–4.5V output)**
Transducer output → voltage divider (10kΩ + 6.8kΩ) → CH0
This drops max 4.5V to ~2.9V, safe for 3.3V reference.

**Channel 1 — Battery voltage (12–15V)**
Battery+ → 10kΩ resistor → CH1 and → 3.3kΩ resistor → GND
(4:1 divider: 15V → 3.75V — just within 3.3V range with margin)

**Channel 2 — Intake air temperature (NTC 10kΩ thermistor)**
3.3V → 10kΩ pull-up resistor → CH2 and → thermistor → GND

**Channel 3 — Spare** (connect to GND if unused)

---

## OBD-II ELM327 USB adapter

Plug the ELM327 adapter into:
1. The bus OBD-II diagnostic port (under dashboard, standard on all buses)
2. Any USB port on the Pi

The adapter appears as /dev/ttyUSB0 automatically.
No additional wiring needed.

---

## Power supply

Use a 12V DC to 5V/3A USB converter connected to the bus battery circuit.
**Never connect the bus 12V directly to the Pi — it will destroy it.**

Recommended connection point: fused 12V accessory circuit (same as radio).
The Pi draws ~700mA peak — use a converter rated for at least 2A.

---

## Audio

3.5mm speaker → 3.5mm jack on the Pi.
Run: `amixer cset numid=3 1` to force audio to 3.5mm (the install.sh does this).
