# SUTRA-C — the compact wire format (v0.7, frozen)

SUTRA-C is the measured compact encoding for agent-to-agent messages. It is
carried by the same state model and semantics as readable SUTRA — it is a wire
format, not a new language. Every design choice here was selected by the
token-cost experiments in [`experiments/token-cost/`](../experiments/token-cost/README.md);
every variant is lossless and decoder-verified.

Measured (o200k tokens, 6-message buyer/seller deal, `examples/compact_deal.py`):

| encoding | tokens total | per message | vs JSON-RPC |
|---|---|---|---|
| readable SUTRA | 134 | 22.3 | 3.2x |
| **SUTRA-C (compact)** | **45** | **7.5** | **9.7x** |
| **SUTRA-C template (meter)** | **17** | **2.8** | **25.6x** |
| JSON-RPC envelope (deployed style) | 435 | 72.5 | 1x |

Cross-model comprehension (round 7): the compact form reads and writes at
12/12 on two model families; the meter form is model-dependent (6/6 read on
deepseek-v4.1-flash). Raw logs in the experiments directory.

## 1. Statements

```
statement := [ "!" ] [ route ] KW slot* tail*
route     := sender_prefix | ∅            (see §3)
KW        := I F Q O K A R C X            (§2)
slot      := value | "." | "-"            (§5)
tail      := ("!" | "~" | "^") value      (§6)
```

Tokens are whitespace-separated, except that double-quoted values may contain
spaces; parsers MUST tokenize quote-aware (backslash escapes included).

## 2. Keywords

| letter | primitive | | letter | primitive |
|---|---|---|---|---|
| `I` | INTENT | | `A` | ACCEPT |
| `F` | FACT | | `R` | REJECT |
| `Q` | QUERY | | `C` | COMMIT |
| `O` | OFFER | | `X` | ACT |
| `K` | COUNTER | | | |

## 3. Routing

- **Directed** message (has a receiver): no prefix; letter case carries the
  direction. Lowercase = `parties[0] -> parties[1]`; UPPERCASE = reverse.
  `q availability a` = the first party queries the second.
- **Broadcast** (no receiver): the sender's one-letter party prefix is glued
  to the primitive: `sF available a 48000` (fact from `parties[1]`).

The two parties are session configuration (`Session(parties=(...),
party_prefix=(...))`), default `("buyer@home", "seller@store")`, prefixes `b`/`s`.

## 4. Positional (Karaka) slots

Arguments are positional, in the fixed slot order for the message kind. These
are the frozen schemas; predicates outside the table use the named fallback
(`pred(k=v, ...)` is not used in C1 — see §7).

| message | slots |
|---|---|
| `INTENT buy` | item, max_price, deadline |
| `FACT available` | item, seller, price |
| `FACT committed` | id, status |
| `QUERY availability` / `QUERY available` | item |
| `COMMIT pay` | amount, to |
| `ACT transfer` | amount, to |
| `OFFER` | id, give.money, want.item, want.brand |
| `COUNTER` | orig, id, give.money, want.item |
| `ACCEPT` / `REJECT` | id |

## 5. Values, dictionary, ellipsis

- **Session dictionary**: repeated values get one-letter handles, negotiated
  once per session with a handshake line:
  `a=SmartTV m=Samsung o=off-001 p=off-001-c`
  (`Session.register(value, alias)` for hand-picked handles,
  `Session.learn(values)` for automatic assignment; 52-handle cap).
- **Bare values**: safe alphabet `A-Za-z0-9@._/-`, not numeric-looking.
  Everything else is double-quoted JSON (lossless).
- **Ellipsis (anuvrtti)**: `.` repeats the last value of that slot in this
  session; the encoder uses it automatically for repeats.
- **Absent middle slot**: `-`.

## 6. Tails

`!reason` (REJECT), `~deadline` (COMMIT), `^in_reply_to`, each ellipsis-aware.
Deadlines travel as ISO dates (a 6-digit ordinal form is accepted on decode).

## 7. Extensions

Unknown predicates fall back to named arguments inside the compact statement:
`F weather city=Bhubaneswar temp=31` — still compact, still lossless.

## 8. Resync (the oops button)

When a message falls outside an agreed template, prefix the full compact
statement with `!`:

```
!R p !price_too_low
```

One marker token; the session continues compact immediately after.

## 9. Template (meter) mode

For an agreed sequence of messages (`TemplateSession(steps, session)`), the
message kind, direction and reply threading are implied by position, and the
payload is a fixed-width concatenation:

- numeric slots are zero-padded to fixed widths (default 5; dates/`by` 6);
- `.` / `-` are single characters even in numeric slots;
- counterparty addresses (`seller`, `to`) and `in_reply_to` are implied;
- **all non-numeric values must be single-character** (dictionary handles),
  otherwise `CompactError`.

The frozen six-step deal produces exactly:

```
a  .-48000  o48000am  op46000.  o  48000739676
```

## 10. Guarantees and limits

- **Lossless**: `decode(encode(m)) == m`; the test suite
  (`tests/test_compact.py`) covers the message zoo, ellipsis, dictionary,
  routing, resync and meter mode.
- **Stateful by design**: ellipsis and dictionary require both sides to evolve
  the same session state; the handshake line establishes it.
- Not yet: runtime-level template negotiation, long-session drift tests,
  package CI. Tracked in the roadmap.

## 11. HTTP binding (v0.9)

The wire format is carried directly — no JSON wrapper on the hot path:

```
POST /sutra/c1/handshake      establish the session
  headers: X-From: <client id>
  body:    the dictionary line (may be empty)
  reply:   204 + X-Sutra-Agent, X-Sutra-Dictionary

POST /sutra/c1                one or more compact statements, newline-separated
  headers: X-From: <client id>
  body:    C1 text (Content-Type: text/x-sutra-c1)
  reply:   200 + C1 text = compact auto-replies (QUERY -> FACT)
           X-Sutra-Responses: number of executed statements
```

Rules: one handshake per client session; stateful sessions (dictionary +
ellipsis) are keyed by the sender and reset by re-handshaking; requests from
unknown sessions are rejected with 409; errors are JSON (off the hot path);
token-auth and rate-limit guards apply when configured. End-to-end measurement:
`examples/network_compact_demo.py`.

**Template (meter) mode over HTTP (v0.10).** After the handshake, a client may
agree on a sequential template:

```
POST /sutra/c1/template        one step per line: `<K> <pred|-> <f|r> [reply_id]`
  reply: 204 + X-Sutra-Steps

POST /sutra/c1                 X-Sutra-Mode: meter
  body:  one meter payload for the current step (§9)
  reply: X-Sutra-Mode: meter, body = payload(s) for the following step(s);
         a QUERY's auto-reply occupies the next template step and advances
         the pointer past it
```

Meter sends are strictly sequential; running past the last step is a 409
("negotiate a new one"); a QUERY with no matching facts is a 409 (the template
expects a reply payload); off-template messages travel as resync C1 (`!` +
statement) and do not move the meter pointer. End-to-end measurement:
`examples/network_meter_demo.py`.

## 12. Python API

```python
from sutra.compact import Session, encode, decode, encode_resync, TemplateSession

s = Session()
s.register("SmartTV", "a")
wire = encode(msg, s)          # canonical dict -> "q availability a"
back = decode(wire, s)         # -> canonical dict, == msg
```
