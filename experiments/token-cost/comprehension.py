"""Round 4 — comprehension: can a real model emit and read the compact forms?

Batched calls through the local codex CLI (ChatGPT-plan auth, no API cost).
Cells:
  json  x parse  (sanity control)
  sutra x parse  (readable SUTRA, current syntax)
  sutra x emit
  c1    x parse  (winner family: letters + folded route + Karaka slots + entities)
  c1    x emit
  c1    x emit-novel  (3 messages with values NOT in the entity table)

Scoring: parse outputs are parsed as JSON and compared field-by-field against
the canonical message; emit outputs are decoded with the real dialect decoders
(repo parser for SUTRA; sweep2 decoder for C1) and compared to canonical.
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

import tiktoken  # noqa: E402

from corpus import MESSAGES  # noqa: E402
from renderers import render_json, render_sutra_current  # noqa: E402
import sweep2 as S2  # noqa: E402

ENC = tiktoken.get_encoding("o200k_base")
tok = lambda s: len(ENC.encode(s))
C1_CFG = {"kw": "l1", "route": "fold", "delta": "off", "numbers": "dec", "wire": "text"}

SPEC_SUTRA = """SUTRA protocol (readable): statements are one of
INTENT pred(k=v, ...);  FACT pred(k=v, ...);  QUERY pred(k=v, ...) FROM "agent";
OFFER id="x" TO "agent" { give: {k: v}, want: {k: v} };
COUNTER "orig" id="x" TO "agent" { give: {...}, want: {...} };
ACCEPT "x";  REJECT "x" REASON "why";  COMMIT pred(k=v, ...) BY "date";  ACT pred(k=v, ...);
Optional header lines start with #, e.g. #from "buyer@home", #to "seller@store".
Strings are double-quoted; numbers bare."""

SPEC_C1 = """SUTRA-C1 protocol (compact):
Primitives: I INTENT, F FACT, Q QUERY, O OFFER, K COUNTER, A ACCEPT, R REJECT, C COMMIT, X ACT.
Routing: a statement with NO route prefix is directed buyer@home -> seller@store when the
primitive letter is lowercase; UPPERCASE means seller@store -> buyer@home. A broadcast keeps
a one-letter sender prefix CONCATENATED to the primitive: bI, sF (b buyer, s seller).
Arguments are positional, in fixed order, space-separated; use - for an absent middle slot:
  I buy <item> <max_price> <deadline>
  F available <item> <seller> <price>         F committed <id> <status>
  Q availability <item>
  C pay <amount> <to>                         X transfer <amount> <to>
  O <id> <give.money> <want.item> <want.brand>
  K <orig> <id> <give.money> <want.item>
  A <id>                R <id> (!reason optional, attached as !x)
OFFER/COUNTER have no predicate word. COMMIT deadline: append ~day (ordinal day number).
Entity table: a=SmartTV m=Samsung o=off-001 p=off-001-c z=off-999 g=signed h=price_too_high u=unsupported
Other values: bare if alphanumeric (letters/digits/@/./-), else double-quoted.
Numbers are decimal. Dates: for the deadline field use the ordinal day number
(2026-03-01 = 739676). in_reply_to is attached as ^id."""


def codex(prompt: str) -> str:
    r = subprocess.run(
        ["codex", "exec", "--skip-git-repo-check", prompt],
        capture_output=True, text=True, timeout=600, cwd="/tmp/opencode",
    )
    out = r.stdout
    # codex exec prints the answer plus a token-usage footer; take everything,
    # the caller extracts JSON.
    return out


def extract_json_array(text: str):
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ── canonical helpers ──────────────────────────────────────────────

def canon(m):
    out = {"primitive": m["primitive"], "predicate": m.get("predicate"),
           "args": dict(m["args"]), "from": m["from"], "to": m.get("to"),
           "extra": dict(m.get("extra", {}))}
    if m.get("body"):
        out["body"] = {k: dict(v) for k, v in m["body"].items()}
    return out


PRIM_EXPAND = {"I": "INTENT", "F": "FACT", "Q": "QUERY", "O": "OFFER", "K": "COUNTER",
               "A": "ACCEPT", "R": "REJECT", "C": "COMMIT", "X": "ACT"}


def _norm_date_field(key, v):
    import datetime as dt
    if key in ("deadline", "by") and isinstance(v, int):
        try:
            return dt.date.fromordinal(v).isoformat()
        except ValueError:
            return v
    return v


def parse_visible(guess, m, encoding):
    """Compare model-parsed fields against the canonical, without punishing
    information that the encoding does not carry (e.g. sender of a QUERY in
    readable SUTRA), and tolerating compact primitive letters."""
    if not isinstance(guess, dict):
        return False
    if isinstance(guess.get("primitive"), str) and guess["primitive"] in PRIM_EXPAND:
        guess = dict(guess, primitive=PRIM_EXPAND[guess["primitive"]])
    try:
        g = {
            "primitive": guess.get("primitive"),
            "predicate": guess.get("predicate"),
            "args": guess.get("args") or {},
            "from": guess.get("from"),
            "to": guess.get("to"),
            "extra": guess.get("extra") or {},
            "body": guess.get("body"),
        }
    except AttributeError:
        return False
    w = canon(m)
    if g["primitive"] != w["primitive"]:
        return False
    if (g["predicate"] or None) != (w["predicate"] or None):
        return False
    g_args = {k: _norm_date_field(k, n(v)) for k, v in g["args"].items() if v is not None}
    if g_args != {k: n(v) for k, v in w["args"].items()}:
        return False
    if g["body"] is not None or "body" in w:
        gb = g["body"] or {}
        wb = w.get("body", {})
        if {k: {kk: n(vv) for kk, vv in v.items()} for k, v in gb.items()} != wb:
            return False
    # routing: SUTRA readable cannot carry the envelope sender for Q/O/K
    p = w["primitive"]
    visible_from = not (p in ("QUERY", "OFFER", "COUNTER") and w.get("to")) or encoding == "c1"
    if visible_from and g["from"] != w["from"]:
        return False
    if w.get("to") and (g["to"] or None) != w["to"]:
        return False
    for k in ("reason", "by", "in_reply_to"):
        if w["extra"].get(k):
            gv = _norm_date_field(k, n(g["extra"].get(k)))
            if gv != n(w["extra"][k]):
                return False
    return True


def n(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def sutra_ast_to_canonical(src):
    from sutra.lexer import Lexer
    from sutra.parser import Parser

    prog = Parser(Lexer(src).tokenize()).parse()
    headers = {h.key: h.value for h in prog.headers}
    stmt = prog.statements[0]
    name = type(stmt).__name__

    def val(v):
        t = type(v).__name__
        if t == "StringVal":
            return v.value
        if t == "NumberVal":
            return n(v.value)
        if t == "BoolVal":
            return v.value
        if t == "NullVal":
            return None
        if t == "MapVal":
            return {k: val(x) for k, x in v.entries.items()}
        if t == "ListVal":
            return [val(x) for x in v.items]
        return None

    out = {"primitive": {"IntentStmt": "INTENT", "FactStmt": "FACT", "QueryStmt": "QUERY",
                         "OfferStmt": "OFFER", "CounterStmt": "COUNTER", "AcceptStmt": "ACCEPT",
                         "RejectStmt": "REJECT", "CommitStmt": "COMMIT", "ActStmt": "ACT"}[name],
           "predicate": None, "args": {}, "from": headers.get("from"), "to": None, "extra": {}}
    if hasattr(stmt, "predicate"):
        out["predicate"] = stmt.predicate.name
        out["args"] = {a.name: val(a.value) for a in stmt.predicate.args}
    if name == "QueryStmt":
        out["to"] = stmt.from_agent
    if name == "OfferStmt":
        out["args"] = {"id": stmt.offer_id}
        out["to"] = stmt.to_agent
        out["body"] = {f.key: val(f.value) for f in stmt.fields if f.key in ("give", "want")}
    if name == "CounterStmt":
        out["args"] = {"orig": stmt.original_offer_id, "id": stmt.offer_id}
        out["to"] = stmt.to_agent
        out["body"] = {f.key: val(f.value) for f in stmt.fields if f.key in ("give", "want")}
    if name == "AcceptStmt":
        out["args"] = {"id": stmt.offer_id}
    if name == "RejectStmt":
        out["args"] = {"id": stmt.offer_id}
        if stmt.reason:
            out["extra"]["reason"] = stmt.reason
    if name == "CommitStmt" and stmt.deadline:
        out["extra"]["by"] = stmt.deadline
    if "to" not in out or (out["to"] is None and "to" in headers):
        out["to"] = headers.get("to")
    return out


def decode_c1(text):
    sess = S2.Session()
    try:
        decoded = S2.text_decode(text.strip(), C1_CFG, sess)
        got = S2.resolve(decoded, C1_CFG, sess, "text")
        return canon(got)
    except Exception:
        return None


# ── tasks ───────────────────────────────────────────────────────────

def run_batch(task, encoding, messages, spec):
    if task == "parse":
        lines = []
        for i, m in enumerate(messages):
            enc = render_json(m) if encoding == "json" else (
                render_sutra_current(m) if encoding == "sutra" else S2.text_encode(m, C1_CFG, S2.Session()))
            enc = enc.replace("\n", " ")
            lines.append(f"{i+1}. {enc}")
        prompt = (f"{spec}\n\nDecode each numbered message into a JSON object with keys: "
                  f"primitive, predicate, args (object), from, to (null if absent), extra (object), "
                  f"body (only for OFFER/COUNTER). Schema per primitive: OFFER -> args={{id}}, "
                  f"COUNTER -> args={{orig,id}}, ACCEPT/REJECT -> args={{id}} with reason (if any) "
                  f"in extra.reason, COMMIT -> extra.by, QUERY/OFFERS set to as shown and from as "
                  f"the sender. Expand the primitive to its full English name "
                  f"(INTENT, FACT, QUERY, OFFER, COUNTER, ACCEPT, REJECT, COMMIT, ACT), write "
                  f"deadline/by as ISO dates (YYYY-MM-DD), and omit absent fields entirely "
                  f"(do not emit null values). Reply with ONLY a JSON array of "
                  f"{len(messages)} objects, same order. No markdown, no commentary.\n\n" + "\n".join(lines))
    else:
        lines = []
        for i, m in enumerate(messages):
            lines.append(f"{i+1}. {render_json(m)}")
        enc_name = "SUTRA" if encoding == "sutra" else "SUTRA-C1"
        prompt = (f"{spec}\n\nEncode each numbered JSON message as exactly one {enc_name} statement. "
                  f"Reply with ONLY a JSON array of {len(messages)} strings, same order. "
                  f"No markdown, no commentary.\n\n" + "\n".join(lines))
    out = codex(prompt)
    arr = extract_json_array(out)
    return prompt, out, arr


def run_cell(task, encoding, messages):
    spec = SPEC_SUTRA if encoding == "sutra" else SPEC_C1
    prompt, out, arr = run_batch(task, encoding, messages, spec)
    p_tok = tok(prompt)
    if arr is None or len(arr) != len(messages):
        print(f"  [{encoding}/{task}] model did not return a valid array; raw head: {out[:300]!r}")
        return {"correct": 0, "total": len(messages), "prompt_tokens": p_tok, "output_tokens": tok(out), "fail": "no-array"}
    correct = 0
    for i, m in enumerate(messages):
        if task == "parse":
            item = arr[i]
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except json.JSONDecodeError:
                    item = None
            ok = parse_visible(item, m, encoding)
        else:
            if encoding == "sutra":
                try:
                    got = sutra_ast_to_canonical(str(arr[i]))
                    ok = got == canon(m) or (parse_visible(got, m, "sutra") and all(
                        n(got["args"].get(k)) == n(v) for k, v in canon(m)["args"].items()))
                except Exception:
                    ok = False
            else:
                got = decode_c1(str(arr[i]))
                ok = got == canon(m)
        correct += 1 if ok else 0
    return {"correct": correct, "total": len(messages), "prompt_tokens": p_tok,
            "output_tokens": tok(out), "raw_output": out}


def main():
    results = {}
    cells = [
        ("parse", "json", MESSAGES),
        ("parse", "sutra", MESSAGES),
        ("emit", "sutra", MESSAGES),
        ("parse", "c1", MESSAGES),
        ("emit", "c1", MESSAGES),
    ]
    only = sys.argv[1:]
    if only:
        cells = [c for c in cells if c[0] in only or c[1] in only]
    for task, encoding, messages in cells:
        t0 = time.time()
        print(f"running {encoding}/{task} ({len(messages)} messages)...", flush=True)
        results[f"{encoding}/{task}"] = run_cell(task, encoding, messages) | {"seconds": round(time.time() - t0)}
        r = results[f"{encoding}/{task}"]
        print(f"  -> {r['correct']}/{r['total']} correct, prompt {r['prompt_tokens']} tok, out {r['output_tokens']} tok")

    print("\n=== comprehension results ===")
    print(f"{'cell':<14}{'correct':>9}{'prompt tok':>12}{'out tok':>9}{'spec tok':>10}")
    print(f"{'SPEC_SUTRA':<14}{'':>9}{'':>12}{'':>9}{tok(SPEC_SUTRA):>10}")
    print(f"{'SPEC_C1':<14}{'':>9}{'':>12}{'':>9}{tok(SPEC_C1):>10}")
    for k, r in results.items():
        print(f"{k:<14}{r['correct']}/{r['total']:<7}{r['prompt_tokens']:>12}{r['output_tokens']:>9}")
    (HERE / "results-comprehension.json").write_text(json.dumps(results, indent=1))
    print("saved results-comprehension.json")


if __name__ == "__main__":
    main()
