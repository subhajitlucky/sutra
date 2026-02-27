"""SUTRA v0.3 — Interpreter

Executes a parsed SUTRA AST against an Agent's state model.
Fully deterministic, transactional execution.
v0.3: Auto-signs COMMIT and OFFER when agent has a keypair.
"""

from __future__ import annotations

from .ast_nodes import (
    Program, Header,
    IntentStmt, FactStmt, QueryStmt, OfferStmt,
    AcceptStmt, RejectStmt, CommitStmt, ActStmt,
    Predicate, NamedArg,
    StringVal, NumberVal, BoolVal, NullVal, MapVal, ListVal,
)
from .agent import Agent
from .crypto import (
    sign, commitment_content, offer_content, SutraSignature,
)


class RuntimeError(Exception):
    pass


class Interpreter:
    """Executes SUTRA programs against an Agent state."""

    def __init__(self, agent: Agent):
        self.agent = agent
        self.responses: list[str] = []

    # ── Value resolution ────────────────────────────────

    @staticmethod
    def _resolve_value(node) -> object:
        if isinstance(node, StringVal):
            return node.value
        if isinstance(node, NumberVal):
            return node.value
        if isinstance(node, BoolVal):
            return node.value
        if isinstance(node, NullVal):
            return None
        if isinstance(node, MapVal):
            return {k: Interpreter._resolve_value(v) for k, v in node.entries.items()}
        if isinstance(node, ListVal):
            return [Interpreter._resolve_value(i) for i in node.items]
        raise RuntimeError(f"Cannot resolve value: {node}")

    @staticmethod
    def _pred_args(pred: Predicate) -> dict[str, object]:
        return {arg.name: Interpreter._resolve_value(arg.value) for arg in pred.args}

    # ── Execution ───────────────────────────────────────

    def execute(self, program: Program) -> list[str]:
        """Execute a SUTRA program. Returns list of response lines."""
        self.responses = []

        # Extract metadata
        meta = {h.key: h.value for h in program.headers}

        for stmt in program.statements:
            self._exec_statement(stmt, meta)

        return self.responses

    def _exec_statement(self, stmt, meta: dict):
        if isinstance(stmt, IntentStmt):
            self._exec_intent(stmt)
        elif isinstance(stmt, FactStmt):
            self._exec_fact(stmt)
        elif isinstance(stmt, QueryStmt):
            self._exec_query(stmt)
        elif isinstance(stmt, OfferStmt):
            self._exec_offer(stmt, meta)
        elif isinstance(stmt, AcceptStmt):
            self._exec_accept(stmt)
        elif isinstance(stmt, RejectStmt):
            self._exec_reject(stmt)
        elif isinstance(stmt, CommitStmt):
            self._exec_commit(stmt)
        elif isinstance(stmt, ActStmt):
            self._exec_act(stmt)
        else:
            raise RuntimeError(f"Unknown statement type: {type(stmt).__name__}")

    def _exec_intent(self, stmt: IntentStmt):
        args = self._pred_args(stmt.predicate)
        self.agent.add_intent(stmt.predicate.name, args)
        self.responses.append(f"[INTENT] {stmt.predicate.name}({_fmt_args(args)})")

    def _exec_fact(self, stmt: FactStmt):
        args = self._pred_args(stmt.predicate)
        self.agent.add_fact(stmt.predicate.name, args)
        self.responses.append(f"[FACT] {stmt.predicate.name}({_fmt_args(args)})")

    def _exec_query(self, stmt: QueryStmt):
        args = self._pred_args(stmt.predicate)
        results = self.agent.query_facts(stmt.predicate.name, args)
        if results:
            for r in results:
                self.responses.append(f"[QUERY RESULT] {r}")
        else:
            self.responses.append(f"[QUERY] No matching facts for {stmt.predicate.name}({_fmt_args(args)})")

    def _exec_offer(self, stmt: OfferStmt, meta: dict):
        fields = {}
        for f in stmt.fields:
            fields[f.key] = self._resolve_value(f.value)
        from_agent = meta.get("from", self.agent.agent_id)
        # v0.3: Auto-sign if agent has a keypair
        sig_dict = None
        sig_info = ""
        if self.agent.keypair is not None:
            content = offer_content(stmt.offer_id, from_agent, stmt.to_agent, fields)
            sig = sign(self.agent.keypair, content)
            sig_dict = sig.to_dict()
            sig_info = f" 🔏 {sig.algorithm}:{sig.signature_hex[:12]}..."
        self.agent.add_offer(
            offer_id=stmt.offer_id,
            from_agent=from_agent,
            to_agent=stmt.to_agent,
            fields=fields,
            signature=sig_dict,
        )
        self.responses.append(f"[OFFER] id={stmt.offer_id!r} → {stmt.to_agent}{sig_info}")

    def _exec_accept(self, stmt: AcceptStmt):
        ok = self.agent.accept_offer(stmt.offer_id)
        if ok:
            self.responses.append(f"[ACCEPT] Offer {stmt.offer_id!r} accepted")
        else:
            self.responses.append(f"[ACCEPT FAILED] Offer {stmt.offer_id!r} not found or not open")

    def _exec_reject(self, stmt: RejectStmt):
        ok = self.agent.reject_offer(stmt.offer_id, stmt.reason)
        if ok:
            reason_part = f" — {stmt.reason}" if stmt.reason else ""
            self.responses.append(f"[REJECT] Offer {stmt.offer_id!r} rejected{reason_part}")
        else:
            self.responses.append(f"[REJECT FAILED] Offer {stmt.offer_id!r} not found or not open")

    def _exec_commit(self, stmt: CommitStmt):
        args = self._pred_args(stmt.predicate)
        # v0.3: Auto-sign if agent has a keypair
        sig_dict = None
        sig_info = ""
        if self.agent.keypair is not None:
            content = commitment_content(
                stmt.predicate.name, args, self.agent.agent_id, stmt.deadline
            )
            sig = sign(self.agent.keypair, content)
            sig_dict = sig.to_dict()
            sig_info = f" 🔏 {sig.algorithm}:{sig.signature_hex[:12]}..."
        self.agent.add_commit(stmt.predicate.name, args, stmt.deadline, sig_dict)
        dl = f" BY {stmt.deadline}" if stmt.deadline else ""
        self.responses.append(f"[COMMIT] {stmt.predicate.name}({_fmt_args(args)}){dl}{sig_info}")

    def _exec_act(self, stmt: ActStmt):
        args = self._pred_args(stmt.predicate)
        self.agent.add_action(stmt.predicate.name, args)
        self.responses.append(f"[ACT] {stmt.predicate.name}({_fmt_args(args)})")


def _fmt_args(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())
