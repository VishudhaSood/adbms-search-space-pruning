#!/usr/bin/env python3
"""Build viz/search_space.html from the trace files in traces/.

Run from the repo root (/workspaces/pg_dev) after tools/pg_trace.sh and the Calcite run:
    python3 viz/build_viewer.py
Then open viz/search_space.html in a browser (no server needed; the data is inside the page).
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACES = os.path.join(ROOT, "traces")
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


def pg_entry(d):
    ev = [[",".join(e["set"]), e["op"], [",".join(i) for i in e["inputs"]], e["startup"], e["total"],
           e["rows"], 1 if e["sorted"] else 0, e["disabled"], RES[e["result"]]] for e in d["events"]]
    return {"tables": d["tables"], "summary": d["summary"],
            "retained": {",".join(p["set"]): p["retained"] for p in d["per_set"]},
            "ev": ev, "plan": compact_pg_tree(d["final_plan"]), "explain": d.get("explain")}


def cal_entry(d):
    sets = {s["id"]: ",".join(s["tables"]) for s in d["sets"]}
    rule_of = {e["node"]: re.sub(r"\(.*", "", e["rule"]) for e in d["events"]}
    nodes = []
    for n in d["nodes"]:
        if n.get("set") is None:
            continue
        nodes.append([n["node"], short_op(n["op"]), 1 if n["physical"] else 0, n["set"],
                      [i["set"] for i in n.get("inputs", [])], n.get("startup"), n.get("total"),
                      n.get("rows"), 1 if n.get("chosen") else 0, 1 if n.get("winner") else 0,
                      rule_of.get(n["node"], "")])
    order = [e["node"] for e in d["events"]]
    tl = [{"step": s["step"], "st": s["startup"], "t": s["total"], "plan": compact_cal_tree(s["plan"])}
          for s in d["timeline"]]
    return {"sets": sets, "nodes": nodes, "order": order, "summary": d["summary"],
            "timeline": tl, "plan": compact_cal_tree(d.get("final_plan"))}


def main():
    queries = {}
    with open(os.path.join(ROOT, "tools", "queries.txt")) as f:
        for line in f:
            if "|" in line:
                q, sql = line.strip().split("|", 1)
                queries[q] = sql
    data = {"queries": []}
    for q, sql in queries.items():
        entry = {"q": q, "sql": sql, "joins": join_edges(sql)}
        for key, fn in (("pg", f"pg_{q}.json"), ("pg_native", f"pg_{q}_native.json"),
                        ("cal", f"calcite_{q}.json")):
            p = os.path.join(TRACES, fn)
            if os.path.exists(p):
                d = load(p)
                entry[key] = pg_entry(d) if key.startswith("pg") else cal_entry(d)
        if "pg" in entry or "cal" in entry:
            data["queries"].append(entry)
    if not data["queries"]:
        sys.exit("No traces found in traces/")
    html = open(TEMPLATE).read().replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
    open(OUT, "w").write(html)
    print(f"Wrote {OUT} ({len(html)//1024} KB, {len(data['queries'])} queries)")


if __name__ == "__main__":
    main()
