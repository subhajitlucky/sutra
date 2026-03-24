"""SUTRA v0.6 — HTTP Transport Server (Hardened)

Hosts a SUTRA agent as an HTTP endpoint. Other agents send SUTRA
messages via POST /sutra, the server processes them and returns results.

v0.3: Agents expose public keys, sign COMMITs/OFFERs, and include
signatures in HTTP responses for cryptographic verification.

v0.6: Security hardening:
  - Bearer token authentication (Authorization header)
  - Nonce-based replay protection
  - Per-pair message ordering (sequence numbers)
  - Message TTL / expiry enforcement

Protocol:
    POST /sutra
    Content-Type: application/json
    Authorization: Bearer <token>   (v0.6 — optional, if auth enabled)

    Request:
    {
        "from": "buyer@home",
        "body": "QUERY availability(item=\\"SmartTV\\") FROM \\"seller@store\\";",
        "nonce": "a1b2c3...",         // v0.6 — replay protection
        "seq": 5,                      // v0.6 — message ordering
        "ttl": 300,                    // v0.6 — seconds until expiry
        "reply_format": "sutra"        // "sutra" | "json" (default: "json")
    }

    Response:
    {
        "status": "ok",
        "agent": "seller@store",
        "responses": ["[QUERY RESULT] ..."],
        "state_snapshot": { ... }
    }

    GET /status       — agent health + state summary
    GET /registry     — list known agents (if registry attached)
    POST /register    — register a remote agent endpoint

All built on Python stdlib (http.server). Zero dependencies.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable

from .agent import Agent
from .lexer import Lexer, LexerError
from .parser import Parser, ParseError
from .interpreter import Interpreter
from .interpreter import RuntimeError as SutraRuntimeError
from .registry import AgentRegistry
from .keystore import KeyStore
from .security import RateLimiter, InputValidator

logger = logging.getLogger("sutra.server")

# Maximum request body size (1MB) to prevent DoS
_MAX_REQUEST_BODY = 1_048_576


class SutraRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for a SUTRA agent endpoint."""

    # Suppress default stderr logging
    def log_message(self, format, *args):
        logger.info(f"{self.client_address[0]} - {format % args}")

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Sutra-Version", "v0.7")
        # Security headers
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        if length > _MAX_REQUEST_BODY:
            return b""  # will be handled as error downstream
        if length <= 0:
            return b""
        return self.rfile.read(length)

    # ── GET endpoints ───────────────────────────────────

    def do_GET(self):
        if self.path == "/status":
            self._handle_status()
        elif self.path == "/registry":
            self._handle_get_registry()
        elif self.path == "/health":
            self._send_json(200, {"status": "ok", "version": "v0.3"})
        elif self.path == "/pubkey":
            self._handle_pubkey()
        else:
            self._send_json(404, {"error": f"Unknown endpoint: {self.path}"})

    # ── POST endpoints ──────────────────────────────────

    def do_POST(self):
        if self.path == "/sutra":
            self._handle_sutra_message()
        elif self.path == "/register":
            self._handle_register()
        else:
            self._send_json(404, {"error": f"Unknown endpoint: {self.path}"})

    # ── Handlers ────────────────────────────────────────

    def _handle_status(self):
        agent: Agent = self.server.sutra_agent
        signed_commits = sum(1 for c in agent.commit_ledger if c.is_signed)
        signed_offers = sum(1 for o in agent.offer_ledger.values() if o.is_signed)
        summary = {
            "agent_id": agent.agent_id,
            "beliefs": len(agent.belief_base),
            "goals": len(agent.goal_set),
            "offers": len(agent.offer_ledger),
            "offers_signed": signed_offers,
            "commitments": len(agent.commit_ledger),
            "commitments_signed": signed_commits,
            "actions": len(agent.action_queue),
            "log_entries": len(agent.message_log),
            "has_keypair": agent.keypair is not None,
        }
        self._send_json(200, {"status": "ok", "agent": summary})

    def _handle_pubkey(self):
        """Expose the agent's public key (safe to share)."""
        agent: Agent = self.server.sutra_agent
        if agent.keypair is None:
            self._send_json(200, {
                "agent_id": agent.agent_id,
                "has_keypair": False,
            })
        else:
            self._send_json(200, {
                "agent_id": agent.agent_id,
                "has_keypair": True,
                "algorithm": agent.keypair.algorithm,
                "public_key": agent.keypair.public_key_hex,
                "fingerprint": agent.keypair.fingerprint,
            })

    def _handle_get_registry(self):
        registry: AgentRegistry | None = self.server.sutra_registry
        if registry is None:
            self._send_json(200, {"agents": {}})
        else:
            self._send_json(200, {"agents": registry.to_dict()})

    def _handle_register(self):
        try:
            data = json.loads(self._read_body())
            agent_id = data["agent_id"]
            url = data["url"]
            capabilities = data.get("capabilities", [])
        except (json.JSONDecodeError, KeyError) as e:
            self._send_json(400, {"error": f"Invalid registration: {e}"})
            return

        registry: AgentRegistry | None = self.server.sutra_registry
        if registry is None:
            self._send_json(500, {"error": "No registry configured"})
            return

        registry.register(agent_id, url, capabilities)
        logger.info(f"Registered agent: {agent_id} → {url}")
        self._send_json(200, {"status": "registered", "agent_id": agent_id})

    def _handle_sutra_message(self):
        # ── Request size check ───────────────────────────
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > _MAX_REQUEST_BODY:
            self._send_json(413, {"error": f"Request too large: {content_length} bytes (max {_MAX_REQUEST_BODY})"})
            return

        # ── v0.6: Bearer token auth ─────────────────────
        token_auth = getattr(self.server, "sutra_token_auth", None)
        if token_auth is not None:
            auth = self.headers.get("Authorization")
            valid, info = token_auth.verify_header(auth)
            if not valid:
                self._send_json(401, {"error": f"Unauthorized: {info}"})
                return

        # Parse request
        raw_body = self._read_body()
        if not raw_body:
            self._send_json(400, {"error": "Empty request body"})
            return
        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"Invalid JSON: {e}"})
            return

        sender = data.get("from", "unknown")
        body = data.get("body", "")

        # ── v0.7: Input validation ───────────────────────
        validator: InputValidator | None = getattr(self.server, "sutra_input_validator", None)
        if validator is not None:
            valid, reason = validator.validate_agent_id(sender)
            if not valid:
                self._send_json(400, {"error": f"Invalid sender: {reason}"})
                return
            valid, reason = validator.validate_body(body)
            if not valid:
                self._send_json(400, {"error": f"Invalid body: {reason}"})
                return

        if not body.strip():
            self._send_json(400, {"error": "Empty SUTRA body"})
            return

        # ── v0.7: Rate limiting ──────────────────────────
        rate_limiter: RateLimiter | None = getattr(self.server, "sutra_rate_limiter", None)
        if rate_limiter is not None:
            allowed, reason = rate_limiter.check(sender)
            if not allowed:
                self._send_json(429, {"error": reason})
                return

        # ── v0.6: TTL / expiry check ───────────────────
        ttl = data.get("ttl", 0)
        msg_ts = data.get("timestamp", 0)
        if ttl > 0 and msg_ts > 0:
            import time
            age = time.time() - msg_ts
            if age > ttl:
                self._send_json(400, {"error": f"Message expired: {age:.0f}s old (TTL={ttl}s)"})
                return

        # ── v0.6: Replay protection ────────────────────
        replay_guard = getattr(self.server, "sutra_replay_guard", None)
        nonce = data.get("nonce")
        if replay_guard is not None and nonce:
            valid, reason = replay_guard.check(nonce, msg_ts or None)
            if not valid:
                self._send_json(409, {"error": f"Replay rejected: {reason}"})
                return

        # ── v0.6: Sequence ordering ────────────────────
        seq_tracker = getattr(self.server, "sutra_seq_tracker", None)
        seq = data.get("seq")
        if seq_tracker is not None and seq is not None:
            agent_id = self.server.sutra_agent.agent_id
            valid, reason = seq_tracker.check(sender, agent_id, seq)
            if not valid:
                self._send_json(409, {"error": f"Ordering rejected: {reason}"})
                return

        # Execute SUTRA against this agent
        agent: Agent = self.server.sutra_agent
        try:
            lexer = Lexer(body)
            tokens = lexer.tokenize()
            parser = Parser(tokens)
            program = parser.parse()
            interp = Interpreter(agent)
            responses = interp.execute(program)
        except LexerError as e:
            self._send_json(422, {"error": f"Lexer error: {e}", "phase": "lexer"})
            return
        except ParseError as e:
            self._send_json(422, {"error": f"Parse error: {e}", "phase": "parser"})
            return
        except SutraRuntimeError as e:
            self._send_json(422, {"error": f"Runtime error: {e}", "phase": "runtime"})
            return

        logger.info(f"Processed message from {sender}: {len(responses)} responses")

        # Call message hook if registered
        hook: Callable | None = self.server.sutra_on_message
        if hook:
            hook(sender, body, responses)

        self._send_json(200, {
            "status": "ok",
            "agent": agent.agent_id,
            "from_sender": sender,
            "responses": responses,
        })


class SutraServer:
    """HTTP server hosting a SUTRA agent.

    Usage:
        agent = Agent("seller@store")
        server = SutraServer(agent, host="0.0.0.0", port=8001)
        server.start()       # non-blocking (background thread)
        # ... later ...
        server.stop()

    Or use as context manager:
        with SutraServer(agent, port=8001) as server:
            ...
    """

    def __init__(
        self,
        agent: Agent,
        host: str = "127.0.0.1",
        port: int = 8000,
        registry: AgentRegistry | None = None,
        on_message: Callable | None = None,
        keystore: KeyStore | None = None,
        auto_sign: bool = False,
        token_auth=None,
        replay_guard=None,
        seq_tracker=None,
        rate_limiter=None,
        input_validator=None,
    ):
        self.agent = agent
        self.host = host
        self.port = port
        self.registry = registry or AgentRegistry()
        self.on_message = on_message
        self.keystore = keystore
        # v0.6 security
        self.token_auth = token_auth
        self.replay_guard = replay_guard
        self.seq_tracker = seq_tracker
        # v0.7 security
        self.rate_limiter = rate_limiter
        self.input_validator = input_validator or InputValidator()

        # v0.3: Auto-assign keypair to agent if requested
        if auto_sign and agent.keypair is None:
            if keystore is None:
                keystore = KeyStore()
                self.keystore = keystore
            agent.keypair = keystore.get_or_create(agent.agent_id)

        self._httpd: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def _create_server(self) -> HTTPServer:
        httpd = HTTPServer((self.host, self.port), SutraRequestHandler)
        # Attach SUTRA state to the server instance
        httpd.sutra_agent = self.agent
        httpd.sutra_registry = self.registry
        httpd.sutra_on_message = self.on_message
        # v0.6 security
        httpd.sutra_token_auth = self.token_auth
        httpd.sutra_replay_guard = self.replay_guard
        httpd.sutra_seq_tracker = self.seq_tracker
        # v0.7 security
        httpd.sutra_rate_limiter = self.rate_limiter
        httpd.sutra_input_validator = self.input_validator
        return httpd

    def start(self, blocking: bool = False):
        """Start the server.

        Args:
            blocking: If True, blocks the calling thread. If False, runs in background.
        """
        self._httpd = self._create_server()
        url = f"http://{self.host}:{self.port}"
        logger.info(f"SUTRA agent '{self.agent.agent_id}' listening on {url}")

        # Auto-register self
        self.registry.register(self.agent.agent_id, url)

        if blocking:
            print(f"🕉  SUTRA Agent '{self.agent.agent_id}' serving on {url}")
            print(f"   POST {url}/sutra    — send SUTRA messages")
            print(f"   GET  {url}/status   — agent state")
            print(f"   GET  {url}/health   — health check")
            print(f"   Press Ctrl+C to stop.\n")
            try:
                self._httpd.serve_forever()
            except KeyboardInterrupt:
                print(f"\n   Shutting down '{self.agent.agent_id}'...")
                self._httpd.shutdown()
        else:
            self._thread = threading.Thread(
                target=self._httpd.serve_forever,
                daemon=True,
                name=f"sutra-{self.agent.agent_id}",
            )
            self._thread.start()

    def stop(self):
        """Stop the server."""
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def __enter__(self):
        self.start(blocking=False)
        return self

    def __exit__(self, *args):
        self.stop()
