"""v0.9 — SUTRA-C over real HTTP: handshake, compact messages, compact replies."""

import socket
import unittest
import urllib.error
import urllib.request

from sutra_lang.agent import Agent
from sutra_lang.client import CompactClient, SutraClientError
from sutra_lang.server import SutraServer

QUERY = {"primitive": "QUERY", "predicate": "available", "args": {"item": "SmartTV"},
         "from": "buyer@home", "to": "seller@store", "extra": {}}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestHttpC1(unittest.TestCase):
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
        client.handshake(self.server.url, values=["SmartTV"])
        return client

    def test_handshake_reports_agent_and_dictionary(self):
        client = CompactClient("buyer@home")
        line = client.handshake(self.server.url, values=["SmartTV"])
        self.assertEqual(line, "a=SmartTV")
        self.assertEqual(client.server_agent, "seller@store")
        self.assertEqual(client.session.entities, {"SmartTV": "a"})

    def test_query_compact_wire_and_compact_reply(self):
        client = self.client()
        wire, replies, exec_count = client.send(self.server.url, QUERY)
        self.assertEqual(wire, "q available a")
        self.assertGreaterEqual(exec_count, 1)
        self.assertEqual(len(replies), 1)
        fact = replies[0]
        self.assertEqual(fact["primitive"], "FACT")
        self.assertEqual(fact["predicate"], "available")
        self.assertEqual(fact["args"]["item"], "SmartTV")
        self.assertEqual(fact["args"]["price"], 48000)
        self.assertEqual(fact["from"], "seller@store")
        self.assertEqual(fact["to"], "buyer@home")

    def test_second_message_uses_ellipsis(self):
        client = self.client()
        client.send(self.server.url, QUERY)
        wire, replies, _ = client.send(self.server.url, QUERY)
        self.assertEqual(wire, "q available .")
        self.assertTrue(replies)

    def test_commit_executes_over_the_wire(self):
        client = self.client()
        commit = {"primitive": "COMMIT", "predicate": "pay",
                  "args": {"amount": 48000, "to": "seller@store"},
                  "from": "buyer@home", "to": "seller@store",
                  "extra": {"by": "2026-03-01"}}
        wire, replies, exec_count = client.send(self.server.url, commit)
        self.assertGreaterEqual(exec_count, 1)
        self.assertEqual(replies, [])

    def test_messages_without_handshake_are_rejected(self):
        # client-side guard: no session yet
        client = CompactClient("buyer@home")
        with self.assertRaises(SutraClientError):
            client.send(self.server.url, QUERY)
        # server-side guard: raw compact request from an unknown session
        req = urllib.request.Request(
            f"{self.server.url}/sutra/c1",
            data=b"q available a",
            headers={"Content-Type": "text/x-sutra-c1", "X-From": "stranger@remote"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 409)

    def test_corrupted_wire_is_rejected(self):
        client = self.client()
        req = urllib.request.Request(
            f"{self.server.url}/sutra/c1",
            data=b"q available .",  # ellipsis with no prior value
            headers={"Content-Type": "text/x-sutra-c1", "X-From": "buyer@home"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 422)


if __name__ == "__main__":
    unittest.main()
