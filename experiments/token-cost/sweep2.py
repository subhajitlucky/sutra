"""Round 3 sweep — deeper Sanskrit mechanisms, 162 configs, decoder-verified.

New axes on the v2 winner family (Karaka slots + entity handles + folded route):

  anuvrtti : Panini's carry-over rule as session ellipsis:
             'off' | 'values' (repeat values -> '.') | 'valpred' (repeat
             predicates too). State evolves identically on both sides.
  numbers  : 'dec' | 'b36' | 'k'  — lossless integer alphabets.
  wire     : 'text' | 'b85' | 'b64' — packed binary (zigzag varints,
             entity indexes, string table) rendered as base85/base64.
  kw       : 'l1' letters | 'tni' token-native | 'dev' Devanagari (control).

Every config is decoded back to the canonical message and compared field by
field (primitive, predicate, routing, args, offer body, extras) for all 12
messages, in session order, including the binary wires.
"""

import base64
import datetime as dt
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tiktoken  # noqa: E402

from corpus import MESSAGES, DIALOGUE  # noqa: E402
from sweep import ENTITY, ROUTE_ALIAS, SCHEMA, OFFER_ORDER, COUNTER_ORDER, ENC  # noqa: E402
from sweep import KW_LETTERS, TNI  # noqa: E402

KW_DEV = {"INTENT": "स", "FACT": "त", "QUERY": "श", "OFFER": "म", "COUNTER": "ट",
          "ACCEPT": "अ", "REJECT": "न", "COMMIT": "ध", "ACT": "क"}
KW_STYLES = {"l1": KW_LETTERS, "tni": TNI, "dev": KW_DEV}

PRIM_ORDER = ["INTENT", "FACT", "QUERY", "OFFER", "COUNTER", "ACCEPT", "REJECT", "COMMIT", "ACT"]
PRED_ORDER = ["buy", "available", "availability", "pay", "transfer", "committed"]
ENTITY_ORDER = ["SmartTV", "Samsung", "Crystal4K", "off-001", "off-001-c", "off-999",
                "signed", "price_too_high", "unsupported"]
ENTITY_IDX = {n: i for i, n in enumerate(ENTITY_ORDER)}
ENTITY_REV = {v: k for k, v in ENTITY.items()}
DATE_SLOTS = {"deadline", "by"}
REPEAT = "."
MISSING = object()


# ── shared helpers ──────────────────────────────────────────────────

def order_of(m):
    p = m["primitive"]
    if p in ("OFFER", "COUNTER"):
        return OFFER_ORDER if p == "OFFER" else COUNTER_ORDER
    if p in ("ACCEPT", "REJECT"):
        return ["id"]
    return SCHEMA.get((p, m.get("predicate")), [])


def flat_of(m):
    flat = dict(m["args"])
    if m.get("body"):
        for k, pairs in m["body"].items():
            for kk, vv in pairs:
                flat[f"{k}.{kk}"] = vv
    for k in ("reason", "by", "in_reply_to"):
        if m.get("extra", {}).get(k):
            flat[k] = m["extra"][k]
    return flat


def to_b36(n):
    if n < 0:
        return "-" + to_b36(-n)
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0:
        return "0"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out


def is_date(v):
    return isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-"


def zigzag(n):
    return (n << 1) if n >= 0 else ((-n) << 1) - 1


def unzigzag(z):
    return (z >> 1) if not (z & 1) else -((z + 1) >> 1)


def push_varint(n, out):
    n = zigzag(n)
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            return


def read_varint(data, i):
    shift, out = 0, 0
    while True:
        b = data[i]
        i += 1
        out |= (b & 0x7F) << shift
        if not b & 0x80:
            return unzigzag(out), i
        shift += 7


class Session:
    def __init__(self):
        self.v = {}
        self.p = {}


# ── semantic fields (wire-independent) ─────────────────────────────

def build_fields(m, cfg, sess):
    """Logical fields; ellipsis decided here, identically on both sides."""
    order = order_of(m)
    flat = flat_of(m)
    fields = {
        "prim": m["primitive"],
        "pred": None,
        "route": (0 if m["from"] == "buyer@home" else 1) if m.get("to") else (2 if m["from"] == "buyer@home" else 3),
        "vals": [],
        "reason": None, "by": None, "reply": None,
        "pred_repeat": False,
    }
    pred = m.get("predicate")
    if pred:
        if cfg["delta"] == "valpred" and sess.p.get(m["primitive"]) == pred:
            fields["pred_repeat"] = True
        else:
            sess.p[m["primitive"]] = pred
        fields["pred"] = pred

    for slot in order:
        v = flat.get(slot, MISSING)
        if v is MISSING:
            fields["vals"].append(("missing",))
        elif cfg["delta"] in ("values", "valpred") and sess.v.get(slot) == v:
            fields["vals"].append(("repeat",))
        else:
            sess.v[slot] = v
            fields["vals"].append(("val", v))

    for key in ("reason", "by", "in_reply_to"):
        val = m.get("extra", {}).get(key)
        if val is None:
            continue
        if cfg["delta"] in ("values", "valpred") and sess.v.get(key) == val:
            fields[{"reason": "reason", "by": "by", "in_reply_to": "reply"}[key]] = ("repeat",)
        else:
            sess.v[key] = val
            fields[{"reason": "reason", "by": "by", "in_reply_to": "reply"}[key]] = ("val", val)
    return fields


def surface_number(n, mode):
    if mode == "b36":
        return to_b36(n)
    if mode == "k":
        return f"{n // 1000}k" if n >= 1000 and n % 1000 == 0 else str(n)
    return str(n)


def parse_number(tok, mode):
    if mode == "k" and tok.endswith("k") and tok[:-1].isdigit():
        return int(tok[:-1]) * 1000
    if mode == "b36":
        try:
            return int(tok, 36)
        except ValueError:
            return None
    try:
        return int(tok)
    except ValueError:
        return None


def surface_value(v, slot, cfg):
    if is_date(v) and (slot in DATE_SLOTS):
        return surface_number(dt.date.fromisoformat(v).toordinal(), cfg["numbers"])
    if isinstance(v, int):
        return surface_number(v, cfg["numbers"])
    if v in ENTITY:
        return ENTITY[v]
    return v if v.replace("@", "").replace("-", "").replace("_", "").isalnum() else json.dumps(v)


def restore_value(tok, slot, cfg):
    if tok == REPEAT:
        return REPEAT
    if slot in DATE_SLOTS:
        n = parse_number(tok, cfg["numbers"])
        if n is not None:
            return dt.date.fromordinal(n).isoformat()
    if tok in ENTITY_REV:  # entity aliases win over base-36 digit parsing
        return ENTITY_REV[tok]
    n = parse_number(tok, cfg["numbers"])
    if n is not None:
        return n
    return tok


def restore_value_bin(tag, payload, slot):
    """payload: int (varint) | bytes (str)."""
    if slot in DATE_SLOTS:
        return dt.date.fromordinal(payload).isoformat()
    if tag == 3:
        return ENTITY_REV.get(payload, payload) if isinstance(payload, str) else payload
    return payload


# ── text wire ───────────────────────────────────────────────────────

KWCASE = {"l1": True, "tni": True, "dev": False}


def text_encode(m, cfg, sess):
    f = build_fields(m, cfg, sess)
    order = order_of(m)
    K = KW_STYLES[cfg["kw"]][f["prim"]]
    prefix = ""
    if cfg["route"] == "fold":
        if f["route"] in (2, 3):
            prefix = ("b " if f["route"] == 2 else "s ")
        else:
            if KWCASE[cfg["kw"]]:
                K = K.lower() if f["route"] == 0 else K.upper()
            else:
                K = K + ("f" if f["route"] == 0 else "r")
    else:
        prefix = {0: "> ", 1: "< ", 2: "b ", 3: "s "}[f["route"]]

    parts = []
    if f["pred"]:
        parts.append(REPEAT if f["pred_repeat"] else f["pred"])
    flat = flat_of(m)
    for slot, val in zip(order, f["vals"]):
        if val == ("missing",):
            parts.append("-")
        elif val == ("repeat",):
            parts.append(REPEAT)
        else:
            parts.append(surface_value(flat[slot], slot, cfg))
    stmt = " ".join(parts)
    tail = ""
    for marker, key, is_date_field in (("!", "reason", False), ("~", "by", True), ("^", "reply", False)):
        fv = f[key]
        if fv is None:
            continue
        if fv == ("repeat",):
            tail += f" {marker}{REPEAT}"
        else:
            v = fv[1]
            if is_date_field:
                tail += f" {marker}{surface_number(dt.date.fromisoformat(v).toordinal(), cfg['numbers'])}"
            elif v in ENTITY:
                tail += f" {marker}{ENTITY[v]}"
            else:
                tail += f" {marker}{v}"
    return f"{prefix}{K} {stmt}{tail}".strip()


def text_decode(text, cfg, sess):
    tokens = text.split()
    route = None
    if cfg["route"] == "fold":
        if tokens and tokens[0] in ("b", "s"):
            route = 2 if tokens.pop(0) == "b" else 3
    else:
        r = tokens.pop(0)
        route = {".": None, ">": 0, "<": 1, "b": 2, "s": 3}[r]
    K = tokens.pop(0)
    if cfg["route"] == "fold":
        if route is None:
            if KWCASE[cfg["kw"]]:
                route = 0 if K.islower() else 1
                K = K.upper()
            else:
                route = 0 if K.endswith("f") else 1
                K = K[:-1]
    rev_kw = {str(v).upper(): k for k, v in KW_STYLES[cfg["kw"]].items()}
    prim = rev_kw[K.upper()]

    # tails
    tails = {}
    body = []
    for tok in tokens:
        if tok[:1] in ("!", "~", "^") and len(tok) > 1:
            tails[tok[0]] = tok[1:]
        else:
            body.append(tok)

    pred = None
    pred_repeat = None
    if prim in ("INTENT", "FACT", "QUERY", "COMMIT", "ACT"):
        pt = body.pop(0)
        if pt == REPEAT:
            pred_repeat = True
        else:
            pred = pt
    # order needs pred; for pred_repeat, look it up from session
    lookup = {"primitive": prim, "predicate": pred, "args": [], "extra": {}}
    if pred_repeat:
        pred = "?repeat"  # placeholder to look up state
    order = order_of({"primitive": prim, "predicate": pred})
    if pred_repeat:
        pred = None  # resolved by caller via session after we return marker

    flat_vals = []
    for slot, tok in zip(order, body):
        flat_vals.append((slot, "missing" if tok == "-" else tok))

    return {"prim": prim, "pred": pred, "pred_repeat": pred_repeat, "route": route,
            "vals": flat_vals, "tails": tails}


# ── binary wire ─────────────────────────────────────────────────────

TE = {"missing": 0, "repeat": 1, "num": 2, "ent": 3, "str": 4}


def bin_encode(m, cfg, sess):
    f = build_fields(m, cfg, sess)
    order = order_of(m)
    flat = flat_of(m)
    out = bytearray()
    out.append(PRIM_ORDER.index(f["prim"]))
    out.append(0xFE if f["pred_repeat"] else (0xFF if not f["pred"] else PRED_ORDER.index(f["pred"])))
    out.append(f["route"])
    for slot, val in zip(order, f["vals"]):
        if val == ("missing",):
            out.append(TE["missing"])
            continue
        v = flat[slot]
        if val == ("repeat",):
            out.append(TE["repeat"])
        elif isinstance(v, int):
            out.append(TE["num"])
            push_varint(v, out)
        elif is_date(v) and slot in DATE_SLOTS:
            out.append(TE["num"])
            push_varint(dt.date.fromisoformat(v).toordinal(), out)
        elif v in ENTITY:
            out.append(TE["ent"])
            out.append(ENTITY_IDX[v])
        else:
            out.append(TE["str"])
            raw = v.encode()
            push_varint(len(raw), out)
            out += raw
    flags = 0
    extras = []
    for bit, key in enumerate(("reason", "by", "reply")):
        fv = f[key]
        if fv is None:
            continue
        flags |= 1 << bit
        if fv == ("repeat",):
            extras.append((TE["repeat"], None))
            continue
        v = fv[1]
        if key == "by":
            extras.append((TE["num"], dt.date.fromisoformat(v).toordinal()))
        elif v in ENTITY:
            extras.append((TE["ent"], ENTITY_IDX[v]))
        else:
            extras.append((TE["str"], v))
    out.append(flags)
    for tag, payload in extras:
        out.append(tag)
        if tag == TE["num"]:
            push_varint(payload, out)
        elif tag == TE["ent"]:
            out.append(payload)
        elif tag == TE["str"]:
            raw = payload.encode()
            push_varint(len(raw), out)
            out += raw
    return bytes(out)


def bin_decode(data, cfg, sess):
    i = 0
    prim = PRIM_ORDER[data[i]]; i += 1
    predb = data[i]; i += 1
    route = data[i]; i += 1
    pred = None if predb == 0xFF else (None if predb == 0xFE else PRED_ORDER[predb])
    pred_repeat = predb == 0xFE
    lookup_pred = pred
    order = order_of({"primitive": prim, "predicate": lookup_pred})
    vals = []
    for _ in order:
        tag = data[i]; i += 1
        if tag == TE["missing"]:
            vals.append(("missing",))
        elif tag == TE["repeat"]:
            vals.append(("repeat",))
        elif tag == TE["num"]:
            n, i = read_varint(data, i)
            vals.append(("num", n))
        elif tag == TE["ent"]:
            vals.append(("ent", ENTITY_ORDER[data[i]])); i += 1
        else:
            ln, i = read_varint(data, i)
            vals.append(("str", data[i:i + ln].decode())); i += ln
    flags = data[i]; i += 1
    tails = {}
    for bit, key in enumerate(("reason", "by", "reply")):
        if not flags & (1 << bit):
            continue
        tag = data[i]; i += 1
        if tag == TE["repeat"]:
            tails[key] = REPEAT
        elif tag == TE["num"]:
            n, i = read_varint(data, i)
            tails[key] = n
        elif tag == TE["ent"]:
            tails[key] = ENTITY_ORDER[data[i]]; i += 1
        else:
            ln, i = read_varint(data, i)
            tails[key] = data[i:i + ln].decode(); i += ln
    return {"prim": prim, "pred": pred, "pred_repeat": pred_repeat, "route": route,
            "vals": vals, "tails": tails}


# ── fields -> canonical message (with session state on decode) ─────

def resolve(decoded, cfg, sess, wire):
    """Turn decoded fields into a canonical message; update session state."""
    prim = decoded["prim"]
    pred = decoded["pred"]
    if decoded.get("pred_repeat"):
        pred = sess.p.get(prim)
    elif pred is not None:
        sess.p[prim] = pred

    order = order_of({"primitive": prim, "predicate": pred})
    values = []
    for slot, v in zip(order, decoded["vals"]):
        if wire == "text":
            slot_name, tok = v
            if tok == "missing":
                continue
            if tok == REPEAT:
                values.append((slot_name, sess.v[slot_name]))
                continue
            val = restore_value(tok, slot_name, cfg)
        else:
            if v[0] == "missing":
                continue
            if v[0] == "repeat":
                values.append((slot, sess.v[slot]))
                continue
            tag, payload = v
            if tag == "num":
                val = restore_value_bin(2, payload, slot)
            elif tag == "ent":
                val = ENTITY_REV.get(payload, payload)
            else:
                val = payload
        sess.v[slot] = val
        values.append((slot, val))

    extra = {}
    for key, out_name, marker_char in (("reason", "reason", "!"), ("by", "by", "~"), ("reply", "in_reply_to", "^")):
        fv = decoded["tails"].get(key if wire != "text" else marker_char)
        if fv is None:
            continue
        slot = "by" if key == "by" else key
        if fv == REPEAT:
            val = sess.v[key]
        elif wire == "text":
            val = restore_value(fv, slot, cfg)
        else:
            tag = 2 if key == "by" else (3 if isinstance(fv, str) and fv in ENTITY_REV else 4)
            val = restore_value_bin(tag, fv, slot)
        sess.v[key] = val
        extra[out_name] = val

    msg = {"primitive": prim, "predicate": pred, "args": [], "from": None, "to": None, "extra": {}}
    route = decoded["route"]
    msg["from"] = "buyer@home" if route in (0, 2) else "seller@store"
    msg["to"] = None if route in (2, 3) else ("seller@store" if route == 0 else "buyer@home")
    if prim in ("OFFER", "COUNTER"):
        body = {"give": [], "want": []}
        for slot, val in values:
            if slot == "id":
                msg["args"].append((slot, val))
            elif slot == "orig":
                msg["args"].append((slot, val))
            else:
                side, name = slot.split(".")
                body[side].append((name, val))
        msg["body"] = body
    else:
        msg["args"] = values
    for k, v in extra.items():
        msg["extra"][k] = v
    return msg


def canonical(m):
    out = {"primitive": m["primitive"], "predicate": m.get("predicate"),
           "args": list(m["args"]), "from": m["from"], "to": m.get("to"), "extra": dict(m.get("extra", {}))}
    if m.get("body"):
        out["body"] = {k: list(v) for k, v in m["body"].items()}
    return out


def main():
    configs = []
    for kw in KW_STYLES:
        for route in ("fold", "session"):
            for delta in ("off", "values", "valpred"):
                for numbers in ("dec", "b36", "k"):
                    for wire in ("text", "b85", "b64"):
                        configs.append({"kw": kw, "route": route, "delta": delta,
                                        "numbers": numbers, "wire": wire})
    print(f"round 3: {len(configs)} configs")

    seen, results = set(), []
    for cfg in configs:
        sess = Session()
        wire_strings = []
        for m in MESSAGES:
            if cfg["wire"] == "text":
                wire_strings.append(text_encode(m, cfg, sess))
            else:
                raw = bin_encode(m, cfg, sess)
                wire_strings.append(base64.b85encode(raw).decode() if cfg["wire"] == "b85"
                                    else base64.b64encode(raw).decode())
        key = "\n".join(wire_strings)
        if key in seen:
            continue
        seen.add(key)

        # full round-trip: decode in the same session order
        sess = Session()
        for m, w in zip(MESSAGES, wire_strings):
            if cfg["wire"] == "text":
                decoded = text_decode(w, cfg, sess)
            else:
                raw = base64.b85decode(w) if cfg["wire"] == "b85" else base64.b64decode(w)
                decoded = bin_decode(raw, cfg, sess)
            got = resolve(decoded, cfg, sess, "text" if cfg["wire"] == "text" else "bin")
            want = canonical(m)
            got2 = canonical(got)
            if got2 != want:
                print("ROUND-TRIP FAIL", json.dumps(cfg), m["id"])
                print("  wire:", w)
                print("  want:", want)
                print("  got :", got2)
                sys.exit(1)

        total = sum(len(ENC["o200k"].encode(w)) for w in wire_strings)
        results.append({"cfg": cfg, "total": total, "strings": wire_strings})

    results.sort(key=lambda r: r["total"])
    v1 = json.load(open(HERE / "results-v1.json"))
    en_total, json_total = v1["english"]["total"]["o200k"], v1["json"]["total"]["o200k"]
    print(f"{len(results)} unique encodings, ALL round-trip verified\n")
    print(f"{'#':<4}{'kw':<5}{'route':<9}{'delta':<9}{'nums':<6}{'wire':<6}{'total':>6}{'vs EN':>8}{'vs JSON':>9}")
    for i, r in enumerate(results[:20]):
        c = r["cfg"]
        print(f"{i+1:<4}{c['kw']:<5}{c['route']:<9}{c['delta']:<9}{c['numbers']:<6}{c['wire']:<6}"
              f"{r['total']:>6}{en_total/r['total']:>7.2f}x{json_total/r['total']:>8.2f}x")
    print(f"\nbaselines: english {en_total} | json {json_total} | sutra_current 330")
    (HERE / "results-sweep2.json").write_text(json.dumps([{"cfg": r["cfg"], "total": r["total"]} for r in results], indent=1))
    print("saved results-sweep2.json")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"ran in {time.time() - t0:.1f}s")
