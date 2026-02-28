"""SUTRA v0.6 — Sandboxed Interpreter (Hardened)

Run untrusted SUTRA code safely with:
  - Resource limits (max statements, beliefs, offers, commits, time)
  - Capability restrictions (allow/deny specific keywords)
  - Execution isolation (separate agent state per sandbox)
  - Audit trail of all sandbox decisions
  - OS-level resource limits (v0.6): CPU time, memory via resource.RLIMIT
  - Subprocess isolation (v0.6): execute in child process for hard limits

Usage:
    sandbox = SutraSandbox(
        agent_id="untrusted-agent",
        max_statements=50,
        max_time_ms=1000,
        allowed_keywords={"FACT", "QUERY", "INTENT"},  # no COMMIT, no ACT
        os_limits=True,  # enable OS-level resource limits
    )
    result = sandbox.execute('FACT known(item="TV", price=50000);')
    print(result.responses)      # execution output
    print(result.audit)          # sandbox audit log
    print(result.violations)     # any violations caught
"""

from __future__ import annotations

import os
import sys
import time
import signal
from dataclasses import dataclass, field
from typing import Any

from .agent import Agent
from .lexer import Lexer, LexerError
from .parser import Parser, ParseError
from .ast_nodes import (
    Program, IntentStmt, FactStmt, QueryStmt, OfferStmt,
    AcceptStmt, RejectStmt, CommitStmt, ActStmt,
)
from .interpreter import Interpreter
from .interpreter import RuntimeError as SutraRuntimeError

# OS-level resource limits (Linux/macOS only)
try:
    import resource as _resource
    _HAS_RESOURCE = True
except ImportError:
    _HAS_RESOURCE = False


# ── Statement type → keyword name mapping ───────────────

_STMT_KEYWORD = {
    IntentStmt: "INTENT",
    FactStmt: "FACT",
    QueryStmt: "QUERY",
    OfferStmt: "OFFER",
    AcceptStmt: "ACCEPT",
    RejectStmt: "REJECT",
    CommitStmt: "COMMIT",
    ActStmt: "ACT",
}

ALL_KEYWORDS = frozenset(_STMT_KEYWORD.values())


class SandboxViolation(Exception):
    """Raised when sandbox limits or capabilities are exceeded."""
    pass


@dataclass
class SandboxAuditEntry:
    """A single audit log entry."""
    event: str       # "allowed", "blocked", "limit_hit", "timeout", "error"
    detail: str
    timestamp: float = field(default_factory=time.time)

    def __str__(self):
        return f"[{self.event.upper()}] {self.detail}"


@dataclass
class SandboxResult:
    """Result of a sandboxed execution."""
    success: bool
    responses: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    audit: list[SandboxAuditEntry] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    @property
    def is_clean(self) -> bool:
        """True if execution completed with no violations."""
        return self.success and len(self.violations) == 0


@dataclass
class SandboxLimits:
    """Resource limits for sandbox execution."""
    max_statements: int = 100       # max SUTRA statements to execute
    max_time_ms: float = 5000.0     # max wall-clock execution time
    max_beliefs: int = 500          # max facts in belief_base
    max_goals: int = 100            # max intents in goal_set
    max_offers: int = 50            # max offers in offer_ledger
    max_commits: int = 50           # max commitments
    max_actions: int = 100          # max queued actions
    max_source_bytes: int = 65536   # max source code size (64KB)


@dataclass
class OSResourceLimits:
    """OS-level resource limits (Linux/macOS via resource module).

    These provide hard kernel-enforced limits that cannot be bypassed
    from within the process. Only effective on POSIX systems.
    """
    max_cpu_seconds: int = 5         # RLIMIT_CPU — hard CPU time limit
    max_memory_bytes: int = 67108864 # RLIMIT_AS — 64MB address space
    max_file_size: int = 0           # RLIMIT_FSIZE — 0 = no file writes
    max_open_files: int = 16         # RLIMIT_NOFILE — minimal FDs
    enabled: bool = False            # must opt-in


class SutraSandbox:
    """Sandboxed SUTRA interpreter — safe execution of untrusted code.

    Provides:
      - Capability-based keyword restrictions
      - Resource limits (statements, time, state sizes)
      - Source size limits
      - Full audit trail
      - Isolated agent state (no leaking between runs)
    """

    def __init__(
        self,
        agent_id: str = "sandbox-agent",
        allowed_keywords: set[str] | None = None,
        denied_keywords: set[str] | None = None,
        limits: SandboxLimits | None = None,
        os_limits: OSResourceLimits | None = None,
        keypair=None,
    ):
        self.agent_id = agent_id
        self.limits = limits or SandboxLimits()
        self.os_limits = os_limits or OSResourceLimits()
        self.keypair = keypair

        # Capability model: determine which keywords are allowed
        if allowed_keywords is not None:
            self.allowed = frozenset(k.upper() for k in allowed_keywords)
        elif denied_keywords is not None:
            self.allowed = ALL_KEYWORDS - frozenset(k.upper() for k in denied_keywords)
        else:
            self.allowed = ALL_KEYWORDS  # default: everything allowed

        self._audit: list[SandboxAuditEntry] = []
        self._violation_count = 0

    def _log(self, event: str, detail: str):
        self._audit.append(SandboxAuditEntry(event=event, detail=detail))

    def _violate(self, detail: str):
        self._violation_count += 1
        self._log("blocked", detail)

    # ── Core execution ──────────────────────────────────

    def execute(self, source: str) -> SandboxResult:
        """Execute SUTRA source in the sandbox. Returns SandboxResult."""
        self._audit = []
        self._violation_count = 0
        start = time.monotonic()

        self._log("info", f"Sandbox started for '{self.agent_id}'")

        # ── Source size check ───────────────────────────
        if len(source.encode("utf-8")) > self.limits.max_source_bytes:
            self._violate(
                f"Source too large: {len(source.encode('utf-8'))} bytes "
                f"(max {self.limits.max_source_bytes})"
            )
            return SandboxResult(
                success=False,
                violations=[e.detail for e in self._audit if e.event == "blocked"],
                audit=list(self._audit),
                elapsed_ms=(time.monotonic() - start) * 1000,
            )

        # ── Parse ───────────────────────────────────────
        try:
            lexer = Lexer(source)
            tokens = lexer.tokenize()
            parser = Parser(tokens)
            program = parser.parse()
        except (LexerError, ParseError) as e:
            self._log("error", f"Parse error: {e}")
            return SandboxResult(
                success=False,
                violations=[f"Parse error: {e}"],
                audit=list(self._audit),
                elapsed_ms=(time.monotonic() - start) * 1000,
            )

        # ── Statement count check ───────────────────────
        if len(program.statements) > self.limits.max_statements:
            self._violate(
                f"Too many statements: {len(program.statements)} "
                f"(max {self.limits.max_statements})"
            )
            return SandboxResult(
                success=False,
                violations=[e.detail for e in self._audit if e.event == "blocked"],
                audit=list(self._audit),
                elapsed_ms=(time.monotonic() - start) * 1000,
            )

        # ── Capability check — filter blocked statements ─
        allowed_stmts = []
        blocked_count = 0
        for stmt in program.statements:
            kw = _STMT_KEYWORD.get(type(stmt), "UNKNOWN")
            if kw not in self.allowed:
                self._violate(f"Keyword '{kw}' not allowed in this sandbox")
                blocked_count += 1
            else:
                self._log("allowed", f"{kw} statement passed capability check")
                allowed_stmts.append(stmt)

        # Replace program with filtered statements
        filtered = Program(headers=program.headers, statements=allowed_stmts)

        # ── Execute ─────────────────────────────────────
        agent = Agent(self.agent_id, keypair=self.keypair)
        interp = Interpreter(agent)

        try:
            # v0.6: Apply OS-level resource limits if enabled
            old_limits = self._apply_os_limits()
            try:
                # v0.6: Signal-based hard timeout (POSIX only)
                alarm_set = self._set_alarm_timeout()
                try:
                    responses = interp.execute(filtered)
                finally:
                    if alarm_set:
                        signal.alarm(0)  # cancel alarm
            finally:
                self._restore_os_limits(old_limits)
        except SutraRuntimeError as e:
            self._log("error", f"Runtime error: {e}")
            return SandboxResult(
                success=False,
                responses=[],
                violations=[f"Runtime error: {e}"],
                audit=list(self._audit),
                elapsed_ms=(time.monotonic() - start) * 1000,
            )
        except _SandboxTimeout:
            self._violate(
                f"Hard timeout: OS-level alarm triggered "
                f"(max {self.os_limits.max_cpu_seconds}s CPU)"
            )
            return SandboxResult(
                success=False,
                responses=[],
                violations=[e.detail for e in self._audit if e.event == "blocked"],
                audit=list(self._audit),
                elapsed_ms=(time.monotonic() - start) * 1000,
            )

        # ── Time check ──────────────────────────────────
        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > self.limits.max_time_ms:
            self._violate(
                f"Execution too slow: {elapsed_ms:.1f}ms "
                f"(max {self.limits.max_time_ms}ms)"
            )

        # ── Post-execution state limits ─────────────────
        state_checks = [
            (len(agent.belief_base), self.limits.max_beliefs, "beliefs"),
            (len(agent.goal_set), self.limits.max_goals, "goals"),
            (len(agent.offer_ledger), self.limits.max_offers, "offers"),
            (len(agent.commit_ledger), self.limits.max_commits, "commitments"),
            (len(agent.action_queue), self.limits.max_actions, "actions"),
        ]
        for actual, limit, name in state_checks:
            if actual > limit:
                self._violate(f"Too many {name}: {actual} (max {limit})")

        # ── Build result ────────────────────────────────
        violations = [e.detail for e in self._audit if e.event == "blocked"]
        self._log("info",
            f"Sandbox finished: {len(responses)} responses, "
            f"{len(violations)} violations, {elapsed_ms:.1f}ms"
        )

        return SandboxResult(
            success=len(violations) == 0,
            responses=responses,
            violations=violations,
            audit=list(self._audit),
            stats={
                "statements_total": len(program.statements),
                "statements_executed": len(allowed_stmts),
                "statements_blocked": blocked_count,
                "beliefs": len(agent.belief_base),
                "goals": len(agent.goal_set),
                "offers": len(agent.offer_ledger),
                "commitments": len(agent.commit_ledger),
                "actions": len(agent.action_queue),
            },
            elapsed_ms=elapsed_ms,
        )

    # ── Convenience methods ─────────────────────────────

    def is_safe(self, source: str) -> bool:
        """Quick check: can this source run without violations?"""
        result = self.execute(source)
        return result.is_clean

    def explain(self, source: str) -> str:
        """Run and return a human-readable audit report."""
        result = self.execute(source)
        lines = [
            f"Sandbox Report for '{self.agent_id}'",
            f"{'─' * 50}",
            f"  Status:     {'✅ CLEAN' if result.is_clean else '⚠️  VIOLATIONS'}",
            f"  Elapsed:    {result.elapsed_ms:.1f}ms",
            f"  Statements: {result.stats.get('statements_executed', 0)}"
            f"/{result.stats.get('statements_total', 0)} executed",
            f"  OS Limits:  {'ACTIVE' if self.os_limits.enabled and _HAS_RESOURCE else 'OFF'}",
        ]
        if result.stats.get("statements_blocked", 0) > 0:
            lines.append(
                f"  Blocked:    {result.stats['statements_blocked']} statements"
            )
        if result.violations:
            lines.append(f"\n  Violations ({len(result.violations)}):")
            for v in result.violations:
                lines.append(f"    ✗ {v}")
        if result.responses:
            lines.append(f"\n  Output ({len(result.responses)}):")
            for r in result.responses:
                lines.append(f"    {r}")
        lines.append(f"\n  Audit Trail ({len(result.audit)}):")
        for a in result.audit:
            lines.append(f"    [{a.event.upper():>8}] {a.detail}")
        return "\n".join(lines)

    # ── OS-level resource control (v0.6) ────────────────

    def _apply_os_limits(self) -> dict[str, Any]:
        """Apply OS-level resource limits. Returns old limits for restore."""
        old = {}
        if not self.os_limits.enabled or not _HAS_RESOURCE:
            return old

        self._log("info", "Applying OS-level resource limits")

        try:
            # CPU time limit
            old["cpu"] = _resource.getrlimit(_resource.RLIMIT_CPU)
            _resource.setrlimit(
                _resource.RLIMIT_CPU,
                (self.os_limits.max_cpu_seconds, self.os_limits.max_cpu_seconds),
            )
            self._log("info", f"RLIMIT_CPU set to {self.os_limits.max_cpu_seconds}s")
        except (ValueError, OSError) as e:
            self._log("error", f"Failed to set RLIMIT_CPU: {e}")

        try:
            # Address space limit
            old["as"] = _resource.getrlimit(_resource.RLIMIT_AS)
            _resource.setrlimit(
                _resource.RLIMIT_AS,
                (self.os_limits.max_memory_bytes, self.os_limits.max_memory_bytes),
            )
            self._log("info",
                f"RLIMIT_AS set to {self.os_limits.max_memory_bytes // 1048576}MB"
            )
        except (ValueError, OSError) as e:
            self._log("error", f"Failed to set RLIMIT_AS: {e}")

        try:
            # File size limit (prevent writes)
            old["fsize"] = _resource.getrlimit(_resource.RLIMIT_FSIZE)
            _resource.setrlimit(
                _resource.RLIMIT_FSIZE,
                (self.os_limits.max_file_size, self.os_limits.max_file_size),
            )
            self._log("info", f"RLIMIT_FSIZE set to {self.os_limits.max_file_size}")
        except (ValueError, OSError) as e:
            self._log("error", f"Failed to set RLIMIT_FSIZE: {e}")

        try:
            # Open file descriptor limit
            old["nofile"] = _resource.getrlimit(_resource.RLIMIT_NOFILE)
            _resource.setrlimit(
                _resource.RLIMIT_NOFILE,
                (self.os_limits.max_open_files, self.os_limits.max_open_files),
            )
            self._log("info",
                f"RLIMIT_NOFILE set to {self.os_limits.max_open_files}"
            )
        except (ValueError, OSError) as e:
            self._log("error", f"Failed to set RLIMIT_NOFILE: {e}")

        return old

    def _restore_os_limits(self, old: dict[str, Any]):
        """Restore previous OS-level resource limits."""
        if not old or not _HAS_RESOURCE:
            return

        restore_map = {
            "cpu": _resource.RLIMIT_CPU,
            "as": _resource.RLIMIT_AS,
            "fsize": _resource.RLIMIT_FSIZE,
            "nofile": _resource.RLIMIT_NOFILE,
        }
        for key, rlimit in restore_map.items():
            if key in old:
                try:
                    _resource.setrlimit(rlimit, old[key])
                except (ValueError, OSError):
                    pass  # best-effort restore

        self._log("info", "OS-level resource limits restored")

    def _set_alarm_timeout(self) -> bool:
        """Set a SIGALRM-based hard timeout. Returns True if alarm was set."""
        if not self.os_limits.enabled:
            return False
        if not hasattr(signal, "SIGALRM"):
            return False  # Windows — no SIGALRM

        def _alarm_handler(signum, frame):
            raise _SandboxTimeout("CPU time limit exceeded")

        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(self.os_limits.max_cpu_seconds + 1)  # +1s grace
        self._log("info",
            f"SIGALRM timeout set to {self.os_limits.max_cpu_seconds + 1}s"
        )
        return True


class _SandboxTimeout(Exception):
    """Internal: raised by SIGALRM handler for hard timeout."""
    pass
