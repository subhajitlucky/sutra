"""SUTRA v0.4 — Message Envelope

A SutraMessage wraps SUTRA source with routing metadata —
sender, recipient, timestamps, and conversation threading.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


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
    """

    from_agent: str
    to_agent: str | None  # None = broadcast
    body: str  # SUTRA source code
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    responses: list[str] = field(default_factory=list)
    reply_body: str | None = None
    timestamp: float = field(default_factory=time.time)
    reply_to: str | None = None

    @property
    def is_broadcast(self) -> bool:
        return self.to_agent is None

    @property
    def is_reply(self) -> bool:
        return self.reply_to is not None

    def __str__(self):
        target = self.to_agent or "* (all)"
        lines = self.body.strip().split("\n")
        first = lines[0].strip()
        preview = first[:60] + ("..." if len(first) > 60 else "")
        reply = " ↩" if self.is_reply else ""
        return f"[{self.from_agent} → {target}]{reply} {preview}"
