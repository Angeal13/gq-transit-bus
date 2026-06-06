# engine_health.py  — Raspberry Pi 3 Bus Node  (add-on module)
# Reads engine data from OBD-II (ELM327 USB) and analog sensors (MCP3208 ADC)
# Runs as a daemon thread alongside the existing stop-tracker.
# Posts a reading to the City Hall server every 2 seconds.
#
# Hardware wiring (MCP3208 via SPI):
#   MCP3208 Pin 1  (CS)   → GPIO 8  (CE0)
#   MCP3208 Pin 2  (Din)  → GPIO 10 (MOSI)
#   MCP3208 Pin 3  (Dout) → GPIO 9  (MISO)
#   MCP3208 Pin 4  (CLK)  → GPIO 11 (SCLK)
#   MCP3208 Pin 16 (VDD)  → 3.3V
#   MCP3208 Pin 15 (VREF) → 3.3V
#   MCP3208 Pin 14 (AGND) → GND
#
#   CH0 → oil pressure transducer (0-5V → divider to 0-3.3V)
#   CH1 → battery voltage divider  (12V → divider to 0-3.3V)
#   CH2 → intake air temp NTC thermistor
#   CH3 → spare / exhaust temp thermocouple amplifier (optional)
#
# OBD-II: ELM327 USB adapter plugged into bus OBD port + Pi USB port.

import time
import logging
import threading
import statistics
from datetime import datetime
from typing import Dict, Optional, Tuple
from collections import deque

import requests

logger = logging.getLogger(__name__)

# ── Import guards (graceful fallback on non-Pi hardware) ──────────────────────
try:
    import obd
    OBD_AVAILABLE = True
except ImportError:
    OBD_AVAILABLE = False
    logger.warning("python-obd not installed — OBD-II in simulation mode.")

try:
    import spidev
    SPI_AVAILABLE = True
except ImportError:
    SPI_AVAILABLE = False
    logger.warning("spidev not installed — ADC in simulation mode.")

# ── Constants ─────────────────────────────────────────────────────────────────

POLL_INTERVAL = 2.0          # seconds between readings

# Hard threshold rules — trigger CRITICAL regardless of history
RULES = {
    'coolant_temp_c':   {'max': 105.0,  'min': None,  'label': 'Coolant temperature'},
    'oil_pressure_psi': {'max': None,   'min': 10.0,  'label': 'Oil pressure'},
    'battery_v':        {'max': 15.5,   'min': 11.5,  'label': 'Battery voltage'},
    'engine_load_pct':  {'max': 98.0,   'min': None,  'label': 'Engine load'},
    'rpm':              {'max': 4500.0, 'min': None,  'label': 'Engine RPM'},
    'intake_temp_c':    {'max': 70.0,   'min': None,  'label': 'Intake air temperature'},
}

# Voltage divider constants for ADC channels
# Oil pressure: transducer 0–100 PSI maps 0.5V–4.5V output
#   ADC voltage (0–3.3V after divider) → PSI
OIL_V_MIN, OIL_V_MAX = 0.5, 4.5
OIL_PSI_MIN, OIL_PSI_MAX = 0.0, 100.0

# Battery: 12–15V through 4:1 voltage divider → 0–3.75V (fits 3.3V ref with headroom)
BATT_DIVIDER = 4.0

# NTC thermistor (10kΩ @ 25°C, B=3950) — simplified Steinhart-Hart
import math
NTC_R_REF  = 10000.0   # 10kΩ reference resistor
NTC_R_NOM  = 10000.0   # thermistor nominal resistance at 25°C
NTC_B      = 3950.0    # beta coefficient
NTC_T_NOM  = 298.15    # 25°C in Kelvin


# ── ADC driver (MCP3208 via SPI) ─────────────────────────────────────────────

class MCP3208:
    """8-channel 12-bit ADC over SPI. Returns 0–4095 raw counts."""

    def __init__(self, bus: int = 0, device: int = 0, vref: float = 3.3):
        self.vref = vref
        if SPI_AVAILABLE:
            self._spi = spidev.SpiDev()
            self._spi.open(bus, device)
            self._spi.max_speed_hz = 1_000_000
            self._spi.mode = 0
        else:
            self._spi = None

    def read_raw(self, channel: int) -> int:
        """Read raw 12-bit value (0–4095) from channel 0–7."""
        if not self._spi:
            return self._simulate(channel)
        if channel < 0 or channel > 7:
            raise ValueError("Channel must be 0–7")
        cmd = [0x06 | (channel >> 2), (channel & 0x03) << 6, 0x00]
        resp = self._spi.xfer2(cmd)
        return ((resp[1] & 0x0F) << 8) | resp[2]

    def read_voltage(self, channel: int) -> float:
        return self.read_raw(channel) * self.vref / 4095.0

    def _simulate(self, channel: int) -> int:
        """Return plausible simulated ADC values for testing."""
        import random
        base = {0: 2200, 1: 3100, 2: 1800, 3: 0}
        return int(base.get(channel, 2048) + random.gauss(0, 30))

    def close(self):
        if self._spi:
            self._spi.close()


# ── Sensor math ───────────────────────────────────────────────────────────────

def adc_to_oil_psi(voltage: float) -> float:
    """Convert transducer output voltage to PSI."""
    voltage = max(OIL_V_MIN, min(OIL_V_MAX, voltage))
    ratio = (voltage - OIL_V_MIN) / (OIL_V_MAX - OIL_V_MIN)
    return OIL_PSI_MIN + ratio * (OIL_PSI_MAX - OIL_PSI_MIN)

def adc_to_battery_v(voltage: float) -> float:
    """Recover actual battery voltage from divided ADC reading."""
    return voltage * BATT_DIVIDER

def adc_to_ntc_temp_c(voltage: float, vcc: float = 3.3) -> float:
    """Convert NTC thermistor voltage divider reading to °C (Steinhart-Hart)."""
    if voltage <= 0 or voltage >= vcc:
        return 25.0  # fallback
    r_ntc = NTC_R_REF * voltage / (vcc - voltage)
    try:
        inv_t = (1.0 / NTC_T_NOM) + (1.0 / NTC_B) * math.log(r_ntc / NTC_R_NOM)
        return (1.0 / inv_t) - 273.15
    except (ValueError, ZeroDivisionError):
        return 25.0


# ── OBD-II reader ────────────────────────────────────────────────────────────

class OBDReader:
    """Wraps python-obd for engine parameter reading."""

    # OBD commands we care about
    COMMANDS = ['RPM', 'COOLANT_TEMP', 'ENGINE_LOAD', 'THROTTLE_POS',
                'SHORT_FUEL_TRIM_1', 'LONG_FUEL_TRIM_1', 'INTAKE_TEMP',
                'RUN_TIME', 'DISTANCE_W_MIL', 'GET_DTC']

    def __init__(self):
        self._conn = None
        self._lock = threading.Lock()
        self._connect()

    def _connect(self):
        if not OBD_AVAILABLE:
            return
        try:
            self._conn = obd.OBD(fast=True, timeout=5)
            if self._conn.is_connected():
                logger.info("OBD-II connected.")
            else:
                logger.warning("OBD-II adapter found but not connected to ECU.")
                self._conn = None
        except Exception as e:
            logger.warning(f"OBD-II connect failed: {e}")
            self._conn = None

    def read(self) -> Dict:
        """Return dict of current OBD values. None for unavailable fields."""
        if not self._conn:
            return self._simulate_obd()

        result = {}
        with self._lock:
            try:
                r = self._conn.query(obd.commands.RPM)
                result['rpm'] = float(r.value.magnitude) if r.value else None

                r = self._conn.query(obd.commands.COOLANT_TEMP)
                result['coolant_temp_c'] = float(r.value.magnitude) if r.value else None

                r = self._conn.query(obd.commands.ENGINE_LOAD)
                result['engine_load_pct'] = float(r.value.magnitude) if r.value else None

                r = self._conn.query(obd.commands.THROTTLE_POS)
                result['throttle_pct'] = float(r.value.magnitude) if r.value else None

                r = self._conn.query(obd.commands.SHORT_FUEL_TRIM_1)
                result['fuel_trim_short_pct'] = float(r.value.magnitude) if r.value else None

                r = self._conn.query(obd.commands.LONG_FUEL_TRIM_1)
                result['fuel_trim_long_pct'] = float(r.value.magnitude) if r.value else None

                r = self._conn.query(obd.commands.INTAKE_TEMP)
                result['intake_temp_c'] = float(r.value.magnitude) if r.value else None

                r = self._conn.query(obd.commands.RUN_TIME)
                result['engine_runtime_s'] = int(r.value.magnitude) if r.value else None

                r = self._conn.query(obd.commands.GET_DTC)
                result['fault_codes'] = [str(c) for c in r.value] if r.value else []
                result['fault_code_count'] = len(result['fault_codes'])

            except Exception as e:
                logger.error(f"OBD read error: {e}")
                self._conn = None  # will reconnect next cycle

        return result

    def _simulate_obd(self) -> Dict:
        """Realistic simulation for development/testing."""
        import random
        t = time.time()
        return {
            'rpm':                 float(int(800 + 1200 * abs(math.sin(t / 60)) + random.gauss(0, 20))),
            'coolant_temp_c':      float(round(88.0 + 5 * abs(math.sin(t / 300)) + random.gauss(0, 0.5), 1)),
            'engine_load_pct':     float(round(30.0 + 20 * abs(math.sin(t / 45)) + random.gauss(0, 1), 1)),
            'throttle_pct':        float(round(15.0 + 10 * abs(math.sin(t / 30)) + random.gauss(0, 0.5), 1)),
            'fuel_trim_short_pct': float(round(random.gauss(1.5, 1.0), 2)),
            'fuel_trim_long_pct':  float(round(random.gauss(0.5, 0.5), 2)),
            'intake_temp_c':       float(round(35.0 + random.gauss(0, 0.3), 1)),
            'engine_runtime_s':    int(t % 86400),
            'fault_codes':         [],
            'fault_code_count':    0,
        }

    def reconnect(self):
        if OBD_AVAILABLE and not self._conn:
            self._connect()


# ── Local rule checker ────────────────────────────────────────────────────────

def check_rules(reading: Dict) -> Tuple[str, list]:
    """
    Apply hard threshold rules to a reading.
    Returns (severity, [alert_messages])
    severity: 'ok' | 'warning' | 'critical'
    """
    alerts = []
    severity = 'ok'

    for key, rule in RULES.items():
        val = reading.get(key)
        if val is None:
            continue
        label = rule['label']
        if rule['max'] is not None and val >= rule['max']:
            alerts.append(f"{label} HIGH: {val:.1f} (limit {rule['max']})")
            severity = 'critical'
        if rule['min'] is not None and val <= rule['min']:
            alerts.append(f"{label} LOW: {val:.1f} (limit {rule['min']})")
            severity = 'critical'

    # Fault codes are always critical
    if reading.get('fault_code_count', 0) > 0:
        codes = ', '.join(reading.get('fault_codes', []))
        alerts.append(f"OBD fault codes active: {codes}")
        severity = 'critical'

    return severity, alerts


# ── Engine health service (daemon thread) ─────────────────────────────────────

class EngineHealthService:
    """
    Daemon thread that:
    1. Reads OBD-II + ADC every POLL_INTERVAL seconds
    2. Applies local rule checks (for immediate driver audio warning)
    3. POSTs the reading to the server for Z-score + EMA analysis
    """

    def __init__(self, bus_id: str, server_url: str, api_key: str,
                 audio_system=None):
        self.bus_id       = bus_id
        self.server_url   = server_url.rstrip('/')
        self.api_key      = api_key
        self.audio        = audio_system

        self._obd         = OBDReader()
        self._adc         = MCP3208()
        self._stop_event  = threading.Event()
        self._thread      = threading.Thread(target=self._loop, daemon=True,
                                             name='engine-health')
        self._session     = requests.Session()
        self._session.headers.update({'X-API-Key': api_key,
                                      'Content-Type': 'application/json'})

        # Local offline queue — store readings if server unreachable
        self._offline: deque = deque(maxlen=300)  # ~10 min at 2s

        # Track last alert spoken to avoid repeating every 2s
        self._last_audio_alert: Optional[str] = None
        self._last_alert_time: float = 0.0

        logger.info("Engine health service initialised.")

    def start(self):
        self._thread.start()
        logger.info("Engine health monitoring started.")

    def stop(self):
        self._stop_event.set()
        self._adc.close()
        logger.info("Engine health service stopped.")

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _loop(self):
        while not self._stop_event.wait(POLL_INTERVAL):
            try:
                reading = self._collect()
                local_severity, local_alerts = check_rules(reading)

                # Speak critical alerts to driver (max once per 60s per alert)
                if local_severity == 'critical' and local_alerts:
                    self._speak_alert(local_alerts[0], reading)

                # Ship to server
                self._post(reading, local_severity, local_alerts)

                # Opportunistic flush of offline queue
                if self._offline:
                    self._flush_offline()

            except Exception as e:
                logger.error(f"Engine health loop error: {e}")

    # ── Data collection ───────────────────────────────────────────────────────

    def _collect(self) -> Dict:
        now = datetime.utcnow().isoformat() + 'Z'

        # OBD-II (reconnect if lost)
        self._obd.reconnect()
        obd_data = self._obd.read()

        # ADC channels
        try:
            oil_v    = self._adc.read_voltage(0)
            batt_v_r = self._adc.read_voltage(1)
            intake_v = self._adc.read_voltage(2)

            oil_psi  = adc_to_oil_psi(oil_v)
            batt_v   = adc_to_battery_v(batt_v_r)
            # Use OBD intake temp if available, ADC as fallback
            if obd_data.get('intake_temp_c') is None:
                obd_data['intake_temp_c'] = adc_to_ntc_temp_c(intake_v)
        except Exception as e:
            logger.warning(f"ADC read error: {e}")
            oil_psi = None
            batt_v  = None

        reading = {
            'bus_id':    self.bus_id,
            'timestamp': now,
            **obd_data,
            'oil_pressure_psi': round(oil_psi, 1) if oil_psi is not None else None,
            'battery_v':        round(batt_v,  2) if batt_v  is not None else None,
        }
        return reading

    # ── Server communication ──────────────────────────────────────────────────

    def _post(self, reading: Dict, local_severity: str, local_alerts: list):
        payload = {**reading,
                   'local_severity': local_severity,
                   'local_alerts':   local_alerts}
        url = f"{self.server_url}/api/engine/reading"
        try:
            r = self._session.post(url, json=payload, timeout=4)
            r.raise_for_status()
        except Exception:
            self._offline.append(payload)

    def _flush_offline(self):
        url  = f"{self.server_url}/api/engine/reading"
        sent = 0
        tmp  = list(self._offline)
        self._offline.clear()
        for payload in tmp:
            try:
                r = self._session.post(url, json=payload, timeout=4)
                r.raise_for_status()
                sent += 1
            except Exception:
                self._offline.append(payload)
                break   # server still down — stop trying
        if sent:
            logger.info(f"Engine health: flushed {sent} offline readings.")

    # ── Driver audio alert ────────────────────────────────────────────────────

    _ALERT_PHRASES = {
        'Coolant temperature': {
            'es': 'Temperatura del motor muy alta. Detenga el vehículo.',
            'fr': 'Température moteur trop élevée. Arrêtez le véhicule.',
            'en': 'Engine temperature critical. Stop the vehicle.',
        },
        'Oil pressure': {
            'es': 'Presión de aceite baja. Detenga el motor.',
            'fr': 'Pression d\'huile basse. Arrêtez le moteur.',
            'en': 'Oil pressure low. Stop the engine.',
        },
        'Battery voltage': {
            'es': 'Voltaje de batería anormal. Revise el alternador.',
            'fr': 'Tension batterie anormale. Vérifiez l\'alternateur.',
            'en': 'Battery voltage abnormal. Check the alternator.',
        },
        'fault': {
            'es': 'Falla detectada en el motor. Consulte al mecánico.',
            'fr': 'Panne moteur détectée. Consultez le mécanicien.',
            'en': 'Engine fault detected. Consult the mechanic.',
        },
    }

    def _speak_alert(self, alert_msg: str, reading: Dict):
        now = time.time()
        if alert_msg == self._last_audio_alert and now - self._last_alert_time < 60:
            return   # don't repeat the same alert within 60 seconds

        if not self.audio:
            logger.warning(f"DRIVER ALERT (no audio): {alert_msg}")
            return

        # Match alert to phrase
        lang = 'es'  # default; ideally passed from route config
        phrase = None
        for key, phrases in self._ALERT_PHRASES.items():
            if key.lower() in alert_msg.lower() or \
               ('fault' in key and 'fault' in alert_msg.lower()):
                phrase = phrases.get(lang, phrases['en'])
                break

        if not phrase:
            phrase = f"Alerta del motor: {alert_msg}"

        from threading import Event
        self.audio.play_audio(phrase, lang, Event(), repetitions=2)
        self._last_audio_alert = alert_msg
        self._last_alert_time  = now
        logger.warning(f"Driver audio alert spoken: {phrase}")
