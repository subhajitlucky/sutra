# SUTRA v0.1 — Language Specification

**Structured Universal Transaction & Reasoning Architecture**

*A minimal, deterministic, agent-to-agent communication language inspired by Dharmic ontology.*

---

## 1. Philosophy

SUTRA is a **declarative agent exchange language** — not a general-purpose programming language.

It exists so that autonomous AI agents can express **intent**, share **knowledge**, **negotiate** deals, and **commit** to obligations in a formal, auditable, deterministic way.

**Design Principles:**
- **Minimal** — under 30 grammar rules, 8 core keywords
- **Deterministic** — same input → same state transition, always
- **Declarative** — no loops, no mutation outside COMMIT
- **Transactional** — all side-effects are isolated per message
- **Transport-agnostic** — works over HTTP, WebSocket, TCP, file exchange
- **Human-readable** — English keywords, clear block structure
- **Machine-executable** — any compliant agent can parse and act on it

**Cultural Root:**
Core concepts map to Dharmic philosophy — not as decoration, but as structural ontology:

| Sanskrit     | SUTRA Keyword | Meaning                |
|--------------|---------------|------------------------|
| Sankalpa     | INTENT        | Declared intention     |
| Pramana      | FACT          | Verified knowledge     |
| Prashna      | QUERY         | Request for knowledge  |
| Samvida      | OFFER         | Proposed agreement     |
| Svikrti      | ACCEPT        | Acceptance of offer    |
| Nirakrti     | REJECT        | Rejection of offer     |
| Dharma       | COMMIT        | Binding obligation     |
| Kriya        | ACT           | Executable action      |

---

## 2. Type System

SUTRA uses a **minimal static type system**:

| Type        | Description                          | Example              |
|-------------|--------------------------------------|----------------------|
| `number`    | 64-bit floating point                | `42`, `3.14`         |
| `string`    | UTF-8 text in double quotes          | `"hello"`            |
| `boolean`   | Logical value                        | `true`, `false`      |
| `timestamp` | ISO 8601 date-time string            | `"2026-03-01T12:00"` |
| `agent`     | Agent identifier (string)            | `"seller@store"`     |
| `null`      | Absence of value                     | `null`               |
| `map`       | Key-value pairs `{k: v, ...}`        | `{price: 500}`       |
| `list`      | Ordered collection `[v, ...]`        | `[1, 2, 3]`          |

---

## 3. Core Keywords (8 Primitives)

### INTENT (Sankalpa)
Declares what the agent wants. Added to the agent's GoalSet.

```sutra
INTENT buy(item="SmartTV", max_price=50000, deadline="2026-03-01");
```

### FACT (Pramana)
Asserts verified knowledge. Added to the agent's BeliefBase.

```sutra
FACT available(item="SmartTV", seller="seller@store", price=48000);
```

### QUERY (Prashna)
Requests information from another agent. Read-only — cannot mutate remote state.

```sutra
QUERY availability(item="SmartTV") FROM "seller@store";
```

### OFFER (Samvida)
Proposes a deal to another agent. Added to OfferLedger.

```sutra
OFFER id="off1" TO "seller@store" {
    give: {money: 48000},
    want: {item: "SmartTV"},
    expires: "2026-03-01T23:59"
};
```

### ACCEPT (Svikrti)
Accepts an existing offer. Validates against OfferLedger, creates PendingCommit.

```sutra
ACCEPT "off1";
```

### REJECT (Nirakrti)
Rejects an existing offer. Optional reason.

```sutra
REJECT "off1" REASON "price_too_high";
```

### COMMIT (Dharma)
Creates a binding obligation. Moves from PendingCommit to CommitLedger. Irreversible.

```sutra
COMMIT deliver(item="SmartTV", to="buyer@home") BY "2026-03-05";
```

### ACT (Kriya)
Queues an executable action.

```sutra
ACT transfer(amount=48000, to="seller@store");
```

---

## 4. Agent State Model

Every SUTRA-compliant agent maintains:

```
Agent {
    id          : string            -- unique agent identifier
    belief_base : Set<Fact>         -- known facts (Pramana)
    goal_set    : Set<Intent>       -- active intentions (Sankalpa)
    offer_ledger: Map<ID, Offer>    -- open offers (Samvida)
    commit_ledger: Map<ID, Commit>  -- binding obligations (Dharma)
    action_queue: List<Action>      -- pending actions (Kriya)
}
```

### State Transition Rules

| Statement | Effect                                             |
|-----------|----------------------------------------------------|
| INTENT    | → Add to `goal_set`                                |
| FACT      | → Add to `belief_base`                             |
| QUERY     | → Generate response from `belief_base` (read-only) |
| OFFER     | → Add to `offer_ledger`                            |
| ACCEPT    | → Validate offer → Create pending commit           |
| REJECT    | → Remove offer from `offer_ledger`                 |
| COMMIT    | → Move to `commit_ledger` (binding, irreversible)  |
| ACT       | → Append to `action_queue`                         |

**No other side effects are permitted.**

---

## 5. Execution Model

1. **Receive** — Agent receives a `.sutra` script (plain text over any transport)
2. **Lex** — Tokenize into token stream
3. **Parse** — Build Abstract Syntax Tree (AST)
4. **Validate** — Type-check, verify references, check offer existence
5. **Execute** — Apply state transitions transactionally
6. **Respond** — Generate response `.sutra` script automatically
7. **Log** — Every executed statement is timestamped and logged

**Isolation:** Each received script executes in a fresh transactional context. On error, all changes roll back.

**Determinism:** Same script + same agent state → same resulting state, always.

---

## 6. Message Format

A SUTRA message is a plain-text script with an optional header:

```sutra
#sutra v0.1
#from "buyer@home"
#to "seller@store"
#timestamp "2026-02-27T20:00:00Z"

INTENT buy(item="SmartTV", max_price=50000);
QUERY availability(item="SmartTV") FROM "seller@store";
```

Headers start with `#` and are metadata. The body is executable SUTRA code.

---

## 7. Trust & Identity

- Agents are identified by string IDs (e.g., `"buyer@home"`)
- Messages MAY include a `#signature` header with a detached JWS
- COMMITs SHOULD be signed by the committing agent
- Trust validation is handled at the transport/application layer, not in the language itself
- This keeps the language minimal while allowing trust layers to be added

---

## 8. Extension Rules

- New predicates can be defined freely (e.g., `deliver(...)`, `transfer(...)`)
- New types cannot be added without spec revision
- Custom metadata headers (prefixed `#x-`) are allowed and ignored by non-supporting agents
- Domain ontologies can be imported via `#import "ontology_uri"` header
- Extensions MUST NOT redefine core keywords
- Unknown keywords → agent responds with `REJECT` + reason `"unsupported"`

---

## 9. Compliance

An agent is **SUTRA-compliant** if it can:
1. Parse any valid SUTRA program per the grammar
2. Maintain the defined agent state model
3. Execute state transitions as specified
4. Respond to QUERY with facts from its belief_base
5. Handle unknown constructs gracefully (REJECT, not crash)

---

## 10. License

SUTRA v0.1 is released under **MIT License** — free to use, modify, and distribute.

*Designed for machines. Readable by humans. Rooted in Dharma.*
