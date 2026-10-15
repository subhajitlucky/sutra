"""Round 7 — the Pop Quiz on three robot families + the Oops Button.

Backends (all verified working on this machine, no API billing):
  codex    -> gpt-6-luna       (ChatGPT plan)
  gemini   -> agy (Antigravity CLI)
  deepseek -> opencode run -m opencode-go/deepseek-v4.1-flash

Cells per backend:
  c1/parse    12 messages -> JSON          (space-separated compact form)
  c1/emit     12 messages JSON -> strings
  meter/parse  6 dialogue payloads -> JSON (fixed-width concatenated form)
  meter/emit   6 JSON messages -> payloads

Everything is logged to logs/round7/ (per-call files, index.jsonl, summary).
Also measures the Oops Button: the cost of one surprise message outside the
negotiated template (resync marker + full message).
"""

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

import tiktoken  # noqa: E402

from corpus import MESSAGES, DIALOGUE  # noqa: E402
from renderers import render_json  # noqa: E402
from comprehension import (  # noqa: E402
    SPEC_C1, tok, canon, parse_visible, extract_json_array, norm_primitive, norm_word,
)
import sweep2 as S2  # noqa: E402
import sweep3 as S3  # noqa: E402
from round5 import build_prompt as build_c1_prompt  # noqa: E402

LOGDIR = HERE / "logs" / "round7"
LOGDIR.mkdir(parents=True, exist_ok=True)

C1 = {"kw": "l1", "route": "fold", "delta": "values", "numbers": "b36", "wire": "text"}
C1_DEC = {**C1, "numbers": "dec"}

METER_SPEC = """SUTRA-C1 meter mode (fixed-width concatenation).
Negotiation template (the 6-message deal, agreed once):
 1 QUERY availability buyer->seller      4 COUNTER seller->buyer
 2 FACT available seller->buyer (reply)  5 ACCEPT buyer->seller
 3 OFFER buyer->seller                   6 COMMIT pay buyer->seller
Per-message fields in order, concatenated with NO separators:
 QUERY: item
 FACT: item seller price          (seller implied by the template)
 OFFER: id give.money want.item want.brand
 COUNTER: orig id give.money want.item
 ACCEPT: id
 COMMIT: amount to by             (to implied; by = deadline)
Values: a=SmartTV m=Samsung o=off-001 p=off-001-c z=off-999 g=signed
h=price_too_high u=unsupported; numbers are decimal zero-padded to 5 digits
(money/price/amount) or 6 digits (deadline as an ordinal day, 2026-03-01 =
739676). '.' means: same value as the previous message for this field.
'-' means the field is absent. Implied fields (counterparty addresses,
in_reply_to) are never transmitted. Example payloads: 'a' (the whole QUERY);
'.-48000' (reply fact); 'o48000am' (a complete OFFER); 'a' 'o' etc."""

_BY_ID = {m["id"]: m for m in MESSAGES}
DIALOGUE_MSGS = [_BY_ID[i] for i in DIALOGUE]  # dialogue order, aligned with TEMPLATE_SCRIPT
ROUTES = [0, 1, 0, 1, 0, 0]


# ── backends ───────────────────────────────────────────────────────

def call_codex(prompt):
    proc = subprocess.run(["codex", "exec", "--skip-git-repo-check", prompt],
                          capture_output=True, text=True, timeout=900, cwd="/tmp/opencode")
    return proc.stdout


def call_gemini(prompt):
    # --dangerously-skip-permissions is required for agy print mode (headless
    # auto-denies tool permissions). The prompt must be attached to -p with =.
    proc = subprocess.run(["agy", "--dangerously-skip-permissions", f"-p={prompt}"],
                          capture_output=True, text=True, timeout=900, cwd="/tmp/opencode")
    # agy writes its answer to stderr in print mode; keep both streams.
    return (proc.stdout or "") + (proc.stderr or "")


def call_deepseek(prompt):
    proc = subprocess.run(["opencode", "run", "-m", "opencode-go/deepseek-v4.1-flash", prompt],
                          capture_output=True, text=True, timeout=900, cwd="/tmp/opencode")
    return proc.stdout


BACKENDS = {"codex": call_codex, "gemini": call_gemini, "deepseek": call_deepseek}


# ── prompts ────────────────────────────────────────────────────────

def meter_prompt(task):
    if task == "parse":
        sess = S2.Session()
        payloads = [S3.payload_encode_meter(m, C1_DEC, sess)[0] for m in DIALOGUE_MSGS]
        lines = "\n".join(f"{i+1}. {p}" for i, p in enumerate(payloads))
        return (f"{METER_SPEC}\n\nDecode the six dialogue payloads below into a JSON array "
                f"of 6 message objects with keys: primitive, predicate, args (object), from, to, "
                f"extra (object), body (only for OFFER/COUNTER); expand primitive names in upper "
                f"case; deadline/by as ISO dates; include implied fields (from, to, in_reply_to). "
                f"Reply with ONLY the JSON array, no markdown.\n\n{lines}")
    lines = "\n".join(f"{i+1}. {render_json(m)}" for i, m in enumerate(DIALOGUE_MSGS))
    return (f"{METER_SPEC}\n\nEncode each numbered JSON message as one meter payload string "
            f"(no separators). Reply with ONLY a JSON array of 6 strings, same order, "
            f"no markdown.\n\n{lines}")


# ── scoring ────────────────────────────────────────────────────────

ADDR = {"buyer": "buyer@home", "seller": "seller@store",
        "b": "buyer@home", "s": "seller@store"}


def norm_addr(v):
    if isinstance(v, str):
        return ADDR.get(v.strip().lower(), v)
    return v


def lenient(item, m, idx, messages, encoding):
    """Documented tolerances, applied equally to every model:
    - a predicate that merely echoes the primitive (OFFER -> "offer") is
      redundant, not wrong;
    - in_reply_to given as a 1-based message index refers to the same thread
      as the canonical message id.
    """
    item = dict(item)
    if encoding == "meter" and isinstance(item.get("predicate"), str) \
            and isinstance(item.get("primitive"), str) \
            and item["predicate"].strip().lower() == item["primitive"].strip().lower():
        item["predicate"] = None
    extra = dict(item.get("extra") or {})
    r = extra.get("in_reply_to")
    if isinstance(r, int) and 1 <= r <= len(messages):
        extra["in_reply_to"] = messages[r - 1]["id"]
    item["extra"] = extra
    return item


def score_parse(items, messages, encoding):
    results = []
    for idx, (m, item) in enumerate(zip(messages, items)):
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError:
                results.append((False, "not-object"))
                continue
        if not isinstance(item, dict):
            results.append((False, "not-object"))
            continue
        item = dict(item, primitive=norm_primitive(item.get("primitive")),
                    **{"from": norm_addr(item.get("from")), "to": norm_addr(item.get("to"))})
        item = lenient(item, m, idx, messages, encoding)
        if item.get("primitive") != m["primitive"]:
            results.append((False, "primitive"))
            continue
        if norm_word(item.get("predicate")) != norm_word(m.get("predicate")):
            results.append((False, "predicate"))
            continue
        try:
            ok = parse_visible(item, m, encoding)
        except Exception:  # noqa: BLE001
            ok = False
        results.append((ok, "" if ok else "fields"))
    return results


def _decode_meter_sequence(items):
    """Decode 6 payloads in sequence; return per-message correctness."""
    sess = S2.Session()
    results = []
    for idx in range(min(len(items), 6)):
        prim, pred, reply_to = S3.TEMPLATE_SCRIPT[idx]
        try:
            text = str(items[idx]).replace(" ", "").replace("\n", "")
            dec = S3.payload_decode_meter(text, prim, pred, ROUTES[idx], reply_to, C1_DEC, sess)
            got = S2.resolve(dec, C1_DEC, sess, "text")
            results.append(bool(parse_visible(canon(got), DIALOGUE_MSGS[idx], "c1")))
        except Exception:  # noqa: BLE001
            results.append(False)
    return results


def score_emit_meter(items):
    """Strict (order preserved) + order-tolerant (best permutation) scores.

    Models sometimes reorder the emitted payloads; both readings are reported
    so the order failure is visible instead of hiding inside one number.
    """
    from itertools import permutations
    strict = _decode_meter_sequence(items)
    best = max(sum(_decode_meter_sequence([items[i] for i in perm]))
               for perm in permutations(range(len(items))))
    results = [(ok, "" if ok else "fields") for ok in strict]
    results.append(("TOLERANT", best))  # sentinel consumed by the caller
    return results


def score_emit_c1(items):
    from comprehension import decode_c1
    results = []
    for m, item in zip(MESSAGES, items):
        got = decode_c1(str(item))
        ok = got is not None and parse_visible(got, m, "c1")
        results.append((bool(ok), "" if ok else "fields"))
    return results


# ── runner ─────────────────────────────────────────────────────────

def run_cell(backend_name, task, encoding):
    if encoding == "c1":
        prompt = build_c1_prompt(task, "c1", MESSAGES)
    else:
        prompt = meter_prompt(task)
    messages = MESSAGES if encoding == "c1" else DIALOGUE_MSGS
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "round": 7, "backend": backend_name,
              "cell": f"{encoding}/{task}", "prompt_tokens": tok(prompt)}
    try:
        out = BACKENDS[backend_name](prompt)
    except subprocess.TimeoutExpired:
        record.update({"correct": 0, "total": len(messages), "error": "timeout", "output_tokens": 0})
        return record
    record["output_tokens"] = tok(out)
    arr = extract_json_array(out)
    if arr is None or len(arr) != len(messages):
        record["error"] = "no-array"
        record["correct"] = 0
        record["total"] = len(messages)
    else:
        if task == "parse":
            per = score_parse(arr, messages, "c1")
            record["correct"] = sum(1 for ok, _ in per if ok)
            record["total"] = len(messages)
            record["failures"] = [why for ok, why in per if not ok]
        elif encoding == "meter":
            per = score_emit_meter(arr)
            record["correct"] = sum(1 for ok, _ in per[:-1] if ok)
            record["total"] = len(messages)
            record["tolerant"] = per[-1][1]
            record["failures"] = [why for ok, why in per[:-1] if not ok]
        else:
            per = score_emit_c1(arr)
            record["correct"] = sum(1 for ok, _ in per if ok)
            record["total"] = len(messages)
            record["failures"] = [why for ok, _ in per if not ok]
    fname = f"{backend_name}--{encoding}-{task}.txt"
    (LOGDIR / fname).write_text(
        f"META: {json.dumps({k: v for k, v in record.items() if k != 'raw'})}\n\n"
        f"PROMPT:\n{prompt}\n\n---OUTPUT---\n{out}\n")
    record["log_file"] = fname
    return record


def oops_button():
    """Cost of one surprise message outside the template."""
    import datetime as dt
    # surprise: a REJECT with a reason, sent seller->buyer, out of sequence
    surprise = {"primitive": "REJECT", "predicate": None, "args": [("id", "off-001-c")],
                "from": "seller@store", "to": "buyer@home", "extra": {"reason": "price_too_low"}}
    # C1 rendering with a resync marker (!) meaning "template break, full message follows"
    baseline = {"primitive": "REJECT", "predicate": None, "args": [("id", "off-001-c")],
                "from": "seller@store", "to": "buyer@home", "extra": {"reason": "price_too_low"}}
    sess = S2.Session()
    # prime state so 'o'/'p' are known handles
    S2.text_encode({"primitive": "FACT", "predicate": "available",
                    "args": [("item", "SmartTV"), ("seller", "seller@store"), ("price", 48000)],
                    "from": "seller@store", "to": None, "extra": {}}, C1, sess)
    S2.text_encode({"primitive": "OFFER", "predicate": None, "args": [("id", "off-001")],
                    "body": {"give": [("money", 48000)], "want": [("item", "SmartTV"), ("brand", "Samsung")]},
                    "from": "buyer@home", "to": "seller@store", "extra": {}}, C1, sess)
    full = S2.text_encode(surprise, C1, sess)
    resync = "!" + full.replace(" ", "")
    return {"full_c1": full, "resync": resync,
            "resync_tokens": tok(resync), "regular_c1_tokens": tok(full)}


def main():
    only = sys.argv[1:]
    print("=== pop quiz: c1 + meter across three robots ===")
    summary = {}
    for backend in [b for b in BACKENDS if not only or b in only]:
        for encoding in ("c1", "meter"):
            for task in ("parse", "emit"):
                t0 = time.time()
                rec = run_cell(backend, task, encoding)
                key = f"{backend} {encoding}/{task}"
                summary[key] = f"{rec['correct']}/{rec['total']}"
                print(f"{key:<22} {rec['correct']}/{rec['total']}  "
                      f"out {rec.get('output_tokens', 0):>4} tok  ({time.time() - t0:.0f}s)"
                      + (f"  errors: {rec.get('failures')}" if rec.get("failures") else ""))
                with open(LOGDIR / "index.jsonl", "a") as f:
                    f.write(json.dumps(rec) + "\n")

    print("\n=== oops button (surprise message cost) ===")
    oops = oops_button()
    print(f"   regular resync+full message: {oops['resync']!r}  ({oops['resync_tokens']} tokens)")
    print(f"   same message in template mode: ~3 tokens -> a surprise costs "
          f"~{oops['resync_tokens'] - 3} extra tokens, once; the session continues cheap after")

    (LOGDIR / "summary.json").write_text(json.dumps({"cells": summary, "oops": oops}, indent=1))
    print(f"\nlogs: {LOGDIR}")


if __name__ == "__main__":
    main()
