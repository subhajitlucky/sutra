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

## Round 3 (planned)

- **Entity dictionaries:** values (items, ids, amounts) become session handles
  after first mention — the payload itself gets compressed.
- **Binary wire:** canonical form → packed bytes → base64/base85 text,
  measured with the same tokenizers (expect ~1 token per 2 chars).
- **Number/date micro-encodings** beyond epoch days.
- **Full schema mode:** primitives + predicates + arg positions + entity
  handles all dictionary-negotiated; measures the text-encoding floor.
- **Comprehension checks (separate axis):** a cheap protocol is useless if
  models emit or read it unreliably; later rounds must measure agent error
  rates per encoding, not just token counts.

## Files

- `corpus.py` — canonical messages (semantic form) + dialogue subset
- `renderers.py` — lossless renderers, one function per representation
- `bench.py` — runs the matrix, validates the SUTRA baseline with the repo
  parser, writes `results-v1.json`, prints the leaderboard
- `results-v1.json` — full per-message counts and rendered texts

Run: `.venv/bin/python experiments/token-cost/bench.py`
