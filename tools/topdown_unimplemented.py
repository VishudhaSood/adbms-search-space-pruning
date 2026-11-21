#!/usr/bin/env python3
"""Which RelSets did Calcite's top-down run never implement, and why?

Run from the repo root:  python3 tools/topdown_unimplemented.py Q8 [suffix]   (default suffix: _topdown)

A RelSet is "unimplemented" if no physical node was ever registered in it. For each one it reports
when (registration step) its first node appeared, relative to the last physical node in the whole run:
  - LATE: created after the last physical node anywhere, i.e. discovered after optimisation had
          finished -> nobody ever asked for it. This is incomplete exploration, not cost pruning.
  - EARLY: created while optimisation was still going on -> skipped by the top-down driver
          (branch-and-bound or never requested by a parent). Check the DEBUG log for the reason.
"""
import json, sys
from collections import defaultdict

q = sys.argv[1]
suffix = sys.argv[2] if len(sys.argv) > 2 else "_topdown"
t = json.load(open(f"traces/calcite_{q}{suffix}.json"))
step = {e["node"]: e["step"] for e in t["events"]}
rule = {e["node"]: e["rule"] for e in t["events"]}
tables = {s["id"]: tuple(s["tables"]) for s in t["sets"]}
by_set = defaultdict(list)
for n in t["nodes"]:
    if n.get("set") is not None:
        by_set[n["set"]].append(n)

last_phys = max(step[n["node"]] for n in t["nodes"] if n["physical"])
total = len(t["events"])
print(f"{q}{suffix}: {total} registrations, last physical node at step {last_phys}")

unimpl = []
for sid, ns in by_set.items():
    if any(n["physical"] for n in ns):
        continue
    first = min(step[n["node"]] for n in ns)
    unimpl.append((first, sid, tables.get(sid, ()), len(ns), rule[min(ns, key=lambda n: step[n["node"]])["node"]]))

late = [u for u in unimpl if u[0] > last_phys]
print(f"unimplemented RelSets: {len(unimpl)}  (LATE, after optimisation ended: {len(late)}; EARLY: {len(unimpl) - len(late)})")
for first, sid, tabs, n, r in sorted(unimpl):
    kind = "LATE " if first > last_phys else "EARLY"
    print(f"  {kind} set {sid:4} tables={','.join(tabs) or '{}':12} first step {first:6}  nodes={n:3}  made by {r}")
