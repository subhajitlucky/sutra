"""Re-score round-7 logs with the fixed scorers — no model calls.

Demonstrates the value of full logging: raw outputs are re-scored offline after
scorer fixes, so no test evidence is lost or re-rolled.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from round7 import (  # noqa: E402
    LOGDIR, MESSAGES, DIALOGUE_MSGS, score_parse, score_emit_meter, score_emit_c1,
)
from comprehension import extract_json_array  # noqa: E402


def main():
    rows = {}
    for path in sorted(LOGDIR.glob("*--*.txt")):
        backend, cell = path.stem.split("--")
        encoding, task = cell.split("-")
        out = path.read_text().split("---OUTPUT---", 1)[1]
        arr = extract_json_array(out)
        messages = MESSAGES if encoding == "c1" else DIALOGUE_MSGS
        key = f"{backend} {encoding}/{task}"
        if arr is None or len(arr) != len(messages):
            rows[key] = {"correct": 0, "total": len(messages), "note": "no-array"}
            continue
        if task == "parse":
            per = score_parse(arr, messages, "c1")
            rows[key] = {"correct": sum(1 for ok, _ in per if ok), "total": len(messages),
                         "failures": [w for ok, w in per if not ok]}
        elif encoding == "meter":
            per = score_emit_meter(arr)
            rows[key] = {"correct": sum(1 for ok, _ in per[:-1] if ok), "total": len(messages),
                         "tolerant": per[-1][1],
                         "failures": [w for ok, w in per[:-1] if not ok]}
        else:
            per = score_emit_c1(arr)
            rows[key] = {"correct": sum(1 for ok, _ in per if ok), "total": len(messages),
                         "failures": [w for ok, w in per if not ok]}

    print(f"{'cell':<24}{'strict':>8}{'tolerant':>10}  notes")
    for key, r in rows.items():
        tol = r.get("tolerant", "")
        note = "" if r.get("correct") == r["total"] else f"  failures: {r.get('failures')}"
        print(f"{key:<24}{r['correct']}/{r['total']:<6}{tol!s:>10}{note}")
    (LOGDIR / "results-rescored.json").write_text(json.dumps(rows, indent=1))
    print(f"\nsaved {LOGDIR / 'results-rescored.json'}")


if __name__ == "__main__":
    main()
