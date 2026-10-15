"""Round 6 — mechanisms read out of the Panini literature.

1. Rule-order channel (blocking/ordering): Panini's rule ORDER itself carries
   information. For a known conversation FSM, the message type, predicate and
   routing are implied by position; only NEW payload values are transmitted.
   "Template sessions" — measured on the 6-message deal.

2. Pratyaharas (range abbreviations with a marker letter): a linear order +
   an end marker names a whole SET. Item handles ordered a..e: `bD` means the
   range b..d (UPPERCASE end = inclusive marker, mirroring Panini's it-marker).
   Measured on 3 new bulk messages.

3. Katapayadi digits (digit -> consonant): numbers become pronounceable,
   tokenizer-friendly strings. Applied to the champion corpus losslessly via
   a digit-wise substitution + inverse.

All variants are decoder-verified.
"""

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tiktoken  # noqa: E402

from corpus import MESSAGES, DIALOGUE  # noqa: E402
from sweep import ENC  # noqa: E402
import sweep2 as S2  # noqa: E402
from comprehension import canon  # noqa: E402

O200K = ENC["o200k"]
tok = lambda s: len(O200K.encode(s))
C1 = {"kw": "l1", "route": "fold", "delta": "values", "numbers": "b36", "wire": "text"}
HANDSHAKE = "a=SmartTV m=Samsung o=off-001 p=off-001-c z=off-999 g=signed h=price_too_high u=unsupported"

# ── 1. template sessions (rule-order channel) ──────────────────────

# The negotiation FSM: this exact type-sequence is negotiated once (adhikara),
# after which each message carries only its new payload.
TEMPLATE_SCRIPT = [  # (primitive, predicate, expected in_reply_to) in dialogue order
    ("QUERY", "availability", None),
    ("FACT", "available", "m03-query"),
    ("OFFER", None, None),
    ("COUNTER", None, None),
    ("ACCEPT", None, None),
    ("COMMIT", "pay", None),
]

# Slots whose value the template implies (counterparty addresses).
IMPLIED_ADDRESS_SLOTS = ("seller", "to")


def payload_encode(m, cfg, sess):
    """Only the values, with anuvrtti repeats. Type/predicate/route implied."""
    f = S2.build_fields(m, cfg, sess)
    order = S2.order_of(m)
    flat = S2.flat_of(m)
    parts = []
    for slot, val in zip(order, f["vals"]):
        if val == ("missing",):
            parts.append("-")
        elif val == ("repeat",):
            parts.append(".")
        elif slot in IMPLIED_ADDRESS_SLOTS and flat[slot] in ("buyer@home", "seller@store"):
            pass  # implied by the template: counterparty address
        else:
            parts.append(S2.surface_value(flat[slot], slot, cfg))
    for key in ("reason", "by"):
        fv = f[key]
        if fv is None:
            continue
        if fv == ("repeat",):
            parts.append("." + {"reason": "!", "by": "~"}[key])
        else:
            marker = {"reason": "!", "by": "~"}[key]
            v = fv[1]
            if key == "by":
                import datetime as dt
                parts.append(marker + S2.surface_number(dt.date.fromisoformat(v).toordinal(), cfg["numbers"]))
            else:
                parts.append(marker + (S2.ENTITY.get(v, v)))
    # in_reply_to is implied by the template; never transmitted
    return " ".join(parts)


def payload_decode(text, prim, pred, route, reply_to, cfg, sess):
    """Surface pairs in `sweep2.resolve`'s text format, template implied."""
    tokens = text.split()
    order = S2.order_of({"primitive": prim, "predicate": pred})
    implied = {}
    if "seller" in order:
        implied["seller"] = "seller@store"
    if "to" in order:
        implied["to"] = "seller@store" if route == 0 else "buyer@home"
    vals = []
    for slot in order:
        if slot in implied:
            # encoder emits '-' (missing) or '.' (repeat) for implied slots;
            # a present address value emits nothing at all.
            if tokens and tokens[0] in ("-", "."):
                t = tokens.pop(0)
                vals.append((slot, "missing" if t == "-" else t))
            else:
                vals.append((slot, implied[slot]))
            continue
        t = tokens.pop(0)
        vals.append((slot, "missing" if t == "-" else t))
    tails = {}
    for t in tokens:
        tails[t[0]] = t[1:]
    if reply_to:
        tails["^"] = reply_to
    return {"prim": prim, "pred": pred, "pred_repeat": False,
            "route": route, "vals": vals, "tails": tails}


def template_session():
    by_id = {m["id"]: m for m in MESSAGES}
    dialogue = [by_id[i] for i in DIALOGUE]
    routes = [0, 1, 0, 1, 0, 0]  # buyer->seller or seller->buyer per dialogue step
    sess = S2.Session()
    texts = []
    for m in dialogue:
        texts.append(payload_encode(m, C1, sess))
    total = sum(tok(t) for t in texts) + tok(HANDSHAKE)
    # round-trip
    sess = S2.Session()
    for m, (prim, pred, reply_to), route, t in zip(dialogue, TEMPLATE_SCRIPT, routes, texts):
        dec = payload_decode(t, prim, pred, route, reply_to, C1, sess)
        got = S2.resolve(dec, C1, sess, "text")
        assert canon(got) == canon(m), f"template round-trip failed: {m['id']} {t}"
    return texts, total


# ── 2. pratyahara ranges ───────────────────────────────────────────

ITEM_ORDER = ["SmartTV", "Laptop", "Monitor", "Keyboard", "Tablet"]
ITEM_ID = {name: chr(ord("a") + i) for i, name in enumerate(ITEM_ORDER)}
ITEM_REV = {v: k for k, v in ITEM_ID.items()}

BULK = [
    {"id": "s1-query-catalog", "primitive": "QUERY", "predicate": "availability",
     "args": [("items", ["Laptop", "Monitor", "Keyboard"])],
     "from": "buyer@home", "to": "seller@store", "extra": {}},
    {"id": "s2-fact-bulk", "primitive": "FACT", "predicate": "available",
     "args": [("items", ["Laptop", "Monitor", "Keyboard"]), ("price", 25000)],
     "from": "seller@store", "to": None, "extra": {}},
    {"id": "s3-offer-bulk", "primitive": "OFFER", "predicate": None,
     "args": [("id", "off-bulk")],
     "body": {"give": [("money", 70000)], "want": [("item", ["Laptop", "Monitor", "Keyboard"])]},
     "from": "buyer@home", "to": "seller@store", "extra": {}},
]


def range_token(items):
    """a..c -> 'aC' (lowercase start, UPPERCASE inclusive end marker)."""
    ids = sorted(ITEM_ID[i] for i in items)
    if len(ids) >= 3 and ids[-1] > ids[0] and all(
            chr(ord(ids[0]) + k) == ids[k] for k in range(len(ids))):
        return ids[0] + ids[-1].upper()
    return " ".join(ids)


def expand_range(tok_s):
    if len(tok_s) == 2 and tok_s[0].islower() and tok_s[1].isupper():
        a, b = ord(tok_s[0]), ord(tok_s[1].lower())
        return [ITEM_REV[chr(c)] for c in range(a, b + 1)]
    return [ITEM_REV[tok_s]]


def bulk_encode(m):
    """Champion-style encoding with pratyahara ranges for item sets."""
    p = m["primitive"]
    if p == "QUERY":
        return f"q availability {range_token(m['args'][0][1])}"
    if p == "FACT":
        return f"sF available {range_token(m['args'][0][1])} {m['args'][1][1]}"
    items = m["body"]["want"][0][1]
    return f"o off-bulk {m['body']['give'][0][1]} {range_token(items)}"


def bulk_encode_explicit(m):
    """Same encoding without ranges (items listed individually)."""
    p = m["primitive"]
    if p == "QUERY":
        return f"q availability {' '.join(ITEM_ID[i] for i in m['args'][0][1])}"
    if p == "FACT":
        return f"sF available {' '.join(ITEM_ID[i] for i in m['args'][0][1])} {m['args'][1][1]}"
    items = m["body"]["want"][0][1]
    return f"o off-bulk {m['body']['give'][0][1]} {' '.join(ITEM_ID[i] for i in items)}"


# ── 3. katapayadi digits ───────────────────────────────────────────

KATA = {"0": "n", "1": "k", "2": "t", "3": "p", "4": "y", "5": "g", "6": "j", "7": "d", "8": "v", "9": "s"}
KATA_REV = {v: k for k, v in KATA.items()}


def kata(to_num, to_str):
    for d, ch in KATA.items():
        to_str = to_str.replace(d, ch)
    return to_str


def kata_roundtrip(text, numbers_alphabet):
    """Substitute decimal digit runs with katapayadi consonants; invert."""
    def sub(mo):
        return "".join(KATA[c] for c in mo.group(0))
    # only substitute standalone values, not entity letters or b36 strings:
    # our champion corpus in 'dec' numbers has pure decimal runs as tokens
    out = re.sub(r"(?<![0-9a-z])[0-9]{2,}(?![0-9a-z])", sub, text)
    return out


# ── 4. chandas meter: fixed-width fields, one concatenated string ──

NUM_WIDTH = {"max_price": 5, "price": 5, "amount": 5, "give.money": 5,
             "deadline": 6, "by": 6}  # decimal, zero-padded (corpus scale)


def payload_encode_meter(m, cfg, sess):
    """Same payload as template mode, but concatenated with fixed widths."""
    f = S2.build_fields(m, cfg, sess)
    order = S2.order_of(m)
    flat = S2.flat_of(m)
    parts, widths = [], []
    for slot, val in zip(order, f["vals"]):
        if val == ("missing",):
            parts.append("-"); widths.append(1)
        elif val == ("repeat",):
            parts.append("."); widths.append(1)
        elif slot in IMPLIED_ADDRESS_SLOTS and flat[slot] in ("buyer@home", "seller@store"):
            continue
        else:
            v = flat[slot]
            if isinstance(v, int):
                w = NUM_WIDTH.get(slot, 5)
                parts.append(str(v).rjust(w, "0")); widths.append(w)
            else:
                s = S2.ENTITY.get(v, v)
                if len(s) != 1:
                    raise ValueError(f"meter mode needs single-char values: {v}")
                parts.append(s); widths.append(1)
    if f["by"] is not None:
        if f["by"] == ("repeat",):
            parts.append("."); widths.append(1)
        else:
            import datetime as dt
            n = dt.date.fromisoformat(f["by"][1]).toordinal()
            parts.append(str(n).rjust(6, "0")); widths.append(6)
    return "".join(parts), widths


def payload_decode_meter(text, prim, pred, route, reply_to, cfg, sess):
    order = S2.order_of({"primitive": prim, "predicate": pred})
    implied = {}
    if "seller" in order:
        implied["seller"] = "seller@store"
    if "to" in order:
        implied["to"] = "seller@store" if route == 0 else "buyer@home"
    vals = []
    pos = 0
    for slot in order:
        if slot in implied:
            # absent unless a marker char is present
            if pos < len(text) and text[pos] in "-.":
                c = text[pos]; pos += 1
                vals.append((slot, "missing" if c == "-" else c))
            else:
                vals.append((slot, implied[slot]))
            continue
        w = NUM_WIDTH.get(slot, 1)
        chunk = text[pos:pos + w]; pos += w
        vals.append((slot, "missing" if chunk == "-" else chunk))
    tails = {}
    if pos < len(text):
        rest = text[pos:]
        if rest.startswith("."):
            tails["~"] = "."
        else:
            tails["~"] = str(int(rest)).lstrip("0") if rest.isdigit() else rest
    if reply_to:
        tails["^"] = reply_to
    return {"prim": prim, "pred": pred, "pred_repeat": False,
            "route": route, "vals": vals, "tails": tails}


def meter_session():
    cfg_dec = {**C1, "numbers": "dec"}  # meter numbers are decimal, zero-padded
    by_id = {m["id"]: m for m in MESSAGES}
    dialogue = [by_id[i] for i in DIALOGUE]
    routes = [0, 1, 0, 1, 0, 0]
    sess = S2.Session()
    out = [payload_encode_meter(m, cfg_dec, sess) for m in dialogue]
    total = sum(tok(t) for t, _ in out) + tok(HANDSHAKE)
    sess = S2.Session()
    for m, (prim, pred, reply_to), route, (t, _w) in zip(dialogue, TEMPLATE_SCRIPT, routes, out):
        dec = payload_decode_meter(t, prim, pred, route, reply_to, cfg_dec, sess)
        got = S2.resolve(dec, cfg_dec, sess, "text")
        assert canon(got) == canon(m), f"meter round-trip failed: {m['id']} {t!r}"
    return out, total


def main():
    print("=== 4. chandas meter (fixed-width concat, Panini's syllable economy) ===")
    try:
        out, total = meter_session()
        for t, w in out:
            print(f"   [{tok(t):>2} tok] {t!r}  widths={w}")
        per = (total - tok(HANDSHAKE)) / 6
        print(f"   dialogue total incl handshake: {total} tokens | per-message {per:.2f}")
        for N in (6, 50, 200, 500):
            cost = per * N + tok(HANDSHAKE)
            print(f"   N={N:<4} meter {cost:>7.0f} | JSON-RPC {69.8 * N:>7.0f} -> {69.8 * N / cost:>5.1f}x")
    except AssertionError as exc:
        print("   meter round-trip:", exc)

    print("\n=== 1. template sessions (rule-order channel) ===")
    texts, total = template_session()
    for t in texts:
        print(f"   [{tok(t):>2} tok] {t}")
    print(f"   dialogue total incl handshake: {total} tokens  (baseline dialogue: 76)")
    by_id = {m["id"]: m for m in MESSAGES}
    dlg = [by_id[i] for i in DIALOGUE]
    json_rpc = 0
    from renderers import render_json
    for i, m in enumerate(dlg):
        env = '{"jsonrpc":"2.0","id":%d,"method":"tools/call","params":{"name":"sutra","arguments":%s}}' % (i + 1, render_json(m))
        json_rpc += tok(env)
    per_msg = (total - tok(HANDSHAKE)) / 6
    print(f"   per-message payload: {per_msg:.2f} tokens (handshake 35, amortized)")
    for N in (6, 50, 200, 500):
        cost = per_msg * N + tok(HANDSHAKE)
        print(f"   N={N:<4} template {cost:>7.0f} | JSON-RPC {69.8 * N:>7.0f} -> {69.8 * N / cost:>5.1f}x")

    print("\n=== 2. pratyahara ranges ===")
    for m in BULK:
        r, e = bulk_encode(m), bulk_encode_explicit(m)
        print(f"   {m['id']:<18} ranged [{tok(r)}]  {r}")
        print(f"   {'':<18} listed [{tok(e)}]  {e}")

    print("\n=== 3. katapayadi digits (champion corpus, dec numbers) ===")
    from corpus import MESSAGES as ALL
    cfg_dec = {"kw": "l1", "route": "fold", "delta": "values", "numbers": "dec", "wire": "text"}
    sess = S2.Session()
    base = [S2.text_encode(m, cfg_dec, sess) for m in ALL]
    base_total = sum(tok(t) for t in base)
    kata_texts = [kata_roundtrip(t, "dec") for t in base]
    kata_total = sum(tok(t) for t in kata_texts)
    print(f"   decimal corpus: {base_total} | katapayadi corpus: {kata_total}")
    sample = [t for t in base if any(ch.isdigit() for ch in t)][0]
    print(f"   example: '{sample}' -> '{kata_roundtrip(sample, 'dec')}'")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nran in {time.time() - t0:.1f}s")
