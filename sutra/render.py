"""Canonical <-> readable SUTRA rendering (used by the compact bridge).

Canonical messages are plain dicts:

    {"primitive": "QUERY", "predicate": "availability", "args": {"item": "SmartTV"},
     "from": "buyer@home", "to": "seller@store", "extra": {}}

`render_readable` produces statements the repo parser accepts;
`parse_readable` turns statements (plus envelope hints) back into canonical
messages. The statement-level fields are lossless; routing that the readable
syntax cannot carry (a directed FACT, for example) travels in `#from`/`#to`
headers or is supplied by the transport layer.
"""

from __future__ import annotations

import json

from .lexer import Lexer
from .parser import Parser

PRIM_BY_CLASS = {
    "IntentStmt": "INTENT", "FactStmt": "FACT", "QueryStmt": "QUERY",
    "OfferStmt": "OFFER", "CounterStmt": "COUNTER", "AcceptStmt": "ACCEPT",
    "RejectStmt": "REJECT", "CommitStmt": "COMMIT", "ActStmt": "ACT",
}


def _q(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def render_readable(msg: dict) -> str:
    """Canonical message -> one readable SUTRA statement (parser-valid)."""
    p, pred = msg["primitive"], msg.get("predicate")
    args = msg.get("args") or {}
    extra = msg.get("extra") or {}

    def predicate(name, items):
        return f"{name}(" + ", ".join(f"{k}={_q(v)}" for k, v in items.items()) + ")"

    if p in ("INTENT", "FACT", "ACT"):
        return f"{p} {predicate(pred, args)};"
    if p == "QUERY":
        return f"QUERY {predicate(pred, args)} FROM {_q(msg['to'])};"
    if p in ("ACCEPT", "REJECT"):
        s = f"{p} {_q(args['id'])}"
        if extra.get("reason"):
            s += f" REASON {_q(extra['reason'])}"
        return s + ";"
    if p == "COMMIT":
        s = f"COMMIT {predicate(pred, args)}"
        if extra.get("by"):
            s += f" BY {_q(extra['by'])}"
        return s + ";"
    if p == "OFFER":
        b = msg["body"]
        g = ", ".join(f"{k}: {_q(v)}" for k, v in b["give"].items())
        w = ", ".join(f"{k}: {_q(v)}" for k, v in b["want"].items())
        return f"OFFER id={_q(args['id'])} TO {_q(msg['to'])} {{ give: {{{g}}}, want: {{{w}}} }};"
    if p == "COUNTER":
        b = msg["body"]
        g = ", ".join(f"{k}: {_q(v)}" for k, v in b["give"].items())
        w = ", ".join(f"{k}: {_q(v)}" for k, v in b["want"].items())
        return (f"COUNTER {_q(args['orig'])} id={_q(args['id'])} TO {_q(msg['to'])} "
                f"{{ give: {{{g}}}, want: {{{w}}} }};")
    raise ValueError(f"cannot render primitive {p!r}")


def _value(node):
    t = type(node).__name__
    if t == "StringVal":
        return node.value
    if t == "NumberVal":
        v = node.value
        return int(v) if float(v).is_integer() else v
    if t == "BoolVal":
        return bool(node.value)
    if t == "NullVal":
        return None
    if t == "MapVal":
        return {k: _value(v) for k, v in node.entries.items()}
    if t == "ListVal":
        return [_value(v) for v in node.items]
    raise ValueError(f"unknown value node {t}")


def parse_readable(source: str, sender: str | None = None,
                   receiver: str | None = None) -> list[dict]:
    """Readable SUTRA (one or more statements) -> canonical messages."""
    program = Parser(Lexer(source).tokenize()).parse()
    headers = {h.key: h.value for h in program.headers}
    from_agent = headers.get("from", sender)
    header_to = headers.get("to", receiver)
    reply_to = headers.get("re")

    out: list[dict] = []
    for stmt in program.statements:
        prim = PRIM_BY_CLASS[type(stmt).__name__]
        msg = {"primitive": prim, "predicate": None, "args": {},
               "from": from_agent, "to": None, "extra": {}}
        if hasattr(stmt, "predicate"):
            msg["predicate"] = stmt.predicate.name
            msg["args"] = {a.name: _value(a.value) for a in stmt.predicate.args}
        if prim == "QUERY":
            msg["to"] = stmt.from_agent
        elif prim in ("OFFER", "COUNTER"):
            if prim == "OFFER":
                msg["args"] = {"id": stmt.offer_id}
            else:
                msg["args"] = {"orig": stmt.original_offer_id, "id": stmt.offer_id}
            msg["to"] = stmt.to_agent
            msg["body"] = {f.key: _value(f.value)
                           for f in stmt.fields if f.key in ("give", "want")}
        elif prim in ("ACCEPT", "REJECT"):
            msg["args"] = {"id": stmt.offer_id}
            if prim == "REJECT" and stmt.reason:
                msg["extra"]["reason"] = stmt.reason
        elif prim == "COMMIT" and stmt.deadline:
            msg["extra"]["by"] = getattr(stmt, "deadline", None)
        if msg["to"] is None:
            msg["to"] = header_to
        if reply_to:
            msg["extra"]["in_reply_to"] = reply_to
        out.append(msg)
    return out
