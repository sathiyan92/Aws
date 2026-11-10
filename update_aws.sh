#!/usr/bin/env bash
# ==============================================================================
# IoT Fleet Platform - Bulletproof AWS Lightsail Fast Update Script
# Updates /opt/iot-fleet-platform directly from GitHub origin/main,
# installs OS and Python dependencies, runs auto-migrations,
# restarts the systemd service, and verifies live health.
# ==============================================================================

echo "=========================================================================="
echo ">>> ⚡ UPDATING IOT FLEET PLATFORM ON AWS LIGHTSAIL..."
echo "=========================================================================="

# 1. Ensure required system packages and libraries are installed
echo ">>> [1/7] Ensuring git, rsync, curl, lsof, psmisc, libzbar0, and python3-venv are present..."
which apt-get >/dev/null 2>&1 && {
    apt-get update -y >/dev/null 2>&1 || true
    apt-get install -y --no-install-recommends git rsync curl lsof psmisc libzbar0 python3-pip python3-venv >/dev/null 2>&1 || true
}

INSTALL_DIR="/opt/iot-fleet-platform"
REPO_URL="https://github.com/sathiyan92/Aws.git"
TMP_DIR="/tmp/iot-fleet-update-tmp"

# 2. Download fresh code from GitHub
echo ">>> [2/7] Downloading latest code from GitHub origin/main..."
rm -rf "$TMP_DIR"
git clone --depth 1 -b main "$REPO_URL" "$TMP_DIR"

if [ ! -d "$TMP_DIR/backend" ]; then
    echo ">>> [!] ERROR: Git clone failed or repository is unreachable!"
    exit 1
fi

# 3. Deploy updated application files to /opt/iot-fleet-platform
echo ">>> [3/7] Deploying application files to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
rsync -av --delete \
    --exclude='.venv' \
    --exclude='.git' \
    --exclude='*.db' \
    --exclude='*.sqlite*' \
    --exclude='backend/uploads' \
    "$TMP_DIR/" "$INSTALL_DIR/"

# Also update secondary directories if they exist
for alt in "/home/ubuntu/iot-fleet-platform" "/home/ubuntu/Aws" "/root/iot-fleet-platform"; do
    if [ -d "$alt" ] && [ "$alt" != "$INSTALL_DIR" ]; then
        echo ">>> Syncing secondary directory: $alt..."
        rsync -av --delete \
            --exclude='.venv' \
            --exclude='.git' \
            --exclude='*.db' \
            --exclude='*.sqlite*' \
            --exclude='backend/uploads' \
            "$TMP_DIR/" "$alt/" 2>/dev/null || true
    fi
done

rm -rf "$TMP_DIR"

# Ensure permissions
mkdir -p "$INSTALL_DIR/backend/uploads/firmware"
chmod -R 775 "$INSTALL_DIR/backend/uploads" 2>/dev/null || true

# 4. Clear all Python bytecode caches and install Python dependencies
echo ">>> [4/7] Installing / updating Python dependencies..."
find "$INSTALL_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$INSTALL_DIR" -name "*.pyc" -delete 2>/dev/null || true

PYTHON_BIN="$INSTALL_DIR/.venv/bin/python3"
PIP_BIN="$INSTALL_DIR/.venv/bin/pip"

if [ ! -x "$PYTHON_BIN" ] || [ ! -x "$PIP_BIN" ]; then
    echo ">>> Creating Python virtual environment at $INSTALL_DIR/.venv..."
    rm -rf "$INSTALL_DIR/.venv"
    python3 -m venv "$INSTALL_DIR/.venv" || true
fi

if [ -x "$INSTALL_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$INSTALL_DIR/.venv/bin/python3"
    PIP_BIN="$INSTALL_DIR/.venv/bin/pip"
else
    echo ">>> Notice: Falling back to system python3..."
    PYTHON_BIN="$(which python3)"
    PIP_BIN="$(which pip3 || which pip)"
fi

echo "  Python executable: $PYTHON_BIN"
echo "  Pip executable   : $PIP_BIN"

$PIP_BIN install --upgrade pip >/dev/null 2>&1 || true
$PIP_BIN install -r "$INSTALL_DIR/requirements.txt"

# 5. Run Database Schema Auto-Migration
echo ">>> [5/7] Running Database Schema Auto-Migration..."
(cd "$INSTALL_DIR" && PYTHONPATH="$INSTALL_DIR/backend" "$PYTHON_BIN" -c "
import sys
sys.path.insert(0, '$INSTALL_DIR/backend')
import src.db.models
from src.db.session import engine
from src.db.auto_migrate import run_auto_migrations
run_auto_migrations(engine)
print('>>> Database auto-migration completed successfully!')
") || true

# 5b. Update Platform Admin Credentials
echo ">>> Updating Administrator Credentials (gtech_admin)..."
(cd "$INSTALL_DIR" && "$PYTHON_BIN" "$INSTALL_DIR/update_admin.py" --username gtech_admin --password Gtech042814516!) || true

# Test running backend import directly to catch any import errors
echo ">>> Verifying backend application imports..."
(cd "$INSTALL_DIR" && "$PYTHON_BIN" -c "
import sys
sys.path.insert(0, '$INSTALL_DIR/backend')
import main
from src.main import app
print('>>> Application entrypoint and FastAPI app verified successfully!')
") || {
    echo ">>> [!] WARNING: Application import test failed! Check dependencies above."
}

# 6. Kill ANY existing process holding port 8000
echo ">>> [6/7] Terminating any stale processes listening on port 8000..."
PORT_PID=$(lsof -t -i:8000 2>/dev/null || ss -lptn 'sport = :8000' 2>/dev/null | grep -oP 'pid=\K\d+' | head -n 1 || true)
if [ -n "$PORT_PID" ]; then
    kill -9 "$PORT_PID" 2>/dev/null || true
fi
fuser -k -9 8000/tcp 2>/dev/null || true
pkill -9 -f "uvicorn" 2>/dev/null || true
pkill -9 -f "run_server" 2>/dev/null || true
pkill -9 -f "main:app" 2>/dev/null || true
sleep 1

# Write systemd service unit file dynamically referencing verified Python binary
cat << EOF > /etc/systemd/system/iot-fleet-platform.service
[Unit]
Description=IoT Fleet Platform - FastAPI Server, Web Portal & OTA Engine
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/iot-fleet-platform
Environment="PYTHONPATH=/opt/iot-fleet-platform/backend"
Environment="PORT=8000"
ExecStart=$PYTHON_BIN /opt/iot-fleet-platform/run_server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable iot-fleet-platform.service
systemctl restart iot-fleet-platform.service

# Reload Nginx if present and clear cache
echo ">>> Refreshing Nginx web server..."
rm -rf /var/cache/nginx/* 2>/dev/null || true
systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || true

# 7. Wait and Verify Health & Features
echo "=========================================================================="
echo ">>> [7/7] WAITING FOR SERVER STARTUP & VERIFYING HEALTH..."
echo "=========================================================================="

API_HEALTH="FAIL"
for i in $(seq 1 15); do
    API_HEALTH=$(curl -s http://127.0.0.1:8000/health || echo "FAIL")
    if [[ "$API_HEALTH" == *"healthy"* ]]; then
        echo "  [Health Check] : $API_HEALTH (ready after ${i}s)"
        break
    fi
    sleep 1
done

if [[ "$API_HEALTH" != *"healthy"* ]]; then
    echo "  [Health Check] : $API_HEALTH"
    echo ">>> [!] Server did not respond within 15 seconds! Fetching systemd diagnostic logs:"
    echo "--------------------------------------------------------------------------"
    systemctl status iot-fleet-platform.service --no-pager -l || true
    echo "--------------------------------------------------------------------------"
    journalctl -u iot-fleet-platform.service -n 35 --no-pager || true
    echo "--------------------------------------------------------------------------"
fi

PENDING_TEST=$(curl -s http://127.0.0.1:8000/api/v1/orders/pending-dispense/VM-000001 || echo "FAIL")
echo "  [Pending Check]: $PENDING_TEST"

PORTAL_TEST=$(curl -s http://127.0.0.1:8000/portal/ | grep -o 'QR & UPI Settings' | head -n 1 || echo "NOT_FOUND")
echo "  [Portal Check] : Found '$PORTAL_TEST' in live portal HTML"

# Re-process any recent Razorpay payments
curl -s -X POST http://127.0.0.1:8000/api/v1/payments/razorpay/webhook/reprocess-failed >/dev/null 2>&1 || true

echo "=========================================================================="
echo ">>> ✅ AWS LIGHTSAIL SERVER DEPLOYMENT COMPLETED!"
echo "=========================================================================="
echo "🌐 Manufacturer Web Portal : http://127.0.0.1:8000/portal/ (or https://gtechinfo.in/portal/)"
echo "👥 Client Tenant Portal    : http://127.0.0.1:8000/client-portal/ (or https://gtechinfo.in/client-portal/)"
echo "=========================================================================="
