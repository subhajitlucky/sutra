"""SUTRA v0.6 — Agent State Persistence

Save and restore agent state to/from disk in JSON format.
Ensures agents can survive crashes and restarts.

Storage layout:
    ~/.sutra/state/
        agent_id.json        — latest snapshot
        agent_id.bak.json    — previous snapshot (atomic backup)

Features:
  - Atomic writes (write to temp → rename) — no corruption on crash
  - Auto-backup: previous snapshot preserved as .bak.json
  - Full round-trip: beliefs, goals, offers, commitments, actions, log
  - Optional auto-save on every N state mutations
"""

from __future__ import annotations

import json
import os
import time
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .agent import Agent, Fact, Intent, Offer, Commitment, Action, LogEntry


# ── Default storage directory ───────────────────────────

DEFAULT_STATE_DIR = os.path.expanduser("~/.sutra/state")


def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


# ════════════════════════════════════════════════════════
#  SERIALIZATION
# ════════════════════════════════════════════════════════

def _serialize_agent(agent: Agent) -> dict:
    """Convert an Agent to a JSON-serializable dict."""
    return {
        "agent_id": agent.agent_id,
        "version": "0.6.0",
        "saved_at": time.time(),
        "belief_base": [
            {"predicate": f.predicate, "args": f.args, "timestamp": f.timestamp}
            for f in agent.belief_base
        ],
        "goal_set": [
            {"predicate": i.predicate, "args": i.args, "timestamp": i.timestamp}
            for i in agent.goal_set
        ],
        "offer_ledger": {
            oid: {
                "offer_id": o.offer_id,
                "from_agent": o.from_agent,
                "to_agent": o.to_agent,
                "fields": o.fields,
                "status": o.status,
                "signature": o.signature,
                "timestamp": o.timestamp,
            }
            for oid, o in agent.offer_ledger.items()
        },
        "commit_ledger": [
            {
                "predicate": c.predicate,
                "args": c.args,
                "deadline": c.deadline,
                "signature": c.signature,
                "timestamp": c.timestamp,
            }
            for c in agent.commit_ledger
        ],
        "action_queue": [
            {"predicate": a.predicate, "args": a.args, "timestamp": a.timestamp}
            for a in agent.action_queue
        ],
        "message_log": [
            {"event": le.event, "detail": le.detail, "timestamp": le.timestamp}
            for le in agent.message_log
        ],
    }


def _deserialize_agent(data: dict, keypair=None) -> Agent:
    """Restore an Agent from a serialized dict."""
    agent = Agent(data["agent_id"], keypair=keypair)

    for f in data.get("belief_base", []):
        fact = Fact(predicate=f["predicate"], args=f["args"], timestamp=f.get("timestamp", 0))
        agent.belief_base.append(fact)

    for i in data.get("goal_set", []):
        intent = Intent(predicate=i["predicate"], args=i["args"], timestamp=i.get("timestamp", 0))
        agent.goal_set.append(intent)

    for oid, o in data.get("offer_ledger", {}).items():
        offer = Offer(
            offer_id=o["offer_id"],
            from_agent=o["from_agent"],
            to_agent=o["to_agent"],
            fields=o["fields"],
            status=o.get("status", "open"),
            signature=o.get("signature"),
            timestamp=o.get("timestamp", 0),
        )
        agent.offer_ledger[oid] = offer

    for c in data.get("commit_ledger", []):
        commit = Commitment(
            predicate=c["predicate"],
            args=c["args"],
            deadline=c.get("deadline"),
            signature=c.get("signature"),
            timestamp=c.get("timestamp", 0),
        )
        agent.commit_ledger.append(commit)

    for a in data.get("action_queue", []):
        action = Action(predicate=a["predicate"], args=a["args"], timestamp=a.get("timestamp", 0))
        agent.action_queue.append(action)

    for le in data.get("message_log", []):
        entry = LogEntry(event=le["event"], detail=le["detail"], timestamp=le.get("timestamp", 0))
        agent.message_log.append(entry)

    return agent


# ════════════════════════════════════════════════════════
#  STATE STORE
# ════════════════════════════════════════════════════════

class StateStore:
    """Persistent storage for SUTRA agent state.

    Usage:
        store = StateStore()

        # Save
        store.save(agent)

        # Load
        agent = store.load("buyer@home")

        # List
        agents = store.list_agents()

        # Auto-save wrapper
        store.auto_save(agent)  # saves immediately
    """

    def __init__(self, state_dir: str = DEFAULT_STATE_DIR):
        self.state_dir = state_dir
        _ensure_dir(self.state_dir)

    def _path(self, agent_id: str) -> str:
        safe = agent_id.replace("/", "_").replace("\\", "_")
        return os.path.join(self.state_dir, f"{safe}.json")

    def _backup_path(self, agent_id: str) -> str:
        safe = agent_id.replace("/", "_").replace("\\", "_")
        return os.path.join(self.state_dir, f"{safe}.bak.json")

    def save(self, agent: Agent) -> str:
        """Save agent state to disk. Returns the file path.

        Uses atomic write (temp + rename) to prevent corruption.
        Previous state is preserved as .bak.json.
        """
        path = self._path(agent.agent_id)
        backup = self._backup_path(agent.agent_id)

        data = _serialize_agent(agent)
        content = json.dumps(data, indent=2, ensure_ascii=False)

        # Backup existing
        if os.path.exists(path):
            try:
                os.replace(path, backup)
            except OSError:
                pass

        # Atomic write
        fd, tmp = tempfile.mkstemp(dir=self.state_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, path)
        except Exception:
            os.unlink(tmp)
            raise

        return path

    def load(self, agent_id: str, keypair=None) -> Agent | None:
        """Load agent state from disk. Returns None if not found."""
        path = self._path(agent_id)
        if not os.path.exists(path):
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return _deserialize_agent(data, keypair=keypair)

    def exists(self, agent_id: str) -> bool:
        """Check if a saved state exists for an agent."""
        return os.path.exists(self._path(agent_id))

    def delete(self, agent_id: str) -> bool:
        """Delete saved state for an agent."""
        path = self._path(agent_id)
        backup = self._backup_path(agent_id)
        deleted = False
        for p in (path, backup):
            if os.path.exists(p):
                os.unlink(p)
                deleted = True
        return deleted

    def list_agents(self) -> list[str]:
        """List all agent IDs with saved state."""
        agents = []
        for fname in os.listdir(self.state_dir):
            if fname.endswith(".json") and not fname.endswith(".bak.json"):
                agents.append(fname[:-5])  # Strip .json
        return sorted(agents)

    def info(self, agent_id: str) -> dict | None:
        """Get metadata about a saved state without loading the full agent."""
        path = self._path(agent_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "agent_id": data.get("agent_id", agent_id),
            "version": data.get("version", "unknown"),
            "saved_at": data.get("saved_at", 0),
            "beliefs": len(data.get("belief_base", [])),
            "goals": len(data.get("goal_set", [])),
            "offers": len(data.get("offer_ledger", {})),
            "commitments": len(data.get("commit_ledger", [])),
            "actions": len(data.get("action_queue", [])),
            "log_entries": len(data.get("message_log", [])),
            "file_size": os.path.getsize(path),
        }
