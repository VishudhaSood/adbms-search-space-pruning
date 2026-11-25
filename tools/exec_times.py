#!/usr/bin/env python3
"""Execution time of PostgreSQL's own plan for every query in tools/queries.txt (for the end of the viewer's replay).

Fair mode, jit off, no parallel workers; one psql session per query: 1 warm-up + RUNS x EXPLAIN (ANALYZE, FORMAT JSON),
median Execution Time. Calcite's plans that differ from PostgreSQL's are timed by tools/run_forced.py (task iii).

Usage (repo root):  python3 tools/exec_times.py          env: RUNS=5 DB=test
Writes stats/exec_times.json  ({"Q1": 0.41, ...}, milliseconds)
"""
import json, os, statistics, subprocess

RUNS = int(os.environ.get("RUNS", 5))
DB = os.environ.get("DB", "test")
SETS = ("SET log_min_messages = fatal; SET max_parallel_workers_per_gather = 0; SET jit = off; SET enable_indexscan = off; "
        "SET enable_bitmapscan = off; SET enable_indexonlyscan = off;")
MARK = "@@@MARK@@@"

out = {}
for line in open("tools/queries.txt"):
    if "|" not in line:
        continue
    q, sql = line.rstrip("\n").split("|", 1)
    lines = [SETS] + [f"\\echo {MARK}\nEXPLAIN (ANALYZE, FORMAT JSON) {sql};" for _ in range(RUNS + 1)]
    p = subprocess.run(["psql", DB, "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-f", "-"],
                       input="\n".join(lines) + "\n", capture_output=True, text=True, check=True)
    docs = [json.loads(x.strip())[0] for x in p.stdout.split(MARK)[1:]]
    ex = [d["Execution Time"] for d in docs[1:]]          # docs[0] is the warm-up
    out[q] = round(statistics.median(ex), 3)
    print(f"{q}: {out[q]:.3f} ms  (runs: {', '.join(f'{v:.2f}' for v in ex)})", flush=True)

json.dump(out, open("stats/exec_times.json", "w"), indent=1)
print("wrote stats/exec_times.json")
