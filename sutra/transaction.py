"""SUTRA v0.6 — Transaction Boundaries with Rollback

Execute SUTRA programs within transaction boundaries — if any
statement fails or a violation occurs, ALL state changes are
rolled back to the pre-transaction snapshot.

Features:
  - Snapshot/restore of entire agent state
  - Automatic rollback on error
  - Nested transaction support (savepoints)
  - Commit/rollback hooks for external systems
  - Deadlock-aware timeouts

Usage:
    tx = SutraTransaction(agent)
    try:
        tx.begin()
        interp = Interpreter(agent)
        interp.execute(program)
        tx.commit()
    except Exception:
        tx.rollback()
"""

from __future__ import annotations

import copy
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .agent import Agent, Fact, Intent, Offer, Commitment, Action, LogEntry


# ════════════════════════════════════════════════════════
#  AGENT STATE SNAPSHOT
# ════════════════════════════════════════════════════════

@dataclass
class AgentSnapshot:
    """A frozen copy of agent state at a point in time."""
    agent_id: str
    belief_base: list[Fact]
    goal_set: list[Intent]
    offer_ledger: dict[str, Offer]
    commit_ledger: list[Commitment]
    action_queue: list[Action]
    message_log: list[LogEntry]
    timestamp: float = field(default_factory=time.time)


def snapshot_agent(agent: Agent) -> AgentSnapshot:
    """Take a deep copy snapshot of agent state."""
    return AgentSnapshot(
        agent_id=agent.agent_id,
        belief_base=copy.deepcopy(agent.belief_base),
        goal_set=copy.deepcopy(agent.goal_set),
        offer_ledger=copy.deepcopy(agent.offer_ledger),
        commit_ledger=copy.deepcopy(agent.commit_ledger),
        action_queue=copy.deepcopy(agent.action_queue),
        message_log=copy.deepcopy(agent.message_log),
    )


def restore_agent(agent: Agent, snap: AgentSnapshot):
    """Restore agent state from a snapshot."""
    agent.belief_base = snap.belief_base
    agent.goal_set = snap.goal_set
    agent.offer_ledger = snap.offer_ledger
    agent.commit_ledger = snap.commit_ledger
    agent.action_queue = snap.action_queue
    agent.message_log = snap.message_log


# ════════════════════════════════════════════════════════
#  TRANSACTION
# ════════════════════════════════════════════════════════

class TransactionError(Exception):
    """Raised when a transaction operation is invalid."""
    pass


class SutraTransaction:
    """Transaction wrapper around SUTRA agent state.

    Provides rollback support — if execution fails midway,
    the agent's state is restored to the pre-transaction snapshot.

    Usage:
        tx = SutraTransaction(agent)
        tx.begin()
        try:
            # ... execute SUTRA statements ...
            tx.commit()
        except Exception:
            tx.rollback()

    Or as a context manager:
        with SutraTransaction(agent) as tx:
            # ... execute statements ...
            # auto-commits on success, auto-rolls back on exception
    """

    def __init__(self, agent: Agent, timeout_s: float = 30.0):
        self.agent = agent
        self.timeout_s = timeout_s
        self._snapshots: list[AgentSnapshot] = []
        self._active = False
        self._start_time: float = 0
        self._on_commit: list[Callable] = []
        self._on_rollback: list[Callable] = []

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def depth(self) -> int:
        """Transaction nesting depth (0 = no active transaction)."""
        return len(self._snapshots)

    def begin(self):
        """Start a transaction (or create a savepoint if already in one)."""
        if self._active and not self._snapshots:
            raise TransactionError("Transaction already active with no snapshot")

        snap = snapshot_agent(self.agent)
        self._snapshots.append(snap)

        if not self._active:
            self._active = True
            self._start_time = time.monotonic()

    def commit(self):
        """Commit the current transaction (or release savepoint)."""
        if not self._active:
            raise TransactionError("No active transaction to commit")

        # Check timeout
        elapsed = time.monotonic() - self._start_time
        if elapsed > self.timeout_s:
            self.rollback()
            raise TransactionError(
                f"Transaction timed out: {elapsed:.1f}s > {self.timeout_s}s"
            )

        self._snapshots.pop()  # discard snapshot (changes are kept)

        if not self._snapshots:
            self._active = False
            for hook in self._on_commit:
                hook(self.agent)

    def rollback(self):
        """Rollback to the most recent snapshot."""
        if not self._snapshots:
            raise TransactionError("No active transaction to rollback")

        snap = self._snapshots.pop()
        restore_agent(self.agent, snap)

        if not self._snapshots:
            self._active = False
            for hook in self._on_rollback:
                hook(self.agent)

    def rollback_all(self):
        """Rollback ALL nested transactions to the very first snapshot."""
        if not self._snapshots:
            return
        first = self._snapshots[0]
        self._snapshots.clear()
        restore_agent(self.agent, first)
        self._active = False
        for hook in self._on_rollback:
            hook(self.agent)

    def on_commit(self, fn: Callable):
        """Register a hook called after successful commit."""
        self._on_commit.append(fn)

    def on_rollback(self, fn: Callable):
        """Register a hook called after rollback."""
        self._on_rollback.append(fn)

    # ── Context manager ─────────────────────────────────

    def __enter__(self):
        self.begin()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        return False  # don't suppress exceptions


# ════════════════════════════════════════════════════════
#  SAFE EXECUTE — All-or-nothing execution
# ════════════════════════════════════════════════════════

def safe_execute(agent: Agent, source: str, timeout_s: float = 30.0) -> tuple[list[str], bool]:
    """Execute SUTRA source with transaction safety.

    If ANY statement fails, ALL changes are rolled back.
    Returns (responses, success).

    Usage:
        responses, ok = safe_execute(agent, 'FACT a(x=1); COMMIT bad();')
        if not ok:
            print("Execution failed, state unchanged")
    """
    from .lexer import Lexer
    from .parser import Parser
    from .interpreter import Interpreter

    tx = SutraTransaction(agent, timeout_s=timeout_s)
    tx.begin()

    try:
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse()
        interp = Interpreter(agent)
        responses = interp.execute(program)
        tx.commit()
        return responses, True
    except Exception as e:
        tx.rollback()
        return [f"[TX ROLLBACK] {e}"], False
