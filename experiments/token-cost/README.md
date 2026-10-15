# Token-cost experiments — finding the cheapest agent encoding

**Goal:** find an encoding of agent-to-agent messages that costs the fewest real
LLM tokens, measured with production tokenizers, while carrying exactly the same
information. The target is an order-of-magnitude cost reduction versus existing
protocols (JSON APIs and English prose).

**Metric:** tokens per canonical message (what agents actually pay), measured
with `tiktoken` `o200k_base` and `cl100k_base`. The baseline (`sutra_current`)
is validated against the repository's own parser before any numbers are
reported — counts of guaranteed-valid SUTRA only.

**Method:** every message is defined once as structured data (`corpus.py`);
all representations are rendered from that form (`renderers.py`), so they are
lossless by construction. Session-scoped dictionary variants carry their
one-time handshake cost in the dialogue metric.

## Results v1 (12 messages; dialogue = 6-message deal)

| representation | corpus o200k | vs EN | vs JSON | dialogue | vs EN |
|---|---|---|---|---|---|
| sutra_c_max | 139 | 1.9× | 3.7× | 116 | 1.2× |
| sutra_pos_session_epoch | 140 | 1.9× | 3.7× | **91** | **1.5×** |
| sutra_pos_session | 148 | 1.8× | 3.5× | 95 | 1.5× |
| sutra_pos_alias | 169 | 1.6× | 3.0× | 107 | 1.3× |
| sutra_pos (no session) | 220 | 1.2× | 2.3× | 127 | 1.1× |
| english | 263 | 1.0× | 2.0× | 140 | 1.0× |
| sutra_current | 330 | 0.8× | 1.6× | 180 | 0.8× |
| json | 514 | 0.5× | 1.0× | 273 | 0.5× |

## Findings

1. **BPE tokenizers reward natural English.** English prose is already dense;
   synthetic syntax pays a penalty (`="`, `)`, `;` are tokens).
   Simple keyword shortening (INTENT→I) buys ~10%, nothing more.
2. **Routing dominates.** `buyer@home>seller@store` is 7 tokens repeated on
   every message — **34% of all tokens**. Session-negotiated aliases
   (HPACK-style) are the single biggest text-level win.
3. **Current SUTRA costs more than English** (0.8×). This experiment is also
   the fix list for the v1.0 wire format.
4. JSON is the true baseline to beat: compact SUTRA variants are already
   **3–3.7× cheaper than JSON** for identical content.

## Sweep v2 — 384 encodings, all round-trip verified (`sweep.py`)

Axes: keyword style (English / 2-letter / 1-letter / digit / Sanskrit root /
token-native) × routing (full / alias / session / direction-fold) × argument
style (named / Karaka-schema slots) × session entity dictionary × dates
(ISO / ordinal) × predicate dictionary = 384 unique encodings. Every variant
has a decoder; `decode(encode(m)) == m` is asserted for all messages.

**Winner family:** 1-letter keywords + direction folded into the keyword
(Panini-style case on the symbol) + fixed Karaka slots + session entity
dictionary. **6.7 tokens/message** (was 27.5 for current SUTRA, 21.9 English,
42.8 JSON). Session cost = `6.7·N + 54` (one-time handshake).

| messages N | sutra_c | english | json | vs json |
|---|---|---|---|---|
| 6 | 94 | 131 | 257 | 2.7× |
| 12 | 134 | 263 | 514 | 3.8× |
| 50 | 387 | 1095 | 2140 | 5.5× |
| 200 | 1387 | 4380 | 8560 | 6.2× |

Sample encodings: `a o` (accept offer o — 2 tokens), `q availability a`
(3 tokens), `b i buy a 50000 D1` (intent, 9 tokens).

**What the Sanskrit mechanisms actually contributed:**
- Karaka slots (vibhakti) — the structural win: keys, `=`, quotes and
  parentheses all disappear. (−35% alone)
- Direction folded into the keyword symbol (case/sandhi) — routing was 34%
  of tokens; folded to zero per message.
- Entity handles (samasa) — payload values become single symbols after first
  mention.
- Predicate dictionary (dhatu table) — net loss in short sessions (handshake
  > savings), break-even around N≈30; measured, published.
- Sanskrit-root vocabulary itself (`PR`, `PV`, `DH`) — neutral: a BPE
  tokenizer cares about frequency, not etymology. The *structure* transferred,
  not the words.

**Status vs the 10× goal:** at 3.3×/6.4× vs English/JSON for the corpus
(6.2× vs JSON at N=200). The remaining paths to 10×: a binary wire format
(base64/base85 over packed bytes), fused primitive+predicate symbols, number
compaction, and the non-token lever — deterministic auto-response, which
removes LLM roundtrips entirely (a separate multiplier on total transaction
cost).

## Sweep v3 — 162 configs (40 unique), all round-trip verified (`sweep2.py`)

New mechanisms: **anuvrtti** (Panini's carry-over as session ellipsis — repeated
values become `.`), number alphabets (base-36, `48k`), **binary wires** (packed
varints → base85/base64), Devanagari keywords (control).

**Winner: `6.25 tokens/message`, handshake 35** (letters + folded route +
Karaka slots + entities + anuvrtti values + base-36):

`o o 111c a m` — a complete OFFER in 5 tokens. `a o` = ACCEPT in 2.

| finding | result |
|---|---|
| Anuvrtti (value ellipsis) | −6 tokens/12 msgs — real but modest after entities |
| base-36 numbers | −1 token vs decimal |
| **Binary wire (b85/b64)** | **LOST.** BPE is trained on text; base85 chars tokenize ~2-3 per 4 chars, and short messages pay tag overhead. For small structured messages, tuned text beats binary. Published as a negative. |
| Devanagari primitives | neutral (स/त/श tokenize fine but buy nothing) |

**The 10× question — against what agents actually emit.** Real deployments send
JSON-RPC/MCP envelopes (~69.8 tokens/message), not lean JSON:

| session length N | sutra_c | vs English | vs lean JSON | **vs JSON-RPC** |
|---|---|---|---|---|
| 6 | 72 | 1.8× | 3.5× | 5.8× |
| 12 | 110 | 2.4× | 4.7× | 7.6× |
| 50 | 348 | 3.2× | 6.2× | **10.0×** |
| 200 | 1285 | 3.4× | 6.7× | **10.9×** |

Cumulative journey: current SUTRA 330 → v1 139 → v2 80 → v3 **75** tokens for
the 12-message corpus.

## Round 4 — comprehension (`comprehension.py`)

Real-model emit/parse through the local codex CLI (batched cells of 12 messages;
EMIT = JSON → protocol, PARSE = protocol → JSON; scored with the real decoders).

| cell | correct | output tokens |
|---|---|---|
| json/parse (control) | 12/12 | 497 |
| sutra/parse (readable) | 10/12 | 796 |
| sutra/emit (readable) | 11/12 | 435 |
| **c1/parse** (6.1 tok/msg) | **12/12** | 854 |
| **c1/emit** | **12/12** | **103** |

Findings:

1. **Compression does not break comprehension** — the compact form matched or
   beat the readable form on both directions. (Single run per cell; an earlier
   run slipped once on direction, so variance is real and n>1 reruns belong in
   round 5.)
2. **The model taught the protocol a trick:** it spontaneously concatenated the
   broadcast prefix (`sF`, not `s F`). Adopted — the round-3 champion dropped
   from 75 to **73 tokens** (6.1/message).
3. **Readable SUTRA has two real gaps the tests exposed:** a QUERY carries no
   sender (the FROM clause reads as the sender), and `in_reply_to` travels as a
   comment — invisible to the repo's own parser.
4. **The price of compactness is dictionary:** C1 needs a 356-token spec vs 158
   for readable. Per-message wins; session setup loses.
5. Accuracy-adjusted emission cost: ~8.6 tokens per correct message (c1) vs
   ~39.5 (readable) — ~4.6×.

## Round 5 — error bars, effort axis, novel entities, logging (`round5.py`)

Every call is logged: `logs/round5/` holds one file per call (metadata + full
prompt + raw output), `index.jsonl` one record per call with per-message
verdicts and failure reasons, `summary.json` the aggregates. The first scoring
pass (before the case-normalization fix) is archived under
`logs/round5-firstpass/`. 21 calls, 216 message-level tests this round.

| cell | reps | mean | min–max | dominant failures |
|---|---|---|---|---|
| json/parse (control) | 12/12 | 1.00 | — | — |
| sutra/parse | 11,11,10 /12 | 0.89 | 0.83–0.92 | `extra` (3), `to` (1) |
| **sutra/emit** | **0,0,11 /12** | **0.31** | **0.00–0.92** | undecodable (24) |
| c1/parse | 9,10,12 /12 | 0.86 | 0.75–1.00 | `body` (4), `primitive` (1) |
| **c1/emit** | **12,10,12 /12** | **0.94** | 0.83–1.00 | `fields` (2) |
| c1/parse @ low effort | 7,10 /12 | 0.71 | 0.58–0.83 | `body` (4), mixed (3) |
| c1/emit @ low effort | 9,11 /12 | 0.83 | 0.75–0.92 | undecodable (3) |
| **c1/emit-novel** | **3,3 /3** | **1.00** | — | — |
| c1/parse-novel | 2,3 /3 | 0.83 | 0.67–1.00 | `body` (1) |

Findings:

1. **Readable SUTRA's emission is a coin flip; compact's is not.** Two of three
   runs produced 12/12 *undecodable* statements — the entire difference is a
   single character: the mandatory `;` terminator, which the model drops.
   SUTRA-C1 has no terminator (message boundary = statement boundary), so the
   failure mode cannot occur. Compact emit: mean 0.94 and **95 output tokens
   in every rep** — stable, near-minimal generation.
2. **Parsing is statistically tied** (sutra 0.89 vs c1 0.86 at high effort);
   c1 errors cluster in OFFER/COUNTER bodies.
3. **Reasoning effort is a real cost/accuracy knob:** at low effort parse drops
   0.86→0.71 and emit 0.94→0.83, but calls run 2–3× faster.
4. **The dictionary fallback works:** novel values (`Laptop`, `Asus`,
   `off-777`) emitted 6/6 correct, parsed 5/6 — no hallucinated aliases.
5. Logging caught a scoring bug (case-sensitive `Intent` vs `INTENT`); the
   archived first-pass logs document it rather than hiding it.

## Round 6 — mechanisms read out of the Panini literature (`sweep3.py`)

Sources: Kiparsky's accounts of the Ashtadhyayi's economy (ordering, blocking,
anuvrtti, adhikara, pratyahara; Minimum Description Length as the stated goal),
the Sivasutra/pratyahara studies, and the katapayadi/bhutasankhya number-coding
literature. Three mechanisms were implemented, all round-trip verified:

1. **Rule-order channel (ordering/blocking as information).** Panini's rule
   *order* carries meaning. When a conversation follows a known template
   (negotiated once, like an adhikara heading), the message type, predicate,
   routing, counterparty addresses and reply threading are all implied by
   position; only new payload values are transmitted. Template sessions:
   59 tokens for the deal → 17.1× vs JSON-RPC at N=500.
2. **Chandas meter (fixed-width fields + sandhi concat).** Vedic meter is
   fixed-width syllables. With per-field fixed widths the payload concatenates
   to one separator-free string: `o48000am` = a complete OFFER; `48000739676`
   = COMMIT amount + deadline; `a` = the whole QUERY. Dialogue: **52 tokens
   incl handshake, 2.83/message → 23.2× at N=200 and 24.0× at N=500 vs
   JSON-RPC; crosses 20× at N≈60.** Sample payloads are in the script output.
3. **Pratyahara ranges.** A linear ordering of handles plus an inclusive
   end marker names a whole set: `bD` = items b..d. Saves 1 token at three
   items, scaling with range length.
4. **Katapayadi digits — negative.** Numbers as consonants (`48000` →
   `yvnnn`) tokenize worse than plain digits (83 vs 76 corpus total).
   Published like every other negative.

Caveats, stated for the record: meter/template modes assume the agreed
template — a deviation needs a fallback encoding plus a resync marker (round
7); the meter mode is token-verified but not yet comprehension-tested with a
model; all counts are o200k on the 12-message corpus / 6-message deal.

## Round 7 — pop quiz across model families (`round7.py`, `rescore7.py`)

Three backends, all local CLIs, no API billing: `codex` → gpt-6-luna;
`opencode run` → deepseek-v4.1-flash; `agy` (Antigravity) → **blocked**: the
CLI hangs on long headless prompts (tiny prompts answer instantly). Raw
outputs for every call are in `logs/round7/`; the earlier attempt with a
defective prompt ordering is archived under `logs/round7-promptbug/`.

| cell | gpt-6-luna | deepseek-v4.1-flash |
|---|---|---|
| c1/parse | 12/12 | 12/12 |
| c1/emit | 12/12 | 12/12 |
| meter/parse | 2/6 | **6/6** |
| meter/emit (strict) | 4/6 | 5/6 |
| meter/emit (order-tolerant) | 4/6 | 5/6 |

Findings:

1. **The compact wire form is fully cross-comprehensible.** Both models read
   *and* write the 6.1 tok/msg form perfectly — this is the encoding to ship.
2. **The meter form (2.8 tok/msg) is comprehensible but harder and
   model-dependent**: deepseek reads it 6/6 and writes it 5/6; gpt-6-luna
   writes 4/6 but reads only 2/6. Ultra-compactness trades against robustness.
3. **Oops button measured**: a surprise outside the agreed template costs its
   compact form plus a resync marker — `!Rp!price_too_low` (7 tokens) vs ~3 in
   template mode. One deviation, small fixed cost, then the session continues
   cheap.
4. The self-checks caught two harness bugs (prompt ordering; a missing
   canonicalisation wrap). Both runs are archived and the raw outputs were
   re-scored offline — no test was re-rolled, nothing hidden.
5. Documented tolerances, applied equally to both models: short addresses
   (`buyer` ≡ `buyer@home`), a predicate that merely echoes the primitive, and
   replies referenced by message index instead of id.

## Round 8 (planned)

- Unblock a third model family (`agy` hang report; smaller prompts or
  interactive profile).
- Freeze SUTRA-C: spec + encoder/decoder in the package; optional `;` parser
  relaxation; package test suite + CI.
- Long sessions (50+ messages) for drift and ellipsis-state discipline;
  fallback/resync under real model traffic.

## Files

- `corpus.py` — canonical messages (semantic form) + dialogue subset
- `renderers.py` — lossless renderers, one function per representation
- `bench.py` — v1 matrix; validates the SUTRA baseline with the repo parser
- `sweep.py` — 384-encoding combinatorial sweep (v2), decoder-verified
- `sweep2.py` — v3 mechanisms: anuvrtti ellipsis, number alphabets, binary
  wires (negative result); the C1 encoder/decoder used by later rounds
- `comprehension.py` — round-4 model-in-the-loop emit/parse tests
- `round5.py` — round-5 repeats, effort axis, novel entities, full logging
- `logs/` — per-call prompts, raw outputs, `index.jsonl`, `summary.json`
- `results-*.json` — machine-readable results per round

Run: `.venv/bin/python experiments/token-cost/<bench|sweep|sweep2|comprehension|round5>.py`
