"""Token-cost benchmark: canonical messages x representations x real tokenizers.

Run from the repository root:
    .venv/bin/python experiments/token-cost/bench.py

Outputs a leaderboard (tokens per representation) and writes results-v1.json.
The `sutra_current` baseline is validated against the repo's own parser, so the
baseline token counts are counts of guaranteed-valid SUTRA.
"""

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))  # repo root, for `import sutra`

import tiktoken  # noqa: E402  (installed in .venv)

from corpus import MESSAGES, DIALOGUE  # noqa: E402
from renderers import REPRESENTATIONS, HANDSHAKES  # noqa: E402

ENCODINGS = {
    "o200k": tiktoken.get_encoding("o200k_base"),
    "cl100k": tiktoken.get_encoding("cl100k_base"),
}


def validate_current_sutra() -> list[str]:
    """Every sutra_current rendering must parse with the repo's own parser."""
    from sutra.lexer import Lexer
    from sutra.parser import Parser

    problems = []
    render = REPRESENTATIONS["sutra_current"]
    for m in MESSAGES:
        src = render(m)
        try:
            Parser(Lexer(src).tokenize()).parse()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{m['id']}: {exc}")
    return problems


def main() -> None:
    problems = validate_current_sutra()
    if problems:
        print("sutra_current FAILED to parse; numbers would be dishonest. Fix first:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print(f"sutra_current baseline validated against the repo parser ({len(MESSAGES)} messages)\n")

    by_id = {m["id"]: m for m in MESSAGES}
    dialogue = [by_id[i] for i in DIALOGUE]

    results = {}
    for name, render in REPRESENTATIONS.items():
        row = {"total": {}, "dialogue": {}, "chars": 0, "messages": {}}
        for m in MESSAGES:
            text = render(m)
            row["chars"] += len(text)
            row["messages"][m["id"]] = {
                "text": text,
                "tokens": {enc: len(tok.encode(text)) for enc, tok in ENCODINGS.items()},
            }
        handshake = HANDSHAKES.get(name, "")
        row["handshake"] = handshake
        for enc in ENCODINGS:
            row["total"][enc] = sum(v["tokens"][enc] for v in row["messages"].values())
            # dialogue includes the one-time session handshake, if any
            row["dialogue"][enc] = (
                sum(row["messages"][m["id"]]["tokens"][enc] for m in dialogue)
                + (len(ENCODINGS[enc].encode(handshake)) if handshake else 0)
            )
        results[name] = row

    base_total = results["english"]["total"]["o200k"]
    json_total = results["json"]["total"]["o200k"]
    base_dlg = results["english"]["dialogue"]["o200k"]
    json_dlg = results["json"]["dialogue"]["o200k"]

    print(f"{'representation':<26}{'o200k':>7}{'cl100k':>8}{'vs EN':>8}{'vs JSON':>9}"
          f"{'dlg o200k':>10}{'dlg vs EN':>10}")
    print("-" * 80)
    for name, row in sorted(results.items(), key=lambda kv: kv[1]["total"]["o200k"]):
        t = row["total"]["o200k"]
        print(f"{name:<26}{t:>7}{row['total']['cl100k']:>8}{base_total/t:>7.1f}x{json_total/t:>8.1f}x"
              f"{row['dialogue']['o200k']:>10}{base_dlg/row['dialogue']['o200k']:>9.1f}x")

    out = HERE / "results-v1.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print(f"\nfull per-message results: {out}")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"ran in {time.time() - t0:.1f}s")
