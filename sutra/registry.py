"""SUTRA v0.2 — Agent Registry

Maps agent identifiers (e.g. "seller@store") to network addresses (URLs).
Supports both static configuration and runtime registration.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field


@dataclass
class AgentEndpoint:
    agent_id: str
    url: str  # e.g. "http://localhost:8001"
    capabilities: list[str] = field(default_factory=list)

    def sutra_url(self) -> str:
        """Full URL for the /sutra endpoint."""
        return f"{self.url.rstrip('/')}/sutra"


class AgentRegistry:
    """Thread-safe registry of known agent endpoints.

    Usage:
        registry = AgentRegistry()
        registry.register("seller@store", "http://localhost:8001")
        endpoint = registry.lookup("seller@store")
    """

    def __init__(self):
        self._agents: dict[str, AgentEndpoint] = {}
        self._lock = threading.Lock()

    def register(self, agent_id: str, url: str, capabilities: list[str] | None = None):
        """Register an agent's network endpoint."""
        with self._lock:
            self._agents[agent_id] = AgentEndpoint(
                agent_id=agent_id,
                url=url,
                capabilities=capabilities or [],
            )

    def unregister(self, agent_id: str):
        """Remove an agent from the registry."""
        with self._lock:
            self._agents.pop(agent_id, None)

    def lookup(self, agent_id: str) -> AgentEndpoint | None:
        """Find an agent's endpoint by ID."""
        with self._lock:
            return self._agents.get(agent_id)

    def list_agents(self) -> list[AgentEndpoint]:
        """Return all registered agents."""
        with self._lock:
            return list(self._agents.values())

    def to_dict(self) -> dict:
        """Serialize registry to dict (for /registry endpoint)."""
        with self._lock:
            return {
                aid: {"url": ep.url, "capabilities": ep.capabilities}
                for aid, ep in self._agents.items()
            }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentRegistry":
        """Load registry from a dict."""
        reg = cls()
        for agent_id, info in data.items():
            reg.register(agent_id, info["url"], info.get("capabilities", []))
        return reg

    @classmethod
    def from_file(cls, path: str) -> "AgentRegistry":
        """Load registry from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def save(self, path: str):
        """Save registry to a JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
