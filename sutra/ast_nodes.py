"""SUTRA v0.1 — AST Node Definitions

Every SUTRA construct is represented as a typed AST node.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


# ── Values ──────────────────────────────────────────────

@dataclass
class StringVal:
    value: str

@dataclass
class NumberVal:
    value: float

@dataclass
class BoolVal:
    value: bool

@dataclass
class NullVal:
    pass

@dataclass
class MapVal:
    entries: dict[str, Any]  # str → Value node

@dataclass
class ListVal:
    items: list[Any]  # list of Value nodes


# ── Predicate ───────────────────────────────────────────

@dataclass
class NamedArg:
    name: str
    value: Any  # Value node

@dataclass
class Predicate:
    name: str
    args: list[NamedArg] = field(default_factory=list)


# ── Headers ─────────────────────────────────────────────

@dataclass
class Header:
    key: str
    value: str


# ── Statements ──────────────────────────────────────────

@dataclass
class IntentStmt:
    """INTENT predicate;"""
    predicate: Predicate

@dataclass
class FactStmt:
    """FACT predicate;"""
    predicate: Predicate

@dataclass
class QueryStmt:
    """QUERY predicate FROM agent;"""
    predicate: Predicate
    from_agent: str

@dataclass
class OfferField:
    key: str
    value: Any  # Value node

@dataclass
class OfferStmt:
    """OFFER id="..." TO "..." { ... } EXPIRES "duration";"""
    offer_id: str
    to_agent: str
    fields: list[OfferField]
    expires: str | None = None  # v0.7: expiration duration/timestamp

@dataclass
class CounterStmt:
    """COUNTER "original_offer_id" id="new_id" TO "agent" { ... } EXPIRES "duration";"""
    original_offer_id: str
    offer_id: str
    to_agent: str
    fields: list[OfferField]
    expires: str | None = None

@dataclass
class AcceptStmt:
    """ACCEPT "offer_id" IF predicate(...);  or  ACCEPT "offer_id";"""
    offer_id: str
    conditions: list[Predicate] | None = None  # v0.7: conditional acceptance

@dataclass
class RejectStmt:
    """REJECT "offer_id" REASON "...";"""
    offer_id: str
    reason: str | None = None

@dataclass
class CommitStmt:
    """COMMIT predicate BY "deadline";"""
    predicate: Predicate
    deadline: str | None = None

@dataclass
class ActStmt:
    """ACT predicate;"""
    predicate: Predicate


# ── Program ─────────────────────────────────────────────

@dataclass
class Program:
    headers: list[Header] = field(default_factory=list)
    statements: list[Any] = field(default_factory=list)  # list of *Stmt nodes
