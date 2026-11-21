#!/usr/bin/env python3
"""Memo size (RelNodes / RelSets / multi-table table sets) per query and Calcite mode."""
import json, os, sys
qs = sys.argv[1:] or ["Q4", "Q6", "Q7", "Q8"]
modes = ["_nosort", "_nosort_nocross", "_nosort_nocross_exchange",
         "_nosort_topdown", "_nosort_topdown_nocross", "_nosort_topdown_nocross_exchange"]
print(f"{'query':6}{'mode':36}{'nodes':>8}{'relsets':>9}{'table sets':>12}")
for q in qs:
    for m in modes:
        f = f"traces/calcite_{q}{m}.json"
        if not os.path.exists(f):
            continue
        t = json.load(open(f))
        s = t["summary"]
        sets = {tuple(x["tables"]) for x in t["sets"] if len(x["tables"]) > 1}
        print(f"{q:6}{m:36}{s['registered']:>8}{s['relsets']:>9}{len(sets):>12}")
