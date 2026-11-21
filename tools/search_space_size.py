#!/usr/bin/env python3
"""Workstream B: how big is the whole join search space of a query?

For each query it counts, from the tables and the join predicates:
  sets_connected     table sets (incl. single tables) that are connected in the join graph
                     = the most sets a cross-product-free DP can build (PostgreSQL's 'sets built' is at most this)
  steps_nocross      ordered DP join steps without cross products: pairs (S1, S2) of disjoint connected sets
                     linked by a predicate, S1 = outer, S2 = inner (2 x the csg-cmp pairs that DPccp enumerates)
  steps_cross        ordered DP join steps when cross products are allowed: any pair of disjoint non-empty sets
  bushy_nocross      complete join trees with no cross product anywhere; outer/inner kept apart (a⋈b != b⋈a)
  bushy_cross        complete join trees, cross products allowed = n! * Catalan(n-1)
  leftdeep_nocross   left-deep trees (inner always one table) with no cross product = the System R space
  leftdeep_cross     = n!
  *_physical         the same trees with one of 3 join methods (hash, merge, nested loop) per join: x 3^(n-1)

Join graph: an edge between two aliases if a predicate  x.col = y.col  links them. With --implied, aliases whose
columns end up in the same equivalence class are also linked (what PostgreSQL does: a.id = b.a_id and
a.id = e.a_id imply b.a_id = e.a_id, so b and e are linked). Calcite doesn't infer these.

Run from the repo root:
  python3 tools/search_space_size.py                      # Q1-Q9 from tools/queries.txt, both graphs
  python3 tools/search_space_size.py job/*.sql            # JOB query files (FROM t AS x, ... WHERE ...)
  python3 tools/search_space_size.py --implied job/1a.sql # PostgreSQL's graph only
Writes stats/search_space_size.md and stats/search_space_size.json (for the funnel plot). If traces/pg_<Q>.json
or traces/calcite_<Q><suffix>.json exist, their counts are added for comparison.
"""
import json, math, os, re, sys

KEYWORDS = {"on", "where", "join", "inner", "left", "right", "full", "outer", "cross", "natural", "using",
            "group", "order", "limit", "having", "union", "as"}


# ---------------- parsing ----------------

def strip_literals(sql):
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def parse(sql):
    """-> (list of aliases, list of (alias1, col1, alias2, col2) equality predicates)."""
    s = strip_literals(sql)
    m = re.search(r"\bfrom\b(.*?)(\bwhere\b|\bgroup\s+by\b|\border\s+by\b|\blimit\b|;|$)", s, re.I | re.S)
    if not m:
        raise ValueError("no FROM clause")
    from_part = re.sub(r"\bon\b.*?(?=\b(?:inner\s+|left\s+|right\s+|full\s+|cross\s+)?join\b|$)", " ",
                       m.group(1), flags=re.I | re.S)          # drop ON conditions; predicates are read below
    items = re.split(r",|\b(?:inner\s+|left\s+(?:outer\s+)?|right\s+(?:outer\s+)?|full\s+(?:outer\s+)?|cross\s+)?join\b",
                     from_part, flags=re.I)
    aliases = []
    for it in items:
        words = [w for w in re.findall(r"[A-Za-z_][\w.]*", it)]
        if not words:
            continue
        table = words[0].split(".")[-1]
        rest = [w for w in words[1:] if w.lower() != "as"]
        alias = rest[0] if rest and rest[0].lower() not in KEYWORDS else table
        aliases.append(alias.lower())
    if len(set(aliases)) != len(aliases):
        raise ValueError(f"duplicate alias in {aliases}")
    known = set(aliases)
    preds = []
    for a1, c1, a2, c2 in re.findall(r"\b(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)\b", s):
        a1, c1, a2, c2 = a1.lower(), c1.lower(), a2.lower(), c2.lower()
        if a1 in known and a2 in known and a1 != a2:
            preds.append((a1, c1, a2, c2))
    return aliases, preds


def join_graph(aliases, preds, implied):
    """-> adjacency bitmasks, one per alias index."""
    idx = {a: i for i, a in enumerate(aliases)}
    n = len(aliases)
    adj = [0] * n
    def link(x, y):
        adj[idx[x]] |= 1 << idx[y]
        adj[idx[y]] |= 1 << idx[x]
    for a1, _, a2, _ in preds:
        link(a1, a2)
    if implied:                                  # equivalence classes of columns, as PostgreSQL builds them
        parent = {}
        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for a1, c1, a2, c2 in preds:
            parent[find((a1, c1))] = find((a2, c2))
        classes = {}
        for col in list(parent):
            classes.setdefault(find(col), set()).add(col[0])
        for members in classes.values():
            ms = sorted(members)
            for i in range(len(ms)):
                for j in range(i + 1, len(ms)):
                    link(ms[i], ms[j])
    return adj


# ---------------- counting ----------------

def count(adj):
    n = len(adj)
    full = (1 << n) - 1
    nbr = {}                                     # connected set -> neighbours outside it
    for i in range(n):
        nbr[1 << i] = adj[i]
    # grow connected sets by size: every connected set of size k+1 = a connected set of size k + one neighbour
    frontier = list(nbr)
    while frontier:
        new = []
        for s in frontier:
            out = nbr[s] & ~s
            while out:
                b = out & -out
                out ^= b
                t = s | b
                if t not in nbr:
                    nb = 0
                    for i in range(n):
                        if t >> i & 1:
                            nb |= adj[i]
                    nbr[t] = nb & ~t
                    new.append(t)
        frontier = new
    for s in nbr:                                # neighbours outside the set only
        nbr[s] &= ~s

    order = sorted(nbr, key=lambda s: bin(s).count("1"))
    trees = {}                                   # bushy, no cross products
    leftdeep = {}                                # left-deep, no cross products
    steps = 0
    for s in order:
        if s & (s - 1) == 0:                     # single table
            trees[s] = 1
            leftdeep[s] = 1
            continue
        t = ld = 0
        sub = (s - 1) & s
        while sub:
            other = s ^ sub
            if sub in nbr and other in nbr and nbr[sub] & other:
                steps += 1
                t += trees[sub] * trees[other]
                if other & (other - 1) == 0:     # inner is one table
                    ld += leftdeep[sub]
            sub = (sub - 1) & s
        trees[s] = t
        leftdeep[s] = ld
    connected_full = full in nbr
    joins = n - 1
    return {
        "tables": n,
        "connected": connected_full,
        "sets_connected": len(nbr),
        "steps_nocross": steps,
        "steps_cross": 3 ** n - 2 ** (n + 1) + 1,
        "bushy_nocross": trees.get(full, 0),
        "bushy_cross": math.factorial(n) * math.comb(2 * joins, joins) // (joins + 1),
        "leftdeep_nocross": leftdeep.get(full, 0),
        "leftdeep_cross": math.factorial(n),
        "bushy_nocross_physical": trees.get(full, 0) * 3 ** joins,
        "bushy_cross_physical": math.factorial(n) * math.comb(2 * joins, joins) // (joins + 1) * 3 ** joins,
        "leftdeep_nocross_physical": leftdeep.get(full, 0) * 3 ** joins,
    }


# ---------------- optional: counts from our own traces ----------------

def trace_counts(q):
    out = {}
    f = f"traces/pg_{q}.json"
    if os.path.exists(f):
        s = json.load(open(f))["summary"]
        out["pg_sets_built"] = s.get("sets_built")
        out["pg_considered"] = s.get("considered")
        out["pg_precheck"] = s.get("pruned_precheck")
        out["pg_built"] = s.get("built")
        out["pg_retained"] = s.get("retained")
    for suffix in ["_nosort", "_nosort_nocross_exchange", "_nosort_topdown_nocross_exchange"]:
        f = f"traces/calcite_{q}{suffix}.json"
        if os.path.exists(f):
            t = json.load(open(f))
            out[f"calcite{suffix}_relnodes"] = t["summary"]["registered"]
            out[f"calcite{suffix}_tablesets"] = len({tuple(x["tables"]) for x in t["sets"]})
    return out


# ---------------- main ----------------

def fmt(x):
    if x is None:
        return "–"
    if isinstance(x, bool):
        return str(x)
    return f"{x:,}" if x < 10 ** 7 else f"{x:.2e}"


def main(argv):
    implied_only = "--implied" in argv
    files = [a for a in argv if not a.startswith("--")]
    queries = []                                 # (name, sql)
    if files:
        for f in files:
            queries.append((os.path.splitext(os.path.basename(f))[0], open(f).read()))
    else:
        for line in open("tools/queries.txt"):
            if "|" in line:
                name, sql = line.split("|", 1)
                queries.append((name.strip(), sql.strip()))

    graphs = [("pg", True)] if implied_only else [("written", False), ("pg", True)]
    rows = []
    for name, sql in queries:
        aliases, preds = parse(sql)
        for gname, implied in graphs:
            r = {"query": name, "graph": gname, "aliases": aliases}
            r.update(count(join_graph(aliases, preds, implied)))
            if gname == "pg" or len(graphs) == 1:
                r.update(trace_counts(name))
            rows.append(r)

    # drop the 'pg' row when inferred predicates add nothing (same counts as the written graph)
    keep = []
    for r in rows:
        if r["graph"] == "pg" and keep and keep[-1]["query"] == r["query"] and \
                keep[-1]["steps_nocross"] == r["steps_nocross"] and keep[-1]["bushy_nocross"] == r["bushy_nocross"]:
            keep[-1]["graph"] = "both"
            keep[-1].update({k: v for k, v in r.items() if k.startswith(("pg_", "calcite"))})
            continue
        keep.append(r)
    rows = keep

    cols = ["query", "graph", "tables", "sets_connected", "steps_nocross", "steps_cross", "bushy_nocross",
            "bushy_cross", "leftdeep_nocross", "bushy_nocross_physical", "bushy_cross_physical",
            "pg_sets_built", "pg_considered", "pg_precheck", "pg_retained",
            "calcite_nosort_relnodes", "calcite_nosort_nocross_exchange_relnodes"]
    cols = [c for c in cols if any(c in r for r in rows)]
    md = ["# Size of the whole join search space",
          "",
          "Generated by `tools/search_space_size.py`. graph = written: join predicates as written (Calcite's view);",
          "pg: plus predicates implied by equivalence classes (PostgreSQL's view); both: the two are the same.",
          "steps = ordered DP join steps (outer, inner); bushy/leftdeep = complete join trees, outer/inner kept apart;",
          "physical = x 3 join methods per join. nocross = no cross products anywhere.",
          "",
          "| " + " | ".join(cols) + " |",
          "| " + " | ".join("---" for _ in cols) + " |"]
    for r in rows:
        md.append("| " + " | ".join(fmt(r.get(c)) if c not in ("query", "graph") else r[c] for c in cols) + " |")
    os.makedirs("stats", exist_ok=True)
    tag = "" if not files else "_" + ("job" if len(files) > 1 else queries[0][0])
    open(f"stats/search_space_size{tag}.md", "w").write("\n".join(md) + "\n")
    json.dump(rows, open(f"stats/search_space_size{tag}.json", "w"), indent=1)
    print("\n".join(md))
    for r in rows:
        if not r["connected"]:
            print(f"WARNING {r['query']} ({r['graph']}): join graph not connected; check the parsed predicates",
                  file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
