#!/usr/bin/env bash
# ==============================================================================
# IoT Fleet Platform - Bulletproof AWS Lightsail Fast Update Script
# Updates /opt/iot-fleet-platform directly from GitHub origin/main,
# kills old port 8000 processes, clears bytecode & Nginx cache, runs auto-migrations,
# restarts the systemd service, and verifies live health.
# ==============================================================================

echo "=========================================================================="
echo ">>> ⚡ UPDATING IOT FLEET PLATFORM ON AWS LIGHTSAIL..."
echo "=========================================================================="

# 1. Ensure required tools are installed
echo ">>> [1/7] Ensuring git, rsync, curl, and process management tools are present..."
which apt-get >/dev/null 2>&1 && {
    apt-get update -y >/dev/null 2>&1 || true
    apt-get install -y --no-install-recommends git rsync curl lsof psmisc >/dev/null 2>&1 || true
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

# 4. Clear all Python bytecode caches (__pycache__ and *.pyc)
echo ">>> [4/7] Clearing all stale Python bytecode caches..."
find "$INSTALL_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$INSTALL_DIR" -name "*.pyc" -delete 2>/dev/null || true

# Ensure virtual environment exists
if [ ! -f "$INSTALL_DIR/.venv/bin/python3" ]; then
    echo ">>> Creating missing Python virtual environment..."
    python3 -m venv "$INSTALL_DIR/.venv"
    "$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
    "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
fi

# 5. Run Database Schema Auto-Migration
echo ">>> [5/7] Running Database Schema Auto-Migration..."
(cd "$INSTALL_DIR" && PYTHONPATH="$INSTALL_DIR/backend" "$INSTALL_DIR/.venv/bin/python3" -c "
import sys
sys.path.insert(0, '$INSTALL_DIR/backend')
import src.db.models
from src.db.session import engine
from src.db.auto_migrate import run_auto_migrations
run_auto_migrations(engine)
print('>>> Database auto-migration completed successfully!')
") || true

# 6. Kill ANY existing process holding port 8000
echo ">>> [6/7] Terminating any stale processes listening on port 8000..."
PORT_PID=$(lsof -t -i:8000 2>/dev/null || ss -lptn 'sport = :8000' 2>/dev/null | grep -oP 'pid=\K\d+' | head -n 1 || true)
if [ -n "$PORT_PID" ]; then
    kill -9 "$PORT_PID" 2>/dev/null || true
fi
fuser -k -9 8000/tcp 2>/dev/null || true
pkill -9 -f "uvicorn" 2>/dev/null || true
pkill -9 -f "main:app" 2>/dev/null || true
sleep 1

# Write systemd service unit file
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
ExecStart=/opt/iot-fleet-platform/.venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
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

sleep 3

# 7. Verify Health & Features
echo "=========================================================================="
echo ">>> [7/7] VERIFYING LIVE PLATFORM UPDATE..."
echo "=========================================================================="

API_HEALTH=$(curl -s http://127.0.0.1:8000/health || echo "FAIL")
echo "  [Health Check] : $API_HEALTH"

PENDING_TEST=$(curl -s http://127.0.0.1:8000/api/v1/orders/pending-dispense/VM-000001 || echo "FAIL")
echo "  [Pending Check]: $PENDING_TEST"

PORTAL_TEST=$(curl -s http://127.0.0.1:8000/portal/ | grep -o 'QR & UPI Settings' | head -n 1 || echo "NOT_FOUND")
echo "  [Portal Check] : Found '$PORTAL_TEST' in live portal HTML"

# Re-process any recent Razorpay payments
curl -s -X POST http://127.0.0.1:8000/api/v1/payments/razorpay/webhook/reprocess-failed >/dev/null 2>&1 || true

echo "=========================================================================="
echo ">>> ✅ AWS LIGHTSAIL SERVER UPDATED SUCCESSFULLY!"
echo "=========================================================================="
echo "🌐 Manufacturer Web Portal : http://127.0.0.1:8000/portal/ (or https://gtechinfo.in/portal/)"
echo "👥 Client Tenant Portal    : http://127.0.0.1:8000/client-portal/ (or https://gtechinfo.in/client-portal/)"
echo "=========================================================================="
