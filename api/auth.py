# =============================================================
# auth.py  —  NEW FILE  |  Place in your swapskill/ folder
# =============================================================
# Handles:
#   1. Password hashing with bcrypt  (never store plain text)
#   2. JWT token creation & verification  (proof of login)
# =============================================================

import os
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY         = os.getenv("SECRET_KEY", "skillswap-dev-secret-CHANGE-IN-PROD")
ALGORITHM          = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7   # token stays valid for 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain_password: str):
    # 1. Convert the long password into a fixed-length 64-character hex string
    prepared_password = hashlib.sha256(plain_password.encode()).hexdigest()
    
    # 2. Now bcrypt handles the 64-character string easily (64 < 72)
    return pwd_context.hash(prepared_password)

def verify_password(plain: str, hashed: str) -> bool:
    """Returns True if plain password matches the stored bcrypt hash."""
    # We MUST hash the plain password with SHA-256 first 
    # because that's how it was stored in hash_password()
    prepared_password = hashlib.sha256(plain.encode()).hexdigest()
    
    return pwd_context.verify(prepared_password, hashed)


def create_access_token(user_id: int, username: str) -> str:
    """
    Builds a signed JWT:  { sub: "1", username: "alice", exp: <timestamp> }
    The browser stores this string and sends it in every request header.
    """
    expire  = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "username": username, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """
    Validates signature + expiry. Returns payload dict or None on failure.
    """
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None