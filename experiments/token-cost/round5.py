"""Round 5 — error bars, reasoning-effort axis, novel entities, full logging.

Every model call is logged to experiments/token-cost/logs/round5/:
  - one file per call with metadata + full prompt + full raw output
  - index.jsonl with one record per call (scores, tokens, failure reasons)
  - summary.json with the aggregated results

Cells: 12-message corpus + 3 novel messages (values outside the entity table).
Backends: the local codex CLI at reasoning effort xhigh (default) and low.
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

from corpus import MESSAGES  # noqa: E402
from renderers import render_json, render_sutra_current  # noqa: E402
from comprehension import (  # noqa: E402
    SPEC_SUTRA, SPEC_C1, tok, canon, parse_visible, decode_c1,
    sutra_ast_to_canonical, extract_json_array, PRIM_EXPAND,
)
import sweep2 as S2  # noqa: E402

C1_CFG = {"kw": "l1", "route": "fold", "delta": "off", "numbers": "dec", "wire": "text"}
LOGDIR = HERE / "logs" / "round5"
LOGDIR.mkdir(parents=True, exist_ok=True)

NOVEL = [
    {"id": "n1-query-laptop", "primitive": "QUERY", "predicate": "availability",
     "args": [("item", "Laptop")], "from": "buyer@home", "to": "seller@store", "extra": {}},
    {"id": "n2-fact-laptop", "primitive": "FACT", "predicate": "available",
     "args": [("item", "Laptop"), ("seller", "seller@store"), ("price", 33000)],
     "from": "seller@store", "to": None, "extra": {}},
    {"id": "n3-offer-asus", "primitive": "OFFER", "predicate": None,
     "args": [("id", "off-777")],
     "body": {"give": [("money", 30000)], "want": [("item", "Laptop"), ("brand", "Asus")]},
     "from": "buyer@home", "to": "seller@store", "extra": {}},
]

CELLS = [
    ("xhigh", "parse", "json", MESSAGES, 1, ""),
    ("xhigh", "parse", "sutra", MESSAGES, 3, ""),
    ("xhigh", "emit", "sutra", MESSAGES, 3, ""),
    ("xhigh", "parse", "c1", MESSAGES, 3, ""),
    ("xhigh", "emit", "c1", MESSAGES, 3, ""),
    ("low", "parse", "c1", MESSAGES, 2, ""),
    ("low", "emit", "c1", MESSAGES, 2, ""),
    ("xhigh", "emit", "c1", NOVEL, 2, "novel"),
    ("xhigh", "parse", "c1", NOVEL, 2, "novel"),
]


def call_codex(prompt: str, effort: str) -> str:
    cmd = ["codex", "exec", "--skip-git-repo-check"]
    if effort == "low":
        cmd += ["-c", 'model_reasoning_effort="low"']
    cmd.append(prompt)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd="/tmp/opencode")
    return proc.stdout


def build_prompt(task, encoding, messages):
    if task == "parse":
        lines = []
        for i, m in enumerate(messages):
            enc = render_json(m) if encoding == "json" else (
                render_sutra_current(m) if encoding == "sutra" else S2.text_encode(m, C1_CFG, S2.Session()))
            lines.append(f"{i+1}. {enc.replace(chr(10), ' ')}")
        spec = SPEC_SUTRA if encoding == "sutra" else SPEC_C1
        return (f"{spec}\n\nDecode each numbered message into a JSON object with keys: "
                f"primitive, predicate, args (object), from, to (null if absent), extra (object), "
                f"body (only for OFFER/COUNTER). Schema per primitive: OFFER -> args={{id}}, "
                f"COUNTER -> args={{orig,id}}, ACCEPT/REJECT -> args={{id}} with reason (if any) "
                f"in extra.reason, COMMIT -> extra.by. Expand the primitive to its full English "
                f"name in upper case (write INTENT, not Intent), write deadline/by as ISO dates "
                f"(YYYY-MM-DD), and omit absent fields entirely (no null values). "
                f"Reply with ONLY a JSON array of {len(messages)} objects, same order. "
                f"No markdown, no commentary.\n\n" + "\n".join(lines))
    lines = [f"{i+1}. {render_json(m)}" for i, m in enumerate(messages)]
    spec = SPEC_SUTRA if encoding == "sutra" else SPEC_C1
    enc_name = "SUTRA" if encoding == "sutra" else "SUTRA-C1"
    return (f"{spec}\n\nEncode each numbered JSON message as exactly one {enc_name} statement. "
            f"Reply with ONLY a JSON array of {len(messages)} strings, same order. "
            f"No markdown, no commentary.\n\n" + "\n".join(lines))


def diagnose_parse(item, m, encoding):
    from comprehension import norm_primitive, norm_word
    if isinstance(item, str):
        try:
            item = json.loads(item)
        except json.JSONDecodeError:
            return False, "not-object"
    if not isinstance(item, dict):
        return False, "not-object"
    item = dict(item, primitive=norm_primitive(item.get("primitive")))
    w = canon(m)
    if item.get("primitive") != w["primitive"]:
        return False, "primitive"
    if norm_word(item.get("predicate")) != norm_word(w.get("predicate")):
        return False, "predicate"
    try:
        visible = parse_visible(item, m, encoding)
    except Exception:  # noqa: BLE001
        return False, "shape"
    if visible:
        return True, ""
    gargs = {k: v for k, v in (item.get("args") or {}).items() if v is not None}
    if gargs != w["args"]:
        return False, "args"
    if "body" in w or item.get("body"):
        return False, "body"
    p = w["primitive"]
    visible_from = not (p in ("QUERY", "OFFER", "COUNTER") and w.get("to")) or encoding == "c1"
    if visible_from and item.get("from") != w["from"]:
        return False, "from"
    if w.get("to") and (item.get("to") or None) != w["to"]:
        return False, "to"
    return False, "extra"


def diagnose_emit(item, m, encoding):
    if not isinstance(item, str):
        return False, "not-string"
    if encoding == "sutra":
        try:
            got = sutra_ast_to_canonical(item)
        except Exception:
            return False, "undecodable"
        return (True, "") if parse_visible(got, m, "sutra") else (False, "fields")
    got = decode_c1(item)
    if got is None:
        return False, "undecodable"
    return (True, "") if parse_visible(got, m, "c1") else (False, "fields")


def run_call(effort, task, encoding, messages, rep, tag):
    cell = f"{encoding}/{task}" + (f"-{tag}" if tag else "")
    fname = f"{cell.replace('/', '-')}@{effort}--r{rep}"
    prompt = build_prompt(task, encoding, messages)
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "round": 5, "backend": "codex",
              "model": "gpt-6-luna", "effort": effort, "cell": cell, "rep": rep,
              "messages": [m["id"] for m in messages],
              "prompt_tokens": tok(prompt)}
    try:
        out = call_codex(prompt, effort)
    except subprocess.TimeoutExpired:
        record.update({"correct": 0, "total": len(messages), "error": "timeout", "output_tokens": 0})
        (LOGDIR / f"{fname}.txt").write_text(f"PROMPT:\n{prompt}\n\nERROR: timeout\n")
        return record
    record["output_tokens"] = tok(out)
    arr = extract_json_array(out)
    per_message = []
    correct = 0
    if arr is None or len(arr) != len(messages):
        record["error"] = "no-array"
        for m in messages:
            per_message.append({"id": m["id"], "ok": False, "why": "no-array"})
    else:
        for m, item in zip(messages, arr):
            if task == "parse":
                ok, why = diagnose_parse(item, m, encoding)
            else:
                ok, why = diagnose_emit(item, m, encoding)
            per_message.append({"id": m["id"], "ok": ok, "why": why})
            correct += 1 if ok else 0
    record["correct"] = correct
    record["total"] = len(messages)
    record["per_message"] = per_message
    record["log_file"] = str(LOGDIR / f"{fname}.txt")
    (LOGDIR / f"{fname}.txt").write_text(
        f"META: {json.dumps({k: v for k, v in record.items() if k not in ('per_message','log_file')})}\n"
        f"PER-MESSAGE: {json.dumps(per_message)}\n\nPROMPT:\n{prompt}\n\n---OUTPUT---\n{out}\n")
    return record


def preflight_novel():
    for m in NOVEL:
        enc = S2.text_encode(m, C1_CFG, S2.Session())
        got = decode_c1(enc)
        if got != canon(m):
            print(f"PREFLIGHT FAIL for {m['id']}: {enc}")
            sys.exit(1)
    print(f"preflight: {len(NOVEL)} novel messages round-trip in C1")


def main():
    preflight_novel()
    index = []
    for effort, task, encoding, messages, reps, tag in CELLS:
        for rep in range(1, reps + 1):
            t0 = time.time()
            record = run_call(effort, task, encoding, messages, rep, tag)
            index.append(record)
            with open(LOGDIR / "index.jsonl", "a") as f:
                f.write(json.dumps(record) + "\n")
            print(f"{record['cell']:<16}@{record['effort']:<6} r{record['rep']}  "
                  f"{record['correct']}/{record['total']}  out {record['output_tokens']:>4} tok  "
                  f"({time.time() - t0:.0f}s)")

    summary = {}
    for rec in index:
        key = f"{rec['cell']}@{rec['effort']}"
        summary.setdefault(key, {"reps": [], "failures": {}})
        summary[key]["reps"].append(f"{rec['correct']}/{rec['total']}")
        for pm in rec.get("per_message", []):
            if not pm["ok"]:
                summary[key]["failures"][pm["why"]] = summary[key]["failures"].get(pm["why"], 0) + 1
    for key, val in summary.items():
        accs = [int(r.split("/")[0]) / int(r.split("/")[1]) for r in val["reps"]]
        val["mean"] = round(sum(accs) / len(accs), 3)
        val["min"] = min(accs)
        val["max"] = max(accs)
    (LOGDIR / "summary.json").write_text(json.dumps(summary, indent=1))
    print()
    print(f"{'cell':<26}{'reps':<22}{'mean':>6}{'min':>7}{'max':>7}  failures")
    for key, val in summary.items():
        print(f"{key:<26}{','.join(val['reps']):<22}{val['mean']:>6.2f}{val['min']:>7.2f}{val['max']:>7.2f}  "
              f"{val['failures'] or ''}")
    print(f"\nlogs: {LOGDIR}")


if __name__ == "__main__":
    main()
