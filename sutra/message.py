"""SUTRA v0.6 — Message Envelope

A SutraMessage wraps SUTRA source with routing metadata —
sender, recipient, timestamps, conversation threading,
and v0.6 security fields (nonce, sequence, encryption).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


def _format_sutra_value(v) -> str:
    """Format a Python value as valid SUTRA source text."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    if isinstance(v, (int, float)):
        return str(v)
    if v is None:
        return "null"
    if isinstance(v, dict):
        entries = ", ".join(
            f"{k}: {_format_sutra_value(val)}" for k, val in v.items()
        )
        return f"{{{entries}}}"
    if isinstance(v, list):
        entries = ", ".join(_format_sutra_value(i) for i in v)
        return f"[{entries}]"
    return f'"{v}"'


@dataclass
class SutraMessage:
    """An envelope for agent-to-agent SUTRA communication.

    Fields:
        from_agent:  Sender agent ID
        to_agent:    Recipient agent ID (None = broadcast)
        body:        Raw SUTRA source code
        id:          Unique message identifier
        responses:   Execution output lines from the interpreter
        reply_body:  Auto-generated SUTRA response (if any)
        timestamp:   Unix timestamp
        reply_to:    ID of the message this replies to (threading)
        nonce:       v0.6 — Unique nonce for replay protection
        sequence:    v0.6 — Monotonic sequence number for ordering
        encrypted:   v0.6 — Encrypted payload dict (replaces body if set)
        ttl:         v0.6 — Time-to-live in seconds (0 = no expiry)
    """

    from_agent: str
    to_agent: str | None  # None = broadcast
    body: str  # SUTRA source code
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    responses: list[str] = field(default_factory=list)
    reply_body: str | None = None
    timestamp: float = field(default_factory=time.time)
    reply_to: str | None = None
    # v0.6 security fields
    nonce: str | None = None
    sequence: int | None = None
    encrypted: dict[str, Any] | None = None
    ttl: float = 0  # 0 = no expiry

    @property
    def is_broadcast(self) -> bool:
        return self.to_agent is None

    @property
    def is_reply(self) -> bool:
        return self.reply_to is not None

    @property
    def is_encrypted(self) -> bool:
        return self.encrypted is not None

    @property
    def is_expired(self) -> bool:
        if self.ttl <= 0:
            return False
        return (time.time() - self.timestamp) > self.ttl

    def to_wire(self) -> dict:
        """Serialize to wire format (for HTTP transport)."""
        d: dict[str, Any] = {
            "id": self.id,
            "from": self.from_agent,
            "to": self.to_agent,
            "timestamp": self.timestamp,
        }
        if self.encrypted:
            d["encrypted"] = self.encrypted
        else:
            d["body"] = self.body
        if self.nonce:
            d["nonce"] = self.nonce
        if self.sequence is not None:
            d["seq"] = self.sequence
        if self.reply_to:
            d["reply_to"] = self.reply_to
        if self.ttl > 0:
            d["ttl"] = self.ttl
        return d

    @classmethod
    def from_wire(cls, data: dict) -> "SutraMessage":
        """Deserialize from wire format."""
        return cls(
            from_agent=data.get("from", "unknown"),
            to_agent=data.get("to"),
            body=data.get("body", ""),
            id=data.get("id", uuid.uuid4().hex[:12]),
            timestamp=data.get("timestamp", time.time()),
            reply_to=data.get("reply_to"),
            nonce=data.get("nonce"),
            sequence=data.get("seq"),
            encrypted=data.get("encrypted"),
            ttl=data.get("ttl", 0),
        )

    def __str__(self):
        target = self.to_agent or "* (all)"
        lines = self.body.strip().split("\n")
        first = lines[0].strip()
        preview = first[:60] + ("..." if len(first) > 60 else "")
        reply = " ↩" if self.is_reply else ""
        return f"[{self.from_agent} → {target}]{reply} {preview}"
