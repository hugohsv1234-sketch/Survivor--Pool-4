"""Password hashing and opaque session tokens; no passwords reach the client."""
import hashlib
import hmac
import secrets


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                            n=32768, r=8, p=3, maxmem=64 * 1024 * 1024).hex()
    return f"scrypt$32768$8$3${salt}${digest}"


def verify_password(password, encoded):
    try:
        method, n, r, p, salt, expected = encoded.split("$")
        if method != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                                n=int(n), r=int(r), p=int(p),
                                maxmem=64 * 1024 * 1024).hex()
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def token():
    return secrets.token_urlsafe(32)


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()
