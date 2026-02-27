"""SUTRA v0.4 — Multi-Agent Runtime

Spawn multiple agents in a single process. They communicate directly
via SUTRA messages — no HTTP, no serialization overhead.

Key features:
  - Direct in-process messaging (send / ask / broadcast)
  - Auto-response: QUERY → matching FACTs returned automatically
  - Offer evaluation: agents register logic to auto-ACCEPT/REJECT
  - Conversation tracking: full transcript with message threading
  - Conversation API: natural multi-turn dialogs between agents

This is the layer that lets agents "talk normally."
"""

from __future__ import annotations

from typing import Callable, Any

from .agent import Agent
from .message import SutraMessage, _format_sutra_value
from .lexer import Lexer
from .parser import Parser
from .interpreter import Interpreter
from .ast_nodes import Program, QueryStmt, OfferStmt


class AgentNotFound(Exception):
    pass


class SutraRuntime:
    """Multi-agent SUTRA runtime — all agents in one process.

    Usage:
        rt = SutraRuntime()
        buyer = rt.spawn("buyer@home")
        seller = rt.spawn("seller@store")

        # One-way message
        rt.send("admin", "seller@store", 'FACT available(item="TV", price=48000);')

        # Request-response (auto-generates response)
        msg, reply = rt.ask("buyer@home", "seller@store",
                            'QUERY available(item="TV") FROM "seller@store";')
        # reply contains matching FACTs sent back to buyer!

        rt.print_transcript()
    """

    def __init__(self):
        self.agents: dict[str, Agent] = {}
        self.transcript: list[SutraMessage] = []
        self._offer_evaluators: dict[str, Callable] = {}

    # ── Agent lifecycle ─────────────────────────────────

    def spawn(self, agent_id: str, keypair=None) -> Agent:
        """Create and register a new agent in this runtime."""
        if agent_id in self.agents:
            raise ValueError(f"Agent '{agent_id}' already exists")
        agent = Agent(agent_id, keypair=keypair)
        self.agents[agent_id] = agent
        return agent

    def kill(self, agent_id: str):
        """Remove an agent from the runtime."""
        if agent_id not in self.agents:
            raise AgentNotFound(agent_id)
        del self.agents[agent_id]
        self._offer_evaluators.pop(agent_id, None)

    def get(self, agent_id: str) -> Agent:
        """Get an agent by ID."""
        if agent_id not in self.agents:
            raise AgentNotFound(agent_id)
        return self.agents[agent_id]

    def list_agents(self) -> list[str]:
        """List all agent IDs in the runtime."""
        return list(self.agents.keys())

    def set_offer_evaluator(self, agent_id: str, evaluator: Callable):
        """Register a function to auto-evaluate incoming offers.

        Signature: evaluator(agent, offer_id, from_agent, fields) -> str
        Return "accept" or "reject:<reason>"
        """
        self._offer_evaluators[agent_id] = evaluator

    # ── Messaging ───────────────────────────────────────

    def send(self, from_id: str, to_id: str, body: str) -> SutraMessage:
        """Send a SUTRA message. Executes on the TARGET agent.

        OFFERs are automatically synced to sender's ledger (bilateral).
        Returns the message with execution responses.
        """
        if to_id not in self.agents:
            raise AgentNotFound(to_id)

        target = self.agents[to_id]
        program = self._parse(body)

        # Execute on target
        interp = Interpreter(target)
        responses = interp.execute(program)

        # Bilateral: sync OFFERs to sender's ledger too
        if from_id in self.agents and from_id != to_id:
            self._bilateral_sync(program, self.agents[from_id])

        msg = SutraMessage(
            from_agent=from_id,
            to_agent=to_id,
            body=body.strip(),
            responses=responses,
        )
        self.transcript.append(msg)
        return msg

    def ask(self, from_id: str, to_id: str, body: str) -> tuple[SutraMessage, SutraMessage | None]:
        """Send SUTRA and get an auto-generated response back.

        For QUERY → auto-responds with matching FACTs.
        For OFFER → auto-responds with ACCEPT/REJECT (if evaluator set).

        The response is executed on BOTH target and sender so both
        agents' states stay in sync.

        Returns (original_message, reply_message_or_None).
        """
        if to_id not in self.agents:
            raise AgentNotFound(to_id)

        target = self.agents[to_id]
        sender = self.agents.get(from_id)
        program = self._parse(body)

        # Execute on target
        interp = Interpreter(target)
        responses = interp.execute(program)

        # Bilateral: sync OFFERs to sender's ledger
        if sender and from_id != to_id:
            self._bilateral_sync(program, sender)

        msg = SutraMessage(
            from_agent=from_id,
            to_agent=to_id,
            body=body.strip(),
            responses=responses,
        )
        self.transcript.append(msg)

        # Generate auto-response
        reply_body = self._auto_respond(program, target, from_id)
        reply_msg = None

        if reply_body:
            reply_program = self._parse(reply_body)

            # Execute response on target (update target's state)
            target_ri = Interpreter(target)
            target_ri.execute(reply_program)

            # Execute response on sender (sender sees the result)
            reply_responses = []
            if sender:
                sender_ri = Interpreter(sender)
                reply_responses = sender_ri.execute(reply_program)

            reply_msg = SutraMessage(
                from_agent=to_id,
                to_agent=from_id,
                body=reply_body.strip(),
                responses=reply_responses,
                reply_to=msg.id,
            )
            self.transcript.append(reply_msg)
            msg.reply_body = reply_body

        return msg, reply_msg

    def broadcast(self, from_id: str, body: str) -> list[SutraMessage]:
        """Send SUTRA to ALL agents except sender."""
        messages = []
        for agent_id in list(self.agents.keys()):
            if agent_id != from_id:
                msg = self.send(from_id, agent_id, body)
                messages.append(msg)
        return messages

    def converse(self, *agent_ids: str) -> "Conversation":
        """Start a tracked conversation between specific agents."""
        for aid in agent_ids:
            if aid not in self.agents:
                raise AgentNotFound(aid)
        return Conversation(self, list(agent_ids))

    # ── Internal helpers ────────────────────────────────

    @staticmethod
    def _parse(body: str) -> Program:
        """Parse SUTRA source into an AST."""
        lexer = Lexer(body)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        return parser.parse()

    def _bilateral_sync(self, program: Program, sender: Agent):
        """Execute OFFER statements on sender to keep bilateral state.

        When buyer sends an OFFER to seller, both should have the
        offer in their ledger. This syncs the sender's copy.
        """
        offers = [s for s in program.statements if isinstance(s, OfferStmt)]
        if offers:
            mini = Program(headers=program.headers, statements=offers)
            mini_interp = Interpreter(sender)
            mini_interp.execute(mini)

    def _auto_respond(self, program: Program, target: Agent, from_id: str) -> str | None:
        """Generate SUTRA auto-response based on incoming statements.

        - QUERY → matching FACTs from target's belief_base
        - OFFER → ACCEPT/REJECT via registered evaluator
        """
        response_lines = []

        for stmt in program.statements:
            if isinstance(stmt, QueryStmt):
                resp = self._respond_to_query(target, stmt)
                if resp:
                    response_lines.append(resp)
            elif isinstance(stmt, OfferStmt):
                resp = self._respond_to_offer(target, stmt, from_id)
                if resp:
                    response_lines.append(resp)

        return "\n".join(response_lines) if response_lines else None

    @staticmethod
    def _respond_to_query(agent: Agent, stmt: QueryStmt) -> str | None:
        """Auto-respond to QUERY with matching FACTs from belief_base."""
        args = {
            a.name: Interpreter._resolve_value(a.value)
            for a in stmt.predicate.args
        }
        results = agent.query_facts(stmt.predicate.name, args)

        if not results:
            return None

        lines = []
        for fact in results:
            args_str = ", ".join(
                f"{k}={_format_sutra_value(v)}" for k, v in fact.args.items()
            )
            lines.append(f"FACT {fact.predicate}({args_str});")
        return "\n".join(lines)

    def _respond_to_offer(self, agent: Agent, stmt: OfferStmt, from_id: str) -> str | None:
        """Auto-respond to OFFER using registered evaluator."""
        evaluator = self._offer_evaluators.get(agent.agent_id)
        if evaluator is None:
            return None

        fields = {}
        for f in stmt.fields:
            fields[f.key] = Interpreter._resolve_value(f.value)

        result = evaluator(agent, stmt.offer_id, from_id, fields)

        if result == "accept":
            return f'ACCEPT "{stmt.offer_id}";'
        elif result and result.startswith("reject:"):
            reason = result.split(":", 1)[1]
            return f'REJECT "{stmt.offer_id}" REASON "{reason}";'
        return None

    # ── Display ─────────────────────────────────────────

    def print_transcript(self):
        """Print the full message transcript."""
        print(f"\n{'═' * 60}")
        print(f"  📜 SUTRA Runtime — Transcript ({len(self.transcript)} messages)")
        print(f"{'═' * 60}")

        for i, msg in enumerate(self.transcript):
            target = msg.to_agent or "* (broadcast)"
            reply = " ↩ reply" if msg.is_reply else ""
            print(f"\n  ┌─ [{i+1}] {msg.from_agent} → {target}{reply}")
            for line in msg.body.strip().split("\n"):
                line = line.strip()
                if line:
                    print(f"  │  {line}")
            if msg.responses:
                print(f"  │")
                for r in msg.responses:
                    print(f"  │  ⤷ {r}")
            print(f"  └─")

    def print_agents(self):
        """Print all agent state summaries."""
        for agent in self.agents.values():
            print(agent.state_summary())
            print()


class Conversation:
    """A tracked multi-turn conversation between specific agents.

    Usage:
        conv = runtime.converse("buyer@home", "seller@store")
        conv.say("seller@store", 'FACT available(item="TV", price=48000);')
        msg, reply = conv.ask("buyer@home", "seller@store",
                              'QUERY available(item="TV") FROM "seller@store";')
        conv.print_transcript()
    """

    def __init__(self, runtime: SutraRuntime, agent_ids: list[str]):
        self.runtime = runtime
        self.agent_ids = agent_ids
        self.messages: list[SutraMessage] = []

    def say(self, from_id: str, body: str) -> list[SutraMessage]:
        """Broadcast SUTRA to all other agents in the conversation."""
        if from_id not in self.agent_ids:
            raise AgentNotFound(f"'{from_id}' not in this conversation")
        msgs = []
        for aid in self.agent_ids:
            if aid != from_id:
                msg = self.runtime.send(from_id, aid, body)
                self.messages.append(msg)
                msgs.append(msg)
        return msgs

    def tell(self, from_id: str, to_id: str, body: str) -> SutraMessage:
        """Send SUTRA to a specific agent in the conversation."""
        if from_id not in self.agent_ids or to_id not in self.agent_ids:
            raise AgentNotFound("Both agents must be in this conversation")
        msg = self.runtime.send(from_id, to_id, body)
        self.messages.append(msg)
        return msg

    def ask(self, from_id: str, to_id: str, body: str) -> tuple[SutraMessage, SutraMessage | None]:
        """Send and get auto-response (QUERY→FACTs, OFFER→ACCEPT/REJECT)."""
        if from_id not in self.agent_ids or to_id not in self.agent_ids:
            raise AgentNotFound("Both agents must be in this conversation")
        msg, reply = self.runtime.ask(from_id, to_id, body)
        self.messages.append(msg)
        if reply:
            self.messages.append(reply)
        return msg, reply

    def print_transcript(self):
        """Print this conversation's transcript."""
        agents_str = " × ".join(self.agent_ids)
        print(f"\n{'═' * 60}")
        print(f"  💬 Conversation: {agents_str}")
        print(f"  Messages: {len(self.messages)}")
        print(f"{'═' * 60}")

        for i, msg in enumerate(self.messages):
            target = msg.to_agent or "* (all)"
            reply = " ↩" if msg.is_reply else ""
            print(f"\n  ┌─ [{i+1}] {msg.from_agent} → {target}{reply}")
            for line in msg.body.strip().split("\n"):
                line = line.strip()
                if line:
                    print(f"  │  {line}")
            if msg.responses:
                print(f"  │")
                for r in msg.responses:
                    print(f"  │  ⤷ {r}")
            print(f"  └─")
