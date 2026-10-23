"""SUTRA-C over real HTTP (v0.9) — two agents, one wire format.

A seller agent runs as an HTTP server; the buyer talks to it in compact C1:
handshake once, then every message and every reply is compact text.

Run:  python examples/network_compact_demo.py
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
        line = buyer.handshake(server.url, values=["SmartTV"])
        print(f"handshake over HTTP: {line!r} [{tokens(line)} tok, once]\n")

        messages = [
            {"primitive": "QUERY", "predicate": "available", "args": {"item": "SmartTV"},
             "from": "buyer@home", "to": "seller@store", "extra": {}},
            {"primitive": "COMMIT", "predicate": "pay",
             "args": {"amount": 48000, "to": "seller@store"},
             "from": "buyer@home", "to": "seller@store", "extra": {"by": "2026-03-01"}},
        ]

        wire_total = tokens(line)
        print(f"{'wire (HTTP body)':<34}{'tok':>4}   reply on the wire")
        print("-" * 78)
        for msg in messages:
            wire, replies, exec_count = buyer.send(server.url, msg)
            wire_total += tokens(wire)
            reply_text = replies[0] if replies else f"({exec_count} executed, no reply)"
            print(f"{wire:<34}{tokens(wire):>4}   {json.dumps(reply_text)}")
        print("-" * 78)

        jsonrpc = 0
        for i, msg in enumerate(messages):
            jsonrpc += tokens('{"jsonrpc":"2.0","id":%d,"method":"tools/call",'
                              '"params":{"name":"sutra","arguments":%s}}'
                              % (i + 1, json.dumps(msg, separators=(",", ":"))))
        print(f"\nwire total: {wire_total} tokens vs {jsonrpc} as JSON-RPC envelopes "
              f"-> {jsonrpc / wire_total:.1f}x cheaper, end to end over HTTP.")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
