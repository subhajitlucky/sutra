"""v0.10 — template (meter) mode over HTTP: payloads like `o48000.m` on the wire."""

import socket
import unittest
import urllib.request

from sutra_lang.agent import Agent
from sutra_lang.client import CompactClient, SutraClientError
from sutra_lang.server import SutraServer

STEPS = [
    ("QUERY", "available", True, None),
    ("FACT", "available", False, "m03-query"),
    ("OFFER", None, True, None),
]

QUERY = {"primitive": "QUERY", "predicate": "available", "args": {"item": "SmartTV"},
         "from": "buyer@home", "to": "seller@store", "extra": {}}
OFFER = {"primitive": "OFFER", "predicate": None, "args": {"id": "off-001"},
         "body": {"give": {"money": 48000}, "want": {"item": "SmartTV", "brand": "Samsung"}},
         "from": "buyer@home", "to": "seller@store", "extra": {}}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestHttpMeter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        agent = Agent("seller@store")
        agent.add_fact("available", {"item": "SmartTV", "seller": "seller@store",
                                     "price": 48000})
        cls.server = SutraServer(agent, port=cls.port)
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def client(self):
        client = CompactClient("buyer@home")
        client.handshake(self.server.url, values=[])
        return client

    def deal_client(self):
        client = CompactClient("buyer@home")
        # hand-picked handles travel in the handshake line: both sides learn them
        client.handshake(self.server.url, line="a=SmartTV m=Samsung o=off-001")
        client.negotiate_template(self.server.url, STEPS)
        return client

    def test_query_then_auto_reply_as_payloads(self):
        client = self.deal_client()
        payload, replies, exec_count = client.send_meter(self.server.url, QUERY)
        self.assertEqual(payload, "a")
        self.assertGreaterEqual(exec_count, 1)
        self.assertEqual(replies, [".48000"])
        fact = client.decode_meter_reply(1, replies[0])
        self.assertEqual(fact["primitive"], "FACT")
        self.assertEqual(fact["args"]["item"], "SmartTV")
        self.assertEqual(fact["args"]["price"], 48000)
        self.assertEqual(fact["from"], "seller@store")
        # step advanced past the reply slot
        self.assertEqual(client.meter_step, 2)

    def test_offer_payload_is_dense(self):
        client = self.deal_client()
        client.send_meter(self.server.url, QUERY)
        payload, replies, exec_count = client.send_meter(self.server.url, OFFER)
        self.assertEqual(payload, "o48000am")
        self.assertEqual(replies, [])
        self.assertGreaterEqual(exec_count, 1)

    def test_template_exhaustion(self):
        client = self.deal_client()
        client.send_meter(self.server.url, QUERY)
        client.send_meter(self.server.url, OFFER)
        with self.assertRaises(SutraClientError):
            client.send_meter(self.server.url, OFFER)

    def test_meter_without_template_is_rejected(self):
        client = self.client()
        with self.assertRaises(SutraClientError) as ctx:
            client.send_meter(self.server.url, QUERY)
        # client-side guard fires first (no template negotiated locally)
        self.assertIn("negotiate_template", str(ctx.exception))

    def test_resync_message_works_alongside_template(self):
        client = self.deal_client()
        client.send_meter(self.server.url, QUERY)
        surprise = {"primitive": "REJECT", "predicate": None,
                    "args": {"id": "off-001-c"},
                    "from": "buyer@home", "to": "seller@store",
                    "extra": {"reason": "price_too_low"}}
        wire, replies, exec_count = client.send_resync(self.server.url, surprise)
        self.assertTrue(wire.startswith("!r"))  # resync marker + forward direction
        self.assertEqual(replies, [])
        self.assertGreaterEqual(exec_count, 1)

    def test_corrupted_payload_is_rejected(self):
        client = self.deal_client()
        req = urllib.request.Request(
            f"{self.server.url}/sutra/c1",
            data=b"a b c d e f",  # wrong shape for step 0
            headers={"Content-Type": "text/x-sutra-c1", "X-From": "buyer@home",
                     "X-Sutra-Mode": "meter"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 422)


if __name__ == "__main__":
    unittest.main()
