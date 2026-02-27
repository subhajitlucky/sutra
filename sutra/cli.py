#!/usr/bin/env python3
"""SUTRA v0.4 — CLI Entry Point

Usage:
    python -m sutra run <file.sutra>                 # Run a script with a default agent
    python -m sutra run <file.sutra> --agent <id>    # Run with named agent
    python -m sutra run <file.sutra> --sign          # Run and sign COMMITs/OFFERs
    python -m sutra parse <file.sutra>               # Parse and dump AST
    python -m sutra demo                             # Run built-in buyer/seller demo
    python -m sutra serve --agent <id> --port 8000   # Start HTTP agent server
    python -m sutra send <url> <file.sutra>          # Send a .sutra message via HTTP
    python -m sutra network-demo                     # Run networked multi-agent demo
    python -m sutra keygen <agent_id>                # Generate signing key pair
    python -m sutra keys                             # List all stored keys
    python -m sutra verify <agent_id>                # Verify an agent's signed commits
    python -m sutra signed-demo                      # Run demo with cryptographic signing
    python -m sutra runtime-demo                     # Run multi-agent runtime demo
"""

import argparse
import sys
import os
import time
import logging

from .lexer import Lexer, LexerError
from .parser import Parser, ParseError
from .interpreter import Interpreter
from .interpreter import RuntimeError as SutraRuntimeError
from .agent import Agent


def run_file(filepath: str, agent_id: str = "default-agent") -> list[str]:
    """Parse and execute a .sutra file."""
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()
    return run_source(source, agent_id)


def run_source(source: str, agent_id: str = "default-agent", agent: Agent | None = None) -> list[str]:
    """Parse and execute SUTRA source code."""
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    parser = Parser(tokens)
    program = parser.parse()
    if agent is None:
        agent = Agent(agent_id)
    interp = Interpreter(agent)
    responses = interp.execute(program)
    return responses


def cmd_run(args):
    if not os.path.exists(args.file):
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    try:
        agent = Agent(args.agent)
        # v0.3: optionally sign COMMITs/OFFERs
        if getattr(args, 'sign', False):
            from .keystore import KeyStore
            store = KeyStore()
            agent.keypair = store.get_or_create(args.agent)
        responses = []
        with open(args.file, "r", encoding="utf-8") as f:
            source = f.read()
        responses = run_source(source, args.agent, agent)
        print(f"\n{'─' * 50}")
        print(f"  SUTRA Execution Results")
        print(f"  Agent: {args.agent}")
        print(f"  File:  {args.file}")
        print(f"{'─' * 50}\n")
        for r in responses:
            print(f"  {r}")
        print(f"\n{'─' * 50}")
        print(f"\n{agent.state_summary()}")
    except LexerError as e:
        print(f"Lexer Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ParseError as e:
        print(f"Parse Error: {e}", file=sys.stderr)
        sys.exit(1)
    except SutraRuntimeError as e:
        print(f"Runtime Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_parse(args):
    if not os.path.exists(args.file):
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(args.file, "r", encoding="utf-8") as f:
            source = f.read()
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse()

        print("\n=== SUTRA AST ===\n")
        print(f"Headers: {len(program.headers)}")
        for h in program.headers:
            print(f"  #{h.key} {h.value!r}")
        print(f"\nStatements: {len(program.statements)}")
        for i, stmt in enumerate(program.statements):
            print(f"  [{i+1}] {type(stmt).__name__}: {stmt}")
    except (LexerError, ParseError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_demo(_args):
    """Run a full buyer-seller negotiation demo."""
    print("\n" + "═" * 60)
    print("  🕉  SUTRA v0.1 — Agent-to-Agent Commerce Demo")
    print("═" * 60)

    buyer = Agent("buyer@home")
    seller = Agent("seller@store")

    # ── Step 1: Seller publishes facts ──────────────────
    print("\n── Step 1: Seller publishes product facts ──")
    seller_facts = '''
FACT available(item="SmartTV", brand="Samsung", price=55000, stock=10);
FACT available(item="SmartTV", brand="LG", price=48000, stock=5);
FACT shipping(method="express", days=3, cost=500);
'''
    responses = run_source(seller_facts, "seller@store", seller)
    for r in responses:
        print(f"  {r}")

    # ── Step 2: Buyer declares intent ───────────────────
    print("\n── Step 2: Buyer declares purchase intent ──")
    buyer_intent = '''
#sutra "v0.1"
#from "buyer@home"

INTENT buy(item="SmartTV", max_price=50000, deadline="2026-03-01");
'''
    responses = run_source(buyer_intent, "buyer@home", buyer)
    for r in responses:
        print(f"  {r}")

    # ── Step 3: Buyer queries seller ────────────────────
    print("\n── Step 3: Buyer queries seller for availability ──")
    # Simulate: buyer sends query, seller's belief_base is checked
    results = seller.query_facts("available", {"item": "SmartTV"})
    if results:
        for fact in results:
            print(f"  [QUERY RESULT] {fact}")
            # Buyer learns the facts
            buyer.add_fact(fact.predicate, fact.args)
    else:
        print("  [QUERY] No results")

    # ── Step 4: Buyer makes offer ───────────────────────
    print("\n── Step 4: Buyer makes an offer ──")
    buyer_offer = '''
OFFER id="off-001" TO "seller@store" {
    give: {money: 46000},
    want: {item: "SmartTV", brand: "LG"},
    expires: "2026-03-01T23:59"
};
'''
    responses = run_source(buyer_offer, "buyer@home", buyer)
    for r in responses:
        print(f"  {r}")
    # Copy offer to seller's ledger too
    seller.add_offer("off-001", "buyer@home", "seller@store",
                     {"give": {"money": 46000}, "want": {"item": "SmartTV", "brand": "LG"},
                      "expires": "2026-03-01T23:59"})

    # ── Step 5: Seller rejects (price too low) ──────────
    print("\n── Step 5: Seller rejects — price too low ──")
    seller_reject = '''
REJECT "off-001" REASON "price_too_low";
'''
    responses = run_source(seller_reject, "seller@store", seller)
    for r in responses:
        print(f"  {r}")

    # ── Step 6: Buyer counter-offers ────────────────────
    print("\n── Step 6: Buyer counter-offers ──")
    buyer_counter = '''
OFFER id="off-002" TO "seller@store" {
    give: {money: 47500},
    want: {item: "SmartTV", brand: "LG"},
    expires: "2026-03-01T23:59"
};
'''
    responses = run_source(buyer_counter, "buyer@home", buyer)
    for r in responses:
        print(f"  {r}")
    seller.add_offer("off-002", "buyer@home", "seller@store",
                     {"give": {"money": 47500}, "want": {"item": "SmartTV", "brand": "LG"},
                      "expires": "2026-03-01T23:59"})

    # ── Step 7: Seller accepts ──────────────────────────
    print("\n── Step 7: Seller accepts the counter-offer ──")
    seller_accept = '''
ACCEPT "off-002";
'''
    responses = run_source(seller_accept, "seller@store", seller)
    for r in responses:
        print(f"  {r}")

    # ── Step 8: Both commit ─────────────────────────────
    print("\n── Step 8: Both sides commit (Dharma — binding) ──")
    buyer_commit = '''
COMMIT pay(amount=47500, to="seller@store") BY "2026-03-02";
ACT transfer(amount=47500, to="seller@store");
'''
    responses = run_source(buyer_commit, "buyer@home", buyer)
    for r in responses:
        print(f"  {r}")

    seller_commit = '''
COMMIT deliver(item="SmartTV", brand="LG", to="buyer@home") BY "2026-03-05";
ACT ship(item="SmartTV", method="express", to="buyer@home");
'''
    responses = run_source(seller_commit, "seller@store", seller)
    for r in responses:
        print(f"  {r}")

    # ── Final State ─────────────────────────────────────
    print("\n" + "═" * 60)
    print("  Final Agent States")
    print("═" * 60)
    print(buyer.state_summary())
    print()
    print(seller.state_summary())
    print("\n  ✓ Transaction complete. Dharma fulfilled.\n")


# ── v0.2: Network commands ──────────────────────────────


def cmd_serve(args):
    """Start an HTTP server hosting a SUTRA agent."""
    from .server import SutraServer
    from .registry import AgentRegistry
    from .keystore import KeyStore

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    agent = Agent(args.agent)
    registry = AgentRegistry()
    keystore = KeyStore() if getattr(args, 'sign', False) else None

    # v0.3: auto-sign if --sign flag
    if getattr(args, 'sign', False):
        agent.keypair = keystore.get_or_create(args.agent)
        print(f"  🔏 Signing enabled (key: {agent.keypair.fingerprint})")

    # Pre-load facts from a file if provided
    if args.facts:
        if not os.path.exists(args.facts):
            print(f"Error: Facts file not found: {args.facts}", file=sys.stderr)
            sys.exit(1)
        with open(args.facts, "r", encoding="utf-8") as f:
            source = f.read()
        responses = run_source(source, args.agent, agent)
        print(f"  Pre-loaded {len(responses)} facts from {args.facts}")

    server = SutraServer(
        agent=agent,
        host=args.host,
        port=args.port,
        registry=registry,
        keystore=keystore,
        auto_sign=getattr(args, 'sign', False),
    )
    server.start(blocking=True)


def cmd_send(args):
    """Send a .sutra file to a remote agent via HTTP."""
    from .client import SutraClient, SutraClientError

    if not os.path.exists(args.file):
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    with open(args.file, "r", encoding="utf-8") as f:
        body = f.read()

    client = SutraClient(timeout=args.timeout)
    url = args.url

    print(f"\n{'─' * 50}")
    print(f"  Sending SUTRA message")
    print(f"  From: {args.from_agent}")
    print(f"  To:   {url}")
    print(f"  File: {args.file}")
    print(f"{'─' * 50}\n")

    try:
        response = client.send(url, args.from_agent, body)
        print(f"  Agent: {response.agent}")
        print(f"  Status: {response.status}")
        print()
        for r in response.responses:
            print(f"  {r}")
        print(f"\n{'─' * 50}")
    except SutraClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_network_demo(_args):
    """Run a full networked buyer/seller negotiation demo.

    Starts two HTTP agents (buyer on :8100, seller on :8101),
    then orchestrates a complete negotiation over the network.
    """
    from .server import SutraServer
    from .client import SutraClient
    from .registry import AgentRegistry

    print("\n" + "═" * 60)
    print("  🕉  SUTRA v0.2 — Networked Agent Commerce Demo")
    print("═" * 60)

    registry = AgentRegistry()
    buyer = Agent("buyer@home")
    seller = Agent("seller@store")

    buyer_server = SutraServer(buyer, port=8100, registry=registry)
    seller_server = SutraServer(seller, port=8101, registry=registry)

    buyer_server.start(blocking=False)
    seller_server.start(blocking=False)
    time.sleep(0.3)  # let servers bind

    registry.register("buyer@home", "http://127.0.0.1:8100")
    registry.register("seller@store", "http://127.0.0.1:8101")

    client = SutraClient(registry=registry, timeout=5.0)

    print(f"\n  ✓ Buyer  agent running on http://127.0.0.1:8100")
    print(f"  ✓ Seller agent running on http://127.0.0.1:8101")

    try:
        # ── Step 1: Load seller facts ───────────────────
        print("\n── Step 1: Load seller product catalog (via HTTP) ──")
        resp = client.send_to("seller@store", "admin", '''
FACT available(item="SmartTV", brand="Samsung", price=55000, stock=10);
FACT available(item="SmartTV", brand="LG", price=48000, stock=5);
FACT shipping(method="express", days=3, cost=500);
''')
        for r in resp.responses:
            print(f"  {r}")

        # ── Step 2: Buyer declares intent ───────────────
        print("\n── Step 2: Buyer declares intent (via HTTP) ──")
        resp = client.send_to("buyer@home", "buyer@home", '''
INTENT buy(item="SmartTV", max_price=50000, deadline="2026-03-01");
''')
        for r in resp.responses:
            print(f"  {r}")

        # ── Step 3: Buyer queries seller ────────────────
        print("\n── Step 3: Buyer queries seller (via HTTP) ──")
        resp = client.send_to("seller@store", "buyer@home", '''
QUERY availability(item="SmartTV") FROM "buyer@home";
''')
        for r in resp.responses:
            print(f"  {r}")

        # ── Step 4: Buyer sends offer to seller ─────────
        print("\n── Step 4: Buyer sends offer to seller (via HTTP) ──")
        resp = client.send_to("seller@store", "buyer@home", '''
OFFER id="off-001" TO "seller@store" {
    give: {money: 46000},
    want: {item: "SmartTV", brand: "LG"},
    expires: "2026-03-01T23:59"
};
''')
        for r in resp.responses:
            print(f"  {r}")

        # ── Step 5: Seller rejects ──────────────────────
        print("\n── Step 5: Seller rejects — price too low (via HTTP) ──")
        resp = client.send_to("seller@store", "seller@store", '''
REJECT "off-001" REASON "price_below_minimum";
''')
        for r in resp.responses:
            print(f"  {r}")

        # ── Step 6: Buyer counter-offers ────────────────
        print("\n── Step 6: Buyer counter-offers (via HTTP) ──")
        resp = client.send_to("seller@store", "buyer@home", '''
OFFER id="off-002" TO "seller@store" {
    give: {money: 47500},
    want: {item: "SmartTV", brand: "LG"},
    expires: "2026-03-01T23:59"
};
''')
        for r in resp.responses:
            print(f"  {r}")

        # ── Step 7: Seller accepts ──────────────────────
        print("\n── Step 7: Seller accepts (via HTTP) ──")
        resp = client.send_to("seller@store", "seller@store", '''
ACCEPT "off-002";
''')
        for r in resp.responses:
            print(f"  {r}")

        # ── Step 8: Both commit via their own endpoints ─
        print("\n── Step 8: Both sides commit — Dharma (via HTTP) ──")
        resp = client.send_to("buyer@home", "buyer@home", '''
COMMIT pay(amount=47500, to="seller@store") BY "2026-03-02";
ACT transfer(amount=47500, to="seller@store");
''')
        for r in resp.responses:
            print(f"  {r}")

        resp = client.send_to("seller@store", "seller@store", '''
COMMIT deliver(item="SmartTV", brand="LG", to="buyer@home") BY "2026-03-05";
ACT ship(item="SmartTV", method="express", to="buyer@home");
''')
        for r in resp.responses:
            print(f"  {r}")

        # ── Final: Check states via HTTP ────────────────
        print("\n" + "═" * 60)
        print("  Final Agent States (fetched via HTTP /status)")
        print("═" * 60)

        buyer_status = client.get_status("http://127.0.0.1:8100")
        seller_status = client.get_status("http://127.0.0.1:8101")

        print(f"\n  Buyer  ({buyer_status['agent']['agent_id']}):")
        for k in ["beliefs", "goals", "offers", "commitments", "actions", "log_entries"]:
            print(f"    {k}: {buyer_status['agent'][k]}")

        print(f"\n  Seller ({seller_status['agent']['agent_id']}):")
        for k in ["beliefs", "goals", "offers", "commitments", "actions", "log_entries"]:
            print(f"    {k}: {seller_status['agent'][k]}")

        print(f"\n  Registry: {list(registry.to_dict().keys())}")
        print("\n  ✓ Networked transaction complete. Dharma fulfilled over HTTP.\n")

    finally:
        buyer_server.stop()
        seller_server.stop()


# ── v0.3: Crypto commands ───────────────────────────────


def cmd_keygen(args):
    """Generate a signing key pair for an agent."""
    from .keystore import KeyStore
    from .crypto import get_backend

    store = KeyStore()
    try:
        keypair = store.generate(args.agent_id, force=args.force)
        print(f"\n  🔑 Key generated for '{args.agent_id}'")
        print(f"     Algorithm:   {keypair.algorithm}")
        print(f"     Fingerprint: {keypair.fingerprint}")
        print(f"     Public key:  {keypair.public_key_hex[:32]}...")
        print(f"     Backend:     {get_backend()}")
        print(f"     Stored at:   {store._key_path(args.agent_id)}\n")
    except FileExistsError as e:
        print(f"  ⚠  {e}", file=sys.stderr)
        print(f"     Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)


def cmd_keys(_args):
    """List all stored agent keys."""
    from .keystore import KeyStore
    from .crypto import get_backend

    store = KeyStore()
    keys = store.list_keys()

    print(f"\n  🔑 SUTRA Key Store (backend: {get_backend()})")
    print(f"{'─' * 60}")

    if not keys:
        print("  No keys found. Use 'sutra keygen <agent_id>' to generate one.")
    else:
        for k in keys:
            print(f"  Agent:       {k['agent_id']}")
            print(f"  Algorithm:   {k['algorithm']}")
            print(f"  Fingerprint: {k['fingerprint']}")
            print(f"  Public key:  {k['public_key'][:32]}...")
            print(f"  {'─' * 56}")

    print()


def cmd_verify(args):
    """Verify all signed commits for an agent (local agent state)."""
    from .keystore import KeyStore
    from .crypto import verify, SutraSignature, commitment_content, offer_content

    store = KeyStore()
    keypair = store.load(args.agent_id)
    if keypair is None:
        print(f"  ⚠  No key found for '{args.agent_id}'", file=sys.stderr)
        sys.exit(1)

    # Run a file to build agent state, then verify
    if not args.file:
        print(f"  Usage: sutra verify <agent_id> <file.sutra>", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.file):
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    agent = Agent(args.agent_id, keypair=keypair)
    with open(args.file, "r", encoding="utf-8") as f:
        source = f.read()
    run_source(source, args.agent_id, agent)

    print(f"\n  🔍 Verifying signed artifacts for '{args.agent_id}'")
    print(f"{'─' * 60}")

    total, valid, invalid = 0, 0, 0

    for i, commit in enumerate(agent.commit_ledger):
        if commit.signature:
            total += 1
            sig = SutraSignature.from_dict(commit.signature)
            content = commitment_content(
                commit.predicate, commit.args, args.agent_id, commit.deadline
            )
            ok = verify(sig, content)
            status = "✅ VALID" if ok else "❌ INVALID"
            if ok:
                valid += 1
            else:
                invalid += 1
            print(f"  COMMIT[{i}] {commit.predicate}: {status}")

    for oid, offer in agent.offer_ledger.items():
        if offer.signature:
            total += 1
            sig = SutraSignature.from_dict(offer.signature)
            content = offer_content(
                offer.offer_id, offer.from_agent, offer.to_agent, offer.fields
            )
            ok = verify(sig, content)
            status = "✅ VALID" if ok else "❌ INVALID"
            if ok:
                valid += 1
            else:
                invalid += 1
            print(f"  OFFER[{oid}]: {status}")

    print(f"{'─' * 60}")
    print(f"  Total: {total}  Valid: {valid}  Invalid: {invalid}")
    if invalid == 0 and total > 0:
        print(f"  ✓ All signatures verified. Dharma is intact.\n")
    elif total == 0:
        print(f"  No signed artifacts found.\n")
    else:
        print(f"  ⚠  {invalid} signature(s) failed verification!\n")
        sys.exit(1)


def cmd_signed_demo(_args):
    """Run a full buyer-seller negotiation with cryptographic signing."""
    from .server import SutraServer
    from .client import SutraClient
    from .registry import AgentRegistry
    from .keystore import KeyStore
    from .crypto import (
        verify, SutraSignature, commitment_content, offer_content, get_backend,
    )

    print("\n" + "═" * 60)
    print("  🕉  SUTRA v0.3 — Signed Agent Commerce Demo")
    print(f"  Crypto backend: {get_backend()}")
    print("═" * 60)

    registry = AgentRegistry()
    keystore = KeyStore()

    # Generate keys for both agents
    buyer_keys = keystore.get_or_create("buyer@home")
    seller_keys = keystore.get_or_create("seller@store")

    buyer = Agent("buyer@home", keypair=buyer_keys)
    seller = Agent("seller@store", keypair=seller_keys)

    print(f"\n  🔑 Buyer  key: {buyer_keys.fingerprint} ({buyer_keys.algorithm})")
    print(f"  🔑 Seller key: {seller_keys.fingerprint} ({seller_keys.algorithm})")

    buyer_server = SutraServer(buyer, port=8200, registry=registry)
    seller_server = SutraServer(seller, port=8201, registry=registry)

    buyer_server.start(blocking=False)
    seller_server.start(blocking=False)
    time.sleep(0.3)

    registry.register("buyer@home", "http://127.0.0.1:8200")
    registry.register("seller@store", "http://127.0.0.1:8201")

    client = SutraClient(registry=registry, timeout=5.0)

    try:
        # ── Step 1: Seller publishes facts (no signature needed) ──
        print("\n── Step 1: Seller publishes catalog ──")
        resp = client.send_to("seller@store", "admin", '''
FACT available(item="SmartTV", brand="LG", price=48000, stock=5);
''')
        for r in resp.responses:
            print(f"  {r}")

        # ── Step 2: Buyer makes signed offer ──
        print("\n── Step 2: Buyer makes SIGNED offer ──")
        resp = client.send_to("buyer@home", "buyer@home", '''
OFFER id="signed-001" TO "seller@store" {
    give: {money: 47000},
    want: {item: "SmartTV", brand: "LG"}
};
''')
        for r in resp.responses:
            print(f"  {r}")

        # ── Step 3: Seller rejects ──
        print("\n── Step 3: Seller rejects ──")
        resp = client.send_to("seller@store", "seller@store", '''
REJECT "signed-001" REASON "price_below_threshold";
''')
        for r in resp.responses:
            print(f"  {r}")

        # ── Step 4: Buyer counter-offers (signed) ──
        print("\n── Step 4: Buyer counter-offers (signed) ──")
        resp = client.send_to("buyer@home", "buyer@home", '''
OFFER id="signed-002" TO "seller@store" {
    give: {money: 47800},
    want: {item: "SmartTV", brand: "LG"}
};
''')
        for r in resp.responses:
            print(f"  {r}")

        # ── Step 5: Seller accepts ──
        print("\n── Step 5: Seller accepts ──")
        # Register buyer's offer in seller's ledger for acceptance
        seller.add_offer("signed-002", "buyer@home", "seller@store",
                         {"give": {"money": 47800}, "want": {"item": "SmartTV", "brand": "LG"}})
        resp = client.send_to("seller@store", "seller@store", '''
ACCEPT "signed-002";
''')
        for r in resp.responses:
            print(f"  {r}")

        # ── Step 6: Both COMMIT with cryptographic signatures ──
        print("\n── Step 6: SIGNED COMMITs (Dharma — cryptographically bound) ──")
        resp = client.send_to("buyer@home", "buyer@home", '''
COMMIT pay(amount=47800, to="seller@store") BY "2026-03-02";
ACT transfer(amount=47800, to="seller@store");
''')
        for r in resp.responses:
            print(f"  {r}")

        resp = client.send_to("seller@store", "seller@store", '''
COMMIT deliver(item="SmartTV", brand="LG", to="buyer@home") BY "2026-03-05";
ACT ship(item="SmartTV", method="express", to="buyer@home");
''')
        for r in resp.responses:
            print(f"  {r}")

        # ── Step 7: Verify all signatures ──
        print("\n" + "═" * 60)
        print("  Signature Verification")
        print("═" * 60)

        # Verify buyer's commit
        for i, commit in enumerate(buyer.commit_ledger):
            if commit.signature:
                sig = SutraSignature.from_dict(commit.signature)
                content = commitment_content(
                    commit.predicate, commit.args, buyer.agent_id, commit.deadline
                )
                ok = verify(sig, content)
                status = "✅ VALID" if ok else "❌ INVALID"
                print(f"  Buyer  COMMIT[{i}] {commit.predicate}: {status}")

        # Verify seller's commit
        for i, commit in enumerate(seller.commit_ledger):
            if commit.signature:
                sig = SutraSignature.from_dict(commit.signature)
                content = commitment_content(
                    commit.predicate, commit.args, seller.agent_id, commit.deadline
                )
                ok = verify(sig, content)
                status = "✅ VALID" if ok else "❌ INVALID"
                print(f"  Seller COMMIT[{i}] {commit.predicate}: {status}")

        # Verify buyer's offers
        for oid, offer in buyer.offer_ledger.items():
            if offer.signature:
                sig = SutraSignature.from_dict(offer.signature)
                content = offer_content(
                    offer.offer_id, offer.from_agent, offer.to_agent, offer.fields
                )
                ok = verify(sig, content)
                status = "✅ VALID" if ok else "❌ INVALID"
                print(f"  Buyer  OFFER[{oid}]: {status}")

        # ── Fetch public keys via HTTP ──
        print("\n── Public Keys (via HTTP /pubkey) ──")
        buyer_pk = client.get_pubkey("http://127.0.0.1:8200")
        seller_pk = client.get_pubkey("http://127.0.0.1:8201")
        print(f"  Buyer:  {buyer_pk.get('fingerprint', 'N/A')} ({buyer_pk.get('algorithm', '?')})")
        print(f"  Seller: {seller_pk.get('fingerprint', 'N/A')} ({seller_pk.get('algorithm', '?')})")

        # ── Final state ──
        print("\n" + "═" * 60)
        print("  Final Agent States")
        print("═" * 60)
        print(buyer.state_summary())
        print()
        print(seller.state_summary())
        print("\n  ✓ Signed transaction complete. Dharma cryptographically sealed.\n")

    finally:
        buyer_server.stop()
        seller_server.stop()


def cmd_runtime_demo(_args):
    """Run a multi-agent runtime demo — agents talking in one process."""
    from .runtime import SutraRuntime

    print("\n" + "═" * 60)
    print("  🕉  SUTRA v0.4 — Multi-Agent Runtime Demo")
    print("  Agents talking in a single process — no HTTP needed")
    print("═" * 60)

    # ── Create runtime and spawn agents ──────────────────
    rt = SutraRuntime()
    rt.spawn("buyer@home")
    rt.spawn("seller@store")
    rt.spawn("logistics@hub")

    print(f"\n  ✓ Spawned: {', '.join(rt.list_agents())}")

    # ── Register seller's auto-evaluation logic ─────────
    def seller_evaluator(agent, offer_id, from_agent, fields):
        """Accept if price >= 47500, reject otherwise."""
        give = fields.get("give", {})
        price = give.get("money", 0)
        if price >= 47500:
            return "accept"
        return f"reject:price_below_47500_offered_{int(price)}"

    rt.set_offer_evaluator("seller@store", seller_evaluator)
    print("  ✓ Seller auto-evaluator: accept if price ≥ ₹47,500")

    # ── Step 1: Seller loads product catalog ─────────────
    print("\n── Step 1: Seller loads product catalog ──")
    msg = rt.send("seller@store", "seller@store", '''
FACT available(item="SmartTV", brand="Samsung", price=55000, stock=10);
FACT available(item="SmartTV", brand="LG", price=48000, stock=5);
FACT shipping(method="express", days=3, cost=500);
''')
    for r in msg.responses:
        print(f"  {r}")

    # ── Step 2: Buyer declares intent ────────────────────
    print("\n── Step 2: Buyer declares purchase intent ──")
    msg = rt.send("buyer@home", "buyer@home", '''
INTENT buy(item="SmartTV", max_price=50000, deadline="2026-03-01");
''')
    for r in msg.responses:
        print(f"  {r}")

    # ── Step 3: Buyer queries seller → AUTO-RESPONSE! ────
    print("\n── Step 3: Buyer queries seller → AUTO-RESPONSE! ──")
    msg, reply = rt.ask("buyer@home", "seller@store", '''
QUERY available(item="SmartTV") FROM "seller@store";
''')
    print(f"  Query executed on seller:")
    for r in msg.responses:
        print(f"    {r}")
    if reply:
        print(f"  ↩ Auto-response (seller → buyer):")
        for r in reply.responses:
            print(f"    {r}")
    else:
        print(f"  ↩ No matching facts")

    # ── Step 4: Buyer offers ₹46,000 → auto-REJECTED! ───
    print("\n── Step 4: Buyer offers ₹46,000 → auto-evaluated ──")
    msg, reply = rt.ask("buyer@home", "seller@store", '''
OFFER id="deal-001" TO "seller@store" {
    give: {money: 46000},
    want: {item: "SmartTV", brand: "LG"}
};
''')
    for r in msg.responses:
        print(f"  {r}")
    if reply:
        print(f"  ↩ Seller auto-response:")
        for r in reply.responses:
            print(f"    {r}")

    # ── Step 5: Buyer counter-offers ₹48,000 → ACCEPTED! ─
    print("\n── Step 5: Buyer counter-offers ₹48,000 → auto-evaluated ──")
    msg, reply = rt.ask("buyer@home", "seller@store", '''
OFFER id="deal-002" TO "seller@store" {
    give: {money: 48000},
    want: {item: "SmartTV", brand: "LG"}
};
''')
    for r in msg.responses:
        print(f"  {r}")
    if reply:
        print(f"  ↩ Seller auto-response:")
        for r in reply.responses:
            print(f"    {r}")

    # ── Step 6: Both commit (Dharma) ─────────────────────
    print("\n── Step 6: Both sides COMMIT (Dharma — binding) ──")
    msg = rt.send("buyer@home", "buyer@home", '''
COMMIT pay(amount=48000, to="seller@store") BY "2026-03-02";
''')
    for r in msg.responses:
        print(f"  {r}")

    msg = rt.send("seller@store", "seller@store", '''
COMMIT deliver(item="SmartTV", brand="LG", to="buyer@home") BY "2026-03-05";
''')
    for r in msg.responses:
        print(f"  {r}")

    # ── Step 7: Seller notifies logistics ────────────────
    print("\n── Step 7: Seller notifies logistics agent ──")
    msg = rt.send("seller@store", "logistics@hub", '''
ACT ship(item="SmartTV", brand="LG", to="buyer@home", method="express");
''')
    for r in msg.responses:
        print(f"  {r}")

    # ── Show conversation transcript ─────────────────────
    rt.print_transcript()

    # ── Final agent states ───────────────────────────────
    print("\n" + "═" * 60)
    print("  Final Agent States")
    print("═" * 60)
    rt.print_agents()

    print("  ✓ Multi-agent runtime demo complete.")
    print("  ✓ Agents communicated using SUTRA — queries auto-answered, offers auto-evaluated.\n")


def main():
    parser = argparse.ArgumentParser(
        prog="sutra",
        description="SUTRA v0.4 — Agent-to-Agent Communication Language",
    )
    sub = parser.add_subparsers(dest="command")

    # run command
    run_p = sub.add_parser("run", help="Execute a .sutra file")
    run_p.add_argument("file", help="Path to .sutra file")
    run_p.add_argument("--agent", default="default-agent", help="Agent identifier")
    run_p.add_argument("--sign", action="store_true", help="Sign COMMITs/OFFERs with agent key")

    # parse command
    parse_p = sub.add_parser("parse", help="Parse a .sutra file and dump AST")
    parse_p.add_argument("file", help="Path to .sutra file")

    # demo command
    sub.add_parser("demo", help="Run buyer/seller negotiation demo (local)")

    # serve command (v0.2)
    serve_p = sub.add_parser("serve", help="Start HTTP agent server")
    serve_p.add_argument("--agent", required=True, help="Agent identifier (e.g. seller@store)")
    serve_p.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    serve_p.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    serve_p.add_argument("--facts", default=None, help="Pre-load facts from a .sutra file")
    serve_p.add_argument("--sign", action="store_true", help="Enable cryptographic signing")

    # send command (v0.2)
    send_p = sub.add_parser("send", help="Send a .sutra message to a remote agent")
    send_p.add_argument("url", help="Target agent URL (e.g. http://localhost:8001)")
    send_p.add_argument("file", help="Path to .sutra file to send")
    send_p.add_argument("--from", dest="from_agent", default="cli-agent", help="Sender agent ID")
    send_p.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds")

    # network-demo command (v0.2)
    sub.add_parser("network-demo", help="Run networked buyer/seller demo over HTTP")

    # keygen command (v0.3)
    keygen_p = sub.add_parser("keygen", help="Generate a signing key pair for an agent")
    keygen_p.add_argument("agent_id", help="Agent identifier (e.g. seller@store)")
    keygen_p.add_argument("--force", action="store_true", help="Overwrite existing key")

    # keys command (v0.3)
    sub.add_parser("keys", help="List all stored signing keys")

    # verify command (v0.3)
    verify_p = sub.add_parser("verify", help="Verify signed commits in a .sutra file")
    verify_p.add_argument("agent_id", help="Agent identifier")
    verify_p.add_argument("file", nargs="?", help="Path to .sutra file")

    # signed-demo command (v0.3)
    sub.add_parser("signed-demo", help="Run buyer/seller demo with cryptographic signing")

    # runtime-demo command (v0.4)
    sub.add_parser("runtime-demo", help="Run multi-agent runtime demo (agents talking in-process)")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "parse":
        cmd_parse(args)
    elif args.command == "demo":
        cmd_demo(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "send":
        cmd_send(args)
    elif args.command == "network-demo":
        cmd_network_demo(args)
    elif args.command == "keygen":
        cmd_keygen(args)
    elif args.command == "keys":
        cmd_keys(args)
    elif args.command == "verify":
        cmd_verify(args)
    elif args.command == "signed-demo":
        cmd_signed_demo(args)
    elif args.command == "runtime-demo":
        cmd_runtime_demo(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
