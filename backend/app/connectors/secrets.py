"""Encryption of connector passwords and tokens (Fernet). The key comes from CONNECTOR_SECRET_KEY, or is generated once
into data/connector.key. Keep that key private: whoever has it and the database can read the stored passwords."""
from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import DATA_DIR, settings


def _key() -> bytes:
    if settings.connector_secret_key.strip():
        return settings.connector_secret_key.strip().encode()
    path = DATA_DIR / "connector.key"
    if path.exists():
        return path.read_bytes().strip()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def encrypt(secrets: dict[str, str]) -> str | None:
    clean = {k: v for k, v in (secrets or {}).items() if v not in (None, "")}
    return Fernet(_key()).encrypt(json.dumps(clean).encode()).decode() if clean else None


def decrypt(token: str | None) -> dict[str, str]:
    if not token:
        return {}
    try:
        return json.loads(Fernet(_key()).decrypt(token.encode()))
    except InvalidToken as e:
        raise ValueError("The stored password cannot be decrypted. The encryption key has changed; enter the password again.") from e
