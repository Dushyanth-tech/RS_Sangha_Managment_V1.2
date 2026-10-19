import os
import hashlib
import hmac
from cryptography.fernet import Fernet
from dotenv import load_dotenv
load_dotenv()

_key = os.environ["BANK_ENCRYPTION_KEY"].encode()
_fernet = Fernet(_key)

def encrypt_value(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()

def decrypt_value(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()

def encrypt_bytes(data: bytes) -> bytes:
    return _fernet.encrypt(data)

def decrypt_bytes(token: bytes) -> bytes:
    return _fernet.decrypt(token)

# Separate secret for fingerprints. Set FINGERPRINT_KEY in .env; falls back to a key derived from BANK_ENCRYPTION_KEY.
_hmac_key = (
    os.environ.get("FINGERPRINT_KEY")
    or hashlib.sha256(b"fingerprint:" + os.environ["BANK_ENCRYPTION_KEY"].encode()).hexdigest()
).encode()

def hash_value(value: str) -> str:
    """Keyed (HMAC-SHA256) fingerprint for uniqueness checks. A leaked DB alone cannot brute-force
    Aadhaar/PAN values, unlike a plain SHA-256."""
    return hmac.new(_hmac_key, value.encode(), hashlib.sha256).hexdigest()

def mask_last4(value: str) -> str:
    digits = value[-4:] if len(value) >= 4 else value
    return f"•••• •••• {digits}"