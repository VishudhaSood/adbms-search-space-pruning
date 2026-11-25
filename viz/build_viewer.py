#!/usr/bin/env python3
"""Build viz/search_space.html from the trace files in traces/.

Run from the repo root (/workspaces/pg_dev) after tools/pg_trace.sh and the Calcite run:
    python3 viz/build_viewer.py
Then open viz/search_space.html in a browser (no server needed; the data is inside the page).

What goes into the page, per query in tools/queries.txt:
  pg, pg_native   traces/pg_<Q>.json, traces/pg_<Q>_native.json   (events with t = µs since planning started)
  cals            every traces/calcite_<Q><mode>.json, keyed by mode ("" = default bottom-up with sorts)
  timing          untraced planning time per engine, so the replay clock runs at real (untraced) speed:
                    PG:      stats/pg_planning_overhead.md (median, 1 warm-up + 5 runs)
                    Calcite: the trace's own "timing" block (median of the untraced runs)
  exec            execution time at the end of the replay (optional):
                    stats/exec_times.json (tools/exec_times.py: EXPLAIN ANALYZE median of PostgreSQL's plan)
                    stats/forced/run_forced.json (task iii: PostgreSQL running Calcite's plan, where it differs)
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACES = os.path.join(ROOT, "traces")
STATS = os.path.join(ROOT, "stats")
TEMPLATE = os.path.join(ROOT, "viz", "viewer_template.html")
OUT = os.path.join(ROOT, "viz", "search_space.html")

RES = {"precheck": "P", "rejected": "R", "evicted": "E", "kept": "K"}


def short_op(op):
    op = op.replace("Enumerable", "").replace("NestedLoopJoin", "NestLoop")
    op = op.replace("TableScan", "Scan")
    if op.startswith("Logical"):
        op = "L·" + op[len("Logical"):]
    return op


def join_edges(sql):
    return sorted({tuple(sorted(p)) for p in re.findall(r"(\w+)\.\w+\s*=\s*(\w+)\.\w+", sql)
                   if p[0] != p[1]})


def compact_pg_tree(t):
    if not t:
        return None
    return {"o": t.get("op"), "s": ",".join(t.get("set", [])), "st": t.get("startup"),
            "t": t.get("total"), "r": t.get("rows"),
            "c": [compact_pg_tree(c) for c in t.get("children", [])]}


SKIP = {"EnumerableProject", "LogicalProject", "AbstractConverter"}


def compact_cal_tree(t):
    """Drop Project / converter nodes so the tree shows the same operators as EXPLAIN."""
    if not t:
        return None
    while t.get("op") in SKIP and len(t.get("children", [])) == 1:
        t = t["children"][0]
    return {"o": short_op(t.get("op", "?")), "tb": t.get("table"), "st": t.get("startup"),
            "t": t.get("total"), "r": t.get("rows"),
            "c": [compact_cal_tree(c) for c in t.get("children", [])]}


def load(path):
    with open(path) as f:
        return json.load(f)


def pg_untraced_ms():
    """query -> untraced median planning time (ms) from tools/pg_overhead.py's table."""
    out = {}
    p = os.path.join(STATS, "pg_planning_overhead.md")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"\| (Q\w+) \| ([\d.]+) \| ([\d.]+) \|", line)
            if m:
                out[m[1]] = float(m[2])
    return out


def pg_entry(d, untraced_ms=None):
    # event: [set, op, inputs, startup, total, rows, sorted, disabled, result, t_us, sortkey]
    ev = [[",".join(e["set"]), e["op"], [",".join(i) for i in e["inputs"]], e["startup"], e["total"],
           e["rows"], 1 if e["sorted"] else 0, e["disabled"], RES[e["result"]], e.get("t"), e.get("sortkey")]
          for e in d["events"]]
    surv = {k: [[s["op"], 1 if s["sorted"] else 0, s["disabled"], s.get("sortkey"), s["total"]] for s in v]
            for k, v in d.get("survivors", {}).items()}
    last_t = max([e[9] for e in ev if e[9] is not None] or [0])
    return {"tables": d["tables"], "summary": d["summary"],
            "retained": {",".join(p["set"]): p["retained"] for p in d["per_set"]},
            "surv": surv, "ev": ev, "plan": compact_pg_tree(d["final_plan"]), "explain": d.get("explain"),
            "timing": {"last_t_us": last_t, "untraced_ms": untraced_ms}}


def cal_entry(d):
    sets = {s["id"]: ",".join(s["tables"]) for s in d["sets"]}
    rule_of = {e["node"]: re.sub(r"\(.*", "", e["rule"]) for e in d["events"]}
    nodes = []
    for n in d["nodes"]:
        if n.get("set") is None:
            continue
        # [node, op, physical, set, input sets, startup, total, rows, chosen, winner, rule, sorted_on, traits]
        nodes.append([n["node"], short_op(n["op"]), 1 if n["physical"] else 0, n["set"],
                      [i["set"] for i in n.get("inputs", [])], n.get("startup"), n.get("total"),
                      n.get("rows"), 1 if n.get("chosen") else 0, 1 if n.get("winner") else 0,
                      rule_of.get(n["node"], ""), n.get("sorted_on") or [], n.get("traits", "")])
    order = [e["node"] for e in d["events"]]
    times = [e.get("t_us") for e in d["events"]]
    tl = [{"step": s["step"], "st": s["startup"], "t": s["total"], "plan": compact_cal_tree(s["plan"])}
          for s in d["timeline"]]
    tm = d.get("timing") or {}
    last_t = max([t for t in times if t is not None] or [0])
    untraced = tm.get("planning_us_untraced_median") or (d.get("summary") or {}).get("planning_us_untraced_median")
    return {"sets": sets, "nodes": nodes, "order": order, "times": times, "summary": d["summary"],
            "timeline": tl, "plan": compact_cal_tree(d.get("final_plan")),
            "timing": {"last_t_us": last_t, "untraced_ms": untraced / 1000 if untraced else None}}


def exec_times():
    """query -> {"pg": ms, "cal": {mode: ms}}; Calcite's plan only where task (iii) forced it."""
    out = {}
    p = os.path.join(STATS, "exec_times.json")
    if os.path.exists(p):
        for q, ms in load(p).items():
            out.setdefault(q, {"pg": None, "cal": {}})["pg"] = ms
    p = os.path.join(STATS, "forced", "run_forced.json")
    if os.path.exists(p):
        for r in load(p):
            e = out.setdefault(r["query"], {"pg": None, "cal": {}})
            if r["native"].get("status") == "ok" and e["pg"] is None:
                e["pg"] = r["native"]["exec_ms"]
            if r["forced"].get("status") == "ok":
                for m in r["modes"]:
                    e["cal"]["" if m.startswith("(default") else m] = r["forced"]["exec_ms"]
    return out


def main():
    queries = {}
    with open(os.path.join(ROOT, "tools", "queries.txt")) as f:
        for line in f:
            if "|" in line:
                q, sql = line.strip().split("|", 1)
                queries[q] = sql
    pg_ms = pg_untraced_ms()
    ex = exec_times()
    data = {"queries": []}
    for q, sql in queries.items():
        entry = {"q": q, "sql": sql, "joins": join_edges(sql), "cals": {}, "exec": ex.get(q)}
        for key, fn in (("pg", f"pg_{q}.json"), ("pg_native", f"pg_{q}_native.json")):
            p = os.path.join(TRACES, fn)
            if os.path.exists(p):
                entry[key] = pg_entry(load(p), pg_ms.get(q) if key == "pg" else None)
        for p in sorted(glob.glob(os.path.join(TRACES, f"calcite_{q}.json")) +
                        glob.glob(os.path.join(TRACES, f"calcite_{q}_*.json"))):
            mode = os.path.basename(p)[len(f"calcite_{q}"):-len(".json")]
            entry["cals"][mode] = cal_entry(load(p))
        if "pg" in entry or entry["cals"]:
            data["queries"].append(entry)
    if not data["queries"]:
        sys.exit("No traces found in traces/")
    html = open(TEMPLATE, encoding="utf-8").read().replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
    open(OUT, "w", encoding="utf-8").write(html)
    n_modes = sum(len(x["cals"]) for x in data["queries"])
    print(f"Wrote {OUT} ({len(html)//1024} KB, {len(data['queries'])} queries, {n_modes} Calcite traces)")


if __name__ == "__main__":
    main()
