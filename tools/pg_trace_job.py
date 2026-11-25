#!/usr/bin/env python3
"""Wednesday: trace PostgreSQL's join search on JOB queries (tasks ii and iv), on the correlated sample imdb_s10.

Per query (one psql session each, the same way tools/pg_trace.sh does Q1-Q14):
  1. traced EXPLAIN after a warm-up EXPLAIN  -> stats/pg_trace_job/<q>.log  (TRACE lines with t= in µs)
  2. plain EXPLAIN                           -> stats/pg_trace_job/<q>_explain.txt
  3. 1 warm-up + RUNS untraced EXPLAIN (SUMMARY) -> median planning time (for the replay clock and planning-time charts)
  4. tools/pg_log_to_trace.py                -> traces/job/pg_<q>.json   (the same format as traces/pg_Q4.json)
Settings for every run: fair mode (no index / index-only / bitmap scans), geqo off (the exhaustive DP up to 17 tables),
no parallel workers, jit off, work_mem 1GB (hash joins fit in memory, as our Calcite cost model assumes).

Usage (repo root, after: source env.sh):
  python3 tools/pg_trace_job.py                 # every JOB query with <= 8 tables (MAXT=8)
  MAXT=12 python3 tools/pg_trace_job.py         # up to 12 tables
  ONLY="1a 3a 32a" python3 tools/pg_trace_job.py
  env: DB=imdb_s10  JOB_DIR=job (falls back to imdb_data/job)  RUNS=3  WORK_MEM=1GB  TIMEOUT=10min
Writes stats/pg_trace_job/summary.md and summary.json (one row per query).
"""
import json, os, re, statistics, subprocess, sys, time

DB = os.environ.get("DB", "imdb_s10")
JOB_DIR = os.environ.get("JOB_DIR") or ("job" if os.path.isfile("job/1a.sql") else "imdb_data/job")  # job/ may be an empty gitlink
MAXT = int(os.environ.get("MAXT", 8))
RUNS = int(os.environ.get("RUNS", 3))
WORK_MEM = os.environ.get("WORK_MEM", "1GB")
TIMEOUT = os.environ.get("TIMEOUT", "10min")
OUT = "stats/pg_trace_job"
SETS = (f"SET log_min_messages = fatal; SET max_parallel_workers_per_gather = 0; SET jit = off; SET geqo = off; SET work_mem = '{WORK_MEM}'; "
        f"SET enable_indexscan = off; SET enable_bitmapscan = off; SET enable_indexonlyscan = off; "
        f"SET statement_timeout = '{TIMEOUT}';")
MARK = "@@@MARK@@@"
os.makedirs(OUT, exist_ok=True)
os.makedirs("traces/job", exist_ok=True)


def qkey(q):
    m = re.match(r"(\d+)([a-z]*)", q)
    return (int(m.group(1)), m.group(2)) if m else (10 ** 6, q)


sizes = {}
for x in json.load(open("stats/search_space_size_job.json")):
    sizes.setdefault(x["query"], x["tables"])
if os.environ.get("ONLY"):
    queries = os.environ["ONLY"].split()
else:
    queries = [q for q in sorted(sizes, key=qkey) if sizes[q] <= MAXT]
print(f"{len(queries)} JOB queries on {DB} (MAXT={MAXT}), queries from {JOB_DIR}/", flush=True)
print(f"{'query':6} {'tables':>6} {'log MB':>7} {'considered':>10} {'precheck':>9} {'retained':>8} {'untraced ms':>11} {'traced s':>9}", flush=True)

summary_path = f"{OUT}/summary.json"
summary = json.load(open(summary_path)) if os.path.exists(summary_path) else {}
for q in queries:
    sql = open(f"{JOB_DIR}/{q}.sql").read().strip().rstrip(";").strip()
    log = f"{OUT}/{q}.log"
    t0 = time.time()
    with open(log, "w") as f:      # 1. warm-up (no TRACE lines anywhere), then the traced EXPLAIN
        subprocess.run(["psql", DB, "-X", "-q", "-P", "pager=off",
                        "-c", f"{SETS} SET log_min_messages = fatal; EXPLAIN {sql}",
                        "-c", f"SET client_min_messages = log; EXPLAIN {sql}"], stdout=f, stderr=subprocess.STDOUT)
    traced_s = time.time() - t0
    with open(f"{OUT}/{q}_explain.txt", "w") as f:          # 2. the plan as PostgreSQL prints it
        subprocess.run(["psql", DB, "-X", "-q", "-P", "pager=off", "-c", f"{SETS} EXPLAIN {sql}"], stdout=f, stderr=subprocess.STDOUT)
    lines = [SETS] + [f"\\echo {MARK}\nEXPLAIN (SUMMARY, FORMAT JSON) {sql};" for _ in range(RUNS + 1)]
    p = subprocess.run(["psql", DB, "-X", "-q", "-A", "-t", "-f", "-"], input="\n".join(lines) + "\n",
                       capture_output=True, text=True)                 # 3. untraced planning time
    pts = []
    for part in p.stdout.split(MARK)[1:]:
        try:
            pts.append(json.loads(part.strip())[0]["Planning Time"])
        except (ValueError, IndexError, KeyError):
            pass
    plan_ms = statistics.median(pts[1:]) if len(pts) > 1 else None
    r = subprocess.run([sys.executable, "tools/pg_log_to_trace.py", log, "--query", q, "--sql", sql,
                        "--explain", f"{OUT}/{q}_explain.txt", "-o", f"traces/job/pg_{q}.json"],
                       capture_output=True, text=True)                 # 4. JSON trace
    try:
        m = json.load(open(f"traces/job/pg_{q}.json"))["summary"]
    except Exception:
        print(f"{q:6} FAILED: {(r.stderr or r.stdout)[-300:]}", flush=True)
        continue
    row = {"query": q, "tables": sizes.get(q), "log_mb": round(os.path.getsize(log) / 2 ** 20, 2),
           "considered": m["considered"], "precheck": m["pruned_precheck"], "built": m["built"],
           "rejected": m["pruned_on_arrival"], "evicted": m["evicted_later"], "retained": m["retained"],
           "untraced_plan_ms": plan_ms, "traced_s": round(traced_s, 2)}
    summary[q] = row
    print(f"{q:6} {row['tables']:>6} {row['log_mb']:>7.2f} {row['considered']:>10} {row['precheck']:>9} {row['retained']:>8} "
          f"{(f'{plan_ms:.1f}' if plan_ms is not None else '–'):>11} {traced_s:>9.1f}", flush=True)
    json.dump(summary, open(summary_path, "w"), indent=1)

rows = sorted(summary.values(), key=lambda r: qkey(r["query"]))
with open(f"{OUT}/summary.md", "w") as f:
    f.write("# PostgreSQL join search on JOB (imdb_s10, fair mode, geqo off)\n\n")
    f.write(f"Generated by `tools/pg_trace_job.py`. DB `{DB}`, work_mem {WORK_MEM}, jit off, no parallel workers. "
            f"Untraced planning time = median of {RUNS} EXPLAIN (SUMMARY) runs after 1 warm-up.\n\n")
    f.write("| query | tables | paths considered | pruned at precheck | built | rejected | evicted | retained | precheck share | untraced planning (ms) | trace log (MB) |\n")
    f.write("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n")
    for r in rows:
        share = r["precheck"] / r["considered"] if r["considered"] else 0
        f.write(f"| {r['query']} | {r['tables']} | {r['considered']:,} | {r['precheck']:,} | {r['built']:,} | {r['rejected']:,} | "
                f"{r['evicted']:,} | {r['retained']:,} | {share:.0%} | {r['untraced_plan_ms'] if r['untraced_plan_ms'] is not None else '–'} | {r['log_mb']} |\n")
print(f"wrote {OUT}/summary.md ({len(rows)} queries)")
