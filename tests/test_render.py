"""Round-trips between canonical messages and readable SUTRA."""

import unittest

from sutra_lang.render import parse_readable, render_readable

DEAL_FACT = {"primitive": "FACT", "predicate": "available",
             "args": {"item": "SmartTV", "seller": "seller@store", "price": 48000},
             "from": "seller@store", "to": None, "extra": {}}

CASES = [
    {"primitive": "INTENT", "predicate": "buy",
     "args": {"item": "SmartTV", "max_price": 50000, "deadline": "2026-03-01"},
     "from": "buyer@home", "to": None, "extra": {}},
    DEAL_FACT,
    {"primitive": "QUERY", "predicate": "availability", "args": {"item": "SmartTV"},
     "from": "buyer@home", "to": "seller@store", "extra": {}},
    {"primitive": "OFFER", "predicate": None, "args": {"id": "off-001"},
     "body": {"give": {"money": 48000}, "want": {"item": "SmartTV", "brand": "Samsung"}},
     "from": "buyer@home", "to": "seller@store", "extra": {}},
    {"primitive": "COUNTER", "predicate": None,
     "args": {"orig": "off-001", "id": "off-001-c"},
     "body": {"give": {"money": 46000}, "want": {"item": "SmartTV"}},
     "from": "seller@store", "to": "buyer@home", "extra": {}},
    {"primitive": "ACCEPT", "predicate": None, "args": {"id": "off-001"},
     "from": "buyer@home", "to": "seller@store", "extra": {}},
    {"primitive": "REJECT", "predicate": None, "args": {"id": "off-001"},
     "from": "seller@store", "to": "buyer@home", "extra": {"reason": "price_too_high"}},
    {"primitive": "COMMIT", "predicate": "pay",
     "args": {"amount": 48000, "to": "seller@store"},
     "from": "buyer@home", "to": "seller@store", "extra": {"by": "2026-03-01"}},
    {"primitive": "ACT", "predicate": "transfer",
     "args": {"amount": 48000, "to": "seller@store"},
     "from": "buyer@home", "to": "seller@store", "extra": {}},
]


class TestRenderRoundTrip(unittest.TestCase):

    def test_statement_level_round_trip(self):
        for msg in CASES:
            with self.subTest(prim=msg["primitive"]):
                src = render_readable(msg)
                [back] = parse_readable(src, sender=msg["from"],
                                        receiver=msg.get("to"))
                self.assertEqual(back["primitive"], msg["primitive"])
                self.assertEqual(back["predicate"], msg.get("predicate"))
                self.assertEqual(back["args"], msg["args"])
                self.assertEqual(back.get("body"), msg.get("body"))
                self.assertEqual(back["extra"], msg["extra"])
                # routing: QUERY/OFFER/COUNTER carry it in the statement;
                # other primitives inherit the envelope hint.
                if msg["primitive"] in ("QUERY", "OFFER", "COUNTER"):
                    self.assertEqual(back["to"], msg["to"])

    def test_headers_supply_routing_and_threading(self):
        src = ('#from "seller@store"\n#to "buyer@home"\n#re "m03-query"\n'
               + render_readable(DEAL_FACT))
        [back] = parse_readable(src)
        self.assertEqual(back["from"], "seller@store")
        self.assertEqual(back["to"], "buyer@home")
        self.assertEqual(back["extra"], {"in_reply_to": "m03-query"})

    def test_multiple_statements_without_semicolons(self):
        src = "\n".join(render_readable(m).rstrip(";") for m in CASES[:3])
        parsed = parse_readable(src)
        self.assertEqual(len(parsed), 3)


if __name__ == "__main__":
    unittest.main()
