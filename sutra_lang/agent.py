"""SUTRA v0.3 — Agent State Model

Each SUTRA-compliant agent maintains this state:
  - belief_base   (Pramana)   — known facts
  - goal_set      (Sankalpa)  — active intentions
  - offer_ledger  (Samvida)   — open offers
  - commit_ledger (Dharma)    — binding obligations (cryptographically signed)
  - action_queue  (Kriya)     — pending actions
  - message_log               — audit trail
  - keypair       (optional)  — Ed25519 signing key
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from .crypto import verify as _verify_sig, SutraSignature, offer_content, commitment_content


@dataclass
class Fact:
    predicate: str
    args: dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def __str__(self):
        args_str = ", ".join(f'{k}={v!r}' for k, v in self.args.items())
        return f"FACT {self.predicate}({args_str})"


@dataclass
class Intent:
    predicate: str
    args: dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def __str__(self):
        args_str = ", ".join(f'{k}={v!r}' for k, v in self.args.items())
        return f"INTENT {self.predicate}({args_str})"


@dataclass
class Offer:
    offer_id: str
    from_agent: str
    to_agent: str
    fields: dict[str, Any]
    status: str = "open"  # open | accepted | rejected | countered | expired
    signature: dict | None = None  # v0.3: SutraSignature.to_dict() or None
    timestamp: float = field(default_factory=time.time)
    # v0.7: Negotiation features
    expires_at: float | None = None  # Unix timestamp when offer expires (None = never)
    counter_to: str | None = None  # Original offer ID if this is a counter-offer
    conditions: list[dict] | None = None  # Conditions attached to acceptance
    negotiation_round: int = 0  # Tracks how many rounds of negotiation

    @property
    def is_signed(self) -> bool:
        return self.signature is not None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @property
    def is_counter(self) -> bool:
        return self.counter_to is not None

    def __str__(self):
        sig = " 🔏" if self.is_signed else ""
        counter = f" ↩counter:{self.counter_to}" if self.is_counter else ""
        exp = " ⏳" if self.expires_at and not self.is_expired else ""
        exp = " ⌛expired" if self.is_expired else exp
        cond = f" [+{len(self.conditions)} conditions]" if self.conditions else ""
        return f"OFFER id={self.offer_id!r} [{self.status}] → {self.to_agent}{counter}{exp}{cond}{sig}"


@dataclass
class Commitment:
    predicate: str
    args: dict[str, Any]
    deadline: str | None = None
    signature: dict | None = None  # v0.3: SutraSignature.to_dict() or None
    timestamp: float = field(default_factory=time.time)

    @property
    def is_signed(self) -> bool:
        return self.signature is not None

    def __str__(self):
        args_str = ", ".join(f'{k}={v!r}' for k, v in self.args.items())
        dl = f" BY {self.deadline}" if self.deadline else ""
        sig = " 🔏" if self.is_signed else ""
        return f"COMMIT {self.predicate}({args_str}){dl}{sig}"


@dataclass
class Action:
    predicate: str
    args: dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def __str__(self):
        args_str = ", ".join(f'{k}={v!r}' for k, v in self.args.items())
        return f"ACT {self.predicate}({args_str})"


@dataclass
class LogEntry:
    event: str
    detail: str
    timestamp: float = field(default_factory=time.time)


class Agent:
    """A SUTRA-compliant agent runtime state."""

    def __init__(self, agent_id: str, keypair=None):
        self.agent_id = agent_id
        self.belief_base: list[Fact] = []
        self.goal_set: list[Intent] = []
        self.offer_ledger: dict[str, Offer] = {}
        self.commit_ledger: list[Commitment] = []
        self.action_queue: list[Action] = []
        self.message_log: list[LogEntry] = []
        self.keypair = keypair  # v0.3: SutraKeyPair or None
        self.trusted_keys: dict[str, str] = {}  # agent_id → public_key_hex
        # v0.7: Predicate index for O(1) belief lookups
        self._fact_index: dict[str, list[Fact]] = {}

    def _log(self, event: str, detail: str):
        self.message_log.append(LogEntry(event=event, detail=detail))

    # ── State mutations ─────────────────────────────────

    def add_fact(self, predicate: str, args: dict[str, Any]):
        fact = Fact(predicate=predicate, args=args)
        self.belief_base.append(fact)
        # Maintain predicate index
        if predicate not in self._fact_index:
            self._fact_index[predicate] = []
        self._fact_index[predicate].append(fact)
        self._log("FACT", str(fact))

    def add_intent(self, predicate: str, args: dict[str, Any]):
        intent = Intent(predicate=predicate, args=args)
        self.goal_set.append(intent)
        self._log("INTENT", str(intent))

    def add_offer(self, offer_id: str, from_agent: str, to_agent: str, fields: dict[str, Any],
                  signature: dict | None = None, expires_at: float | None = None,
                  counter_to: str | None = None):
        # Calculate negotiation round from counter chain
        neg_round = 0
        if counter_to and counter_to in self.offer_ledger:
            neg_round = self.offer_ledger[counter_to].negotiation_round + 1
        offer = Offer(
            offer_id=offer_id,
            from_agent=from_agent,
            to_agent=to_agent,
            fields=fields,
            signature=signature,
            expires_at=expires_at,
            counter_to=counter_to,
            negotiation_round=neg_round,
        )
        self.offer_ledger[offer_id] = offer
        # If this is a counter-offer, mark the original as "countered"
        if counter_to and counter_to in self.offer_ledger:
            original = self.offer_ledger[counter_to]
            if original.status == "open":
                original.status = "countered"
                self._log("COUNTERED", f"Offer {counter_to!r} superseded by counter {offer_id!r}")
        self._log("OFFER", str(offer))

    def accept_offer(self, offer_id: str, conditions: list[dict] | None = None) -> bool:
        offer = self.offer_ledger.get(offer_id)
        if offer is None:
            self._log("ACCEPT_FAIL", f"Offer {offer_id!r} not found")
            return False
        if offer.status != "open":
            # Check if expired
            if offer.is_expired:
                offer.status = "expired"
                self._log("ACCEPT_FAIL", f"Offer {offer_id!r} expired")
                return False
            self._log("ACCEPT_FAIL", f"Offer {offer_id!r} not open (status={offer.status})")
            return False
        # Check expiry before accepting
        if offer.is_expired:
            offer.status = "expired"
            self._log("ACCEPT_FAIL", f"Offer {offer_id!r} expired before acceptance")
            return False
        offer.status = "accepted"
        offer.conditions = conditions
        self._log("ACCEPT", f"Offer {offer_id!r} accepted" +
                  (f" with {len(conditions)} conditions" if conditions else ""))
        return True

    def reject_offer(self, offer_id: str, reason: str | None = None) -> bool:
        offer = self.offer_ledger.get(offer_id)
        if offer is None or offer.status not in ("open", "countered"):
            self._log("REJECT_FAIL", f"Offer {offer_id!r} not found or not open")
            return False
        if offer.is_expired:
            offer.status = "expired"
            self._log("REJECT_FAIL", f"Offer {offer_id!r} already expired")
            return False
        offer.status = "rejected"
        self._log("REJECT", f"Offer {offer_id!r} rejected" + (f": {reason}" if reason else ""))
        return True

    def expire_offers(self) -> list[str]:
        """Check all open offers and mark expired ones. Returns list of expired offer IDs."""
        expired = []
        for oid, offer in self.offer_ledger.items():
            if offer.status == "open" and offer.is_expired:
                offer.status = "expired"
                expired.append(oid)
                self._log("EXPIRED", f"Offer {oid!r} expired")
        return expired

    def get_negotiation_chain(self, offer_id: str) -> list[Offer]:
        """Trace the full counter-offer chain for an offer."""
        chain = []
        # Walk backwards to find the root
        current_id = offer_id
        while current_id:
            offer = self.offer_ledger.get(current_id)
            if offer is None:
                break
            chain.append(offer)
            current_id = offer.counter_to
        chain.reverse()
        # Now walk forward from root to find all counters
        root_id = chain[0].offer_id if chain else offer_id
        forward = [o for o in self.offer_ledger.values() if o.counter_to == root_id and o not in chain]
        chain.extend(forward)
        return chain

    def add_commit(self, predicate: str, args: dict[str, Any], deadline: str | None = None,
                   signature: dict | None = None):
        commit = Commitment(predicate=predicate, args=args, deadline=deadline,
                            signature=signature)
        self.commit_ledger.append(commit)
        self._log("COMMIT", str(commit))

    def add_action(self, predicate: str, args: dict[str, Any]):
        action = Action(predicate=predicate, args=args)
        self.action_queue.append(action)
        self._log("ACT", str(action))

    def query_facts(self, predicate: str, args: dict[str, Any]) -> list[Fact]:
        """Query belief_base for matching facts (indexed by predicate, subset match).

        Uses _fact_index for O(1) predicate lookup instead of scanning all facts.
        """
        candidates = self._fact_index.get(predicate)
        if not candidates:
            return []
        if not args:
            return list(candidates)
        results = []
        for fact in candidates:
            match = True
            fact_args = fact.args
            for k, v in args.items():
                if k in fact_args and fact_args[k] != v:
                    match = False
                    break
            if match:
                results.append(fact)
        return results

    def rebuild_index(self):
        """Rebuild the fact predicate index from belief_base (use after deserialization)."""
        self._fact_index.clear()
        for fact in self.belief_base:
            if fact.predicate not in self._fact_index:
                self._fact_index[fact.predicate] = []
            self._fact_index[fact.predicate].append(fact)

    # ── Signature verification ───────────────────────────

    def trust_key(self, agent_id: str, public_key_hex: str):
        """Register a trusted public key for an agent."""
        self.trusted_keys[agent_id] = public_key_hex

    def verify_offer(self, offer_id: str) -> bool:
        """Verify the cryptographic signature on a signed offer.

        Returns True if signature is valid, False if invalid or no signature.
        """
        offer = self.offer_ledger.get(offer_id)
        if offer is None or offer.signature is None:
            return False
        sig = SutraSignature.from_dict(offer.signature)
        content = offer_content(
            offer.offer_id, offer.from_agent, offer.to_agent, offer.fields
        )
        return _verify_sig(sig, content)

    def verify_commitment(self, index: int) -> bool:
        """Verify the cryptographic signature on a signed commitment.

        Returns True if signature is valid, False if invalid or no signature.
        """
        if index < 0 or index >= len(self.commit_ledger):
            return False
        commit = self.commit_ledger[index]
        if commit.signature is None:
            return False
        sig = SutraSignature.from_dict(commit.signature)
        content = commitment_content(
            commit.predicate, commit.args,
            sig.signer, commit.deadline
        )
        return _verify_sig(sig, content)

    def verify_all_signatures(self) -> dict[str, list]:
        """Verify all signed offers and commitments. Returns report."""
        report = {"valid_offers": [], "invalid_offers": [],
                  "valid_commits": [], "invalid_commits": []}
        for oid, offer in self.offer_ledger.items():
            if offer.signature:
                if self.verify_offer(oid):
                    report["valid_offers"].append(oid)
                else:
                    report["invalid_offers"].append(oid)
        for i, commit in enumerate(self.commit_ledger):
            if commit.signature:
                if self.verify_commitment(i):
                    report["valid_commits"].append(i)
                else:
                    report["invalid_commits"].append(i)
        return report

    # ── Display ─────────────────────────────────────────

    def state_summary(self) -> str:
        lines = [
            f"╔══════ Agent: {self.agent_id} ══════",
            f"║ Beliefs ({len(self.belief_base)}):",
        ]
        for f in self.belief_base:
            lines.append(f"║   • {f}")
        lines.append(f"║ Goals ({len(self.goal_set)}):")
        for g in self.goal_set:
            lines.append(f"║   • {g}")
        lines.append(f"║ Offers ({len(self.offer_ledger)}):")
        for o in self.offer_ledger.values():
            lines.append(f"║   • {o}")
        signed_commits = sum(1 for c in self.commit_ledger if c.is_signed)
        lines.append(f"║ Commitments ({len(self.commit_ledger)}, {signed_commits} signed):")
        for c in self.commit_ledger:
            lines.append(f"║   • {c}")
        lines.append(f"║ Actions ({len(self.action_queue)}):")
        for a in self.action_queue:
            lines.append(f"║   • {a}")
        lines.append(f"║ Log ({len(self.message_log)} entries)")
        lines.append("╚" + "═" * 40)
        return "\n".join(lines)
