#!/usr/bin/env python3
"""
IoT Fleet Platform - Administrative Password Reset Utility
===========================================================
Allows server administrators to securely reset passwords for any account
(Manufacturer Admin or Tenant Vendor) directly from the command line.

Usage:
    python reset_admin_password.py <username_or_email> <new_password>

Examples:
    # Reset Super-Admin password:
    python reset_admin_password.py admin MyNewSecurePassword2026!

    # Reset a Vendor's password:
    python reset_admin_password.py gtech_vendor VendorSecret@789
"""
import sys
import os

# Include backend directory in python path
backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
sys.path.insert(0, backend_dir)

try:
    from src.db.session import SessionLocal
    from src.db.models.user import User
    from src.core.security.hashing import hash_password
except ImportError as err:
    print(f"[!] Error loading application modules: {err}")
    print("    Ensure you run this script from /opt/iot-fleet-platform on AWS.")
    sys.exit(1)


def reset_user_password(identifier: str, new_pass: str):
    if len(new_pass.strip()) < 6:
        print("[!] Error: New password must be at least 6 characters long.")
        return False

    db = SessionLocal()
    try:
        user = db.query(User).filter(
            (User.username == identifier.strip()) | (User.email == identifier.strip())
        ).first()

        if not user:
            print(f"[✗] User with username or email '{identifier}' was not found in the database.")
            print("\nAvailable registered users in database:")
            all_users = db.query(User).all()
            for u in all_users:
                print(f"  - Username: {u.username:<15} | Email: {u.email:<25} | Role: {u.role}")
            return False

        user.password_hash = hash_password(new_pass.strip())
        user.status = "ACTIVE"
        db.commit()

        print("\n==================================================================")
        print(">>> [✓] PASSWORD UPDATED SUCCESSFULLY! <<<")
        print(f"  User ID    : {user.id}")
        print(f"  Username   : {user.username}")
        print(f"  Email      : {user.email}")
        print(f"  Role       : {user.role}")
        print(f"  Client ID  : {user.client_id or '(Manufacturer)'}")
        print("==================================================================")
        print("You can now sign in immediately using your new password!\n")
        return True
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    ident = sys.argv[1]
    pwd = sys.argv[2]
    reset_user_password(ident, pwd)
