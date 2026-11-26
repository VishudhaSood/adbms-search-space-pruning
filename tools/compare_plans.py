#!/usr/bin/env python3
"""Task (ii): compare Calcite's JOB plans with PostgreSQL's, and give each difference a first-pass cause.

For every JOB query with both traces (traces/job/calcite_<q><suffix>.json[.gz] and traces/job/pg_<q>.json[.gz]):
  1. join trees: same / ops (a join method differs) / mirrored (outer and inner swapped somewhere) / different;
  2. cause, the first test that applies, in this order:
       same plan          identical tree, sides and join methods
       row estimates      a table set in either plan has Calcite and PostgreSQL row estimates more than ROW_TOL
                          apart (base tables are tested first, then joins). Different estimates make the two
                          optimizers compare different numbers, whatever their search does.
       search space       one optimizer's plan uses a table set the other never built (e.g. PostgreSQL joins
                          two tables through a predicate it inferred; Calcite with nocross can't)
       cost-model gap     same row estimates, same table sets available, but the plans differ: each optimizer
                          prices the other's plan differently. Task (iii) forces Calcite's plan onto PostgreSQL to
                          confirm. With a top-down Calcite mode, a Calcite plan costlier than PostgreSQL's is
                          reported as "search failure" instead (top-down can miss plans, Findings 1 and 4).
                          Costs within COST_TOL of each other are "near tie".
  3. the costs of both plans (at the top join; PostgreSQL's trace leaves out the Aggregate), and the table set
     whose row estimates are furthest apart.

Run from the repo root:
  python3 tools/compare_plans.py                              # Calcite mode _nosort_nocross_exchange
  python3 tools/compare_plans.py _nosort_topdown_nocross_exchange
Writes stats/job_compare<suffix>.md and .json.
"""
import glob, gzip, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calcite_to_pglab import calcite_tree, pg_tree, compare, order_str

ROW_TOL = 1.10      # row estimates more than 10% apart count as different
COST_TOL = 0.01     # costs within 1% are a near tie

JOIN_OPS = ("Join",)
SCAN_OPS = ("TableScan",)


def load(path):
    for p in (path, path + ".gz"):
        if os.path.exists(p):
            return json.load(gzip.open(p, "rt") if p.endswith(".gz") else open(p))
    return None


def alias(table):
    table = table.lower()
    return table.split("__", 1)[1] if "__" in table else table


# ---------- row estimates per table set ----------

def calcite_rows(plan):
    """{frozenset(aliases): rows} for every join, filter and scan in Calcite's plan (topmost node per set)."""
    out = {}
    # pre-order: record before visiting children
    def pre(n):
        if any(k in n["op"] for k in SCAN_OPS):
            return frozenset([alias(n["table"])])
        sets = [pre(c) for c in n.get("children", [])]
        s = frozenset().union(*sets) if sets else frozenset()
        return s
    def record(n):
        s = pre(n)
        if s and (any(k in n["op"] for k in JOIN_OPS + SCAN_OPS) or "Filter" in n["op"]):
            out.setdefault(s, n["rows"])
        for c in n.get("children", []):
            record(c)
    record(plan)
    return out


def pg_rows(trace):
    """{frozenset(aliases): rows} for every table set PostgreSQL built (largest estimate among its surviving
    paths, so parameterized paths don't count), plus its final plan."""
    out = {}
    surv = trace.get("survivors") or []
    for entry in surv:
        key, paths = entry if isinstance(entry, list) else (entry, surv[entry])
        rows = [p["rows"] for p in paths if "rows" in p]
        if rows:
            out[frozenset(a.lower() for a in (key.split() if isinstance(key, str) else key))] = max(rows)
    def walk(n):
        out.setdefault(frozenset(a.lower() for a in n["set"]), n["rows"])
        for c in n.get("children", []):
            walk(c)
    walk(trace["final_plan"])
    return out


def ratio(a, b):
    a, b = max(a, 1.0), max(b, 1.0)
    return max(a, b) / min(a, b)


def top_join(n):
    """The topmost join (skip Aggregate / Project / Sort above it); for a 1-table plan, the plan itself."""
    while not any(k in n["op"] for k in JOIN_OPS) and len(n.get("children", [])) == 1:
        n = n["children"][0]
    return n


def fmt_set(s):
    return "{" + ",".join(sorted(s)) + "}"


# ---------- per query ----------

def classify(q, cal, pg, topdown):
    cplan, pplan = cal["final_plan"], pg["final_plan"]
    ctree, ptree = calcite_tree(cplan), pg_tree(pplan)
    vs = compare(ctree, ptree)
    crows, prows = calcite_rows(cplan), pg_rows(pg)
    pfinal = {}
    def walk(n):
        pfinal[frozenset(a.lower() for a in n["set"])] = n["rows"]
        for c in n.get("children", []):
            walk(c)
    walk(pplan)

    # row estimates on every set either plan uses, where both optimizers have a number
    diffs = []
    for s in set(crows) | set(pfinal):
        if s in crows and s in prows:
            diffs.append((ratio(crows[s], prows[s]), s, crows[s], prows[s]))
    worst = max(diffs, key=lambda d: d[0]) if diffs else None
    base_bad = [d for d in diffs if len(d[1]) == 1 and d[0] > ROW_TOL]
    join_bad = [d for d in diffs if len(d[1]) > 1 and d[0] > ROW_TOL]

    c_built = {frozenset(alias(t) for t in s["tables"]) for s in cal.get("sets", []) if s.get("tables")}
    p_built = {frozenset(a.lower() for a in (e["set"])) for e in pg.get("per_set", [])}
    c_only = sorted((s for s in crows if len(s) > 1 and p_built and s not in p_built), key=len)
    p_only = sorted((s for s in pfinal if len(s) > 1 and c_built and s not in c_built), key=len)

    ccost, pcost = top_join(cplan)["total"], pplan["total"]
    rel = (ccost - pcost) / max(pcost, 1e-9)

    if vs == "same":
        cause, detail = "same plan", ""
    elif base_bad:
        d = max(base_bad, key=lambda d: d[0])
        cause, detail = "row estimates", f"base {fmt_set(d[1])}: Calcite {d[2]:.0f} vs PG {d[3]:.0f}"
    elif join_bad:
        d = max(join_bad, key=lambda d: d[0])
        cause, detail = "row estimates", f"join {fmt_set(d[1])}: Calcite {d[2]:.0f} vs PG {d[3]:.0f}"
    elif p_only:
        cause, detail = "search space", f"Calcite never built {fmt_set(p_only[0])} (in PG's plan)"
    elif c_only:
        cause, detail = "search space", f"PG never built {fmt_set(c_only[0])} (in Calcite's plan)"
    elif abs(rel) <= COST_TOL:
        cause, detail = "near tie", f"costs {rel:+.1%} apart"
    elif rel > 0 and topdown:
        cause, detail = "search failure", f"Calcite's plan costs {rel:+.1%} vs PG's (top-down missed a cheaper plan?)"
    else:
        cause, detail = "cost-model gap", f"Calcite's plan {rel:+.1%} vs PG's plan (each in its own model)"
    return {
        "query": q, "tables": len(pg.get("tables", [])),
        "vs_pg": vs, "cause": cause, "detail": detail,
        "calcite_cost": round(ccost, 2), "pg_cost": round(pcost, 2), "cost_diff": round(rel, 4),
        "worst_rows": None if not worst else {"set": sorted(worst[1]), "calcite": worst[2], "pg": worst[3],
                                              "ratio": round(worst[0], 2)},
        "calcite_order": order_str(ctree), "pg_order": order_str(ptree),
        "light_trace": bool(cal.get("light_trace")),
    }


def main(argv):
    suffix = argv[0] if argv else "_nosort_nocross_exchange"
    topdown = "topdown" in suffix
    names = set()
    for f in glob.glob("traces/job/pg_*.json*"):
        m = re.match(r"traces/job/pg_(\d+[a-z])\.json(\.gz)?$", f)
        if m:
            names.add(m.group(1))
    names = sorted(names, key=lambda q: (int(re.match(r"\d+", q).group()), q))
    rows, skipped = [], []
    for q in names:
        cal = load(f"traces/job/calcite_{q}{suffix}.json")
        pg = load(f"traces/job/pg_{q}.json")
        if cal is None or pg is None:
            skipped.append(q)
            continue
        try:
            rows.append(classify(q, cal, pg, topdown))
        except Exception as e:                       # one odd trace shouldn't stop the table
            skipped.append(f"{q} ({type(e).__name__}: {e})")

    counts = {}
    for r in rows:
        counts[r["cause"]] = counts.get(r["cause"], 0) + 1
    order = ["same plan", "row estimates", "search space", "cost-model gap", "search failure", "near tie"]
    md = [f"# JOB: Calcite (`{suffix}`) vs PostgreSQL plans (task ii)", "",
          "Generated by `tools/compare_plans.py`. Cause = the first test that applies: same plan; row estimates "
          f"(a table set's estimates differ by more than {ROW_TOL - 1:.0%}); search space (one side's plan uses a "
          "table set the other never built); cost-model gap or search failure (same estimates and sets, different "
          f"plan); near tie (costs within {COST_TOL:.0%}). Costs are at the top join. A first pass: task (iii) "
          "forced runs confirm cost-model gaps.", "",
          f"**{len(rows)} queries compared** ({len(skipped)} skipped: no trace on one side). " +
          ", ".join(f"{k}: {counts[k]}" for k in order if k in counts), "",
          "| Query | Tables | vs PG | Cause | Detail | Calcite cost | PG cost | Worst row ratio | Calcite plan | PG plan |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        w = r["worst_rows"]
        md.append(f"| {r['query']} | {r['tables']} | {r['vs_pg']} | {r['cause']} | {r['detail']} | "
                  f"{r['calcite_cost']:,.2f} | {r['pg_cost']:,.2f} | "
                  f"{'' if not w else str(w['ratio']) + ' ' + fmt_set(w['set'])} | "
                  f"`{r['calcite_order']}` | `{r['pg_order']}` |")
    if skipped:
        md += ["", "Skipped: " + ", ".join(skipped)]
    os.makedirs("stats", exist_ok=True)
    open(f"stats/job_compare{suffix}.md", "w").write("\n".join(md) + "\n")
    json.dump({"suffix": suffix, "counts": counts, "skipped": skipped, "queries": rows},
              open(f"stats/job_compare{suffix}.json", "w"), indent=1)
    print("\n".join(md[:6]))
    print(f"-> stats/job_compare{suffix}.md")


if __name__ == "__main__":
    main(sys.argv[1:])
