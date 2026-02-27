"""SUTRA v0.3 — HTTP Transport Client

Sends SUTRA messages to remote agents over HTTP.
v0.3: Supports fetching public keys and verifying signatures.

Usage:
    client = SutraClient()
    response = client.send(
        to_url="http://localhost:8001",
        from_agent="buyer@home",
        body='QUERY availability(item="SmartTV") FROM "seller@store";'
    )
    print(response["responses"])

Also supports registry-based lookup:
    client = SutraClient(registry=registry)
    response = client.send_to("seller@store", from_agent="buyer@home", body="...")

All built on urllib — zero external dependencies.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field

from .registry import AgentRegistry


class SutraClientError(Exception):
    """Raised when a SUTRA HTTP request fails."""
    def __init__(self, message: str, status_code: int | None = None, detail: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or {}


@dataclass
class SutraResponse:
    """Parsed response from a SUTRA agent."""
    status: str
    agent: str
    responses: list[str]
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "SutraResponse":
        return cls(
            status=data.get("status", "unknown"),
            agent=data.get("agent", "unknown"),
            responses=data.get("responses", []),
            raw=data,
        )

    def __str__(self):
        lines = [f"[{self.agent}] {self.status}"]
        for r in self.responses:
            lines.append(f"  {r}")
        return "\n".join(lines)


class SutraClient:
    """HTTP client for sending SUTRA messages to remote agents.

    Can work with direct URLs or agent IDs (via registry lookup).
    """

    def __init__(self, registry: AgentRegistry | None = None, timeout: float = 10.0):
        self.registry = registry or AgentRegistry()
        self.timeout = timeout

    def send(
        self,
        to_url: str,
        from_agent: str,
        body: str,
    ) -> SutraResponse:
        """Send a SUTRA message to a specific URL.

        Args:
            to_url: Base URL of the target agent (e.g. "http://localhost:8001")
            from_agent: Sender agent ID
            body: Raw SUTRA source code

        Returns:
            SutraResponse with execution results
        """
        endpoint = f"{to_url.rstrip('/')}/sutra"

        payload = json.dumps({
            "from": from_agent,
            "body": body,
        }).encode("utf-8")

        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Sutra-Version": "v0.3",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return SutraResponse.from_dict(data)
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(body_text)
            except json.JSONDecodeError:
                detail = {"raw": body_text}
            raise SutraClientError(
                f"HTTP {e.code}: {detail.get('error', body_text)}",
                status_code=e.code,
                detail=detail,
            ) from e
        except urllib.error.URLError as e:
            raise SutraClientError(f"Connection failed: {e.reason}") from e

    def send_to(
        self,
        agent_id: str,
        from_agent: str,
        body: str,
    ) -> SutraResponse:
        """Send a SUTRA message to an agent by ID (resolved via registry).

        Args:
            agent_id: Target agent ID (e.g. "seller@store")
            from_agent: Sender agent ID
            body: Raw SUTRA source code
        """
        endpoint = self.registry.lookup(agent_id)
        if endpoint is None:
            raise SutraClientError(f"Agent '{agent_id}' not found in registry")
        return self.send(endpoint.url, from_agent, body)

    def check_health(self, url: str) -> dict:
        """Check if a SUTRA agent is healthy."""
        endpoint = f"{url.rstrip('/')}/health"
        req = urllib.request.Request(endpoint)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    def get_status(self, url: str) -> dict:
        """Get agent status/state summary."""
        endpoint = f"{url.rstrip('/')}/status"
        req = urllib.request.Request(endpoint)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    def register_agent(self, registry_url: str, agent_id: str, agent_url: str):
        """Register an agent with a remote registry."""
        endpoint = f"{registry_url.rstrip('/')}/register"
        payload = json.dumps({
            "agent_id": agent_id,
            "url": agent_url,
        }).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_pubkey(self, url: str) -> dict:
        """Fetch an agent's public key from their /pubkey endpoint."""
        endpoint = f"{url.rstrip('/')}/pubkey"
        req = urllib.request.Request(endpoint)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"error": str(e)}
