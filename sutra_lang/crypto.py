"""SUTRA v0.3 — Cryptographic Signing & Verification

Provides Ed25519 digital signatures for COMMIT and OFFER statements,
making agent commitments tamper-proof and verifiable.

Architecture:
    ┌─────────────┐     sign()     ┌──────────────┐
    │ Agent        │───────────────►│ Signed       │
    │ Private Key  │               │ Commitment   │
    └─────────────┘               └──────┬───────┘
                                         │
    ┌─────────────┐    verify()    ┌─────▼────────┐
    │ Agent        │◄──────────────│ Signature +  │
    │ Public Key   │               │ Content Hash │
    └─────────────┘               └──────────────┘

Uses Ed25519 (via `cryptography` library) for production.
Falls back to HMAC-SHA256 if `cryptography` is not installed.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

# ── Backend detection ───────────────────────────────────

_BACKEND = "none"

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives import serialization
    from cryptography.exceptions import InvalidSignature
    _BACKEND = "ed25519"
except ImportError:
    pass

if _BACKEND == "none":
    import hmac as _hmac
    import secrets as _secrets
    _BACKEND = "hmac"


# ── Content hashing ────────────────────────────────────

def content_hash(content: dict[str, Any]) -> str:
    """Deterministic SHA-256 hash of content dict.

    Produces the same hash regardless of key order.
    """
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Key types ───────────────────────────────────────────

@dataclass
class SutraKeyPair:
    """An agent's signing key pair."""
    agent_id: str
    private_key_bytes: bytes  # Raw private key
    public_key_bytes: bytes   # Raw public key
    algorithm: str            # "ed25519" or "hmac-sha256"
    created_at: float

    @property
    def public_key_hex(self) -> str:
        return self.public_key_bytes.hex()

    @property
    def fingerprint(self) -> str:
        """Short fingerprint for display (first 16 chars of pubkey hash)."""
        h = hashlib.sha256(self.public_key_bytes).hexdigest()
        return h[:16]


@dataclass
class SutraSignature:
    """A cryptographic signature over SUTRA content."""
    signer: str               # Agent ID
    content_hash: str          # SHA-256 of signed content
    signature_hex: str         # Hex-encoded signature bytes
    algorithm: str             # "ed25519" or "hmac-sha256"
    public_key_hex: str        # Signer's public key
    timestamp: float           # When the signature was created

    def to_dict(self) -> dict:
        return {
            "signer": self.signer,
            "content_hash": self.content_hash,
            "signature": self.signature_hex,
            "algorithm": self.algorithm,
            "public_key": self.public_key_hex,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SutraSignature":
        return cls(
            signer=data["signer"],
            content_hash=data["content_hash"],
            signature_hex=data["signature"],
            algorithm=data["algorithm"],
            public_key_hex=data["public_key"],
            timestamp=data["timestamp"],
        )

    def __str__(self):
        short_sig = self.signature_hex[:16] + "..."
        return f"Sig({self.signer}, {self.algorithm}, {short_sig})"


# ── Key Generation ──────────────────────────────────────

def generate_keypair(agent_id: str) -> SutraKeyPair:
    """Generate a new signing key pair for an agent."""
    if _BACKEND == "ed25519":
        return _generate_ed25519(agent_id)
    else:
        return _generate_hmac(agent_id)


def _generate_ed25519(agent_id: str) -> SutraKeyPair:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return SutraKeyPair(
        agent_id=agent_id,
        private_key_bytes=private_bytes,
        public_key_bytes=public_bytes,
        algorithm="ed25519",
        created_at=time.time(),
    )


def _generate_hmac(agent_id: str) -> SutraKeyPair:
    """Fallback: generate a shared secret for HMAC-SHA256."""
    secret = _secrets.token_bytes(32)
    return SutraKeyPair(
        agent_id=agent_id,
        private_key_bytes=secret,
        public_key_bytes=secret,  # HMAC: same key for sign & verify
        algorithm="hmac-sha256",
        created_at=time.time(),
    )


# ── Signing ─────────────────────────────────────────────

def sign(keypair: SutraKeyPair, content: dict[str, Any]) -> SutraSignature:
    """Sign content with an agent's private key.

    Args:
        keypair: The signer's key pair
        content: Dict to sign (will be canonicalized + hashed)

    Returns:
        SutraSignature containing the signature
    """
    c_hash = content_hash(content)
    message = c_hash.encode("utf-8")

    if keypair.algorithm == "ed25519":
        sig_bytes = _sign_ed25519(keypair.private_key_bytes, message)
    else:
        sig_bytes = _sign_hmac(keypair.private_key_bytes, message)

    return SutraSignature(
        signer=keypair.agent_id,
        content_hash=c_hash,
        signature_hex=sig_bytes.hex(),
        algorithm=keypair.algorithm,
        public_key_hex=keypair.public_key_hex,
        timestamp=time.time(),
    )


def _sign_ed25519(private_key_bytes: bytes, message: bytes) -> bytes:
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    return private_key.sign(message)


def _sign_hmac(secret: bytes, message: bytes) -> bytes:
    return _hmac.new(secret, message, hashlib.sha256).digest()


# ── Verification ────────────────────────────────────────

def verify(signature: SutraSignature, content: dict[str, Any]) -> bool:
    """Verify a signature against content and the signer's public key.

    Args:
        signature: The signature to verify
        content: The original content dict

    Returns:
        True if signature is valid, False otherwise
    """
    # Re-compute content hash
    c_hash = content_hash(content)
    if c_hash != signature.content_hash:
        return False

    message = c_hash.encode("utf-8")
    sig_bytes = bytes.fromhex(signature.signature_hex)
    pub_bytes = bytes.fromhex(signature.public_key_hex)

    if signature.algorithm == "ed25519":
        return _verify_ed25519(pub_bytes, message, sig_bytes)
    elif signature.algorithm == "hmac-sha256":
        return _verify_hmac(pub_bytes, message, sig_bytes)
    else:
        return False


def _verify_ed25519(public_key_bytes: bytes, message: bytes, sig_bytes: bytes) -> bool:
    try:
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(sig_bytes, message)
        return True
    except (InvalidSignature, Exception):
        return False


def _verify_hmac(secret: bytes, message: bytes, sig_bytes: bytes) -> bool:
    expected = _hmac.new(secret, message, hashlib.sha256).digest()
    return _hmac.compare_digest(expected, sig_bytes)


# ── Utilities ───────────────────────────────────────────

def get_backend() -> str:
    """Return the active crypto backend name."""
    return _BACKEND


def commitment_content(predicate: str, args: dict, agent_id: str,
                       deadline: str | None = None) -> dict:
    """Build a canonical content dict for a COMMIT statement."""
    content = {
        "type": "COMMIT",
        "agent": agent_id,
        "predicate": predicate,
        "args": args,
    }
    if deadline:
        content["deadline"] = deadline
    return content


def offer_content(offer_id: str, from_agent: str, to_agent: str,
                  fields: dict) -> dict:
    """Build a canonical content dict for an OFFER statement."""
    return {
        "type": "OFFER",
        "offer_id": offer_id,
        "from": from_agent,
        "to": to_agent,
        "fields": fields,
    }
