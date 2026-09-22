"""Fernet-based encryption for secrets at rest (MCP server API keys/tokens).

Key lives on the host filesystem, outside the database and outside git,
at settings.secret_key_file (default ~/.muster/secret.key, 0600).
"""
from __future__ import annotations

from cryptography.fernet import Fernet

from app.config import settings


def _load_or_create_key() -> bytes:
    settings.ensure_dirs()
    key_file = settings.secret_key_file
    if key_file.exists():
        return key_file.read_bytes()
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet.encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes) -> str:
    return _fernet.decrypt(ciphertext).decode("utf-8")
