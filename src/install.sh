#!/bin/bash
# install.sh — Raspberry Pi 3 Bus Node
# Complete setup: transit system + engine health + intranet WiFi
# Run as: sudo bash install.sh
# Tested on Raspberry Pi OS Lite 64-bit (Bullseye / Bookworm)

set -e
APP_DIR="/opt/bioko_bus"

echo "========================================================"
echo " Bioko Transit — Bus Node Installer"
echo " Installs: stop tracker + engine health + intranet WiFi"
echo "========================================================"

# ── System packages ───────────────────────────────────────────────────────────
apt-get update -y
apt-get install -y \
    python3 python3-pip python3-venv \
    espeak espeak-data libespeak-dev \
    libportaudio2 portaudio19-dev \
    alsa-utils \
    git

# ── Enable SPI (for MCP3208 ADC) ─────────────────────────────────────────────
if ! grep -q "dtparam=spi=on" /boot/config.txt; then
    echo "dtparam=spi=on" >> /boot/config.txt
fi
modprobe spi_bcm2835 2>/dev/null || true

# ── Application directory ─────────────────────────────────────────────────────
mkdir -p "$APP_DIR/logs" "$APP_DIR/offline_data"
cp -r ./* "$APP_DIR/" 2>/dev/null || true
# Make .env from template if not present
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.template" "$APP_DIR/.env"
fi

# ── Python virtual environment ────────────────────────────────────────────────
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

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
