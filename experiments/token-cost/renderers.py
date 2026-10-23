"""Lossless renderers: canonical message -> string, for every representation.

Every representation carries ALL information in the canonical form:
primitive, predicate, ordered args, offer body, routing (from/to), extras.
What varies is the surface encoding. No representation may drop fields.

Naming: `sutra_*` = candidate compact wire encodings (SUTRA-C experiments).
"""

import json

# ── compact keyword maps ───────────────────────────────────────────

KW_SHORT2 = {
    "INTENT": "IN", "FACT": "FA", "QUERY": "QU", "OFFER": "OF", "COUNTER": "CN",
    "ACCEPT": "AC", "REJECT": "RJ", "COMMIT": "CM", "ACT": "AT",
}
KW_LETTERS = {
    "INTENT": "I", "FACT": "F", "QUERY": "Q", "OFFER": "O", "COUNTER": "K",
    "ACCEPT": "A", "REJECT": "R", "COMMIT": "C", "ACT": "X",
}
KW_DIGITS = {
    "INTENT": "0", "FACT": "1", "QUERY": "2", "OFFER": "3", "COUNTER": "4",
    "ACCEPT": "5", "REJECT": "6", "COMMIT": "7", "ACT": "8",
}
KW_SYMBOLS = {
    "INTENT": "»", "FACT": "·", "QUERY": "?", "OFFER": "↔", "COUNTER": "⇄",
    "ACCEPT": "✓", "REJECT": "✗", "COMMIT": "⚑", "ACT": "▶",
}
# Sanskrit roots in compact ASCII transliteration (objective: test whether the
# Sanskrit-root naming itself buys tokenizer efficiency, not just length).
KW_SANSKRIT = {
    "INTENT": "SK", "FACT": "PR", "QUERY": "PV", "OFFER": "SV", "COUNTER": "KRT",
    "ACCEPT": "ST", "REJECT": "NR", "COMMIT": "DH", "ACT": "KY",
}

PRIMITIVES = list(KW_LETTERS.keys())


def _safe_token(s: str) -> bool:
    """A string is safe to emit bare if it contains no syntax characters."""
    if not s:
        return False
    bad = set(' "(),;:{}[]=~|^!')
    return not (set(s) & bad)


def fmt_str(v: str, bare: bool) -> str:
    if bare and _safe_token(v):
        return v
    return json.dumps(v, ensure_ascii=False)


def fmt_val(v, bare: bool) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if v is None:
        return "null"
    return fmt_str(v, bare)


# ── baselines ──────────────────────────────────────────────────────

def render_english(m: dict) -> str:
    p, pred, args, extra = m["primitive"], m.get("predicate"), dict(m["args"]), m.get("extra", {})
    who = m["from"]
    to = m.get("to")
    addr = f"{who} to {to}" if to else who
    joined = ", ".join(f"{k} {v}" for k, v in args.items())
    if p == "INTENT":
        s = f"{who} intends to {pred}: {joined}."
    elif p == "FACT":
        s = f"{who} states as fact: {pred}: {joined}."
    elif p == "QUERY":
        s = f"{who} asks {to} about {pred}: {joined}."
    elif p == "OFFER":
        body = m["body"]
        give = ", ".join(f"{k} {v}" for k, v in body["give"])
        want = ", ".join(f"{k} {v}" for k, v in body["want"])
        s = f"{who} offers {to} the deal {args['id']}: giving {give}; wanting {want}."
    elif p == "COUNTER":
        body = m["body"]
        give = ", ".join(f"{k} {v}" for k, v in body["give"])
        want = ", ".join(f"{k} {v}" for k, v in body["want"])
        s = f"{who} counters the offer {args['orig']} to {to} with deal {args['id']}: giving {give}; wanting {want}."
    elif p == "ACCEPT":
        s = f"{who} accepts the offer {args['id']}." + (f" Sent to {to}." if to else "")
    elif p == "REJECT":
        s = f"{who} rejects the offer {args['id']} because {extra.get('reason')}." + (f" Sent to {to}." if to else "")
    elif p == "COMMIT":
        s = f"{who} commits to {pred}: {joined}, by {extra.get('by')}."
    elif p == "ACT":
        s = f"{who} performs the action {pred}: {joined}."
    if extra.get("in_reply_to"):
        s += f" (in reply to {extra['in_reply_to']})"
    return s


def render_json(m: dict) -> str:
    obj = {
        "primitive": m["primitive"],
        "predicate": m.get("predicate"),
        "args": dict(m["args"]),
        "from": m["from"],
        "to": m.get("to"),
        "extra": m.get("extra", {}),
    }
    if "body" in m:
        obj["body"] = {k: dict(v) for k, v in m["body"].items()}
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def render_sutra_current(m: dict) -> str:
    """Exactly the syntax sutra_lang/parser.py accepts. Strings always quoted."""
    p, pred = m["primitive"], m.get("predicate")
    args = m["args"]
    adict = dict(args)
    body = m.get("body")
    extra = m.get("extra", {})
    q = lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, str) else str(v)

    def predicate(name, items):
        inner = ", ".join(f"{k}={q(v)}" for k, v in items)
        return f"{name}({inner})"

    if p in ("INTENT", "FACT", "ACT"):
        stmt = f"{p} {predicate(pred, args)};"
    elif p == "QUERY":
        stmt = f"QUERY {predicate(pred, args)} FROM {q(m['to'])};"
    elif p == "OFFER":
        give = ", ".join(f"{k}: {q(v)}" for k, v in body["give"])
        want = ", ".join(f"{k}: {q(v)}" for k, v in body["want"])
        stmt = f"OFFER id={q(adict['id'])} TO {q(m['to'])} {{ give: {{{give}}}, want: {{{want}}} }};"
    elif p == "COUNTER":
        give = ", ".join(f"{k}: {q(v)}" for k, v in body["give"])
        want = ", ".join(f"{k}: {q(v)}" for k, v in body["want"])
        stmt = (
            f"COUNTER {q(adict['orig'])} id={q(adict['id'])} TO {q(m['to'])} "
            f"{{ give: {{{give}}}, want: {{{want}}} }};"
        )
    elif p == "ACCEPT":
        stmt = f"ACCEPT {q(adict['id'])};"
    elif p == "REJECT":
        stmt = f"REJECT {q(adict['id'])}"
        if extra.get("reason"):
            stmt += f" REASON {q(extra['reason'])}"
        stmt += ";"
    elif p == "COMMIT":
        stmt = f"COMMIT {predicate(pred, args)}"
        if extra.get("by"):
            stmt += f" BY {q(extra['by'])}"
        stmt += ";"
    else:
        raise ValueError(p)

    headers = []
    if not (p in ("QUERY", "OFFER", "COUNTER") and m.get("to")):
        headers.append(f"#from {q(m['from'])}")
        if m.get("to"):
            headers.append(f"#to {q(m['to'])}")
    body_str = (" ".join(headers) + "\n" if headers else "") + stmt
    if extra.get("in_reply_to"):
        body_str += f" // in_reply_to={extra['in_reply_to']}"
    return body_str


# ── compact (SUTRA-C candidates) ──────────────────────────────────

import datetime as _dt

from corpus import POSITIONAL_ORDER

ROUTE_ALIAS = {"buyer@home": "b", "seller@store": "s"}
PRED_ALIAS = {  # schema-negotiated predicate dictionary
    "buy": "1", "available": "2", "availability": "3",
    "pay": "4", "transfer": "5", "committed": "6",
}

HANDSHAKE_ROUTE = "b=buyer@home s=seller@store"
HANDSHAKE_PRED = "1=buy 2=available 3=availability 4=pay 5=transfer 6=committed"


def _ordinal_if_date(v):
    if isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-":
        try:
            return str(_dt.date.fromisoformat(v).toordinal())
        except ValueError:
            return v
    return v


def render_compact(m: dict, kw: dict, *, positional=False, spacing="tight",
                   route="full", dates="iso", pred_alias=False) -> str:
    p = m["primitive"]
    pred = m.get("predicate")
    args_items = m["args"]
    body = m.get("body")
    extra = m.get("extra", {})
    K = kw[p]
    sp = "" if spacing == "tight" else " "
    sc = "" if spacing == "tight" else ", "

    def val(v):
        if dates == "ordinal":
            v = _ordinal_if_date(v)
        return fmt_val(v, True)

    if pred and pred_alias and pred in PRED_ALIAS:
        pred = PRED_ALIAS[pred]

    if route == "none":
        # Session-implied routing: one-to-one sessions need no per-message
        # route; broadcasts still carry the sender alias.
        prefix = "" if m.get("to") else ROUTE_ALIAS.get(m["from"], m["from"])
    elif route == "alias":
        prefix = ROUTE_ALIAS.get(m["from"], m["from"]) + ">" + (
            ROUTE_ALIAS.get(m.get("to"), m.get("to")) if m.get("to") else "-"
        )
    else:
        prefix = m["from"] + ">" + (m.get("to") or "-")

    if p in ("INTENT", "FACT", "ACT", "QUERY", "COMMIT"):
        order = POSITIONAL_ORDER.get((p, m.get("predicate")))
        vals = dict(args_items)
        if positional and order and all(k in vals for k in order):
            inner = " ".join(val(vals[k]) for k in order)
        else:
            inner = sc.join(f"{k}={val(v)}" for k, v in args_items)
        stmt = f"{K}{sp}{pred}({inner})"
        if p == "COMMIT" and extra.get("by"):
            stmt += f"{sp}~{val(extra['by'])}"
    elif p in ("OFFER", "COUNTER"):
        give = sc.join(f"{k}={val(v)}" for k, v in body["give"])
        want = sc.join(f"{k}={val(v)}" for k, v in body["want"])
        if p == "OFFER":
            head = f"{K}{sp}id={args_items[0][1]}"
        else:
            head = f"{K}{sp}{args_items[0][1]},{args_items[1][1]}"
        stmt = f"{head}{sp}{{give({give})|want({want})}}"
    elif p == "ACCEPT":
        stmt = f"{K}{sp}{args_items[0][1]}"
    elif p == "REJECT":
        stmt = f"{K}{sp}{args_items[0][1]}"
        if extra.get("reason"):
            stmt += f"!{extra['reason']}"
    else:
        raise ValueError(p)

    if extra.get("in_reply_to"):
        stmt += f"{sp}^{extra['in_reply_to']}"
    return f"{prefix}{sp}{stmt}" if prefix else stmt


# ── variant registry ───────────────────────────────────────────────

def _c(kw, **kwr):
    return lambda m: render_compact(m, kw, **kwr)


REPRESENTATIONS = {
    "english": render_english,
    "json": render_json,
    "sutra_current": render_sutra_current,
    "sutra_short2": _c(KW_SHORT2),
    "sutra_letters": _c(KW_LETTERS),
    "sutra_letters_spaced": _c(KW_LETTERS, spacing="space"),
    "sutra_digits": _c(KW_DIGITS),
    "sutra_symbols": _c(KW_SYMBOLS),
    "sutra_sanskrit": _c(KW_SANSKRIT),
    "sutra_pos": _c(KW_LETTERS, positional=True),
    "sutra_pos_sanskrit": _c(KW_SANSKRIT, positional=True),
    "sutra_pos_sanskrit_spaced": _c(KW_SANSKRIT, positional=True, spacing="space"),
    "sutra_pos_alias": _c(KW_LETTERS, positional=True, route="alias"),
    "sutra_pos_session": _c(KW_LETTERS, positional=True, route="none"),
    "sutra_pos_session_epoch": _c(KW_LETTERS, positional=True, route="none", dates="ordinal"),
    "sutra_c_max": _c(KW_LETTERS, positional=True, route="none", dates="ordinal", pred_alias=True),
}

# One-time session costs for representations that negotiate dictionaries.
HANDSHAKES = {
    "sutra_pos_alias": HANDSHAKE_ROUTE,
    "sutra_pos_session": HANDSHAKE_ROUTE,
    "sutra_pos_session_epoch": HANDSHAKE_ROUTE,
    "sutra_c_max": HANDSHAKE_ROUTE + " " + HANDSHAKE_PRED,
}
