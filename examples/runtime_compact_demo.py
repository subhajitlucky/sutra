"""SUTRA-C over the real multi-agent runtime (v0.8).

A buyer and a seller negotiate through the compact wire format while the
runtime executes the decoded messages. Auto-responses (QUERY -> FACT,
OFFER -> ACCEPT) travel back through the same codec.

Run:  python examples/runtime_compact_demo.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sutra_lang.compact_bridge import CompactChannel  # noqa: E402
from sutra_lang.runtime import SutraRuntime  # noqa: E402

try:
    import tiktoken
    ENC = tiktoken.get_encoding("o200k_base")
    tokens = lambda s: len(ENC.encode(s))
except ImportError:
    tokens = lambda s: len(s.split())


def main():
    rt = SutraRuntime()
    rt.spawn("buyer@home")
    rt.spawn("seller@store")
    rt.send("seller@store", "seller@store",
            'FACT available(item="SmartTV", seller="seller@store", price=48000);')
    rt.set_offer_evaluator(
        "seller@store",
        lambda agent, offer_id, from_agent, fields:
            "accept" if fields.get("give", {}).get("money", 0) >= 47500
            else "reject:price_too_low",
    )

    channel = CompactChannel(rt)
    channel.register("SmartTV", "a")
    channel.register("Samsung", "m")
    channel.register("off-001", "o")
    print(f"handshake: {channel.handshake_line()!r} [{tokens(channel.handshake_line())} tok]\n")

    script = [
        ("ask", {"primitive": "QUERY", "predicate": "available",
                 "args": {"item": "SmartTV"}, "from": "buyer@home",
                 "to": "seller@store", "extra": {}}),
        ("ask", {"primitive": "OFFER", "predicate": None, "args": {"id": "off-001"},
                 "body": {"give": {"money": 48000},
                          "want": {"item": "SmartTV", "brand": "Samsung"}},
                 "from": "buyer@home", "to": "seller@store", "extra": {}}),
        ("send", {"primitive": "COMMIT", "predicate": "pay",
                  "args": {"amount": 48000, "to": "seller@store"},
                  "from": "buyer@home", "to": "seller@store",
                  "extra": {"by": "2026-03-01"}}),
    ]

    print(f"{'wire':<28}{'tok':>4}   runtime result")
    print("-" * 78)
    for mode, msg in script:
        if mode == "ask":
            wire, reply_wires, msg_obj, reply = channel.ask(msg)
            for line in msg_obj.responses:
                print(f"{wire:<28}{tokens(wire):>4}   {line}")
            for rw in reply_wires:
                print(f"{rw:<28}{tokens(rw):>4}   <- auto-reply on the wire")
        else:
            wire, result = channel.send(msg)
            for line in result.responses:
                print(f"{wire:<28}{tokens(wire):>4}   {line}")

    def jsonrpc(msg, i):
        return ('{"jsonrpc":"2.0","id":%d,"method":"tools/call","params":{"name":"sutra",'
                '"arguments":%s}}' % (i, json.dumps(msg, separators=(",", ":"))))

    rt_tokens = channel.wire_tokens()
    outbound = [m for _, m in script]
    replies = [c for entry in channel.log for c in entry.get("reply_canonicals", [])]
    json_tokens = sum(tokens(jsonrpc(m, i))
                      for i, m in enumerate(outbound + replies))
    print("-" * 78)
    print(f"\nwire tokens this session: {rt_tokens} (handshake {tokens(channel.handshake_line())} once)")
    print(f"the same messages as JSON-RPC envelopes: {json_tokens} tokens "
          f"-> {json_tokens / rt_tokens:.1f}x; every wire message was decoded by the "
          f"peer, rendered to readable SUTRA, and executed by the runtime.")


if __name__ == "__main__":
    main()
