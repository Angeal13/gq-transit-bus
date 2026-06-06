# config.py — Raspberry Pi 3 Bus Node
# Bioko Island Public Transit System — FINAL version
# Intranet mode: connects to BIOKO_BUS WiFi, routes through relay node to City Hall

import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/bus_node.log', mode='a'),
    ]
)
logger = logging.getLogger(__name__)

COUNTRY_CODE = os.getenv('COUNTRY_CODE', 'GQ').upper()
REGION_NAME  = os.getenv('REGION_NAME',  'Bioko')

# ── Server (intranet only — no internet needed) ───────────────────────────────
# 'bioko-server' is resolved by the relay node's dnsmasq to City Hall.
# Works identically at Malabo depot, Luba terminal, Riaba, Moka, Punta Europa.
SERVER_CONFIG = {
    'base_url': os.getenv('SERVER_URL', 'http://bioko-server:5000'),
    'api_key':  os.getenv('API_KEY',    'BIOKO_BUS_KEY_CHANGE_ME'),
    'timeout':  int(os.getenv('SERVER_TIMEOUT', '8')),
}
logger.info(f"Server: {SERVER_CONFIG['base_url']} | Region: {REGION_NAME}")

# ── Heartbeat ─────────────────────────────────────────────────────────────────
HEARTBEAT_CONFIG = {
    'interval_seconds': int(os.getenv('HEARTBEAT_INTERVAL', '30')),
    'max_retries':      3,
    'retry_delay':      5,
}

# ── Audio ─────────────────────────────────────────────────────────────────────
AUDIO_CONFIG = {
    'rate':         140,
    'volume':       1.0,
    'language':     os.getenv('AUDIO_LANGUAGE', 'es'),
    'repeat_count': 3,
    'repeat_delay': 10,
}

# ── Offline storage ───────────────────────────────────────────────────────────
OFFLINE_CONFIG = {
    'data_dir':          'offline_data',
    'max_queued_events': 500,
    'sync_interval':     60,
}

# ── GPIO buttons ──────────────────────────────────────────────────────────────
GPIO_CONFIG = {
    'advance_pin':   17,   # BCM — next stop
    'exit_pin':      27,   # BCM — emergency stop
    'complete_pin':  22,   # BCM — complete route
    'bouncetime_ms': 300,
}

# ── Engine health (OBD-II + ADC) ──────────────────────────────────────────────
ENGINE_CONFIG = {
    'obd_port':       os.getenv('OBD_PORT',       '/dev/ttyUSB0'),
    'obd_baudrate':   int(os.getenv('OBD_BAUDRATE', '38400')),
    'poll_interval':  float(os.getenv('ENGINE_POLL_INTERVAL', '2.0')),
    'adc_spi_bus':    int(os.getenv('ADC_SPI_BUS',    '0')),
    'adc_spi_device': int(os.getenv('ADC_SPI_DEVICE', '0')),
    'adc_vref':       float(os.getenv('ADC_VREF',     '3.3')),
    'ch_oil_pressure': 0,
    'ch_battery':      1,
    'ch_intake_temp':  2,
    'alert_repeat_delay': 60,
    'offline_buffer':     300,
}

ENGINE_THRESHOLDS = {
    'coolant_temp_c':   {'max': 105.0, 'min': None},
    'oil_pressure_psi': {'max': None,  'min': 10.0},
    'battery_v':        {'max': 15.5,  'min': 11.5},
    'rpm':              {'max': 4500,  'min': None},
    'engine_load_pct':  {'max': 98.0,  'min': None},
    'intake_temp_c':    {'max': 70.0,  'min': None},
}

# ── Pi health ─────────────────────────────────────────────────────────────────
PI_HEALTH = {
    'check_interval':       900,
    'low_memory_threshold': 85,
    'high_temp_threshold':  70,
}
