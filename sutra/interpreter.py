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

    # Class-level dispatch table — avoids per-statement isinstance chains
    _DISPATCH = None  # initialized after class definition

    def __init__(self, agent: Agent):
        self.agent = agent
        self.responses: list[str] = []

    # ── Value resolution ────────────────────────────────

    # Type-indexed dispatch for value resolution — O(1) lookup vs isinstance chain
    _VALUE_RESOLVERS = None  # initialized after class definition

    @staticmethod
    def _resolve_value(node) -> object:
        resolver = Interpreter._VALUE_RESOLVERS.get(type(node))
        if resolver is not None:
            return resolver(node)
        raise RuntimeError(f"Cannot resolve value: {node}")

    @staticmethod
    def _pred_args(pred: Predicate) -> dict[str, object]:
        resolve = Interpreter._resolve_value
        return {arg.name: resolve(arg.value) for arg in pred.args}

    # ── Execution ───────────────────────────────────────

    def execute(self, program: Program) -> list[str]:
        """Execute a SUTRA program. Returns list of response lines."""
        self.responses = []

        # Extract metadata
        meta = {h.key: h.value for h in program.headers}

        dispatch = Interpreter._DISPATCH
        for stmt in program.statements:
            handler = dispatch.get(type(stmt))
            if handler is not None:
                handler(self, stmt, meta)
            else:
                raise RuntimeError(f"Unknown statement type: {type(stmt).__name__}")

        return self.responses

    def _exec_statement(self, stmt, meta: dict):
        handler = Interpreter._DISPATCH.get(type(stmt))
        if handler is not None:
            handler(self, stmt, meta)
        else:
            raise RuntimeError(f"Unknown statement type: {type(stmt).__name__}")

    def _exec_intent(self, stmt: IntentStmt, meta: dict):
        args = self._pred_args(stmt.predicate)
        self.agent.add_intent(stmt.predicate.name, args)
        self.responses.append(f"[INTENT] {stmt.predicate.name}({_fmt_args(args)})")

    def _exec_fact(self, stmt: FactStmt, meta: dict):
        args = self._pred_args(stmt.predicate)
        self.agent.add_fact(stmt.predicate.name, args)
        self.responses.append(f"[FACT] {stmt.predicate.name}({_fmt_args(args)})")

    def _exec_query(self, stmt: QueryStmt, meta: dict):
        args = self._pred_args(stmt.predicate)
        results = self.agent.query_facts(stmt.predicate.name, args)
        if results:
            for r in results:
                self.responses.append(f"[QUERY RESULT] {r}")
        else:
            self.responses.append(f"[QUERY] No matching facts for {stmt.predicate.name}({_fmt_args(args)})")

    def _exec_offer(self, stmt: OfferStmt, meta: dict):
        resolve = self._resolve_value
        fields = {f.key: resolve(f.value) for f in stmt.fields}
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

    def _exec_accept(self, stmt: AcceptStmt, meta: dict):
        ok = self.agent.accept_offer(stmt.offer_id)
        if ok:
            self.responses.append(f"[ACCEPT] Offer {stmt.offer_id!r} accepted")
        else:
            self.responses.append(f"[ACCEPT FAILED] Offer {stmt.offer_id!r} not found or not open")

    def _exec_reject(self, stmt: RejectStmt, meta: dict):
        ok = self.agent.reject_offer(stmt.offer_id, stmt.reason)
        if ok:
            reason_part = f" — {stmt.reason}" if stmt.reason else ""
            self.responses.append(f"[REJECT] Offer {stmt.offer_id!r} rejected{reason_part}")
        else:
            self.responses.append(f"[REJECT FAILED] Offer {stmt.offer_id!r} not found or not open")

    def _exec_commit(self, stmt: CommitStmt, meta: dict):
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

    def _exec_act(self, stmt: ActStmt, meta: dict):
        args = self._pred_args(stmt.predicate)
        self.agent.add_action(stmt.predicate.name, args)
        self.responses.append(f"[ACT] {stmt.predicate.name}({_fmt_args(args)})")


def _fmt_args(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


# ── Initialize dispatch tables after class definition ──

Interpreter._DISPATCH = {
    IntentStmt: Interpreter._exec_intent,
    FactStmt: Interpreter._exec_fact,
    QueryStmt: Interpreter._exec_query,
    OfferStmt: Interpreter._exec_offer,
    AcceptStmt: Interpreter._exec_accept,
    RejectStmt: Interpreter._exec_reject,
    CommitStmt: Interpreter._exec_commit,
    ActStmt: Interpreter._exec_act,
}

Interpreter._VALUE_RESOLVERS = {
    StringVal: lambda n: n.value,
    NumberVal: lambda n: n.value,
    BoolVal: lambda n: n.value,
    NullVal: lambda n: None,
    MapVal: lambda n: {k: Interpreter._resolve_value(v) for k, v in n.entries.items()},
    ListVal: lambda n: [Interpreter._resolve_value(i) for i in n.items],
}
