---
name: sutra
description: "SUTRA — A minimal, deterministic agent-to-agent communication language with 8 Sanskrit-inspired keywords (INTENT, FACT, QUERY, OFFER, ACCEPT, REJECT, COMMIT, ACT). Use when agents need to negotiate deals, query knowledge, commit to obligations with Ed25519 cryptographic signatures, or coordinate multi-agent workflows. Includes HTTP transport, multi-agent runtime with auto-response, and conversation tracking. Alternative to unstructured English or rigid JSON APIs for agent communication."
---

# SUTRA — Agent-to-Agent Communication Language

SUTRA (Structured Universal Transaction & Reasoning Architecture) is a minimal, deterministic, formally-specified language that enables AI agents to communicate, negotiate, and commit to agreements. Sanskrit-inspired ontology, English-readable syntax.

## When to Use

Use SUTRA when you need agents to:
- **Negotiate** deals (offers, counter-offers, accept/reject)
- **Query** each other's knowledge bases with auto-responses
- **Commit** to binding obligations with cryptographic signatures
- **Coordinate** multi-agent workflows (e.g., buyer → seller → logistics)
- **Audit** every interaction via deterministic message transcripts

Use instead of unstructured English (ambiguous) or raw JSON APIs (no semantic meaning).

## Core Primitives (8 Keywords)

| Keyword   | Sanskrit   | What It Does                          |
|-----------|------------|---------------------------------------|
| `INTENT`  | Sankalpa   | Declare what the agent wants          |
| `FACT`    | Pramana    | Assert verified knowledge             |
| `QUERY`   | Prashna    | Ask another agent for information     |
| `OFFER`   | Samvida    | Propose a deal with terms             |
| `ACCEPT`  | Svikrti    | Accept an offer                       |
| `REJECT`  | Nirakrti   | Reject an offer (with reason)         |
| `COMMIT`  | Dharma     | Bind to an obligation (signed)        |
| `ACT`     | Kriya      | Execute an action                     |

## Quick Example — Agent Negotiation

```sutra
// Buyer agent declares intent
INTENT buy(item="SmartTV", max_price=50000);

// Buyer queries seller
QUERY available(item="SmartTV") FROM "seller@store";

// Buyer makes an offer
OFFER id="deal-001" TO "seller@store" {
    give: {money: 48000},
    want: {item: "SmartTV", brand: "LG"}
};

// After acceptance — buyer commits (cryptographically signed)
COMMIT pay(amount=48000, to="seller@store") BY "2026-03-02";

// Execute the payment
ACT transfer(amount=48000, to="seller@store");
```

## How Agents Use SUTRA

### 1. Generate SUTRA messages
When your agent wants to communicate, produce valid SUTRA:
```
OFFER id="task-001" TO "worker@gpu-cluster" {
    task: "train_model",
    dataset: "imagenet-1k",
    budget_usd: 50
};
```

### 2. Parse incoming messages
SUTRA has a formal grammar (8 keywords, under 30 rules). Any compliant parser can read it.

### 3. Auto-respond to queries
When Agent A sends `QUERY available(item="GPU") FROM "provider@cloud";`, the runtime auto-checks Agent B's knowledge base and responds with matching `FACT` statements.

### 4. Auto-evaluate offers
Register evaluation logic and the runtime auto-accepts/rejects:
```python
def my_evaluator(agent, offer_id, from_agent, fields):
    if fields["budget_usd"] >= 40:
        return "accept"
    return "reject:budget_too_low"
```

### 5. Sign commitments
COMMITs and OFFERs are Ed25519-signed — tamper-proof, verifiable:
```
[COMMIT] pay(amount=48000) BY 2026-03-02 🔏 ed25519:a1b2c3d4...
```

## Architecture

```
┌─────────────────────────────────────────┐
│           SUTRA v0.4 Stack              │
├─────────────────────────────────────────┤
│  Runtime    — Multi-agent process       │  ← v0.4: agents talk directly
│  Transport  — HTTP server/client        │  ← v0.2: agents talk over network
│  Crypto     — Ed25519 sign/verify       │  ← v0.3: tamper-proof commitments
│  Interpreter — AST executor             │  ← v0.1: deterministic execution
│  Parser     — Recursive descent         │  ← v0.1: formal grammar
│  Lexer      — Tokenizer                 │  ← v0.1: 8 keywords
│  Agent      — State model (BDI-lite)    │  ← v0.1: beliefs, goals, offers
└─────────────────────────────────────────┘
```

## Installation

```bash
pip install sutra-lang
# or clone:
git clone https://github.com/subhajitlucky/sutra.git
cd sutra && python -m sutra_lang demo
```

## Key Commands

```bash
python -m sutra_lang demo              # Local negotiation demo
python -m sutra_lang network-demo      # HTTP-based multi-agent demo
python -m sutra_lang signed-demo       # Cryptographically signed demo
python -m sutra_lang runtime-demo      # Multi-agent runtime demo (v0.4)
python -m sutra_lang run file.sutra    # Execute a .sutra file
python -m sutra_lang keygen "agent-id" # Generate signing keys
```

## Links

- **GitHub:** https://github.com/subhajitlucky/sutra
- **Spec:** `spec/SUTRA_SPEC.md` — full language specification
- **Grammar:** `spec/GRAMMAR.ebnf` — formal EBNF grammar
- **Examples:** `examples/` — buyer, seller, knowledge sharing scripts

## Why SUTRA Over Alternatives?

| Feature              | English | JSON API | SUTRA |
|----------------------|---------|----------|-------|
| Human-readable       | ✅       | ❌        | ✅     |
| Machine-executable   | ❌       | ✅        | ✅     |
| Deterministic        | ❌       | ✅        | ✅     |
| Expresses intent     | ✅       | ❌        | ✅     |
| Negotiation-native   | ❌       | Partial  | ✅     |
| Cryptographically signed | ❌   | ❌        | ✅     |
| Auditable transcript | ❌       | Partial  | ✅     |
