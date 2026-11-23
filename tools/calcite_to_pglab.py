#!/usr/bin/env python3
"""Task (iii), step 1: turn Calcite's chosen plans into pg_lab hint blocks, and list where they differ from PostgreSQL.

For every query and Calcite mode with a trace (traces/calcite_<Q><suffix>.json) it
  1. reduces Calcite's final plan to its join tree: joins (outer = left/probe, inner = right/build) and scans;
     Project, Filter, Sort and other one-input operators are skipped (PostgreSQL adds its own sorts);
  2. writes LOAD 'pg_lab' + fair-mode settings + a pg_lab hint block + the query to stats/forced/<Q><suffix>.sql
     (pg_lab ignores hints unless LOAD 'pg_lab' ran in the session), e.g. for Q4:
        /*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
           JoinOrder((c (b a)))  HashJoin(b a)  HashJoin(c b a)
           SeqScan(a) SeqScan(b) SeqScan(c) */
        SELECT ...
  3. compares the join tree with PostgreSQL's native plan (traces/pg_<Q>.json, fair mode):
        same      = same tree, same outer/inner sides, same join methods -> no forced run needed
        mirrored  = same tree once outer/inner are ignored, but some join has its sides swapped
        ops       = same tree and sides, different join method somewhere
        different = different join tree
  4. marks a plan "not forceable" if any of its joins has no join predicate between its two sides (a cross
     product): pg_lab can't force an intermediate PostgreSQL never builds.

Output: stats/forced/*.sql, stats/forced/index.json (for tools/run_forced.py) and stats/forced/index.md.
Plans that are identical across modes are written once; the index lists every mode that produced them.

Run from the repo root:
  python3 tools/calcite_to_pglab.py                 # every query and mode that has a trace
  python3 tools/calcite_to_pglab.py --job           # JOB: traces/job/, original SQL from job/, out: stats/forced/job/
  python3 tools/calcite_to_pglab.py Q4 Q8           # only these queries
  python3 tools/calcite_to_pglab.py --mode _nosort_topdown
"""
import glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search_space_size import parse, join_graph          # same SQL parser and join graph as Workstream B

CONFIG = "Config(plan_mode=full; exec_mode=sequential)"
# pg_lab only reads hints once its library is loaded in the session (tested 23 Nov: without LOAD the hint
# block is silently ignored). The settings are fair mode, as in every other run.
PREAMBLE = ("LOAD 'pg_lab';\n"
            "SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;\n"
            "SET max_parallel_workers_per_gather = 0; SET geqo = off;\n")   # geqo: JOB has 12-17 table queries
JOIN_HINT = {"EnumerableHashJoin": "HashJoin", "EnumerableMergeJoin": "MergeJoin",
             "EnumerableNestedLoopJoin": "NestLoop", "EnumerableBatchNestedLoopJoin": "NestLoop",
             # our own nested-loop rule (option nlj) produces EnumerableNestedLoopJoin as well
             }
PG_JOIN = {"HashJoin": "HashJoin", "MergeJoin": "MergeJoin", "NestLoop": "NestLoop", "NestedLoop": "NestLoop"}
OUT_DIR = "stats/forced"


# ---------------- plan trees ----------------
# A tree is ("scan", alias) or ("join", method, outer, inner).

def calcite_tree(node):
    op = node["op"]
    kids = node.get("children", [])
    if op in JOIN_HINT:
        if len(kids) != 2:
            raise ValueError(f"{op} with {len(kids)} inputs")
        return ("join", JOIN_HINT[op], calcite_tree(kids[0]), calcite_tree(kids[1]))
    if op.endswith("TableScan"):
        name = (node.get("alias") or node["table"]).lower()
        return ("scan", name.split("__", 1)[1] if "__" in name else name)   # JOB: "title__t" -> alias "t"
    if len(kids) == 1:                      # Project, Filter, Sort, Calc, Aggregate, converters
        return calcite_tree(kids[0])
    raise ValueError(f"don't know how to translate {op} with {len(kids)} inputs")


def pg_tree(node):
    op = node["op"]
    kids = node.get("children", [])
    if op in PG_JOIN:
        return ("join", PG_JOIN[op], pg_tree(kids[0]), pg_tree(kids[1]))
    if not kids:
        return ("scan", node["set"][0].lower())
    if len(kids) == 1:                      # Sort, Material, Memoize, Hash ...
        return pg_tree(kids[0])
    raise ValueError(f"PostgreSQL node {op} with {len(kids)} inputs")


def aliases(t):
    return [t[1]] if t[0] == "scan" else aliases(t[2]) + aliases(t[3])


def order_str(t):
    """pg_lab JoinOrder notation: (outer inner), nested."""
    return t[1] if t[0] == "scan" else f"({order_str(t[2])} {order_str(t[3])})"


def shape(t, keep_sides=True, keep_ops=True):
    """Canonical form for comparing trees."""
    if t[0] == "scan":
        return t[1]
    a, b = shape(t[2], keep_sides, keep_ops), shape(t[3], keep_sides, keep_ops)
    if not keep_sides:
        a, b = sorted([a, b], key=str)
    return (t[1] if keep_ops else "J", a, b)


def compare(cal, pg):
    if pg is None:
        return "no PG trace"
    if shape(cal) == shape(pg):
        return "same"
    if shape(cal, keep_ops=False) == shape(pg, keep_ops=False):
        return "ops"
    if shape(cal, keep_sides=False, keep_ops=False) == shape(pg, keep_sides=False, keep_ops=False):
        return "mirrored" if shape(cal, keep_sides=False) == shape(pg, keep_sides=False) else "mirrored+ops"
    return "different"


def cross_products(t, adj, index):
    """Joins whose two sides share no join predicate (in PostgreSQL's graph, incl. implied predicates)."""
    if t[0] == "scan":
        return []
    left, right = aliases(t[2]), aliases(t[3])
    lm = rmask = 0
    for a in left:
        lm |= adj[index[a]]
    for a in right:
        rmask |= 1 << index[a]
    bad = [] if lm & rmask else [f"{' '.join(left)} x {' '.join(right)}"]
    return bad + cross_products(t[2], adj, index) + cross_products(t[3], adj, index)


def hint_block(t):
    lines = [CONFIG]
    if t[0] == "join":
        ops = []
        def walk(n):
            if n[0] == "join":
                walk(n[2]); walk(n[3])
                ops.append(f"{n[1]}({' '.join(aliases(n))})")
        walk(t)
        lines.append(f"JoinOrder({order_str(t)})  " + "  ".join(ops))
    lines.append(" ".join(f"SeqScan({a})" for a in sorted(aliases(t))))
    return "/*=pg_lab= " + "\n   ".join(lines) + " */"


# ---------------- main ----------------

def main(argv):
    job = "--job" in argv
    argv = [a for a in argv if a != "--job"]
    global OUT_DIR
    if job:
        OUT_DIR = "stats/forced/job"
    mode_filter = None
    if "--mode" in argv:
        i = argv.index("--mode")
        mode_filter = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    only = {q.upper() for q in argv}

    found = {}                                          # (query, suffix) -> path
    pattern, regex = (("traces/job/calcite_*.json", r"traces/job/calcite_(\d+[a-z])(.*)\.json$") if job else
                      ("traces/calcite_Q*.json", r"traces/calcite_(Q\d+)(.*)\.json$"))
    for f in glob.glob(pattern):
        m = re.match(regex, f)
        if not m:
            continue
        q, suffix = m.group(1), m.group(2)
        if only and q.upper() not in only:
            continue
        if mode_filter is not None and suffix != mode_filter:
            continue
        found[(q, suffix)] = f
    if not found:
        sys.exit("no Calcite traces matched")

    os.makedirs(OUT_DIR, exist_ok=True)
    plans = {}                                          # (query, hint) -> entry
    problems = []
    def qkey(q):                                        # Q4 -> 4; 13a -> (13, "a")
        m = re.match(r"Q?(\d+)([a-z]?)", q)
        return (int(m.group(1)), m.group(2))
    for (q, suffix), f in sorted(found.items(), key=lambda x: (qkey(x[0][0]), x[0][1])):
        t = json.load(open(f))
        try:
            cal = calcite_tree(t["final_plan"])
        except ValueError as e:
            problems.append(f"{q}{suffix}: {e}")
            continue
        if job:   # Calcite planned a rewritten copy (quoted, alias tables); PostgreSQL gets JOB's own text
            sql = open(f"job/{q}.sql").read().strip().rstrip(";")
        else:
            sql = t["sql"].strip().rstrip(";")
        pg = None
        for pgf in ([f"traces/job/pg_{q}.json", f"traces/pg_{q}.json"] if job else [f"traces/pg_{q}.json"]):
            if os.path.exists(pgf):
                pg = pg_tree(json.load(open(pgf))["final_plan"])
                break
        names, preds = parse(sql)
        adj = join_graph(names, preds, implied=True)
        crosses = cross_products(cal, adj, {a: i for i, a in enumerate(names)})
        hint = hint_block(cal)
        key = (q, hint)
        if key not in plans:
            plans[key] = {
                "query": q, "modes": [], "file": f"{OUT_DIR}/{q}{suffix or '_default'}.sql",
                "join_order": order_str(cal), "calcite_cost": round(t["final_plan"]["total"], 2),
                "pg_join_order": order_str(pg) if pg else None,
                "vs_pg": compare(cal, pg),
                "forceable": not crosses, "cross_products": crosses,
                "preamble": PREAMBLE, "hint": hint, "sql": sql,
            }
            open(plans[key]["file"], "w").write(PREAMBLE + hint + "\n" + sql + ";\n")
        plans[key]["modes"].append(suffix or "(default: sorts)")

    rows = sorted(plans.values(), key=lambda p: (qkey(p["query"]), p["vs_pg"] == "same", p["file"]))
    json.dump(rows, open(f"{OUT_DIR}/index.json", "w"), indent=1)

    need = [p for p in rows if p["vs_pg"] != "same"]
    md = ["# Calcite plans as pg_lab hints (task iii)", "",
          "Generated by `tools/calcite_to_pglab.py`. One row per distinct Calcite plan; *modes* lists every Calcite",
          "mode that chose it. vs PG: same / ops (join method differs) / mirrored (outer and inner swapped somewhere) /",
          "different (other join tree). Only plans that are not `same` need a forced run.", "",
          f"Plans needing a forced run: **{len(need)}** of {len(rows)} "
          f"({sum(1 for p in need if not p['forceable'])} not forceable).", "",
          "| Query | Calcite join order | Calcite cost | PostgreSQL join order | vs PG | Forceable | Modes | File |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for p in rows:
        md.append(f"| {p['query']} | `{p['join_order']}` | {p['calcite_cost']} | `{p['pg_join_order'] or '–'}` | "
                  f"{p['vs_pg']} | {'yes' if p['forceable'] else 'no: ' + '; '.join(p['cross_products'])} | "
                  f"{', '.join(p['modes'])} | `{os.path.basename(p['file'])}` |")
    open(f"{OUT_DIR}/index.md", "w").write("\n".join(md) + "\n")
    print("\n".join(md))
    for p in problems:
        print("SKIPPED", p, file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
