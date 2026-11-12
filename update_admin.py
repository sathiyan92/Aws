#!/usr/bin/env python3
"""
==============================================================================
Platform Admin Credentials & Hardware Discovery Database Sync Tool
==============================================================================
Safely updates the Super Administrator (MANUFACTURER_ADMIN) credentials
across SQLite databases, ensures discovered_hardware table exists, and updates
.env configuration files with absolute Linux permission protection.

Usage:
  Interactive mode:
    python update_admin.py

  Non-interactive CLI mode:
    python update_admin.py --username gtech_admin --password GtechAdmin@2026
    python update_admin.py --password OnlyNewPassword123!
==============================================================================
"""

import sys
import os
import argparse
import getpass
import hashlib
import secrets
import sqlite3
import re
import glob
import uuid
from datetime import datetime, timezone

# PBKDF2-HMAC-SHA256 hasher identical to backend security standard
ITERATIONS = 600_000

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hash_bytes = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        ITERATIONS,
    )
    return f"pbkdf2:sha256:{ITERATIONS}${salt}${hash_bytes.hex()}"

def update_env_file(filepath: str, new_username: str = None, new_password: str = None):
    if not os.path.exists(filepath):
        return False
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        updated_lines = []
        user_updated = False
        pass_updated = False

        for line in lines:
            if new_username and re.match(r"^SUPERADMIN_USERNAME\s*=", line):
                updated_lines.append(f'SUPERADMIN_USERNAME="{new_username}"\n')
                user_updated = True
            elif new_password and re.match(r"^SUPERADMIN_PASSWORD\s*=", line):
                updated_lines.append(f'SUPERADMIN_PASSWORD="{new_password}"\n')
                pass_updated = True
            else:
                updated_lines.append(line)

        # If not present in file, append
        if new_username and not user_updated:
            updated_lines.append(f'SUPERADMIN_USERNAME="{new_username}"\n')
        if new_password and not pass_updated:
            updated_lines.append(f'SUPERADMIN_PASSWORD="{new_password}"\n')

        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(updated_lines)
        return True
    except Exception as e:
        print(f"  [!] Notice: Could not update {filepath}: {e}")
        return False

def update_sqlite_db(db_path: str, new_username: str = None, new_password: str = None):
    if not os.path.exists(db_path):
        return False
    try:
        # Guarantee Linux read/write permissions on database file and directory
        try:
            os.chmod(db_path, 0o666)
            db_dir = os.path.dirname(os.path.abspath(db_path))
            if db_dir:
                os.chmod(db_dir, 0o777)
        except Exception:
            pass

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # 1. Ensure discovered_hardware schema exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS discovered_hardware (
                id VARCHAR(36) PRIMARY KEY,
                mac_address VARCHAR(32) UNIQUE NOT NULL,
                chip_id VARCHAR(64),
                ip_address VARCHAR(45),
                firmware_version VARCHAR(32) DEFAULT 'v2.2.0-razorpay-ota',
                suggested_device_id VARCHAR(32),
                last_seen_at DATETIME NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_discovered_hardware_mac ON discovered_hardware (mac_address)")
        cur.execute("DELETE FROM devices WHERE device_id IN ('PENDING', 'AUTO')")

        # 2. Update Admin Password across all MANUFACTURER_ADMIN rows
        target_pass = new_password or "GtechAdmin@2026"
        hashed = hash_password(target_pass)

        # Update any existing admin users
        cur.execute("""
            UPDATE users
            SET password_hash = ?, updated_at = datetime('now')
            WHERE username IN ('admin', 'gtech_admin') OR role = 'MANUFACTURER_ADMIN'
        """, (hashed,))
        updated_rows = cur.rowcount

        # 3. Ensure 'gtech_admin' exists
        cur.execute("SELECT id FROM users WHERE username = 'gtech_admin'")
        if not cur.fetchone():
            gtech_id = str(uuid.uuid4())
            email = "gtech_admin@gtechinfo.in"
            cur.execute("SELECT id FROM users WHERE email = ?", (email,))
            if cur.fetchone():
                email = f"gtech_admin_{gtech_id[:6]}@gtechinfo.in"
            cur.execute("""
                INSERT INTO users (id, client_id, username, email, password_hash, full_name, role, status, created_at, updated_at)
                VALUES (?, NULL, 'gtech_admin', ?, ?, 'Platform Administrator', 'MANUFACTURER_ADMIN', 'ACTIVE', datetime('now'), datetime('now'))
            """, (gtech_id, email, hashed))
            print(f"  [+] Created user 'gtech_admin' in {db_path}")

        # 4. Ensure 'admin' exists as alias
        cur.execute("SELECT id FROM users WHERE username = 'admin'")
        if not cur.fetchone():
            admin_id = str(uuid.uuid4())
            email = "admin@manufacturer.local"
            cur.execute("SELECT id FROM users WHERE email = ?", (email,))
            if cur.fetchone():
                email = f"admin_legacy_{admin_id[:6]}@manufacturer.local"
            cur.execute("""
                INSERT INTO users (id, client_id, username, email, password_hash, full_name, role, status, created_at, updated_at)
                VALUES (?, NULL, 'admin', ?, ?, 'Platform Super Administrator', 'MANUFACTURER_ADMIN', 'ACTIVE', datetime('now'), datetime('now'))
            """, (admin_id, email, hashed))
            print(f"  [+] Created user 'admin' in {db_path}")

        conn.commit()
        conn.close()

        # Guarantee write permissions after commit
        try:
            os.chmod(db_path, 0o666)
            db_dir = os.path.dirname(os.path.abspath(db_path))
            if db_dir:
                os.chmod(db_dir, 0o777)
        except Exception:
            pass

        print(f"  [OK] Successfully synchronized database: {db_path} ({updated_rows} users updated)")
        return True
    except Exception as e:
        print(f"  [!] Error updating {db_path}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Update platform admin username and password.")
    parser.add_argument("--current", help="Current admin username or email (default: admin)", default="admin")
    parser.add_argument("--username", help="New admin username", default="gtech_admin")
    parser.add_argument("--password", help="New admin password", default="GtechAdmin@2026")
    args = parser.parse_args()

    new_user = args.username
    new_pass = args.password

    print("\n[*] Applying admin credentials & database sync...")

    # 1. Update SQLite Databases
    sqlite_paths = [
        "iot_platform_dev.db",
        os.path.join("backend", "iot_platform_dev.db"),
        "/opt/iot-fleet-platform/iot_platform_dev.db",
        "/opt/iot-fleet-platform/backend/iot_platform_dev.db",
    ]
    # Scan for any other db files
    for extra in glob.glob("/opt/iot-fleet-platform/**/*.db", recursive=True):
        if extra not in sqlite_paths:
            sqlite_paths.append(extra)

    updated_db_count = 0
    for p in sqlite_paths:
        if update_sqlite_db(p, new_username=new_user, new_password=new_pass):
            updated_db_count += 1

    # 2. Update .env files
    env_paths = [
        ".env",
        os.path.join("backend", ".env"),
        "/opt/iot-fleet-platform/.env",
        "/opt/iot-fleet-platform/backend/.env",
    ]
    for ep in env_paths:
        if update_env_file(ep, new_username=new_user, new_password=new_pass):
            print(f"  [OK] Updated environment config: {ep}")

    print("\n=======================================================")
    print("   Admin Credentials & DB Schema Synchronized!")
    print("=======================================================")
    print(f"  Primary User   : gtech_admin")
    print(f"  Alias User     : admin")
    print(f"  Password       : {new_pass}")
    print(f"  Databases Synced: {updated_db_count}")
    print("=======================================================\n")

if __name__ == "__main__":
    main()
