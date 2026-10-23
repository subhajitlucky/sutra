"""Meter mode over real HTTP (v0.10) — the densest form on the network.

Handshake once, agree on a 3-step template, then every message is a
fixed-width payload: `a` (the query), `.48000` (the auto-reply),
`o48000am` (a whole offer). ~2.8 tokens per message, on real HTTP.

Run:  python examples/network_meter_demo.py
"""

import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sutra_lang.agent import Agent  # noqa: E402
from sutra_lang.client import CompactClient  # noqa: E402
from sutra_lang.server import SutraServer  # noqa: E402

try:
    import tiktoken
    ENC = tiktoken.get_encoding("o200k_base")
    tokens = lambda s: len(ENC.encode(s))
except ImportError:
    tokens = lambda s: len(s.split())

STEPS = [
    ("QUERY", "available", True, None),
    ("FACT", "available", False, "m03-query"),
    ("OFFER", None, True, None),
]
QUERY = {"primitive": "QUERY", "predicate": "available", "args": {"item": "SmartTV"},
         "from": "buyer@home", "to": "seller@store", "extra": {}}
OFFER = {"primitive": "OFFER", "predicate": None, "args": {"id": "off-001"},
         "body": {"give": {"money": 48000},
                  "want": {"item": "SmartTV", "brand": "Samsung"}},
         "from": "buyer@home", "to": "seller@store", "extra": {}}


def jsonrpc(msg, i):
    return ('{"jsonrpc":"2.0","id":%d,"method":"tools/call","params":{"name":"sutra",'
            '"arguments":%s}}' % (i, json.dumps(msg, separators=(",", ":"))))


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    seller = Agent("seller@store")
    seller.add_fact("available", {"item": "SmartTV", "seller": "seller@store",
                                  "price": 48000})
    server = SutraServer(seller, port=port)
    server.start()

    buyer = CompactClient("buyer@home")
    try:
        line = buyer.handshake(server.url, line="a=SmartTV m=Samsung o=off-001")
        steps = buyer.negotiate_template(server.url, STEPS)
        print(f"handshake: {line!r} [{tokens(line)} tok, once]")
        print(f"template negotiated over HTTP: {steps} steps\n")

        wire_total = tokens(line)
        print(f"{'wire (HTTP body)':<10}{'tok':>4}   reply on the wire")
        print("-" * 70)
        for msg in (QUERY, OFFER):
            payload, replies, exec_count = buyer.send_meter(server.url, msg)
            wire_total += tokens(payload)
            reply = replies[0] if replies else f"({exec_count} executed, no reply)"
            print(f"{payload:<10}{tokens(payload):>4}   {json.dumps(reply)}")
        print("-" * 70)

        json_total = sum(tokens(jsonrpc(m, i)) for i, m in enumerate((QUERY, OFFER)))
        print(f"\nmeter total: {wire_total} tokens vs {json_total} as JSON-RPC "
              f"envelopes -> {json_total / wire_total:.1f}x cheaper, over real HTTP.")

        surprise = {"primitive": "REJECT", "predicate": None, "args": {"id": "off-001-c"},
                    "from": "buyer@home", "to": "seller@store",
                    "extra": {"reason": "price_too_low"}}
        wire, _, _ = buyer.send_resync(server.url, surprise)
        print(f"oops button off-template: {wire!r} [{tokens(wire)} tok]")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
