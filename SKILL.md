# SUTRA — Agent Communication Language

## What It Does

SUTRA (Structured Universal Transaction & Reasoning Architecture) is a minimal,
deterministic language for AI agent-to-agent communication. It enables agents to:

- Declare intentions and share verified knowledge
- Query other agents for information
- Negotiate offers, accept/reject proposals
- Commit to binding obligations and execute actions

## When to Use

Use SUTRA when building systems where autonomous AI agents need to:
- Trade resources, services, or information
- Negotiate multi-step agreements
- Maintain auditable transaction records
- Communicate with formalized intent (not unstructured English)

## Core Primitives

| Keyword   | Purpose               | Sanskrit Origin |
|-----------|-----------------------|-----------------|
| `INTENT`  | Declare intention     | Sankalpa        |
| `FACT`    | Assert knowledge      | Pramana         |
| `QUERY`   | Request information   | Prashna         |
| `OFFER`   | Propose agreement     | Samvida         |
| `ACCEPT`  | Agree to offer        | Svikrti         |
| `REJECT`  | Decline offer         | Nirakrti        |
| `COMMIT`  | Binding obligation    | Dharma          |
| `ACT`     | Execute action        | Kriya           |

## Quick Start

```sutra
#sutra "v0.1"
#from "agent-a"
#to "agent-b"

INTENT buy(item="Widget", max_price=100);
QUERY availability(item="Widget") FROM "agent-b";
OFFER id="deal-001" TO "agent-b" {
    give: {money: 95},
    want: {item: "Widget"}
};
```

## Agent Integration

Agents that learn SUTRA can:
1. Parse incoming SUTRA messages from other agents
2. Generate SUTRA statements to express their intentions
3. Maintain state (beliefs, offers, commitments) per the SUTRA spec
4. Execute deterministic, auditable negotiations

## Links

- GitHub: https://github.com/your-username/sutra
- Spec: See `spec/SUTRA_SPEC.md` in the repository
- Examples: See `examples/` directory
