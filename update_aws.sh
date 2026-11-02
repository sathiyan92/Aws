#!/usr/bin/env bash
# ==============================================================================
# IoT Fleet Platform - One-Click AWS Lightsail Fast Update Script
# Updates /opt/iot-fleet-platform directly from GitHub origin/main,
# runs database auto-migrations, reprocesses any failed webhooks,
# and restarts the systemd service.
# ==============================================================================
set -e

echo "=========================================================================="
echo ">>> ⚡ UPDATING IOT FLEET PLATFORM ON AWS LIGHTSAIL..."
echo "=========================================================================="

INSTALL_DIR="/opt/iot-fleet-platform"
REPO_URL="https://github.com/sathiyan92/Aws.git"
TMP_DIR="/tmp/iot-fleet-update-tmp"

# 1. Fetch fresh code from GitHub
echo ">>> [1/6] Downloading latest code from GitHub..."
rm -rf "$TMP_DIR"
git clone --depth 1 -b main "$REPO_URL" "$TMP_DIR"

# 2. Sync to installation directory (preserving .venv, databases, uploads)
echo ">>> [2/6] Deploying updated application files to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
rsync -av --delete \
    --exclude='.venv' \
    --exclude='.git' \
    --exclude='*.db' \
    --exclude='*.sqlite*' \
    --exclude='backend/uploads' \
    "$TMP_DIR/" "$INSTALL_DIR/"

rm -rf "$TMP_DIR"

# 3. Ensure permissions
mkdir -p "$INSTALL_DIR/backend/uploads/firmware"
chmod -R 775 "$INSTALL_DIR/backend/uploads" 2>/dev/null || true

# 4. Explicitly run database auto-migrations using the virtual environment
echo ">>> [3/6] Running Database Schema Auto-Migration..."
if [ -f "$INSTALL_DIR/.venv/bin/python3" ]; then
    (cd "$INSTALL_DIR" && PYTHONPATH="$INSTALL_DIR/backend" "$INSTALL_DIR/.venv/bin/python3" -c "
import sys
sys.path.insert(0, '$INSTALL_DIR/backend')
import src.db.models
from src.db.session import engine
from src.db.auto_migrate import run_auto_migrations
run_auto_migrations(engine)
print('>>> Database auto-migration completed successfully!')
") || true
fi

# 5. Stop any existing background processes holding port 8000 and restart service
echo ">>> [4/6] Ensuring port 8000 is clean and restarting systemd service..."
fuser -k 8000/tcp 2>/dev/null || true
pkill -9 -f "uvicorn" 2>/dev/null || true
sleep 1

# Ensure systemd service configuration is up to date
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
ExecStart=/opt/iot-fleet-platform/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable iot-fleet-platform.service
systemctl restart iot-fleet-platform.service
sleep 3

# 6. Verify Service Status and API Health
echo ">>> [5/6] Verifying API Health..."
curl -s http://127.0.0.1:8000/health || true
echo ""

echo ">>> [6/6] Re-processing any recent Razorpay payments..."
curl -s -X POST http://127.0.0.1:8000/api/v1/payments/razorpay/webhook/reprocess-failed || true
echo ""

echo ">>> [Verify] Checking pending-dispense endpoint for VM-000001:"
curl -s http://127.0.0.1:8000/api/v1/orders/pending-dispense/VM-000001 || true
echo ""

echo "=========================================================================="
echo ">>> ✅ ACTIVE FLEET QR MAPPINGS:"
echo "=========================================================================="
curl -s http://127.0.0.1:8000/api/v1/payments/razorpay/qr/mappings/all || true
echo ""
echo "=========================================================================="
