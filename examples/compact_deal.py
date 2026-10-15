"""SUTRA-C end-to-end deal demo (v0.7).

Runs the full 6-message buyer/seller negotiation through the compact codec:
    canonical message -> SUTRA-C -> decode -> readable SUTRA -> repo parser
Token accounting uses tiktoken when available (pip install tiktoken).

Run:  python examples/compact_deal.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sutra.compact import (  # noqa: E402
    Session, TemplateSession, decode, encode, encode_resync,
)

try:
    import tiktoken
    ENC = tiktoken.get_encoding("o200k_base")
    tokens = lambda s: len(ENC.encode(s))
except ImportError:  # token counts are optional
    tokens = lambda s: len(s.split())

STEPS = [
    ("QUERY", "availability", True, None),
    ("FACT", "available", False, "m03-query"),
    ("OFFER", None, True, None),
    ("COUNTER", None, False, None),
    ("ACCEPT", None, True, None),
    ("COMMIT", "pay", True, None),
]

DEAL = [
    {"primitive": "QUERY", "predicate": "availability", "args": {"item": "SmartTV"},
     "from": "buyer@home", "to": "seller@store", "extra": {}},
    {"primitive": "FACT", "predicate": "available", "args": {"item": "SmartTV", "price": 48000},
     "from": "seller@store", "to": "buyer@home", "extra": {"in_reply_to": "m03-query"}},
    {"primitive": "OFFER", "predicate": None, "args": {"id": "off-001"},
     "body": {"give": {"money": 48000}, "want": {"item": "SmartTV", "brand": "Samsung"}},
     "from": "buyer@home", "to": "seller@store", "extra": {}},
    {"primitive": "COUNTER", "predicate": None,
     "args": {"orig": "off-001", "id": "off-001-c"},
     "body": {"give": {"money": 46000}, "want": {"item": "SmartTV"}},
     "from": "seller@store", "to": "buyer@home", "extra": {}},
    {"primitive": "ACCEPT", "predicate": None, "args": {"id": "off-001"},
     "from": "buyer@home", "to": "seller@store", "extra": {}},
    {"primitive": "COMMIT", "predicate": "pay",
     "args": {"amount": 48000, "to": "seller@store"},
     "from": "buyer@home", "to": "seller@store", "extra": {"by": "2026-03-01"}},
]


def q(v):
    return json.dumps(v, ensure_ascii=False) if isinstance(v, str) else str(v)


def render_readable(msg):
    """Canonical message -> readable SUTRA (accepted by the repo parser)."""
    p, pred = msg["primitive"], msg.get("predicate")
    args = msg.get("args") or {}

    def predicate(name, items):
        return f"{name}(" + ", ".join(f"{k}={q(v)}" for k, v in items.items()) + ")"

    if p in ("INTENT", "FACT", "ACT"):
        return f"{p} {predicate(pred, args)};"
    if p == "QUERY":
        return f"QUERY {predicate(pred, args)} FROM {q(msg['to'])};"
    if p in ("ACCEPT", "REJECT"):
        s = f"{p} {q(args['id'])}"
        if msg.get("extra", {}).get("reason"):
            s += f" REASON {q(msg['extra']['reason'])}"
        return s + ";"
    if p == "COMMIT":
        s = f"COMMIT {predicate(pred, args)}"
        if msg.get("extra", {}).get("by"):
            s += f" BY {q(msg['extra']['by'])}"
        return s + ";"
    if p == "OFFER":
        b = msg["body"]
        g = ", ".join(f"{k}: {q(v)}" for k, v in b["give"].items())
        w = ", ".join(f"{k}: {q(v)}" for k, v in b["want"].items())
        return f"OFFER id={q(args['id'])} TO {q(msg['to'])} {{ give: {{{g}}}, want: {{{w}}} }};"
    if p == "COUNTER":
        b = msg["body"]
        g = ", ".join(f"{k}: {q(v)}" for k, v in b["give"].items())
        w = ", ".join(f"{k}: {q(v)}" for k, v in b["want"].items())
        return (f"COUNTER {q(args['orig'])} id={q(args['id'])} TO {q(msg['to'])} "
                f"{{ give: {{{g}}}, want: {{{w}}} }};")
    raise ValueError(p)


def jsonrpc(msg, i):
    return ('{"jsonrpc":"2.0","id":%d,"method":"tools/call","params":{"name":"sutra",'
            '"arguments":%s}}' % (i + 1, json.dumps(msg, separators=(",", ":"))))


def main():
    from sutra.lexer import Lexer
    from sutra.parser import Parser

    buyer, seller = Session(), Session()
    for value, alias in (("SmartTV", "a"), ("Samsung", "m"), ("off-001", "o"), ("off-001-c", "p")):
        buyer.register(value, alias)
    handshake = buyer.handshake()
    seller.apply_handshake(handshake)

    print("handshake (once per session):", handshake, f"[{tokens(handshake)} tok]\n")
    print(f"{'#':<3}{'C1 wire':<20}{'tok':>4}  readable rendering (parser-validated)")
    print("-" * 78)
    c1_total, readable_total = 0, 0

    enc = TemplateSession(STEPS, Session())
    for value, alias in (("SmartTV", "a"), ("Samsung", "m"), ("off-001", "o"), ("off-001-c", "p")):
        enc.session.register(value, alias)
    dec = TemplateSession(STEPS, Session())
    dec.session.apply_handshake(enc.session.handshake())
    meter_payloads = []

    for i, msg in enumerate(DEAL):
        wire = encode(msg, buyer)
        back = decode(wire, seller)
        assert back == msg, f"round-trip failed at step {i}: {wire!r}"
        readable = render_readable(back)
        Parser(Lexer(readable).tokenize()).parse()  # must be executable SUTRA
        c1_total += tokens(wire)
        readable_total += tokens(readable)
        payload = enc.encode(msg, i)
        meter_payloads.append(payload)
        assert dec.decode(payload, i) == msg, f"meter round-trip failed at step {i}"
        print(f"{i:<3}{wire:<20}{tokens(wire):>4}  {readable}")

    print("-" * 78)
    meter_total = sum(tokens(p) for p in meter_payloads)
    json_total = sum(tokens(jsonrpc(m, i)) for i, m in enumerate(DEAL))
    print("\nmeter payloads (template agreed):", meter_payloads)
    print(f"{'':<24}{'total':>6}{'per message':>13}")
    for name, total in (("readable SUTRA", readable_total),
                        ("SUTRA-C (compact)", c1_total),
                        ("SUTRA-C template/meter", meter_total),
                        ("JSON-RPC envelope", json_total)):
        print(f"{name:<24}{total:>6}{total / len(DEAL):>13.2f}")
    print(f"\nvs JSON-RPC: compact {json_total / c1_total:.1f}x cheaper, "
          f"meter {json_total / meter_total:.1f}x cheaper")

    surprise = encode_resync(
        {"primitive": "REJECT", "predicate": None, "args": {"id": "off-001-c"},
         "from": "seller@store", "to": "buyer@home", "extra": {"reason": "price_too_low"}},
        buyer)
    print(f"\noops button (surprise outside the template): {surprise!r} "
          f"[{tokens(surprise)} tok] — session continues compact after")


if __name__ == "__main__":
    main()
