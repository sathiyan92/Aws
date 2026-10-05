"""
Cryptographic password hashing and verification utilities.
Uses PBKDF2-HMAC-SHA256 with 600,000 iterations and per-user cryptographic salt.
"""
import hashlib
import os
import secrets

ITERATIONS = 600_000


def hash_password(password: str) -> str:
    """Hash a plaintext password using PBKDF2-HMAC-SHA256 with a secure salt."""
    salt = secrets.token_hex(16)
    hash_bytes = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        ITERATIONS,
    )
    return f"pbkdf2:sha256:{ITERATIONS}${salt}${hash_bytes.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against the stored PBKDF2 hash."""
    try:
        header, salt, stored_hash = hashed_password.split("$")
        method, alg, iterations_str = header.split(":")
        iterations = int(iterations_str)
        computed_hash = hashlib.pbkdf2_hmac(
            alg,
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        return secrets.compare_digest(computed_hash, stored_hash)
    except Exception:
        return False
