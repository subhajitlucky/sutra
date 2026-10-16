"""SUTRA-C over the multi-agent runtime (v0.8).

A CompactChannel gives two agents a shared compact wire format on top of a
SutraRuntime: messages are encoded to SUTRA-C, decoded by the peer session,
rendered back to readable SUTRA, and executed by the existing interpreter.
Auto-responses (QUERY -> FACT, OFFER -> ACCEPT/REJECT) travel back through the
same codec, because the runtime's reply bodies are real SUTRA source.

Both sessions process the identical conversation in the same order — one side
encodes each outgoing message, the other decodes it, and replies mirror that —
so the dictionary and ellipsis states stay consistent without extra traffic.
"""

from __future__ import annotations

from .compact import CompactError, Session, decode, encode
from .render import parse_readable, render_readable


class CompactChannel:
    def __init__(self, runtime, parties=("buyer@home", "seller@store"),
                 party_prefix=("b", "s")):
        self.runtime = runtime
        self.parties = tuple(parties)
        self.sessions = {
            p: Session(parties=self.parties, party_prefix=tuple(party_prefix))
            for p in self.parties
        }
        self.log: list[dict] = []

    # -- dictionary --------------------------------------------------

    def register(self, value: str, alias: str) -> None:
        for session in self.sessions.values():
            session.register(value, alias)

    def learn(self, values) -> None:
        for session in self.sessions.values():
            session.learn(values)

    def handshake_line(self) -> str:
        return self.sessions[self.parties[0]].handshake()

    # -- wire helpers ------------------------------------------------

    def _wire(self, msg: dict) -> str:
        sender = msg["from"]
        receiver = msg["to"]
        if sender not in self.sessions or receiver not in self.sessions:
            raise CompactError(f"unknown party in {sender!r} -> {receiver!r}")
        wire = encode(msg, self.sessions[sender])
        canonical = decode(wire, self.sessions[receiver])  # peer verifies
        return wire if canonical == msg else self._mismatch(msg, wire, canonical)

    @staticmethod
    def _mismatch(msg, wire, canonical):
        raise CompactError(f"peer decoded a different message: {wire!r}\n"
                           f"  sent: {msg}\n  got : {canonical}")

    def _reply_wires(self, reply_body: str, sender: str, receiver: str):
        wires = []
        canonicals = []
        for reply in parse_readable(reply_body, sender=sender, receiver=receiver):
            wire = encode(reply, self.sessions[sender])
            back = decode(wire, self.sessions[receiver])  # requester verifies
            if back != reply:
                raise CompactError(f"reply round-trip mismatch: {wire!r}")
            wires.append(wire)
            canonicals.append(reply)
        return wires, canonicals

    # -- transport ---------------------------------------------------

    def send(self, msg: dict):
        """One-way message. Returns (wire, SutraMessage)."""
        wire = self._wire(msg)
        result = self.runtime.send(msg["from"], msg["to"], render_readable(msg))
        self.log.append({"wire": wire, "readable": render_readable(msg),
                         "responses": list(result.responses)})
        return wire, result

    def ask(self, msg: dict):
        """Request-response. Returns (wire, reply_wires, SutraMessage, reply)."""
        wire = self._wire(msg)
        msg_obj, reply = self.runtime.ask(msg["from"], msg["to"], render_readable(msg))
        reply_wires, reply_canonicals = [], []
        if reply and reply.body:
            reply_wires, reply_canonicals = self._reply_wires(
                reply.body, sender=msg["to"], receiver=msg["from"])
        self.log.append({"wire": wire, "readable": render_readable(msg),
                         "responses": list(msg_obj.responses),
                         "reply_wires": reply_wires,
                         "reply_canonicals": reply_canonicals,
                         "reply_readable": reply.body if reply else None})
        return wire, reply_wires, msg_obj, reply

    def wire_tokens(self) -> int:
        """Total wire tokens when tiktoken is installed, else word count."""
        try:
            import tiktoken
            enc = tiktoken.get_encoding("o200k_base")
            count = lambda s: len(enc.encode(s))
        except ImportError:
            count = lambda s: len(s.split())
        total = 0
        for entry in self.log:
            total += count(entry["wire"])
            total += sum(count(w) for w in entry.get("reply_wires", []))
        return total
