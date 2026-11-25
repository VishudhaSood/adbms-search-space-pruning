#!/usr/bin/env python3
"""Day 1 check: are the traces there, and do Calcite's rows/costs match PostgreSQL's?

Run from the repo root:  python3 tools/check_day1.py [suffix]
  suffix = which Calcite run to check, e.g. _nosort or _nlj (default: the default run, calcite_Q*.json)
Queries come from tools/queries.txt; a query without both traces is skipped, not failed.
Exit code 0 = everything passed.
"""
import json, os, re, sys

SUFFIX = sys.argv[1] if len(sys.argv) > 1 else ""
QUERIES = [l.split("|")[0] for l in open("tools/queries.txt") if "|" in l]
skipped = []
TOL = 0.01          # EXPLAIN prints 2 decimals
ok = True

def fail(msg):
    global ok
    ok = False
    print("  FAIL:", msg)

# 1. 16 trace files, non-empty, with the expected fields
print("1. Trace files")
for q in QUERIES:
    paths = {"calcite": f"traces/calcite_{q}{SUFFIX}.json", "pg": f"traces/pg_{q}.json"}
    if not all(os.path.exists(x) for x in paths.values()):
        skipped.append(q); print(f"  skip {q}: missing " + ", ".join(x for x in paths.values() if not os.path.exists(x))); continue
    for opt, p in paths.items():
        if os.path.getsize(p) == 0:
            fail(f"{p} is empty"); continue
        d = json.load(open(p))
        if not d.get("summary") or not d.get("final_plan"):
            fail(f"{p} has no summary or final_plan")
        if opt == "calcite" and d["summary"].get("registered", 0) == 0:
            fail(f"{p} registered 0 nodes (listener not attached?)")
print("  done")

# 2. Top-level rows and costs: Calcite vs PostgreSQL EXPLAIN (fair mode)
print("2. Rows and costs, Calcite vs PostgreSQL")
print(f"  {'Q':<3} {'PG cost':>18} {'Calcite cost':>18} {'PG rows':>8} {'Cal rows':>8}  result")
pg_line = re.compile(r"cost=([\d.]+)\.\.([\d.]+) rows=(\d+)")
QUERIES = [q for q in QUERIES if q not in skipped]
for q in QUERIES:
    try:
        c = json.load(open(f"traces/calcite_{q}{SUFFIX}.json"))["final_plan"]
        exp = open(f"stats/pg_trace_fair/{q}_explain.txt").read()
    except Exception as e:
        fail(f"{q}: {e}"); continue
    m = pg_line.search(exp)
    ps, pt, pr = float(m[1]), float(m[2]), int(m[3])
    cs, ct, cr = c["startup"], c["total"], round(c["rows"])
    same = abs(ps - cs) <= TOL and abs(pt - ct) <= TOL and pr == cr
    print(f"  {q:<3} {ps:>8.2f}..{pt:<8.2f} {cs:>8.2f}..{ct:<8.2f} {pr:>8} {cr:>8}  {'match' if same else 'DIFFERENT'}")
    if not same:
        fail(f"{q} differs: explain it in plan_comparison.md or fix it")

# 3. Same join order? Compare the order tables appear in each plan tree
print("3. Table order in the chosen plan")
def calcite_tables(n):
    out = [n["table"].split("__")[0]] if "table" in n else []   # alias tables: "b__b1" is table b
    for k in n.get("children", []):
        out += calcite_tables(k)
    return out
for q in QUERIES:
    c = calcite_tables(json.load(open(f"traces/calcite_{q}{SUFFIX}.json"))["final_plan"])
    p = re.findall(r"Seq Scan on (\w+)", open(f"stats/pg_trace_fair/{q}_explain.txt").read())
    print(f"  {q}: PG {' '.join(p):<10} Calcite {' '.join(c):<10} {'same' if c == p else 'DIFFERENT'}")

print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED (see above)")
sys.exit(0 if ok else 1)
