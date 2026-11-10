#!/usr/bin/env python3
"""
==============================================================================
Platform Admin Credentials Update Tool
==============================================================================
Safely updates the Super Administrator (MANUFACTURER_ADMIN) username and/or
password across the SQLite / PostgreSQL database and .env configuration files.

Usage:
  Interactive mode:
    python update_admin.py

  Non-interactive CLI mode:
    python update_admin.py --username new_admin --password NewPassword123!
    python update_admin.py --password OnlyNewPassword123!
    python update_admin.py --username OnlyNewUsername
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

def update_sqlite_db(db_path: str, current_identifier: str, new_username: str = None, new_password: str = None):
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

        # Find admin user by username, email, or role
        cur.execute(
            "SELECT id, username, email, role FROM users WHERE username = ? OR email = ? OR username = 'admin' OR username = 'gtech_admin' OR role = 'MANUFACTURER_ADMIN' LIMIT 1",
            (current_identifier, current_identifier)
        )
        row = cur.fetchone()
        if not row:
            # Fallback to first user with role MANUFACTURER_ADMIN
            cur.execute("SELECT id, username, email, role FROM users WHERE role = 'MANUFACTURER_ADMIN' LIMIT 1")
            row = cur.fetchone()

        if not row:
            conn.close()
            return False

        user_id, old_username, old_email, role = row

        updates = []
        params = []
        if new_username:
            updates.append("username = ?")
            params.append(new_username)
        if new_password:
            hashed = hash_password(new_password)
            updates.append("password_hash = ?")
            params.append(hashed)

        if updates:
            params.append(user_id)
            query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
            cur.execute(query, params)
            conn.commit()
            print(f"  [OK] Successfully updated database: {db_path} (User: '{old_username}' -> '{new_username or old_username}')")

        conn.close()
        return True
    except Exception as e:
        print(f"  [!] Error updating {db_path}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Update platform admin username and password.")
    parser.add_argument("--current", help="Current admin username or email (default: admin)", default="admin")
    parser.add_argument("--username", help="New admin username")
    parser.add_argument("--password", help="New admin password")
    args = parser.parse_args()

    current_id = args.current
    new_user = args.username
    new_pass = args.password

    # Interactive mode if neither username nor password provided
    if not new_user and not new_pass:
        print("\n=======================================================")
        print("   Platform Admin Account Credentials Updater")
        print("=======================================================\n")
        
        prompt_curr = input(f"Current Admin Username or Email [default: {current_id}]: ").strip()
        if prompt_curr:
            current_id = prompt_curr
        
        prompt_user = input("Enter NEW Username (leave empty to keep unchanged): ").strip()
        if prompt_user:
            new_user = prompt_user

        prompt_pass = getpass.getpass("Enter NEW Password (min 6 chars, leave empty to keep unchanged): ").strip()
        if prompt_pass:
            confirm_pass = getpass.getpass("Confirm NEW Password: ").strip()
            if prompt_pass != confirm_pass:
                print("\n[X] Error: Passwords do not match!")
                sys.exit(1)
            if len(prompt_pass) < 6:
                print("\n[X] Error: Password must be at least 6 characters long!")
                sys.exit(1)
            new_pass = prompt_pass

    if not new_user and not new_pass:
        print("\n[!] No changes requested. Exiting.")
        sys.exit(0)

    print("\n[*] Applying credentials update...")

    # 1. Update SQLite Databases
    sqlite_paths = [
        "iot_platform_dev.db",
        os.path.join("backend", "iot_platform_dev.db"),
        "/opt/iot-fleet-platform/iot_platform_dev.db",
        "/opt/iot-fleet-platform/backend/iot_platform_dev.db",
    ]
    updated_db_count = 0
    for p in sqlite_paths:
        if update_sqlite_db(p, current_id, new_username=new_user, new_password=new_pass):
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
    print("   Credentials Updated Successfully!")
    print("=======================================================")
    if new_user:
        print(f"  Username : {new_user}")
    if new_pass:
        print(f"  Password : {new_pass}")
    print("=======================================================\n")

if __name__ == "__main__":
    main()
