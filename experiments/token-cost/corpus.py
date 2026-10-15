"""Canonical agent messages for the token-cost experiments.

Every message is defined once as structured data (the semantic form).
All representations are rendered FROM this form, so encodings are
lossless by construction. When decoders land, they must round-trip
back to exactly these structures.

The corpus models one realistic negotiation between two agents:
buyer@home and seller@store.
"""

# Each message: primitive, predicate, ordered args, routing, extras.
MESSAGES = [
    {
        "id": "m01-intent",
        "primitive": "INTENT",
        "predicate": "buy",
        "args": [("item", "SmartTV"), ("max_price", 50000), ("deadline", "2026-03-01")],
        "from": "buyer@home",
        "to": None,
        "extra": {},
    },
    {
        "id": "m02-fact",
        "primitive": "FACT",
        "predicate": "available",
        "args": [("item", "SmartTV"), ("seller", "seller@store"), ("price", 48000)],
        "from": "seller@store",
        "to": None,
        "extra": {},
    },
    {
        "id": "m03-query",
        "primitive": "QUERY",
        "predicate": "availability",
        "args": [("item", "SmartTV")],
        "from": "buyer@home",
        "to": "seller@store",
        "extra": {},
    },
    {
        "id": "m04-offer",
        "primitive": "OFFER",
        "predicate": None,
        "args": [("id", "off-001")],
        "body": {
            "give": [("money", 48000)],
            "want": [("item", "SmartTV"), ("brand", "Samsung")],
        },
        "from": "buyer@home",
        "to": "seller@store",
        "extra": {},
    },
    {
        "id": "m05-counter",
        "primitive": "COUNTER",
        "predicate": None,
        "args": [("orig", "off-001"), ("id", "off-001-c")],
        "body": {
            "give": [("money", 46000)],
            "want": [("item", "SmartTV")],
        },
        "from": "seller@store",
        "to": "buyer@home",
        "extra": {},
    },
    {
        "id": "m06-accept",
        "primitive": "ACCEPT",
        "predicate": None,
        "args": [("id", "off-001")],
        "from": "buyer@home",
        "to": "seller@store",
        "extra": {},
    },
    {
        "id": "m07-reject",
        "primitive": "REJECT",
        "predicate": None,
        "args": [("id", "off-001")],
        "from": "seller@store",
        "to": "buyer@home",
        "extra": {"reason": "price_too_high"},
    },
    {
        "id": "m08-commit",
        "primitive": "COMMIT",
        "predicate": "pay",
        "args": [("amount", 48000), ("to", "seller@store")],
        "from": "buyer@home",
        "to": "seller@store",
        "extra": {"by": "2026-03-01"},
    },
    {
        "id": "m09-act",
        "primitive": "ACT",
        "predicate": "transfer",
        "args": [("amount", 48000), ("to", "seller@store")],
        "from": "buyer@home",
        "to": "seller@store",
        "extra": {},
    },
    {
        "id": "m10-fact-committed",
        "primitive": "FACT",
        "predicate": "committed",
        "args": [("id", "off-001"), ("status", "signed")],
        "from": "seller@store",
        "to": None,
        "extra": {},
    },
    {
        "id": "m11-unsupported",
        "primitive": "REJECT",
        "predicate": None,
        "args": [("id", "off-999")],
        "from": "seller@store",
        "to": "buyer@home",
        "extra": {"reason": "unsupported"},
    },
    {
        "id": "m12-query-response",
        "primitive": "FACT",
        "predicate": "available",
        "args": [("item", "SmartTV"), ("price", 48000)],
        "from": "seller@store",
        "to": "buyer@home",
        "extra": {"in_reply_to": "m03-query"},
    },
]

# The six-message exchange that completes a deal, used for aggregate cost.
DIALOGUE = ["m03-query", "m12-query-response", "m04-offer", "m05-counter", "m06-accept", "m08-commit"]

# Per-predicate positional argument order for compact positional encodings.
# Order follows the Karaka-style fixed slot order: object, instrument, recipient.
POSITIONAL_ORDER = {
    ("INTENT", "buy"): ["item", "max_price", "deadline"],
    ("FACT", "available"): ["item", "seller", "price"],
    ("FACT", "committed"): ["id", "status"],
    ("QUERY", "availability"): ["item"],
    ("COMMIT", "pay"): ["amount", "to"],
    ("ACT", "transfer"): ["amount", "to"],
}
