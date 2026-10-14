#!/usr/bin/env bash
# ==============================================================================
# IoT Fleet Platform - Automated AWS Deployment Script
# Compatible with: Ubuntu 22.04 LTS / 24.04 LTS (AWS Lightsail & AWS EC2)
# ==============================================================================
set -e

echo "=================================================="
echo ">>> Starting Automated IoT Fleet Platform Setup..."
echo "=================================================="

# 1. Require root or sudo privileges
if [ "$EUID" -ne 0 ]; then
  echo ">>> Requesting sudo privileges..."
  exec sudo bash "$0" "$@"
fi

# 2. Determine target install directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/iot-fleet-platform"

echo ">>> Updating apt package lists..."
apt-get update -y
apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git \
    ufw \
    build-essential

# 3. Synchronize application source to /opt/iot-fleet-platform
if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    echo ">>> Deploying application files to $INSTALL_DIR..."
    mkdir -p "$INSTALL_DIR"
    cp -ru "$SCRIPT_DIR"/* "$INSTALL_DIR"/ 2>/dev/null || rsync -av --exclude='.git' --exclude='.venv' "$SCRIPT_DIR"/ "$INSTALL_DIR"/
else
    echo ">>> Already running inside $INSTALL_DIR."
fi

cd "$INSTALL_DIR"

# 4. Create uploads directory for OTA firmware binaries
mkdir -p "$INSTALL_DIR/backend/uploads/firmware"
chmod -R 775 "$INSTALL_DIR/backend/uploads"

# 5. Create Python Virtual Environment & Install Dependencies
echo ">>> Creating Python virtual environment..."
python3 -m venv "$INSTALL_DIR/.venv"
source "$INSTALL_DIR/.venv/bin/activate"

echo ">>> Upgrading pip and installing requirements..."
pip install --upgrade pip
pip install -r "$INSTALL_DIR/requirements.txt"

# 6. Initialize database schema & seed initial admin & sample devices
echo ">>> Bootstrapping platform database & fleet records..."
python3 -c "
import sys, os
sys.path.insert(0, os.path.abspath('backend'))
from src.db.session import engine, SessionLocal
from src.db.base import Base
from src.db.seed import seed_database
from src.db.models.user import User

Base.metadata.create_all(bind=engine)
db = SessionLocal()
admin = db.query(User).filter_by(username='admin').first()
if not admin:
    print('>>> Fresh setup: Seeding default manufacturer admin & device types...')
    seed_database(db)
    print('>>> Seed records created successfully.')
else:
    print('>>> Existing admin user detected, skipping seeding.')
db.close()
"

# 7. Configure Systemd Service for Auto-Start & Auto-Restart on Boot
echo ">>> Configuring systemd service: iot-fleet-platform.service..."
cat << 'EOF' > /etc/systemd/system/iot-fleet-platform.service
[Unit]
Description=IoT Fleet Platform - FastAPI Server, Web Portal & OTA Engine
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/iot-fleet-platform
Environment="PYTHONPATH=/opt/iot-fleet-platform/backend"
Environment="PORT=8000"
ExecStart=/opt/iot-fleet-platform/.venv/bin/uvicorn src.main:app --app-dir backend --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

# Resource & File Descriptor Limits for high device concurrency
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

# 8. Reload systemd, enable service on boot, and start service
echo ">>> Starting IoT Fleet Platform service..."
systemctl daemon-reload
systemctl enable iot-fleet-platform.service
systemctl restart iot-fleet-platform.service

# 9. Configure UFW Firewall rules
echo ">>> Configuring firewall rules (SSH, HTTP, Port 8000)..."
ufw allow 22/tcp >/dev/null 2>&1 || true
ufw allow 80/tcp >/dev/null 2>&1 || true
ufw allow 443/tcp >/dev/null 2>&1 || true
ufw allow 8000/tcp >/dev/null 2>&1 || true
ufw --force enable >/dev/null 2>&1 || true

# 10. Fetch Public IP Address
PUBLIC_IP=$(curl -s -m 5 http://checkip.amazonaws.com || curl -s -m 5 https://ifconfig.me || echo "YOUR_SERVER_IP")
PUBLIC_IP=$(echo "$PUBLIC_IP" | tr -d '[:space:]')

echo ""
echo "=========================================================================="
echo "🚀 IOT FLEET PLATFORM DEPLOYED SUCCESSFULLY ON AWS!"
echo "=========================================================================="
echo "📍 Public Server IP       : $PUBLIC_IP"
echo "🌐 Manufacturer Web Portal : http://$PUBLIC_IP:8000/portal"
echo "📖 Swagger API Docs        : http://$PUBLIC_IP:8000/docs"
echo "🔑 Default Superadmin      : admin"
echo "🔒 Default Password        : Admin@SecurePlatform2026!"
echo "--------------------------------------------------------------------------"
echo "📡 ESP32 ARDUINO FIRMWARE CONFIGURATION:"
echo "   In firmware/arduino/esp32_iot_node/esp32_iot_node.ino, set line 46:"
echo "   const char* SERVER_BASE_URL = \"http://$PUBLIC_IP:8000\";"
echo "--------------------------------------------------------------------------"
echo "🛠️ USEFUL SERVICE COMMANDS:"
echo "   View live logs : sudo journalctl -u iot-fleet-platform -f"
echo "   Restart server : sudo systemctl restart iot-fleet-platform"
echo "   Check status   : sudo systemctl status iot-fleet-platform"
echo "=========================================================================="
