#!/bin/bash
# install.sh — Raspberry Pi 3 Bus Node
# Complete setup: transit system + engine health + intranet WiFi
# Run as: sudo bash install.sh
# Tested on Raspberry Pi OS Lite 64-bit (Bullseye / Bookworm)
#
# INTERNET REQUIRED: only during this install script.
# After installation the Pi operates 100% offline on the BIOKO_BUS intranet.
# TTS voices (Spanish, French, English) are downloaded once here and cached.

set -e
APP_DIR="/opt/bioko_bus"

echo "========================================================"
echo " Bioko Transit — Bus Node Installer"
echo " Installs: stop tracker + engine health + intranet WiFi"
echo " TTS: pyttsx3 + espeak-ng (offline after install)"
echo "========================================================"

# ── System packages ───────────────────────────────────────────────────────────
apt-get update -y
apt-get install -y \
    python3 python3-pip python3-venv \
    espeak-ng \
    espeak-ng-data \
    libespeak-ng-dev \
    libportaudio2 portaudio19-dev \
    alsa-utils \
    git

# ── Download espeak-ng voice data for ES / FR / EN ───────────────────────────
# espeak-ng-data package already includes all languages on Raspberry Pi OS.
# Verify the Spanish voice is present and working.
echo "Verifying espeak-ng Spanish voice..."
if espeak-ng -v es "Bienvenido a Bioko Transit" --ipa > /dev/null 2>&1; then
    echo "  ✔ Spanish voice (es) OK"
else
    echo "  Installing additional espeak-ng language data..."
    apt-get install -y espeak-ng-data
fi

# Verify French and English voices
for LANG in fr en; do
    if espeak-ng -v $LANG "Test" > /dev/null 2>&1; then
        echo "  ✔ Voice '$LANG' OK"
    else
        echo "  WARNING: Voice '$LANG' not found — Spanish will be used as fallback."
    fi
done

# ── Enable SPI (for MCP3208 ADC) ─────────────────────────────────────────────
if ! grep -q "dtparam=spi=on" /boot/config.txt; then
    echo "dtparam=spi=on" >> /boot/config.txt
fi
modprobe spi_bcm2835 2>/dev/null || true

# ── Application directory ─────────────────────────────────────────────────────
mkdir -p "$APP_DIR/logs" "$APP_DIR/offline_data"
cp -r ./* "$APP_DIR/" 2>/dev/null || true
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.template" "$APP_DIR/.env"
fi

# ── Python virtual environment ────────────────────────────────────────────────
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# ── pyttsx3 espeak backend test ───────────────────────────────────────────────
echo "Testing pyttsx3 + espeak-ng offline TTS..."
"$APP_DIR/venv/bin/python" - << 'PYTEST'
import pyttsx3, sys
try:
    e = pyttsx3.init(driverName='espeak')
    voices = e.getProperty('voices')
    es_voice = next((v for v in voices if 'es' in v.id.lower()), None)
    if es_voice:
        e.setProperty('voice', es_voice.id)
        print(f"  ✔ pyttsx3 espeak OK — Spanish voice: {es_voice.id}")
    else:
        print("  WARNING: Spanish voice not matched by id — will use default.")
    e.stop()
except Exception as ex:
    print(f"  ERROR: pyttsx3 test failed: {ex}", file=sys.stderr)
    sys.exit(1)
PYTEST

# ── USB serial permissions (for ELM327 OBD-II adapter) ───────────────────────
usermod -aG dialout pi 2>/dev/null || true
echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", MODE="0666"' \
    > /etc/udev/rules.d/99-obd.rules
udevadm control --reload-rules

# ── WiFi config for BIOKO_BUS intranet ───────────────────────────────────────
read -p "WiFi password for BIOKO_BUS network: " WIFI_PASS
cp "$APP_DIR/wpa_supplicant_bioko.conf" /etc/wpa_supplicant/wpa_supplicant.conf
sed -i "s|CHANGE_TO_YOUR_WIFI_PASSWORD|${WIFI_PASS}|" \
    /etc/wpa_supplicant/wpa_supplicant.conf
echo "WiFi configured for BIOKO_BUS intranet."

# ── API key ───────────────────────────────────────────────────────────────────
read -p "API key (must match City Hall server — default: BIOKO_BUS_KEY_CHANGE_ME): " API_KEY_INPUT
API_KEY_INPUT="${API_KEY_INPUT:-BIOKO_BUS_KEY_CHANGE_ME}"
sed -i "s|BIOKO_BUS_KEY_CHANGE_ME|${API_KEY_INPUT}|" "$APP_DIR/.env"

# ── systemd service ───────────────────────────────────────────────────────────
cat > /etc/systemd/system/bioko-bus.service << SERVICE
[Unit]
Description=Bioko Transit Bus Node
After=network.target sound.target
Wants=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable bioko-bus.service

echo ""
echo "========================================================"
echo " Bus node installation complete."
echo ""
echo " TTS: pyttsx3 + espeak-ng — fully offline after this."
echo " No internet needed for announcements at runtime."
echo ""
echo " Hardware to connect:"
echo "   1. ELM327 USB → bus OBD-II port + Pi USB"
echo "   2. MCP3208 ADC → Pi GPIO (see WIRING.md)"
echo "   3. Buttons → GPIO 17 (next), 27 (stop), 22 (complete)"
echo "   4. Speaker → 3.5mm jack"
echo "   5. Power → 12V→5V USB converter from bus battery"
echo ""
echo " Start: sudo systemctl start bioko-bus"
echo " Logs:  sudo journalctl -u bioko-bus -f"
echo "========================================================"
