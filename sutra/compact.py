"""SUTRA-C — the measured compact wire format (v0.7).

Freezes the encoding family that won the token-cost experiments
(experiments/token-cost/): 6.1 tokens/message, ~24x cheaper than deployed
JSON-RPC envelopes in template sessions, verified readable and writable by
multiple model families (round 7).

Mechanisms (all documented in spec/SUTRA_C.md):
  - single-letter primitives; direction folded into letter case
  - positional Karaka slots with fixed order per (primitive, predicate)
  - session entity dictionary (handshake line) for repeated values
  - ellipsis: '.' repeats the last value of a slot (anuvrtti)
  - '-' marks an absent middle slot
  - tails: !reason  ~deadline  ^in_reply_to
  - resync: a leading '!' means "template broken: a full C1 statement follows"
  - optional template (meter) mode: fixed-width concatenated payloads with the
    message type implied by an agreed sequence

Everything is stdlib-only and lossless: decode(encode(m)) == m.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

KW = {
    "INTENT": "I", "FACT": "F", "QUERY": "Q", "OFFER": "O", "COUNTER": "K",
    "ACCEPT": "A", "REJECT": "R", "COMMIT": "C", "ACT": "X",
}
KW_REV = {v: k for k, v in KW.items()}
PRIMITIVES = list(KW)

# Fixed positional (Karaka) slot order per message kind.
SCHEMA: dict[tuple[str, str | None], list[str]] = {
    ("INTENT", "buy"): ["item", "max_price", "deadline"],
    ("FACT", "available"): ["item", "seller", "price"],
    ("FACT", "committed"): ["id", "status"],
    ("QUERY", "availability"): ["item"],
    ("COMMIT", "pay"): ["amount", "to"],
    ("ACT", "transfer"): ["amount", "to"],
    ("OFFER", None): ["id", "give.money", "want.item", "want.brand"],
    ("COUNTER", None): ["orig", "id", "give.money", "want.item"],
    ("ACCEPT", None): ["id"],
    ("REJECT", None): ["id"],
}
PREDICATE_PRIMS = ("INTENT", "FACT", "QUERY", "COMMIT", "ACT")
REPEAT = "."
MISSING = "-"
RESYNC = "!"
DATE_SLOTS = ("deadline", "by")
TAIL_MARKERS = {"reason": "!", "by": "~", "in_reply_to": "^"}

_BARE_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@._/-")
_RESERVED_TOKENS = {REPEAT, MISSING}


class CompactError(ValueError):
    pass


def _is_number_like(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _is_date(s: str) -> bool:
    return isinstance(s, str) and len(s) == 10 and s[4] == "-" and s[7] == "-"


def _bare(v: str) -> bool:
    return bool(v) and set(v) <= _BARE_OK and v not in _RESERVED_TOKENS and not _is_number_like(v)


def split_tokens(text: str) -> list[str]:
    """Whitespace split that respects double-quoted strings (with backslash
    escapes), so values like "Smart TV Pro" stay one token."""
    tokens: list[str] = []
    buf: list[str] = []
    in_quotes = False
    escaped = False
    for ch in text:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\" and in_quotes:
            buf.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_quotes = not in_quotes
            buf.append(ch)
            continue
        if ch.isspace() and not in_quotes:
            if buf:
                tokens.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tokens


@dataclass
class Session:
    """Per-conversation state: entity dictionary, party aliases, ellipsis."""

    parties: tuple[str, str] = ("buyer@home", "seller@store")
    party_prefix: tuple[str, str] = ("b", "s")
    entities: dict[str, str] = field(default_factory=dict)   # value -> alias
    reverse: dict[str, str] = field(default_factory=dict)    # alias -> value
    slots: dict[str, Any] = field(default_factory=dict)      # ellipsis state
    predicates: dict[str, str] = field(default_factory=dict)

    # -- dictionary -------------------------------------------------
    def register(self, value: str, alias: str) -> None:
        """Hand-picked alias (the memorable handles negotiated by humans)."""
        if len(alias) != 1 or not alias.isalpha():
            raise CompactError(f"alias must be a single letter: {alias!r}")
        if alias in self.reverse or value in self.entities:
            raise CompactError(f"duplicate alias/value: {alias!r}/{value!r}")
        self.entities[value], self.reverse[alias] = alias, value

    def learn(self, values: Iterable[str]) -> None:
        alphabet = [c for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"]
        for v in values:
            if v in self.entities or v in self.parties or not isinstance(v, str):
                continue
            if not alphabet:
                raise CompactError("entity dictionary full (52 handles)")
            alias = alphabet.pop(0)
            self.entities[v], self.reverse[alias] = alias, v

    def handshake(self) -> str:
        """One line both sides exchange once per session."""
        pairs = [f"{alias}={value}" for value, alias in self.entities.items()]
        return " ".join(pairs)

    def apply_handshake(self, line: str) -> None:
        for pair in line.split():
            alias, _, value = pair.partition("=")
            if alias and value:
                self.entities[value] = alias
                self.reverse[alias] = value

    # -- value surface ----------------------------------------------
    def surface(self, v: Any, slot: str) -> str:
        if v is None:
            raise CompactError(f"null value in slot {slot}")
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int):
            return str(v)
        if v in self.entities:
            return self.entities[v]
        if isinstance(v, str) and _bare(v):
            return v
        return json.dumps(v, ensure_ascii=False)

    def restore(self, tok: str, slot: str) -> Any:
        if tok in self.reverse:
            return self.reverse[tok]
        if slot in DATE_SLOTS and tok.isdigit() and len(tok) == 6:
            return dt.date.fromordinal(int(tok)).isoformat()
        if tok.isdigit() or (tok.startswith("-") and tok[1:].isdigit()):
            return int(tok)
        if tok in ("true", "false"):
            return tok == "true"
        if tok.startswith('"') and tok.endswith('"'):
            return json.loads(tok)
        return tok


def _flatten(msg: dict) -> dict[str, Any]:
    flat = dict(msg.get("args") or {})
    for side, pairs in (msg.get("body") or {}).items():
        for k, v in (pairs.items() if isinstance(pairs, dict) else pairs):
            flat[f"{side}.{k}"] = v
    for k in ("reason", "by", "in_reply_to"):
        v = (msg.get("extra") or {}).get(k)
        if v is not None:
            flat[k] = v
    return flat


def slot_order(primitive: str, predicate: str | None) -> list[str]:
    return SCHEMA.get((primitive, predicate), [])


# ── C1 encode / decode ─────────────────────────────────────────────

def encode(msg: dict, session: Session) -> str:
    """Canonical message dict -> one C1 statement (ellipsis-aware)."""
    prim = msg["primitive"]
    pred = msg.get("predicate")
    flat = _flatten(msg)
    order = slot_order(prim, pred)

    # routing
    src, dst = msg.get("from"), msg.get("to")
    directed = dst is not None
    forward = directed and src == session.parties[0]
    if directed and src not in session.parties:
        raise CompactError(f"unknown party: {src!r}")
    if not directed and src not in session.parties:
        raise CompactError(f"unknown party: {src!r}")

    K = KW[prim]
    prefix = ""
    if directed:
        K = K.lower() if forward else K.upper()
    else:
        idx = session.parties.index(src)
        prefix = session.party_prefix[idx]  # broadcast: sender glued to the letter

    parts: list[str] = []
    if pred and prim in PREDICATE_PRIMS:
        parts.append(pred)
    if order:
        for slot in order:
            v = flat.get(slot, MISSING)
            if v is MISSING:
                parts.append(MISSING)
            elif slot in session.slots and session.slots[slot] == v:
                parts.append(REPEAT)
            else:
                session.slots[slot] = v
                parts.append(session.surface(v, slot))
    elif pred:  # unknown predicate: named-argument fallback (general extension)
        for k, v in (msg.get("args") or {}).items():
            parts.append(f"{k}={session.surface(v, k)}")

    stmt = f"{prefix}{K} " + " ".join(parts) if parts else f"{prefix}{K}"
    tail: list[str] = []
    for key in ("reason", "by", "in_reply_to"):
        v = (msg.get("extra") or {}).get(key)
        if v is None:
            continue
        marker = TAIL_MARKERS[key]
        if key in session.slots and session.slots[key] == v:
            tail.append(f"{marker}{REPEAT}")
        else:
            session.slots[key] = v
            tail.append(f"{marker}{session.surface(v, key)}")
    if tail:
        stmt += " " + " ".join(tail)
    return stmt


def decode(text: str, session: Session) -> dict:
    """One C1 statement -> canonical message dict. Raises CompactError."""
    if text.startswith(RESYNC):
        text = text[1:].strip()  # resync: the rest is a plain C1 statement
    tokens = split_tokens(text)
    if not tokens:
        raise CompactError("empty statement")

    # routing
    first = tokens[0]
    prefix = None
    if len(first) > 1 and first[0] in session.party_prefix and first[1:].upper() in KW_REV:
        prefix = first[0]
        tokens[0] = first[1:]
        first = tokens[0]
    K = tokens.pop(0)
    if prefix is not None:
        src = session.parties[session.party_prefix.index(prefix)]
        dst = None
    else:
        if K.islower():
            src, dst = session.parties[0], session.parties[1]
        else:
            src, dst = session.parties[1], session.parties[0]
        K = K.upper()
    prim = KW_REV.get(K)
    if prim is None:
        raise CompactError(f"unknown primitive letter: {first!r}")

    # predicate (when the primitive carries one)
    pred = None
    if prim in PREDICATE_PRIMS:
        if not tokens:
            raise CompactError(f"{prim} without predicate")
        pt = tokens.pop(0)
        if pt == REPEAT:
            pred = session.predicates.get(prim)
            if pred is None:
                raise CompactError(f"ellipsis for {prim} predicate with no prior value")
        else:
            pred = pt
            session.predicates[prim] = pred

    # tails are the trailing marked tokens
    tails: dict[str, str] = {}
    while tokens and tokens[-1][:1] in TAIL_MARKERS.values() and len(tokens[-1]) > 1:
        t = tokens.pop()
        tails[t[0]] = t[1:]
    marker_to_key = {v: k for k, v in TAIL_MARKERS.items()}

    order = slot_order(prim, pred)
    args: dict[str, Any] = {}
    body: dict[str, dict[str, Any]] = {}
    if order:
        if len(tokens) != len(order):
            raise CompactError(f"{prim}: expected {len(order)} slot tokens, got {len(tokens)}")
        for slot, tok in zip(order, tokens):
            if tok == MISSING:
                continue
            if tok == REPEAT:
                if slot not in session.slots:
                    raise CompactError(f"ellipsis for slot {slot!r} with no prior value")
                v = session.slots[slot]
            else:
                v = session.restore(tok, slot)
                session.slots[slot] = v
            if "." in slot:
                side, name = slot.split(".", 1)
                body.setdefault(side, {})[name] = v
            else:
                args[slot] = v
    else:
        for tok in tokens:
            k, _, v = tok.partition("=")
            if not _:
                raise CompactError(f"unstructured argument without '=': {tok!r}")
            args[k] = session.restore(v, k)

    extra: dict[str, Any] = {}
    for marker, tok in tails.items():
        key = marker_to_key[marker]
        if tok == REPEAT:
            if key not in session.slots:
                raise CompactError(f"ellipsis for {key!r} with no prior value")
            v = session.slots[key]
        else:
            v = session.restore(tok, key)
            session.slots[key] = v
        extra[key] = v

    out: dict[str, Any] = {"primitive": prim, "predicate": pred, "args": args,
                           "from": src, "to": dst, "extra": extra}
    if body:
        out["body"] = body
    return out


# ── template (meter) mode ──────────────────────────────────────────

DEFAULT_WIDTHS = {"max_price": 5, "price": 5, "amount": 5, "give.money": 5,
                  "by": 6, "deadline": 6}
IMPLIED_ADDRESS_SLOTS = ("seller", "to")


@dataclass
class TemplateSession:
    """Agreed message sequence; payloads carry only new field values.

    `steps`: list of (primitive, predicate, direction, in_reply_to) where
    direction is True for parties[0] -> parties[1].
    """

    steps: list[tuple[str, str | None, bool, str | None]]
    session: Session
    widths: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_WIDTHS))

    def _order(self, step: int) -> list[str]:
        prim, pred, _, _ = self.steps[step]
        return slot_order(prim, pred)

    def encode(self, msg: dict, step: int) -> str:
        prim, pred, forward, reply_to = self.steps[step]
        assert msg["primitive"] == prim, f"step {step}: expected {prim}"
        flat = _flatten(msg)
        out: list[str] = []
        for slot in self._order(step):
            v = flat.get(slot, MISSING)
            if v is MISSING:
                out.append(MISSING)
            elif slot in IMPLIED_ADDRESS_SLOTS and v in self.session.parties:
                continue  # implied by the template
            elif slot in self.session.slots and self.session.slots[slot] == v:
                out.append(REPEAT)
            else:
                self.session.slots[slot] = v
                if isinstance(v, int):
                    w = self.widths.get(slot, 5)
                    out.append(str(v).rjust(w, "0"))
                else:
                    s = self.session.surface(v, slot)
                    if len(s) != 1:
                        raise CompactError(f"meter mode needs single-char values: {v!r}")
                    out.append(s)
        by = flat.get("by")
        if by is not None:
            if self.session.slots.get("by") == by:
                out.append(REPEAT)
            else:
                self.session.slots["by"] = by
                day = dt.date.fromisoformat(by).toordinal() if _is_date(by) else int(by)
                out.append(str(day).rjust(6, "0"))
        return "".join(out)

    def decode(self, text: str, step: int) -> dict:
        prim, pred, forward, reply_to = self.steps[step]
        order = self._order(step)
        src, dst = (self.session.parties if forward else self.session.parties[::-1])
        pos = 0
        implied = {}
        if "seller" in order:
            implied["seller"] = self.session.parties[1]
        if "to" in order:
            implied["to"] = dst
        args: dict[str, Any] = {}
        body: dict[str, dict[str, Any]] = {}
        for slot in order:
            if slot in implied:
                if pos < len(text) and text[pos] in (MISSING, REPEAT):
                    tok = text[pos]
                    pos += 1
                    v = MISSING if tok == MISSING else self._ellipsis(slot)
                else:
                    v = implied[slot]
            elif pos < len(text) and text[pos] in (MISSING, REPEAT):
                tok = text[pos]
                pos += 1
                v = MISSING if tok == MISSING else self._ellipsis(slot)
            else:
                # numeric slots are fixed-width; everything else is one char.
                # A digit at this position implies a numeric field.
                w = self.widths.get(slot)
                if w is None:
                    w = 5 if (pos < len(text) and text[pos].isdigit()) else 1
                chunk = text[pos:pos + w]
                pos += w
                if chunk.isdigit():
                    v = self.session.restore(chunk.lstrip("0") or "0", slot)
                else:
                    v = self.session.restore(chunk, slot)
                self.session.slots[slot] = v
            if v is MISSING:
                continue
            if "." in slot:
                side, name = slot.split(".", 1)
                body.setdefault(side, {})[name] = v
            else:
                args[slot] = v
        extra: dict[str, Any] = {}
        if pos < len(text):
            rest = text[pos:]
            if rest == REPEAT:
                extra["by"] = self._ellipsis("by")
            else:
                day = int(rest)
                extra["by"] = dt.date.fromordinal(day).isoformat()
                self.session.slots["by"] = extra["by"]
        if reply_to:
            extra["in_reply_to"] = reply_to
        out: dict[str, Any] = {"primitive": prim, "predicate": pred, "args": args,
                               "from": src, "to": dst, "extra": extra}
        if body:
            out["body"] = body
        return out

    def _ellipsis(self, slot: str) -> Any:
        if slot not in self.session.slots:
            raise CompactError(f"ellipsis for slot {slot!r} with no prior value")
        return self.session.slots[slot]


# ── resync ─────────────────────────────────────────────────────────

def encode_resync(msg: dict, session: Session) -> str:
    """A message outside the agreed template: marker + full C1 statement."""
    return RESYNC + encode(msg, session)


def is_resync(text: str) -> bool:
    return text.startswith(RESYNC)


def decode_resync(text: str, session: Session) -> dict:
    if not is_resync(text):
        raise CompactError("not a resync statement")
    return decode(text[1:].strip(), session)
