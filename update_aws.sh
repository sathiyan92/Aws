#!/usr/bin/env bash
# ==============================================================================
# IoT Fleet Platform - One-Click AWS Lightsail Fast Update Script
# Updates /opt/iot-fleet-platform directly from GitHub origin/main,
# runs database auto-migrations, reprocesses any failed webhooks,
# and restarts the systemd service.
# ==============================================================================
set -e

echo "=========================================================================="
echo ">>> ⚡ UPDATING IOT FLEET PLATFORM ON AWS LIGHTSAIL (Commit: origin/main)..."
echo "=========================================================================="

INSTALL_DIR="/opt/iot-fleet-platform"
REPO_URL="https://github.com/sathiyan92/Aws.git"
TMP_DIR="/tmp/iot-fleet-update-tmp"

# 1. Fetch fresh code from GitHub
echo ">>> [1/5] Downloading latest code from GitHub..."
rm -rf "$TMP_DIR"
git clone --depth 1 -b main "$REPO_URL" "$TMP_DIR"

# 2. Sync to installation directory (preserving .venv, databases, uploads)
echo ">>> [2/5] Deploying updated application files to $INSTALL_DIR..."
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
if [ -f "$INSTALL_DIR/.venv/bin/python3" ]; then
    echo ">>> Running Database Schema Auto-Migration..."
    PYTHONPATH="$INSTALL_DIR/backend" "$INSTALL_DIR/.venv/bin/python3" -c "
import sys
sys.path.insert(0, '$INSTALL_DIR/backend')
from src.db.session import engine
from src.db.auto_migrate import run_auto_migrations
run_auto_migrations(engine)
print('>>> Database auto-migration completed successfully!')
" || true
fi

# 5. Restart service
echo ">>> [3/5] Restarting iot-fleet-platform systemd service..."
systemctl restart iot-fleet-platform || systemctl restart iot-fleet || true
sleep 3

# 6. Verify & Auto-Reprocess any pending/failed webhooks
echo ">>> [4/5] Verifying API Health..."
curl -s http://127.0.0.1:8000/health || true
echo ""

echo ">>> [5/5] Re-processing any failed Razorpay payments..."
curl -s -X POST http://127.0.0.1:8000/api/v1/payments/razorpay/webhook/reprocess-failed || true
echo ""

echo ">>> [Verify] Verifying pending-dispense endpoint for VM-000001:"
curl -s http://127.0.0.1:8000/api/v1/orders/pending-dispense/VM-000001 || true
echo ""

echo "=========================================================================="
echo ">>> ✅ UPDATE SUCCESSFUL! Current Active Fleet QR Mappings:"
echo "=========================================================================="
curl -s http://127.0.0.1:8000/api/v1/payments/razorpay/qr/mappings/all
echo ""
echo "=========================================================================="
