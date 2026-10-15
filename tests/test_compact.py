"""Tests for sutra.compact — the SUTRA-C wire format (v0.7).

Run:  python -m unittest discover -s tests -v
"""

import unittest

from sutra.compact import (
    CompactError, Session, TemplateSession,
    decode, decode_resync, encode, encode_resync, is_resync,
)


def fresh(**kwargs) -> Session:
    return Session(**kwargs)


class TestRoundTrip(unittest.TestCase):
    """decode(encode(m)) == m for the whole message zoo."""

    def assert_roundtrip(self, msg, session=None):
        session = session or fresh()
        text = encode(msg, session)
        back = decode(text, session)
        self.assertEqual(back, msg, f"round-trip failed for {msg}: {text!r}")
        return text

    def test_all_primitives_both_directions(self):
        cases = [
            {"primitive": "QUERY", "predicate": "availability", "args": {"item": "SmartTV"},
             "from": "buyer@home", "to": "seller@store", "extra": {}},
            {"primitive": "QUERY", "predicate": "availability", "args": {"item": "SmartTV"},
             "from": "seller@store", "to": "buyer@home", "extra": {}},
            {"primitive": "INTENT", "predicate": "buy",
             "args": {"item": "SmartTV", "max_price": 50000, "deadline": "2026-03-01"},
             "from": "buyer@home", "to": None, "extra": {}},
            {"primitive": "FACT", "predicate": "available",
             "args": {"item": "SmartTV", "seller": "seller@store", "price": 48000},
             "from": "seller@store", "to": None, "extra": {}},
            {"primitive": "ACT", "predicate": "transfer",
             "args": {"amount": 48000, "to": "seller@store"},
             "from": "buyer@home", "to": "seller@store", "extra": {}},
            {"primitive": "COMMIT", "predicate": "pay",
             "args": {"amount": 48000, "to": "seller@store"},
             "from": "buyer@home", "to": "seller@store", "extra": {"by": "2026-03-01"}},
            {"primitive": "ACCEPT", "predicate": None, "args": {"id": "off-001"},
             "from": "buyer@home", "to": "seller@store", "extra": {}},
            {"primitive": "REJECT", "predicate": None, "args": {"id": "off-001"},
             "from": "seller@store", "to": "buyer@home", "extra": {"reason": "price_too_high"}},
            {"primitive": "OFFER", "predicate": None, "args": {"id": "off-001"},
             "body": {"give": {"money": 48000}, "want": {"item": "SmartTV", "brand": "Samsung"}},
             "from": "buyer@home", "to": "seller@store", "extra": {}},
            {"primitive": "COUNTER", "predicate": None,
             "args": {"orig": "off-001", "id": "off-001-c"},
             "body": {"give": {"money": 46000}, "want": {"item": "SmartTV"}},
             "from": "seller@store", "to": "buyer@home", "extra": {}},
        ]
        for msg in cases:
            with self.subTest(msg=msg["primitive"]):
                self.assert_roundtrip(msg)

    def test_missing_middle_slot(self):
        msg = {"primitive": "FACT", "predicate": "available",
               "args": {"item": "SmartTV", "price": 48000},
               "from": "seller@store", "to": "buyer@home", "extra": {}}
        text = self.assert_roundtrip(msg)
        self.assertIn("-", text)

    def test_quoted_values_with_spaces(self):
        msg = {"primitive": "FACT", "predicate": "available",
               "args": {"item": "Smart TV Pro", "seller": "seller@store", "price": 48000},
               "from": "seller@store", "to": None, "extra": {}}
        text = self.assert_roundtrip(msg)
        self.assertIn('"Smart TV Pro"', text)

    def test_unknown_predicate_named_fallback(self):
        msg = {"primitive": "FACT", "predicate": "weather",
               "args": {"city": "Bhubaneswar", "temp": 31},
               "from": "seller@store", "to": None, "extra": {}}
        self.assert_roundtrip(msg)

    def test_in_reply_to_tail(self):
        msg = {"primitive": "FACT", "predicate": "available",
               "args": {"item": "SmartTV", "seller": "seller@store", "price": 48000},
               "from": "seller@store", "to": "buyer@home",
               "extra": {"in_reply_to": "m03-query"}}
        text = self.assert_roundtrip(msg)
        self.assertIn("^m03-query", text)


class TestEllipsis(unittest.TestCase):

    def test_repeat_values_become_dots_and_round_trip(self):
        session = fresh()
        first = {"primitive": "FACT", "predicate": "available",
                 "args": {"item": "SmartTV", "seller": "seller@store", "price": 48000},
                 "from": "seller@store", "to": "buyer@home", "extra": {}}
        second = {"primitive": "FACT", "predicate": "committed",
                  "args": {"id": "SmartTV", "status": "signed"},
                  "from": "seller@store", "to": "buyer@home", "extra": {}}
        t1 = encode(first, session)
        t2 = encode(second, session)
        self.assertEqual(decode(t1, session), first)
        self.assertEqual(decode(t2, session), second)
        third = {"primitive": "FACT", "predicate": "committed",
                 "args": {"id": "SmartTV", "status": "void"},
                 "from": "seller@store", "to": "buyer@home", "extra": {}}
        t3 = encode(third, session)
        self.assertIn(".", t3)  # id repeats
        self.assertEqual(decode(t3, session), third)

    def test_ellipsis_without_prior_raises(self):
        session = fresh()
        with self.assertRaises(CompactError):
            decode("q availability .", session)

    def test_predicate_ellipsis(self):
        session = fresh()
        a = {"primitive": "QUERY", "predicate": "availability", "args": {"item": "SmartTV"},
             "from": "buyer@home", "to": "seller@store", "extra": {}}
        b = {"primitive": "QUERY", "predicate": "availability", "args": {"item": "Laptop"},
             "from": "buyer@home", "to": "seller@store", "extra": {}}
        encode(a, session)
        t = encode(b, session)
        self.assertEqual(decode(t, session), b)


class TestDictionary(unittest.TestCase):

    def test_handshake_learn_and_apply(self):
        sender, receiver = fresh(), fresh()
        sender.learn(["SmartTV", "Samsung", "off-001"])
        line = sender.handshake()
        receiver.apply_handshake(line)
        self.assertEqual(receiver.entities, sender.entities)
        self.assertEqual(receiver.reverse, sender.reverse)

    def test_alias_is_single_char_and_round_trips(self):
        session = fresh()
        session.learn(["SmartTV"])
        msg = {"primitive": "QUERY", "predicate": "availability", "args": {"item": "SmartTV"},
               "from": "buyer@home", "to": "seller@store", "extra": {}}
        text = encode(msg, session)
        self.assertEqual(text, "q availability a")
        self.assertEqual(decode(text, session), msg)


class TestRoutingAndResync(unittest.TestCase):

    def test_broadcast_prefix_is_concatenated(self):
        session = fresh()
        msg = {"primitive": "FACT", "predicate": "available",
               "args": {"item": "SmartTV", "seller": "seller@store", "price": 48000},
               "from": "seller@store", "to": None, "extra": {}}
        text = encode(msg, session)
        self.assertTrue(text.startswith("sF "), text)
        self.assertEqual(decode(text, session), msg)

    def test_direction_case(self):
        session = fresh()
        q_fwd = {"primitive": "ACCEPT", "predicate": None, "args": {"id": "off-001"},
                 "from": "buyer@home", "to": "seller@store", "extra": {}}
        q_rev = dict(q_fwd, from_agent=None)
        q_rev = {"primitive": "ACCEPT", "predicate": None, "args": {"id": "off-001"},
                 "from": "seller@store", "to": "buyer@home", "extra": {}}
        fwd = encode(q_fwd, session)
        rev = encode(q_rev, session)
        self.assertTrue(fwd.startswith("a "))
        self.assertTrue(rev.startswith("A "))
        self.assertEqual(decode(fwd, session), q_fwd)
        self.assertEqual(decode(rev, session), q_rev)

    def test_resync_round_trip(self):
        session = fresh()
        surprise = {"primitive": "REJECT", "predicate": None, "args": {"id": "off-001-c"},
                    "from": "seller@store", "to": "buyer@home",
                    "extra": {"reason": "price_too_low"}}
        text = encode_resync(surprise, session)
        self.assertTrue(is_resync(text))
        self.assertEqual(decode_resync(text, session), surprise)
        self.assertEqual(decode(text, session), surprise)  # decode handles the marker


class TestTemplateMeter(unittest.TestCase):

    STEPS = [
        ("QUERY", "availability", True, None),
        ("FACT", "available", False, "m03-query"),
        ("OFFER", None, True, None),
        ("COUNTER", None, False, None),
        ("ACCEPT", None, True, None),
        ("COMMIT", "pay", True, None),
    ]

    def _deal(self):
        return [
            {"primitive": "QUERY", "predicate": "availability", "args": {"item": "SmartTV"},
             "from": "buyer@home", "to": "seller@store", "extra": {}},
            {"primitive": "FACT", "predicate": "available",
             "args": {"item": "SmartTV", "price": 48000},
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

    def test_deal_payloads_and_round_trip(self):
        session = fresh()
        session.register("SmartTV", "a")
        session.register("Samsung", "m")
        session.register("off-001", "o")
        session.register("off-001-c", "p")
        enc = TemplateSession(self.STEPS, session)
        payloads = [enc.encode(m, i) for i, m in enumerate(self._deal())]
        self.assertEqual(payloads,
                         ["a", ".-48000", "o48000am", "op46000.", "o", "48000739676"])

        # decode with a peer that shares the dictionary and template
        peer_session = fresh()
        peer_session.apply_handshake(session.handshake())
        dec = TemplateSession(self.STEPS, peer_session)
        for i, (msg, payload) in enumerate(zip(self._deal(), payloads)):
            self.assertEqual(dec.decode(payload, i), msg, f"step {i}: {payload!r}")

    def test_meter_rejects_multichar_values(self):
        session = fresh()
        enc = TemplateSession(self.STEPS, session)
        bad = {"primitive": "QUERY", "predicate": "availability",
               "args": {"item": "Unknown Thing"},
               "from": "buyer@home", "to": "seller@store", "extra": {}}
        with self.assertRaises(CompactError):
            enc.encode(bad, 0)


class TestErrors(unittest.TestCase):

    def test_empty_and_unknown(self):
        session = fresh()
        with self.assertRaises(CompactError):
            decode("", session)
        with self.assertRaises(CompactError):
            decode("Z foo", session)

    def test_wrong_slot_count(self):
        session = fresh()
        with self.assertRaises(CompactError):
            decode("q availability a b c", session)


if __name__ == "__main__":
    unittest.main()
