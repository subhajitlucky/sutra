"""SUTRA-C over the real runtime: the deal, end to end, in wire form."""

import unittest

from sutra.compact import decode
from sutra.compact_bridge import CompactChannel
from sutra.runtime import SutraRuntime


def build():
    rt = SutraRuntime()
    rt.spawn("buyer@home")
    rt.spawn("seller@store")
    # seller's knowledge arrives the normal way
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
    return rt, channel


class TestCompactBridge(unittest.TestCase):

    def test_query_over_compact_wire_with_auto_reply(self):
        rt, channel = build()
        query = {"primitive": "QUERY", "predicate": "available",
                 "args": {"item": "SmartTV"}, "from": "buyer@home",
                 "to": "seller@store", "extra": {}}
        wire, reply_wires, msg, reply = channel.ask(query)
        self.assertEqual(wire, "q available a")
        self.assertTrue(reply is not None and reply.body)
        self.assertEqual(len(reply_wires), 1)
        back = decode(reply_wires[0], channel.sessions["buyer@home"])
        self.assertEqual(back["primitive"], "FACT")
        self.assertEqual(back["predicate"], "available")
        self.assertEqual(back["args"].get("price"), 48000)
        self.assertEqual(back["from"], "seller@store")
        self.assertEqual(back["to"], "buyer@home")

    def test_offer_over_compact_wire_auto_accepts(self):
        rt, channel = build()
        offer = {"primitive": "OFFER", "predicate": None, "args": {"id": "off-001"},
                 "body": {"give": {"money": 48000},
                          "want": {"item": "SmartTV", "brand": "Samsung"}},
                 "from": "buyer@home", "to": "seller@store", "extra": {}}
        wire, reply_wires, msg, reply = channel.ask(offer)
        self.assertTrue(reply is not None)
        self.assertTrue(reply_wires and reply_wires[0].startswith("A "), reply_wires)
        back = decode(reply_wires[0], channel.sessions["buyer@home"])
        self.assertEqual(back["primitive"], "ACCEPT")

    def test_commit_executes_on_the_target(self):
        rt, channel = build()
        commit = {"primitive": "COMMIT", "predicate": "pay",
                  "args": {"amount": 48000, "to": "seller@store"},
                  "from": "buyer@home", "to": "seller@store",
                  "extra": {"by": "2026-03-01"}}
        wire, result = channel.send(commit)
        self.assertIn("[COMMIT]", " ".join(result.responses))

    def test_peer_rejects_a_corrupted_wire(self):
        rt, channel = build()
        query = {"primitive": "QUERY", "predicate": "available",
                 "args": {"item": "SmartTV"}, "from": "buyer@home",
                 "to": "seller@store", "extra": {}}
        channel.ask(query)
        # the third decode of the same ellipsis in a fresh session must fail
        from sutra.compact import CompactError, Session
        with self.assertRaises(CompactError):
            decode("q availability .", Session())

    def test_empty_dictionary_still_transports(self):
        rt, _ = build()
        channel = CompactChannel(rt)  # no registers: literals travel bare
        query = {"primitive": "QUERY", "predicate": "available",
                 "args": {"item": "TV"}, "from": "buyer@home",
                 "to": "seller@store", "extra": {}}
        wire, _, _, _ = channel.ask(query)
        self.assertIn("TV", wire)

    def test_wire_token_accounting_runs(self):
        rt, channel = build()
        channel.ask({"primitive": "QUERY", "predicate": "available",
                     "args": {"item": "SmartTV"}, "from": "buyer@home",
                     "to": "seller@store", "extra": {}})
        self.assertGreater(channel.wire_tokens(), 0)


if __name__ == "__main__":
    unittest.main()
