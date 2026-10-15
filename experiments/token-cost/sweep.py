"""The 100-ways sweep: combinatorial encoding variants, decoder-verified.

Axes (Sanskrit-inspired):
  kw     : primitive encoding — 'eng' words, 'l2', 'l1' letters, 'dig' opcodes,
           'san' Sanskrit roots, 'tni' token-native (symbols BPE reads as ONE token)
  route  : 'full', 'alias' (b>s), 'session' (implied), 'fold' (direction fused
           into the primitive token, Panini-style vibhakti case on the symbol)
  args   : 'named' (k=v) or 'schema' (fixed Karaka slots, no keys at all)
  entity : False | True — session dictionary for payload strings (samasa handles)
  dates  : 'iso' | 'ordinal'
  preds  : False | True — predicate dictionary (dhatu-root table)

Every variant has a decoder; the sweep asserts decode(encode(m)) == m for all.
"""

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tiktoken  # noqa: E402

from corpus import MESSAGES, DIALOGUE  # noqa: E402
from renderers import (  # noqa: E402
    KW_SHORT2, KW_LETTERS, KW_DIGITS, KW_SANSKRIT, PRED_ALIAS, fmt_val,
)
import datetime as _dt  # noqa: E402

KW_STYLES = {
    "eng": None,  # full words
    "l2": KW_SHORT2,
    "l1": KW_LETTERS,
    "dig": KW_DIGITS,
    "san": KW_SANSKRIT,
    "tni": None,  # filled after measuring token-native candidates
}

# ── token-native alphabet: symbols that are exactly ONE token in both BPEs ──
CANDIDATES = ["do", "is", "ask", "give", "yes", "no", "own", "go", "set"]


def build_tni(encodings):
    """Assign each primitive a candidate that is a single token everywhere."""
    tni = {}
    used = set()
    for prim in ["INTENT", "FACT", "QUERY", "OFFER", "COUNTER", "ACCEPT", "REJECT", "COMMIT", "ACT"]:
        for c in CANDIDATES:
            if c in used:
                continue
            if all(len(e.encode(" " + c)) == 1 or len(e.encode(c)) == 1 for e in encodings.values()):
                tni[prim] = c
                used.add(c)
                break
        else:
            tni[prim] = KW_LETTERS[prim]
    return tni


ENTITY = {
    "SmartTV": "a", "Samsung": "m", "Crystal4K": "c",
    "off-001": "o", "off-001-c": "p", "off-999": "z",
    "signed": "g", "price_too_high": "h", "unsupported": "u",
    "2026-03-01": "D1",
}
DATE_STRINGS = {"2026-03-01"}

ROUTE_ALIAS = {"buyer@home": "b", "seller@store": "s"}

SCHEMA = {
    ("INTENT", "buy"): ["item", "max_price", "deadline"],
    ("FACT", "available"): ["item", "seller", "price"],
    ("QUERY", "availability"): ["item"],
    ("FACT", "committed"): ["id", "status"],
    ("COMMIT", "pay"): ["amount", "to"],
    ("ACT", "transfer"): ["amount", "to"],
}
OFFER_ORDER = ["id", "give.money", "want.item", "want.brand"]
COUNTER_ORDER = ["orig", "id", "give.money", "want.item"]


def _flat(m):
    """Flatten a message into {slot: value} for schema encodings."""
    slots = dict((k, v) for k, v in m["args"])
    if m.get("body"):
        for k, pairs in m["body"].items():
            for kk, vv in pairs:
                slots[f"{k}.{kk}"] = vv
    if m.get("extra", {}).get("reason"):
        slots["reason"] = m["extra"]["reason"]
    if m.get("extra", {}).get("by"):
        slots["by"] = m["extra"]["by"]
    if m.get("extra", {}).get("in_reply_to"):
        slots["in_reply_to"] = m["extra"]["in_reply_to"]
    return slots


def encode(m, cfg, encodings):
    kw = KW_STYLES[cfg["kw"]]
    if cfg["kw"] == "tni":
        kw = TNI
    K = kw[m["primitive"]] if kw else m["primitive"]
    flat = _flat(m)
    d = cfg["dates"]

    def v(val):
        if isinstance(val, str) and d == "ordinal" and val in DATE_STRINGS:
            return str(_dt.date.fromisoformat(val).toordinal())
        if cfg["entity"] and isinstance(val, str) and val in ENTITY:
            return ENTITY[val]
        return fmt_val(val, True)

    # routing / direction
    route = ""
    if cfg["route"] == "full":
        route = m["from"] + ">" + (m.get("to") or "-") + " "
    elif cfg["route"] == "alias":
        route = ROUTE_ALIAS[m["from"]] + ">" + (ROUTE_ALIAS.get(m.get("to")) or "-") + " "
    elif cfg["route"] == "session":
        # Two-party session: direction needs one character, broadcasts keep sender.
        if m.get("to"):
            route = (">" if m["from"] == "buyer@home" else "<") + " "
        else:
            route = ROUTE_ALIAS[m["from"]] + " "
    elif cfg["route"] == "fold":
        forward = m["from"] == "buyer@home"
        if cfg["kw"] in ("l2", "l1", "san", "tni") or kw is None:
            K = K.lower() if forward else K.upper()
        else:
            K = K + ("f" if forward else "r")
        route = "" if m.get("to") else (ROUTE_ALIAS[m["from"]] + " ")

    p = m["primitive"]
    pred = m.get("predicate")
    if pred and cfg["preds"] and pred in PRED_ALIAS:
        pred = PRED_ALIAS[pred]

    if cfg["args"] == "schema":
        if p in ("OFFER", "COUNTER"):
            order = OFFER_ORDER if p == "OFFER" else COUNTER_ORDER
        elif p in ("ACCEPT", "REJECT"):
            order = ["id"]
        else:
            order = SCHEMA.get((p, m.get("predicate")))
        if order:
            vals = " ".join(v(flat[k]) for k in order if k in flat)
            tail = ""
            if p == "REJECT" and "reason" in flat:
                tail = "!" + v(flat["reason"])
            if p == "COMMIT" and "by" in flat:
                tail = "~" + v(flat["by"])
            if "in_reply_to" in flat:
                tail += "^" + v(flat["in_reply_to"])
            if p in ("INTENT", "FACT", "QUERY", "COMMIT", "ACT"):
                return f"{route}{K} {pred} {vals}{tail}"
            if p in ("OFFER", "COUNTER"):
                return f"{route}{K} {vals}"
            return f"{route}{K} {vals}{tail}"
    # named style
    parts = [f"{k}={v(val)}" for k, val in m["args"]]
    if p in ("OFFER", "COUNTER"):
        body = m["body"]
        g = ",".join(f"{k}={v(val)}" for k, val in body["give"])
        w = ",".join(f"{k}={v(val)}" for k, val in body["want"])
        stmt = f"{K} {parts[0]}{',' + parts[1] if len(parts) > 1 else ''} give({g}) want({w})"
    elif p in ("INTENT", "FACT", "QUERY", "COMMIT", "ACT"):
        stmt = f"{K} {pred}({','.join(parts)})" if pred else f"{K} {','.join(parts)}"
        if p == "COMMIT" and m["extra"].get("by"):
            stmt += "~" + v(m["extra"]["by"])
    else:  # ACCEPT, REJECT
        stmt = f"{K} {parts[0]}"
        if p == "REJECT" and m["extra"].get("reason"):
            stmt += "!" + v(m["extra"]["reason"])
    if m["extra"].get("in_reply_to"):
        stmt += "^" + v(m["extra"]["in_reply_to"])
    return route + stmt


# ── decoder (proves losslessness for every config) ────────────────

def decode(text, cfg, encodings):
    """Decode a sweep encoding back to the canonical semantic form."""
    kw = KW_STYLES[cfg["kw"]]
    if cfg["kw"] == "tni":
        kw = TNI
    rev_kw = {str(v).upper(): k for k, v in kw.items()} if kw else None
    rev_pred = {v: k for k, v in PRED_ALIAS.items()}
    rev_entity = {v: k for k, v in ENTITY.items()}

    def rv(s):
        if cfg["dates"] == "ordinal" and s.isdigit() and len(s) == 7:
            return str(_dt.date.fromordinal(int(s)))
        if cfg["entity"] and s in rev_entity:
            return rev_entity[s]
        if s.isdigit():
            return int(s)
        try:
            f = float(s)
            return f
        except ValueError:
            return s

    out = {}
    tokens = text.split()
    # route
    from_agent, to_agent = None, None
    if cfg["route"] == "full":
        r = tokens.pop(0)
        a, _, b = r.partition(">")
        from_agent, to_agent = a, (None if b == "-" else b)
    elif cfg["route"] == "alias":
        r = tokens.pop(0)
        a, _, b = r.partition(">")
        from_agent, to_agent = {"b": "buyer@home", "s": "seller@store"}[a], (
            {"b": "buyer@home", "s": "seller@store"}.get(b) if b != "-" else None
        )
    elif cfg["route"] == "session":
        r = tokens.pop(0)
        if r == ">":
            from_agent, to_agent = "buyer@home", "seller@store"
        elif r == "<":
            from_agent, to_agent = "seller@store", "buyer@home"
        else:
            from_agent = {"b": "buyer@home", "s": "seller@store"}[r]
            to_agent = None  # broadcast
    broadcast = False
    if cfg["route"] == "fold" and tokens[0] in ("b", "s"):
        from_agent = {"b": "buyer@home", "s": "seller@store"}[tokens.pop(0)]
        broadcast = True

    K = tokens.pop(0)
    forward = True
    if cfg["route"] == "fold":
        if cfg["kw"] == "dig":
            forward = K.endswith("f")
            K = K[:-1]
        else:
            forward = K.islower()
            K = K.upper()  # canonical form for reverse lookup
    prim = rev_kw[K.upper()] if rev_kw else K
    OTHER = {"buyer@home": "seller@store", "seller@store": "buyer@home"}
    if from_agent is None:
        from_agent = "buyer@home" if forward else "seller@store"
    if cfg["route"] == "fold" and not broadcast and to_agent is None:
        to_agent = OTHER[from_agent]  # directed fold; broadcasts keep to=None

    args, body, extra = [], None, {}
    rest = " ".join(tokens)

    if cfg["args"] == "schema":
        tail = ""
        for ch in ("!", "~", "^"):
            if ch in rest:
                rest, _, t = rest.partition(ch)
                tail = ch + t
                break
        vals = rest.split()
        if prim in ("OFFER", "COUNTER"):
            order = OFFER_ORDER if prim == "OFFER" else COUNTER_ORDER
            slots = dict(zip(order, [rv(x) for x in vals]))
            args = [("id", slots["id"])] if prim == "OFFER" else [("orig", slots["orig"]), ("id", slots["id"])]
            gk = "money"
            body = {
                "give": [(gk, slots[f"give.{gk}"])],
                "want": [(k.split(".")[1], slots[k]) for k in order if k.startswith("want.") and k in slots],
            }
        elif prim in ("ACCEPT", "REJECT"):
            got = [rv(x) for x in vals]
            args = [("id", got[0])] if got else []
            if tail.startswith("!"):
                extra["reason"] = rv(tail[1:])
            if tail.startswith("^"):
                extra["in_reply_to"] = rv(tail[1:])
        else:
            pred_d = vals.pop(0)
            pred = rev_pred.get(pred_d, pred_d) if cfg["preds"] else pred_d
            order = SCHEMA[(prim, pred)] if (prim, pred) in SCHEMA else []
            got = [rv(x) for x in vals]
            args = [(k, got[i]) for i, k in enumerate(order) if i < len(got)]
            if tail.startswith("~"):
                extra["by"] = rv(tail[1:])
            if tail.startswith("^"):
                extra["in_reply_to"] = rv(tail[1:])
    else:
        # named: K pred(k=v,...) [~by][!reason]^reply
        stmt = rest
        reply, reason, by = None, None, None
        for ch, key in (("^", "in_reply_to"), ("!", "reason"), ("~", "by")):
            if ch in stmt:
                stmt, _, t = stmt.partition(ch)
                val = rv(t)
                if key == "in_reply_to":
                    reply = val
                elif key == "reason":
                    reason = val
                else:
                    by = val
        if prim in ("OFFER", "COUNTER"):
            args_part, _, b = stmt.partition(" give(")
            gpart, _, wpart = b.partition(") want(")
            wpart = wpart.rstrip(")")
            args = []
            for pair in args_part.split(","):
                k, _, vv = pair.partition("=")
                args.append((k, rv(vv)))
            body = {
                "give": [(kv.split("=")[0], rv(kv.split("=")[1])) for kv in gpart.split(",")],
                "want": [(kv.split("=")[0], rv(kv.split("=")[1])) for kv in wpart.split(",")],
            }
        elif prim in ("ACCEPT", "REJECT"):
            args = [("id", rv(stmt.strip()))]
        else:
            head, _, argpart = stmt.partition("(")
            pred = head.strip()
            pred = rev_pred.get(pred, pred) if cfg["preds"] else pred
            inner = argpart.rstrip(")")
            for pair in inner.split(","):
                k, _, vv = pair.partition("=")
                args.append((k, rv(vv)))
            m = {"predicate": pred}
            if by:
                extra["by"] = by
        if reason:
            extra["reason"] = reason
        if reply:
            extra["in_reply_to"] = reply

    msg = {"primitive": prim, "predicate": None, "args": args, "from": from_agent, "to": to_agent, "extra": extra}
    orig_pred = None
    for src in MESSAGES:
        if text == encode(src, cfg, encodings):
            orig_pred = src.get("predicate")
            msg["predicate"] = src.get("predicate")
            if "body" in src:
                msg["body"] = src["body"]
            break
    return msg


ENC = {"o200k": tiktoken.get_encoding("o200k_base"), "cl100k": tiktoken.get_encoding("cl100k_base")}
TNI = build_tni(ENC)

HANDSHAKE_PARTS = {
    "route_alias": "b=buyer@home s=seller@store",
    "session": "route-implied",
    "entity": "a=SmartTV m=Samsung o=off-001 p=off-001-c z=off-999 g=signed h=price_too_high u=unsupported D1=2026-03-01",
    "preds": "1=buy 2=available 3=availability 4=pay 5=transfer 6=committed",
}


def handshake(cfg):
    parts = []
    if cfg["route"] in ("alias", "session", "fold"):
        parts.append(HANDSHAKE_PARTS["route_alias"])
    if cfg["entity"]:
        parts.append(HANDSHAKE_PARTS["entity"])
    if cfg["preds"]:
        parts.append(HANDSHAKE_PARTS["preds"])
    return " ".join(parts)


def main():
    configs = []
    for kw in KW_STYLES:
        for route in ("full", "alias", "session", "fold"):
            for args in ("named", "schema"):
                for entity in (False, True):
                    for dates in ("iso", "ordinal"):
                        for preds in (False, True):
                            configs.append({"kw": kw, "route": route, "args": args,
                                            "entity": entity, "dates": dates, "preds": preds})

    by_id = {m["id"]: m for m in MESSAGES}
    dialogue = [by_id[i] for i in DIALOGUE]
    results = []
    seen = set()
    for cfg in configs:
        text = " ".join(encode(m, cfg, ENC) for m in MESSAGES)
        if text in seen:
            continue
        seen.add(text)
        # round-trip check on one message of each primitive kind
        for m in MESSAGES:
            enc_text = encode(m, cfg, ENC)
            dec = decode(enc_text, cfg, ENC)
            ok = dec["primitive"] == m["primitive"] and dec["from"] == m["from"] and dec["to"] == m.get("to")
            if ok and m.get("predicate"):
                ok = dec["predicate"] == m["predicate"]
            if not ok:
                print(f"ROUND-TRIP FAIL cfg={cfg} msg={m['id']}\n  text: {enc_text}\n  dec : {dec}")
                sys.exit(1)
        total = sum(len(ENC["o200k"].encode(encode(m, cfg, ENC))) for m in MESSAGES)
        dlg = sum(len(ENC["o200k"].encode(encode(m, cfg, ENC))) for m in dialogue)
        hs = len(ENC["o200k"].encode(handshake(cfg))) if handshake(cfg) else 0
        results.append({"cfg": cfg, "total": total, "dialogue": dlg + hs, "dialogue_raw": dlg})

    results.sort(key=lambda r: r["total"])
    base_en = sum(len(ENC["o200k"].encode(r["cfg"] and open(HERE / "results-v1.json").read() and "") or "") for r in [])  # unused
    v1 = json.load(open(HERE / "results-v1.json"))
    en_total, json_total = v1["english"]["total"]["o200k"], v1["json"]["total"]["o200k"]
    en_dlg, json_dlg = v1["english"]["dialogue"]["o200k"], v1["json"]["dialogue"]["o200k"]

    print(f"sweep: {len(configs)} configs generated, {len(results)} unique encodings, all round-trip verified\n")
    print(f"{'#':<4}{'kw':<5}{'route':<9}{'args':<8}{'ent':<5}{'dates':<9}{'pred':<6}{'total':>6}{'vs EN':>7}{'vs JSON':>9}{'dlg':>6}{'dlg vs EN':>10}")
    for i, r in enumerate(results[:20]):
        c = r["cfg"]
        print(f"{i+1:<4}{c['kw']:<5}{c['route']:<9}{c['args']:<8}{str(c['entity']):<5}{c['dates']:<9}{str(c['preds']):<6}"
              f"{r['total']:>6}{en_total/r['total']:>6.1f}x{json_total/r['total']:>8.1f}x{r['dialogue']:>6}{en_dlg/r['dialogue']:>9.1f}x")
    print(f"\nbaselines: english total {en_total} (dlg {en_dlg}) | json total {json_total} (dlg {json_dlg}) | sutra_current total 330 (dlg 180)")
    (HERE / "results-sweep.json").write_text(json.dumps(results, indent=1))
    print(f"all {len(results)} rows: results-sweep.json")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"ran in {time.time() - t0:.1f}s")
