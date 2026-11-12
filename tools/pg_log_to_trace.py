#!/usr/bin/env python3
"""Turn the TRACE lines from patches/search_space_trace.patch into a trace JSON
that viz/search_space_viewer.html can draw.

Usage:
  python3 tools/pg_log_to_trace.py stats/pg_trace_fair/Q4.log --query Q4 \
      --sql "SELECT ..." --explain stats/pg_trace_fair/Q4_explain.txt -o traces/pg_Q4.json

What the log lines mean (one per event, in the order PostgreSQL did them):
  baserel  relid=1 name=a          which table each relid number is
  precheck ...                     join path thrown away BEFORE it was built
                                   (add_path_precheck: its lower-bound cost already loses)
  kept     ...                     add_path accepted the new path
  rejected ...                     add_path threw the new path away (an old one dominates it)
  evict    ...                     an older path was removed because the new one dominates it
  survivor ...                     paths still in the pathlist when set_cheapest runs (= retained)
"""
import argparse
import json
import re
import sys

LINE = re.compile(r"TRACE (\w+) (.*)$")
FIELD = re.compile(r"(\w+)=(\([^)]*\)|\S+)")


def bms(s):
    """'(b 1 2)' -> [1, 2]; '-' -> None"""
    if s == "-":
        return None
    nums = re.findall(r"\d+", s)
    return [int(n) for n in nums]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--query", default="Q?")
    ap.add_argument("--sql", default="")
    ap.add_argument("--explain", default=None)
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()

    names = {}          # relid -> table name
    raw = []            # parsed events before relid -> name mapping
    with open(a.log, errors="replace") as f:
        for line in f:
            m = LINE.search(line)
            if not m:
                continue
            what, rest = m.group(1), m.group(2)
            fields = dict(FIELD.findall(rest))
            if what == "baserel":
                names[int(fields["relid"])] = fields["name"]
                continue
            raw.append((what, fields))

    if not raw:
        sys.exit("No TRACE lines found. Is the patch installed and client_min_messages = log?")

    def tables(ids):
        if ids is None:
            return None
        return sorted(names.get(i, f"rel{i}") for i in ids)

    events, survivors, last_surv_key = [], {}, None
    step = 0
    for what, fd in raw:
        if fd.get("kind") == "upper":       # SELECT/projection steps above the joins: not part of the join search
            continue
        ids = bms(fd["rels"])
        if not ids:
            continue
        ev = {
            "set": tables(ids),
            "op": fd.get("type"),
            "inputs": [t for t in (tables(bms(fd.get("outer", "-"))), tables(bms(fd.get("inner", "-")))) if t],
            "startup": float(fd.get("startup", 0)),
            "total": float(fd.get("total", 0)),
            "rows": float(fd.get("rows", 0)),
            "sorted": int(fd.get("keys", 0)) > 0,
            "disabled": int(fd.get("disabled", 0)),
        }
        key = ",".join(ev["set"])
        if what == "survivor":
            lst = survivors.get(key)
            same = lst and all(lst[0][f] == ev[f] for f in ("op", "startup", "total", "inputs"))
            if last_surv_key != key or same:  # a new set_cheapest call (PG can call it twice): start again
                survivors[key] = []
            survivors[key].append(ev)
            last_surv_key = key
            continue
        last_surv_key = None
        step += 1
        ev["step"] = step
        ev["result"] = {"kept": "kept", "rejected": "rejected", "evict": "evicted",
                        "precheck": "precheck"}[what]
        events.append(ev)

    # counts per set and overall
    per_set = {}
    for ev in events:
        k = ",".join(ev["set"])
        c = per_set.setdefault(k, {"set": ev["set"], "kept": 0, "rejected": 0, "evicted": 0,
                                   "precheck": 0, "retained": 0, "disabled_paths": 0})
        c[ev["result"]] += 1
        if ev["disabled"] and ev["result"] in ("kept", "rejected"):
            c["disabled_paths"] += 1
    for k, s in survivors.items():
        per_set.setdefault(k, {"set": k.split(","), "kept": 0, "rejected": 0, "evicted": 0,
                               "precheck": 0, "retained": 0, "disabled_paths": 0})
        per_set[k]["retained"] = len(s)

    tot = {f: sum(c[f] for c in per_set.values())
           for f in ("kept", "rejected", "evicted", "precheck", "retained", "disabled_paths")}
    all_tables = sorted(names.values())
    summary = {
        "tables": len(all_tables),
        "sets_built": len(per_set),
        "considered": tot["kept"] + tot["rejected"] + tot["precheck"],   # every path PG costed
        "built": tot["kept"] + tot["rejected"],                         # paths actually created
        "pruned_precheck": tot["precheck"],
        "pruned_on_arrival": tot["rejected"],
        "evicted_later": tot["evicted"],
        "retained": tot["retained"],
        "disabled_paths": tot["disabled_paths"],
    }

    # final plan: cheapest surviving path of the full set, then the same for each input (approximation)
    def best_of(key):
        s = survivors.get(key) or []
        s = sorted(s, key=lambda e: (e["disabled"], e["total"]))
        return s[0] if s else None

    def plan(key, depth=0):
        b = best_of(key)
        if b is None or depth > 20:
            return {"op": "?", "set": key.split(",")}
        node = {"op": b["op"], "set": b["set"], "startup": b["startup"], "total": b["total"],
                "rows": b["rows"], "children": []}
        for inp in b["inputs"]:
            node["children"].append(plan(",".join(inp), depth + 1))
        return node

    explain = open(a.explain).read() if a.explain else None
    out = {
        "optimizer": "pg",
        "query": a.query,
        "sql": a.sql,
        "tables": all_tables,
        "events": events,
        "survivors": survivors,
        "per_set": list(per_set.values()),
        "summary": summary,
        "final_plan": plan(",".join(all_tables)),
        "explain": explain,
    }
    js = json.dumps(out, indent=1)
    if a.out:
        open(a.out, "w").write(js)
        print(f"{a.query}: {summary}")
    else:
        print(js)


if __name__ == "__main__":
    main()
