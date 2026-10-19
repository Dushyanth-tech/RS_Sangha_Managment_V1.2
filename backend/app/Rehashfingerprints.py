"""Run ONCE after deploying the new crypto.py:  python rehash_fingerprints.py
Recomputes id_proof_number_hash / pan_number_hash with the keyed HMAC, and masks old plaintext Aadhaar."""
from app.dbconnection import SessionLocal
from app.authModal import User
from app.crypto import decrypt_value, hash_value, mask_last4
from sqlalchemy import text

db = SessionLocal()
try:
    n = 0
    for u in db.query(User).all():
        if u.id_proof_number_enc:
            u.id_proof_number_hash = hash_value(decrypt_value(u.id_proof_number_enc)); n += 1
        if u.pan_number_enc:
            u.pan_number_hash = hash_value(decrypt_value(u.pan_number_enc)); n += 1
    # old rows copied the full Aadhaar in clear text -> mask them
    db.execute(text(
        "UPDATE subadmin_requests SET aadhar_number = '•••• •••• ' || RIGHT(aadhar_number, 4) "
        "WHERE aadhar_number ~ '^[0-9A-Za-z]{8,}$'"
    ))
    db.commit()
    print(f"Re-hashed {n} values and masked old Aadhaar rows.")
finally:
    db.close()