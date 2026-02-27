"""SUTRA v0.3 — Key Store

Persistent storage for agent signing keys.
Keys are stored as JSON files in ~/.sutra/keys/ by default.

File format:
    ~/.sutra/keys/<agent_id>.key.json
    {
        "agent_id": "seller@store",
        "algorithm": "ed25519",
        "private_key": "<hex>",
        "public_key": "<hex>",
        "created_at": 1234567890.0
    }
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .crypto import SutraKeyPair, generate_keypair


DEFAULT_KEY_DIR = os.path.expanduser("~/.sutra/keys")


class KeyStore:
    """Manages persistent storage of agent key pairs.

    Usage:
        store = KeyStore()
        keypair = store.get_or_create("seller@store")
        print(keypair.fingerprint)
    """

    def __init__(self, key_dir: str = DEFAULT_KEY_DIR):
        self.key_dir = key_dir
        self._cache: dict[str, SutraKeyPair] = {}

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

        Returns None if no key exists for the agent.
        """
        if agent_id in self._cache:
            return self._cache[agent_id]

        path = self._key_path(agent_id)
        if not os.path.exists(path):
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        keypair = SutraKeyPair(
            agent_id=data["agent_id"],
            private_key_bytes=bytes.fromhex(data["private_key"]),
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
        """Save key pair to disk."""
        self._ensure_dir()
        path = self._key_path(keypair.agent_id)
        data = {
            "agent_id": keypair.agent_id,
            "algorithm": keypair.algorithm,
            "private_key": keypair.private_key_bytes.hex(),
            "public_key": keypair.public_key_bytes.hex(),
            "created_at": keypair.created_at,
        }
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
