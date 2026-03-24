"""SUTRA v0.6 — Security Hardening

Provides replay protection, message encryption, bearer-token auth,
message ordering, and nonce tracking for the SUTRA protocol.

Addresses:
  - Replay attacks:  Nonce + seen-set deduplication
  - Eavesdropping:   AES-256-GCM payload encryption with shared secrets
  - Unauthorized:    Bearer token middleware for HTTP endpoints
  - Out-of-order:    Per-pair sequence counters with gap rejection
  - Expiry:          TTL-based message expiration

All features are opt-in and composable — they layer on top of the
existing SUTRA message envelope.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import threading
from dataclasses import dataclass, field
from typing import Any


# ════════════════════════════════════════════════════════
#  NONCE / REPLAY PROTECTION
# ════════════════════════════════════════════════════════

class ReplayGuard:
    """Detects replayed messages via nonce tracking.

    Each message carries a unique nonce (128-bit hex). The guard
    keeps a bounded set of recently seen nonces and rejects duplicates.

    Also enforces TTL — messages older than `max_age_s` are rejected
    even if they have fresh nonces (prevents delayed replays).
    """

    def __init__(self, max_seen: int = 10_000, max_age_s: float = 300.0):
        self.max_seen = max_seen
        self.max_age_s = max_age_s
        self._seen: dict[str, float] = {}  # nonce → timestamp
        self._lock = threading.Lock()

    @staticmethod
    def generate_nonce() -> str:
        """Generate a cryptographically random 128-bit nonce."""
        return secrets.token_hex(16)

    def check(self, nonce: str, timestamp: float | None = None) -> tuple[bool, str]:
        """Check if a message nonce is valid.

        Returns (is_valid, reason).
        """
        now = time.time()
        ts = timestamp or now

        # TTL check
        age = now - ts
        if age > self.max_age_s:
            return False, f"Message expired: {age:.0f}s old (max {self.max_age_s:.0f}s)"
        if age < -30:  # allow 30s clock skew
            return False, f"Message from the future: {-age:.0f}s ahead"

        with self._lock:
            # Replay check
            if nonce in self._seen:
                return False, f"Replay detected: nonce {nonce[:16]}... already seen"

            # Record
            self._seen[nonce] = now

            # Time-based eviction: remove expired nonces first
            if len(self._seen) > self.max_seen:
                expired_nonces = [
                    n for n, t in self._seen.items()
                    if now - t > self.max_age_s
                ]
                for n in expired_nonces:
                    del self._seen[n]
                # If still full after time eviction, evict oldest
                if len(self._seen) > self.max_seen:
                    oldest = min(self._seen, key=self._seen.get)
                    del self._seen[oldest]

        return True, "ok"

    def mark_seen(self, nonce: str):
        """Manually mark a nonce as seen."""
        with self._lock:
            self._seen[nonce] = time.time()

    @property
    def seen_count(self) -> int:
        return len(self._seen)


# ════════════════════════════════════════════════════════
#  MESSAGE ORDERING
# ════════════════════════════════════════════════════════

class SequenceTracker:
    """Enforces message ordering between agent pairs.

    Each (sender, receiver) pair gets an independent monotonic counter.
    Out-of-order or duplicate sequence numbers are rejected.

    Features:
      - Per-pair counters (no global bottleneck)
      - Gap detection (missing messages)
      - Optional gap tolerance for unreliable transports
    """

    def __init__(self, gap_tolerance: int = 0):
        self._counters: dict[str, int] = {}  # "from→to" → next expected seq
        self._outgoing: dict[str, int] = {}  # "from→to" → next seq to send
        self._lock = threading.Lock()
        self.gap_tolerance = gap_tolerance

    def _pair_key(self, from_id: str, to_id: str) -> str:
        return f"{from_id}→{to_id}"

    def next_seq(self, from_id: str, to_id: str) -> int:
        """Get the next sequence number for an outgoing message."""
        key = self._pair_key(from_id, to_id)
        with self._lock:
            seq = self._outgoing.get(key, 0)
            self._outgoing[key] = seq + 1
            return seq

    def check(self, from_id: str, to_id: str, seq: int) -> tuple[bool, str]:
        """Validate an incoming message's sequence number.

        Returns (is_valid, reason).
        """
        key = self._pair_key(from_id, to_id)
        with self._lock:
            expected = self._counters.get(key, 0)

            if seq < expected:
                return False, f"Duplicate/old: seq={seq}, expected≥{expected}"

            gap = seq - expected
            if gap > self.gap_tolerance:
                return False, f"Gap detected: expected {expected}, got {seq} (gap={gap})"

            # Accept and advance
            self._counters[key] = seq + 1
            return True, "ok"

    def reset(self, from_id: str, to_id: str):
        """Reset counters for a pair."""
        key = self._pair_key(from_id, to_id)
        with self._lock:
            self._counters.pop(key, None)
            self._outgoing.pop(key, None)


# ════════════════════════════════════════════════════════
#  ENCRYPTION (AES-256-GCM)
# ════════════════════════════════════════════════════════

class MessageEncryptor:
    """AES-256-GCM encryption for SUTRA message payloads.

    Uses pre-shared symmetric keys between agent pairs.
    No key exchange protocol — keys must be distributed out-of-band.

    Security properties:
      - Confidentiality: AES-256-GCM encryption
      - Integrity: GCM authentication tag
      - IV: Random 96-bit nonce per message (never reused)
    """

    def __init__(self):
        self._keys: dict[str, bytes] = {}  # pair_key → 32-byte secret

    @staticmethod
    def generate_shared_secret() -> str:
        """Generate a 256-bit shared secret (hex-encoded)."""
        return secrets.token_hex(32)

    def register_pair(self, agent_a: str, agent_b: str, shared_secret_hex: str):
        """Register a shared secret for a pair of agents."""
        key = hashlib.sha256(shared_secret_hex.encode()).digest()
        # Store both directions
        self._keys[f"{agent_a}↔{agent_b}"] = key
        self._keys[f"{agent_b}↔{agent_a}"] = key

    def _get_key(self, from_id: str, to_id: str) -> bytes | None:
        return self._keys.get(f"{from_id}↔{to_id}")

    def encrypt(self, from_id: str, to_id: str, plaintext: str) -> dict | None:
        """Encrypt a SUTRA message body.

        Returns dict with {ciphertext, iv, tag} (all hex) or None if no key.
        """
        key = self._get_key(from_id, to_id)
        if key is None:
            return None

        iv = os.urandom(12)  # 96-bit nonce
        plaintext_bytes = plaintext.encode("utf-8")

        try:
            # Try AES-GCM via cryptography lib
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            cipher = AESGCM(key)
            ciphertext = cipher.encrypt(iv, plaintext_bytes, None)
            return {
                "ciphertext": ciphertext[:-16].hex(),
                "tag": ciphertext[-16:].hex(),
                "iv": iv.hex(),
                "algorithm": "AES-256-GCM",
            }
        except ImportError:
            # Fallback: XOR with HMAC-SHA256 keystream (basic, not production-grade)
            keystream = b""
            for i in range((len(plaintext_bytes) + 31) // 32):
                keystream += hmac.new(key, iv + i.to_bytes(4, "big"), hashlib.sha256).digest()
            keystream = keystream[:len(plaintext_bytes)]
            ct = bytes(a ^ b for a, b in zip(plaintext_bytes, keystream))
            tag = hmac.new(key, iv + ct, hashlib.sha256).hexdigest()[:32]
            return {
                "ciphertext": ct.hex(),
                "tag": tag,
                "iv": iv.hex(),
                "algorithm": "HMAC-XOR-SHA256",
            }

    def decrypt(self, from_id: str, to_id: str, encrypted: dict) -> str | None:
        """Decrypt a SUTRA message body.

        Returns plaintext string or None on failure.
        """
        key = self._get_key(from_id, to_id)
        if key is None:
            return None

        iv = bytes.fromhex(encrypted["iv"])
        algo = encrypted.get("algorithm", "")

        if algo == "AES-256-GCM":
            try:
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                ct = bytes.fromhex(encrypted["ciphertext"])
                tag = bytes.fromhex(encrypted["tag"])
                cipher = AESGCM(key)
                plaintext = cipher.decrypt(iv, ct + tag, None)
                return plaintext.decode("utf-8")
            except Exception:
                return None
        elif algo == "HMAC-XOR-SHA256":
            ct = bytes.fromhex(encrypted["ciphertext"])
            expected_tag = hmac.new(key, iv + ct, hashlib.sha256).hexdigest()[:32]
            if not hmac.compare_digest(encrypted["tag"], expected_tag):
                return None
            keystream = b""
            for i in range((len(ct) + 31) // 32):
                keystream += hmac.new(key, iv + i.to_bytes(4, "big"), hashlib.sha256).digest()
            keystream = keystream[:len(ct)]
            plaintext = bytes(a ^ b for a, b in zip(ct, keystream))
            return plaintext.decode("utf-8")
        return None


# ════════════════════════════════════════════════════════
#  BEARER TOKEN AUTH
# ════════════════════════════════════════════════════════

class TokenAuth:
    """Bearer-token authentication for SUTRA HTTP endpoints.

    Simple but effective: each agent gets a long-lived token.
    Requests must include `Authorization: Bearer <token>` header.
    Tokens are SHA-256 hashed before storage (no plaintext on disk).
    """

    def __init__(self):
        self._tokens: dict[str, str] = {}  # agent_id → token_hash

    @staticmethod
    def generate_token() -> str:
        """Generate a cryptographically random bearer token."""
        return secrets.token_urlsafe(48)

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def register(self, agent_id: str, token: str):
        """Register a bearer token for an agent."""
        self._tokens[agent_id] = self._hash(token)

    def verify(self, agent_id: str, token: str) -> bool:
        """Verify a bearer token matches the registered agent."""
        expected = self._tokens.get(agent_id)
        if expected is None:
            return False
        return hmac.compare_digest(expected, self._hash(token))

    def verify_header(self, auth_header: str | None) -> tuple[bool, str]:
        """Verify an HTTP Authorization header.

        Expected format: "Bearer <token>"
        Returns (is_valid, agent_id_or_error).
        """
        if not auth_header:
            return False, "Missing Authorization header"
        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0] != "Bearer":
            return False, "Invalid format (expected: Bearer <token>)"

        token = parts[1]
        token_hash = self._hash(token)
        for agent_id, stored_hash in self._tokens.items():
            if hmac.compare_digest(stored_hash, token_hash):
                return True, agent_id
        return False, "Invalid token"

    @property
    def registered_agents(self) -> list[str]:
        return list(self._tokens.keys())


# ════════════════════════════════════════════════════════
#  RATE LIMITER
# ════════════════════════════════════════════════════════

class RateLimiter:
    """Token-bucket rate limiter for per-agent request throttling.

    Each agent gets a bucket with `max_tokens` capacity, refilling at
    `refill_rate` tokens per second. Each request consumes one token.
    """

    def __init__(self, max_tokens: int = 60, refill_rate: float = 10.0):
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self._buckets: dict[str, tuple[float, float]] = {}  # agent_id → (tokens, last_refill)
        self._lock = threading.Lock()

    def check(self, agent_id: str) -> tuple[bool, str]:
        """Check if a request from agent_id is allowed.

        Returns (allowed, reason).
        """
        now = time.time()
        with self._lock:
            tokens, last = self._buckets.get(agent_id, (float(self.max_tokens), now))
            # Refill tokens based on elapsed time
            elapsed = now - last
            tokens = min(self.max_tokens, tokens + elapsed * self.refill_rate)
            if tokens >= 1.0:
                self._buckets[agent_id] = (tokens - 1.0, now)
                return True, "ok"
            else:
                self._buckets[agent_id] = (tokens, now)
                return False, f"Rate limited: {agent_id} (retry after {(1.0 - tokens) / self.refill_rate:.1f}s)"

    def reset(self, agent_id: str):
        """Reset rate limit for an agent."""
        with self._lock:
            self._buckets.pop(agent_id, None)


# ════════════════════════════════════════════════════════
#  INPUT SANITIZER
# ════════════════════════════════════════════════════════

class InputValidator:
    """Validates and sanitizes SUTRA message inputs.

    Prevents:
      - Oversized messages (DoS via payload size)
      - Control character injection
      - Null byte injection
    """

    def __init__(
        self,
        max_body_bytes: int = 65536,  # 64KB max SUTRA source
        max_agent_id_len: int = 256,
    ):
        self.max_body_bytes = max_body_bytes
        self.max_agent_id_len = max_agent_id_len

    def validate_body(self, body: str) -> tuple[bool, str]:
        """Validate a SUTRA message body."""
        if not body or not body.strip():
            return False, "Empty body"
        body_bytes = len(body.encode("utf-8"))
        if body_bytes > self.max_body_bytes:
            return False, f"Body too large: {body_bytes} bytes (max {self.max_body_bytes})"
        # Check for null bytes (injection vector)
        if "\x00" in body:
            return False, "Null bytes not allowed in body"
        return True, "ok"

    def validate_agent_id(self, agent_id: str) -> tuple[bool, str]:
        """Validate an agent identifier."""
        if not agent_id:
            return False, "Empty agent ID"
        if len(agent_id) > self.max_agent_id_len:
            return False, f"Agent ID too long: {len(agent_id)} (max {self.max_agent_id_len})"
        # Only allow printable ASCII + common symbols
        if not all(32 <= ord(c) <= 126 for c in agent_id):
            return False, "Agent ID contains invalid characters"
        # Prevent path traversal
        if ".." in agent_id or "/" in agent_id or "\\" in agent_id:
            return False, "Agent ID contains path traversal characters"
        return True, "ok"
