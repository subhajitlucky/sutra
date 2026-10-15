# 🕉 SUTRA — Structured Universal Transaction & Reasoning Architecture

**A minimal, deterministic agent-to-agent communication language.**

SUTRA is a formal language designed for autonomous AI agents to communicate, negotiate, and commit to agreements. It combines English-readable syntax with Dharmic ontological roots — making it both globally accessible and culturally unique.

> *Designed for machines. Readable by humans. Rooted in Dharma.*

---

## Token-efficiency research (2026)

The protocol has been *measured*, not assumed. A dedicated lab
([`experiments/token-cost/`](experiments/token-cost/README.md)) tests encodings
with production tokenizers and real models. Every claim is decoder-verified;
every failure is published.

- **6.1 → 2.8 tokens per message**, via mechanisms read out of the Panini
  literature: case-slot arguments, session dictionaries, carried-over ellipsis
  (anuvrtti), pratyahara-style ranges, and fixed-width "meter" payloads where
  the negotiation template is implied by order. A complete OFFER becomes
  `o48000am`.
- **~24× cheaper than deployed JSON-RPC/MCP envelopes** in template sessions
  (N≥500), ~7× vs lean JSON, ~3.4× vs English.
- **Cross-model comprehension verified**: the compact wire form reads and
  writes at 12/12 on gpt-6-luna and deepseek-v4.1-flash; the meter form is
  stronger on deepseek (6/6 read). Raw prompts and outputs are in the round-7
  logs.
- The readable syntax's mandatory `;` was the single largest emission failure
  in model testing; the compact form removes terminators entirely (planned
  parser relaxation, v0.7).

Negatives are published too: binary wires lose to tuned text; katapayadi
numbers lose to plain digits; vocabulary etymology buys nothing against BPE.

## Why SUTRA?

Today's AI agents communicate via unstructured English or rigid JSON APIs. Neither is ideal:

- **English** is ambiguous, context-dependent, and impossible to formally verify
- **JSON protocols** are verbose, lack semantic meaning, and can't express intent

SUTRA sits in between — a **minimal formal language** where every statement has precise semantics, is deterministically executable, and is auditable.

| Feature | English | JSON Protocol | SUTRA |
|---------|---------|---------------|-------|
| Human-readable | ✅ | ❌ | ✅ |
| Machine-executable | ❌ | ✅ | ✅ |
| Deterministic | ❌ | ✅ | ✅ |
| Expresses intent | ✅ | ❌ | ✅ |
| Negotiation-native | ❌ | Partial | ✅ |
| Auditable | ❌ | Partial | ✅ |

---

## Core Keywords (8 Primitives)

Inspired by Dharmic ontology:

| Keyword  | Sanskrit Root | Meaning              |
|----------|---------------|----------------------|
| `INTENT` | Sankalpa      | Declared intention   |
| `FACT`   | Pramana       | Verified knowledge   |
| `QUERY`  | Prashna       | Request for info     |
| `OFFER`  | Samvida       | Proposed agreement   |
| `ACCEPT` | Svikrti       | Accept an offer      |
| `REJECT` | Nirakrti      | Reject an offer      |
| `COMMIT` | Dharma        | Binding obligation   |
| `ACT`    | Kriya         | Execute an action    |

---

## Quick Example

```sutra
#sutra "v0.1"
#from "buyer@home"
#to "seller@store"

// Declare intent (Sankalpa)
INTENT buy(item="SmartTV", max_price=50000);

// Query seller (Prashna)
QUERY availability(item="SmartTV") FROM "seller@store";

// Make an offer (Samvida)
OFFER id="off-001" TO "seller@store" {
    give: {money: 48000},
    want: {item: "SmartTV", brand: "Samsung"}
};

// After negotiation — commit (Dharma)
ACCEPT "off-001";
COMMIT pay(amount=48000, to="seller@store") BY "2026-03-01";
ACT transfer(amount=48000, to="seller@store");
```

---

## Installation & Usage

```bash
# Clone the repo
git clone https://github.com/subhajitlucky/sutra.git
cd sutra

# Run a .sutra file
python -m sutra run examples/buyer.sutra

# Parse and inspect AST
python -m sutra parse examples/buyer.sutra

# Run the built-in buyer/seller demo (local)
python -m sutra demo

# ── v0.2: Network Transport ──

# Start an agent as an HTTP server
python -m sutra serve --agent "seller@store" --port 8001

# (Optional) pre-load facts on startup
python -m sutra serve --agent "seller@store" --port 8001 --facts examples/seller.sutra

# Send a .sutra message to a remote agent
python -m sutra send http://localhost:8001 examples/buyer.sutra --from "buyer@home"

# Run the full networked multi-agent demo
python -m sutra network-demo
```

No dependencies required — pure Python 3.11+.

---

## Architecture

```
Source (.sutra)
    │
    ▼
[ Lexer ]  →  Token Stream
    │
    ▼
[ Parser ]  →  Abstract Syntax Tree (AST)
    │
    ▼
[ Interpreter ]  →  Agent State Mutations
    │
    ▼
[ Agent Runtime ]
    ├── BeliefBase    (Pramana)
    ├── GoalSet       (Sankalpa)
    ├── OfferLedger   (Samvida)
    ├── CommitLedger  (Dharma)
    ├── ActionQueue   (Kriya)
    └── MessageLog    (Audit trail)

v0.2 Transport Layer:
┌──────────────┐  POST /sutra  ┌──────────────┐
│  Agent A     │──────────────►│  Agent B     │
│  (Client)    │  JSON envelope│  (Server)    │
│              │◄──────────────│              │
│  SutraClient │  200 + results│  SutraServer │
└──────────────┘               └──────────────┘
        │                              │
        └──── AgentRegistry ───────────┘
              (ID → URL mapping)
```

---

## Agent State Model

Every SUTRA agent maintains:

| Store          | Sanskrit  | Purpose                |
|----------------|-----------|------------------------|
| `belief_base`  | Pramana   | Known facts            |
| `goal_set`     | Sankalpa  | Active intentions      |
| `offer_ledger` | Samvida   | Open/closed offers     |
| `commit_ledger`| Dharma    | Binding obligations    |
| `action_queue` | Kriya     | Pending actions        |

---

## Design Principles

1. **Minimal** — 8 keywords, <30 grammar rules
2. **Deterministic** — same input + state → same output, always
3. **Declarative** — no loops, no general programming
4. **Transactional** — all mutations isolated per message
5. **Transport-agnostic** — works over HTTP, WebSocket, TCP, files
6. **Auditable** — every action is logged with timestamp

---

## Project Structure

```
sutra/
├── sutra/
│   ├── __init__.py       # Package init
│   ├── __main__.py       # python -m sutra
│   ├── tokens.py         # Token types and keywords
│   ├── lexer.py          # Tokenizer
│   ├── ast_nodes.py      # AST node definitions
│   ├── parser.py         # Recursive descent parser
│   ├── agent.py          # Agent state model
│   ├── interpreter.py    # AST executor
│   ├── cli.py            # CLI entry point
│   ├── server.py         # v0.2 — HTTP transport server
│   ├── client.py         # v0.2 — HTTP transport client
│   ├── registry.py       # v0.2 — Agent registry (ID→URL)
│   ├── crypto.py         # v0.3 — Ed25519 signing & verification
│   ├── keystore.py       # v0.3 — Persistent key storage
│   ├── message.py        # v0.4 — Message envelope (routing metadata)
│   ├── runtime.py        # v0.4 — Multi-agent runtime + Conversation
│   ├── sandbox.py        # v0.5 — Sandboxed interpreter
│   ├── security.py       # v0.6 — Replay, encryption, auth, ordering
│   ├── persistence.py    # v0.6 — State persistence (atomic writes)
│   └── transaction.py    # v0.6 — Transaction rollback (snapshots)
├── wasm/
│   ├── sutra.js          # v0.5 — Full JavaScript interpreter
│   ├── index.html        # v0.5 — Browser playground
│   └── package.json      # v0.5 — npm package config
├── spec/
│   ├── SUTRA_SPEC.md     # Full language specification
│   └── GRAMMAR.ebnf      # Formal grammar
├── examples/
│   ├── buyer.sutra       # Buyer agent example
│   ├── seller.sutra      # Seller agent example
│   ├── finalize.sutra    # Deal finalization
│   └── knowledge.sutra   # Knowledge sharing
├── SKILL.md              # Skills.sh compatible skill file
├── pyproject.toml        # Python package config
└── README.md             # This file
```

---

## HTTP Transport (v0.2)

SUTRA agents can communicate over HTTP using the built-in transport layer. Zero external dependencies — uses Python's `http.server` and `urllib`.

### Protocol

Agents expose a `POST /sutra` endpoint that accepts JSON-wrapped SUTRA messages:

```
POST /sutra HTTP/1.1
Content-Type: application/json

{
    "from": "buyer@home",
    "body": "QUERY availability(item=\"SmartTV\") FROM \"seller@store\";"
}
```

Response:
```json
{
    "status": "ok",
    "agent": "seller@store",
    "responses": ["[QUERY RESULT] FACT available(item='SmartTV', ...)"]
}
```

### Additional Endpoints

| Method | Path        | Purpose                    |
|--------|-------------|----------------------------|
| GET    | `/health`   | Health check               |
| GET    | `/status`   | Agent state summary        |
| GET    | `/registry` | List known agents          |
| POST   | `/register` | Register a remote agent    |

### Agent Registry

Agents find each other via an `AgentRegistry` — a simple ID → URL lookup:

```python
from sutra.registry import AgentRegistry
from sutra.client import SutraClient

registry = AgentRegistry()
registry.register("seller@store", "http://localhost:8001")

client = SutraClient(registry=registry)
response = client.send_to("seller@store", from_agent="buyer@home",
    body='QUERY availability(item="SmartTV") FROM "buyer@home";')
```

### Programmatic Usage

```python
from sutra.agent import Agent
from sutra.server import SutraServer
from sutra.client import SutraClient

# Start seller agent
seller = Agent("seller@store")
server = SutraServer(seller, port=8001)
server.start()  # background thread

# Send message from buyer
client = SutraClient()
resp = client.send("http://localhost:8001", "buyer@home",
    'OFFER id="deal-1" TO "seller@store" { give: {money: 47500}, want: {item: "SmartTV"} };')
print(resp.responses)

server.stop()
```

---

## Cryptographic Signatures (v0.3)

COMMIT and OFFER statements are now **cryptographically signed** using Ed25519 digital signatures. This makes agent commitments tamper-proof and independently verifiable.

### Key Management

```bash
# Generate a signing key for an agent
python -m sutra keygen "seller@store"

# List all stored keys
python -m sutra keys

# Run a script with signing enabled
python -m sutra run examples/finalize.sutra --agent "buyer@home" --sign

# Verify signatures in a file
python -m sutra verify "buyer@home" examples/finalize.sutra

# Run the full signed demo
python -m sutra signed-demo
```

### How It Works

1. Each agent generates an **Ed25519 key pair** (stored in `~/.sutra/keys/`)
2. When an agent executes a COMMIT or OFFER, the content is:
   - Canonicalized to JSON (sorted keys, no whitespace)
   - SHA-256 hashed
   - Signed with the agent's private key
3. The signature is attached to the Commitment/Offer object
4. Any agent can verify the signature using the signer's **public key**

### Programmatic Usage

```python
from sutra.crypto import generate_keypair, sign, verify, commitment_content
from sutra.agent import Agent

# Generate keys
keypair = generate_keypair("buyer@home")

# Create signed agent
agent = Agent("buyer@home", keypair=keypair)

# Sign a commitment manually
content = commitment_content("pay", {"amount": 47500}, "buyer@home", "2026-03-02")
signature = sign(keypair, content)
print(f"Signed: {signature}")

# Verify
assert verify(signature, content) == True
```

### Public Key Exchange

Agents expose their public keys via `GET /pubkey`:
```json
{
    "agent_id": "seller@store",
    "has_keypair": true,
    "algorithm": "ed25519",
    "public_key": "a1b2c3...",
    "fingerprint": "e4f5a6b7c8d9e0f1"
}
```

### Signed Output

When signing is enabled, COMMIT and OFFER responses show the signature:
```
[COMMIT] pay(amount=47500, to='seller@store') BY 2026-03-02 🔏 ed25519:a1b2c3d4e5f6...
[OFFER] id='deal-001' → seller@store 🔏 ed25519:f6e5d4c3b2a1...
```

---

## Dharmic Roots — Not Decoration

SUTRA's Sanskrit-inspired keywords aren't cosmetic. They map to precise ontological concepts from Indian philosophy:

- **Sankalpa** (INTENT) — a resolved will, not a wish
- **Pramana** (FACT) — valid means of knowledge, verified truth
- **Samvida** (OFFER) — a mutual understanding, proposal for agreement
- **Dharma** (COMMIT) — duty, binding moral obligation
- **Kriya** (ACT) — action with consequence (Karma)

This gives SUTRA a unique philosophical foundation that distinguishes it from generic protocol designs.

---

## Multi-Agent Runtime (v0.4)

Run multiple agents **in a single process** with direct messaging, auto-response, and conversation tracking. No HTTP overhead — agents talk through shared memory.

### Can Agents Talk Normally?

**Yes.** The v0.4 runtime enables natural agent communication:

- **QUERY → auto-response:** Agent A asks Agent B a question, Agent B automatically responds with matching facts from its knowledge base
- **OFFER → auto-evaluation:** Agents can register logic to auto-ACCEPT/REJECT incoming offers based on custom rules
- **Bilateral state sync:** When Agent A makes an offer to Agent B, both agents have it in their ledger
- **Full transcript:** Every message is recorded with threading

```bash
# See agents talk
python -m sutra runtime-demo
```

### Programmatic Usage

```python
from sutra.runtime import SutraRuntime

# Create runtime and spawn agents
rt = SutraRuntime()
rt.spawn("buyer@home")
rt.spawn("seller@store")

# Load seller's knowledge
rt.send("seller@store", "seller@store",
    'FACT available(item="SmartTV", price=48000);')

# Buyer queries seller → auto gets matching FACTs back!
msg, reply = rt.ask("buyer@home", "seller@store",
    'QUERY available(item="SmartTV") FROM "seller@store";')
# reply.responses → ["[FACT] available(item='SmartTV', price=48000.0)"]

# Register offer evaluation logic
def evaluator(agent, offer_id, from_agent, fields):
    price = fields.get("give", {}).get("money", 0)
    return "accept" if price >= 47500 else "reject:price_too_low"

rt.set_offer_evaluator("seller@store", evaluator)

# Buyer sends offer → auto-evaluated!
msg, reply = rt.ask("buyer@home", "seller@store", '''
OFFER id="deal-001" TO "seller@store" {
    give: {money: 48000},
    want: {item: "SmartTV"}
};
''')
# reply.responses → ["[ACCEPT] Offer 'deal-001' accepted"]

# View full conversation
rt.print_transcript()
```

### Conversation API

For multi-turn dialogs between specific agents:

```python
conv = rt.converse("buyer@home", "seller@store")

# Broadcast to all in conversation
conv.say("seller@store", 'FACT available(item="SmartTV", price=48000);')

# Directed message
conv.tell("buyer@home", "seller@store", 'INTENT buy(item="SmartTV");')

# Request-response
msg, reply = conv.ask("buyer@home", "seller@store",
    'QUERY available(item="SmartTV") FROM "seller@store";')

conv.print_transcript()
```

### Key Methods

| Method | Description |
|--------|-------------|
| `rt.spawn(id)` | Create agent in runtime |
| `rt.send(from, to, body)` | One-way message (execute on target) |
| `rt.ask(from, to, body)` | Request-response with auto-reply |
| `rt.broadcast(from, body)` | Send to all other agents |
| `rt.converse(*ids)` | Start tracked conversation |
| `rt.set_offer_evaluator(id, fn)` | Register offer logic |
| `rt.print_transcript()` | Show all messages |

---

## Sandboxed Interpreter (v0.5)

SUTRA v0.5 introduces **sandboxed execution** — run untrusted SUTRA code safely with capability-based security and resource limits. Plus a **complete JavaScript interpreter** that runs in browsers.

### Python Sandbox

```python
from sutra.sandbox import SutraSandbox, SandboxLimits

# Read-only sandbox — only FACT and QUERY allowed
sandbox = SutraSandbox(
    agent_id="untrusted",
    allowed_keywords={"FACT", "QUERY"},
)

result = sandbox.execute('''
FACT known(topic="SUTRA", version=5);
QUERY known(topic="SUTRA") FROM "self";
COMMIT deliver(item="blocked") BY "2025-01-01";
''')

print(result.success)       # False — COMMIT was blocked
print(result.violations)    # ["Keyword 'COMMIT' not allowed in this sandbox"]
print(result.responses)     # Only FACT and QUERY responses
print(result.stats)         # {statements_total: 3, statements_executed: 2, ...}
```

### Sandbox Features

| Feature | Description |
|---------|-------------|
| **Capability restrictions** | Allow/deny specific keywords per sandbox |
| **Resource limits** | Max statements, beliefs, offers, commits, time |
| **Source size limits** | Prevent excessively large scripts (default: 64KB) |
| **Audit trail** | Full log of allowed/blocked/error events |
| **Deny-lists** | Block specific keywords: `denied_keywords={"COMMIT", "ACT"}` |
| **Safety report** | `sandbox.explain(source)` for human-readable audit |

### CLI Commands

```bash
python -m sutra sandbox-demo     # Run sandboxed interpreter demo
python -m sutra playground       # Open browser playground (http://localhost:8080)
```

### JavaScript / Browser Interpreter

A complete JavaScript port of the SUTRA interpreter lives in `wasm/sutra.js` — zero dependencies, runs in any browser or Node.js:

```javascript
const { SutraVM, SutraSandbox } = require("./wasm/sutra.js");

// Direct execution
const vm = new SutraVM("my-agent");
const result = vm.execute('FACT known(item="TV", price=50000);');
console.log(result);  // ["[FACT] known(item=\"TV\", price=50000)"]

// Sandboxed execution
const sandbox = new SutraSandbox({
    agentId: "untrusted",
    allowedKeywords: ["FACT", "QUERY"],
    maxStatements: 50,
});
const res = sandbox.execute('COMMIT steal(data="secret");');
console.log(res.violations);  // ["Keyword 'COMMIT' not allowed"]
```

### Browser Playground

Open `wasm/index.html` in any browser or run:

```bash
python -m sutra playground --port 8080
```

Features:
- Live SUTRA editor with syntax-aware output coloring
- 5 built-in examples (buyer, seller, knowledge, negotiation, sandbox)
- Sandboxed execution mode for untrusted code demos
- Agent state inspector
- Zero dependencies — pure HTML/JS, no build step

---

## Security Hardening (v0.6)

v0.6 addresses 9 infrastructure-level security gaps identified through systematic audit. All protections are opt-in via `hardened=True` mode for backward compatibility.

### Threat Mitigations

| Threat | Mitigation | Module |
|--------|-----------|--------|
| Replay attacks | Nonce-based deduplication (UUID4 + TTL) | `security.py` |
| Eavesdropping | AES-256-GCM encryption (HMAC-XOR-SHA256 fallback) | `security.py` |
| Unauthorized access | Bearer token auth (SHA-256 hashed storage) | `security.py` |
| Out-of-order messages | Per-pair monotonic sequence counters | `security.py` |
| State corruption | Transaction boundaries with snapshot rollback | `transaction.py` |
| State loss | Atomic persistence to disk (~/.sutra/state/) | `persistence.py` |
| Deadlocks | Circular wait detection in `ask()` | `runtime.py` |
| Resource exhaustion | OS-level RLIMIT (CPU, memory, files) | `sandbox.py` |
| Timeout hangs | Configurable `ask_timeout_s` + SIGALRM | `runtime.py` / `sandbox.py` |

### Hardened Runtime

```python
from sutra.runtime import SutraRuntime
from sutra.agent import Agent

# Enable all v0.6 protections
rt = SutraRuntime(hardened=True, ask_timeout_s=5.0)
rt.register(Agent("buyer"))
rt.register(Agent("seller"))

# Messages now carry nonces + sequence numbers automatically
msg, reply = rt.ask("buyer", "seller", 'QUERY item(name="phone");')
print(msg.nonce)     # UUID4 nonce for replay protection
print(msg.sequence)  # Monotonic sequence number
```

### Message Encryption

```python
from sutra.security import MessageEncryptor

enc = MessageEncryptor()
key = enc.generate_key()
enc.add_key("buyer", "seller", key)

ciphertext = enc.encrypt("buyer", "seller", 'OFFER buy(item="phone");')
plaintext = enc.decrypt("buyer", "seller", ciphertext)
```

### Transaction Rollback

```python
from sutra.transaction import SutraTransaction

tx = SutraTransaction(agent)
tx.begin()
try:
    # execute SUTRA statements...
    tx.commit()
except Exception:
    tx.rollback()  # restores agent to pre-transaction state
```

### State Persistence

```python
from sutra.persistence import StateStore

store = StateStore()
store.save(agent)               # atomic write to ~/.sutra/state/
loaded = store.load("agent-id") # full round-trip
```

### Demo

```bash
python -m sutra hardened-demo
```

---

## Roadmap

- [x] v0.1 — Core language spec + Python interpreter
- [x] v0.2 — HTTP transport layer (agents communicate over network)
- [x] v0.3 — Cryptographic signatures for COMMIT
- [x] v0.4 — Multi-agent runtime (agents talk in one process)
- [x] v0.5 — Sandboxed interpreter + JavaScript port + browser playground
- [x] v0.6 — Security hardening (replay, encryption, auth, transactions, persistence)
- [x] research — token-cost lab: measured encodings, cross-model comprehension, negatives published
- [ ] v0.7 — SUTRA-C wire format (spec + encoder/decoder in the package); optional `;` in the parser; package test suite + CI
- [ ] v1.0 — Formal verification + production runtime

---

## Contributing

SUTRA is open source under the MIT License.

Contributions welcome — especially:
- Implementations in other languages (Rust, Go, JS)
- Transport layer adapters
- IDE syntax highlighting
- Additional examples

---

## Origin

SUTRA was born from a cross-model AI experiment — designs solicited from Claude, Gemini, DeepSeek, Grok, and Kimi were analyzed, synthesized, and distilled into this minimal core language.

The result: a language that captures the **universal consensus** of what agents need to communicate, stripped to its essence.

---

**License:** MIT

**Author:** Subhajit

**Version:** 0.6.0 · research track active (`experiments/token-cost/`)
