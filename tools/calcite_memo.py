#!/usr/bin/env python3
"""Day 2: break down Calcite's memo for one query, from traces/calcite_<Q>.json.

Run from the repo root:  python3 tools/calcite_memo.py Q4 [suffix]   (suffix e.g. _nosort, _nlj)
Prints: summary, RelSets grouped by table set (with winners and chosen plan),
which rule produced which RelNodes, join operators generated, and the
best-plan timeline.
"""
import collections, json, sys

q = sys.argv[1] if len(sys.argv) > 1 else "Q4"
suffix = sys.argv[2] if len(sys.argv) > 2 else ""
t = json.load(open(f"traces/calcite_{q}{suffix}.json"))
sets = {s["id"]: tuple(s["tables"]) for s in t["sets"]}
short = lambda op: op.replace("Enumerable", "E.").replace("Logical", "L.")

print(f"== {q}: {t['sql']}")
print("summary:", t["summary"])
print("nodes not in final memo (merged away):", sum(1 for n in t["nodes"] if n.get("set") is None))

print("\n== RelSets by table set")
by_set = collections.defaultdict(list)
for n in t["nodes"]:
    by_set[n["set"]].append(n)
by_tables = collections.defaultdict(list)
for sid in by_set:
    by_tables[sets.get(sid, ())].append(sid)
for tables in sorted(by_tables, key=lambda x: (len(x), x)):
    print(f"\n{{{', '.join(tables)}}}: {len(by_tables[tables])} RelSet(s)")
    for sid in sorted(by_tables[tables]):
        ns = by_set[sid]
        ops = collections.Counter(short(n["op"]) for n in ns)
        win = [f"{short(n['op'])} {n['total']:.2f}" for n in ns
               if n["winner"] and n["physical"] and "total" in n]
        chosen = " [in chosen plan]" if any(n["chosen"] for n in ns) else ""
        print(f"  set {sid}: {len(ns)} nodes {dict(ops)}  winner: {', '.join(win) or '-'}{chosen}")

print("\n== RelNodes added, by rule")
rc = collections.defaultdict(collections.Counter)
for e in t["events"]:
    rc[e["rule"].split("(")[0]][short(e["op"])] += 1
for rule, ops in sorted(rc.items(), key=lambda x: -sum(x[1].values())):
    print(f"  {rule}: {sum(ops.values())}  {dict(ops)}")

print("\n== Join operators generated")
for op in ("EnumerableHashJoin", "EnumerableMergeJoin", "EnumerableNestedLoopJoin"):
    ns = [n for n in t["nodes"] if n["op"] == op]
    combos = collections.Counter(tuple(sorted(set().union(*[sets.get(i["set"], ()) for i in n["inputs"]]))) for n in ns)
    won = sum(1 for n in ns if n["chosen"])
    print(f"  {short(op)}: {len(ns)} generated, {won} in chosen plan; table sets: {dict(combos)}")

print("\n== Best-plan timeline (registration step, total cost)")
print("  " + ", ".join(f"{s['step']}: {s['total']:.2f}" for s in t["timeline"]))
print(f"  of {t['summary']['registered']} registrations")
