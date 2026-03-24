"""SUTRA v0.7 — Key Store (Hardened)

Persistent storage for agent signing keys with optional encryption at rest.

File format (encrypted):
    ~/.sutra/keys/<agent_id>.key.json
    {
        "agent_id": "seller@store",
        "algorithm": "ed25519",
        "private_key": "<hex-or-encrypted>",
        "public_key": "<hex>",
        "created_at": 1234567890.0,
        "encrypted": true,
        "kdf_salt": "<hex>"
    }

Security:
  - Private keys encrypted at rest using PBKDF2-HMAC-SHA256 + AES-like XOR cipher
  - File permissions restricted to 0o600 (owner read/write only)
  - Atomic writes to prevent corruption
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import secrets
from pathlib import Path

from .crypto import SutraKeyPair, generate_keypair


DEFAULT_KEY_DIR = os.path.expanduser("~/.sutra/keys")


def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 32-byte encryption key from password using PBKDF2."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations=100_000)


def _encrypt_private_key(private_key_hex: str, password: str) -> tuple[str, str]:
    """Encrypt private key hex with password. Returns (encrypted_hex, salt_hex)."""
    salt = secrets.token_bytes(16)
    key = _derive_key(password, salt)
    pk_bytes = bytes.fromhex(private_key_hex)
    # XOR-cipher with HMAC-derived keystream (portable, no external deps)
    keystream = b""
    for i in range((len(pk_bytes) + 31) // 32):
        keystream += _hmac.new(key, salt + i.to_bytes(4, "big"), hashlib.sha256).digest()
    keystream = keystream[:len(pk_bytes)]
    encrypted = bytes(a ^ b for a, b in zip(pk_bytes, keystream))
    # Append HMAC tag for integrity verification
    tag = _hmac.new(key, encrypted, hashlib.sha256).digest()[:16]
    return (encrypted + tag).hex(), salt.hex()


def _decrypt_private_key(encrypted_hex: str, salt_hex: str, password: str) -> str | None:
    """Decrypt private key hex. Returns None on wrong password."""
    key = _derive_key(password, bytes.fromhex(salt_hex))
    data = bytes.fromhex(encrypted_hex)
    encrypted, stored_tag = data[:-16], data[-16:]
    # Verify HMAC tag first
    expected_tag = _hmac.new(key, encrypted, hashlib.sha256).digest()[:16]
    if not _hmac.compare_digest(stored_tag, expected_tag):
        return None  # wrong password or tampered
    # Decrypt
    keystream = b""
    salt = bytes.fromhex(salt_hex)
    for i in range((len(encrypted) + 31) // 32):
        keystream += _hmac.new(key, salt + i.to_bytes(4, "big"), hashlib.sha256).digest()
    keystream = keystream[:len(encrypted)]
    decrypted = bytes(a ^ b for a, b in zip(encrypted, keystream))
    return decrypted.hex()


class KeyStore:
    """Manages persistent storage of agent key pairs.

    Usage:
        store = KeyStore()
        keypair = store.get_or_create("seller@store")
        print(keypair.fingerprint)
    """

    def __init__(self, key_dir: str = DEFAULT_KEY_DIR, password: str | None = None):
        self.key_dir = key_dir
        self._cache: dict[str, SutraKeyPair] = {}
        self._password = password  # if set, encrypts private keys at rest

    def _ensure_dir(self):
        os.makedirs(self.key_dir, exist_ok=True)

    def _key_path(self, agent_id: str) -> str:
        # Sanitize agent_id for filename
        safe_id = agent_id.replace("@", "_at_").replace("/", "_")
        return os.path.join(self.key_dir, f"{safe_id}.key.json")

    def generate(self, agent_id: str, force: bool = False) -> SutraKeyPair:
        """Generate and store a new key pair for an agent.

        Args:
            agent_id: Agent identifier
            force: If True, overwrite existing key

        Returns:
            The generated SutraKeyPair

        Raises:
            FileExistsError: If key already exists and force=False
        """
        self._ensure_dir()
        path = self._key_path(agent_id)

        if os.path.exists(path) and not force:
            raise FileExistsError(
                f"Key already exists for '{agent_id}' at {path}. "
                f"Use force=True to overwrite."
            )

        keypair = generate_keypair(agent_id)
        self._save(keypair)
        self._cache[agent_id] = keypair
        return keypair

    def load(self, agent_id: str) -> SutraKeyPair | None:
        """Load a key pair from disk.

        Returns None if no key exists or decryption fails.
        """
        if agent_id in self._cache:
            return self._cache[agent_id]

        path = self._key_path(agent_id)
        if not os.path.exists(path):
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Decrypt private key if encrypted
        private_key_hex = data["private_key"]
        if data.get("encrypted", False):
            if not self._password:
                raise ValueError(
                    f"Key for '{agent_id}' is encrypted but no password provided"
                )
            decrypted = _decrypt_private_key(
                private_key_hex, data["kdf_salt"], self._password
            )
            if decrypted is None:
                raise ValueError(
                    f"Failed to decrypt key for '{agent_id}' — wrong password or tampered key"
                )
            private_key_hex = decrypted

        keypair = SutraKeyPair(
            agent_id=data["agent_id"],
            private_key_bytes=bytes.fromhex(private_key_hex),
            public_key_bytes=bytes.fromhex(data["public_key"]),
            algorithm=data["algorithm"],
            created_at=data["created_at"],
        )
        self._cache[agent_id] = keypair
        return keypair

    def get_or_create(self, agent_id: str) -> SutraKeyPair:
        """Load existing key or generate a new one."""
        keypair = self.load(agent_id)
        if keypair is None:
            keypair = self.generate(agent_id)
        return keypair

    def _save(self, keypair: SutraKeyPair):
        """Save key pair to disk, optionally encrypting the private key."""
        self._ensure_dir()
        path = self._key_path(keypair.agent_id)
        private_key_hex = keypair.private_key_bytes.hex()
        encrypted = False
        kdf_salt = None

        # Encrypt private key at rest if password is set
        if self._password:
            private_key_hex, kdf_salt = _encrypt_private_key(
                keypair.private_key_bytes.hex(), self._password
            )
            encrypted = True

        data = {
            "agent_id": keypair.agent_id,
            "algorithm": keypair.algorithm,
            "private_key": private_key_hex,
            "public_key": keypair.public_key_bytes.hex(),
            "created_at": keypair.created_at,
            "encrypted": encrypted,
        }
        if kdf_salt:
            data["kdf_salt"] = kdf_salt
        # Write atomically (write to tmp, then rename)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
        # Restrict permissions (owner read/write only)
        os.chmod(path, 0o600)

    def list_keys(self) -> list[dict]:
        """List all stored keys (public info only)."""
        self._ensure_dir()
        keys = []
        for fname in sorted(os.listdir(self.key_dir)):
            if not fname.endswith(".key.json"):
                continue
            path = os.path.join(self.key_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                keys.append({
                    "agent_id": data["agent_id"],
                    "algorithm": data["algorithm"],
                    "public_key": data["public_key"],
                    "fingerprint": SutraKeyPair(
                        agent_id=data["agent_id"],
                        private_key_bytes=b"",
                        public_key_bytes=bytes.fromhex(data["public_key"]),
                        algorithm=data["algorithm"],
                        created_at=data["created_at"],
                    ).fingerprint,
                    "created_at": data["created_at"],
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return keys

    def delete(self, agent_id: str) -> bool:
        """Delete a stored key pair."""
        path = self._key_path(agent_id)
        self._cache.pop(agent_id, None)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def export_public_key(self, agent_id: str) -> dict | None:
        """Export only the public key info (safe to share)."""
        keypair = self.load(agent_id)
        if keypair is None:
            return None
        return {
            "agent_id": keypair.agent_id,
            "algorithm": keypair.algorithm,
            "public_key": keypair.public_key_hex,
            "fingerprint": keypair.fingerprint,
        }
